#!/usr/bin/env python3
"""Prepare a pristine Forever installation with fresh databases and fresh extracted data.

Old databases, maps, overrides and gameplay modules are never imported. Only the
existing local TLS identity is mounted read-only. No global Docker cleanup occurs.
"""
import argparse
import base64
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time

from clean_game_tables import TABLE_WRITER, missing_tables, recover as recover_game_table

ROOT = Path(__file__).resolve().parents[1]
CORE = 'b4e7b940593f6402a822d4fbcdf31331d16f73b6'
PROJECT = 'forever-clean'
FORMAT = 'wowforever-clean-server-v1'
OLD_PROJECTS = ('forever', 'forever-refresh-70658')
SUPPORTED = (70658, 70790)
SERVICES = ('mysql', 'worldserver', 'bnetserver', 'web')


def run(command, *, capture=False, data=None):
    public_workload = command[:2] == ['docker', 'build'] or ('run' in command and 'extractor' in command)
    result = subprocess.run(command, input=data, stdout=subprocess.PIPE if capture else None,
                            stderr=None if public_workload else subprocess.PIPE, text=True)
    if result.returncode:
        # Resolved Compose files/configs contain private credentials. Never echo them.
        if 'run' in command and 'extractor' in command:
            raise RuntimeError('Extraction failed; see extractor output above (the temporary container was removed)')
        if TABLE_WRITER in command:
            raise RuntimeError('Could not publish verified GameTable: ' + (result.stderr or '').strip()[-1000:])
        if OLD_WORLD_SOCKET_PROBE in command:
            # This fixed /proc probe contains no credentials or configuration.
            raise RuntimeError('Old world socket probe failed for ' + command[2] + ': '
                               + (result.stderr or '').strip()[-1000:])
        raise RuntimeError('Command failed: ' + ' '.join(command[:3]) + '; use the status command for service logs')
    return result.stdout or ''


def write_private(path, value):
    temp = path.with_suffix(path.suffix + '.partial')
    with temp.open('w', encoding='utf-8') as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def client_root(path):
    root = path.resolve(strict=True)
    if root.name.lower() == '_forever_':
        root = root.parent
    if not (root / '.build.info').is_file() or not (root / 'Data').is_dir():
        raise ValueError('Client root must contain .build.info, Data and _forever_')
    if not (root / '_forever_/Wow.exe').is_file():
        raise ValueError('Missing actual _forever_/Wow.exe under the selected root')
    return root


def windows_path(path):
    match = re.fullmatch(r'/mnt/([a-zA-Z])/(.*)', str(path))
    return match[1].upper() + ':\\' + match[2].replace('/', '\\') if match else None


def executable_build(executable):
    """Read Windows PE version information without executing or modifying the game."""
    winpath = windows_path(executable)
    if not winpath or not shutil.which('powershell.exe'):
        raise ValueError('EXE version requires WSL Windows interop; alternatively supply --client-build from FileVersion')
    payload = base64.b64encode(winpath.encode()).decode()
    script = ("$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'));"
              "$v=(Get-Item -LiteralPath $p -ErrorAction Stop).VersionInfo;"
              "[pscustomobject]@{file=$v.FileVersion;product=$v.ProductVersion}|ConvertTo-Json -Compress")
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, errors='replace', timeout=30, check=True)
    versions = json.loads(result.stdout.lstrip('\ufeff'))
    found = set()
    for value in versions.values():
        if value:
            m = re.search(r'(?<!\d)1[.,]60[.,]1[.,](\d+)', value)
            if m:
                found.add(int(m[1]))
    if len(found) != 1:
        raise ValueError('Could not determine one unambiguous 1.60.1 EXE build')
    return found.pop()


def identity(source, test, declared=None):
    source, test = client_root(source), client_root(test)
    if source == test:
        raise ValueError('Keep the original and the independent test client separate')
    rows = list(csv.reader((source / '.build.info').read_text(encoding='utf-8-sig').splitlines(), delimiter='|'))
    columns = {name.split('!')[0]: i for i, name in enumerate(rows[0])}
    active = [row for row in rows[1:] if row and row[columns['Product']] == 'wowf' and row[columns['Active']] == '1']
    if len(active) != 1:
        raise ValueError('Choose a single active wowf installation')
    row = active[0]
    copied_rows = list(csv.reader((test / '.build.info').read_text(encoding='utf-8-sig').splitlines(), delimiter='|'))
    copied_columns = {name.split('!')[0]: i for i, name in enumerate(copied_rows[0])}
    copied_active = [r for r in copied_rows[1:] if r and r[copied_columns['Product']] == 'wowf' and r[copied_columns['Active']] == '1']
    if len(copied_active) != 1 or copied_active[0][copied_columns['Build Key']].lower() != row[columns['Build Key']].lower():
        raise ValueError('Original and test client CASC build keys differ; select a matching test copy')
    original_exe, copied_exe = source / '_forever_/Wow.exe', test / '_forever_/Wow.exe'
    digest = sha_file(original_exe)
    if digest != sha_file(copied_exe):
        raise ValueError('Original and test EXE differ; the server must match the client that will be launched')
    observed = executable_build(original_exe) if shutil.which('powershell.exe') else None
    if observed is not None and declared is not None and observed != declared:
        raise ValueError('--client-build disagrees with the actual Windows EXE')
    build = observed if observed is not None else declared
    if build not in SUPPORTED:
        raise ValueError('Confirm the actual EXE FileVersion; this baseline supports 70658 and 70790 only')
    return dict(source=str(source), test=str(test), exe_build=build, exe_sha256=digest,
                metadata_version=row[columns['Version']], build_key=row[columns['Build Key']], product='wowf')


def certificate_directory(old_state):
    state = json.loads(old_state.read_text())
    model = json.loads(Path(state['compose']).read_text())
    candidates = [Path(m['source']).resolve(strict=True) for m in model['services']['bnetserver'].get('volumes', [])
                  if m.get('type') == 'bind' and m.get('target') == '/opt/trinitycore/certs']
    if len(candidates) != 1:
        raise ValueError('Cannot identify the existing local TLS directory')
    certs = candidates[0]
    for name in ('forever.cert.pem', 'forever.key.pem', 'ca/forever_root_ca.crt'):
        if not (certs / name).is_file():
            raise ValueError('Existing TLS identity is incomplete')
    return certs


def mount(source, target, readonly=True):
    return dict(type='bind', source=str(source), target=target, read_only=readonly,
                bind=dict(create_host_path=False))


def model(state, *, published=False):
    directory = Path(state['root'])
    credential = state['credentials']
    common = dict(image=state['image'], pull_policy='never', networks=['clean'], restart='no',
                  environment=dict(DB_PASSWORD=credential['database']))
    data = mount(directory / 'data', '/opt/trinitycore/data')
    logs = dict(type='volume', source='logs', target='/opt/trinitycore/logs')
    entrypoint = mount(ROOT / 'docker/clean/entrypoint.py', '/usr/local/bin/forever-clean-entrypoint.py')
    services = {
        'mysql': dict(image='mysql:8.0', networks=['clean'], restart='unless-stopped',
                      environment=dict(MYSQL_ROOT_PASSWORD=credential['root'], DB_PASSWORD=credential['database']),
                      command=['--max-allowed-packet=1G', '--skip-log-bin', '--innodb-buffer-pool-size=512M',
                               '--character-set-server=utf8mb4', '--collation-server=utf8mb4_unicode_ci'],
                      volumes=[dict(type='volume', source='mysql-data', target='/var/lib/mysql'),
                               mount(ROOT / 'docker/clean/mysql-init.sh', '/docker-entrypoint-initdb.d/01-clean.sh')],
                      healthcheck=dict(test=['CMD-SHELL', 'MYSQL_PWD="$$MYSQL_ROOT_PASSWORD" mysqladmin ping -h 127.0.0.1 -uroot --silent'],
                                       interval='5s', timeout='5s', retries=60, start_period='20s')),
        'initialize': dict(common, command=['initialize'], volumes=[data, logs, entrypoint],
                           depends_on={'mysql': {'condition': 'service_healthy'}}, profiles=['setup']),
        'worldserver': dict(common, command=['worldserver'], volumes=[data, logs, entrypoint],
                            logging=dict(driver='json-file', options={'max-size': '20m', 'max-file': '3'}),
                            depends_on={'mysql': {'condition': 'service_healthy'}}),
        'bnetserver': dict(common, command=['bnetserver'], volumes=[logs, entrypoint, mount(state['certs'], '/opt/trinitycore/certs')],
                           extra_hosts=['trinity.actual.battle.net:127.0.0.1'],
                           depends_on={'mysql': {'condition': 'service_healthy'}}),
        'web': dict(image=state['web_image'], pull_policy='never', networks=['clean'], restart='unless-stopped',
                    environment=dict(DB_HOST='mysql', DB_USER='trinity', DB_PASSWORD=credential['database'],
                                     SOAP_URL='http://worldserver:7878/', SOAP_USER='FOREVERWEB', SOAP_PASSWORD=credential['soap'],
                                     SERVER_NAME='Forever Clean', GAME_VERSION=f"1.60.1.{state['client']['exe_build']}",
                                     PUBLIC_ADDRESS='127.0.0.1', CA_CERT='/certs/ca/forever_root_ca.crt'),
                    volumes=[mount(Path(state['certs']) / 'ca/forever_root_ca.crt', '/certs/ca/forever_root_ca.crt')]),
        'extractor': dict(image=state['image'], pull_policy='never', profiles=['setup'], network_mode='none',
                          read_only=True, tmpfs=['/tmp:rw,nosuid,nodev,size=64m'],
                          entrypoint=['/usr/local/bin/forever-clean-extract.sh'],
                          volumes=[mount(state['client']['source'], '/client'),
                                   mount(state['extraction'], '/output', False),
                                   mount(ROOT / 'docker/clean/extract.sh', '/usr/local/bin/forever-clean-extract.sh')])}
    if published:
        services['worldserver']['ports'] = ['127.0.0.1:8085:8085']
        services['bnetserver']['ports'] = ['127.0.0.1:1119:1119', '127.0.0.1:8081:8081']
        services['web']['ports'] = ['127.0.0.1:8088:8000']
    return dict(name=PROJECT, services=services, networks={'clean': {}}, volumes={'mysql-data': {}, 'logs': {}})


def compose(state, *args, capture=False, data=None):
    return run(['docker', 'compose', '-p', PROJECT, '-f', state['compose'], *args], capture=capture, data=data)


def save(state):
    write_private(Path(state['root']) / 'state.json', state)


def configure_compose(state, published=False):
    write_private(Path(state['compose']), model(state, published=published))
    compose(state, 'config', '-q')


def container(state, service):
    ident = compose(state, 'ps', '-aq', service, capture=True).strip()
    if not ident:
        return None
    values = json.loads(run(['docker', 'inspect', ident], capture=True))
    item = values[0]
    labels = item['Config'].get('Labels', {})
    if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != service:
        raise ValueError('Container ownership mismatch')
    return item


def wait_exit(state, service, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = container(state, service)
        if item and not item['State']['Running']:
            if item['State']['ExitCode'] != 0:
                raise RuntimeError('Fresh database initialization failed; retain its logs and inspect status')
            return
        print('Fresh database import is running; do not restart it.', flush=True)
        time.sleep(20)
    raise RuntimeError('Import is still running. It was not stopped; rerun install to continue waiting, or use status')


WORLD_TCP_PROBE = '''
import socket
try:
    with socket.create_connection(("127.0.0.1", 8085), 2):
        pass
except OSError:
    print("WAIT")
else:
    print("READY")
'''

# Legacy runtime images contain sh but not Python. Inspect only this container's
# network namespace, using POSIX shell builtins and the kernel LISTEN state.
OLD_WORLD_SOCKET_PROBE = '''
for probe_file in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$probe_file" ] || continue
    while read -r probe_slot probe_local probe_remote probe_state probe_rest; do
        case "$probe_local:$probe_state" in
            *:"$1":0A) printf 'READY\\n'; exit 0 ;;
        esac
    done < "$probe_file"
done
printf 'WAIT\\n'
'''


def wait_world(state, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = container(state, 'worldserver')
        if not item or not item['State']['Running']:
            raise RuntimeError('Clean worldserver stopped; inspect status')
        labels = item['Config'].get('Labels', {})
        if labels.get('org.wowforever.core') != CORE or labels.get('org.wowforever.advancement') != 'none':
            raise RuntimeError('Unexpected game server image; expected the pinned pristine core without Advancement')
        # A log tail is not a readiness signal: CLI prompts can evict the line,
        # and a previous process's ready message can survive a later restart.
        tcp = compose(state, 'exec', '-T', 'worldserver', 'python3', '-c', WORLD_TCP_PROBE, capture=True).strip()
        if tcp == 'READY':
            expected = ['70', str(state['client']['exe_build']), '137']
            realm = sql(state, 'SELECT id,gamebuild,contentSetId,flag FROM auth.realmlist;\n').split()
            if len(realm) != 4 or realm[:3] != expected:
                raise RuntimeError('The running clean server did not retain one realm with the actual client build')
            if not int(realm[3]) & 2:  # REALM_FLAG_OFFLINE is cleared after StartNetwork succeeds.
                print('Pristine worldserver ready: TCP 8085 and online realm 70 / build ' + expected[1] + ' verified.', flush=True)
                return
            reason = 'realm is still marked offline'
        else:
            reason = 'TCP 8085 is not accepting connections yet'
        print('Waiting for pristine worldserver readiness: ' + reason + '...', flush=True)
        time.sleep(10)
    raise RuntimeError('Clean worldserver readiness timed out; inspect status')


def sql(state, text):
    item = container(state, 'mysql')
    if not item:
        raise RuntimeError('Fresh MySQL container is missing')
    return run(['docker', 'exec', '-i', item['Id'], 'sh', '-c',
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names'], capture=True, data=text)


def prepare_realm(state):
    build = int(state['client']['exe_build'])
    if sql(state, f'SELECT COUNT(*) FROM auth.build_info WHERE build={build};\n').strip() != '1':
        raise RuntimeError('The pristine upstream auth schema does not contain the actual EXE build')
    if sql(state, 'SELECT COUNT(*) FROM auth.battlenet_accounts; SELECT COUNT(*) FROM characters.characters;\n').split() != ['0', '0']:
        raise RuntimeError('Expected fresh empty account and character databases; refusing to adopt existing progress')
    sql(state, "DELETE FROM auth.realmlist WHERE id<>70;\n"
        f"UPDATE auth.realmlist SET name='Forever Clean', address='127.0.0.1', localAddress='127.0.0.1', "
        f"localSubnetMask='255.255.255.0', port=8085, icon=0, contentSetId=137, gamebuild={build} WHERE id=70;\n")
    if sql(state, 'SELECT id,gamebuild,contentSetId FROM auth.realmlist;\n').split() != ['70', str(build), '137']:
        raise RuntimeError('Fresh realm identity did not match the selected EXE build')


def storage_stamp(root):
    folder = root / 'Data/data'
    return [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(folder.iterdir())]


def ensure_game_tables(state):
    """Repair only an authenticated missing table, preserving completed imports."""
    output = Path(state['root']) / 'data'
    missing = missing_tables(output)
    if not missing:
        return
    if missing != ['ArtifactKnowledgeMultiplier.txt']:
        raise RuntimeError('Missing required GameTables: ' + ', '.join(missing)
                           + '. Keep the extraction and inspect the client; no dummy tables were generated.')
    expected = dict(core=CORE, exe_sha256=state['client']['exe_sha256'], build_key=state['client']['build_key'])
    if json.loads((output / '.clean-extraction.json').read_text()) != expected:
        raise ValueError('GameTable repair requires this clean installation extraction checkpoint')
    if output.is_symlink() or (output / 'gt').is_symlink():
        raise ValueError('Linked clean data directories are unsupported')
    item = container(state, 'worldserver')
    if item and item['State']['Running']:
        raise RuntimeError('Stop the clean worldserver before repairing its extracted GameTable')
    source = Path(state['client']['source'])
    before_info = (source / '.build.info').read_bytes()
    before = storage_stamp(source)
    body, report = recover_game_table(source, state['client']['build_key'])
    if before_info != (source / '.build.info').read_bytes() or before != storage_stamp(source):
        raise RuntimeError('Client storage changed during GameTable repair; close games/downloaders and retry')
    target = output / 'gt/ArtifactKnowledgeMultiplier.txt'
    if target.is_symlink() or (target.exists() and target.stat().st_size):
        raise ValueError('GameTable destination changed; existing nonempty data is preserved')
    report.update(format='wowforever-clean-game-table-repair-v1', file_data_id=1582086,
                  build_key=state['client']['build_key'], core=CORE, bytes=len(body),
                  sha256=hashlib.sha256(body).hexdigest(), content_md5=hashlib.md5(body).hexdigest(),
                  client_modified=False, databases_modified=False, server_binaries_modified=False)
    # Write metadata before publishing the validated bytes. A retry can safely
    # repeat this step after an interruption; no database import is restarted.
    write_private(output / '.clean-game-table-repair.json', report)
    # Existing extractor outputs are owned by root. Publish through a narrowly
    # mounted container instead of changing their permissions or requiring sudo.
    table_dir = str(target.parent)
    if ',' in table_dir:
        raise ValueError('A comma in the generated GameTable directory is unsupported')
    run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--interactive',
         '--mount', 'type=bind,source=' + table_dir + ',target=/output',
         '--entrypoint', 'python3', state['image'], '-c', TABLE_WRITER, '/output'],
        data=json.dumps(dict(body=base64.b64encode(body).decode('ascii'), sha256=report['sha256'])))
    if sha_file(target) != report['sha256']:
        raise RuntimeError('Published GameTable checksum mismatch')
    print('RESTORED GameTable: ArtifactKnowledgeMultiplier.txt; current ROOT content hash verified; source=' + report['source'], flush=True)


def stop_previous(state):
    items = []
    for project in OLD_PROJECTS:
        ids = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project], capture=True).split()
        for ident in ids:
            item = json.loads(run(['docker', 'inspect', ident], capture=True))[0]
            labels = item['Config'].get('Labels', {})
            if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') not in SERVICES:
                continue
            if item['State']['Running']:
                if labels['com.docker.compose.service'] == 'worldserver':
                    tcp = run(['docker', 'exec', ident, 'sh', '-c', OLD_WORLD_SOCKET_PROBE,
                               'forever-old-world-probe', '1F95'], capture=True).strip()
                    if tcp != 'READY':
                        raise RuntimeError('An old worldserver may still be importing its first database; it was not stopped')
                items.append(dict(id=ident, project=project, service=labels['com.docker.compose.service']))
    # Record all identities before stopping anything; rollback can restore only these containers.
    previous = {item['id']: item for item in state.get('previous', [])}
    previous.update({item['id']: item for item in items})
    state['previous'] = list(previous.values())
    save(state)
    for item in sorted(items, key=lambda x: x['service'] == 'mysql'):
        run(['docker', 'stop', '-t', '120', item['id']])


TLS_PROBE = '''import socket,ssl,time
context=ssl.create_default_context(cafile="/certs/ca/forever_root_ca.crt")
for attempt in range(60):
    try:
        for port in (1119,8081):
            with socket.create_connection(("bnetserver",port),3) as stream:
                with context.wrap_socket(stream,server_hostname="trinity.actual.battle.net"):
                    pass
        with socket.create_connection(("worldserver",8085),3):
            pass
        print("CLEAN TLS AND WORLD PORTS READY",flush=True)
        break
    except OSError as error:
        if attempt % 5 == 0:
            print("Waiting for clean TLS/world: "+str(error),flush=True)
        time.sleep(2)
else:
    raise SystemExit("Clean TLS/world readiness timed out")
'''


def install(args):
    directory = args.root.resolve()
    state_path = directory / 'state.json'
    if state_path.exists():
        state = load_state(state_path)
        if state['phase'] == 'ready':
            print('Already ready. Use status/restart; existing clean databases were not reset.')
            return
    else:
        if directory.exists():
            raise ValueError('Choose a NEW clean directory; no existing files are adopted or removed')
        if run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT], capture=True).strip() or run(
                ['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + PROJECT], capture=True).strip():
            raise ValueError('A previous clean project exists; use its state instead of adopting its databases')
        client = identity(args.client, args.test_client, args.client_build)
        certs = certificate_directory(args.old_state.resolve(strict=True))
        for original in (Path(client['source']), Path(client['test']), certs):
            if directory == original or directory.is_relative_to(original) or original.is_relative_to(directory):
                raise ValueError('The clean installation must be separate from clients and certificate storage')
        if shutil.disk_usage(directory.parent).free < 15 * 1024**3:
            raise ValueError('At least 15 GiB free on the clean installation filesystem is required')
        directory.mkdir(mode=0o700)
        (directory / 'data').mkdir()
        extraction = directory / ('extract-' + secrets.token_hex(6))
        extraction.mkdir()
        state = dict(format=FORMAT, root=str(directory), compose=str(directory / 'compose.private.json'), core=CORE,
                     project=PROJECT, phase='prepared', certs=str(certs), extraction=str(extraction), client=client,
                     image='forever-trinitycore:clean-' + CORE[:12], web_image='forever-clean-web:local',
                     credentials={key: secrets.token_hex(24) for key in ('root', 'database', 'soap')}, previous=[])
        save(state)
        configure_compose(state)
    # Resume through the current tool checkout, including fixes that do not require
    # recompiling the already-built pristine game binaries.
    control = directory / 'server.sh'
    control.write_text('#!/bin/sh\nexec python3 ' + shlex.quote(str(Path(__file__).resolve())) +
                       ' "$@" --root ' + shlex.quote(str(directory)) + '\n')
    control.chmod(0o700)
    print(f"Clean core {CORE[:12]}; EXE {state['client']['exe_build']}; CASC metadata {state['client']['metadata_version']}", flush=True)
    print('State: ' + str(state_path), flush=True)
    if state['phase'] in ('prepared', 'building'):
        state['phase'] = 'building'; save(state)
        run(['docker', 'build', '--progress=plain', '-f', str(ROOT / 'docker/clean/Dockerfile'),
             '--build-arg', f'BUILD_JOBS={args.jobs}', '-t', state['image'], str(ROOT)])
        run(['docker', 'build', '-t', state['web_image'], str(ROOT / 'web')])
        state['phase'] = 'built'; save(state)
    extraction_marker = directory / 'data/.clean-extraction.json'
    if state['phase'] == 'extracting' and extraction_marker.is_file():
        marker = json.loads(extraction_marker.read_text())
        expected = dict(core=CORE, exe_sha256=state['client']['exe_sha256'], build_key=state['client']['build_key'])
        if marker != expected:
            raise ValueError('Fresh extraction checkpoint identity mismatch')
        state['phase'] = 'extracted'; save(state)
    if state['phase'] in ('built', 'extracting'):
        verified = identity(Path(state['client']['source']), Path(state['client']['test']), state['client']['exe_build'])
        if verified['exe_sha256'] != state['client']['exe_sha256'] or verified['build_key'] != state['client']['build_key']:
            raise RuntimeError('Client identity changed during the build; retain state and choose a matching baseline')
        if Path(state['extraction']).exists() and any(Path(state['extraction']).iterdir()):
            # Preserve a previous partial extraction; do not merge it into a fresh result.
            print('Retaining previous extraction attempt: ' + state['extraction'], flush=True)
            state['extraction'] = str(directory / ('extract-' + secrets.token_hex(6)))
            Path(state['extraction']).mkdir()
        Path(state['extraction']).mkdir(exist_ok=True)
        configure_compose(state)
        state['phase'] = 'extracting'; save(state)
        before = storage_stamp(Path(state['client']['source']))
        compose(state, '--profile', 'setup', 'run', '--rm', '--no-deps', 'extractor')
        if storage_stamp(Path(state['client']['source'])) != before:
            raise RuntimeError('Original storage changed during extraction; close games/downloaders and retry install')
        output = Path(state['extraction'])
        for required in ('dbc', 'gt', 'cameras', 'maps', 'vmaps/GameObjectModels.dtree'):
            if not (output / required).exists():
                raise RuntimeError('Fresh extraction is incomplete: ' + required)
        write_private(output / '.clean-extraction.json', dict(core=CORE, exe_sha256=state['client']['exe_sha256'], build_key=state['client']['build_key']))
        if (directory / 'data').exists():
            (directory / 'data').rmdir()
        output.rename(directory / 'data')
        # Extractor is no longer run after this phase; retain its old path as provenance only.
        state['phase'] = 'extracted'; save(state)
    if state['phase'] == 'extracted':
        ensure_game_tables(state)
        compose(state, 'up', '-d', '--wait', 'mysql')
        state['phase'] = 'importing'; save(state)
        compose(state, '--profile', 'setup', 'up', '-d', 'initialize')
    if state['phase'] == 'importing':
        if container(state, 'initialize') is None:
            compose(state, '--profile', 'setup', 'up', '-d', 'initialize')
        wait_exit(state, 'initialize', args.timeout)
        prepare_realm(state)
        state['phase'] = 'initialized'; save(state)
    if state['phase'] == 'initialized':
        ensure_game_tables(state)
        # Apply runtime Python/config fixes to existing images without rebuilding
        # the pinned game binaries or rerunning the completed SQL initialization.
        configure_compose(state)
        compose(state, 'up', '-d', '--no-build', 'worldserver')
        wait_world(state, args.timeout)
        state['phase'] = 'staged'; save(state)
    if state['phase'] in ('staged', 'switching'):
        if state['phase'] == 'staged':
            state['phase'] = 'switching'; save(state)
        # A resumed switch must recheck the current process, not rely on the
        # readiness result from a previous install invocation.
        wait_world(state, args.timeout)
        stop_previous(state)
        configure_compose(state, published=True)
        compose(state, 'up', '-d', '--no-build', 'mysql', 'worldserver', 'bnetserver', 'web')
        wait_world(state, args.timeout)
        compose(state, 'run', '--rm', '--no-deps', 'web', 'python', '-c', TLS_PROBE)
        state['phase'] = 'ready'; save(state)
    print('CLEAN READY: one Normal realm 70; no imported accounts, characters, gameplay mods or old extracted data.')
    print('Create a NEW account at http://127.0.0.1:8088, then log out/in in Multi before testing.')
    print('Manage: ' + str(directory / 'server.sh') + ' status|start|stop|restart|purge-old')
    try:
        prepare_client_command(state)
    except (OSError, ValueError) as error:
        print('Server remains ready; client helper could not be copied: ' + str(error))


def prepare_client_command(state):
    test = Path(state['client']['test']).resolve(strict=True)
    folder = test / '.forever-multi'
    if not folder.resolve().is_relative_to(test):
        raise ValueError('Linked test-client tool directory is not supported')
    folder.mkdir(exist_ok=True)
    body = (ROOT / 'tools/clean-server/Prepare-CleanClient.ps1').read_bytes()
    path = folder / ('Prepare-CleanClient-' + hashlib.sha256(body).hexdigest()[:12] + '.ps1')
    if path.exists() and (path.is_symlink() or path.read_bytes() != body):
        raise ValueError('Existing client helper identity mismatch')
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(body)
    values = [windows_path(path), windows_path(test / '_forever_'), windows_path(state['client']['source'])]
    if all(values):
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        print('WINDOWS CLIENT PREPARATION (close the game first):')
        print('powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' + quote(values[0]) +
              ' -GameDirectory ' + quote(values[1]) + ' -OriginalDirectory ' + quote(values[2]))


def load_state(path):
    state = json.loads(path.read_text())
    if state.get('format') != FORMAT or state.get('project') != PROJECT or state.get('core') != CORE or Path(state['root']) != path.parent.resolve():
        raise ValueError('Clean state identity mismatch')
    if Path(state['compose']) != path.parent.resolve() / 'compose.private.json':
        raise ValueError('Unexpected Compose path')
    return state


def purge_old(state):
    """Explicit clean-install cleanup: Compose-owned old containers/volumes only.

    Bind directories (clients, certificate identity and add-on sources) are not
    volume-pruned or recursively deleted. Docker refuses volumes still in use.
    """
    if state['phase'] != 'ready':
        raise ValueError('Finish the fresh installation before purging old Docker storage')
    wait_world(state, 30)
    removed = []
    for project in OLD_PROJECTS:
        ids = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project], capture=True).split()
        owned = []
        for ident in ids:
            item = json.loads(run(['docker', 'inspect', ident], capture=True))[0]
            labels = item['Config'].get('Labels', {})
            if labels.get('com.docker.compose.project') != project:
                raise ValueError('Old container project identity mismatch')
            if item['State']['Running']:
                raise ValueError('An old project container is still running; inspect it before cleanup')
            owned.append(ident)
        if owned:
            run(['docker', 'rm', *owned])
        for kind in ('volume', 'network'):
            ids = run(['docker', kind, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project], capture=True).split()
            for ident in ids:
                item = json.loads(run(['docker', kind, 'inspect', ident], capture=True))[0]
                if item.get('Labels', {}).get('com.docker.compose.project') != project:
                    raise ValueError('Old storage project identity mismatch')
                run(['docker', kind, 'rm', ident])
                removed.append(dict(project=project, kind=kind, id=ident))
    state['purged_old'] = removed
    save(state)
    print('Old Compose containers, database/log volumes and networks removed. Clean project and bind files retained.')


def execute(args):
    if args.action == 'install':
        install(args)
    else:
        state = load_state(args.root.resolve(strict=True) / 'state.json')
        if args.action == 'status':
            print(f"Phase: {state['phase']}; pristine core: {state['core'][:12]}; EXE: {state['client']['exe_build']}")
            compose(state, '--profile', 'setup', 'ps', '-a')
            compose(state, 'logs', '--tail=70', 'initialize', 'worldserver', 'bnetserver', 'web')
        elif args.action == 'purge-old':
            purge_old(state)
        else:
            if state['phase'] != 'ready':
                raise ValueError('First initialization is not complete; use status or rerun install, do not restart it')
            if args.action == 'start':
                compose(state, 'up', '-d', '--no-build', *SERVICES)
            elif args.action == 'stop':
                compose(state, 'stop', 'web', 'bnetserver', 'worldserver')
            else:
                compose(state, 'restart', 'worldserver', 'bnetserver', 'web')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'start', 'stop', 'restart', 'purge-old'))
    parser.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    parser.add_argument('--client', type=Path, default=Path('/mnt/e/WoW_Forever'))
    parser.add_argument('--test-client', type=Path, default=Path('/mnt/e/WoWForEver-work/experiments/Forever-client-v3/_forever_'))
    parser.add_argument('--old-state', type=Path, default=Path.home() / 'WoWForEver/backups/server-refresh-20261105-134121-3b67e9/state.json')
    parser.add_argument('--client-build', type=int, choices=SUPPORTED)
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=2)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'status':
        execute(args)
        return
    lock_dir = Path.home() / '.cache'
    lock_dir.mkdir(exist_ok=True)
    with (lock_dir / 'forever-clean-control.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another clean operation is running; use status instead of starting a second one')
        execute(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Clean setup stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
