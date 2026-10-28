#!/usr/bin/env python3
"""Native assembler/VMAP-manager test with an owned two-triangle plane, no assets."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile


def fixture(root):
    raw=root/'raw';(raw/'dir_bin').mkdir(parents=True)
    data=b'VMAP04E\0'+struct.pack('<4I',4,1,42,0)
    data+=struct.pack('<II6fI',0,42,-250,-250,-1,250,250,1,0)
    data+=b'GRP '+struct.pack('<II',4,0)
    data+=b'INDX'+struct.pack('<II6I',28,6,0,1,2,0,2,3)
    data+=b'VERT'+struct.pack('<II12f',52,4,-250,-250,0,250,-250,0,250,250,0,-250,250,0)
    (raw/'own-plane.raw').write_bytes(data)
    mid=1600*32/3;pos=(mid+800,mid-4500,735);name=b'own-plane.raw'
    spawn=struct.pack('<BBI7f6fI',1,0,1001,*pos,0,0,0,1,pos[0]-250,pos[1]-250,734,
                      pos[0]+250,pos[1]+250,736,len(name))+name
    (raw/'dir_bin/1220').write_bytes(spawn)
    return raw


def check(assembler,probe):
    with tempfile.TemporaryDirectory(prefix='owned-vmap-') as temp:
        root=Path(temp);raw=fixture(root)
        subprocess.run([str(assembler),'--threads','1',str(raw),str(root/'vmaps')],check=True,capture_output=True)
        process=subprocess.run([str(probe),str(root/'vmaps'),'1220','33','23'],check=True,capture_output=True,text=True)
        data=json.loads(next(line for line in process.stdout.splitlines() if line.startswith('{')))
        if not data['load_success'] or not data['samples'] or any(abs(r['height']-735)>.01 for r in data['samples']):
            raise ValueError('Owned plane height/coordinate check failed')
        missing=subprocess.run([str(probe),str(root/'vmaps'),'1220','5','5'],capture_output=True,text=True)
        if missing.returncode==0:raise ValueError('Nonexistent tile accepted')
        return dict(owned_fixture=True,game_assets_used=False,expected_height=735,
                    collision_samples=len(data['samples']),actual_height_range=[min(r['height'] for r in data['samples']),max(r['height'] for r in data['samples'])],
                    missing_tile_rejected=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assembler',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(check(args.assembler,args.probe),indent=2))
