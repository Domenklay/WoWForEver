#!/usr/bin/env python3
"""Owned-plane test of isolated model names and mandatory spawn indexes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def check(assembler,probe,scripts):
    sys.path.insert(0,str(scripts))
    from legion_activation import stage_geometry
    spec=importlib.util.spec_from_file_location('owned_plane',Path(__file__).with_name('test-owned-plane.py'))
    owned=importlib.util.module_from_spec(spec);spec.loader.exec_module(owned)
    with tempfile.TemporaryDirectory(prefix='owned-activation-') as temp:
        root=Path(temp);source=root/'source';source.mkdir()
        raw=owned.fixture(root)
        subprocess.run([str(assembler),'--threads','1',str(raw),str(source/'vmaps')],check=True,capture_output=True)
        (source/'maps').mkdir()
        (source/'maps/1220_33_23.map').write_bytes(b'owned terrain placeholder')
        (source/'maps/1220.tilelist').write_bytes(b'owned tile placeholder')
        files=[dict(path=p.relative_to(source).as_posix(),bytes=p.stat().st_size,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in source.rglob('*')
               if p.is_file() and p.suffix!='.vmtileidx']
        report=dict(format='wowforever-legion-geometry-extraction-v1',geometry_probe_passed=True,
                    errors=[],map_id=1220,wdt_file_data_id=15730590,client_metadata_unchanged=True,
                    tile=dict(world_tile_x=33,world_tile_y=23,raw_maid_index=2135),
                    compiled_core_revision='91d49b230f89c3ab4719f5b2b2d1e70ed36613c4',
                    files=files,source_install_operation='owned-fixture')
        (source/'report.json').write_text(json.dumps(report))
        staged=root/'staged';result=stage_geometry(source,staged)
        if not any(r['path'].endswith('.vmtileidx') for r in result['files']):
            raise ValueError('Spawn indexes were not staged')
        if (staged/'vmaps/own-plane.raw.vmo').exists(): raise ValueError('Old model name was retained')
        process=subprocess.run([str(probe),str(staged/'vmaps'),'1220','33','23'],check=True,capture_output=True,text=True)
        data=json.loads(next(x for x in process.stdout.splitlines() if x.startswith('{')))
        if any(abs(s['height']-735)>.01 for s in data['samples']): raise ValueError('Changed height after isolation')
        return dict(game_assets_used=False,model_names_isolated=True,spawn_indexes_preserved=True,
                    native_height_samples=data['city_collision_samples'],expected_height=735,
                    client_hotfix_runtime_verified=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assembler',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--scripts',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(check(args.assembler,args.probe,args.scripts),indent=2))
