#!/usr/bin/env python3
"""Read-only ROOT type comparison using installed resources and native WDT slots.

Writes a small metadata report, never game bytes or changes to the installation.
The result is evidence for a later repair, not a declaration of its cause.
"""
import argparse
from collections import Counter, defaultdict
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile

from casc_manifest_update import Encoding, root_groups

spec=importlib.util.spec_from_file_location('root_type_install',Path(__file__).with_name('install-legion-resources.py'))
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)
WDT_CONTROLS=(775971,782779)
MAID_ROLES=('terrain_root','terrain_obj0','terrain_obj1','terrain_tex0','terrain_lod',
            'terrain_map_texture','terrain_map_normal','terrain_minimap')
MPHD_ROLES=('map_lighting','map_occlusion','map_fogs','map_mpv','map_tex','map_wdl','map_pd4')


def profiles(root,wanted):
    found=defaultdict(list)
    for group in root_groups(root):
        fid=0
        for index,(delta,) in enumerate(struct.iter_unpack('<I',memoryview(root)[group['ids_offset']:group['ckeys_offset']])):
            fid+=delta
            if fid in wanted:
                offset=group['ckeys_offset']+16*index
                found[fid].append(dict(locale=group['locale'],raw_flags=group['content_flags'],
                                       ckey=root[offset:offset+16].hex()))
            fid+=1
    return dict(found)


def chunks(data):
    out={};offset=0
    while offset<len(data):
        if offset+8>len(data):raise ValueError('Truncated WDT chunk header')
        tag,size=struct.unpack_from('<4sI',data,offset);offset+=8
        if size>len(data)-offset or tag in out:raise ValueError('Invalid WDT chunk bounds or duplicate')
        out[tag]=data[offset:offset+size];offset+=size
    return out


def world_roles(data):
    parts=chunks(data)
    if (parts.get(b'REVM')!=struct.pack('<I',18) or len(parts.get(b'DHPM',b''))!=32 or
            len(parts.get(b'DIAM',b''))!=4096*32 or len(parts.get(b'NIAM',b''))!=4096*8):
        raise ValueError('Unsupported native WDT schema')
    result=defaultdict(set)
    for role,fid in zip(MPHD_ROLES,struct.unpack('<8I',parts[b'DHPM'])[1:]):
        if fid:result[role].add(fid)
    # Sampling several present cells is enough to observe metadata by role;
    # this does not establish asset dependency closure.
    present=[i for i in range(4096) if struct.unpack_from('<I',parts[b'NIAM'],8*i)[0]&1]
    for i in present[:16]:
        for role,fid in zip(MAID_ROLES,struct.unpack_from('<8I',parts[b'DIAM'],32*i)):
            if fid:result[role].add(fid)
    return dict(result)


def read_content(store,encoding,ckey):
    wanted=bytes.fromhex(ckey)
    for ck,row in encoding.rows('c'):
        if ck!=wanted:continue
        for n in range(row[0]):
            ek=row[22+16*n:38+16*n]
            if ek[:9] in store.entries:return store.read(ek,wanted)
        raise ValueError('Reference content has no local encoding')
    raise ValueError('Reference content is absent from ENCODING')


def audit(client,resource_report,output,progress=print):
    client,_=install.canary.copy_identity(client)
    _,journal=install.operation(client)
    info=(client/'.build.info').read_bytes()
    raw=Path(resource_report).read_bytes()
    if (journal['phase']!='verified' or install.canary.sha(info)!=journal['after_info_sha256'] or
            install.canary.sha(raw)!=journal['source_report_sha256']):
        raise ValueError('Installed resource batch and report no longer match')
    package=json.loads(raw)
    target_ids={fid for row in package['files'] if row['payload'] for fid in row['target_file_data_ids']}
    output=Path(output).resolve()
    if output.exists() or output.is_relative_to(client) or any(x.lower()=='data' for x in output.parts):
        raise ValueError('Choose a NEW report outside client/server data')
    progress('Reading active ROOT metadata without changing the client...')
    store=install.canary.storelib.Store(client,synthetic_only=False)
    ck,ek=store.values['encoding'].split()[:2]
    encoding=Encoding(store.read(bytes.fromhex(ek),bytes.fromhex(ck)))
    root=read_content(store,encoding,store.values['root'].split()[0])
    observed=profiles(root,target_ids|set(WDT_CONTROLS))
    if any(fid not in observed for fid in target_ids):raise ValueError('Installed private ID missing in ROOT')
    roles=defaultdict(set);reference_errors=[]
    for fid in WDT_CONTROLS:
        choices=[p for p in observed.get(fid,[]) if p['locale']&0x2000 and p['raw_flags'][0]==0]
        if not choices:
            reference_errors.append(dict(file_data_id=fid,error='No ordinary ruRU ROOT profile'));continue
        roles['map_wdt'].add(fid)
        try:
            data=read_content(store,encoding,choices[0]['ckey'])
            for role,ids in world_roles(data).items():roles[role].update(ids)
        except ValueError as error:reference_errors.append(dict(file_data_id=fid,error=str(error)))
    role_ids=set().union(*roles.values()) if roles else set()
    native=profiles(root,role_ids)
    rows=[]
    for row in package['files']:
        if row['payload']:
            rows.append(dict(path=row['path'],file_data_ids=row['target_file_data_ids'],
                             root_profiles={str(fid):observed[fid] for fid in row['target_file_data_ids']}))
    summary=Counter(tuple(p['raw_flags']) for fid in target_ids for p in observed[fid])
    references={role:[dict(file_data_id=fid,profiles=native.get(fid,[])) for fid in sorted(ids)]
                for role,ids in sorted(roles.items())}
    if (client/'.build.info').read_bytes()!=info:raise ValueError('Client build changed while reading; close game/launcher')
    result=dict(format='wowforever-legion-root-type-audit-v1',build_info_sha256=install.canary.sha(info),
                private_ids=len(target_ids),private_profile_counts=[dict(raw_flags=list(k),records=v) for k,v in summary.items()],
                private_resources=rows,native_world_roles=references,reference_errors=reference_errors,
                client_modified=False,server_modified=False,streaming_failure_cause_proven=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    progress('ROOT type report: '+str(output))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client',type=Path);parser.add_argument('--resource-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:
        token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            audit(args.client,args.resource_report,args.output)
    except (OSError,ValueError,KeyError,TypeError,struct.error) as error:
        parser.exit(1,'ROOT type audit stopped: '+str(error)+'\n')
