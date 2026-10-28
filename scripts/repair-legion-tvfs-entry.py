#!/usr/bin/env python3
"""One-texture native TVFS namespace canary; no game payload or server changes.

Mirror the original texture's RU virtual entries INSIDE their native child
manifests. ROOT is intentionally unchanged. Confirm in-game before expanding
this experiment to a whole zone.
"""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import uuid

spec=importlib.util.spec_from_file_location('entry_install',Path(__file__).with_name('install-legion-resources.py'))
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)
storelib=install.canary.storelib
OLD_ID=123086
NEW_ID=15728640


def configured(store,name):
    ck,ek=store.values[name].split()[:2]
    return store.read(bytes.fromhex(ek),bytes.fromhex(ck))


def add_span(est,obj):
    spec=b'b:{*=n}\0';offset=0
    for value in est.split(b'\0')[:-1]:
        if value+b'\0'==spec:break
        offset+=len(value)+1
    else:offset=len(est);est+=spec
    return est,[dict(offset=0,bytes=len(obj['content']),ekey_prefix=obj['ekey'][:9].hex(),
                     encoded_bytes=len(obj['encoded']),content_bytes=len(obj['content']),
                     ckey=obj['ckey'].hex(),espec_offset=offset)]


def mirror_child(data,old_id=OLD_ID,new_id=NEW_ID):
    parsed=storelib.tvfs.parse_tvfs(data);leaves=parsed['leaves'];new=dict(leaves);mirrored=[]
    for name,spans in leaves.items():
        match=re.fullmatch(r'([0-9A-Fa-f]{8})([0-9A-Fa-f]{32})',name)
        if not match or int(match[1],16)!=old_id:continue
        target=f'{new_id:08X}'+match[2]
        if target in new:raise ValueError('Native child already contains the canary ID')
        new[target]=copy.deepcopy(spans)
        mirrored.append(dict(original=name,added=target,ckey=match[2].lower(),spans=len(spans)))
    if not mirrored:return None,[]
    encoded=storelib.encode_tvfs(new,parsed['tables']['est'],parsed['max_depth'])
    check=storelib.tvfs.parse_tvfs(encoded)['leaves']
    if any(check[name]!=spans for name,spans in leaves.items()):raise ValueError('Original child entries changed')
    return encoded,mirrored


def plan(store,progress=print,old_id=OLD_ID,new_id=NEW_ID):
    original=configured(store,'vfs-root');parsed=storelib.tvfs.parse_tvfs(original)
    leaves=copy.deepcopy(parsed['leaves']);est=parsed['tables']['est'];children=[];replacements={}
    vfs={}
    for key,value in store.values.items():
        if re.fullmatch(r'vfs-\d+',key):
            ck,ek=value.split()[:2];vfs.setdefault((ck,ek[:18]),[]).append((key,ek))
    # Resolve native submanifest entries from the build's own vfs-N catalogue.
    # Do not interpret ROOT flags as virtual path flags.
    for name,spans in parsed['leaves'].items():
        if not re.fullmatch(r'[0-9A-Fa-f]{16}',name) or not int(name[:8],16)&0x2000:continue
        if len(spans)!=1:raise ValueError('Unsupported multi-span directory reference')
        span=spans[0];matches=vfs.get((span['ckey'],span['ekey_prefix']),[])
        if not matches or len({ek for key,ek in matches})!=1:
            raise ValueError('Native RU directory is not consistently listed in build config: '+name)
        key,ek=matches[0]
        if span['offset']!=0:raise ValueError('Unsupported directory offset')
        progress('Reading native TVFS directory '+name+'...')
        data=store.read(bytes.fromhex(ek),bytes.fromhex(span['ckey']))
        if len(data)!=span['bytes']:raise ValueError('Native submanifest size mismatch')
        candidate,mirrored=mirror_child(data,old_id,new_id)
        if candidate is None:continue
        obj=install.canary.lab.asset(candidate)
        if not any(child['ekey']==obj['ekey'] for child in children):children.append(obj)
        est,leaves[name]=add_span(est,obj)
        replacements[name]=dict(obj=obj,source_config_key=key,old_value=store.values[key],directory=name,mirrored=mirrored)
    if not children:raise ValueError('No native RU TVFS entries found for the original texture; nothing changed')
    # The previous experiment placed a literal full virtual path at the top
    # level. Preserve other assets, but remove that route for this canary ID.
    removed=[]
    for name in list(leaves):
        m=re.fullmatch(r'[0-9A-Fa-f]{16}:([0-9A-Fa-f]{8})[0-9A-Fa-f]{32}',name)
        if m and int(m[1],16)==new_id:removed.append(name);del leaves[name]
    if len(removed)!=1:raise ValueError('Expected exactly one previous flat canary entry')
    candidate=storelib.encode_tvfs(leaves,est,parsed['max_depth'])
    return dict(original=original,candidate=candidate,children=children,replacements=replacements,removed=removed)


def apply(client,checker,progress=print,old_id=OLD_ID,new_id=NEW_ID):
    client,_=install.canary.copy_identity(client);parent_folder,parent=install.operation(client)
    if parent['phase']!='verified' or not parent.get('root_types_repaired') or parent.get('tvfs_entry_canary'):
        raise ValueError('Expected a verified type-repaired resource layer without this canary')
    expected={int(fid):row for fid,row in parent['expected_after'].items()}
    if new_id not in expected:raise ValueError('Canary texture is absent from the installed package')
    original=(client/'.build.info').read_bytes()
    if install.canary.sha(original)!=parent['after_info_sha256']:raise ValueError('Client build changed')
    before=install.scan(checker,client,expected,parent['locale'],progress);install.check_rows(before,expected)
    meta=install.container.metadata(client/'Data/data');store=storelib.Store(client,synthetic_only=False)
    if ('RepairMarker.psv' in meta or len(meta.get('shmem',b''))!=20480 or
            struct.unpack_from('<I',meta['shmem'])[0]!=5 or
            list(struct.unpack_from('<16I',meta['shmem'],0x110))!=[store.buckets[i]['version'] for i in range(16)] or
            store.values.get('vfs-1')!=store.values.get('vfs-root')):
        raise ValueError('Client metadata is inconsistent; close game and launcher')
    prepared_plan=plan(store,progress,old_id,new_id)
    old_root_ref=storelib.tvfs.parse_tvfs(prepared_plan['original'])['leaves']['.root']
    def change_vfs(data):
        if storelib.tvfs.parse_tvfs(data)['leaves']['.root']!=old_root_ref:
            raise ValueError('Legacy ROOT reference unexpectedly changed')
        return prepared_plan['candidate']
    controls={next(iter(expected)):expected[next(iter(expected))]}
    prepared,_=install.manifests(store,{}, {},before,controls,progress,root_transform=lambda root:root,
        vfs_transform=change_vfs,extra_assets=prepared_plan['children'])
    last=max(int(key[4:]) for key in store.values if re.fullmatch(r'vfs-\d+',key))
    registered={}
    # Keep every old registry entry. Other locales can still reference old
    # children; removing those keys would change their directory recognition.
    for row in prepared_plan['replacements'].values():
        obj=row['obj']
        if obj['ekey'] not in registered:
            last+=1;key=f'vfs-{last}';registered[obj['ekey']]=key
            store.values[key]=obj['ckey'].hex()+' '+obj['ekey'].hex()
            store.values[key+'-size']=f'{len(obj["content"])} {len(obj["encoded"])}'
            store.config+='\n'+key+' = '+store.values[key]+'\n'+key+'-size = '+store.values[key+'-size']+'\n'
        row['new_config_key']=registered[obj['ekey']]
    configuration=install.canary.resource_configuration(store,prepared)
    config=client/configuration['path'];created=not config.exists()
    if not created and config.read_bytes()!=configuration['body']:raise ValueError('Build config collision')
    prologues={}
    for p in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
        with p.open('rb') as stream:prologues[int(p.name[5:])]=stream.read(480)
    payloads,shared=install.plan_segment(meta,prologues,prepared['additions'])
    if any((client/'Data/data'/name).exists() for name in payloads):raise ValueError('Storage destination exists')
    if shutil.disk_usage(client).free<sum(map(len,payloads.values()))+sum(map(len,meta.values()))+256*1024**2:
        raise ValueError('Insufficient free disk space for the metadata layer and rollback')
    if (client/'.build.info').read_bytes()!=original or install.container.metadata(client/'Data/data')!=meta:
        raise ValueError('Client changed during preparation')
    token=uuid.uuid4().hex;folder=client/install.OPS/token;(folder/'before').mkdir(parents=True)
    for name,body in meta.items():(folder/'before'/name).write_bytes(body)
    (folder/'before.build.info').write_bytes(original)
    if ((folder/'before.build.info').read_bytes()!=original or
            any((folder/'before'/name).read_bytes()!=body for name,body in meta.items())):
        raise ValueError('Backup write failed')
    report_rows=[dict(directory=row['directory'],build_config_key=row['new_config_key'],
                     source_config_key=row['source_config_key'],mirrored=row['mirrored'])
                 for row in prepared_plan['replacements'].values()]
    journal=copy.deepcopy(parent)
    journal.update(phase='prepared',tvfs_entry_canary=True,tvfs_canary_original_id=old_id,tvfs_canary_new_id=new_id,
        root_policy='typed ROOT; one texture mirrored in native TVFS children; other flat routes unverified',
        tvfs_canary_directories=report_rows,before_info_sha256=install.canary.sha(original),
        after_info_sha256=install.canary.sha(configuration['build_info']),before={n:install.canary.sha(b) for n,b in meta.items()},
        added={n:dict(bytes=len(b),sha256=install.canary.sha(b)) for n,b in payloads.items()},
        generations=list(struct.unpack_from('<16I',shared,0x110)),new_build_key=configuration['build_key'],
        configuration=dict(path=configuration['path'],created=created,sha256=install.canary.sha(configuration['body'])),
        original_segments=sorted(prologues),resource_ancestors=list(parent.get('resource_ancestors',[]))+[parent_folder.name],
        wow_client_runtime_verified=False)
    install.canary.checkpoint(folder/'operation.json',journal)
    install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=token))
    progress('TVFS canary backup: '+str(folder))
    try:
        for name,body in payloads.items():
            with (client/'Data/data'/name).open('xb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
        tmp=folder/'new-shmem';tmp.write_bytes(shared);os.replace(tmp,client/'Data/data/shmem')
        if created:
            config.parent.mkdir(parents=True,exist_ok=True)
            with config.open('xb') as stream:stream.write(configuration['body'])
        tmp=folder/'new.build.info';tmp.write_bytes(configuration['build_info']);os.replace(tmp,client/'.build.info')
        journal['phase']='switched';install.canary.checkpoint(folder/'operation.json',journal)
        del prepared,payloads,store
        actual=install.verify(client,checker,progress)
        current=storelib.Store(client,synthetic_only=False)
        if configured(current,'vfs-root')!=prepared_plan['candidate']:raise ValueError('Installed root directory differs')
        for row in prepared_plan['replacements'].values():
            if configured(current,row['new_config_key'])!=row['obj']['content']:
                raise ValueError('Installed child directory differs')
        journal['phase']='verified';install.canary.checkpoint(folder/'operation.json',journal)
    except BaseException:
        install.rollback(client);install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=parent_folder.name))
        raise
    result=dict(format='wowforever-native-tvfs-entry-canary-v1',operation=token,original_id=old_id,new_id=new_id,
        directories=report_rows,native_verified_ids=len(actual),root_unchanged=True,server_modified=False,
        game_asset_payloads_unchanged=True,in_game_texture_render_verified=False)
    install.canary.checkpoint(folder/'result.json',result)
    progress('NATIVE TVFS ENTRY CANARY INSTALLED; repeat the texture comparison before teleporting.')
    progress('Report: '+str(folder/'result.json'))
    return result


def rollback(client):
    client,_=install.canary.copy_identity(client);folder,journal=install.operation(client)
    if not journal.get('tvfs_entry_canary'):raise ValueError('No active TVFS entry canary')
    install.rollback(client)
    install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=journal['resource_ancestors'][-1]))
    print('TVFS ENTRY CANARY ROLLED BACK; type repair and resource payloads retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['apply','rollback']);parser.add_argument('client',type=Path)
    parser.add_argument('--checker',type=Path,default=Path(__file__).with_name('check-client-casc.sh'))
    parser.add_argument('--report-dir',type=Path);args=parser.parse_args()
    try:
        token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='apply':
                apply(args.client,args.checker)
                from legion_reports import auto_collect
                auto_collect(args.client,args.report_dir)
            else:rollback(args.client)
    except (ValueError,OSError,KeyError,TypeError,struct.error) as error:
        parser.exit(1,'TVFS entry canary stopped: '+str(error)+'\n')
