#!/usr/bin/env python3
"""Build the pinned Forever core and test it against an isolated copy of an existing server."""
import argparse
import copy
import fcntl
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CORE = 'b6ae12c227ef00bfe24fdaf16fba28acc61a5b7f'
PROJECT = 'forever-refresh-70658'
SERVICES = ('mysql', 'worldserver', 'bnetserver', 'web')
GAME_SERVICES = ('web', 'bnetserver', 'worldserver')
MYSQL = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot '
DUMP = ('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction '
        '--quick --routines --events --triggers --no-tablespaces --set-gtid-purged=OFF '
        '--databases auth characters world hotfixes')


def run(args, *, capture=False, data=None):
    # Compose's resolved configuration contains passwords; only callers may inspect it.
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode:
        # Do not echo arbitrary Compose errors: they can include interpolated secrets.
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]) +
                           ' (details withheld because configuration may contain passwords)')
    return result.stdout if capture else ''


def private_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temp.replace(path)


def compose_file(state):
    return ['docker', 'compose', '-p', state['project'], '-f', state['compose']]


def old_compose(directory):
    return ['docker', 'compose', '--project-directory', str(directory)]


def inspect(container):
    return json.loads(run(['docker', 'inspect', container], capture=True))[0]


def isolated_model(original, images, image, project):
    """Keep resolved local mounts/settings, but give every writable volume/network a new name."""
    model = copy.deepcopy(original)
    model['name'] = project
    model.pop('include', None)
    for kind in ('volumes', 'networks'):
        for name, value in model.get(kind, {}).items():
            if value and (value.get('external') or value.get('driver_opts')):
                raise ValueError('External/shared storage or network requires a separate migration: ' + name)
            if value:
                value.pop('name', None)
    model['services'] = {name: model['services'][name] for name in SERVICES}
    for name, service in model['services'].items():
        if service.get('container_name') or service.get('network_mode'):
            raise ValueError('Custom container_name/network_mode is not supported: ' + name)
        service.pop('profiles', None)
        service.pop('build', None)
        service['image'] = image if name in ('worldserver', 'bnetserver') else images[name]
        service['pull_policy'] = 'never'
        environment = service.get('environment', {})
        if name != 'mysql' and environment.get('DB_HOST', 'mysql') != 'mysql':
            raise ValueError('A database outside the isolated mysql service is not supported: ' + name)
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind':
                # Existing client data, certificates, overrides and downloads are shared read-only.
                if name == 'mysql' and mount['target'] == '/var/lib/mysql':
                    raise ValueError('A bind-mounted MySQL data directory cannot be isolated automatically')
                mount['read_only'] = True
                mount.setdefault('bind', {})['create_host_path'] = False
                if mount['target'] == '/opt/trinitycore/overrides':
                    source = Path(mount['source'])
                    for filename in ('worldserver.conf', 'bnetserver.conf'):
                        config = source / filename
                        if config.is_file() and re.search(r'^\s*\w*DatabaseInfo\s*=', config.read_text(), re.M):
                            raise ValueError('Database connection overrides require manual isolation: ' + filename)
        if name == 'mysql':
            mounts = [m for m in service.get('volumes', []) if m['target'] == '/var/lib/mysql']
            if len(mounts) != 1 or mounts[0]['type'] != 'volume':
                raise ValueError('Expected a named MySQL data volume')
    world = model['services']['worldserver'].setdefault('environment', {})
    # This revision natively knows 70658. Do not delete its build_info/auth-key rows using CLIENT_BUILD.
    world.update(CLIENT_BUILD='', ADVANCEMENT_ENABLED='1', SUBCLASS_ENABLED='0', SUBCLASS_FREEPICK='0')
    model['services']['web'].setdefault('environment', {})['GAME_VERSION'] = '1.60.1.70658'
    # `config --format json` already escapes literal dollars for reuse as a
    # Compose file. Preserve those escapes, including passwords and healthchecks.
    return model


def db_sql(container, database, sql, *, capture=False):
    if database not in ('', 'auth', 'world', 'characters', 'hotfixes'):
        raise ValueError('Unknown database')
    return run(['docker', 'exec', '-i', container, 'sh', '-c', MYSQL + database],
               data=sql, capture=capture)


def dump_database(container, path):
    partial = path.with_suffix('.partial')
    with partial.open('wb') as target:
        os.chmod(partial, 0o600)
        process = subprocess.Popen(['docker', 'exec', container, 'sh', '-c', DUMP],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with gzip.GzipFile(fileobj=target, mode='wb') as compressed:
                shutil.copyfileobj(process.stdout, compressed, 1024 * 1024)
        finally:
            process.stdout.close()
            code = process.wait()
    if code:
        raise RuntimeError('Database backup failed; original databases have not been changed')
    # Read to EOF to validate CRC before any candidate database is imported.
    with gzip.open(partial, 'rb') as check:
        while check.read(1024 * 1024):
            pass
    partial.replace(path)


def import_database(container, path):
    process = subprocess.Popen(['docker', 'exec', '-i', container, 'sh', '-c', MYSQL],
                               stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with gzip.open(path, 'rb') as source:
            shutil.copyfileobj(source, process.stdin, 1024 * 1024)
        process.stdin.close()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if process.wait():
        raise RuntimeError('Import into the new, isolated database failed')


def wait_mysql(container, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(['docker', 'exec', container, 'sh', '-c', MYSQL + '-e "SELECT 1"'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError('New MySQL did not become ready')


def preflight(old):
    logs = run(['docker', 'logs', '--tail=15000', old['worldserver']['Id']], capture=True)
    # Both a ready server and the known custom-schema crash occur AFTER initial import.
    # Never stop a server whose first import has not finished.
    initialized = 'World initialized' in logs or re.search(r'worldserver-daemon.*ready', logs)
    up_to_date = all(re.search(name + r' database is up.to.date', logs, re.I)
                     for name in ('Characters?', 'World', 'Hotfixes'))
    if not (initialized or up_to_date):
        raise RuntimeError('Initial database import is not confirmed complete; old services were not stopped')
    result = db_sql(old['mysql']['Id'], '',
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='updates' "
                    "AND table_schema IN ('auth','characters','world','hotfixes');\n", capture=True)
    if result.strip().splitlines()[-1:] != ['4']:
        raise RuntimeError('All four initialized databases are required')
    db_sql(old['mysql']['Id'], 'world', 'SELECT core_version FROM version LIMIT 1;\n', capture=True)


def restore_old(state):
    # Stop the clone before releasing the old ports. Never delete a database or volume.
    run(compose_file(state) + ['stop', *GAME_SERVICES, 'mysql'])
    if state.get('addon_installed') and (Path(state['backup']) / 'addon/advancement-addon.json').is_file():
        addon_module().restore(Path(state['backup']) / 'addon')
        state['addon_installed'] = False
    if state.get('old_stopped'):
        for name in ('worldserver', 'bnetserver', 'web'):
            if state['old'][name]['running']:
                run(['docker', 'start', state['old'][name]['id']])
    state['phase'] = 'rolled-back'
    private_json(Path(state['backup']) / 'state.json', state)
    print('Old containers restarted. Both database copies and candidate logs are retained.')


def addon_module():
    spec = importlib.util.spec_from_file_location('advancement_installer', ROOT / 'scripts/install-advancement-addon.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_world(state, timeout):
    command = compose_file(state)
    container = run(command + ['ps', '-q', 'worldserver'], capture=True).strip()
    deadline = time.monotonic() + timeout
    last_notice = 0
    while time.monotonic() < deadline:
        info = inspect(container)
        labels = info['Config'].get('Labels', {})
        if labels.get('org.wowforever.core') != CORE or labels.get('org.wowforever.advancement') != '1.11.0':
            raise RuntimeError('Worldserver container is not using the expected core and mod image')
        if info['RestartCount'] > 0 or info['State']['Status'] in ('dead', 'exited'):
            raise RuntimeError('New worldserver exited or restarted; inspect its retained logs')
        logs = run(['docker', 'logs', '--tail=3000', container], capture=True)
        if re.search(r'worldserver-daemon.*ready', logs) and 'ForeverAdvancement ready:' in logs:
            if 'version=1.11.0' not in logs:
                raise RuntimeError('Worldserver did not confirm the expected mod version')
            # Allow web and bnetserver to finish starting after world readiness.
            # The website uses worldserver:8085 for its Offline/Online badge.
            probe = subprocess.run(command + ['exec', '-T', 'web', 'python', '-c',
                'import socket; '
                '[socket.create_connection((host,port),3).close() '
                'for host,port in (("worldserver",8085),("bnetserver",1119),("bnetserver",8081))]'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe.returncode == 0:
                return
        if time.monotonic() - last_notice > 20:
            print('Waiting for updated worldserver, advancement catalogue and port 8085...', flush=True)
            last_notice = time.monotonic()
        time.sleep(2)
    raise RuntimeError('New worldserver did not report ready before timeout')


def build(image, jobs):
    args = ['docker', 'build', '--target', 'server-refresh', '--build-arg', 'TC_COMMIT=' + CORE,
            '--build-arg', 'BUILD_JOBS=' + str(jobs), '-t', image, str(ROOT)]
    # Output belongs in the local terminal. No user databases/certificates are in the build context.
    subprocess.run(args, check=True)


def migrate(args):
    old_dir = args.old_project.resolve(strict=True)
    original = json.loads(run(old_compose(old_dir) + ['config', '--format', 'json'], capture=True))
    if original.get('name') == PROJECT:
        raise ValueError('The source must be the old server, not an earlier refresh')
    old = {}
    for name in SERVICES:
        ids = run(old_compose(old_dir) + ['ps', '-a', '-q', name], capture=True).split()
        if len(ids) != 1:
            raise ValueError('Expected exactly one existing container for ' + name)
        old[name] = inspect(ids[0])
    if not old['mysql']['State']['Running']:
        raise ValueError('The original MySQL must be running')
    addon_module().addons_root(args.client)
    preflight(old)
    # Refuse any earlier clone instead of accidentally reusing its volume.
    prior = run(['docker', 'ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=' + PROJECT], capture=True)
    prior_volumes = run(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + PROJECT], capture=True)
    if prior.strip() or prior_volumes.strip():
        raise ValueError('A previous refresh project exists. Use status/rollback; do not reuse or delete its database')
    image = 'forever-trinitycore:refresh-70658-' + uuid.uuid4().hex[:10]
    model = isolated_model(original, {name: info['Image'] for name, info in old.items()}, image, PROJECT)
    backup = old_dir / 'backups' / ('server-refresh-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    backup.mkdir(mode=0o700, parents=True)
    compose = backup / 'compose.private.json'
    private_json(compose, model)
    state = {'format': 'wowforever-server-refresh-v1', 'phase': 'prepared', 'project': PROJECT,
             'backup': str(backup), 'compose': str(compose), 'core': CORE, 'image': image,
             'old_project': str(old_dir), 'old_stopped': False, 'addon_installed': False,
             'old': {name: {'id': info['Id'], 'image': info['Image'], 'running': info['State']['Running']}
                     for name, info in old.items()}}
    state_file = backup / 'state.json'
    private_json(state_file, state)
    command = compose_file(state)
    run(command + ['config', '-q'], capture=True)
    print('Migration state (private, do not upload): ' + str(state_file), flush=True)
    build(image, args.jobs)  # The old server is not stopped while compiling.
    preflight(old)
    try:
        state['old_stopped'] = True
        private_json(state_file, state)  # persisted BEFORE the first stop, including interrupts
        print('Stopping old game services; MySQL and all original files are retained.', flush=True)
        run(['docker', 'stop', '-t', '120', *[old[name]['Id'] for name in GAME_SERVICES]])
        state['phase'] = 'backing-up'
        private_json(state_file, state)
        dump_database(old['mysql']['Id'], backup / 'databases.sql.gz')
        state['phase'] = 'importing-clone'
        private_json(state_file, state)
        run(command + ['up', '-d', '--no-deps', 'mysql'])
        new_mysql = run(command + ['ps', '-q', 'mysql'], capture=True).strip()
        wait_mysql(new_mysql)
        import_database(new_mysql, backup / 'databases.sql.gz')
        # Only the clone receives core updates or mod schema/bindings.
        db_sql(new_mysql, 'characters', (ROOT / 'mods/forever-advancement/sql/characters.sql').read_text())
        db_sql(new_mysql, 'world', (ROOT / 'mods/forever-advancement/sql/world.sql').read_text())
        db_sql(new_mysql, 'hotfixes',
               'DELETE FROM hotfix_data WHERE TableHash=3224459983 AND RecordId IN (190031901,190031902);\n'
               'DELETE FROM chr_classes_x_power_types WHERE ID IN (190031901,190031902);\n')
        state['phase'] = 'starting-clone'
        private_json(state_file, state)
        run(command + ['up', '-d', '--no-deps', 'worldserver', 'bnetserver', 'web'])
        wait_world(state, args.timeout)
        # Install UI only after server readiness; preserve its previous copy for rollback.
        state['addon_installed'] = True
        private_json(state_file, state)
        addon_module().install(args.client, backup / 'addon')
        state['phase'] = 'ready'
        private_json(state_file, state)
    except BaseException:
        print('Refresh failed. Returning to original containers; the original databases were not modified.', file=sys.stderr)
        restore_old(state)
        raise
    print('REFRESH READY: core ' + CORE[:12] + ', ForeverAscension 1.11.0, TCP 8085 reachable from website.')
    print('State: ' + str(state_file))
    print('Rollback: python3 scripts/refresh-forever-server.py rollback --state ' + str(state_file))
    print('Next: start the copied _forever_/Wow.exe using launcher 2.0.5 and check login.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    upgrade = sub.add_parser('migrate')
    upgrade.add_argument('--old-project', type=Path, default=Path.home() / 'WoWForEver')
    upgrade.add_argument('--client', type=Path, default=Path('/mnt/e/WoWForEver-work/experiments/Forever-client-v2/_forever_'))
    upgrade.add_argument('--jobs', type=int, choices=range(1, 17), default=2)
    upgrade.add_argument('--timeout', type=int, default=900)
    for name in ('status', 'rollback'):
        sub.add_parser(name).add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    state = None if args.action == 'migrate' else json.loads(args.state.read_text())
    old_dir = args.old_project if state is None else Path(state['old_project'])
    (old_dir / 'backups').mkdir(exist_ok=True)
    with (old_dir / 'backups/content-port.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'migrate':
            migrate(args)
        elif args.action == 'rollback':
            if state['phase'] == 'rolled-back':
                print('Already rolled back; no services changed.')
            else:
                restore_old(state)
        else:
            print('Phase: ' + state['phase'] + '; core: ' + state['core'][:12])
            run(compose_file(state) + ['ps'])
            run(compose_file(state) + ['logs', '--tail=50', 'worldserver', 'bnetserver'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('Stopped: ' + (str(error) or 'interrupted') + '. No original database volume has been deleted.', file=sys.stderr)
        sys.exit(1)
