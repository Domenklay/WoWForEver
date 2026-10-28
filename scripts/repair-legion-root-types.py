#!/usr/bin/env python3
"""Journaled ROOT/TVFS type repair; preserves installed payloads and server state."""
import argparse
from collections import Counter,defaultdict
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

from casc_manifest_update import root_groups

spec=importlib.util.spec_from_file_location('type_repair_install',Path(__file__).with_name('install-legion-resources.py'))
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)


def world_role(path):
    for suffix,role in [('_tex0.adt','terrain_tex0'),('_obj0.adt','terrain_obj0'),('_obj1.adt','terrain_obj1'),
                        ('_lod.adt','terrain_lod'),('_lgt.wdt','map_lighting'),('_occ.wdt','map_occlusion'),
                        ('_fogs.wdt','map_fogs'),('_mpv.wdt','map_mpv'),('.adt','terrain_root'),
                        ('.wdt','map_wdt'),('.wdl','map_wdl'),('.tex','map_tex')]:
        if path.endswith(suffix):return role
    return None


def ordinary(profiles):
    result=[]
    for p in profiles:
        flags=p.get('raw_flags',[]);locale=p.get('locale',0)
        if len(flags)==3 and flags[0]==0 and locale&0x2000:
            result.append((locale,tuple(flags)))
    return result


def policies(report,namespace,audit,private):
    namespace_rows={r['target_file_data_id']:r for r in namespace['resources']}
    target_rows={fid:r for r in report['files'] if r['payload'] for fid in r['target_file_data_ids']}
    audit_rows={fid:r for r in audit['private_resources'] for fid in r['file_data_ids']}
    if set(private)!=set(target_rows) or set(private)!=set(audit_rows):raise ValueError('Private resource IDs disagree')
    # Missing original IDs inherit a predominant profile only for the SAME
    # parsed resource kind. WMO roots and group files are distinct kinds.
    pools=defaultdict(Counter)
    def kind(path):
        if path.endswith('.wmo'):return 'wmo_group' if re.search(r'_\d{3}\.wmo$',path) else 'wmo_root'
        return Path(path).suffix
    for row in namespace['resources']:
        pools[kind(row['path'])].update(ordinary(row['root_variants']))
    planned={};evidence=Counter()
    for fid,obj in private.items():
        row=target_rows[fid];old=namespace_rows.get(fid)
        if not old or old['path']!=row['path'] or old['original_file_data_id'] not in row['original_file_data_ids']:
            raise ValueError('Namespace binding mismatch')
        got=audit_rows[fid]
        if got['path']!=row['path'] or got['root_profiles'][str(fid)]!=[
                dict(locale=0xffffffff,raw_flags=[0x10000000,0,0],ckey=obj['ckey'].hex())]:
            raise ValueError('Expected an unchanged generic private ROOT entry')
        role=world_role(row['path'])
        if role:
            choices=set(ordinary([p for r in audit['native_world_roles'].get(role,[]) for p in r['profiles']]))
            if len(choices)!=1:raise ValueError('World role profile is absent or ambiguous: '+role)
            profile=next(iter(choices));evidence['native_world_slot']+=1
        else:
            choices=set(ordinary(old['root_variants']))
            if len(choices)==1:profile=next(iter(choices));evidence['original_id_profile']+=1
            elif not choices:
                body=obj['content']
                signature={'.m2':(b'MD20',b'MD21'),'.skin':(b'SKIN',),'.blp':(b'BLP1',b'BLP2')}.get(Path(row['path']).suffix)
                if signature and body[:4] not in signature:raise ValueError('Fallback resource kind does not match bytes')
                if row['path'].endswith('.wmo'):
                    # Native WMO roots have MOHD; group files have MOGP.
                    pos=0;tags=set()
                    while pos<len(body):
                        if pos+8>len(body):raise ValueError('Truncated WMO kind header')
                        tag,size=struct.unpack_from('<4sI',body,pos);pos+=8
                        if size>len(body)-pos:raise ValueError('Truncated WMO kind body')
                        tags.add(tag);pos+=size
                    wanted=b'PGOM' if kind(row['path'])=='wmo_group' else b'DHOM'
                    if wanted not in tags:raise ValueError('WMO root/group filename differs from its bytes')
                votes=pools[kind(row['path'])]
                if not votes:raise ValueError('Missing model-kind profile: '+row['path'])
                profile,count=votes.most_common(1)[0]
                if count*2<=sum(votes.values()):raise ValueError('No predominant model-kind profile')
                evidence['same_kind_profile']+=1
            else:raise ValueError('Ambiguous original profile: '+row['path'])
        locale,flags=profile
        # These private IDs are opened by ID. Keep the native type/storage
        # bits, explicitly adding hashless mode where a named source had it off.
        flags=(flags[0],flags[1]|0x10000000,flags[2])
        if any(not 0<=v<=limit for v,limit in zip(flags,(0xffffffff,0xffffffff,255))):
            raise ValueError('Invalid raw ROOT profile')
        planned[fid]=dict(locale=locale,raw_flags=flags,ckey=obj['ckey'].hex())
    return planned,dict(evidence)


def replace_root(data,planned):
    kept=[];removed={}
    for group in root_groups(data):
        ids=[];fid=0
        for (delta,) in struct.iter_unpack('<I',data[group['ids_offset']:group['ckeys_offset']]):
            fid+=delta;ids.append(fid);fid+=1
        selected=set(ids)&planned.keys()
        if not selected:kept.append(data[group['start']:group['end']]);continue
        if selected!=set(ids) or group['locale']!=0xffffffff or group['content_flags']!=[0x10000000,0,0]:
            raise ValueError('Private entries are mixed with original ROOT groups or already repaired')
        for i,fid in enumerate(ids):
            key=data[group['ckeys_offset']+16*i:group['ckeys_offset']+16*(i+1)].hex()
            if fid in removed or key!=planned[fid]['ckey']:raise ValueError('Private ROOT CKey mismatch')
            removed[fid]=key
    if removed.keys()!=planned.keys():raise ValueError('Not all requested private entries were replaced')
    groups=defaultdict(dict)
    for fid,p in planned.items():groups[(p['locale'],tuple(p['raw_flags']))][fid]=p['ckey']
    for (locale,flags),rows in sorted(groups.items()):
        block=struct.pack('<4IB',len(rows),locale,*flags);previous=0
        for fid in sorted(rows):block+=struct.pack('<I',fid-previous);previous=fid+1
        block+=b''.join(bytes.fromhex(rows[fid]) for fid in sorted(rows));kept.append(block)
    result=data[:24]+b''.join(kept)
    list(root_groups(result)) # Total/named counts are unchanged.
    return result


def tvfs_renamer(planned):
    seen=set()
    def change(name):
        match=re.fullmatch(r'FFFFFFFF10000000:([0-9A-F]{8})([0-9A-F]{32})',name)
        if not match:return name
        fid=int(match[1],16)
        if fid not in planned:return name
        p=planned[fid]
        if fid in seen or match[2].lower()!=p['ckey']:raise ValueError('TVFS private reference mismatch')
        seen.add(fid);f1,f2,f3=p['raw_flags'];flags=f1|f2|(f3<<17)
        return f'{p["locale"]:08X}{flags:08X}:{fid:08X}{p["ckey"].upper()}'
    return change,seen


def apply(client,report_path,namespace_path,audit_path,checker,progress=print):
    client,_=install.canary.copy_identity(client);parent_folder,parent=install.operation(client)
    if parent['phase']!='verified' or parent.get('root_types_repaired'):raise ValueError('Expected an unrepaired verified batch')
    original=(client/'.build.info').read_bytes()
    audit_bytes=Path(audit_path).read_bytes();audit=json.loads(audit_bytes)
    namespace_bytes=Path(namespace_path).read_bytes();namespace=json.loads(namespace_bytes)
    report,shared,private,objects,old_ids,report_hash=install.read_package(report_path)
    if (install.canary.sha(original)!=parent['after_info_sha256'] or
            report_hash!=parent['source_report_sha256'] or
            report['source_plan_sha256']!=install.canary.sha(namespace_bytes) or
            audit.get('format')!='wowforever-legion-root-type-audit-v1' or
            audit['build_info_sha256']!=install.canary.sha(original) or audit['reference_errors']):
        raise ValueError('Reports do not match the current resource layer')
    planned,evidence=policies(report,namespace,audit,private)
    expected={int(fid):row for fid,row in parent['expected_after'].items()}
    progress('Verifying all installed content before metadata repair...')
    before=install.scan(checker,client,expected,parent['locale'],progress);install.check_rows(before,expected)
    meta=install.container.metadata(client/'Data/data')
    if 'RepairMarker.psv' in meta:raise ValueError('Client has a repair marker')
    store=install.canary.storelib.Store(client,synthetic_only=False)
    shmem=meta['shmem']
    if (len(shmem)!=20480 or struct.unpack_from('<I',shmem)[0]!=5 or
            list(struct.unpack_from('<16I',shmem,0x110))!=[store.buckets[i]['version'] for i in range(16)]):
        raise ValueError('Active shmem differs from local IDX generations')
    if store.values.get('vfs-1')!=store.values.get('vfs-root'):raise ValueError('Unsupported distinct TVFS roots')
    change,seen=tvfs_renamer(planned)
    controls={next(iter(expected)):expected[next(iter(expected))]}
    progress('Rebuilding typed ROOT and matching TVFS paths; payload files stay unchanged...')
    audit_spec=importlib.util.spec_from_file_location('repair_root_audit',Path(__file__).with_name('audit-legion-root-types.py'))
    auditor=importlib.util.module_from_spec(audit_spec);audit_spec.loader.exec_module(auditor)
    def transform_root(root):
        references={row['file_data_id']:row['profiles'] for rows in audit['native_world_roles'].values() for row in rows}
        actual=auditor.profiles(root,set(references))
        if any(actual.get(fid,[])!=rows for fid,rows in references.items()):
            raise ValueError('Native world type audit differs from active ROOT')
        return replace_root(root,planned)
    prepared,_=install.manifests(store,{}, {},before,controls,progress,
        root_transform=transform_root,path_transform=change)
    if seen!=planned.keys():raise ValueError('TVFS did not contain every private reference')
    configuration=install.canary.resource_configuration(store,prepared)
    config_path=client/configuration['path'];created=not config_path.exists()
    if not created and config_path.read_bytes()!=configuration['body']:raise ValueError('Build configuration collision')
    prologues={}
    for p in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
        with p.open('rb') as src:prologues[int(p.name[5:])]=src.read(480)
    payloads,new_shared=install.plan_segment(meta,prologues,prepared['additions'])
    if any((client/'Data/data'/name).exists() for name in payloads):raise ValueError('Storage destination exists')
    if shutil.disk_usage(client).free<sum(map(len,payloads.values()))+sum(map(len,meta.values()))+256*1024**2:
        raise ValueError('Insufficient disk space for manifests and rollback metadata')
    if (client/'.build.info').read_bytes()!=original or install.container.metadata(client/'Data/data')!=meta:
        raise ValueError('Client changed during preparation; close game and launcher')
    token=uuid.uuid4().hex;folder=client/install.OPS/token;(folder/'before').mkdir(parents=True)
    for name,body in meta.items():(folder/'before'/name).write_bytes(body)
    (folder/'before.build.info').write_bytes(original)
    if ((folder/'before.build.info').read_bytes()!=original or
            any((folder/'before'/name).read_bytes()!=body for name,body in meta.items())):
        raise ValueError('Metadata backup verification failed')
    ancestors=list(parent.get('resource_ancestors',[]))+[parent_folder.name]
    journal=copy.deepcopy(parent)
    journal.update(phase='prepared',before_info_sha256=install.canary.sha(original),
        after_info_sha256=install.canary.sha(configuration['build_info']),before={n:install.canary.sha(b) for n,b in meta.items()},
        added={n:dict(bytes=len(b),sha256=install.canary.sha(b)) for n,b in payloads.items()},
        generations=list(struct.unpack_from('<16I',new_shared,0x110)),new_build_key=configuration['build_key'],
        configuration=dict(path=configuration['path'],created=created,sha256=install.canary.sha(configuration['body'])),
        original_segments=sorted(prologues),expected_after=expected,root_types_repaired=True,
        root_type_profiles=planned,
        root_policy='typed native ROOT profiles; provisional flat TVFS routes, not game-validated',resource_ancestors=ancestors,
        root_type_audit_sha256=install.canary.sha(audit_bytes),root_type_evidence=evidence,wow_client_runtime_verified=False)
    install.canary.checkpoint(folder/'operation.json',journal)
    install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=token))
    progress('Repair backup: '+str(folder))
    try:
        for name,body in payloads.items():
            with (client/'Data/data'/name).open('xb') as out:out.write(body);out.flush();os.fsync(out.fileno())
        temp=folder/'new-shmem';temp.write_bytes(new_shared);os.replace(temp,client/'Data/data/shmem')
        if created:
            config_path.parent.mkdir(parents=True,exist_ok=True)
            with config_path.open('xb') as out:out.write(configuration['body'])
        temp=folder/'new.build.info';temp.write_bytes(configuration['build_info']);os.replace(temp,client/'.build.info')
        journal['phase']='switched';install.canary.checkpoint(folder/'operation.json',journal)
        del prepared,payloads,private,objects,store
        actual=install.verify(client,checker,progress)
        # CascFileFullInfo can return the first node's flags for aliased CKeys.
        # Validate types by FileDataID in the actual installed ROOT instead.
        current=install.canary.storelib.Store(client,synthetic_only=False)
        ck,ek=current.values['encoding'].split()[:2]
        encoding=auditor.Encoding(current.read(bytes.fromhex(ek),bytes.fromhex(ck)))
        root=auditor.read_content(current,encoding,current.values['root'].split()[0])
        profiles=auditor.profiles(root,set(planned))
        for fid,p in planned.items():
            want=dict(locale=p['locale'],raw_flags=list(p['raw_flags']),ckey=p['ckey'])
            if profiles.get(fid)!=[want]:raise ValueError('Installed ROOT type check failed for '+str(fid))
        journal['phase']='verified';install.canary.checkpoint(folder/'operation.json',journal)
    except BaseException:
        install.rollback(client)
        install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=parent_folder.name))
        raise
    result=dict(format='wowforever-legion-root-type-repair-v1',private_ids=len(planned),native_verified_ids=len(actual),
        evidence=evidence,operation=token,resource_payloads_changed=False,server_modified=False,
        actual_teleport_verified=False,parent_operation=parent_folder.name)
    install.canary.checkpoint(folder/'result.json',result)
    progress('ROOT TYPES REPAIRED AND READ VERIFIED; actual game loading still requires testing.')
    progress('Report: '+str(folder/'result.json'))
    return result


def rollback(client):
    client,_=install.canary.copy_identity(client);folder,journal=install.operation(client)
    if journal.get('tvfs_entry_canary'):raise ValueError('Roll back the TVFS entry canary before the ROOT type repair')
    if not journal.get('root_types_repaired') or not journal.get('resource_ancestors'):raise ValueError('No active type repair')
    install.rollback(client)
    install.canary.checkpoint(client/install.OPS/'active.json',dict(operation=journal['resource_ancestors'][-1]))
    print('ROOT TYPE REPAIR ROLLED BACK; resource payload layer retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['apply','rollback']);parser.add_argument('client',type=Path)
    for name in ('resource-report','namespace-report','type-audit'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--checker',type=Path,default=Path(__file__).with_name('check-client-casc.sh'))
    parser.add_argument('--report-dir',type=Path)
    args=parser.parse_args()
    try:
        token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='rollback':rollback(args.client)
            else:
                if any(v is None for v in (args.resource_report,args.namespace_report,args.type_audit)):
                    raise ValueError('apply requires all three reports')
                apply(args.client,args.resource_report,args.namespace_report,args.type_audit,args.checker)
                from legion_reports import auto_collect
                auto_collect(args.client,args.report_dir)
    except (ValueError,OSError,KeyError,TypeError,struct.error) as error:
        parser.exit(1,'ROOT type repair stopped: '+str(error)+'\n')
