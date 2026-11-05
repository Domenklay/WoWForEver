import importlib.util
from pathlib import Path
import struct
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('terrain335',ROOT/'scripts/convert-335-terrain.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def tile(flags=1,liquid=b'',holes=None):
    area=struct.pack('<4sHH',b'AREA',1,3483)
    width=2 if flags&2 else 1 if flags&4 else 4
    height=struct.pack('<4sIff',b'MHGT',flags,1.0,5.0)
    if not flags&1:height+=bytes((129*129+128*128)*width)
    if flags&8:height+=bytes(36)
    blocks=[area,height,liquid,bytes(512) if holes is None else holes]
    cursor=44;bounds=[]
    for b in blocks:
        bounds.extend((cursor,len(b)) if b else (0,0));cursor+=len(b)
    return struct.pack('<4s10I',b'MAPS',9,12340,*bounds)+b''.join(blocks)

class Terrain335Tests(unittest.TestCase):
    def test_each_supported_height_representation_preserves_bytes_and_build(self):
        for flags in (0,1,2,4,8,9,10,12):
            with self.subTest(flags=flags):
                source=tile(flags)
                candidate,report=module.convert(source)
                a=struct.unpack_from('<4s10I',source);b=struct.unpack_from('<4s10I',candidate)
                self.assertEqual(b[:3],(b'MAPS',10,12340))
                self.assertEqual(source[44:a[9]],candidate[44:b[9]])
                self.assertEqual(b[10],2048)
                self.assertFalse(report['native_gridmap_load_verified'])

    def test_holes_expand_spatially_in_both_axes(self):
        masks=struct.pack('<H',1)+struct.pack('<H',1<<15)+bytes(508)
        expanded=module.expand_holes(masks)
        self.assertEqual(expanded[:8],bytes([3,3,0,0,0,0,0,0]))
        self.assertEqual(expanded[8:16],bytes([0,0,0,0,0,0,192,192]))
        self.assertEqual(len(expanded),2048)
        self.assertEqual(module.expand_holes(bytes([255])*512),bytes([255])*2048)

    def test_refuses_liquids_unknown_flags_truncation_and_bad_versions(self):
        bad_version=bytearray(tile());struct.pack_into('<I',bad_version,4,10)
        for source in (tile(liquid=b'MLIQ'),tile(flags=6),tile(flags=16),tile()[:-1],tile()+b'x',bytes(bad_version)):
            with self.subTest(size=len(source)):
                with self.assertRaises(ValueError):module.convert(source)

    def test_refuses_overlapping_blocks(self):
        source=bytearray(tile());struct.pack_into('<I',source,20,44)
        with self.assertRaises(ValueError):module.convert(source)
