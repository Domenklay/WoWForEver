#!/usr/bin/env python3
"""Start restored 70658 services on a private Docker network, then remove the trial.

Only the verified backup is read. No live Compose, ports, paths, tags or databases
are changed. Saved image IDs must already be local. Game-client login is not tested.
"""
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import sys
import tarfile
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('service_restore_sql', SCRIPTS / 'test-baseline-restore.py')
sql = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sql)
base = sql.baseline
import module_readiness

FORMAT = 'forever-baseline-services-trial-v1'
PREFIX = 'forever-services-check-'
LABEL = 'org.wowforever.services-trial'
SERVICES = ('worldserver', 'bnetserver', 'web')
ENTRY = '/usr/local/bin/forever-clean-entrypoint.py'
DATA = '/opt/trinitycore/data'
CERTS = '/opt/trinitycore/certs'
CA = '/certs/ca/forever_root_ca.crt'


def archived_path(name):
    p = PurePosixPath(name)
    if (p.is_absolute() or not name.startswith('fs/') or '..' in p.parts
            or str(p) != name.rstrip('/') or len(p.parts) < 2):
        raise ValueError('Unsafe restored archive path')
    return p


def unpack(archive, folder):
    """Do not restore absolute paths, links, ownership or executable permissions."""
    seen = set()
    with tarfile.open(archive, 'r|gz') as stream:
        for item in stream:
            part = archived_path(item.name)
            if str(part) in seen or not (item.isfile() or item.isdir()):
                raise ValueError('Duplicate or unsupported restored archive member')
            seen.add(str(part))
            target = folder.joinpath(*part.parts)
            base.direct(target)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if item.isdir():
                target.mkdir(exist_ok=True, mode=0o700)
            else:
                with target.open('xb') as output, stream.extractfile(item) as source:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                target.chmod(0o600)


def relocated(folder, source):
    path = PurePosixPath(source)
    if not path.is_absolute() or source.startswith('//') or '..' in path.parts or str(path) != source:
        raise ValueError('Unexpected saved absolute source path')
    target = base.direct(folder / 'fs' / source.lstrip('/'))
    if not target.exists():
        raise ValueError('Required saved source is absent from archive')
    return target


def bind_source(model, service, target):
    mounts = [m for m in model['services'][service].get('volumes', [])
              if isinstance(m, dict) and m.get('type') == 'bind' and m.get('target') == target]
    if len(mounts) != 1:
        raise ValueError('Expected exactly one saved ' + service + ' bind for ' + target)
    return mounts[0]['source']


def bind(source, target):
    if any(c in str(source) for c in ',\n\r'):
        raise ValueError('Unsupported comma/newline in restored bind path')
    return 'type=bind,source=' + str(source) + ',target=' + target + ',readonly'


def checked_manifest(manifest):
    if (manifest.get('client_build') != 70658 or set(manifest.get('images', {})) != set(base.SERVICES)
            or not isinstance(manifest.get('database_snapshot'), dict)):
        raise ValueError('Expected the verified combined 70658 four-service baseline')
    if manifest.get('core') != 'b4e7b940593f6402a822d4fbcdf31331d16f73b6':
        raise ValueError('Unsupported saved core')
    for item in manifest['images'].values():
        if not re.fullmatch('sha256:[0-9a-f]{64}', item.get('id', '')):
            raise ValueError('Invalid saved image identity')


class ServicesTrial:
    def __init__(self, manifest, folder, nonce, candidate=None):
        if not re.fullmatch('[0-9a-f]{12}', nonce):
            raise ValueError('Invalid trial identity')
        self.manifest, self.folder, self.nonce = manifest, base.direct(folder), nonce
        self.name = PREFIX + nonce
        self.network = self.name + '-net'
        self.names = {s: self.name + '-' + s for s in SERVICES}
        self.volumes = [self.name + '-world-logs', self.name + '-bnet-logs']
        self.db = sql.MysqlTrial(manifest['images']['mysql']['id'], folder, nonce)
        self.images=copy.deepcopy(manifest['images'])
        self.candidate=candidate
        if candidate:
            if not re.fullmatch('sha256:[0-9a-f]{64}',candidate): raise ValueError('Candidate requires an exact local image ID')
            self.images['worldserver']['id']=candidate
        self.allocated = False
        self.password = secrets.token_hex(24)
        self.soap = secrets.token_hex(24)
        self.state = {}
        self.expected = {}

    def owned(self, kind, name, role):
        out = sql.docker(kind, 'inspect', name, missing=True)
        if out is None:
            return None
        item = json.loads(out)[0]
        labels = item.get('Config', {}).get('Labels', {}) if kind == 'container' else item.get('Labels', {})
        if (labels.get(LABEL) != self.nonce or labels.get(LABEL + '.role') != role
                or item['Name'].lstrip('/') != name):
            raise ValueError('Service-trial resource ownership mismatch; nothing removed')
        return item

    def labels(self, role):
        return ['--label', LABEL + '=' + self.nonce, '--label', LABEL + '.role=' + role]

    def preflight(self):
        for service, item in self.manifest['images'].items():
            image = json.loads(sql.docker('image', 'inspect', item['id']))[0]
            if image['Id'] != item['id'] or image.get('Os') != 'linux':
                raise ValueError('Saved local image identity/platform differs: ' + service)
            if service == 'worldserver':
                labels = image.get('Config', {}).get('Labels', {})
                game = self.manifest['gameplay']
                expected = {'org.wowforever.core': self.manifest['core'],
                            'org.wowforever.gameplay.source': game['source_sha256'],
                            'org.wowforever.advancement': labels.get('org.wowforever.advancement'),
                            'org.wowforever.encyclopedia': game['encyclopedia'],
                            'org.wowforever.scaling': '0.2.0'}
                self.advancement_version=labels.get('org.wowforever.advancement')
                if self.advancement_version not in ('1.11.0','1.12.0','1.13.0','1.14.0','1.14.1') or any(labels.get(k) != v for k, v in expected.items()):
                    raise ValueError('Saved gameplay image labels differ from the backup')
        if self.candidate:
            item=base.game.adv.image(self.candidate)
            base.game.check_image(item,{'core':self.manifest['core']},candidate=True)
            self.advancement_version=base.game.adv.VERSION
        for kind, name, role in self.resources():
            if self.owned(kind, name, role):
                raise ValueError('Trial resource already exists; no existing resource reused')

    def resources(self):
        return ([('container', self.names[s], s) for s in reversed(SERVICES)]
                + [('volume', v, 'logs') for v in self.volumes]
                + [('network', self.network, 'network')])

    def prepare_sources(self):
        root = relocated(self.folder, self.manifest['root'])
        model = json.loads((root / 'compose.private.json').read_text())
        saved = json.loads((root / 'state.json').read_text())
        if (saved.get('core') != self.manifest['core'] or saved.get('gameplay') != self.manifest['gameplay']
                or saved.get('client', {}).get('exe_build') != 70658):
            raise ValueError('Archived state differs from the backup identity')
        self.state = {'credentials': {'database': self.password, 'soap': self.soap}}
        # Redaction also covers the old credentials if an archived file logs them.
        self.state['credentials'].update({'old_' + k: v for k, v in saved.get('credentials', {}).items()})
        self.data = relocated(self.folder, bind_source(model, 'worldserver', DATA))
        self.certs = relocated(self.folder, bind_source(model, 'bnetserver', CERTS))
        self.entry = relocated(self.folder, bind_source(model, 'bnetserver', ENTRY))
        self.ca = relocated(self.folder, bind_source(model, 'web', CA))
        if not self.data.is_dir() or not self.certs.is_dir() or not self.entry.is_file() or not self.ca.is_file():
            raise ValueError('Restored resource/certificate types differ')
        if not all((self.certs / name).is_file() for name in ('forever.cert.pem', 'forever.key.pem')):
            raise ValueError('Restored TLS certificate/key pair is incomplete')
        # The web image runs as uid 10001 and must read the PUBLIC certificate.
        self.ca.chmod(0o644)
        self.envs = {}
        for service in SERVICES:
            original = model['services'][service].get('environment', {})
            env = {'DB_PASSWORD': self.password, 'FOREVER_RELEASE_MANAGED': '1'}
            if service == 'worldserver':
                for key in ('FOREVER_ADVANCEMENT_ENABLED', 'FOREVER_ENCYCLOPEDIA_ENABLED',
                            'FOREVER_SCALING_ENABLED', 'FOREVER_SCALING_DAMAGE_GUARD',
                            'FOREVER_SCALING_MIN_OFFSET', 'FOREVER_SCALING_CREATURE_MAX_LEVEL'):
                    value = original.get(key)
                    if not isinstance(value, str) or not re.fullmatch('-?[0-9]+', value):
                        raise ValueError('Missing/invalid saved gameplay environment: ' + key)
                    env[key] = value
                if any(env[k] != '1' for k in ('FOREVER_ADVANCEMENT_ENABLED', 'FOREVER_ENCYCLOPEDIA_ENABLED', 'FOREVER_SCALING_ENABLED')):
                    raise ValueError('This trial requires all three saved gameplay modules enabled')
                if self.candidate:
                    # Exercise new dungeon modules on isolated clone only.
                    # No host ports or live DB connections are possible.
                    env.update(FOREVER_SCALING_MIN_OFFSET='-3',
                               FOREVER_DUNGEON_SCALING_ENABLED='1',
                               FOREVER_DUNGEON_FINDER_ENABLED='1')
            elif service == 'web':
                env = dict(DB_HOST='mysql', DB_USER='trinity', DB_PASSWORD=self.password,
                           SOAP_URL='http://worldserver:7878/', SOAP_USER='FOREVERWEB', SOAP_PASSWORD=self.soap,
                           SERVER_NAME='Forever restore trial', GAME_VERSION='1.60.1.70658',
                           PUBLIC_ADDRESS='127.0.0.1', CA_CERT=CA)
            path = self.folder / (service + '.private.env')
            with path.open('x') as stream:
                stream.write(''.join(k + '=' + v + '\n' for k, v in env.items()))
            path.chmod(0o600)
            self.envs[service] = path

    def attach_database(self):
        # Database import and count/schema checks ran before any service can write.
        self.db.sql("ALTER USER 'trinity'@'%' IDENTIFIED BY '" + self.password + "' ACCOUNT UNLOCK;\n")
        self.allocated = True
        sql.docker('network', 'create', '--internal', *self.labels('network'), self.network)
        network = self.owned('network', self.network, 'network')
        if not network.get('Internal') or network.get('Driver') != 'bridge':
            raise ValueError('Trial network is not an internal bridge')
        database = self.db.owned('container')
        if set(database.get('NetworkSettings', {}).get('Networks', {})) != {'none'}:
            raise ValueError('Trial MySQL already has an unexpected network')
        # Docker refuses adding a bridge alongside its special `none` network.
        # Detach only our new SQL trial; a failed connect is cleaned up normally.
        sql.docker('network', 'disconnect', 'none', self.db.name)
        sql.docker('network', 'connect', '--alias', 'mysql', self.network, self.db.name)
        database = self.db.owned('container')
        if (set(database.get('NetworkSettings', {}).get('Networks', {})) != {self.network}
                or database['HostConfig'].get('PortBindings')):
            raise ValueError('Trial MySQL internal-network isolation check failed')
        for volume in self.volumes:
            sql.docker('volume', 'create', *self.labels('logs'), volume)

    def create(self, service):
        mounts = []
        if service == 'worldserver':
            mounts = [bind(self.data, DATA), 'type=volume,source=' + self.volumes[0] + ',target=/opt/trinitycore/logs,volume-nocopy']
        elif service == 'bnetserver':
            mounts = [bind(self.certs, CERTS), bind(self.entry, ENTRY),
                      'type=volume,source=' + self.volumes[1] + ',target=/opt/trinitycore/logs,volume-nocopy']
        else:
            mounts = [bind(self.ca, CA)]
        args = ['container', 'create', '--name', self.names[service], '--pull=never', '--restart=no',
                '--network', self.network, '--network-alias', service, '--cpus=2',
                '--memory=' + ('6g' if service == 'worldserver' else '1g'),
                *self.labels(service), '--env-file', str(self.envs[service])]
        if service == 'bnetserver':
            args += ['--add-host', 'trinity.actual.battle.net:127.0.0.1']
        for mount in mounts:
            args += ['--mount', mount]
        args += [self.images[service]['id']]
        if service != 'web':
            args += [service]
        sql.docker(*args)
        self.expected[service] = mounts
        self.check_container(service)
        sql.docker('container', 'start', self.names[service])

    def check_container(self, service):
        item = self.owned('container', self.names[service], service)
        if not item:
            raise ValueError('Trial service is missing')
        host = item['HostConfig']
        network = item.get('NetworkSettings', {}).get('Networks', {})
        if (item['Image'] != self.images[service]['id']
                or host.get('NetworkMode') != self.network or host.get('PortBindings')
                or host.get('Binds') or host.get('Privileged') or set(network) != {self.network}
                or host.get('RestartPolicy', {}).get('Name') != 'no'):
            raise ValueError('Restored service isolation check failed')
        actual = []
        for m in item.get('Mounts', []):
            if m['Type'] == 'bind':
                if m.get('RW') or self.folder not in Path(m['Source']).parents:
                    raise ValueError('A service bind escapes the restored trial or is writable')
                actual.append(bind(m['Source'], m['Destination']))
            elif m['Type'] == 'volume' and m['Name'] in self.volumes:
                self.owned('volume', m['Name'], 'logs')
                actual.append('type=volume,source=' + m['Name'] + ',target=' + m['Destination'] + ',volume-nocopy')
            else:
                raise ValueError('Unexpected service mount')
        if sorted(actual) != sorted(self.expected[service]):
            raise ValueError('Restored service mount set differs')
        return item

    def exec(self, service, program, *args):
        self.check_container(service)
        return sql.docker('exec', '-i', self.names[service], program, *args)

    # Minimal adapter for the shared current-process module-file/console probe.
    def run(self, command, **kwargs):
        if command[:2] != ['docker', 'logs']:
            raise ValueError('Only trial Docker logs are supported')
        import subprocess
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise sql.DockerFailure('Trial Docker logs failed')
        return result.stdout

    def compose(self, state, *args, **kwargs):
        if args[:3] != ('exec', '-T', 'worldserver'):
            raise ValueError('Only the trial worldserver probe is supported')
        return self.exec('worldserver', *args[3:])

    def ready(self, timeout):
        deadline = time.monotonic() + timeout
        first = None
        last = {}
        progress_at = 0
        scale = '0.4' if self.candidate else '0.2'
        patterns = list(base.game.adv.ready_patterns({'advancement':{'version':self.advancement_version}})) + [
            'ForeverEncyclopedia ready:',
            'ForeverScaling ready: personal-virtual-v' + scale + ' (enabled=true'
        ]
        if self.candidate:
            patterns.append('ForeverDungeonFinder: direct-entry-v0.2 registered (enabled=true')
        while time.monotonic() < deadline:
            item = self.check_container('worldserver')
            if not item['State']['Running']:
                raise sql.TrialFailure('Restored worldserver stopped during initialization')
            identity = (item['Id'], item['State']['StartedAt'])
            if first is None:
                first = identity
            if first != identity:
                raise sql.TrialFailure('Restored worldserver restarted during readiness')
            last = module_readiness.snapshot(self, self.state, item)
            text = '\n'.join(last['lines'])
            failures = module_readiness.startup_failures(last)
            if failures:
                raise sql.TrialFailure('Restored module initialization failed: ' + '; '.join(failures[-6:]))
            if all(p in text for p in patterns):
                try:
                    self.exec('worldserver', 'python3', '-c',
                              "import socket; socket.create_connection(('127.0.0.1',8085),2).close()")
                    realm = self.db.sql('SELECT id,gamebuild,contentSetId,flag FROM auth.realmlist;').split()
                    if len(realm) == 4 and realm[:3] == ['70','70658','137'] and not int(realm[3]) & 2:
                        return last
                except sql.DockerFailure:
                    pass
            if time.monotonic() >= progress_at:
                missing = [p for p in patterns if p not in text]
                print('Waiting for restored world readiness; missing: ' + '; '.join(missing) if missing
                      else 'Waiting for restored world TCP 8085 and online realm...', flush=True)
                progress_at = time.monotonic() + 20
            time.sleep(3)
        raise sql.TrialFailure('Restored readiness timed out; missing: ' + ('; '.join(p for p in patterns if p not in '\n'.join(last.get('lines', []))) or 'TCP 8085 / online realm'))

    def probes(self):
        """Probe only internal aliases, verify restored CA and certificate hostname."""
        code = r'''
import hashlib,json,socket,ssl,urllib.request
result={}
for host,port in [('worldserver',8085),('bnetserver',1119)]:
    with socket.create_connection((host,port),5): pass
    result[host]=True
ctx=ssl.create_default_context(cafile='/opt/trinitycore/certs/ca/forever_root_ca.crt')
with socket.create_connection(('bnetserver',8081),5) as sock:
    with ctx.wrap_socket(sock,server_hostname='trinity.actual.battle.net') as tls:
        result['tls_verified']=bool(tls.getpeercert())
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://web:8000/healthz',timeout=5) as response:
    assert json.load(response).get('ok') is True
with opener.open('http://web:8000/api/status',timeout=5) as response:
    status=json.load(response)
    assert status.get('online') is True and isinstance(status.get('players'),int)
with opener.open('http://web:8000/forever_root_ca.crt',timeout=5) as response:
    result['served_ca_sha256']=hashlib.sha256(response.read()).hexdigest()
print(json.dumps(result))
'''
        result = json.loads(self.exec('bnetserver', 'python3', '-c', code))
        if result.get('served_ca_sha256') != base.clean.sha_file(self.ca) or not result.get('tls_verified'):
            raise ValueError('Restored TLS/web CA probe differs')
        return result

    def cleanup(self, force=False):
        if self.allocated or force:
            # Check ALL ownership (including DB) before any destructive action.
            found = [(kind, name) for kind, name, role in self.resources() if self.owned(kind, name, role)]
            self.db.owned('container'); self.db.owned('volume')
            for kind, name in found:
                if kind == 'network':
                    continue
                sql.docker(kind, 'rm', *(['--force', '--volumes'] if kind == 'container' else []), name)
            self.db.cleanup(force=force)
            if ('network', self.network) in found:
                sql.docker('network', 'rm', self.network)
        else:
            self.db.cleanup()
        # Only files under the newly allocated, nonce-checked private trial folder.
        for service in SERVICES:
            (self.folder / (service + '.private.env')).unlink(missing_ok=True)
        fs = self.folder / 'fs'
        if fs.exists():
            base.direct(fs)
            shutil.rmtree(fs)


def run_check(backup, work_parent, timeout=600, candidate=None):
    backup, work_parent = base.direct(backup), base.direct(work_parent)
    print('Verifying the existing server baseline...', flush=True)
    manifest = base.verify(backup)
    checked_manifest(manifest)
    # Keep the private restored files on the WSL/Linux filesystem, not Windows ACLs.
    if work_parent == Path('/mnt') or Path('/mnt') in work_parent.parents:
        raise ValueError('Use a Linux/WSL work directory outside /mnt for private restored files')
    if work_parent == Path(manifest['root']) or Path(manifest['root']) in work_parent.parents:
        raise ValueError('Trial work directory must be outside the saved live server root')
    work_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(backup / 'server-files.tar.gz', 'r|gz') as archive:
        required = sum(item.size for item in archive if item.isfile()) + 1024**3
    if shutil.disk_usage(work_parent).free < required:
        raise ValueError('Not enough space for the separate restored server files')
    nonce = secrets.token_hex(6)
    folder = work_parent / (PREFIX + nonce)
    folder.mkdir(mode=0o700)
    trial = ServicesTrial(manifest, folder, nonce, candidate=candidate) if candidate else ServicesTrial(manifest, folder, nonce)
    report_path = folder / 'report.json'
    report = dict(format=FORMAT, nonce=nonce, backup=str(backup), images=manifest['images'],
                  created_utc=datetime.now(timezone.utc).isoformat(), phase='prepared', candidate_image=candidate,
                  database_verified=False, services_verified=False, cleanup_verified=False,
                  client_login_verified=False, image_archive_load_tested=False,
                  full_server_restore_verified=False)
    def save():
        base.clean.write_private(report_path, report)
    save()
    try:
        trial.preflight()
        print('Restoring saved server files into a new private trial directory...', flush=True)
        unpack(backup / 'server-files.tar.gz', folder)
        trial.prepare_sources()
        trial.db.start()
        trial.db.require_space(sql.gzip_size(backup / 'databases-current.sql.gz'))
        print('Importing the saved four databases into the new trial volume...', flush=True)
        trial.db.restore(backup / 'databases-current.sql.gz')
        report['snapshot'], report['module_rows'] = sql.check_restored(trial.db, manifest['database_snapshot'])
        report['database_verified'] = True
        if candidate:
            trial.db.sql('USE characters;\n'+(base.game.ROOT/'mods/forever-advancement/sql/preferences.sql').read_text())
        report['phase'] = 'starting-services'; save()
        trial.attach_database()
        print('Starting restored world/login/web on an internal network; no host ports...', flush=True)
        for service in SERVICES:
            trial.create(service)
        report['world_readiness'] = trial.ready(timeout)
        if candidate:
            audit=trial.exec('worldserver','python3','-c',
                "from pathlib import Path; p=Path('/opt/trinitycore/logs/ForeverAdvancement-catalog.tsv'); assert p.stat().st_size<32*1024*1024; print(p.read_text(),end='')")
            audit_path=folder/'native-catalog.tsv'
            audit_path.write_text(audit);audit_path.chmod(0o600)
            report['native_catalog_audit']={'path':str(audit_path),'sha256':hashlib.sha256(audit.encode()).hexdigest(),'rows':max(0,len(audit.splitlines())-1)}
        deadline = time.monotonic() + 120
        while True:
            for service in SERVICES:
                if not trial.check_container(service)['State']['Running']:
                    raise sql.TrialFailure('Restored service stopped: ' + service)
            try:
                report['service_probes'] = trial.probes()
                break
            except sql.DockerFailure:
                if time.monotonic() >= deadline:
                    raise sql.TrialFailure('Restored TLS/web readiness timed out')
                time.sleep(3)
        # Recheck one process generation across world readiness and external probes.
        world = trial.check_container('worldserver')
        before = report['world_readiness']
        if (world['Id'],world['State']['StartedAt']) != (before['container'],before['startedAt']):
            raise sql.TrialFailure('Worldserver changed during final probes')
        report['services_verified'] = True
        report['phase'] = 'services-verified'; save()
    except BaseException as error:
        report['phase'] = 'failed'
        if trial.allocated:
            try:
                item = trial.owned('container', trial.names['worldserver'], 'worldserver')
                if item:
                    report['world_failure'] = module_readiness.snapshot(trial, trial.state, item, allow_stopped=True)
            except Exception:
                report['diagnostics_unavailable'] = True
        report['error'] = str(error) if isinstance(error, (ValueError, sql.DockerFailure, sql.TrialFailure)) else type(error).__name__
        save()
        print('Service trial diagnostics: ' + str(report_path), file=sys.stderr)
        raise
    finally:
        print('Removing only the labelled service trial and its private extracted files...', flush=True)
        try:
            trial.cleanup()
            report['cleanup_verified'] = True
            report['phase'] = 'verified' if report['services_verified'] else 'failed-cleaned'
            save()
        except BaseException:
            report['phase'] = 'cleanup-needed'; save()
            print('Service trial cleanup needs attention. Report: ' + str(report_path), file=sys.stderr)
            raise
    print(('CANDIDATE SERVICES VERIFIED: ' if candidate else 'RESTORED SERVICES VERIFIED: ') + str(report_path), flush=True)
    return report


def cleanup_report(path):
    path = base.direct(path)
    report = json.loads(path.read_text())
    if (report.get('format') != FORMAT or path.name != 'report.json'
            or path.parent.name != PREFIX + report.get('nonce', '')):
        raise ValueError('Unexpected service trial report path/identity')
    trial = ServicesTrial({'images': report['images']}, path.parent, report['nonce'])
    trial.cleanup(force=True)
    report['cleanup_verified'] = True
    report['phase'] = 'verified' if report.get('services_verified') else 'failed-cleaned'
    base.clean.write_private(path, report)
    print('SERVICE TRIAL CLEANUP VERIFIED: ' + str(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--backup', type=Path)
    choice.add_argument('--cleanup-report', type=Path)
    p.add_argument('--work-parent', type=Path, default=Path.home() / 'WoWForEver-restore-trials')
    p.add_argument('--candidate-image', help='Trial an exact verified local gameplay image on a restored clone')
    p.add_argument('--timeout', type=int, default=600)
    args = p.parse_args()
    if not 60 <= args.timeout <= 1800:
        p.error('--timeout must be between 60 and 1800 seconds')
    os.umask(0o077)
    lock_path = Path.home() / '.cache/forever-restore-test.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.cleanup_report:
            cleanup_report(args.cleanup_report)
        else:
            run_check(args.backup, args.work_parent, args.timeout, args.candidate_image)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        main()
    except KeyboardInterrupt:
        print('Service trial interrupted; check the report for cleanup status.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, sql.DockerFailure, sql.TrialFailure)) else type(error).__name__
        print('Service trial failed: ' + message + '. Live server was not modified.', file=sys.stderr)
        raise SystemExit(1)
