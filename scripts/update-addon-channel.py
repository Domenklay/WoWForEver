#!/usr/bin/env python3
"""Validate, pin immutable AddOn payloads from Git, and promote the complete testing set."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
PATHS={'ForeverAscension':'mods/forever-advancement/addon/ForeverAscension',
       'ForeverEncyclopedia':'mods/living-encyclopedia/addon/ForeverEncyclopedia'}
PROTOCOLS={'ForeverAscension':3,'ForeverEncyclopedia':1}
EXTENSIONS={'lua','toc','xml','blp','tga','png','jpg','jpeg','ttf','ogg','mp3','wav','txt','csv'}
RESERVED={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}

def token(s):
    return isinstance(s,str) and bool(re.fullmatch(r'[A-Za-z0-9._+\-]{1,100}',s))
def file_path(s):
    return (isinstance(s,str) and 0<len(s)<=220 and s.rsplit('.',1)[-1].lower() in EXTENSIONS
            and all(re.fullmatch(r'[A-Za-z0-9_\-][A-Za-z0-9._\-]*',p) and not p.endswith('.')
                    and p.split('.')[0].upper() not in RESERVED for p in s.split('/')))
def keys(obj,expected):
    if not isinstance(obj,dict) or set(obj)!=set(expected): raise ValueError('Unexpected manifest fields')
def validate(c):
    keys(c,('format','revision','channels'))
    if c['format']!='forever-addon-channels-v1' or not token(c['revision']): raise ValueError('Invalid catalogue format/revision')
    keys(c['channels'],('stable','testing'))
    for channel,r in c['channels'].items():
        keys(r,('release','clientBuild','addons'))
        if not token(r['release']) or type(r['clientBuild']) is not int or r['clientBuild']!=70658: raise ValueError('Unsupported release build')
        if not isinstance(r['addons'],list) or len(r['addons'])!=2 or {m.get('name') for m in r['addons']}!=set(PATHS): raise ValueError('Expected the complete two-AddOn set')
        for m in r['addons']:
            keys(m,('name','version','protocol','sourceCommit','sourcePath','files'))
            if (not token(m['version']) or type(m['protocol']) is not int or m['protocol']!=PROTOCOLS[m['name']]
                or m['sourcePath']!=PATHS[m['name']] or not re.fullmatch('[0-9a-f]{40}',m['sourceCommit'])): raise ValueError('Incompatible or unpinned AddOn')
            if not isinstance(m['files'],list) or not 1<=len(m['files'])<=2048: raise ValueError('Missing/oversized AddOn file list')
            seen=set(); total=0
            for f in m['files']:
                keys(f,('name','size','sha256'))
                if (not file_path(f['name']) or f['name'].lower() in seen or type(f['size']) is not int
                    or not 0<=f['size']<=32*1024**2 or not re.fullmatch('[0-9a-f]{64}',f['sha256'])): raise ValueError('Unsafe AddOn file entry')
                seen.add(f['name'].lower()); total+=f['size']
            if total>128*1024**2 or m['name'].lower()+'.toc' not in seen: raise ValueError('Incomplete/oversized AddOn')
    if len(json.dumps(c).encode())>512*1024: raise ValueError('Catalogue size limit exceeded')
    return c

def git(repo,*args):
    p=subprocess.run(['git','-C',str(repo),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise ValueError('Required Git object is unavailable; fetch the source commit first')
    return p.stdout

def pin(repo,name,commit,version):
    if name not in PATHS or not re.fullmatch('[0-9a-f]{40}',commit) or not token(version): raise ValueError('Invalid pin arguments')
    if git(repo,'rev-parse','--verify',commit+'^{commit}').decode().strip()!=commit: raise ValueError('Expected a full commit SHA')
    prefix=PATHS[name]+'/'
    blobs={}
    for row in git(repo,'ls-tree','-r','-z',commit,'--',PATHS[name]).split(b'\0'):
        if not row: continue
        header,path=row.split(b'\t',1); mode,kind,oid=header.decode().split(); path=path.decode()
        if mode not in ('100644','100755') or kind!='blob' or not path.startswith(prefix): raise ValueError('Only regular AddOn source files are allowed')
        rel=path[len(prefix):]
        if not file_path(rel): raise ValueError('Unsupported AddOn payload path: '+rel)
        blobs[rel]=oid
    toc=git(repo,'show',commit+':'+prefix+name+'.toc').decode('utf-8-sig')
    match=re.search(r'^##\s*Version:\s*(.*?)\s*$',toc,re.M)
    if not match or match[1]!=version: raise ValueError('Requested version differs from the pinned TOC version')
    # TOC/XML define executable AddOn source. Unreferenced legacy Lua variants
    # in the source folder are not part of the installed release. Include media.
    required={name+'.toc'}|{n for n in blobs if n.rsplit('.',1)[-1].lower() not in ('lua','toc','xml')}
    required.update(line.strip().replace('\\','/') for line in toc.splitlines() if line.strip() and not line.lstrip().startswith('#'))
    done=set();files=[]
    while required-done:
        rel=sorted(required-done)[0]
        if not file_path(rel) or rel not in blobs: raise ValueError('TOC/XML references missing or unsafe file: '+rel)
        body=git(repo,'cat-file','blob',blobs[rel]);done.add(rel)
        if rel.lower().endswith('.xml'):
            tree=ET.fromstring(body)
            for node in tree.iter():
                if 'file' in node.attrib:
                    child=(PurePosixPath(rel).parent/node.attrib['file'].replace('\\','/')).as_posix()
                    required.add(child)
        files.append(dict(name=rel,size=len(body),sha256=hashlib.sha256(body).hexdigest()))
    return dict(name=name,version=version,protocol=PROTOCOLS[name],sourceCommit=commit,sourcePath=PATHS[name],files=sorted(files,key=lambda f:f['name']))

def verify_git(repo,c):
    for release in c['channels'].values():
        for m in release['addons']:
            actual=pin(repo,m['name'],m['sourceCommit'],m['version'])
            if sorted(actual['files'],key=lambda f:f['name'])!=sorted(m['files'],key=lambda f:f['name']): raise ValueError('Pinned payload differs from catalogue: '+m['name'])

def save(path,c):
    validate(c)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Linked catalogue paths are unsupported')
    data=json.dumps(c,ensure_ascii=False,indent=2)+'\n'
    temp=path.with_suffix('.json.tmp')
    with temp.open('x') as f: f.write(data)
    temp.replace(path)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,default=ROOT/'addons/channels.json')
    p.add_argument('--repo',type=Path,default=ROOT)
    sub=p.add_subparsers(dest='action',required=True)
    check=sub.add_parser('check');check.add_argument('--verify-git',action='store_true')
    update=sub.add_parser('pin');update.add_argument('--channel',choices=['stable','testing'],default='testing')
    update.add_argument('--addon',choices=list(PATHS),required=True);update.add_argument('--commit',required=True)
    update.add_argument('--version',required=True);update.add_argument('--release',required=True)
    promote=sub.add_parser('promote');promote.add_argument('--release',required=True)
    a=p.parse_args(); c=validate(json.loads(a.catalog.read_text()))
    if a.action=='check':
        if a.verify_git: verify_git(a.repo,c)
        print('ADDON CHANNELS VERIFIED: '+str(a.catalog));return
    if not token(a.release): raise ValueError('Invalid release ID')
    if a.action=='pin':
        m=pin(a.repo,a.addon,a.commit,a.version)
        target=c['channels'][a.channel]
        target['addons']=[m if old['name']==a.addon else old for old in target['addons']]
    else:
        # Both payloads move together; there is no independent per-AddOn promotion.
        c['channels']['stable']=copy.deepcopy(c['channels']['testing']);target=c['channels']['stable']
    target['release']=a.release;c['revision']=datetime.now(timezone.utc).strftime('70658-%Y%m%dT%H%M%S%fZ')
    save(a.catalog,c)
    print('CATALOGUE UPDATED LOCALLY: '+str(a.catalog)+'; commit and publish it to main/addons/channels.json')

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError) as e: raise SystemExit('AddOn catalogue update stopped: '+str(e))
