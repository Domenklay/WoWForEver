#!/usr/bin/env python3
"""Offline, terrain-only MAPS v9 -> Forever v10 candidate; never deploys data.

Only area/height blocks and low-resolution holes are supported. Liquid tiles
are rejected until their flags, types and tables are mapped explicitly.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


def expand_holes(data):
    if len(data) != 512:
        raise ValueError('Expected 256 uint16 low-resolution hole masks')
    output = bytearray()
    # Same spatial expansion as the pinned Forever extractor's TransformToHighRes.
    for mask, in struct.iter_unpack('<H', data):
        for y in range(8):
            output.append(sum(((mask >> ((y//2)*4+x//2)) & 1) << x for x in range(8)))
    return bytes(output)


def convert(data):
    if len(data) < 44:
        raise ValueError('Truncated MAP header')
    magic, version, build, *bounds = struct.unpack_from('<4s10I', data)
    if magic != b'MAPS' or version != 9:
        raise ValueError('Expected MAPS integer version 9')
    blocks = []
    cursor = 44
    for name, offset, size in zip(('area', 'height', 'liquid', 'holes'), bounds[::2], bounds[1::2]):
        if bool(offset) != bool(size):
            raise ValueError('Inconsistent block offset/size: '+name)
        if size:
            if offset != cursor or size > len(data)-offset:
                raise ValueError('Noncontiguous, overlapping or truncated block: '+name)
            cursor += size
        blocks.append(data[offset:offset+size] if size else b'')
    if cursor != len(data):
        raise ValueError('Unexpected trailing bytes')
    area, height, liquid, holes = blocks
    if liquid:
        raise ValueError('Liquid conversion is not implemented; candidate refused')
    if len(area) < 8:
        raise ValueError('Missing area block')
    tag, flags, area_id = struct.unpack_from('<4sHH', area)
    if tag != b'AREA' or flags & ~1 or len(area) != (8 if flags & 1 else 520):
        raise ValueError('Unsupported area block')
    if len(height) < 16:
        raise ValueError('Missing height block')
    tag, flags, low, high = struct.unpack_from('<4sIff', height)
    if tag != b'MHGT' or flags & ~15 or (flags & 6) == 6 or not all(map(math.isfinite, (low, high))) or high < low:
        raise ValueError('Unsupported height encoding')
    width = 2 if flags & 2 else 1 if flags & 4 else 4
    expected = 16 + (0 if flags & 1 else (129*129+128*128)*width) + (36 if flags & 8 else 0)
    if len(height) != expected:
        raise ValueError('Height sample count/flight-bound size mismatch')
    output_blocks = [area, height, b'', expand_holes(holes) if holes else b'']
    new_bounds = []
    cursor = 44
    for block in output_blocks:
        new_bounds.extend((cursor, len(block)) if block else (0, 0))
        cursor += len(block)
    result = struct.pack('<4s10I', b'MAPS', 10, build, *new_bounds) + b''.join(output_blocks)
    return result, dict(source_build=build, area_bytes=len(area), height_bytes=len(height),
                        source_holes_bytes=len(holes), candidate_holes_bytes=len(output_blocks[3]),
                        area_and_height_bytes_unchanged=True, native_gridmap_load_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map-id', type=int, required=True)
    parser.add_argument('--tile-x', type=int, required=True)
    parser.add_argument('--tile-y', type=int, required=True)
    args = parser.parse_args()
    if not 0 <= args.map_id <= 9999 or not all(0 <= n < 64 for n in (args.tile_x, args.tile_y)):
        parser.error('Invalid map/grid coordinates')
    if args.output.exists():
        parser.error('Output must be a new directory')
    source = args.input.read_bytes()
    candidate, report = convert(source)
    args.output.mkdir(parents=True, exist_ok=False)
    name = f'{args.map_id:04}_{args.tile_x:02}_{args.tile_y:02}.map'
    (args.output/'maps').mkdir()
    (args.output/'maps'/name).write_bytes(candidate)
    report.update(format='wowforever-335-terrain-candidate-v1', map_id=args.map_id,
                  grid_x=args.tile_x, grid_y=args.tile_y, file='maps/'+name,
                  source_sha256=hashlib.sha256(source).hexdigest(),
                  candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                  map_id_and_coordinates_independently_verified=False,
                  installable=False, deployed=False,
                  blockers=['Native GridMap load/height probe not run', 'Client map record and WDT/assets not verified',
                            'VMAP collision geometry missing', 'Area IDs require Forever table comparison',
                            'Only one terrain tile; complete map coverage not established'])
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Terrain candidate:', args.output/'maps'/name)
    print('NOT INSTALLABLE: server terrain conversion only. Report:', args.output/'report.json')


if __name__ == '__main__':
    main()
