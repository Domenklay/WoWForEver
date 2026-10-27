#!/usr/bin/env python3
"""Reversible native-container experiments in a prepared client COPY only.

Empty mode changes only container metadata; resource mode adds an own text and
updates manifests. Close all games/launchers. Original client is never written.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path

from casc_native_container import plan_empty_segment, plan_segment

SPEC = importlib.util.spec_from_file_location('container_canary', Path(__file__).with_name('casc-copy-canary.py'))
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)
META = re.compile(r'(?:[0-9a-f]{10}\.idx|[0-9a-f]{16}\.lru|shmem|RepairMarker\.psv)', re.I)


def checked_configuration(journal):
    value = journal.get('configuration')
    if value:
        key = journal['new_build_key']
        if (not re.fullmatch('[0-9a-f]{32}', key) or
                value['path'] != f'Data/config/{key[:2]}/{key[2:4]}/{key}'):
            raise ValueError('Invalid resource configuration path/key')
    return value


def metadata(folder):
    result = {}
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1:
            raise ValueError('Unsupported storage entry: '+str(path))
        if re.fullmatch(r'data\.\d{3}', path.name):
            continue
        if not META.fullmatch(path.name) or path.stat().st_size > 32*1024*1024:
            raise ValueError('Unsupported metadata entry: '+str(path))
        result[path.name] = path.read_bytes()
    return result


def active(client):
    root = client/'casc-container-operations'
    if root.is_symlink() or (root/'active.json').is_symlink():
        raise ValueError('Linked container journal')
    token = json.loads((root/'active.json').read_text())['operation']
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('Invalid container operation identifier')
    folder = root/token
    if folder.is_symlink() or (folder/'operation.json').is_symlink():
        raise ValueError('Linked container journal')
    journal = json.loads((folder/'operation.json').read_text())
    if journal.get('format') != 'wowforever-empty-container-operation-v1' or journal.get('copy') != str(client):
        raise ValueError('Container journal belongs to another copy')
    return folder, journal


def rollback(client):
    client, marker = canary.copy_identity(client)
    folder, journal = active(client)
    if journal['phase'] == 'rolled_back':
        return folder
    accepted = {marker['sha256']['.build.info'], journal.get('build_info_sha256')}
    if canary.sha((client/'.build.info').read_bytes()) not in accepted:
        raise ValueError('Build info changed outside the empty-segment experiment')
    original_info = None
    if journal.get('mode') == 'resource':
        original_info = (folder/'before.build.info').read_bytes()
        if canary.sha(original_info) != marker['sha256']['.build.info']:
            raise ValueError('Invalid original build info backup')
    configuration = checked_configuration(journal)
    parent = journal.get('parent_operation')
    if parent and not re.fullmatch('[0-9a-f]{32}', parent):
        raise ValueError('Invalid parent operation')
    old = {}
    if (folder/'before').is_symlink():
        raise ValueError('Linked backup')
    for name, digest in journal['before'].items():
        path = folder/'before'/name
        if not META.fullmatch(name) or path.is_symlink() or canary.sha(path.read_bytes()) != digest:
            raise ValueError('Invalid or modified metadata backup')
        old[name] = path.read_bytes()
    segment_name = journal['new_segment']
    previous_segments = journal['original_segments']
    if (not previous_segments or previous_segments != list(range(len(previous_segments))) or
            segment_name != f'data.{previous_segments[-1]+1:03d}' or
            segment_name not in journal['added']):
        raise ValueError('Invalid new segment name')
    # Preserve whatever the client changed, even if it pruned original IDX.
    current = metadata(client/'Data/data')
    quarantine = folder/('after-'+uuid.uuid4().hex)
    quarantine.mkdir()
    for name, body in current.items():
        (quarantine/name).write_bytes(body)
    for name, body in old.items():
        temp = folder/('restore-'+name)
        temp.write_bytes(body)
        os.replace(temp, client/'Data/data'/name)
    for name in current.keys()-old.keys():
        (client/'Data/data'/name).unlink()
    added = client/'Data/data'/segment_name
    if added.exists():
        os.replace(added, quarantine/segment_name)
    if original_info is not None:
        temp = folder/'restore.build.info'
        temp.write_bytes(original_info)
        os.replace(temp, client/'.build.info')
    if configuration and configuration['created']:
        target = client/configuration['path']
        if target.exists():
            os.replace(target, quarantine/'added-build-config')
    if metadata(client/'Data/data') != old:
        raise ValueError('Metadata restoration verification failed; backup retained')
    journal['phase'] = 'rolled_back'
    canary.checkpoint(folder/'operation.json', journal)
    if parent:
        canary.checkpoint(folder.parent/'active.json', dict(operation=parent))
    return folder


def apply(client, checker, controls=None, expected_build=canary.BASE_KEY, progress=print, resource=False):
    client, marker = canary.copy_identity(client)
    if marker['build_key'] != expected_build:
        raise ValueError('Unsupported client build')
    original = (client/'.build.info').read_bytes()
    if canary.sha(original) != marker['sha256']['.build.info']:
        raise ValueError('Restore the original copy build before this experiment')
    if (client/'casc-canary-operations/active.json').exists():
        old = json.loads(canary.operation_file(client).read_text())
        if old.get('phase') != 'rolled_back':
            raise ValueError('Roll back the old resource canary first')
    operations = client/'casc-container-operations'
    if operations.is_symlink():
        raise ValueError('Linked operation directory')
    parent = None
    if resource:
        previous_folder, previous = active(client)
        if previous['phase'] != 'verified' or previous.get('mode', 'empty') != 'empty':
            raise ValueError('Resource test requires a verified empty-segment experiment')
        progress('Confirming the installed empty segment before preparing the resource...')
        verify(client, checker)
        parent = previous_folder.name
    elif (operations/'active.json').exists() and active(client)[1]['phase'] != 'rolled_back':
        raise ValueError('An empty-container operation already exists; verify or rollback it')
    before = metadata(client/'Data/data')
    if 'RepairMarker.psv' in before:
        raise ValueError('Copy has a repair marker; restore metadata first')
    controls = canary.CONTROLS if controls is None else controls
    progress('Checking unchanged game resources with native CascLib...')
    baseline = canary.native_check(checker, client, controls)
    prologues = {}
    for path in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
        with path.open('rb') as incoming:
            prologues[int(path.name[5:])] = incoming.read(480)
    prepared = configuration = None
    if resource:
        progress('Preparing the own-text resource and consistent ROOT/ENCODING/TVFS/DOWNLOAD...')
        store = canary.storelib.Store(client, synthetic_only=False)
        if store.build_key != expected_build or store.values.get('vfs-1') != store.values.get('vfs-root'):
            raise ValueError('Unsupported active build/VFS profile')
        prepared = canary.prepare_resource(store, controls, progress)
        configuration = canary.resource_configuration(store, prepared)
        target = client/configuration['path']
        configuration['created'] = not target.exists()
        if target.exists() and target.read_bytes() != configuration['body']:
            raise ValueError('Build configuration collision')
    progress('Validating native header slots and preparing all 16 padded IDX (may take a minute)...')
    payloads, shared = (plan_segment(before, prologues, prepared['additions']) if resource
                        else plan_empty_segment(before, prologues))
    if any((client/'Data/data'/name).exists() for name in payloads):
        raise ValueError('Candidate path already exists; no files written')
    if shutil.disk_usage(client).free < sum(map(len, before.values()))+sum(map(len, payloads.values()))+256*1024*1024:
        raise ValueError('Insufficient free space for metadata, backups and reserve')
    if metadata(client/'Data/data') != before or (client/'.build.info').read_bytes() != original:
        raise ValueError('Copy changed during preparation; close the game and launchers')
    token = uuid.uuid4().hex
    folder = operations/token
    (folder/'before').mkdir(parents=True)
    for name, body in before.items():
        target = folder/'before'/name
        target.write_bytes(body)
        if target.read_bytes() != body:
            raise ValueError('Backup verification failed')
    segment_name = next(name for name in payloads if name.startswith('data.'))
    if resource:
        (folder/'before.build.info').write_bytes(original)
    journal = dict(format='wowforever-empty-container-operation-v1', copy=str(client), phase='prepared',
                   mode='resource' if resource else 'empty', parent_operation=parent,
                   before={name:canary.sha(body) for name,body in before.items()},
                   added={name:canary.sha(body) for name,body in payloads.items()},
                   added_sizes={name:len(body) for name,body in payloads.items()},
                   original_segments=sorted(prologues),
                   new_segment=segment_name, expected_generations=list(struct.unpack_from('<16I', shared, 0x110)),
                   native_before=baseline, game_resources_changed=False,
                   wow_client_runtime_verified=False)
    if resource:
        journal.update(build_info_sha256=canary.sha(configuration['build_info']),
                       new_build_key=configuration['build_key'],
                       configuration=dict(path=configuration['path'], created=configuration['created'],
                                          sha256=canary.sha(configuration['body'])),
                       canary_file_id=canary.CANARY_ID, root_profiles=prepared['profiles'],
                       manifests_changed=True)
    canary.checkpoint(folder/'operation.json', journal)
    canary.checkpoint(operations/'active.json', dict(operation=token))
    try:
        for name, body in payloads.items():
            with (client/'Data/data'/name).open('xb') as outgoing:
                outgoing.write(body)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        temp = folder/'new-shmem'
        temp.write_bytes(shared)
        os.replace(temp, client/'Data/data/shmem')
        if resource:
            target = client/configuration['path']
            if configuration['created']:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as outgoing:
                    outgoing.write(configuration['body'])
            if target.read_bytes() != configuration['body']:
                raise ValueError('Build configuration verification failed')
            if (client/'.build.info').read_bytes() != original:
                raise ValueError('Build info changed during resource preparation')
            temp = folder/'new.build.info'
            temp.write_bytes(configuration['build_info'])
            os.replace(temp, client/'.build.info')
        journal['phase'] = 'switched'
        canary.checkpoint(folder/'operation.json', journal)
        after = verify_files(client, folder, journal, checker)
        journal['phase'] = 'verified'
        journal['native_after'] = after
        canary.checkpoint(folder/'operation.json', journal)
    except BaseException:
        rollback(client)
        raise
    progress(('NATIVE RESOURCE VERIFIED: new FileDataID and old controls read correctly.' if resource else
              'EMPTY SEGMENT VERIFIED: native resource reads preserved; WowB.exe launch still requires testing.'))
    progress('Backup and report: '+str(folder))
    return journal


def verify_files(client, folder, journal, checker):
    for name, digest in journal['added'].items():
        if not re.fullmatch(r'(?:[0-9a-f]{10}\.idx|data\.\d{3})', name):
            raise ValueError('Invalid candidate filename')
        path = client/'Data/data'/name
        if path.stat().st_size != journal['added_sizes'][name] or canary.sha(path.read_bytes()) != digest:
            raise ValueError('Candidate file changed or disappeared: '+name)
    shared = (client/'Data/data/shmem').read_bytes()
    if len(shared) != 20480 or list(struct.unpack_from('<16I', shared, 0x110)) != journal['expected_generations']:
        raise ValueError('Active index generations changed')
    expected = {int(row['file_id']):dict(bytes=int(row['bytes']), sha256=row['sha256'], tag_mask=row['tag_mask'])
                for row in journal['native_before']}
    if journal.get('mode') == 'resource':
        configuration = checked_configuration(journal)
        if canary.sha((client/configuration['path']).read_bytes()) != configuration['sha256']:
            raise ValueError('Resource build configuration changed')
        expected[canary.CANARY_ID] = dict(bytes=len(canary.CANARY_TEXT),
                                        sha256=canary.sha(canary.CANARY_TEXT), tag_mask='0')
    return canary.native_check(checker, client, expected)


def verify(client, checker):
    client, marker = canary.copy_identity(client)
    folder, journal = active(client)
    if journal['phase'] != 'verified':
        raise ValueError('Empty-segment experiment is not installed')
    if canary.sha((client/'.build.info').read_bytes()) != journal.get('build_info_sha256', marker['sha256']['.build.info']):
        raise ValueError('Copy build info changed')
    return verify_files(client, folder, journal, checker)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'apply-resource', 'verify', 'rollback'])
    parser.add_argument('client', type=Path)
    parser.add_argument('--checker', type=Path, default=Path(__file__).with_name('check-client-casc.sh'))
    args = parser.parse_args()
    try:
        token = hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        lock = Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')
        with lock.open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action in ('apply', 'apply-resource'):
                apply(args.client, args.checker, resource=args.action == 'apply-resource')
            elif args.action == 'rollback':
                print('CONTAINER EXPERIMENT ROLLED BACK. Backup:', rollback(args.client))
            else:
                verify(args.client, args.checker)
                print('CONTAINER EXPERIMENT STILL VERIFIED; report actual game launch separately.')
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Empty-segment experiment stopped: {error}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Interrupted; close games/launchers and run the rollback action.\n')
