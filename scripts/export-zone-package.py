#!/usr/bin/env python3
"""Export one verified CASC transaction into a local launcher package. No client writes.

Game files are written only to the explicit output directory, never to this Git
repository. Native read verification is not a rendering/server validation claim.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

REPO=Path(__file__).resolve().parents[1]
META=re.compile(r'(?:shmem|[a-fA-F0-9]{10}\.idx|[a-fA-F0-9]{16}\.lru)')
ADDED=re.compile(r'(?:data\.[0-9]{3}|[a-fA-F0-9]{10}\.idx|[a-fA-F0-9]{16}\.lru)')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def plain(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Linked paths are unsupported')
    if not path.is_file():raise ValueError('Missing file: '+str(path))
    return path


def version(path):
    rows=list(csv.reader(plain(path).read_text().splitlines(),delimiter='|'))
    columns=[s.split('!')[0] for s in rows[0]]
    product=columns.index('Product');ver=columns.index('Version')
    values=[r[ver] for r in rows[1:] if len(r)>max(product,ver) and r[product]=='wow_classic_beta']
    if len(set(values))!=1:raise ValueError('Expected one unambiguous Forever client version')
    return values[0]


def export(client,operation,output,package_id,name,package_version,validation=None):
    client=Path(client).resolve(strict=True);operation=Path(operation).resolve(strict=True);output=Path(output).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',package_id) or package_id in {'.','..'}:raise ValueError('Invalid package id')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',package_version) or package_version in {'.','..'}:raise ValueError('Invalid package version')
    if not name or len(name.encode())>200:raise ValueError('Invalid package name')
    if output==REPO or output.is_relative_to(REPO):raise ValueError('Game payload packages must be outside Git')
    if output==client or output.is_relative_to(client):raise ValueError('Output must be outside the client')
    if output.exists():raise FileExistsError('Use a new package directory')
    j=json.loads(plain(operation/'operation.json').read_text())
    if j.get('format')!='wowforever-legion-resource-operation-v1' or j.get('phase')!='verified' or j.get('copy')!=str(client):
        raise ValueError('Expected a verified transaction belonging to this client')
    before_info=plain(operation/'before.build.info');after_info=plain(client/'.build.info')
    if sha(before_info)!=j['before_info_sha256'] or sha(after_info)!=j['after_info_sha256']:raise ValueError('Build metadata differs from journal')
    if version(before_info)!=version(after_info):raise ValueError('This is not a client-version updater')
    base={'.build.info':sha(before_info)};changes=[];sources={}
    for entry in (operation/'before').iterdir():
        if not META.fullmatch(entry.name):raise ValueError('Unknown backup metadata: '+entry.name)
        digest=sha(plain(entry))
        if j['before'].get(entry.name)!=digest:raise ValueError('Backup checksum mismatch')
        base['Data/data/'+entry.name]=digest
    if 'Data/data/shmem' not in base:raise ValueError('Missing shmem backup')
    if {p.rsplit('/',1)[-1] for p in base if p!='.build.info'}!=set(j['before']):
        raise ValueError('Incomplete metadata backup')
    current={p.name:p for p in (client/'Data/data').iterdir() if META.fullmatch(p.name)}
    expected={p.rsplit('/',1)[-1] for p in base if p!='.build.info'}
    for filename,row in j['added'].items():
        if not ADDED.fullmatch(filename):raise ValueError('Unknown added data entry: '+filename)
        path=plain(client/'Data/data'/filename)
        if sha(path)!=row['sha256'] or path.stat().st_size!=row['bytes']:raise ValueError('Added file changed: '+filename)
        if META.fullmatch(filename):expected.add(filename)
        sources['Data/data/'+filename]=path
    if set(current)!=expected:raise ValueError('Native metadata generations changed after this operation; re-prepare the package')
    if (client/'Data/data/RepairMarker.psv').exists():raise ValueError('Client repair is pending')
    shmem=plain(current['shmem']).read_bytes()
    if len(shmem)!=20480 or list(struct.unpack_from('<16I',shmem,0x110))!=j['generations']:
        raise ValueError('Current shmem generations differ from the verified operation')
    for filename,path in current.items():
        rel='Data/data/'+filename
        if filename.endswith('.idx') and rel in base and sha(plain(path))!=base[rel]:raise ValueError('Existing native index changed')
        if sha(plain(path))!=base.get(rel):sources[rel]=path
    config=j['configuration'];rel=config['path']
    if not config.get('created') or not re.fullmatch(r'Data/config/[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{32}',rel):
        raise ValueError('Expected a newly created content-addressed build config')
    if rel.split('/')[2:4]!=[rel.split('/')[-1][:2],rel.split('/')[-1][2:4]]:
        raise ValueError('Build config directory does not match its key')
    if sha(plain(client/rel))!=config['sha256']:raise ValueError('Build config checksum mismatch')
    sources[rel]=client/rel;sources['.build.info']=after_info
    for rel,path in sorted(sources.items()):changes.append(dict(path=rel,before=base.get(rel),after=sha(path)))
    if len(changes)>1024 or sum(p.stat().st_size for p in sources.values())>8*1024**3:
        raise ValueError('Package exceeds launcher operation/payload limits')
    rendered=server=False
    if validation is not None:
        proof=json.loads(plain(validation).read_text())
        if proof.get('format')!='wowforever-zone-validation-v1' or proof.get('candidate_build_info_sha256')!=sha(after_info):raise ValueError('Validation does not identify this exact candidate build')
        if type(proof.get('client_render_verified')) is not bool or type(proof.get('server_ready')) is not bool:raise ValueError('Expected explicit boolean validation results')
        rendered=proof['client_render_verified'];server=proof['server_ready']
    manifest=dict(format='wowforever-zone-package-v1',id=package_id,name=name,version=package_version,
                  client_version=version(after_info),status='verified' if rendered and server else 'experimental',
                  client_render_verified=rendered,server_ready=server,base_files=base,files=changes)
    output.mkdir(parents=True)
    try:
        for rel,path in sources.items():
            target=output/'payload'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            if sha(target)!=next(c['after'] for c in changes if c['path']==rel):raise ValueError('Payload changed during export')
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    except BaseException:
        shutil.rmtree(output);raise
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client',type=Path,required=True);p.add_argument('--operation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--id',required=True);p.add_argument('--name',required=True)
    p.add_argument('--version',default='0.1.0');p.add_argument('--validation',type=Path)
    a=p.parse_args()
    try:
        m=export(a.client,a.operation,a.output,a.id,a.name,a.version,a.validation)
        print('Package:',a.output);print('Status:',m['status']);print('This exports one transaction, not an entire zone or its server data.')
    except (OSError,ValueError,KeyError,struct.error) as e:p.exit(1,'Package export stopped: '+str(e)+'\n')
