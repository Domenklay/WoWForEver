#!/usr/bin/env python3
"""Install the existing Ascension module on ready 70658, retaining DBs, resources and TLS."""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import module_readiness

ROOT = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

network = module('advancement_network', 'repair-clean-network.py')
clean = network.clean
upgrade = module('advancement_snapshot', 'upgrade-forever-server.py')
upgrade.clean = clean
VERSION = '1.12.0'
FORMAT = 'forever-clean-advancement-v1'
OWN_SCRIPTS = ('spell_forever_subclass', 'spell_forever_advancement',
               'spell_forever_custom_mana_shield', 'aura_forever_custom_mana_shield')
MARKER = '.advancement-in-progress.json'
CURRENT_ROOT = None

def source_id():
    paths = sorted((ROOT / 'mods/forever-advancement/server').glob('*'))
    paths += sorted((ROOT / 'mods/forever-advancement/sql').glob('*.sql'))
    paths += [ROOT / p for p in ['scripts/inject-advancement.py', 'docker/clean/entrypoint.py',
              'docker/advancement/Dockerfile', 'docker/patches/0004-forever-subclass-server-addon-endpoint.patch']]
    value = hashlib.sha256()
    for path in paths:
        value.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    return value.hexdigest()


def image(name):
    return json.loads(clean.run(['docker', 'image', 'inspect', name], capture=True))[0]


def check_image(item, state, advanced=False):
    labels = item.get('Config', {}).get('Labels', {})
    expected = VERSION if advanced else 'none'
    if labels.get('org.wowforever.core') != state['core'] or labels.get('org.wowforever.advancement') != expected:
        raise ValueError('Image does not match the pinned 70658 core and requested gameplay module')
    if advanced and labels.get('org.wowforever.advancement.source') != source_id():
        raise ValueError('Candidate Advancement source differs from the reviewed source')


def build(state, jobs):
    old = image(state['image']); check_image(old, state)
    build_tag = 'forever-trinitycore:advancement-build-base-' + state['core'][:12]
    runtime_tag = 'forever-trinitycore:before-advancement-' + old['Id'].split(':')[-1][:12]
    clean.run(['docker', 'tag', old['Id'], runtime_tag])
    clean.run(['docker', 'build', '--progress=plain', '--target', 'build', '-f', str(ROOT / 'docker/clean/Dockerfile'),
               '--build-arg', 'TC_COMMIT=' + state['core'], '--build-arg', f'BUILD_JOBS={jobs}',
               '-t', build_tag, str(ROOT)])
    candidate = 'forever-trinitycore:ascension-70658-' + source_id()[:12]
    clean.run(['docker', 'build', '--progress=plain', '-f', str(ROOT / 'docker/advancement/Dockerfile'),
               '--build-arg', 'CLEAN_BUILD_IMAGE=' + build_tag, '--build-arg', 'CLEAN_RUNTIME_IMAGE=' + runtime_tag,
               '--build-arg', 'ADVANCEMENT_SOURCE=' + source_id(), '--build-arg', f'BUILD_JOBS={jobs}',
               '-t', candidate, str(ROOT)])
    check_image(image(candidate), state, True)
    return candidate


def sql_quote(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "''") + "'"


def bindings(state):
    rows = clean.sql(state, 'SELECT spell_id,ScriptName FROM world.spell_script_names WHERE ScriptName IN ('
                     + ','.join(map(sql_quote, OWN_SCRIPTS)) + ') ORDER BY spell_id,ScriptName;\n')
    result = []
    for row in rows.splitlines():
        number, name = row.split('\t')
        if not number.isdecimal() or name not in OWN_SCRIPTS: raise ValueError('Unexpected owned script binding')
        result.append([int(number), name])
    return result


def restore_bindings(state, rows):
    body = 'START TRANSACTION; DELETE FROM world.spell_script_names WHERE ScriptName IN (' + ','.join(map(sql_quote, OWN_SCRIPTS)) + ');\n'
    for number, name in rows:
        if not isinstance(number, int) or name not in OWN_SCRIPTS: raise ValueError('Invalid saved binding')
        body += f'INSERT INTO world.spell_script_names (spell_id,ScriptName) VALUES ({number},{sql_quote(name)});\n'
    clean.sql(state, body + 'COMMIT;\n')


def checkpoint(record, phase):
    record['phase'] = phase
    clean.write_private(Path(record['directory']) / 'install.json', record)
    print('Ascension: ' + phase, flush=True)


def configure(before, model, candidate, directory):
    state = copy.deepcopy(before)
    state.update(image=candidate, database_version='advancement-1.12.0@' + before.get('database_version', 'pristine-' + before['core'][:12]))
    state['advancement'] = dict(version=VERSION, protocol=3, source_sha256=source_id(), backup=str(directory / 'install.json'))
    model = copy.deepcopy(model)
    world = model['services']['worldserver']
    world['image'] = candidate
    world['environment'].update(FOREVER_ADVANCEMENT_ENABLED='1', FOREVER_RELEASE_MANAGED='1')
    # The candidate contains its reviewed entrypoint. Do not mask it with an old
    # read-only helper from a previous checkout; all data/cert mounts stay intact.
    world['volumes'] = [m for m in world.get('volumes', []) if not isinstance(m, dict) or m.get('target') != '/usr/local/bin/forever-clean-entrypoint.py']
    return state, model


def ready_patterns(state):
    version=state.get('advancement',{}).get('version',VERSION)
    detail='1 canonical abilities' if version=='1.11.0' else '0 visible abilities'
    return ('ForeverAdvancement ready:', 'ForeverAdvancement custom rules: '+detail+'; protocol=3; version='+version)

READY_PATTERNS = ready_patterns({})


def wait_module(state, timeout=180):
    return module_readiness.wait(clean, state, ready_patterns(state), timeout)


def load_backup(root, path):
    path = upgrade.direct(path)
    if path.parent.parent != root / 'advancement' or not re.fullmatch('[0-9a-f]{12}', path.parent.name):
        raise ValueError('Backup must belong to this clean server')
    record = json.loads(path.read_text())
    if (record.get('format') != FORMAT or record['root'] != str(root) or record['directory'] != str(path.parent)
        or record['before']['root'] != str(root) or record['before']['compose'] != str(root / 'compose.private.json')
        or upgrade.digest(record['before']) != record['before_digest']
        or hashlib.sha256(record['compose_before'].encode()).hexdigest() != record['compose_digest']):
        raise ValueError('Backup identity or checksum mismatch')
    return record


def rollback(record):
    root = Path(record['root']); marker = root / MARKER
    if marker.exists() and json.loads(marker.read_text()).get('backup') != str(Path(record['directory']) / 'install.json'):
        raise ValueError('Another module installation owns the recovery marker')
    current = clean.load_state(root / 'state.json')
    if current.get('advancement') and current['advancement'].get('backup') != str(Path(record['directory']) / 'install.json'):
        raise ValueError('Another Advancement installation is active')
    if not current.get('advancement') and upgrade.digest(current) != record['before_digest']:
        raise ValueError('Active server changed outside this installation')
    if record['phase'] in ('rolled-back', 'failed-recovered'):
        return
    check_image(image(record['before']['image']), record['before'])
    clean.compose(current, 'stop', 'web', 'bnetserver', 'worldserver')
    if record.get('sql_changed'):
        restore_bindings(record['before'], record['bindings_before'])
    # Keep all character progress and new Advancement tables. Full database
    # restore is deliberately never used for module rollback.
    upgrade.private_text(root / 'compose.private.json', record['compose_before'])
    clean.save(record['before'])
    upgrade.private_text(root / 'server.sh', record['control_before'], 0o700)
    if record['previous_running']:
        clean.compose(record['before'], 'up', '-d', '--no-build', '--no-deps', *record['previous_running'])
        clean.wait_world(record['before'], 180)
    marker.unlink(missing_ok=True)
    checkpoint(record, 'rolled-back')


def install(root, jobs):
    if (root / '.gameplay-in-progress.json').exists():
        raise ValueError('Recover the interrupted gameplay install with enable-clean-gameplay.py first')
    if (root / MARKER).exists():
        raise ValueError('An interrupted Advancement install needs rollback; see ' + str(root / MARKER))
    before = network.checked(root)
    if before.get('advancement'):
        if before['advancement']['source_sha256'] != source_id(): raise ValueError('A different module revision is active; use its reviewed update path')
        wait_module(before); print('Ascension is already active; no changes.'); return
    if before['core'] != clean.CORE: raise ValueError('This module release requires the current pinned 70658 core')
    model_text = Path(before['compose']).read_text(); model = json.loads(model_text)
    world = model['services']['worldserver']
    if model.get('name') != before['project'] or world.get('image') != before['image'] or world.get('command') != ['worldserver']:
        raise ValueError('Unexpected owned worldserver configuration')
    clean.wait_world(before, 60)
    candidate = build(before, jobs)  # No services stopped until both builds succeed.
    if clean.load_state(root / 'state.json') != before or Path(before['compose']).read_text() != model_text:
        raise ValueError('Active installation changed during compilation')
    folder = root / 'advancement' / os.urandom(6).hex(); upgrade.direct(root)
    if folder.parent.is_symlink(): raise ValueError('Linked backup directory is unsupported')
    folder.mkdir(parents=True, mode=0o700)
    target, target_model = configure(before, model, candidate, folder)
    record = dict(format=FORMAT, root=str(root), directory=str(folder), before=before, before_digest=upgrade.digest(before),
                  compose_before=model_text, compose_digest=hashlib.sha256(model_text.encode()).hexdigest(),
                  control_before=(root / 'server.sh').read_text(), target=target,
                  previous_running=upgrade.stop_running(before), sql_changed=False)
    checkpoint(record, 'prepared')
    clean.write_private(root / MARKER, dict(backup=str(folder / 'install.json')))
    try:
        clean.compose(before, 'stop', 'web', 'bnetserver', 'worldserver')
        checkpoint(record, 'stopped')
        size = int(clean.sql(before, "SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes');\n").strip())
        if shutil.disk_usage(folder).free < max(1024**3, size): raise ValueError('Insufficient free space for a private four-database backup')
        record['snapshot'] = upgrade.snapshot(before)
        record['bindings_before'] = bindings(before)
        print('Saving private snapshot of auth/world/characters/hotfixes; do not interrupt...', flush=True)
        record['database_sha256'] = upgrade.dump_databases(before, folder / 'databases-before.sql.gz')
        checkpoint(record, 'backed-up')
        record['sql_changed'] = True; checkpoint(record, 'migrating')
        for database in ('characters', 'world'):
            clean.sql(before, 'USE `' + database + '`;\n' + (ROOT / 'mods/forever-advancement/sql' / (database + '.sql')).read_text())
        clean.write_private(Path(before['compose']), target_model)
        clean.compose(target, 'config', '-q')
        clean.compose(target, 'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver')
        wait_module(target)
        if upgrade.snapshot(target)['counts'] != record['snapshot']['counts']:
            raise RuntimeError('Account/character counts changed unexpectedly')
        clean.save(target)
        upgrade.private_text(root / 'server.sh', upgrade.control_text(root), 0o700)
        if record['previous_running']:
            clean.compose(target, 'up', '-d', '--no-build', '--no-deps', *record['previous_running'])
        checkpoint(record, 'active')
        (root / MARKER).unlink()
        print('ASCENSION ACTIVE: 70658, protocol 3, version 1.12.0. Accounts, characters, resources and CA retained.')
        print('Backup/rollback record: ' + str(folder / 'install.json'))
    except Exception as original:
        try:
            rollback(record); checkpoint(record, 'failed-recovered')
        except Exception as recovery:
            raise RuntimeError('Installation failed: ' + network.command_error(before, original) + '\nRecovery also failed: '
                               + network.command_error(before, recovery) + '\nBackup: ' + str(folder / 'install.json')) from original
        raise


def main():
    global CURRENT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'rollback'))
    parser.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=2)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args(); os.umask(0o077); root = upgrade.direct(args.root); CURRENT_ROOT = root
    if args.action == 'status':
        state = network.checked(root)
        if state.get('advancement'): wait_module(state)
        else: clean.wait_world(state, 30)
        print(json.dumps(dict(build=70658, advancement=state.get('advancement'), databases_reset=False), indent=2)); return
    lock_path = Path.home() / '.cache/forever-clean-control.lock'; lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another clean-server operation is running')
        if args.action == 'install': install(root, args.jobs)
        elif args.backup: rollback(load_backup(root, args.backup))
        else: parser.error('--backup is required for rollback')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        try: state = clean.load_state(CURRENT_ROOT / 'state.json'); detail = network.command_error(state, error)
        except Exception: detail = str(error)
        print('Ascension setup stopped: ' + detail, file=sys.stderr); raise SystemExit(1)
