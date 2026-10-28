#!/usr/bin/env python3
"""Extract one staged Legion tile with read-only client mounts, never deploy it."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import uuid

spec=importlib.util.spec_from_file_location('geometry_installer',Path(__file__).with_name('install-legion-resources.py'))
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)
ROOT=Path(__file__).resolve().parents[1]


def inputs(client,resource_report,map_report):
    client,_=install.canary.copy_identity(client)
    folder,journal=install.operation(client)
    journal['operation']=folder.name
    if journal['phase']!='verified' or journal.get('map_record_installed'):
        raise ValueError('Expected a verified resource-only installation')
    if install.compare.sha_file(client/'.build.info')!=journal['after_info_sha256']:
        raise ValueError('Copy build changed since resource installation')
    raw=Path(resource_report).read_bytes()
    if len(raw)>32*1024*1024:raise ValueError('Oversized resource report')
    resource=json.loads(raw)
    table=json.loads(Path(map_report).read_text())
    digest=hashlib.sha256(raw).hexdigest()
    if (resource.get('format')!='wowforever-legion-private-resource-stage-v1' or
            table.get('format')!='wowforever-legion-map-record-candidate-v1' or
            digest!=journal['source_report_sha256'] or digest!=table['source_resource_report_sha256'] or
            resource['package_sha256']!=journal['source_package_sha256'] or
            table['resource_package_sha256']!=resource['package_sha256']):
        raise ValueError('Geometry input reports do not match the installed batch')
    tile=resource['tile'];gx,gy=tile['world_tile_x'],tile['world_tile_y']
    if (table['map_id']!=1220 or tile['declared_map_id']!=1220 or
            table['directory']!='ForeverDalaran' or
            type(gx) is not int or type(gy) is not int or not 0<=gx<64 or not 0<=gy<64 or
            tile['raw_maid_index']!=gx*64+gy):
        raise ValueError('Unsupported map/tile or inconsistent coordinate order')
    wdt=table['wdt_file_data_id']
    definitions=[r for r in resource['files'] if wdt in r['target_file_data_ids']]
    if (type(wdt) is not int or not 0xf00000<=wdt<0xffff00 or len(definitions)!=1 or
            not definitions[0]['path'].endswith('.wdt') or
            Path(definitions[0]['path']).stem.endswith(('_lgt','_occ','_fogs','_mpv')) or not definitions[0]['payload']):
        raise ValueError('Main private WDT missing from the package')
    expected=journal['expected_after'].get(str(wdt))
    if not expected or expected['sha256']!=definitions[0]['sha256'] or expected['ckey']!=definitions[0]['ckey']:
        raise ValueError('Private WDT differs from the installed bytes')
    return client,journal,resource,table


def metadata_fingerprint(client):
    result={}
    for p in (client/'Data/data').iterdir():
        if p.is_file() and not re.fullmatch(r'data\.\d{3}',p.name):
            result[p.name]=install.compare.sha_file(p)
    return result


def inventory(output,map_id,gx,gy):
    terrain=output/'maps'/f'{map_id:04}_{gx:02}_{gy:02}.map'
    tilelist=output/'maps'/f'{map_id:04}.tilelist'
    tree=output/'vmaps'/f'{map_id:04}'/f'{map_id:04}.vmtree'
    tile=output/'vmaps'/f'{map_id:04}'/f'{map_id:04}_{gx:02}_{gy:02}.vmtile'
    errors=[];records=[]
    for p in (terrain,tilelist,tree,tile):
        if not p.is_file():errors.append('Missing '+p.relative_to(output).as_posix())
    if terrain.is_file():
        with terrain.open('rb') as source:head=source.read(44)
        if len(head)!=44 or head[:4]!=b'MAPS' or struct.unpack_from('<I',head,4)[0]!=10:
            errors.append('Unexpected terrain header/version')
        else:
            values=struct.unpack('<4s10I',head)
            if values[2]!=70532:errors.append('Unexpected extracted client build')
            for i in range(3,11,2):
                offset,size=values[i:i+2]
                if (offset==0)!=(size==0) or (size and (offset<44 or offset+size>terrain.stat().st_size)):
                    errors.append('Terrain section outside file bounds')
    if tilelist.is_file():
        data=tilelist.read_bytes()
        expected=bytearray(b'0'*4096);expected[4095-(gx*64+gy)]=ord('1')
        if len(data)!=4108 or data[:4]!=b'MAPS' or data[12:]!=expected:
            errors.append('Extracted tile list is not the one requested cell')
    for p in (tree,tile):
        if p.is_file():
            with p.open('rb') as source:magic=source.read(8)
            if magic!=b'VMAP_4.E':errors.append('Unexpected VMAP version: '+p.name)
    for p in sorted(output.rglob('*')):
        if p.is_symlink():raise ValueError('Linked geometry output is unsupported')
        if not p.is_file() or p.suffix not in {'.map','.tilelist','.vmtree','.vmtile','.vmo'}:continue
        relative=p.relative_to(output).as_posix()
        if p.suffix=='.map' and p!=terrain:errors.append('Unexpected extra terrain tile: '+relative)
        if p.suffix in {'.vmtree','.vmtile'} and p.parent.name!=f'{map_id:04}':
            errors.append('Unexpected other map in VMAP output: '+relative)
        if p.suffix=='.vmo':
            with p.open('rb') as model:
                if model.read(8)!=b'VMAP_4.E':errors.append('Unexpected collision model header: '+relative)
        records.append(dict(path=relative,bytes=p.stat().st_size,sha256=install.compare.sha_file(p)))
    if not any(r['path'].endswith('.vmo') for r in records):errors.append('No assembled collision models')
    return records,errors


def extract(client,resource_report,map_report,output,image='forever-legion-casc-probe:local',threads=2,progress=print):
    client,journal,resource,table=inputs(client,resource_report,map_report)
    output=Path(output).resolve()
    if (output.exists() or output.is_relative_to(client) or output.is_relative_to(ROOT/'data') or
            any(p.lower() in {'data','_classic_beta_'} for p in output.parts)):
        raise ValueError('Choose a NEW geometry directory outside client/server data trees')
    if type(threads) is not int or not 1<=threads<=8:raise ValueError('Threads must be 1..8')
    subprocess.run(['docker','image','inspect',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    progress('Checking all installed resources before read-only extraction...')
    expected={int(fid):row for fid,row in journal['expected_after'].items()}
    actual=install.scan(ROOT/'scripts/check-client-casc.sh',client,expected,journal['locale'],progress)
    install.check_rows(actual,expected)
    original_info=install.compare.sha_file(client/'.build.info');before=metadata_fingerprint(client)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<2*1024**3:
        raise ValueError('Keep at least 2 GiB free for staged raw and assembled collision')
    output.mkdir();logs=output/'logs';logs.mkdir()
    container_name='wowforever-geometry-'+uuid.uuid4().hex
    command=['docker','run','--name',container_name,'--rm','--network','none','--read-only','--cap-drop','ALL',
             '--security-opt','no-new-privileges','--user',f'{os.getuid()}:{os.getgid()}',
             '--cpus',str(threads),'--ulimit','core=0','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=512m',
             '--mount',f'type=bind,src={client},dst=/wow,readonly',
             '--mount',f'type=bind,src={ROOT/"tools/legion-geometry"},dst=/geometry-code,readonly',
             '--mount',f'type=bind,src={output},dst=/out','--entrypoint','python3',image,
             '-B','/geometry-code/run.py','--map-id',str(table['map_id']),'--wdt-id',str(table['wdt_file_data_id']),
             '--grid-x',str(resource['tile']['world_tile_x']),'--grid-y',str(resource['tile']['world_tile_y']),
             '--threads',str(threads)]
    progress('Compiling cached tool entry points, extracting the single tile and testing collision...')
    failure=None;code=None
    try:
        with (logs/'runner.log').open('w') as log:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                for line in process.stdout:
                    log.write(line);log.flush();progress(line.rstrip())
                code=process.wait()
            except BaseException:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
                subprocess.run(['docker','rm','-f',container_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
                raise
        if code:failure=f'Geometry container returned {code}; see logs/runner.log and per-tool logs'
    except (OSError,subprocess.SubprocessError) as error:
        failure=str(error)
    records,errors=inventory(output,table['map_id'],resource['tile']['world_tile_x'],resource['tile']['world_tile_y'])
    if failure:errors.insert(0,failure)
    unchanged=(install.compare.sha_file(client/'.build.info')==original_info and metadata_fingerprint(client)==before)
    if not unchanged:errors.append('Client metadata changed concurrently; keep the game and launcher closed')
    probe=json.loads((output/'height-probe.json').read_text()) if (output/'height-probe.json').is_file() else None
    if not probe or not probe.get('load_success') or not probe.get('city_collision_samples'):
        errors.append('City collision was not confirmed by the server height probe')
    diagnostics=[]
    for log in sorted(logs.glob('*.log')):
        with log.open(errors='replace') as text:
            for line in text:
                if re.search(r'error|failed|can.t open|fatal',line,re.I) and len(diagnostics)<200:
                    diagnostics.append(dict(log=log.name,text=line.strip()[:1000]))
    result=dict(format='wowforever-legion-geometry-extraction-v1',map_id=table['map_id'],
        wdt_file_data_id=table['wdt_file_data_id'],tile=resource['tile'],source_install_operation=journal.get('operation',None),
        source_resource_report_sha256=journal['source_report_sha256'],native_resource_ids_verified=len(actual),
        client_mounted_read_only=True,client_metadata_unchanged=unchanged,client_modified=False,server_modified=False,
        compiled_core_revision='91d49b230f89c3ab4719f5b2b2d1e70ed36613c4',global_gameobject_models_extracted=False,
        files=records,height_probe=probe,extraction_diagnostics=diagnostics,errors=errors,geometry_probe_passed=not errors,
        full_collision_coverage_verified=False,
        client_map_enabled=False,server_map_enabled=False,player_spawn_verified=False)
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    progress('Geometry report: '+str(output/'report.json'))
    progress('STAGED GEOMETRY PROBE PASSED' if not errors else 'STAGED GEOMETRY INCOMPLETE; nothing was deployed')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client',type=Path)
    parser.add_argument('--resource-report',type=Path,required=True)
    parser.add_argument('--map-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',default='forever-legion-casc-probe:local')
    parser.add_argument('--threads',type=int,default=2)
    args=parser.parse_args()
    try:
        token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=extract(args.client,args.resource_report,args.map_report,args.output,args.image,args.threads)
            if result['errors']:raise SystemExit(1)
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,struct.error,subprocess.SubprocessError) as error:
        parser.exit(1,f'Geometry preparation stopped: {error}\n')
