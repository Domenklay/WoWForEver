#!/usr/bin/env python3
"""Copy installed AddOns between separate clients, with backup and rollback.

Copies AddOns code only, never WTF/SavedVariables, CASC, executable or server data.
Close both game clients and addon updaters before running.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def inventory(folder):
    folder=Path(folder)
    if not folder.exists():return {}
    if folder.is_symlink() or not folder.is_dir():raise ValueError('Expected a real AddOns directory')
    result={}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():raise ValueError('Linked AddOn entries are unsupported: '+str(path))
        if path.is_file():result[path.relative_to(folder).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():raise ValueError('Unsupported AddOn entry: '+str(path))
    return result


def client_folder(path):
    p=Path(path).resolve(strict=True)
    if not (p/'WowB.exe').is_file():raise ValueError('Client folder must contain WowB.exe: '+str(p))
    for sub in (p/'Interface',p/'Interface/AddOns'):
        if sub.is_symlink():raise ValueError('Linked Interface/AddOns folders are unsupported')
    return p


def replace_addons(source,target,expected):
    """Stage/verify before switching; preserve the previous directory until verification."""
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.addon-copy-',dir=target.parent) as temp:
        stage=Path(temp)/'next';old=Path(temp)/'previous'
        if source is not None:shutil.copytree(source,stage)
        if inventory(stage)!=expected:raise ValueError('Staged AddOns differ from snapshot')
        had_target=target.exists()
        if had_target:os.replace(target,old)
        try:
            if source is not None:os.replace(stage,target)
            if inventory(target)!=expected:raise ValueError('Installed AddOns failed verification')
        except BaseException:
            if target.exists():shutil.rmtree(target)
            if had_target:os.replace(old,target)
            raise


def copy_addons(source_client,target_client,backup):
    source_client=client_folder(source_client);target_client=client_folder(target_client)
    if source_client==target_client or source_client.is_relative_to(target_client) or target_client.is_relative_to(source_client):
        raise ValueError('Source and target clients must be independent directories')
    source=source_client/'Interface/AddOns';target=target_client/'Interface/AddOns'
    if not source.is_dir():raise ValueError('Source has no installed AddOns directory')
    expected=inventory(source)
    if not any(name.lower().endswith('.toc') for name in expected):raise ValueError('Source contains no AddOn .toc files')
    before=inventory(target);had_target=target.exists()
    backup=Path(backup).resolve()
    if any(backup.is_relative_to(c) for c in (source_client,target_client)):
        raise ValueError('Backup must be outside both clients')
    if backup.exists():raise FileExistsError('Use a new backup directory: '+str(backup))
    backup.mkdir(parents=True)
    if had_target:
        shutil.copytree(target,backup/'before')
        if inventory(backup/'before')!=before:raise ValueError('Backup verification failed')
    report=dict(format='wowforever-addon-copy-v1',source_client=str(source_client),target_client=str(target_client),
                previous_existed=had_target,before_files=before,copied_files=expected,phase='backed_up',
                source_modified=False,client_game_data_modified=False,server_modified=False)
    manifest=backup/'addon-copy.json';manifest.write_text(json.dumps(report,indent=2)+'\n')
    if inventory(source)!=expected or inventory(target)!=before:raise ValueError('AddOns changed during backup; close games/updaters')
    replace_addons(source,target,expected)
    report['phase']='verified';manifest.write_text(json.dumps(report,indent=2)+'\n')
    print('Copied installed AddOns:')
    for name in sorted({p.split('/')[0] for p in expected if p.lower().endswith('.toc')}):print('  '+name)
    print('Target:',target);print('Backup:',backup)
    return report


def restore(backup):
    backup=Path(backup).resolve(strict=True)
    report=json.loads((backup/'addon-copy.json').read_text())
    if report.get('format')!='wowforever-addon-copy-v1' or report.get('phase') not in {'backed_up','verified'}:
        raise ValueError('Expected a completed addon-copy backup')
    client=client_folder(report['target_client'])
    if client==Path(report['source_client']).resolve():raise ValueError('Restore cannot target the original source client')
    target=client/'Interface/AddOns'
    old=backup/'before' if report['previous_existed'] else None
    if (old is not None and inventory(old)!=report['before_files']) or (old is None and report['before_files']):
        raise ValueError('Original backup was changed')
    # Preserve edits made after synchronization instead of discarding them.
    recovery=backup/'after-before-restore'
    if recovery.exists():raise FileExistsError('This backup was already used for a restore')
    current=inventory(target)
    if target.exists():
        shutil.copytree(target,recovery)
        if inventory(recovery)!=current:raise ValueError('Current AddOns backup failed')
    replace_addons(old,target,report['before_files'])
    print('Restored:',target)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path);p.add_argument('--target',type=Path);p.add_argument('--backup',type=Path)
    p.add_argument('--restore',type=Path)
    a=p.parse_args()
    try:
        if a.restore:
            if a.source or a.target or a.backup:p.error('--restore cannot be combined with copy options')
            restore(a.restore)
        else:
            if not all((a.source,a.target,a.backup)):p.error('--source, --target and --backup are required')
            copy_addons(a.source,a.target,a.backup)
    except (ValueError,OSError,KeyError) as e:p.exit(1,'AddOn copy stopped: '+str(e)+'\n')
