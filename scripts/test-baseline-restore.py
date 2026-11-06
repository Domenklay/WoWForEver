#!/usr/bin/env python3
"""Restore a verified baseline's four databases in a disposable, isolated MySQL.

No live Compose/state is read and no working service is stopped. The trial uses
the saved MySQL image ID, a new labelled volume, no network and no host ports.
This tests SQL restoration, not worldserver/client recovery.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('restore_baseline_backup', SCRIPTS / 'backup-clean-baseline.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
FORMAT = 'forever-baseline-database-trial-v1'
LABEL = 'org.wowforever.restore-trial'
PREFIX = 'forever-baseline-check-'
DATABASES = ('auth', 'world', 'characters', 'hotfixes')
MODULE_TABLES = ('forever_advancement_spells', 'forever_advancement_resources',
                 'forever_advancement_talents', 'forever_advancement_class_progress',
                 'forever_advancement_class_state', 'forever_encyclopedia_discovery',
                 'forever_encyclopedia_account', 'forever_encyclopedia_talent',
                 'forever_encyclopedia_character', 'forever_encyclopedia_appearance_selection')
SCHEMA_SQL = ("SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,"
              "COALESCE(COLUMN_DEFAULT,'<NULL>'),EXTRA FROM information_schema.COLUMNS "
              "WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes') "
              'ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION;\n')
COUNTS_SQL = ('SELECT COUNT(*) FROM auth.battlenet_accounts; SELECT COUNT(*) FROM auth.account; '
              'SELECT COUNT(*) FROM characters.characters;\n')
MYSQL = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names'


class DockerFailure(RuntimeError):
    pass


class TrialFailure(RuntimeError):
    """A deliberately public error, without SQL or credentials."""


def docker(*args, data=None, missing=False):
    result = subprocess.run(['docker', *args], input=data, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        if missing and re.search(r'no such (container|volume)', result.stderr, re.I):
            return None
        # Docker output can contain env/config values. Only report the operation.
        raise DockerFailure('Docker ' + ' '.join(args[:2]) + f' failed (exit {result.returncode})')
    return result.stdout


class MysqlTrial:
    def __init__(self, image, folder, nonce=None):
        if not re.fullmatch('sha256:[0-9a-f]{64}', image):
            raise ValueError('Invalid saved MySQL image ID')
        self.nonce = nonce or secrets.token_hex(6)
        if not re.fullmatch('[0-9a-f]{12}', self.nonce):
            raise ValueError('Invalid trial identity')
        self.name = PREFIX + self.nonce
        self.volume = self.name + '-data'
        self.image = image
        self.folder = baseline.direct(folder)
        self.env_file = self.folder / '.mysql-private.env'
        self.can_cleanup = False
        self.owns_env = False

    def owned(self, kind):
        name = self.name if kind == 'container' else self.volume
        output = docker(kind, 'inspect', name, missing=True)
        if output is None:
            return None
        item = json.loads(output)[0]
        labels = item['Config'].get('Labels', {}) if kind == 'container' else item.get('Labels', {})
        if labels.get(LABEL) != self.nonce or labels.get(LABEL + '.role') != kind:
            raise ValueError('Trial resource ownership mismatch; no resource removed')
        actual = item['Name'].lstrip('/')
        if actual != name:
            raise ValueError('Trial resource name mismatch')
        return item

    def start(self):
        info = json.loads(docker('image', 'inspect', self.image))[0]
        if info['Id'] != self.image or info.get('Os') != 'linux':
            raise ValueError('Saved MySQL image is unavailable or has another identity/platform')
        if self.owned('container') or self.owned('volume'):
            raise ValueError('Trial resources already exist; no existing resource reused')
        self.can_cleanup = True
        with self.env_file.open('x') as stream:
            self.owns_env = True
            os.chmod(self.env_file, 0o600)
            stream.write('MYSQL_ROOT_PASSWORD=' + secrets.token_hex(32) + '\n')
        docker('volume', 'create', '--label', LABEL + '=' + self.nonce,
               '--label', LABEL + '.role=volume', self.volume)
        docker('container', 'create', '--name', self.name, '--pull=never',
               '--label', LABEL + '=' + self.nonce, '--label', LABEL + '.role=container',
               '--network=none', '--restart=no', '--cpus=1', '--memory=1g',
               '--env-file', str(self.env_file),
               '--mount', 'type=volume,source=' + self.volume + ',target=/var/lib/mysql,volume-nocopy',
               self.image, '--skip-log-bin', '--event-scheduler=OFF',
               '--innodb-buffer-pool-size=128M', '--max-allowed-packet=1G',
               '--character-set-server=utf8mb4', '--collation-server=utf8mb4_unicode_ci')
        item = self.owned('container')
        host = item['HostConfig']
        mounts = item.get('Mounts', [])
        if (item['Image'] != self.image or host.get('NetworkMode') != 'none'
                or host.get('PortBindings') or host.get('Binds')
                or len(mounts) != 1 or mounts[0].get('Type') != 'volume'
                or mounts[0].get('Name') != self.volume or mounts[0].get('Destination') != '/var/lib/mysql'):
            raise ValueError('Trial isolation check failed; container was not started')
        docker('container', 'start', self.name)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            item = self.owned('container')
            if not item['State']['Running']:
                raise TrialFailure('Trial MySQL exited during initialization; live server is unchanged')
            try:
                # mysqladmin ping may succeed against the entrypoint's temporary
                # bootstrap mysqld. Require the actual server process as PID 1.
                ready = docker('exec', '-i', self.name, 'sh', '-c',
                               'test "$(cat /proc/1/comm)" = mysqld && ' + MYSQL,
                               data='SELECT 1;\n').strip()
                if ready == '1':
                    # Four-database dumps omit mysql users. Locked definers allow
                    # the clean server's trinity views/routines to be inspected,
                    # without importing the working server's credentials.
                    for host in ('%', 'localhost'):
                        self.sql("CREATE USER IF NOT EXISTS 'trinity'@'" + host + "' ACCOUNT LOCK;\n"
                                 + ''.join("GRANT ALL ON `" + db + "`.* TO 'trinity'@'" + host + "';\n"
                                           for db in DATABASES))
                    return
            except DockerFailure:
                pass
            time.sleep(2)
        raise TrialFailure('Trial MySQL initialization timed out')

    def sql(self, text):
        self.owned('container')
        return docker('exec', '-i', self.name, 'sh', '-c', MYSQL, data=text)

    def require_space(self, sql_bytes):
        self.owned('container')
        rows = docker('exec', self.name, 'df', '-Pk', '/var/lib/mysql').splitlines()
        if len(rows) != 2 or len(rows[1].split()) < 6:
            raise ValueError('Could not measure trial volume free space')
        available = int(rows[1].split()[3]) * 1024
        required = max(512 * 1024**2, 3 * sql_bytes)
        if available < required:
            raise ValueError(f'Not enough trial-volume space: {available / 1024**3:.1f} GiB free, '
                             f'{required / 1024**3:.1f} GiB estimated required')

    def restore(self, source):
        self.owned('container')
        errors = self.folder / 'mysql-import.private.log'
        with gzip.open(source, 'rb') as stream, errors.open('xb') as log:
            command = ['docker', 'exec', '-i', self.name, 'sh', '-c', MYSQL + ' --binary-mode=1']
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log) as process:
                try:
                    while block := stream.read(1024 * 1024):
                        process.stdin.write(block)
                    process.stdin.close()
                    code = process.wait()
                except BrokenPipeError:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                    code = process.wait() or 1
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        if code:
            text = errors.read_text(errors='replace')
            safe = re.search(r'ERROR\s+\d+(?:\s+\([A-Z0-9]+\))?(?:\s+at line\s+\d+)?', text)
            raise TrialFailure('Trial SQL import failed (exit ' + str(code) + ')'
                               + (': ' + safe[0] if safe else '; private import log retained'))

    def cleanup(self, force=False):
        # Inspect both objects BEFORE the first removal. A name by itself never
        # grants permission to delete a live Compose resource or another trial.
        if not (force or self.can_cleanup):
            return
        container, volume = self.owned('container'), self.owned('volume')
        if container:
            docker('container', 'rm', '--force', '--volumes', self.name)
        if volume:
            docker('volume', 'rm', self.volume)
        if force or self.owns_env:
            self.env_file.unlink(missing_ok=True)


def snapshot(trial):
    counts = trial.sql(COUNTS_SQL).split()
    if len(counts) != 3 or not all(v.isdecimal() for v in counts):
        raise ValueError('Restored account/character count query failed')
    schema = trial.sql(SCHEMA_SQL)
    return {'counts': counts, 'schema_sha256': baseline.upgrade.digest(schema)}


def check_restored(trial, expected):
    actual = snapshot(trial)
    if actual != expected:
        raise ValueError('Restored database counts or schema differ from the saved snapshot')
    modules = {}
    for table in MODULE_TABLES:
        value = trial.sql('SELECT COUNT(*) FROM characters.`' + table + '`;\n').strip()
        if not value.isdecimal():
            raise ValueError('Module table verification failed')
        modules[table] = int(value)
    return actual, modules


def gzip_size(path):
    total = 0
    with gzip.open(path, 'rb') as stream:
        while block := stream.read(1024 * 1024):
            total += len(block)
    return total


def run_check(backup):
    backup = baseline.direct(backup)
    print('Verifying the existing baseline archives...', flush=True)
    manifest = baseline.verify(backup)
    expected = manifest.get('database_snapshot')
    if (not isinstance(expected, dict) or set(expected) != {'counts', 'schema_sha256'}
            or not isinstance(expected['counts'], list) or len(expected['counts']) != 3
            or not all(isinstance(v, str) and v.isdecimal() for v in expected['counts'])
            or not re.fullmatch('[0-9a-f]{64}', expected.get('schema_sha256', ''))):
        raise ValueError('Backup has no valid database snapshot to compare against')
    sql_bytes = gzip_size(backup / 'databases-current.sql.gz')
    nonce = secrets.token_hex(6)
    folder = backup.parent / ('restore-test-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + nonce)
    folder.mkdir(mode=0o700)
    trial = MysqlTrial(manifest['images']['mysql']['id'], folder, nonce)
    report = dict(format=FORMAT, nonce=nonce, backup=str(backup), image=trial.image,
                  created_utc=datetime.now(timezone.utc).isoformat(), phase='prepared',
                  uncompressed_sql_bytes=sql_bytes,
                  data_verified=False, cleanup_verified=False, full_server_restore_verified=False)
    report_file = folder / 'report.json'
    def save():
        baseline.clean.write_private(report_file, report)
    save()
    try:
        report['phase'] = 'initializing'; save()
        print('Starting a disposable isolated MySQL; live services stay running...', flush=True)
        trial.start()
        trial.require_space(sql_bytes)
        report['phase'] = 'importing'; save()
        print('Restoring the four databases into the new trial volume...', flush=True)
        trial.restore(backup / 'databases-current.sql.gz')
        report['phase'] = 'checking'; save()
        report['snapshot'], report['module_rows'] = check_restored(trial, expected)
        report['data_verified'] = True
        report['phase'] = 'data-verified'; save()
    except BaseException as error:
        report['phase'] = 'failed'
        report['error'] = str(error) if isinstance(error, (ValueError, DockerFailure, TrialFailure)) else type(error).__name__
        save()
        raise
    finally:
        print('Removing only the labelled trial container and trial volume...', flush=True)
        try:
            trial.cleanup()
            report['cleanup_verified'] = True
            if report['data_verified']:
                report['phase'] = 'verified'
            save()
        except BaseException:
            report['phase'] = 'cleanup-needed'; save()
            print('Trial cleanup needs attention. Recovery report: ' + str(report_file), file=sys.stderr)
            raise
    print('DATABASE RESTORE VERIFIED: ' + str(report_file), flush=True)
    return report


def cleanup_report(path):
    path = baseline.direct(path)
    report = json.loads(path.read_text())
    if report.get('format') != FORMAT:
        raise ValueError('Unexpected trial report format')
    trial = MysqlTrial(report['image'], path.parent, report['nonce'])
    if (path.name != 'report.json' or not path.parent.name.startswith('restore-test-')
            or not path.parent.name.endswith('-' + trial.nonce)):
        raise ValueError('Unexpected trial report path')
    trial.cleanup(force=True)
    report['cleanup_verified'] = True
    report['phase'] = 'verified' if report.get('data_verified') else 'failed-cleaned'
    baseline.clean.write_private(path, report)
    print('TRIAL CLEANUP VERIFIED: ' + str(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--backup', type=Path)
    group.add_argument('--cleanup-report', type=Path)
    args = p.parse_args()
    os.umask(0o077)
    lock_path = Path.home() / '.cache/forever-restore-test.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another isolated restore trial is running')
        if args.cleanup_report:
            cleanup_report(args.cleanup_report)
        else:
            run_check(args.backup)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except KeyboardInterrupt:
        print('Restore trial interrupted. Check its report for cleanup status.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        detail = str(error) if isinstance(error, (ValueError, DockerFailure, TrialFailure)) else type(error).__name__
        print('Restore trial failed: ' + detail + '. Live server was not modified.', file=sys.stderr)
        raise SystemExit(1)
