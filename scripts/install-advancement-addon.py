#!/usr/bin/env python3
"""Replace the old UI with ForeverAscension, keeping both old directories for rollback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

NAMES=('ForeverAscension','ForeverSubclass')
SOURCE=Path(__file__).parents[1]/'mods/forever-advancement/addon/ForeverAscension'


def addons_root(client):
    client=Path(client).resolve(strict=True)
    if not (client/'WowB.exe').is_file():raise ValueError('Expected client folder containing WowB.exe')
    interface=client/'Interface';addons=interface/'AddOns'
    if interface.is_symlink() or addons.is_symlink():raise ValueError('Symlinked Interface/AddOns is not supported')
    for name in NAMES:
        if (addons/name).is_symlink():raise ValueError('Symlinked AddOn is not supported')
    return client,addons


def install(client,backup):
    client,addons=addons_root(client);addons.mkdir(parents=True,exist_ok=True)
    backup=Path(backup).resolve()
    if backup.exists() and any(backup.iterdir()):raise FileExistsError(backup)
    backup.mkdir(parents=True,exist_ok=True)
    previous={name:(addons/name).exists() for name in NAMES}
    for name,exists in previous.items():
        if exists:shutil.copytree(addons/name,backup/name,symlinks=True)
    report={'client':str(client),'previous':previous,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.iterdir() if p.is_file()}}
    (backup/'advancement-addon.json').write_text(json.dumps(report,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='.ForeverAscension-',dir=addons) as temp:
        stage=Path(temp)/'new';shutil.copytree(SOURCE,stage)
        moved=[]
        try:
            for name,exists in previous.items():
                if exists:os.rename(addons/name,Path(temp)/name);moved.append(name)
            os.rename(stage,addons/'ForeverAscension')
        except BaseException:
            for name in reversed(moved):os.rename(Path(temp)/name,addons/name)
            raise
    return addons/'ForeverAscension'


def restore(backup):
    backup=Path(backup).resolve(strict=True)
    report=json.loads((backup/'advancement-addon.json').read_text())
    _,addons=addons_root(report['client'])
    # Preserve any user edits made after installation before restoring either UI.
    current=backup/'before-restore'
    if current.exists():raise FileExistsError(current)
    current.mkdir()
    for name in NAMES:
        if (addons/name).exists():shutil.copytree(addons/name,current/name,symlinks=True)
    with tempfile.TemporaryDirectory(prefix='.ForeverAscension-restore-',dir=addons) as temp:
        temp=Path(temp);moved=[];installed=[]
        for name,exists in report['previous'].items():
            if exists:shutil.copytree(backup/name,temp/('restore-'+name),symlinks=True)
        try:
            for name in NAMES:
                if (addons/name).exists():os.rename(addons/name,temp/name);moved.append(name)
            for name,exists in report['previous'].items():
                if exists:os.rename(temp/('restore-'+name),addons/name);installed.append(name)
        except BaseException:
            for name in installed:shutil.rmtree(addons/name)
            for name in moved:os.rename(temp/name,addons/name)
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--client',type=Path);p.add_argument('--backup',type=Path,required=True);p.add_argument('--restore',action='store_true');a=p.parse_args()
    if a.restore:restore(a.backup)
    elif a.client:print(install(a.client,a.backup))
    else:p.error('--client is required')
