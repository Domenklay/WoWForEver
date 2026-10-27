#!/usr/bin/env python3
"""Copy only Forever client trees into a new, independently verified experiment."""
import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

AUDITED_BUILD = 'ad1802f4455e427ed8b7769aab25b0c0'
PARTS = ('.build.info', 'Data', '_classic_beta_')


def inventory(source):
    files = {}
    for part in PARTS:
        start = source/part
        if start.is_symlink():
            raise ValueError(f'Symlinked source is unsupported: {start}')
        if part == '.build.info':
            if not start.is_file():
                raise ValueError(f'Missing {start}')
            paths = [start]
        else:
            if not start.is_dir():
                raise ValueError(f'Missing directory {start}')
            paths = []
            for folder, dirs, names in os.walk(start, followlinks=False):
                for name in dirs+names:
                    if (Path(folder)/name).is_symlink():
                        raise ValueError(f'Symlinked client path is unsupported: {Path(folder)/name}')
                paths.extend(Path(folder)/name for name in names)
        for path in paths:
            info = path.stat()
            if not path.is_file():
                raise ValueError(f'Unsupported client file: {path}')
            files[path.relative_to(source).as_posix()] = (info.st_size,info.st_mtime_ns,info.st_ino,info.st_dev)
    return files


def build_key(text):
    rows = list(csv.reader(io.StringIO(text), delimiter='|'))
    if not rows:
        raise ValueError('Empty .build.info')
    columns = {name.split('!')[0]:i for i,name in enumerate(rows[0])}
    if not {'Product','Active','Build Key'} <= columns.keys():
        raise ValueError('Unknown .build.info columns')
    if any(row and len(row)!=len(rows[0]) for row in rows[1:]):
        raise ValueError('Malformed .build.info row')
    matches = [row[columns['Build Key']] for row in rows[1:] if row and
               row[columns['Product']]=='wow_classic_beta' and row[columns['Active']]=='1']
    if len(matches)!=1 or len(matches[0])!=32:
        raise ValueError('Expected one active Classic Beta build')
    bytes.fromhex(matches[0])
    return matches[0].lower()


def prepare(source, output, expected_build=AUDITED_BUILD, progress=None):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Destination must be NEW: {output}')
    # The source can be E:\ itself; NEVER recursively copy the entire drive.
    # Reject aliases/case variants of selected client trees on NTFS as well.
    for part in PARTS:
        selected = source/part
        if output==selected or selected in output.parents:
            raise ValueError('Destination is inside a selected client tree')
        for parent in output.parents:
            if parent.exists() and selected.exists() and os.path.samefile(parent,selected):
                raise ValueError('Destination aliases a selected client tree')
    text = (source/'.build.info').read_text()
    actual = build_key(text)
    if actual!=expected_build.lower():
        raise ValueError(f'Build changed: expected {expected_build}, found {actual}')
    if not (source/'_classic_beta_/WowB.exe').is_file():
        raise ValueError('Missing _classic_beta_/WowB.exe')
    files = inventory(source)
    total = sum(row[0] for row in files.values())
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    free = shutil.disk_usage(ancestor).free
    if free < total+256*1024*1024:
        raise ValueError(f'Not enough free space: need {total+256*1024*1024} bytes, available {free}')
    if progress:
        progress(f'Copying {len(files)} files, {total/1024**3:.2f} GiB. Source client is read-only for this operation.')
    output.parent.mkdir(parents=True, exist_ok=True)
    copied, last = 0, time.monotonic()
    digests = {}
    with tempfile.TemporaryDirectory(prefix='.forever-client-copy-',dir=output.parent) as temp:
        stage = Path(temp)/'client'
        stage.mkdir()
        for name, info in sorted(files.items()):
            src, dst = source/name, stage/name
            dst.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with src.open('rb') as incoming, dst.open('xb') as outgoing:
                for block in iter(lambda:incoming.read(4*1024*1024),b''):
                    digest.update(block);outgoing.write(block);copied+=len(block)
                    if progress and time.monotonic()-last>=2:
                        progress(f'Copied {copied/1024**3:.2f}/{total/1024**3:.2f} GiB')
                        last=time.monotonic()
            verify = hashlib.sha256()
            with dst.open('rb') as incoming:
                for block in iter(lambda:incoming.read(4*1024*1024),b''):
                    verify.update(block)
            if verify.digest()!=digest.digest() or dst.stat().st_size!=info[0]:
                raise ValueError(f'Copy verification failed: {name}')
            os.utime(dst,ns=(src.stat().st_atime_ns,info[1]))
            os.chmod(dst,src.stat().st_mode & 0o777)
            digests[name] = digest.hexdigest()
        if inventory(source)!=files or (source/'.build.info').read_text()!=text:
            raise ValueError('Source changed during copy. Close the game/launcher before retrying.')
        report = dict(format='wowforever-legion-client-copy-v1',source=str(source),destination=str(output),
                      build_key=actual,files=len(files),bytes=total,copied_parts=list(PARTS),
                      verification='All copied files reread and SHA-256 checked; independent files, no hardlinks',
                      source_client_modified=False,game_data_patch_installed=False,
                      installation_supported=False,sha256=digests)
        (stage/'legion-client-copy.json').write_text(json.dumps(report,indent=2)+'\n')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    if progress:
        progress(f'COPY VERIFIED: {output}')
        progress(f'Test executable: {output / "_classic_beta_/WowB.exe"}')
    return report


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-build-key',default=AUDITED_BUILD)
    args = parser.parse_args()
    try:
        prepare(args.source,args.output,args.expected_build_key,lambda text:print(text,flush=True))
    except (ValueError,OSError) as error:
        parser.exit(1,f'Copy stopped: {error}\n')
