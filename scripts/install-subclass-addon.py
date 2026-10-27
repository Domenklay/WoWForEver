#!/usr/bin/env python3
"""Install only ForeverSubclass AddOn files. Does not touch CASC or executables."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def install(client,backup):
    client=Path(client).resolve(strict=True);backup=Path(backup).resolve()
    if not (client/'WowB.exe').is_file():raise ValueError('Expected _classic_beta_ folder with WowB.exe')
    source=Path(__file__).resolve().parents[1]/'mods/forever-subclass/addon/ForeverSubclass'
    addons=client/'Interface/AddOns';addons.mkdir(parents=True,exist_ok=True)
    target=addons/'ForeverSubclass'
    if target.is_symlink():raise ValueError('Refusing to replace a symlinked AddOn')
    backup.mkdir(parents=True,exist_ok=True)
    manifest=backup/'addon-install.json'
    if manifest.exists():raise FileExistsError(manifest)
    previous=target.exists()
    if previous:shutil.copytree(target,backup/'previous-addon',symlinks=True)
    report=dict(client=str(client),previous_existed=previous,installed_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()})
    manifest.write_text(json.dumps(report,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='.ForeverSubclass-',dir=addons) as temp:
        stage=Path(temp)/'addon';shutil.copytree(source,stage)
        old=Path(temp)/'previous'
        if previous:os.rename(target,old)
        try:os.rename(stage,target)
        except BaseException:
            if previous:os.rename(old,target)
            raise
    return target


def restore(backup):
    backup=Path(backup).resolve(strict=True)
    report=json.loads((backup/'addon-install.json').read_text())
    target=Path(report['client'])/'Interface/AddOns/ForeverSubclass'
    if target.is_symlink():raise ValueError('Refusing to replace a symlinked AddOn')
    if target.exists():
        saved=backup/'addon-before-restore'
        if saved.exists():raise FileExistsError(saved)
        shutil.copytree(target,saved,symlinks=True)
    with tempfile.TemporaryDirectory(prefix='.ForeverSubclass-restore-',dir=target.parent) as temp:
        staged=Path(temp)/'addon'
        if report['previous_existed']:shutil.copytree(backup/'previous-addon',staged,symlinks=True)
        old=Path(temp)/'current'
        had_current=target.exists()
        if had_current:os.rename(target,old)
        try:
            if report['previous_existed']:os.rename(staged,target)
        except BaseException:
            if had_current:os.rename(old,target)
            raise
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',type=Path)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    if args.restore:print('Restored:',restore(args.backup))
    else:
        if not args.client:parser.error('--client is required for installation')
        print('AddOn:',install(args.client,args.backup))
