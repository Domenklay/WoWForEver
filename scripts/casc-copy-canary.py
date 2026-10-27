#!/usr/bin/env python3
"""Reversible, native-verified canary in a prepared client COPY only.

Adds an original text resource, not Legion terrain. Existing data/config/index
files are never overwritten. Only the copy's .build.info is switched atomically.
"""
import argparse
import csv
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import struct
import tempfile
import uuid
from pathlib import Path

from casc_download import append_download
from casc_manifest_update import Encoding,append_root,extend_encoding,root_groups

SPEC=importlib.util.spec_from_file_location('canary_store',Path(__file__).with_name('update-casc-sandbox.py'))
storelib=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storelib)
lab=storelib.lab
BASE_KEY='ad1802f4455e427ed8b7769aab25b0c0'
CANARY_ID=16777214
CANARY_TEXT=b'WoWForEver independent-copy CASC canary v1\n'
CONTROLS={
    1120838:dict(bytes=485104,sha256='57401c9210015a0481dfd78452829d659920e410121aa65e3c2e0ce3ed095d8d'),
    1120853:dict(bytes=500044,sha256='a77f414875016ed8d20cb871739f9e0661afe947b625d7f10409031ba6cd4636'),
    1379264:dict(bytes=1632,sha256='0ef55a6e60acd18b5f78d037a99c668f1f3852c6cec7685aab3f71e3b1a15ab0'),
    1379316:dict(bytes=432,sha256='de16fbea697d21b27ad3041c1e5bd52a4dcac6fbb02156aff01c1d5783321a26')}


def sha(data):return hashlib.sha256(data).hexdigest()


def checkpoint(path,value):
    temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');os.replace(temp,path)


def copy_identity(path):
    path=Path(path).resolve(strict=True)
    marker=json.loads((path/'legion-client-copy.json').read_text())
    if (marker.get('format')!='wowforever-legion-client-copy-v1' or
            Path(marker['destination']).resolve()!=path or
            Path(marker['source']).resolve()==path):
        raise ValueError('Only an independently prepared client copy is accepted')
    for part in ('Data','.build.info','legion-client-copy.json'):
        p=path/part
        if p.is_symlink() or (p.is_file() and p.stat().st_nlink>1):raise ValueError('Linked copy is unsupported')
        original=Path(marker['source'])/part
        if original.exists() and p.exists() and os.path.samefile(original,p):
            raise ValueError('Copy aliases the original client')
    for p in (path/'Data').rglob('*'):
        if p.is_symlink() or (p.is_file() and p.stat().st_nlink>1):
            raise ValueError('Linked client data is unsupported')
    return path,marker


def operation_file(path):
    folder=path/'casc-canary-operations'
    if folder.is_symlink() or (folder/'active.json').is_symlink():raise ValueError('Linked operation directory')
    token=json.loads((folder/'active.json').read_text())['operation']
    if not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('Invalid operation identifier')
    target=folder/token/'operation.json'
    if target.parent.is_symlink() or target.is_symlink():raise ValueError('Linked operation journal')
    return target


def native_check(checker,path,expected):
    run=subprocess.run([str(Path(checker).resolve()),str(path),*map(str,expected)],
                       capture_output=True,text=True,timeout=600)
    rows=list(csv.DictReader(io.StringIO(run.stdout),delimiter='\t'))
    if run.returncode or len(rows)!=len(expected):
        raise ValueError('Native CascLib check failed: '+run.stderr+'\n'+run.stdout)
    actual={int(row['file_id']):row for row in rows}
    if set(actual)!=set(expected):raise ValueError('Native check returned unexpected file IDs')
    for fid,want in expected.items():
        row=actual[fid]
        if row['status']!='READ_OK' or int(row['bytes'])!=want['bytes'] or row['sha256']!=want['sha256']:
            raise ValueError(f'Native hash/size mismatch for {fid}: {row}')
        if 'tag_mask' not in row:raise ValueError('Native checker must expose tag_mask')
        int(row['tag_mask'],16)
        if 'tag_mask' in want and row['tag_mask']!=want['tag_mask']:
            raise ValueError(f'Native tag membership changed for {fid}')
    return rows


def rollback_files(path,journal_file):
    journal=json.loads(journal_file.read_text())
    if journal.get('format')!='wowforever-casc-canary-operation-v1' or journal.get('copy')!=str(path):
        raise ValueError('Operation journal belongs to another copy')
    for item in journal['files']:
        if (not re.fullmatch(r'Data/(?:data/(?:data\.\d{3}|[0-9a-f]{10}\.idx)|config/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32})',item['path']) or
                item['temporary']!=item['path']+'.'+journal_file.parent.name+'.tmp'):
            raise ValueError('Invalid operation file path')
    original=bytes.fromhex(journal['original_build_info_hex'])
    marker=json.loads((path/'legion-client-copy.json').read_text())
    if sha(original)!=marker['sha256']['.build.info']:raise ValueError('Original build info does not match copy baseline')
    current=(path/'.build.info').read_bytes()
    if sha(current) not in (sha(original),journal['new_build_info_sha256']):
        raise ValueError('Copy .build.info changed outside this operation; rollback refused')
    if current!=original:
        temp=journal_file.parent/'restore.build.info'
        temp.write_bytes(original);os.replace(temp,path/'.build.info')
    for item in reversed(journal['files']):
        target=path/item['path']
        if target.exists():
            if sha(target.read_bytes())!=item['sha256']:
                raise ValueError('Modified operation file retained: '+str(target))
            target.unlink()
        (path/item['temporary']).unlink(missing_ok=True)
    journal['phase']='rolled_back';checkpoint(journal_file,journal)


def apply(path,checker,controls=None,expected_build=BASE_KEY,progress=print):
    path,marker=copy_identity(path)
    operations=path/'casc-canary-operations'
    if operations.is_symlink():raise ValueError('Linked operation directory')
    if (operations/'active.json').exists():
        previous=json.loads(operation_file(path).read_text())
        if previous.get('phase')!='rolled_back':raise ValueError('A canary operation already exists; rollback first')
    controls=CONTROLS if controls is None else controls
    original=(path/'.build.info').read_bytes()
    if sha(original)!=marker['sha256']['.build.info']:
        raise ValueError('Copy build info differs from its verified baseline; rollback first')
    if marker['build_key']!=expected_build:raise ValueError('Unexpected copy build key')
    store=storelib.Store(path,synthetic_only=False)
    if store.build_key!=expected_build:raise ValueError('Unexpected active build key')
    if store.values.get('vfs-1')!=store.values.get('vfs-root'):
        raise ValueError('Unsupported distinct vfs-1/root profile; no changes made')
    progress('Checking existing control files with native CascLib...')
    before=native_check(checker,path,controls)
    def configured(name):
        keys=store.values[name].split()
        return store.read(bytes.fromhex(keys[1]),bytes.fromhex(keys[0]))
    progress('Validating original ENCODING and ROOT; preparing the canary...')
    encoding_bytes=configured('encoding');encoding=Encoding(encoding_bytes)
    root_ckey=bytes.fromhex(store.values['root'].split()[0]);root_ekey=None
    for key,raw in encoding.rows('c'):
        if key==root_ckey:root_ekey=raw[22:38]
    if root_ekey is None:raise ValueError('ROOT absent from ENCODING')
    old_root=store.read(root_ekey,root_ckey);old_vfs=configured('vfs-root')
    profiles={str(fid):[] for fid in controls}
    for group in root_groups(old_root):
        current=0
        for index,(delta,) in enumerate(struct.iter_unpack('<I',memoryview(old_root)[group['ids_offset']:group['ckeys_offset']])):
            current+=delta
            if current in controls:
                offset=group['ckeys_offset']+index*16
                profiles[str(current)].append(dict(locale=group['locale'],raw_flags=group['content_flags'],
                    combined_flags=group['flags'],has_names=group['has_names'],ckey=old_root[offset:offset+16].hex()))
            current+=1
    reference=storelib.tvfs.parse_tvfs(old_vfs)['leaves'].get('.root',[])
    if len(reference)!=1 or reference[0]['ckey']!=root_ckey.hex() or reference[0]['bytes']!=len(old_root) or reference[0]['offset']!=0:
        raise ValueError('Original TVFS .root reference mismatch')
    resource=lab.asset(CANARY_TEXT)
    root=lab.asset(append_root(old_root,{CANARY_ID:resource['ckey']},locale=0xffffffff))
    vfs=lab.asset(storelib.rebuild_tvfs(old_vfs,root,{CANARY_ID:resource},locale=0xffffffff))
    # Explicit empty tags for an inert canary only. No terrain tag policy is inferred.
    download=lab.asset(append_download(configured('download'),[
        dict(ekey=resource['ekey'],encoded_bytes=len(resource['encoded']),priority=0,tag_indices=[])]))
    additions=[resource,root,vfs,download]
    encoded=lab.asset(extend_encoding(encoding_bytes,additions));additions.append(encoded)
    # Fully validate the newly generated tables before making files visible.
    rebuilt=Encoding(encoded['content'])
    for _ in rebuilt.rows('c'):pass
    for _ in rebuilt.rows('e'):pass
    numbers=[int(p.name[5:]) for p in (path/'Data/data').glob('data.*') if re.fullmatch(r'data\.\d{3}',p.name)]
    segment=max(numbers)+1
    if segment>999 or segment>=(1<<(40-store.bits)):raise ValueError('No available data segment number')
    body=bytearray();extra={}
    for obj in additions:
        prefix=obj['ekey'][:9]
        if prefix in store.entries:
            if store.read(obj['ekey'],obj['ckey'])!=obj['content']:raise ValueError('Existing EKey prefix collision')
            continue
        if prefix in extra:raise ValueError('New EKey prefix collision')
        offset=len(body);record=lab.storage_record(obj,offset);body.extend(record)
        extra[prefix]=prefix+((segment<<store.bits)|offset).to_bytes(5,'big')+len(record).to_bytes(4,'little')
    if len(body)>1<<store.bits:raise ValueError('Canary segment exceeds IDX offset capacity')
    payloads={}
    if body:payloads[f'Data/data/data.{segment:03d}']=bytes(body)
    for number,bucket in store.buckets.items():
        new=[raw for key,raw in extra.items() if lab.bucket(key)==number]
        if not new:continue
        if bucket['version']>=0xffffffff:raise ValueError('IDX generation overflow')
        raw=bytearray(storelib.write_index(number,bucket['records']+new,store.bits,bucket['segment']))
        # Match the native two-seed entry checksum chain, not the lab fallback.
        high=low=0
        for record in sorted(bucket['records']+new):high,low=lab.hashlittle2(record,high,low)
        struct.pack_into('<I',raw,36,high)
        payloads[f'Data/data/{number:02x}{bucket["version"]+1:08x}.idx']=bytes(raw)
    values=dict(store.values)
    for name,obj in (('root',root),('encoding',encoded),('download',download),('vfs-root',vfs),('vfs-1',vfs)):
        values[name]=obj['ckey'].hex()+(' '+obj['ekey'].hex() if name!='root' else '')
        if name!='root':values[name+'-size']=f'{len(obj["content"])} {len(obj["encoded"])}'
    config='\n'.join(line.split(' = ',1)[0]+' = '+values[line.split(' = ',1)[0]] if ' = ' in line else line
                     for line in store.config.splitlines())+'\n'
    build=hashlib.md5(config.encode()).hexdigest()
    config_path=f'Data/config/{build[:2]}/{build[2:4]}/{build}'
    if (path/config_path).exists():
        if (path/config_path).read_bytes()!=config.encode():raise ValueError('Build config collision')
    else:payloads[config_path]=config.encode()
    store.csv[store.row][store.build_column]=build
    output=io.StringIO();csv.writer(output,delimiter='|',lineterminator='\n').writerows(store.csv)
    new_info=output.getvalue().encode()
    if shutil.disk_usage(path).free<sum(map(len,payloads.values()))+256*1024*1024:raise ValueError('Insufficient space for canary metadata')
    token=uuid.uuid4().hex;operations=path/'casc-canary-operations';operations.mkdir(exist_ok=True)
    folder=operations/token;folder.mkdir();journal_file=folder/'operation.json'
    journal=dict(format='wowforever-casc-canary-operation-v1',copy=str(path),phase='planned',
                 original_build_info_hex=original.hex(),new_build_info_sha256=sha(new_info),
                 original_build_key=store.build_key,new_build_key=build,files=[])
    for name,blob in payloads.items():
        if (path/name).exists():raise FileExistsError(path/name)
        journal['files'].append(dict(path=name,temporary=name+'.'+token+'.tmp',sha256=sha(blob)))
    checkpoint(journal_file,journal)
    checkpoint(operations/'active.json',dict(operation=token))
    try:
        progress(f'Appending {sum(map(len,payloads.values()))/1024**2:.1f} MiB; existing data files stay unchanged...')
        for item in journal['files']:
            temp=path/item['temporary'];target=path/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
            with temp.open('xb') as f:
                f.write(payloads[item['path']]);f.flush();os.fsync(f.fileno())
            if sha(temp.read_bytes())!=item['sha256']:raise ValueError('New file verification failed')
            if target.exists():raise FileExistsError(target)
            temp.rename(target)
        if (path/'.build.info').read_bytes()!=original:raise ValueError('Copy changed during canary preparation')
        switch=folder/'new.build.info';switch.write_bytes(new_info);os.replace(switch,path/'.build.info')
        journal['phase']='switched';checkpoint(journal_file,journal)
        masks={int(row['file_id']):row['tag_mask'] for row in before}
        expected={fid:dict(want,tag_mask=masks[fid]) for fid,want in controls.items()}
        expected[CANARY_ID]=dict(bytes=len(CANARY_TEXT),sha256=sha(CANARY_TEXT),tag_mask='0')
        progress('Verifying the new FileDataID and all previous controls with native CascLib...')
        after=native_check(checker,path,expected)
        journal['phase']='verified';checkpoint(journal_file,journal)
        result=dict(format='wowforever-casc-canary-result-v1',copy=str(path),original_build_key=store.build_key,
                    new_build_key=build,canary_file_id=CANARY_ID,canary_bytes=len(CANARY_TEXT),
                    canary_ckey=resource['ckey'].hex(),canary_sha256=sha(CANARY_TEXT),
                    native_before=before,native_after=after,root_profiles=profiles,operation=token,
                    original_client_modified=False,dalaran_installed=False,wow_client_runtime_verified=False)
        checkpoint(folder/'result.json',result)
        progress('CANARY VERIFIED: new FileDataID and existing control files read correctly.')
        progress(f'Report: {folder / "result.json"}')
        return result
    except BaseException:
        progress('Canary verification failed; reverting the copy...')
        rollback_files(path,journal_file)
        raise


def rollback(path):
    path,_marker=copy_identity(path)
    rollback_files(path,operation_file(path))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['apply','rollback'])
    parser.add_argument('client',type=Path)
    parser.add_argument('--checker',type=Path,default=Path(__file__).with_name('check-client-casc.sh'))
    args=parser.parse_args()
    lock=Path(tempfile.gettempdir())/('wowforever-casc-edit-'+sha(str(args.client.resolve()).casefold().encode())+'.lock')
    try:
        with lock.open('a') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='apply':apply(args.client,args.checker)
            else:rollback(args.client);print('CANARY ROLLED BACK')
    except (ValueError,OSError,KeyError,subprocess.TimeoutExpired) as error:
        parser.exit(1,f'Canary stopped: {error}\n')
    except KeyboardInterrupt:
        parser.exit(130,'Canary interrupted; use rollback if an operation journal remains.\n')
