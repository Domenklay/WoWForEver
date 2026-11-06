#!/usr/bin/env python3
"""Versioned server generations. Client files are read-only; old databases survive cutover.

plan -> prepare (fresh extraction) -> apply (quiesce, dump, isolated DB clone,
reviewed migrations, runtime checks, cutover). rollback retains post-cutover
progress in the new volume and a second dump. No database is reset in place.
"""
import argparse
import csv
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys

from server_release_catalog import release, digest, migration_body

spec = importlib.util.spec_from_file_location('release_clean', Path(__file__).with_name('clean-forever-server.py'))
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)
FORMAT = 'wowforever-server-upgrade-v1'
DATABASES = ('auth', 'world', 'characters', 'hotfixes')
RUNTIME = ('worldserver', 'bnetserver', 'web')


def direct(path):
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Use direct paths without symbolic links')
    return path.resolve(strict=True)


def inspect_client(selected, expected):
    selected = direct(selected)
    if selected.is_file():
        selected = selected.parent
    preferred = selected.name if selected.name in ('_forever_', '_classic_beta_') else None
    root = selected.parent if preferred else selected
    direct(root / 'Data/data')
    info = direct(root / '.build.info')
    rows = list(csv.reader(info.read_text(encoding='utf-8-sig').splitlines(), delimiter='|'))
    header = [key.split('!')[0] for key in rows[0]]
    candidates = []
    for product, folder, name in [('wowf', '_forever_', 'Wow.exe'), ('wow_classic_beta', '_classic_beta_', 'WowB.exe')]:
        if preferred and folder != preferred:
            continue
        active = [dict(zip(header, row)) for row in rows[1:] if len(row) == len(header)]
        active = [r for r in active if r.get('Product') == product and r.get('Active') == '1']
        exe = root / folder / name
        if len(active) != 1 or not exe.is_file():
            continue
        exe = direct(exe)
        # No --declared-build fallback: preloading must not masquerade as activation.
        actual = clean.executable_build(exe)
        if actual != expected:
            continue
        row = active[0]
        if row.get('Version') != f'1.60.1.{actual}':
            raise ValueError('EXE and active .build.info differ; finish activation in the source launcher')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', row.get('Build Key', '')):
            raise ValueError('Invalid active CASC build key')
        candidates.append(dict(source=str(root), test=str(root), game_dir=str(exe.parent),
                               product=product, exe_build=actual, exe_sha256=clean.sha_file(exe),
                               metadata_version=row['Version'], build_key=row['Build Key'].lower()))
    if len(candidates) != 1:
        raise ValueError(f'Expected one activated 1.60.1.{expected} EXE. Preload files or a 70658 copy are insufficient')
    return candidates[0]


def checked_state(root):
    return clean.load_state(direct(root) / 'state.json')


def original_unchanged(plan):
    if (Path(plan['root']) / '.upgrade-in-progress.json').exists():
        raise ValueError('Recover the unfinished upgrade before starting another operation')
    state = checked_state(Path(plan['root']))
    if digest(state) != plan['before_digest'] or clean.sha_file(Path(state['compose'])) != plan['compose_digest']:
        raise ValueError('Active server changed since planning; create a new plan')
    return state


def client_unchanged(plan):
    current = inspect_client(Path(plan['client']['game_dir']), plan['descriptor']['client_build'])
    if current != plan['client']:
        raise ValueError('Client identity changed after planning; do not merge different builds')


def checkpoint(plan, phase):
    plan['phase'] = phase
    clean.write_private(Path(plan['directory']) / 'plan.json', plan)
    print('Upgrade phase: ' + phase, flush=True)


def load_plan(path):
    path = direct(path)
    plan = json.loads(path.read_text())
    if plan.get('format') != FORMAT or Path(plan['directory']) != path.parent:
        raise ValueError('Upgrade plan identity mismatch')
    root = direct(Path(plan['root']))
    if path.parent.parent != root / 'upgrades' or not re.fullmatch(r'[0-9a-f]{12}', path.parent.name):
        raise ValueError('Plan must belong to this clean installation')
    if release(plan['descriptor']['id']) != plan['descriptor']:
        raise ValueError('Reviewed release changed; use a fresh plan')
    if digest(plan['before']) != plan['before_digest'] or hashlib.sha256(plan['old_compose_text'].encode()).hexdigest() != plan['compose_digest']:
        raise ValueError('Previous generation snapshot changed')
    target = plan['target']
    if (target['project'] != 'forever-clean-r-' + path.parent.name or target['project'] == plan['before']['project'] or
        target['root'] != str(root) or target['compose'] != str(path.parent / 'compose.private.json') or
        target['data_directory'] != str(path.parent / 'data') or target['release'] != plan['descriptor']['id'] or
        target['client'] != plan['client'] or target['core'] != plan['descriptor']['core']):
        raise ValueError('Staging generation escaped its plan')
    return plan


def plan_upgrade(root, client, identifier):
    root = direct(root)
    if (root / '.upgrade-in-progress.json').exists():
        raise ValueError('Recover the unfinished upgrade before planning another release')
    before = checked_state(root)
    if before['phase'] != 'ready':
        raise ValueError('Finish the current database initialization before upgrading')
    descriptor = release(identifier)
    if before['client']['exe_build'] not in descriptor['from_builds']:
        raise ValueError('This release does not define an upgrade from the active client build')
    database = before.get('database_version', 'pristine-' + before['core'][:12])
    if database != descriptor['database']['from']:
        raise ValueError('Database version is outside the reviewed migration chain')
    identity = inspect_client(client, descriptor['client_build'])
    if identity['product'] not in descriptor['products']:
        raise ValueError('Client product is not supported by this release')
    # State, snapshots, dumps and extraction must never be under client storage.
    source = Path(identity['source'])
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('Server releases and owned client storage must be separate')
    ident = secrets.token_hex(6)
    parent = root / 'upgrades'
    if parent.is_symlink():
        raise ValueError('Linked upgrade directory is unsupported')
    parent.mkdir(exist_ok=True, mode=0o700)
    folder = parent / ident
    folder.mkdir(mode=0o700)
    target = json.loads(json.dumps(before))
    target.update(project='forever-clean-r-' + ident, release=descriptor['id'], core=descriptor['core'],
                  client=identity, data_directory=str(folder / 'data'), extraction=str(folder / 'data'),
                  compose=str(folder / 'compose.private.json'), database_version=descriptor['database']['to'])
    if target['core'] != before['core']:
        target['image'] = 'forever-trinitycore:release-' + target['core'][:12]
    value = dict(format=FORMAT, root=str(root), directory=str(folder), descriptor=descriptor, client=identity,
                 before=before, before_digest=digest(before), compose_digest=clean.sha_file(Path(before['compose'])),
                 old_compose=json.loads(Path(before['compose']).read_text()), target=target,
                 old_compose_text=Path(before['compose']).read_text(),
                 old_control=(root / 'server.sh').read_text(), phase='planned')
    checkpoint(value, 'planned')
    clean.write_private(root / 'upgrade-last-plan.json', dict(plan=str(folder / 'plan.json')))
    print('Plan: ' + str(folder / 'plan.json'))
    print('Client/core/data/database versions are tracked separately. Old data and DB volume will be retained.')
    return value


def image_identity(state):
    values = json.loads(clean.run(['docker', 'image', 'inspect', state['image']], capture=True))
    labels = values[0].get('Config', {}).get('Labels', {})
    if labels.get('org.wowforever.core') != state['core'] or labels.get('org.wowforever.advancement') != 'none':
        raise ValueError('Expected the pinned pristine core image without gameplay modules')


def prepare(plan, jobs=2):
    original_unchanged(plan)
    client_unchanged(plan)
    if plan['phase'] == 'prepared':
        return
    if plan['phase'] not in ('planned', 'extracting'):
        raise ValueError('This plan is not available for preparation')
    target = plan['target']
    if target['core'] != plan['before']['core']:
        clean.run(['docker', 'build', '--progress=plain', '-f', str(clean.ROOT / 'docker/clean/Dockerfile'),
                   '--build-arg', 'TC_COMMIT=' + target['core'], '--build-arg', f'BUILD_JOBS={jobs}',
                   '-t', target['image'], str(clean.ROOT)])
    image_identity(target)
    output = Path(target['data_directory'])
    marker = output / '.clean-extraction.json'
    identity = dict(core=target['core'], exe_sha256=target['client']['exe_sha256'], build_key=target['client']['build_key'])
    complete = marker.is_file() and json.loads(marker.read_text()) == identity
    if output.exists() and not complete:
        if output.is_symlink():
            raise ValueError('Linked extraction is unsupported')
        output.rename(output.with_name('partial-' + secrets.token_hex(6)))
    if not complete:
        if shutil.disk_usage(Path(plan['root'])).free < 15 * 1024**3:
            raise ValueError('At least 15 GiB free is required for separate extracted data')
        output.mkdir(mode=0o700)
        clean.configure_compose(target)
        before = clean.storage_stamp(Path(plan['client']['source']))
        checkpoint(plan, 'extracting')
        clean.compose(target, '--profile', 'setup', 'run', '--rm', '--no-deps',
                      '-e', 'FOREVER_CASC_PRODUCT=' + plan['client']['product'], 'extractor')
        if clean.storage_stamp(Path(plan['client']['source'])) != before:
            raise RuntimeError('Client storage changed during extraction; close the game and source launcher')
        client_unchanged(plan)
        clean.write_private(marker, identity)
    clean.ensure_game_tables(target)
    clean.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
               '--mount', 'type=bind,source=' + str(output) + ',target=/output,readonly',
               '--mount', 'type=bind,source=' + str(clean.ROOT / 'docker/clean/extract.sh') + ',target=/validate.sh,readonly',
               '--entrypoint', 'bash', target['image'], '/validate.sh', '--validate-only', '/output'])
    checkpoint(plan, 'prepared')


def dump_databases(state, destination):
    """Stream a checked logical backup to a private gzip file, without buffering DBs in RAM."""
    item = clean.container(state, 'mysql')
    if not item or not item['State']['Running']:
        raise RuntimeError('MySQL must be running for the database snapshot')
    partial = destination.with_suffix(destination.suffix + '.partial')
    if destination.exists() or partial.exists() or partial.is_symlink():
        raise ValueError('A backup is never overwritten')
    command = ['docker', 'exec', item['Id'], 'sh', '-c',
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction '
               '--routines --triggers --events --hex-blob --set-gtid-purged=OFF --databases auth world characters hotfixes']
    with partial.open('xb') as output, subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        os.chmod(partial, 0o600)
        try:
            with gzip.GzipFile(fileobj=output, mode='wb') as compressed:
                while block := process.stdout.read(1024 * 1024):
                    compressed.write(block)
            if process.wait() != 0:
                raise RuntimeError('Database dump failed; private SQL output was not printed')
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            process.kill()
            process.wait()
            raise
    if partial.stat().st_size < 32:
        raise RuntimeError('Empty database snapshot')
    partial.replace(destination)
    return clean.sha_file(destination)


def restore_databases(state, source, expected):
    if clean.sha_file(source) != expected:
        raise ValueError('Backup checksum mismatch')
    item = clean.container(state, 'mysql')
    if not item or item['Config']['Labels']['com.docker.compose.project'] != state['project']:
        raise ValueError('Clone ownership mismatch')
    command = ['docker', 'exec', '-i', item['Id'], 'sh', '-c',
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --binary-mode=1']
    with gzip.open(source, 'rb') as stream, subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            while block := stream.read(1024 * 1024):
                process.stdin.write(block)
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError('Restoring isolated database clone failed')
        except BaseException:
            process.kill()
            process.wait()
            raise


def snapshot(state):
    counts = clean.sql(state, 'SELECT COUNT(*) FROM auth.battlenet_accounts; SELECT COUNT(*) FROM auth.account; '
                       'SELECT COUNT(*) FROM characters.characters;\n').split()
    if len(counts) != 3 or not all(v.isdecimal() for v in counts):
        raise ValueError('Account/character snapshot failed')
    schema = clean.sql(state, "SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,"
                       "COALESCE(COLUMN_DEFAULT,'<NULL>'),EXTRA FROM information_schema.COLUMNS "
                       "WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes') "
                       'ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION;\n')
    return dict(counts=counts, schema_sha256=digest(schema))


def stop_running(state):
    running = [s for s in RUNTIME if (item := clean.container(state, s)) and item['State']['Running']]
    return running


def control_text(root):
    return '#!/bin/sh\nexec python3 ' + shlex.quote(str(clean.ROOT / 'scripts/clean-forever-server.py')) + ' "$@" --root ' + shlex.quote(str(root)) + '\n'


def private_text(path, body, mode=0o600):
    pending = path.with_name(path.name + '.pending-' + secrets.token_hex(6))
    try:
        with pending.open('x') as stream:
            os.chmod(pending, mode)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        if pending.exists(): pending.unlink()


def publish(plan):
    target = json.loads(json.dumps(plan['target']))
    target['compose'] = str(Path(plan['root']) / 'compose.private.json')
    target['phase'] = 'ready'
    clean.configure_compose(target, published=True)
    clean.compose(target, 'up', '-d', '--no-build', *clean.SERVICES)
    clean.wait_world(target, 180)
    # TLS checks run in the known core image, not in the MySQL image.
    clean.compose(target, 'run', '--rm', '--no-deps', '--entrypoint', 'python3', 'bnetserver', '-c',
                  clean.TLS_PROBE.replace('/certs/ca/', '/opt/trinitycore/certs/ca/'))
    clean.save(target)
    control = Path(plan['root']) / 'server.sh'
    private_text(control, control_text(Path(plan['root'])), 0o700)
    return target


def recover_previous(plan):
    root = Path(plan['root'])
    marker = root / '.upgrade-in-progress.json'
    if marker.exists() and json.loads(marker.read_text()).get('plan') != str(Path(plan['directory']) / 'plan.json'):
        raise ValueError('A different upgrade owns the lifecycle marker')
    # Stop only this generation, whether ports were published yet or not.
    clean.compose(plan['target'], 'stop', *RUNTIME)
    active = root / 'compose.private.json'
    private_text(active, plan['old_compose_text'])
    clean.save(plan['before'])
    if plan.get('previous_running'):
        clean.compose(plan['before'], 'up', '-d', '--no-build', *plan['previous_running'])
    if marker.exists(): marker.unlink()
    private_text(root / 'server.sh', plan['old_control'], 0o700)


def apply(plan):
    before = original_unchanged(plan)
    client_unchanged(plan)
    if plan['phase'] != 'prepared':
        raise ValueError('Prepare extraction first. Interrupted applies require recover, then a fresh plan')
    image_identity(plan['target'])
    folder = Path(plan['directory'])
    marker = Path(plan['target']['data_directory']) / '.clean-extraction.json'
    if json.loads(marker.read_text()) != dict(core=plan['target']['core'], exe_sha256=plan['client']['exe_sha256'], build_key=plan['client']['build_key']):
        raise ValueError('Extraction identity mismatch')
    plan['previous_running'] = stop_running(before)
    checkpoint(plan, 'quiescing')
    private_text(Path(plan['root']) / 'server.sh', control_text(Path(plan['root'])), 0o700)
    clean.write_private(Path(plan['root']) / '.upgrade-in-progress.json', dict(plan=str(folder / 'plan.json')))
    try:
        clean.compose(before, 'stop', *RUNTIME)
        clean.compose(before, 'up', '-d', '--wait', 'mysql')
        size = int(clean.sql(before, "SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES "
                             "WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes');\n").strip())
        if shutil.disk_usage(folder).free < max(1024**3, 2 * size):
            raise ValueError('Insufficient space for a retained database snapshot and clone')
        baseline = snapshot(before)
        plan['database_snapshot'] = baseline
        backup = folder / 'databases-before.sql.gz'
        plan['backup_sha256'] = dump_databases(before, backup)
        checkpoint(plan, 'backed-up')
        # Pin the clone to the exact running MySQL image, avoiding an implicit version jump.
        plan['target']['mysql_image'] = clean.container(before, 'mysql')['Image']
        clean.configure_compose(plan['target'])
        clean.compose(plan['target'], 'up', '-d', '--wait', 'mysql')
        restore_databases(plan['target'], backup, plan['backup_sha256'])
        if snapshot(plan['target']) != baseline:
            raise RuntimeError('Restored database clone differs in schema or account/character counts')
        checkpoint(plan, 'cloned')
        for migration in plan['descriptor']['database']['migrations']:
            clean.sql(plan['target'], 'USE `' + migration['database'] + '`;\n' + migration_body(migration))
        build = plan['descriptor']['client_build']
        clean.sql(plan['target'], f'INSERT INTO auth.build_info (build,majorVersion,minorVersion,bugfixVersion,hotfixVersion) '
                  f'VALUES ({build},1,60,1,NULL) ON DUPLICATE KEY UPDATE majorVersion=1,minorVersion=60,bugfixVersion=1;\n'
                  f'UPDATE auth.realmlist SET gamebuild={build},flag=flag|2 WHERE id=70;\n')
        clean.compose(plan['target'], 'up', '-d', '--no-build', 'worldserver', 'bnetserver')
        clean.wait_world(plan['target'], 180)
        after = snapshot(plan['target'])
        if after['counts'] != baseline['counts']:
            raise RuntimeError('Account or character counts changed during offline migration')
        if not plan['descriptor']['database']['migrations'] and after['schema_sha256'] != baseline['schema_sha256']:
            raise RuntimeError('Unexpected schema change in a client-only release')
        plan['database_after'] = after
        checkpoint(plan, 'verified')
        publish(plan)
        checkpoint(plan, 'active')
        (Path(plan['root']) / '.upgrade-in-progress.json').unlink()
        print(f"ACTIVE RELEASE {plan['descriptor']['id']}; realm 70; old database volume and extracted data retained.")
    except Exception:
        checkpoint(plan, 'recovering')
        recover_previous(plan)
        checkpoint(plan, 'failed-recovered')
        raise


def rollback(plan):
    current = checked_state(Path(plan['root']))
    if plan['phase'] == 'active' or (plan['phase'] in ('verified', 'rolling-back', 'rollback-snapshotted') and current.get('project') == plan['target']['project']):
        if current.get('project') != plan['target']['project']:
            raise ValueError('Only the currently active generation can be rolled back')
        checkpoint(plan, 'rolling-back')
        clean.write_private(Path(plan['root']) / '.upgrade-in-progress.json', dict(plan=str(Path(plan['directory']) / 'plan.json')))
        clean.compose(current, 'stop', *RUNTIME)
        # Preserve progress made after cutover before returning to the earlier snapshot.
        after = Path(plan['directory']) / ('databases-after-' + secrets.token_hex(6) + '.sql.gz')
        plan['rollback_backup_sha256'] = dump_databases(current, after)
        plan['rollback_backup_file'] = str(after)
        checkpoint(plan, 'rollback-snapshotted')
    elif plan['phase'] not in ('quiescing', 'backed-up', 'cloned', 'verified', 'recovering', 'rolling-back', 'rollback-snapshotted'):
        raise ValueError('No interrupted or active upgrade to recover')
    elif digest(current) != plan['before_digest']:
        raise ValueError('Active state changed outside this upgrade')
    recover_previous(plan)
    checkpoint(plan, 'rolled-back')
    print('Previous generation restored. New volume and all dumps retained; post-upgrade progress is in the new snapshot.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'apply', 'rollback', 'status'))
    parser.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    parser.add_argument('--client', type=Path)
    parser.add_argument('--release', default='forever-1.60.1.70707')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=2)
    args = parser.parse_args()
    os.umask(0o077)
    lock_dir = Path.home() / '.cache'
    lock_dir.mkdir(exist_ok=True)
    with (lock_dir / 'forever-clean-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'plan':
            if args.client is None:
                parser.error('--client is required for plan')
            plan_upgrade(args.root, args.client, args.release)
        else:
            if args.plan is None:
                pointer = direct(args.root) / 'upgrade-last-plan.json'
                if not pointer.is_file():
                    parser.error('Run plan first, or provide --plan for an existing upgrade')
                args.plan = Path(json.loads(pointer.read_text())['plan'])
            plan = load_plan(args.plan)
            if Path(plan['root']) != args.root.resolve():
                raise ValueError('The upgrade plan belongs to another server root')
            if args.action == 'prepare': prepare(plan, args.jobs)
            elif args.action == 'apply': apply(plan)
            elif args.action == 'rollback': rollback(plan)
            else: print(json.dumps(dict(phase=plan['phase'], release=plan['descriptor']['id'], client=plan['client'],
                                       backup=plan.get('backup_sha256')), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Upgrade stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
