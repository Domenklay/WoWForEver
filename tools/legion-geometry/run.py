#!/usr/bin/env python3
"""Container entry point: cached tool compilation and isolated one-map extraction."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent


def run(command,log,cwd,environment,timeout):
    with log.open('w') as target:
        process=subprocess.run([str(x) for x in command],cwd=cwd,env=environment,stdout=target,
                               stderr=subprocess.STDOUT,timeout=timeout)
    if process.returncode:
        raise ValueError(f'Command failed ({process.returncode}); see {log.name}')


def extract(client,output,map_id,wdt_id,gx,gy,threads):
    client,output=Path(client),Path(output)
    logs=output/'logs';logs.mkdir(exist_ok=True)
    environment=dict(os.environ,WOWFOREVER_GEOMETRY_MAP_ID=str(map_id),WOWFOREVER_GEOMETRY_WDT_ID=str(wdt_id))
    work=Path(tempfile.mkdtemp(prefix='forever-geometry-'))
    print('Compiling only the extractor entry points and height probe...',flush=True)
    with (logs/'build.log').open('w') as target:
        # Keep compiler diagnostics in the result folder, not mixed into JSON output.
        process=subprocess.run(['python3','-B',str(ROOT/'build-tools.py'),'--output',str(work/'bin')],
                               stdout=target,stderr=subprocess.STDOUT,timeout=600)
    if process.returncode:raise ValueError('Tool build failed; see logs/build.log')
    cache=Path('/src/TrinityCore/build/src/tools/vmap4_assembler/CMakeFiles/vmap4assembler.dir/link.txt')
    import shlex
    link=shlex.split(cache.read_text())
    assembler=(cache.parents[2]/link[link.index('-o')+1]).resolve()
    print('Extracting terrain for the single clipped WDT...',flush=True)
    run([work/'bin/mapextractor','-i',client,'-o',output,'-e','1','-l','ruRU','-p','wow_classic_beta'],
        logs/'terrain.log',output,environment,900)
    raw=output/'raw';raw.mkdir()
    print('Extracting collision for placed city models...',flush=True)
    run([work/'bin/vmap4extractor','-d',client,'-p','wow_classic_beta','-dl','ruRU','-l','--threads',str(threads)],
        logs/'vmap-extract.log',raw,environment,1800)
    print('Assembling staged VMAP trees and models...',flush=True)
    run([assembler,'--threads',str(threads),raw/'Buildings',output/'vmaps'],
        logs/'vmap-assemble.log',output,environment,1800)
    print('Probing city collision using the server VMAP manager...',flush=True)
    probe=subprocess.run([str(work/'bin/check-height'),str(output/'vmaps'),str(map_id),str(gx),str(gy)],
                         text=True,capture_output=True,timeout=180)
    (logs/'height-probe.log').write_text(probe.stdout+probe.stderr)
    candidates=[line for line in probe.stdout.splitlines() if line.startswith('{')]
    result=json.loads(candidates[-1]) if candidates else dict(load_success=False,error='No height probe JSON')
    result['process_returncode']=probe.returncode
    (output/'height-probe.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('map-id','wdt-id','grid-x','grid-y','threads'):parser.add_argument('--'+name,type=int,required=True)
    args=parser.parse_args()
    try:
        if not (0<args.map_id<=65535 and 0xf00000<=args.wdt_id<0xffff00 and
                0<=args.grid_x<64 and 0<=args.grid_y<64 and 1<=args.threads<=8):
            raise ValueError('Invalid one-map extraction arguments')
        result=extract('/wow','/out',args.map_id,args.wdt_id,args.grid_x,args.grid_y,args.threads)
        if not result.get('load_success') or not result.get('city_collision_samples'):raise ValueError('No validated city collision samples')
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print('Geometry extraction stopped:',error,flush=True)
        raise SystemExit(1)
