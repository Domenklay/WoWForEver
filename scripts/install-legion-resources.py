#!/usr/bin/env python3
"""Install private resources in an independent client copy, with journaled rollback.

Storage experiment only. Adds no Map row and changes no server files. The new
ROOT entries intentionally use the generic hashless policy tested by the canary;
terrain-specific ROOT policy and actual zone loading remain unverified.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import tempfile
import uuid
from collections import Counter
from pathlib import Path
import zipfile

from casc_download import Download, append_download
from casc_manifest_update import Encoding, append_root, extend_encoding
from casc_native_container import plan_segment


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


container=load('casc-container-canary.py')
compare=load('plan-legion-client.py')
canary=container.canary
OPS='legion-resource-operations'
FORMAT='wowforever-legion-resource-operation-v1'
NAMES=re.compile(r'(?:data\.\d{3}|[0-9a-f]{10}\.idx)')


def read_package(report_path):
    report_path=Path(report_path).resolve(strict=True)
    raw=report_path.read_bytes()
    if len(raw)>32*1024*1024:
        raise ValueError('Oversized resource report')
    report=json.loads(raw)
    if (report.get('format')!='wowforever-legion-private-resource-stage-v1' or
            report.get('reference_parser_revision',0)<2 or not report.get('typed_references_rewritten')):
        raise ValueError('Expected the completed private resource package v2')
    archive=report_path.parent/'private-resources.zip'
    if compare.sha_file(archive)!=report['package_sha256']:
        raise ValueError('Resource package SHA mismatch')
    shared={};private={};original=set();payloads={};all_targets=set();paths=set()
    with zipfile.ZipFile(archive) as incoming:
        if len(incoming.namelist())!=len(set(incoming.namelist())):
            raise ValueError('Duplicate archive member')
        index=incoming.getinfo('private-resource-index.json')
        if index.file_size>32*1024*1024:
            raise ValueError('Oversized package index')
        if json.loads(incoming.read(index))!={k:v for k,v in report.items() if k!='package_sha256'}:
            raise ValueError('Resource report differs from its ZIP index')
        for row in report['files']:
            compare.safe_name(row['path'])
            if row['path'] in paths or type(row['bytes']) is not int or not 0<row['bytes']<=64*1024*1024:
                raise ValueError('Duplicate resource path or unsupported size')
            paths.add(row['path'])
            old,new=row['original_file_data_ids'],row['target_file_data_ids']
            if not old or len(old)!=len(new):
                raise ValueError('Missing FileDataID binding')
            for fid in old+new:
                if type(fid) is not int or not 0<fid<=0xffffffff:
                    raise ValueError('Invalid FileDataID')
            if original.intersection(old) or all_targets.intersection(new) or len(set(new))!=len(new) or len(set(old))!=len(old):
                raise ValueError('Duplicate original or target FileDataID')
            original.update(old);all_targets.update(new)
            expected=dict(bytes=row['bytes'],sha256=row['sha256'],ckey=row['ckey'])
            for key,size in [('sha256',64),('ckey',32)]:
                if not re.fullmatch('[0-9a-f]{'+str(size)+'}',expected[key]):
                    raise ValueError('Invalid resource fingerprint')
            if row['payload'] is None:
                if old!=new:
                    raise ValueError('Shared resource renumbered without payload')
                shared.update({fid:expected for fid in new})
            else:
                if row['payload']!='data/'+row['path'] or any(a==b or not 0xf00000<=b<0xffff00 for a,b in zip(old,new)):
                    raise ValueError('Invalid private resource allocation')
                member=incoming.getinfo(row['payload'])
                if member.file_size!=row['bytes']:
                    raise ValueError('Private payload size mismatch')
                body=incoming.read(member)
                if canary.sha(body)!=row['sha256'] or hashlib.md5(body).hexdigest()!=row['ckey']:
                    raise ValueError('Private payload fingerprint mismatch')
                obj=canary.lab.asset(body)
                payloads.setdefault(obj['ckey'],obj)
                private.update({fid:obj for fid in new})
    if not private or original.intersection(private):
        raise ValueError('Empty private package or private IDs alias original IDs')
    return report,shared,private,payloads,original,canary.sha(raw)


def scan(checker,client,ids,locale,progress):
    previous=os.environ.get('CASC_CHECK_LOCALE')
    os.environ['CASC_CHECK_LOCALE']=locale
    try:
        return compare.scan(Path(checker),client,ids,progress)
    finally:
        if previous is None:os.environ.pop('CASC_CHECK_LOCALE',None)
        else:os.environ['CASC_CHECK_LOCALE']=previous


def check_rows(rows,expected):
    for fid,want in expected.items():
        row=rows.get(fid,{})
        if row.get('status')!='READ_OK' or int(row['bytes'])!=want['bytes'] or row['sha256']!=want['sha256']:
            raise ValueError(f'Native read/hash mismatch for {fid}: {row}')
        for name in ('ckey','tag_mask'):
            if name in want and row[name]!=want[name]:
                raise ValueError(f'Native {name} changed for {fid}')


def manifests(store,private,objects,before,controls,progress):
    def configured(name):
        ck,ek=store.values[name].split()[:2]
        return store.read(bytes.fromhex(ek),bytes.fromhex(ck))
    progress('Building ROOT/ENCODING/DOWNLOAD/TVFS for the private resource batch...')
    encoded=configured('encoding');encoding=Encoding(encoded)
    key=bytes.fromhex(store.values['root'].split()[0]);old_root=None
    for ck,row in encoding.rows('c'):
        if ck==key:
            for n in range(row[0]):
                ek=row[22+16*n:38+16*n]
                if ek[:9] in store.entries:
                    old_root=store.read(ek,key);break
    if old_root is None:
        raise ValueError('Active ROOT not locally readable')
    # append_root checks collisions in ALL groups, including other locales.
    root=canary.lab.asset(append_root(old_root,{fid:obj['ckey'] for fid,obj in private.items()},locale=0xffffffff))
    vfs=canary.lab.asset(canary.storelib.rebuild_tvfs(configured('vfs-root'),root,private,locale=0xffffffff))
    download_bytes=configured('download');download=Download(download_bytes)
    # Keep tag membership of an existing CKey when adding a new encoding for it.
    masks={}
    for row in before.values():
        if row['status']=='READ_OK':
            ck=row['ckey'];mask=int(row['tag_mask'],16)
            if ck in masks and masks[ck]!=mask:
                raise ValueError('Existing CKey has inconsistent native tag masks')
            masks[ck]=mask
    references=Counter(int(before[fid]['tag_mask'],16) for fid in controls if before[fid]['status']=='READ_OK')
    if not references:
        raise ValueError('No verified controls to establish storage tag membership')
    common=references.most_common(1)[0][0]
    refs=download.references({str(i):o['ekey'] for i,o in enumerate(objects.values())})
    rows=[]
    for i,obj in enumerate(objects.values()):
        mask=masks.get(obj['ckey'].hex(),common)
        if mask>>download.tag_count:
            raise ValueError('Native control tag mask exceeds DOWNLOAD tag count')
        if not refs[str(i)]['match_count']:
            rows.append(dict(ekey=obj['ekey'],encoded_bytes=len(obj['encoded']),priority=0,
                             tag_indices=[n for n in range(download.tag_count) if mask&(1<<n)]))
    dl=canary.lab.asset(append_download(download_bytes,rows))
    additions=list(objects.values())+[root,vfs,dl]
    enc=canary.lab.asset(extend_encoding(encoded,additions,allow_variants=True));additions.append(enc)
    checked=Encoding(enc['content'])
    for kind in ('c','e'):
        for _ in checked.rows(kind):pass
    # Reuse identical resident encodings; never place colliding prefixes in IDX.
    write=[]
    for obj in additions:
        if obj['ekey'][:9] in store.entries:
            if store.read(obj['ekey'],obj['ckey'])!=obj['content']:
                raise ValueError('Existing EKey prefix/content collision')
        else:
            write.append(obj)
    return dict(additions=write,root=root,vfs=vfs,download=dl,encoded=enc),common


def operation(client):
    base=client/OPS
    if base.is_symlink() or (base/'active.json').is_symlink():
        raise ValueError('Linked operation journal')
    token=json.loads((base/'active.json').read_text())['operation']
    if not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('Invalid operation token')
    folder=base/token
    if folder.is_symlink() or (folder/'operation.json').is_symlink():raise ValueError('Linked operation')
    journal=json.loads((folder/'operation.json').read_text())
    if journal.get('format')!=FORMAT or journal.get('copy')!=str(client):
        raise ValueError('Journal belongs to another client')
    return folder,journal


def checked_configuration(journal):
    config=journal['configuration'];key=journal['new_build_key']
    if not re.fullmatch('[0-9a-f]{32}',key) or config['path']!=f'Data/config/{key[:2]}/{key[2:4]}/{key}':
        raise ValueError('Invalid configuration path')
    return config


def rollback(client):
    client,_=canary.copy_identity(client)
    folder,journal=operation(client)
    if journal['phase']=='rolled_back':return folder
    original=(folder/'before.build.info').read_bytes()
    if canary.sha(original)!=journal['before_info_sha256']:
        raise ValueError('Build-info backup is invalid')
    if canary.sha((client/'.build.info').read_bytes()) not in {journal['before_info_sha256'],journal['after_info_sha256']}:
        raise ValueError('Client build changed outside this operation')
    saved={}
    if (folder/'before').is_symlink():raise ValueError('Linked metadata backup')
    for name,digest in journal['before'].items():
        path=folder/'before'/name
        if not container.META.fullmatch(name) or path.is_symlink() or canary.sha(path.read_bytes())!=digest:
            raise ValueError('Invalid metadata backup')
        saved[name]=path.read_bytes()
    config=checked_configuration(journal)
    if any(not NAMES.fullmatch(name) for name in journal['added']):raise ValueError('Invalid added filename')
    segments=journal['original_segments']
    if not segments or segments!=list(range(len(segments))) or [name for name in journal['added'] if name.startswith('data.')] != [f'data.{len(segments):03d}']:
        raise ValueError('Invalid new segment in journal')
    current=container.metadata(client/'Data/data')
    quarantine=folder/('after-'+uuid.uuid4().hex);quarantine.mkdir()
    for name,body in current.items():(quarantine/name).write_bytes(body)
    for name,body in saved.items():
        temp=folder/('restore-'+name);temp.write_bytes(body);os.replace(temp,client/'Data/data'/name)
    for name in current.keys()-saved.keys():(client/'Data/data'/name).unlink()
    # Keep any additional archives created by a failed game launch, too.
    # Only archives at/after the verified original segment count can be moved.
    for path in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
        if int(path.name[5:])>=len(segments):
            os.replace(path,quarantine/path.name)
    temp=folder/'restore.build.info';temp.write_bytes(original);os.replace(temp,client/'.build.info')
    if config['created'] and (client/config['path']).exists():
        os.replace(client/config['path'],quarantine/'added-build-config')
    if container.metadata(client/'Data/data')!=saved:raise ValueError('Metadata restoration failed; backup retained')
    journal['phase']='rolled_back';canary.checkpoint(folder/'operation.json',journal)
    return folder


def verify(client,checker,progress=print):
    client,_=canary.copy_identity(client);folder,journal=operation(client)
    if journal['phase'] not in {'switched','verified'}:raise ValueError('Resource batch is not installed')
    if canary.sha((client/'.build.info').read_bytes())!=journal['after_info_sha256']:
        raise ValueError('Client build info changed')
    for name,record in journal['added'].items():
        if not NAMES.fullmatch(name):raise ValueError('Invalid filename in journal')
        path=client/'Data/data'/name
        if path.stat().st_size!=record['bytes'] or compare.sha_file(path)!=record['sha256']:
            raise ValueError('Installed resource storage file changed: '+name)
    shared=(client/'Data/data/shmem').read_bytes()
    if len(shared)!=20480 or list(struct.unpack_from('<16I',shared,0x110))!=journal['generations']:
        raise ValueError('Active IDX generations changed')
    config=client/checked_configuration(journal)['path']
    if compare.sha_file(config)!=journal['configuration']['sha256']:raise ValueError('Configuration changed')
    expected={int(k):v for k,v in journal['expected_after'].items()}
    actual=scan(checker,client,expected,journal['locale'],progress);check_rows(actual,expected)
    return actual


def apply(client,report_path,checker,locale='ruRU',progress=print,controls=None):
    client,marker=canary.copy_identity(client)
    if (client/OPS/'active.json').exists() and operation(client)[1]['phase']!='rolled_back':
        raise ValueError('A batch operation exists; verify or roll it back first')
    if (client/OPS).is_symlink():raise ValueError('Linked operation directory')
    report,shared,private,objects,old_ids,report_hash=read_package(report_path)
    private_count,shared_count=len(private),len(shared)
    original=(client/'.build.info').read_bytes()
    if canary.sha(original)!=report['target_build_info_sha256']:
        raise ValueError('Client build differs from the private resource plan')
    if compare.sha_file(Path(marker['source'])/'.build.info')!=marker['sha256']['.build.info']:
        raise ValueError('Original client build changed since independent copy')
    before_meta=container.metadata(client/'Data/data')
    if 'RepairMarker.psv' in before_meta:raise ValueError('Client has a repair marker')
    if controls is None:
        controls=dict(canary.CONTROLS)
        if (client/'casc-container-operations/active.json').exists():
            _,parent=container.active(client)
            if parent.get('phase')!='verified' or parent.get('mode')!='resource':
                raise ValueError('Expected the verified resource canary parent')
            controls[canary.CANARY_ID]=dict(bytes=len(canary.CANARY_TEXT),sha256=canary.sha(canary.CANARY_TEXT),tag_mask='0')
    ids=old_ids|set(controls)|set(report.get('unresolved_additional_placement_ids',[]))
    progress('Reading all original IDs and checking every shared resource before installation...')
    before=scan(checker,client,ids,locale,progress)
    check_rows(before,shared);check_rows(before,controls)
    for fid in report.get('unresolved_additional_placement_ids',[]):
        if before[fid]['status']!='READ_OK':raise ValueError(f'Additional WDL root file {fid} is not readable')
    store=canary.storelib.Store(client,synthetic_only=False)
    active_shared=before_meta['shmem']
    if (len(active_shared)!=20480 or struct.unpack_from('<I',active_shared)[0]!=5 or
            list(struct.unpack_from('<16I',active_shared,0x110))!=[store.buckets[i]['version'] for i in range(16)]):
        raise ValueError('Active shmem and newest IDX generations disagree')
    if store.values.get('vfs-1')!=store.values.get('vfs-root'):
        raise ValueError('Unsupported distinct TVFS roots')
    prepared,tag_mask=manifests(store,private,objects,before,controls,progress)
    configuration=canary.resource_configuration(store,prepared)
    config_path=client/configuration['path'];configuration['created']=not config_path.exists()
    if config_path.exists() and config_path.read_bytes()!=configuration['body']:
        raise ValueError('Build configuration collision')
    prologues={}
    for path in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
        with path.open('rb') as source:prologues[int(path.name[5:])]=source.read(480)
    progress('Preparing native storage headers and all 16 IDX...')
    payloads,new_shared=plan_segment(before_meta,prologues,prepared['additions'])
    if any((client/'Data/data'/name).exists() for name in payloads):raise ValueError('Candidate storage filename exists')
    if shutil.disk_usage(client).free<sum(map(len,payloads.values()))+sum(map(len,before_meta.values()))+256*1024*1024:
        raise ValueError('Insufficient space for added segment, backups and 256 MiB reserve')
    if container.metadata(client/'Data/data')!=before_meta or (client/'.build.info').read_bytes()!=original:
        raise ValueError('Client changed during preparation; close game and launchers')
    if compare.sha_file(Path(report_path))!=report_hash:raise ValueError('Resource report changed')
    expected={fid:dict(bytes=int(row['bytes']),sha256=row['sha256'],tag_mask=row['tag_mask'],ckey=row['ckey'])
              for fid,row in before.items() if row['status']=='READ_OK'}
    for fid,obj in private.items():expected[fid]=dict(bytes=len(obj['content']),sha256=canary.sha(obj['content']),ckey=obj['ckey'].hex())
    token=uuid.uuid4().hex;folder=client/OPS/token;(folder/'before').mkdir(parents=True)
    for name,body in before_meta.items():
        target=folder/'before'/name;target.write_bytes(body)
        if target.read_bytes()!=body:raise ValueError('Metadata backup verification failed')
    (folder/'before.build.info').write_bytes(original)
    journal=dict(format=FORMAT,copy=str(client),phase='prepared',locale=locale,
        before_info_sha256=canary.sha(original),after_info_sha256=canary.sha(configuration['build_info']),
        before={name:canary.sha(body) for name,body in before_meta.items()},
        added={name:dict(bytes=len(body),sha256=canary.sha(body)) for name,body in payloads.items()},
        generations=list(struct.unpack_from('<16I',new_shared,0x110)),new_build_key=configuration['build_key'],
        configuration=dict(path=configuration['path'],created=configuration['created'],sha256=canary.sha(configuration['body'])),
        original_segments=sorted(prologues),source_report_sha256=report_hash,
        source_package_sha256=report['package_sha256'],original_scan_counts=dict(Counter(row['status'] for row in before.values())),private_resource_ids=private_count,shared_resource_ids=shared_count,
        root_policy='experimental generic hashless group, all locales; terrain-specific policy not verified',
        download_default_tag_mask=f'{tag_mask:x}',expected_after=expected,
        map_record_installed=False,server_modified=False,zone_playability_verified=False,
        full_dependency_closure_proven=False,wow_client_runtime_verified=False)
    canary.checkpoint(folder/'operation.json',journal);canary.checkpoint(client/OPS/'active.json',dict(operation=token))
    progress('Backup and journal: '+str(folder))
    try:
        progress('Installing the native segment and switching manifests in the test copy...')
        for name,body in payloads.items():
            with (client/'Data/data'/name).open('xb') as target:
                target.write(body);target.flush();os.fsync(target.fileno())
        temp=folder/'new-shmem';temp.write_bytes(new_shared);os.replace(temp,client/'Data/data/shmem')
        if configuration['created']:
            config_path.parent.mkdir(parents=True,exist_ok=True)
            with config_path.open('xb') as target:target.write(configuration['body'])
        temp=folder/'new.build.info';temp.write_bytes(configuration['build_info']);os.replace(temp,client/'.build.info')
        journal['phase']='switched';canary.checkpoint(folder/'operation.json',journal)
        # CascLib loads large manifests too; release encoded batch buffers before the native scan.
        del payloads,prepared,objects,private,store
        actual=verify(client,checker,progress)
        journal['phase']='verified';journal['native_verified_ids']=len(actual)
        canary.checkpoint(folder/'operation.json',journal)
    except BaseException:
        progress('Verification failed; restoring the previous copy metadata...')
        rollback(client)
        raise
    result=dict(format='wowforever-legion-resource-install-result-v1',private_resource_ids=private_count,
        shared_resource_ids=shared_count,native_verified_ids=len(actual),operation=token,
        source_report_sha256=report_hash,original_scan_counts=journal['original_scan_counts'],
        map_record_installed=False,server_modified=False,zone_playability_verified=False,
        wow_client_runtime_verified=False,root_policy=journal['root_policy'])
    canary.checkpoint(folder/'result.json',result)
    progress(f'PRIVATE RESOURCES INSTALLED AND READ VERIFIED: {private_count} new IDs')
    progress('Report: '+str(folder/'result.json'))
    progress('Launch the test copy and report whether the existing world still works. Map 1220 is not enabled yet.')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['apply','verify','rollback'])
    parser.add_argument('client',type=Path)
    parser.add_argument('--resource-report',type=Path)
    parser.add_argument('--checker',type=Path,default=Path(__file__).with_name('check-client-casc.sh'))
    parser.add_argument('--locale',choices=['ruRU','enUS'],default='ruRU')
    args=parser.parse_args()
    try:
        token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='apply':
                if args.resource_report is None:raise ValueError('--resource-report is required for apply')
                apply(args.client,args.resource_report,args.checker,args.locale)
            elif args.action=='verify':
                verify(args.client,args.checker);print('PRIVATE RESOURCE BATCH STILL VERIFIED')
            else:
                print('PRIVATE RESOURCE BATCH ROLLED BACK:',rollback(args.client))
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,struct.error,zipfile.BadZipFile) as error:
        parser.exit(1,f'Resource batch stopped: {error}\n')
