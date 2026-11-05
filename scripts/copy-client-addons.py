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


def client_folder(path,executable='WowB.exe'):
    p=Path(path).resolve(strict=True)
    if (not isinstance(executable,str) or Path(executable).name!=executable or '\\' in executable or
            not executable.casefold().endswith('.exe')):raise ValueError('Invalid client executable name')
    if not (p/executable).is_file():raise ValueError('Client folder must contain '+executable+': '+str(p))
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


def copy_addons(source_client,target_client,backup,source_executable='WowB.exe',target_executable='WowB.exe',merge=False):
    source_client=client_folder(source_client,source_executable);target_client=client_folder(target_client,target_executable)
    if source_client==target_client or source_client.is_relative_to(target_client) or target_client.is_relative_to(source_client):
        raise ValueError('Source and target clients must be independent directories')
    source=source_client/'Interface/AddOns';target=target_client/'Interface/AddOns'
    if not source.is_dir():raise ValueError('Source has no installed AddOns directory')
    source_expected=inventory(source);expected=source_expected
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
    install_source=source
    if merge:
        install_source=backup/'merged-source'
        if had_target:shutil.copytree(target,install_source)
        else:install_source.mkdir()
        for child in source.iterdir():
            dest=install_source/child.name
            if dest.is_dir():shutil.rmtree(dest)
            elif dest.exists():dest.unlink()
            if child.is_dir():shutil.copytree(child,dest)
            else:shutil.copy2(child,dest)
        expected=inventory(install_source)
        if any(expected.get(name)!=digest for name,digest in source_expected.items()):
            raise ValueError('Merged AddOns differ from the original source')
    report=dict(format='wowforever-addon-copy-v1',source_client=str(source_client),target_client=str(target_client),
                source_executable=source_executable,target_executable=target_executable,
                merge_source_addons=merge,
                previous_existed=had_target,before_files=before,copied_files=expected,phase='backed_up',
                source_modified=False,client_game_data_modified=False,server_modified=False)
    manifest=backup/'addon-copy.json';manifest.write_text(json.dumps(report,indent=2)+'\n')
    if inventory(source)!=source_expected or inventory(target)!=before:raise ValueError('AddOns changed during backup; close games/updaters')
    replace_addons(install_source,target,expected)
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
    client=client_folder(report['target_client'],report.get('target_executable','WowB.exe'))
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
