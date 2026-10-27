#!/usr/bin/env python3
"""Plan private FileDataIDs from the target copy's complete ROOT, without writes.

Reads ROOT/ENCODING/IDX locally. Does not rewrite references or install a zone.
"""
import argparse
import importlib.util
import json
import re
import struct
from collections import Counter, defaultdict, deque
from pathlib import Path

from casc_manifest_update import Encoding, root_groups


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary=load('namespace_canary','casc-copy-canary.py')
comparison=load('namespace_compare','plan-legion-client.py')
world=load('namespace_world','prepare-legion-zone.py')
POOL_START=0x00f00000
POOL_END=0x00ffff00
CONTROLS={775969:'.tex',775970:'.wdl',775971:'.wdt',778027:'.adt',7281217:'.adt',782779:'.wdt',1349477:'.db2'}


def latest_index_names(folder):
    latest={}
    for path in folder.glob('*.idx'):
        match=re.fullmatch('([0-9a-f]{2})([0-9a-f]{8})\\.idx',path.name)
        if match:
            bucket,generation=(int(value,16) for value in match.groups())
            if bucket<16 and (bucket not in latest or generation>latest[bucket][0]):
                latest[bucket]=(generation,path.name)
    return {row[1] for row in latest.values()}


def encoding_lookup(encoding,keys):
    found={}
    for key,raw in encoding.rows('c'):
        if key in keys:
            found[key.hex()]=dict(bytes=int.from_bytes(raw[1:6],'big'),
                                  ekeys=[raw[22+i*16:38+i*16].hex() for i in range(raw[0])])
    return found


def inspect_root(store,wanted,donor_keys,progress=print):
    def configured(name):
        keys=store.values[name].split()
        return store.read(bytes.fromhex(keys[1]),bytes.fromhex(keys[0]))
    progress('Reading ENCODING and locating the active ROOT...')
    encoding=Encoding(configured('encoding'))
    root_key=bytes.fromhex(store.values['root'].split()[0])
    root_row=encoding_lookup(encoding,{root_key}).get(root_key.hex())
    if not root_row:
        raise ValueError('Active ROOT absent from ENCODING')
    root=None
    for key in root_row['ekeys']:
        if bytes.fromhex(key)[:9] in store.entries:
            root=store.read(bytes.fromhex(key),root_key)
            break
    if root is None:
        raise ValueError('Active ROOT is not locally readable')
    progress('Checking reservations across ALL ROOT groups, including other locales...')
    reserved=set()
    variants=defaultdict(list)
    groups=records=0
    for group in root_groups(root):
        groups+=1
        current=0
        for index,(delta,) in enumerate(struct.iter_unpack('<I',memoryview(root)[group['ids_offset']:group['ckeys_offset']])):
            current+=delta
            if current>0xffffffff:
                raise ValueError('ROOT ID overflow')
            reserved.add(current)
            records+=1
            if current in wanted:
                off=group['ckeys_offset']+index*16
                variants[current].append(dict(ckey=root[off:off+16].hex(),locale=group['locale'],
                                              raw_flags=group['content_flags'],combined_flags=group['flags']))
            current+=1
    requested_keys={bytes.fromhex(value['ckey']) for rows in variants.values() for value in rows}|donor_keys
    progress('Resolving donor and ROOT CKeys against ENCODING and local IDX...')
    encoded=encoding_lookup(encoding,requested_keys)
    for row in encoded.values():
        row['locally_indexed_ekeys']=[key for key in row['ekeys'] if bytes.fromhex(key)[:9] in store.entries]
    return reserved,dict(variants),encoded,dict(groups=groups,records=records,unique_reserved_ids=len(reserved))


def closure(package,resources,variants,encoded):
    rows={}
    paths={}
    for row in package['files']:
        for fid in row['file_data_ids']:
            rows[fid]=row
        paths[row['path']]=row['file_data_ids']
    private=set()
    reasons=defaultdict(set)
    for fid,row in rows.items():
        same_root=any(value['ckey']==row['ckey'] for value in variants.get(fid,()))
        indexed=bool(encoded.get(row['ckey'],{}).get('locally_indexed_ekeys'))
        if resources[fid]['classification']!='identical' or row['transformation'] or not same_root or not indexed:
            private.add(fid)
            reasons[fid].add('not_identical_or_not_available_in_target')
    parents=defaultdict(set)
    children=defaultdict(set)
    for edge in package['references']:
        for parent in paths.get(edge['source'],()):
            children[parent].add(edge['file_data_id'])
            parents[edge['file_data_id']].add(parent)
    queue=deque(private)
    while queue:
        child=queue.popleft()
        for parent in parents.get(child,()):
            reasons[parent].add('references_a_private_child')
            if parent not in private:
                private.add(parent)
                queue.append(parent)
            # All aliases of one staged file must receive its revised content.
            for alias in rows[parent]['file_data_ids']:
                if alias not in private:
                    private.add(alias)
                    reasons[alias].add('alias_of_a_rewritten_parent')
                    queue.append(alias)
    return rows,private,reasons,children


def allocate(private,reserved,start=POOL_START,end=POOL_END):
    result={}
    candidate=start
    for fid in sorted(private):
        while candidate in reserved and candidate<end:
            candidate+=1
        if candidate>=end:
            raise ValueError('Private FileDataID pool exhausted; no IDs assigned')
        result[fid]=candidate
        candidate+=1
    return result


def controls_report(store,variants,encoded):
    result=[]
    for fid,suffix in CONTROLS.items():
        for variant in variants.get(fid,()):
            row=encoded.get(variant['ckey'],{})
            for key in row.get('locally_indexed_ekeys',()):
                value=dict(file_data_id=fid,declared_type=suffix,root=variant,format_verified=False)
                try:
                    data=store.read(bytes.fromhex(key),bytes.fromhex(variant['ckey']))
                    value.update(bytes=len(data),sha256=canary.sha(data),signature_hex=data[:4].hex())
                    tags=({tag for tag,_ in world.chunks(data)} if suffix!='.db2' else set())
                    if suffix=='.wdt':
                        value['format_verified']={'MPHD','MAIN'}<=tags
                    elif suffix=='.adt':
                        value['format_verified']='MCNK' in tags
                    elif suffix=='.wdl':
                        value['format_verified']='MAOF' in tags
                    elif suffix=='.db2':
                        value['format_verified']=data[:4] in {b'WDC1',b'WDC2',b'WDC3',b'WDC4',b'WDC5'}
                    value.update(bytes=len(data),sha256=canary.sha(data),chunks=sorted(tags))
                except (ValueError,UnicodeError,struct.error,OSError) as exc:
                    value['error']=str(exc)
                result.append(value)
                break
    return result


def plan(client_plan,package_report,target,output,progress=print):
    output=Path(output).resolve()
    target,marker=canary.copy_identity(target)
    if output.exists() or output.is_relative_to(target/'Data') or output.is_relative_to(target/'_classic_beta_') or output==target/'.build.info':
        raise ValueError('Use a new report path outside target data/executable trees')
    data=json.loads(Path(client_plan).read_text())
    if data.get('format')!='wowforever-legion-client-comparison-v1':
        raise ValueError('Expected the completed client comparison')
    if comparison.sha_file(Path(package_report))!=data['source_report_sha256']:
        raise ValueError('Package report changed since comparison')
    package=json.loads(Path(package_report).read_text())
    if package['package_sha256']!=data['package_sha256'] or package.get('errors'):
        raise ValueError('Package/comparison mismatch')
    expected=data['client_build_info_sha256']
    source=Path(marker['source'])
    if marker['sha256']['.build.info']!=expected or comparison.sha_file(source/'.build.info')!=expected:
        raise ValueError('Copy baseline/source build differs from the comparison')
    original_info=comparison.sha_file(target/'.build.info')
    resources={row['file_data_id']:row for row in data['resources']}
    package_ids={fid for row in package['files'] for fid in row['file_data_ids']}
    if set(resources)!=package_ids or len(resources)!=len(data['resources']):
        raise ValueError('Incomplete/duplicate comparison FileDataIDs')
    for row in package['files']:
        for fid in row['file_data_ids']:
            actual=resources[fid]
            if actual['path']!=row['path'] or actual['package_ckey']!=row['ckey'] or actual['package_sha256']!=row['sha256']:
                raise ValueError('Comparison resource fingerprint mismatch')
    progress('Validating the target copy local IDX (may take a few minutes)...')
    store=canary.storelib.Store(target,synthetic_only=False)
    index_hashes={f'{number:02x}{row["version"]:08x}.idx':comparison.sha_file(target/'Data/data'/f'{number:02x}{row["version"]:08x}.idx')
                  for number,row in store.buckets.items()}
    shared=(target/'Data/data/shmem').read_bytes()
    if (len(shared)!=20480 or struct.unpack_from('<I',shared)[0]!=5 or
            list(struct.unpack_from('<16I',shared,0x110))!=[store.buckets[i]['version'] for i in range(16)]):
        raise ValueError('Target shmem/index selection is inconsistent; no namespace plan published')
    wanted=package_ids|set(CONTROLS)|{row['file_data_id'] for row in data['external_dependencies']}
    reserved,variants,encoded,summary=inspect_root(store,wanted,{bytes.fromhex(row['ckey']) for row in package['files']},progress)
    rows,private,reasons,children=closure(package,resources,variants,encoded)
    mapping=allocate(private,reserved|set(rows)|wanted)
    staged=[]
    counts=Counter()
    profiles=Counter()
    for fid,row in sorted(rows.items()):
        rewrite=any(child in private for child in children.get(fid,()))
        encoding=encoded.get(row['ckey'])
        policy=('rewrite_references_then_rehash' if rewrite else
                'reuse_original_ID_candidate' if fid not in private else
                'reuse_local_CKey_candidate' if encoding and encoding['locally_indexed_ekeys'] else
                'add_ENCODING_variant_and_payload' if encoding else 'add_new_CKey_and_payload')
        counts[policy]+=1
        staged.append(dict(original_file_data_id=fid,target_file_data_id=mapping.get(fid,fid),path=row['path'],
                           original_id_reserved_in_target=fid in reserved,root_variants=variants.get(fid,[]),
                           donor_ckey=row['ckey'],encoding=encoding,action=policy,reasons=sorted(reasons.get(fid,())),
                           requires_final_target_read_check=True))
        if fid not in private:
            for variant in variants.get(fid,()):
                if variant['ckey']==row['ckey']:
                    profiles[(Path(row['path']).suffix.lower(),variant['locale'],tuple(variant['raw_flags']))]+=1
    progress('Checking resident world-file controls for observed native ROOT profiles...')
    control_rows=controls_report(store,variants,encoded)
    external=[]
    for dependency in data['external_dependencies']:
        fid=dependency['file_data_id']
        key=dependency['native'].get('ckey')
        root_match=any(value['ckey']==key for value in variants.get(fid,()))
        external.append(dict(file_data_id=fid,source_native=dependency['native'],
                             target_root_matches_source=root_match,
                             encoding=encoded.get(key),requires_final_target_read_check=True))
    result=dict(format='wowforever-legion-private-id-plan-v1',package_sha256=data['package_sha256'],
                source_comparison_sha256=comparison.sha_file(Path(client_plan)),target_build_key=store.build_key,
                target_build_info_sha256=original_info,root_summary=summary,
                shmem_sha256=canary.sha(shared),
                resources=staged,counts=dict(counts),private_ids=len(mapping),shared_id_candidates=len(rows)-len(mapping),
                pool=dict(start=POOL_START,end_exclusive=POOL_END,checked_against_all_ROOT_groups=True,donor_ids_excluded=True),
                observed_reuse_profiles=[dict(extension=k[0],locale=k[1],raw_flags=list(k[2]),files=v) for k,v in sorted(profiles.items())],
                world_file_controls=control_rows,external_dependencies=external,coverage_limits=package['coverage_limits'],
                client_modified=False,references_rewritten=False,root_policy_assigned=False,installable=False,
                note='Private IDs are free in this target ROOT snapshot, including other locales. Existing payloads are only IDX candidates until fully read. The final importer must revalidate the target snapshot. Map records, new references and server geometry are not installed.')
    if comparison.sha_file(target/'.build.info')!=original_info or comparison.sha_file(source/'.build.info')!=expected:
        raise ValueError('Client build changed during planning')
    if (target/'Data/data/shmem').read_bytes()!=shared or latest_index_names(target/'Data/data')!=set(index_hashes):
        raise ValueError('Target index selection changed during planning')
    for name,digest in index_hashes.items():
        if comparison.sha_file(target/'Data/data'/name)!=digest:
            raise ValueError('Target IDX changed during planning')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as outgoing:
        json.dump(result,outgoing,indent=2)
        outgoing.write('\n')
    progress(f'Private IDs: {len(mapping)}; shared ID candidates: {len(rows)-len(mapping)}')
    progress('Private ID plan: '+str(output))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('comparison',type=Path)
    parser.add_argument('--package-report',type=Path,required=True)
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        plan(args.comparison,args.package_report,args.target,args.output)
    except (ValueError,OSError,KeyError,TypeError,struct.error) as error:
        parser.exit(1,f'Private ID planning stopped: {error}\n')
