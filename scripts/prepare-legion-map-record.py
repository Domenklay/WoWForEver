#!/usr/bin/env python3
"""Prepare an offline Map.db2 candidate and optionally inspect missing WDL IDs.

Does not install a table, update CASC, or restart the server.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

from legion_map_db2 import MapTable, add_map

spec = importlib.util.spec_from_file_location('map_client_comparison', Path(__file__).with_name('plan-legion-client.py'))
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def prepare(map_path, resource_report, output, check_client=None, progress=print):
    map_path, resource_report, output = (Path(p).resolve() for p in (map_path, resource_report, output))
    if output.exists() or any(part in {'Data', '_classic_beta_'} for part in output.parts):
        raise ValueError('Choose a NEW output directory outside client data/executable trees')
    if output.is_relative_to(resource_report.parent):
        raise ValueError('Keep the map candidate separate from the resource package')
    report_bytes = resource_report.read_bytes()
    report = json.loads(report_bytes)
    if report.get('format') != 'wowforever-legion-private-resource-stage-v1' or report.get('reference_parser_revision',0) < 2:
        raise ValueError('Expected the completed private resource package v2')
    package = resource_report.parent/'private-resources.zip'
    progress('Verifying the private resource package...')
    if comparison.sha_file(package) != report['package_sha256']:
        raise ValueError('Private resource ZIP differs from the report')
    with zipfile.ZipFile(package) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate ZIP entries')
        info = archive.getinfo('private-resource-index.json')
        if info.file_size > 32*1024*1024:
            raise ValueError('Oversized resource index')
        if json.loads(archive.read(info)) != {k:v for k,v in report.items() if k != 'package_sha256'}:
            raise ValueError('Resource report differs from the packaged index')
    definitions = [row for row in report['files'] if row['path'].endswith('.wdt') and
                   not Path(row['path']).stem.endswith(('_lgt','_occ','_fogs','_mpv'))]
    if len(definitions) != 1 or len(definitions[0]['target_file_data_ids']) != 1:
        raise ValueError('Expected exactly one private main WDT')
    definition = definitions[0]
    if not definition['payload']:
        raise ValueError('Main WDT must be a private resource')
    wdt_id = definition['target_file_data_ids'][0]
    with zipfile.ZipFile(package) as archive:
        info = archive.getinfo(definition['payload'])
        if info.file_size != definition['bytes'] or info.file_size > 8*1024*1024:
            raise ValueError('Invalid WDT size')
        wdt = archive.read(info)
        if hashlib.sha256(wdt).hexdigest() != definition['sha256'] or hashlib.md5(wdt).hexdigest() != definition['ckey']:
            raise ValueError('WDT fingerprint mismatch')
    chunks = {}
    position = 0
    while position < len(wdt):
        if position+8 > len(wdt):
            raise ValueError('Truncated WDT header')
        tag, size = struct.unpack_from('<4sI',wdt,position)
        if size > len(wdt)-position-8 or tag in chunks:
            raise ValueError('Invalid WDT chunk bounds or duplicate chunk')
        chunks[tag] = wdt[position+8:position+8+size]
        position += 8+size
    if (chunks.get(b'REVM') != struct.pack('<I',18) or len(chunks.get(b'DHPM',b'')) != 32 or
            len(chunks.get(b'NIAM',b'')) != 4096*8 or len(chunks.get(b'DIAM',b'')) != 4096*32):
        raise ValueError('Unsupported main WDT schema')
    tile = report['tile']['raw_maid_index']
    if not isinstance(tile,int) or not 0 <= tile < 4096:
        raise ValueError('Invalid raw MAID tile index')
    present = [i for i in range(4096) if struct.unpack_from('<I',chunks[b'NIAM'],i*8)[0] & 1]
    if present != [tile] or not struct.unpack_from('<I',chunks[b'DHPM'])[0] & 0x200:
        raise ValueError('Expected a single-tile WDT with FileDataID MAID entries')
    if map_path.stat().st_size > 16*1024*1024:
        raise ValueError('Oversized Map.db2')
    source = map_path.read_bytes()
    before = MapTable(source)
    map_id = report['tile']['declared_map_id']
    progress(f'Preparing Map {map_id} -> private WDT {wdt_id}...')
    candidate = add_map(source,map_id,wdt_id)
    after = MapTable(candidate)
    checks = []
    client_hash = None
    map_native = None
    map_matches = False
    if check_client is not None:
        check_client = Path(check_client).resolve(strict=True)
        client_hash = comparison.sha_file(check_client/'.build.info')
        if client_hash != report['target_build_info_sha256']:
            raise ValueError('Client build snapshot differs from the private package plan')
        ids = sorted(set(report['unresolved_additional_placement_ids']) | {1349477})
        progress(f'Checking Map.db2 and {len(ids)-1} additional placement IDs with read-only CascLib...')
        native = comparison.scan(Path(__file__).with_name('check-client-casc.sh'),check_client,ids,progress)
        map_native = native[1349477]
        map_matches = (map_native['status'] == 'READ_OK' and
                       map_native['sha256'] == hashlib.sha256(source).hexdigest())
        checks = [dict(file_data_id=fid,native=native[fid],donor_content_match_verified=False,
                       recursive_dependencies_verified=False) for fid in sorted(native) if fid != 1349477]
        if comparison.sha_file(check_client/'.build.info') != client_hash:
            raise ValueError('Client build changed during the read-only check')
    result = dict(format='wowforever-legion-map-record-candidate-v1',map_id=map_id,
                  directory=after.semantic[map_id][0],name=after.semantic[map_id][1],wdt_file_data_id=wdt_id,
                  source_map_sha256=hashlib.sha256(source).hexdigest(),candidate_map_sha256=hashlib.sha256(candidate).hexdigest(),
                  source_resource_report_sha256=hashlib.sha256(report_bytes).hexdigest(),resource_package_sha256=report['package_sha256'],
                  layout_hash=f'{before.layout:08x}',readable_old_maps_preserved=len(before.semantic),
                  opaque_section_ids_preserved=True,old_section_count=before.section_count,new_section_count=after.section_count,
                  template_map_id=0,template_zmp_cleared=True,source_build_match_verified=map_matches,native_loader_checked_here=False,
                  source_map_native_check=map_native,source_map_ckey=hashlib.md5(source).hexdigest(),
                  source_has_opaque_sections=any(s[0] for s in before.section_headers),
                  client_build_info_sha256=client_hash,additional_placement_checks=checks,
                  unresolved_placement_ids=report['unresolved_additional_placement_ids'],client_modified=False,
                  server_modified=False,installable=False,
                  remaining_requirements=['match source Map.db2 to the actual test client',
                      'resolve additional WDL resources and their dependencies',
                      'complete ROOT/tag and opaque auxiliary format review',
                      'transactional CASC import and game test','server map data extraction and safe entry'])
    if comparison.sha_file(map_path) != result['source_map_sha256'] or resource_report.read_bytes() != report_bytes:
        raise ValueError('Source inputs changed during preparation')
    output.parent.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=output.name+'.partial-',dir=output.parent))
    try:
        (stage/'Map.db2').write_bytes(candidate)
        if (stage/'Map.db2').read_bytes() != candidate:
            raise ValueError('Candidate verification failed')
        (stage/'report.json').write_text(json.dumps(result,indent=2)+'\n')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage)
        raise
    progress('Offline candidate: '+str(output/'Map.db2'))
    progress('Report: '+str(output/'report.json'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map-db2',type=Path,required=True)
    parser.add_argument('--resource-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-client',type=Path)
    args = parser.parse_args()
    try:
        prepare(args.map_db2,args.resource_report,args.output,args.check_client)
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,struct.error,zipfile.BadZipFile) as error:
        parser.exit(1,f'Map candidate preparation stopped: {error}\n')
