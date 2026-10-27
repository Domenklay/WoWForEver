#!/usr/bin/env python3
"""Restore small CASC metadata in a rolled-back independent copy, with backup.

Close the game and all launchers first. Never writes to the source or data.NNN.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import uuid
from pathlib import Path


SPEC = importlib.util.spec_from_file_location('copy_canary', Path(__file__).with_name('casc-copy-canary.py'))
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)
META = re.compile(r'(?:[0-9a-f]{10}\.idx|[0-9a-f]{16}\.lru|shmem|RepairMarker\.psv)', re.I)
DATA = re.compile(r'data\.\d{3}')


def inspect(folder):
    metadata, archives = {}, {}
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1:
            raise ValueError(f'Unsupported linked/non-file storage entry: {path}')
        if DATA.fullmatch(path.name):
            with path.open('rb') as stream:
                head = hashlib.sha256(stream.read(4096)).hexdigest()
            archives[path.name] = (path.stat().st_size, head)
        elif META.fullmatch(path.name) and path.stat().st_size <= 32*1024*1024:
            metadata[path.name] = path.read_bytes()
        else:
            raise ValueError(f'Unsupported metadata entry: {path}')
    return metadata, archives


def restore(client):
    client, marker = canary.copy_identity(client)
    source = Path(marker['source']).resolve(strict=True)
    info = (source/'.build.info').read_bytes()
    if (info != (client/'.build.info').read_bytes() or
            canary.sha(info) != marker['sha256']['.build.info']):
        raise ValueError('Source/copy build info must match the verified copy baseline')
    if (client/'casc-canary-operations/active.json').exists():
        journal = json.loads(canary.operation_file(client).read_text())
        if journal.get('phase') != 'rolled_back':
            raise ValueError('Roll back the canary before restoring metadata')
    incoming, original_archives = inspect(source/'Data/data')
    current, copied_archives = inspect(client/'Data/data')
    if not original_archives or original_archives != copied_archives:
        raise ValueError('Archive sizes/first 4096 bytes differ; metadata-only restoration refused')
    if 'RepairMarker.psv' in incoming:
        raise ValueError('Source has a repair marker; do not use it as a healthy baseline')
    buckets = {int(name[:2], 16) for name in incoming if name.endswith('.idx')}
    if buckets != set(range(16)) or 'shmem' not in incoming:
        raise ValueError('Source must have all 16 index buckets and shmem')
    # Every source index must be one of the files verified during preparation.
    for name, body in incoming.items():
        if name.endswith('.idx') and marker['sha256'].get('Data/data/'+name) != canary.sha(body):
            raise ValueError(f'Source index differs from the verified baseline: {name}')
    if incoming == current:
        return None
    backup_root = client/'casc-metadata-recovery'
    if backup_root.is_symlink():
        raise ValueError('Linked backup directory')
    backup = backup_root/uuid.uuid4().hex
    backup.mkdir(parents=True)
    (backup/'before').mkdir()
    (backup/'staged').mkdir()
    for name, body in current.items():
        (backup/'before'/name).write_bytes(body)
    for name, body in incoming.items():
        target = backup/'staged'/name
        target.write_bytes(body)
        if target.read_bytes() != body:
            raise ValueError('Staged metadata verification failed')
    report = dict(format='wowforever-copy-metadata-recovery-v1', source=str(source), copy=str(client),
                  phase='prepared', archive_check='sizes and first 4096 bytes only; not full integrity',
                  before={name:canary.sha(body) for name,body in current.items()},
                  restored={name:canary.sha(body) for name,body in incoming.items()})
    canary.checkpoint(backup/'result.json', report)
    # Refuse if a game/launcher changed either snapshot while preparing.
    if (inspect(source/'Data/data') != (incoming, original_archives) or
            inspect(client/'Data/data') != (current, copied_archives) or
            (source/'.build.info').read_bytes() != info or
            (client/'.build.info').read_bytes() != info):
        raise ValueError('Storage changed; close games/launchers and retry')
    try:
        for name in current.keys() - incoming.keys():
            (client/'Data/data'/name).unlink()
        for name in incoming:
            os.replace(backup/'staged'/name, client/'Data/data'/name)
        if inspect(client/'Data/data') != (incoming, copied_archives):
            raise ValueError('Restored metadata verification failed')
    except BaseException:
        for name in incoming.keys() - current.keys():
            (client/'Data/data'/name).unlink(missing_ok=True)
        for name, body in current.items():
            (client/'Data/data'/name).write_bytes(body)
        report['phase'] = 'failed_restored_previous_metadata'
        canary.checkpoint(backup/'result.json', report)
        raise
    report['phase'] = 'restored'
    canary.checkpoint(backup/'result.json', report)
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    args = parser.parse_args()
    try:
        import fcntl
        import tempfile
        token = canary.sha(str(args.client.resolve()).casefold().encode())
        lock = Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')
        with lock.open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            backup = restore(args.client)
        print('COPY METADATA RESTORED' if backup else 'COPY METADATA ALREADY MATCHES SOURCE')
        if backup:
            print('Backup:', backup)
        print('Run the native control check, then test this copy WITHOUT applying the canary.')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'Restoration stopped: {error}\n')
