#!/usr/bin/env python3
"""Capture the active 70658 server without rebuilding or changing its profile.

Runtime writers pause only for the logical database snapshot. Large resource and
image exports run after the original services have resumed. No restore action.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import stat
import sys
import tarfile

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('baseline_gameplay', SCRIPTS / 'enable-clean-gameplay.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)
clean, upgrade = game.clean, game.upgrade
FORMAT = 'forever-server-baseline-v1'
RUNTIME = ('web', 'bnetserver', 'worldserver')
SERVICES = ('mysql', 'worldserver', 'bnetserver', 'web')
MARKERS = (game.MARKER, game.adv.MARKER, '.upgrade-in-progress.json')


def direct(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Linked backup/source paths are unsupported')
    return path.resolve()


def files_below(path):
    path = direct(path)
    mode = path.stat().st_mode
    if stat.S_ISREG(mode):
        return [path]
    if not stat.S_ISDIR(mode):
        raise ValueError('Only regular files and directories can be saved')
    result = [path]
    def unreadable(error):
        raise error
    for base, dirs, files in os.walk(path, followlinks=False, onerror=unreadable):
        for name in dirs + files:
            item = direct(Path(base) / name)
            if item.is_file() or item.is_dir():
                result.append(item)
            else:
                raise ValueError('Special files cannot be saved')
    return result


def controller_checkout(root):
    lines = (root / 'server.sh').read_text().splitlines()
    if len(lines) != 2 or lines[0] != '#!/bin/sh':
        raise ValueError('Unrecognized server controller; no service changed')
    command = shlex.split(lines[1])
    if (len(command) != 6 or command[:2] != ['exec', 'python3']
            or command[3:] != ['$@', '--root', str(root)]):
        raise ValueError('Unrecognized server controller; no service changed')
    script = direct(command[2])
    if script.name != 'clean-forever-server.py' or script.parent.name != 'scripts':
        raise ValueError('Unrecognized controller source')
    return script.parent.parent


def checkout_files(checkout):
    listing = clean.run(['git', '-C', str(checkout), 'ls-files', '-z'], capture=True)
    files = []
    for name in listing.split('\0'):
        if not name:
            continue
        part = Path(name)
        if part.is_absolute() or '..' in part.parts or '.git' in part.parts:
            raise ValueError('Unsafe checkout path')
        item = direct(checkout / part)
        if not item.is_file():
            raise ValueError('A tracked controller source is missing')
        files.append(item)
    if not files:
        raise ValueError('Empty controller checkout')
    return files


def collect_sources(root, state, model):
    files = set()
    # The active generation's mounts only: extractor points to the game client.
    for service in SERVICES:
        for mount in model['services'][service].get('volumes', []):
            if not isinstance(mount, dict):
                raise ValueError('Expected structured owned Compose mounts')
            if mount.get('type') == 'bind':
                source = direct(mount['source'])
                if any(source == Path(state['client'].get(k, '/__absent__'))
                       for k in ('source', 'test', 'game_dir')):
                    raise ValueError('Client mount cannot be included in server backup')
                files.update(files_below(source))
    for path in (root / 'state.json', root / 'compose.private.json', root / 'server.sh'):
        files.update(files_below(path))
    if (root / 'overrides').exists():
        files.update(files_below(root / 'overrides'))
    # Preserve the rollback record as well as current settings, separately from
    # the new post-install dump. Do not reinterpret an old dump as current data.
    record = direct(state['gameplay']['backup'])
    if record.parent.parent != root / 'advancement' or record.name != 'install.json':
        raise ValueError('Unexpected current gameplay record')
    files.update(files_below(record.parent))
    checkouts = {controller_checkout(root), SCRIPTS.parent}
    for checkout in checkouts:
        files.update(checkout_files(checkout))
    return sorted(files), sorted(map(str, checkouts))


def active_images(state):
    records, images, running = {}, {}, []
    for service in SERVICES:
        item = clean.container(state, service)
        labels = (item or {}).get('Config', {}).get('Labels', {})
        if (not item or labels.get('com.docker.compose.project') != state['project']
                or labels.get('com.docker.compose.service') != service):
            raise ValueError('Active container ownership mismatch')
        if not item['State']['Running']:
            raise ValueError('All four baseline services must be running before backup')
        if service in RUNTIME:
            running.append(service)
        identity = item['Image']
        image = game.adv.image(identity)
        if image['Id'] != identity:
            raise ValueError('Docker image identity mismatch')
        if service == 'worldserver':
            game.check_image(image, state, candidate=True)
            if item['Config']['Image'] != state['image']:
                raise ValueError('World image differs from saved state')
        images[identity] = image['Size']
        records[service] = {'id': identity, 'reference': item['Config']['Image']}
    return records, images, running


def pack_files(destination, files):
    with tarfile.open(destination, 'w:gz') as archive:
        for path in files:
            before = path.stat()
            archive.add(path, arcname='fs/' + str(path).lstrip('/'), recursive=False)
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns):
                raise RuntimeError('Source changed during backup; bundle is incomplete')


def artifact(path):
    return {'bytes': path.stat().st_size, 'sha256': clean.sha_file(path)}


def verify(folder):
    folder = direct(folder)
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('format') != FORMAT or manifest.get('complete') is not True:
        raise ValueError('Backup is incomplete')
    expected = {'databases-current.sql.gz', 'server-files.tar.gz', 'docker-images.tar', 'RESTORE.ru.txt'}
    if set(manifest.get('artifacts', {})) != expected:
        raise ValueError('Unexpected backup artifact set')
    for name, identity in manifest['artifacts'].items():
        path = direct(folder / name)
        if artifact(path) != identity:
            raise ValueError('Backup checksum/size mismatch: ' + name)
    with gzip.open(folder / 'databases-current.sql.gz', 'rb') as stream:
        while stream.read(1024 * 1024):
            pass
    with tarfile.open(folder / 'server-files.tar.gz', 'r|gz') as archive:
        for item in archive:
            if (not (item.isfile() or item.isdir()) or not item.name.startswith('fs/')
                    or '..' in Path(item.name).parts):
                raise ValueError('Unexpected server archive member')
            if item.isdir():
                continue
            stream = archive.extractfile(item)
            while stream.read(1024 * 1024):
                pass
    # Config hashes prove the exported archive contains the exact running images.
    with tarfile.open(folder / 'docker-images.tar', 'r:') as archive:
        entries = json.load(archive.extractfile('manifest.json'))
        found = set()
        for entry in entries:
            config = archive.extractfile(entry['Config']).read(8 * 1024 * 1024)
            found.add('sha256:' + hashlib.sha256(config).hexdigest())
        if found != {v['id'] for v in manifest['images'].values()}:
            raise ValueError('Exported Docker image identities differ')
    return manifest


RESTORE = '''Приватный снимок активного сервера 70658.

databases-current.sql.gz — новые четыре базы ПОСЛЕ установки модулей.
server-files.tar.gz — файлы активных bind mounts, настройки, сертификаты,
контроллер, его рабочие исходники и текущая запись отката. Пути внутри fs/.
docker-images.tar — четыре работающих образа (общие слои/образы сохранены один раз).
manifest.json — пути, идентичности образов, версии и контрольные суммы.

Проверка: backup-clean-baseline.py verify --backup ПУТЬ.
Сначала проверять восстановление в ОТДЕЛЬНОМ окружении: docker load, привязка
сохранённых ID к reference из manifest, восстановление файлов с корректировкой
путей controller/Compose и импорт SQL в НОВЫЙ MySQL-том. Исходный сервер и том
не заменять. После импорта проверить аккаунты, персонажей и все модули.
Сырые MySQL-тома и журналы не копировались. Клиент WoW не входит в этот серверный
снимок; его работающую установку и профиль лаунчера хранить отдельно.
Это проверка архива и его целостности, не проверенное восстановление базы.
Приватные пароли/ключи/SQL не публиковать и не присылать для обычной диагностики.
'''


def create(root, output):
    root, output = direct(root), direct(output)
    if str(output).startswith('/mnt/e/') and not os.path.ismount('/mnt/e'):
        raise ValueError('/mnt/e is not a mounted Windows drive; no backup started')
    if output == root or root in output.parents:
        raise ValueError('Backup destination must be outside the live server')
    if output.exists():
        raise ValueError('Backup destination already exists; it will not be overwritten')
    if any((root / name).exists() for name in MARKERS):
        raise ValueError('An unfinished server operation needs recovery first')
    state = game.network.checked(root)
    if not state.get('gameplay'):
        raise ValueError('This backup requires the active combined gameplay baseline')
    model = json.loads((root / 'compose.private.json').read_text())
    if model.get('name') != state['project']:
        raise ValueError('Compose project mismatch')
    clean.compose(state, 'config', '-q', capture=True)
    game.wait_module(state)
    images, image_sizes, running = active_images(state)
    files, checkouts = collect_sources(root, state, model)
    state_hash, compose_hash = clean.sha_file(root / 'state.json'), clean.sha_file(root / 'compose.private.json')
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(output == path or output in path.parents for path in files):
        raise ValueError('Backup destination overlaps archived sources')
    db_size = int(clean.sql(state, "SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES "
                           "WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes');").strip())
    required = sum(p.stat().st_size for p in files) + sum(image_sizes.values()) + 2 * db_size + 1024**3
    if shutil.disk_usage(output.parent).free < required:
        raise ValueError(f'Not enough backup space; estimated requirement {required / 1024**3:.1f} GiB')
    output.mkdir(mode=0o700)
    manifest = dict(format=FORMAT, complete=False, created_utc=datetime.now(timezone.utc).isoformat(),
                    core=state['core'], client_build=70658, root=str(root), images=images,
                    gameplay=state['gameplay'], controller_checkouts=checkouts,
                    resume_services=running, client_included=False, restore_tested=False, artifacts={})
    clean.write_private(output / 'manifest.json', manifest)
    resume = output / 'resume-required.json'
    clean.write_private(resume, {'root': str(root), 'services': running})
    try:
        print('Pausing world/login/web for the current four-database snapshot...', flush=True)
        clean.compose(state, 'stop', *running, capture=True)
        for service in running:
            if clean.container(state, service)['State']['Running']:
                raise RuntimeError('A runtime writer did not stop')
        manifest['database_snapshot'] = upgrade.snapshot(state)
        upgrade.dump_databases(state, output / 'databases-current.sql.gz')
    finally:
        # Also covers a partially failed stop, dump error, Ctrl-C and SIGTERM.
        print('Resuming the original services...', flush=True)
        clean.compose(state, 'start', *running, capture=True)
        game.wait_module(state)
        resume.unlink()
    print('Server resumed. Saving server resources and controller sources...', flush=True)
    pack_files(output / 'server-files.tar.gz', files)
    if (clean.sha_file(root / 'state.json') != state_hash
            or clean.sha_file(root / 'compose.private.json') != compose_hash):
        raise RuntimeError('Server configuration changed during backup')
    print('Exporting exact running Docker images; the server stays available...', flush=True)
    clean.run(['docker', 'image', 'save', '-o', str(output / 'docker-images.tar'), *image_sizes], capture=True)
    (output / 'RESTORE.ru.txt').write_text(RESTORE)
    for name in ('databases-current.sql.gz', 'server-files.tar.gz', 'docker-images.tar', 'RESTORE.ru.txt'):
        manifest['artifacts'][name] = artifact(output / name)
    manifest['complete'] = True
    clean.write_private(output / 'manifest.json', manifest)
    try:
        verify(output)
    except BaseException:
        manifest['complete'] = False
        clean.write_private(output / 'manifest.json', manifest)
        raise
    print('BASELINE BACKUP VERIFIED: ' + str(output), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('create', 'verify'))
    p.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    p.add_argument('--output', type=Path)
    p.add_argument('--backup', type=Path)
    args = p.parse_args()
    os.umask(0o077)
    if args.action == 'verify':
        if not args.backup:
            p.error('--backup is required')
        verify(args.backup)
        print('BASELINE BACKUP VERIFIED: ' + str(args.backup))
        return
    if not args.output:
        p.error('--output is required; use a new directory')
    lock_path = Path.home() / '.cache/forever-clean-control.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another clean-server operation is running')
        create(args.root, args.output)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except KeyboardInterrupt:
        print('Backup interrupted. Check service status and any resume-required.json before retrying.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        # Neither raw Docker stderr nor SQL/config exceptions belong in public logs.
        detail = str(error) if type(error) is ValueError else type(error).__name__
        print('Baseline backup failed (' + detail + '); incomplete files were retained. Check free space, service status, '
              'and resume-required.json. No restore or rebuild was performed.', file=sys.stderr)
        raise SystemExit(1)
