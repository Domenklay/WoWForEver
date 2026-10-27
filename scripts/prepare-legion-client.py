#!/usr/bin/env python3
"""Copy only Forever client trees into a new, independently verified experiment."""
import argparse
import csv
import fcntl
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
EXCLUDED_DIRS = {'cache','logs','errors','screenshots','gpucache','shadercache'}
EXCLUDED_SUFFIXES = ('.tmp','.temp','.log','.dmp')


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
                if part == '_classic_beta_':
                    if Path(folder) == start:
                        dirs[:] = [name for name in dirs if name.casefold() not in EXCLUDED_DIRS]
                    names = [name for name in names if not name.casefold().endswith(EXCLUDED_SUFFIXES)]
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


def file_hash(path, progress=None):
    digest = hashlib.sha256();read = 0;last = time.monotonic()
    with path.open('rb') as incoming:
        for block in iter(lambda:incoming.read(4*1024*1024),b''):
            digest.update(block);read+=len(block)
            if progress and time.monotonic()-last>=2:
                progress(f'Checking saved file {path.name}: {read/1024**3:.2f} GiB')
                last=time.monotonic()
    return digest.hexdigest()


def save_state(path, state):
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state)+'\n')
    os.replace(temp,path)


def checked_name(name):
    if not isinstance(name,str):
        raise ValueError('Invalid saved copy path')
    path = Path(name)
    if ('\\' in name or path.is_absolute() or
            '..' in path.parts or not path.parts or path.parts[0] not in PARTS or
            (path.parts[0]=='.build.info' and len(path.parts)!=1)):
        raise ValueError('Invalid saved copy path')
    return name


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
    # Validate the target BEFORE creating a lock or directory on its filesystem.
    # Keep advisory locks on WSL's Linux filesystem, not the Windows drive.
    token = hashlib.sha256(str(output).casefold().encode()).hexdigest()
    lock = Path(tempfile.gettempdir())/('wowforever-client-copy-'+token+'.lock')
    if lock.is_symlink():
        raise ValueError('Symlinked copy lock is unsupported')
    with lock.open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX | fcntl.LOCK_NB)
        return prepare_locked(source,output,expected_build,progress)


def prepare_locked(source, output, expected_build, progress):
    if output.exists():
        raise FileExistsError(f'Destination must be NEW: {output}')
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
    partial = output.with_name(output.name+'.partial')
    state_path = partial/'state.json'
    identity = dict(format='wowforever-client-copy-state-v1',source=str(source),destination=str(output),build_key=actual)
    if partial.is_symlink():
        raise ValueError('Symlinked partial directory is unsupported')
    if partial.exists():
        # Only resume our own checkpoint, never adopt an arbitrary directory.
        for folder,dirs,names in os.walk(partial,followlinks=False):
            if any((Path(folder)/name).is_symlink() for name in dirs+names):
                raise ValueError('Symlinked partial copy is unsupported')
        state = json.loads(state_path.read_text())
        if not isinstance(state,dict) or any(state.get(key)!=value for key,value in identity.items()):
            raise ValueError('Partial copy belongs to a different source/build/destination')
        if not isinstance(state.get('completed'),dict) or any(not isinstance(v,dict) for v in state['completed'].values()):
            raise ValueError('Invalid partial copy checkpoint')
        if progress:
            progress('Resuming saved copy; verifying completed files before reuse.')
    else:
        free = shutil.disk_usage(ancestor).free
        if free < total+256*1024*1024:
            raise ValueError(f'Not enough free space: need {total+256*1024*1024} bytes, available {free}')
        partial.mkdir(parents=True)
        state = dict(identity,completed={})
        save_state(state_path,state)
    stage = partial/'client';stage.mkdir(exist_ok=True)
    work = partial/'in-progress'
    # Unverified fragments are never reused or exposed inside the game tree.
    work.unlink(missing_ok=True)
    done = state['completed']
    for name in list(done):
        checked_name(name)
        if name not in files:
            (stage/name).unlink(missing_ok=True)
            del done[name]
    reusable = set()
    for name,info in files.items():
        saved = done.get(name,{})
        dst = stage/name
        if (saved.get('source_info')==list(info) and dst.is_file() and
                dst.stat().st_size==info[0] and file_hash(dst,progress)==saved.get('sha256')):
            reusable.add(name)
    remaining = sum(info[0] for name,info in files.items() if name not in reusable)
    free = shutil.disk_usage(ancestor).free
    if free < remaining+256*1024*1024:
        raise ValueError(f'Not enough free space: need {remaining+256*1024*1024} bytes, available {free}')
    if progress:
        progress(f'Client: {total/1024**3:.2f} GiB; verified files reused: {len(reusable)}; remaining to copy: {remaining/1024**3:.2f} GiB.')
    copied = sum(files[name][0] for name in reusable);last = time.monotonic()
    digests = {name:done[name]['sha256'] for name in reusable}
    try:
        for name, info in sorted(files.items()):
            if name in reusable:
                continue
            src, dst = source/name, stage/name
            dst.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with src.open('rb') as incoming, work.open('wb') as outgoing:
                for block in iter(lambda:incoming.read(4*1024*1024),b''):
                    digest.update(block);outgoing.write(block);copied+=len(block)
                    if progress and time.monotonic()-last>=2:
                        progress(f'Copied {copied/1024**3:.2f}/{total/1024**3:.2f} GiB')
                        last=time.monotonic()
            if file_hash(work,progress)!=digest.hexdigest() or work.stat().st_size!=info[0]:
                raise ValueError(f'Copy verification failed: {name}')
            os.replace(work,dst)
            os.utime(dst,ns=(src.stat().st_atime_ns,info[1]))
            os.chmod(dst,src.stat().st_mode & 0o777)
            digests[name] = digest.hexdigest()
            done[name] = dict(source_info=list(info),sha256=digests[name])
            save_state(state_path,state)
        if inventory(source)!=files or (source/'.build.info').read_text()!=text:
            raise ValueError('Source changed during copy. Close the game/launcher before retrying.')
        report = dict(format='wowforever-legion-client-copy-v1',source=str(source),destination=str(output),
                      build_key=actual,files=len(files),bytes=total,copied_parts=list(PARTS),
                      verification='All copied files reread and SHA-256 checked; independent files, no hardlinks',
                      source_client_modified=False,game_data_patch_installed=False,
                      installation_supported=False,sha256=digests,
                      excluded_client_dirs=sorted(EXCLUDED_DIRS),excluded_client_suffixes=list(EXCLUDED_SUFFIXES))
        (stage/'legion-client-copy.json').write_text(json.dumps(report,indent=2)+'\n')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    except BaseException:
        if progress:
            progress(f'Partial copy retained for the same command to resume: {partial}')
        raise
    try:
        state_path.unlink()
        partial.rmdir()
    except OSError:
        if progress:
            progress(f'Copy complete; temporary metadata remains in {partial}')
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
    except KeyboardInterrupt:
        parser.exit(130,'Copy interrupted. Saved progress can be resumed with the same command.\n')
    except (ValueError,OSError) as error:
        parser.exit(1,f'Copy stopped: {error}\n')
