"""Read-only role matching must use WDT slot structure, not file extensions."""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('root_audit',ROOT/'scripts/audit-legion-root-types.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def chunk(tag,body):return tag+struct.pack('<I',len(body))+body


class RootTypeTests(unittest.TestCase):
    def test_native_slots_distinguish_root_texture_object_and_auxiliary_files(self):
        main=bytearray(4096*8);struct.pack_into('<I',main,2135*8,1)
        maid=bytearray(4096*32);struct.pack_into('<8I',maid,2135*32,*range(101,109))
        data=chunk(b'REVM',struct.pack('<I',18))+chunk(b'DHPM',struct.pack('<8I',0x200,*range(201,208)))
        data+=chunk(b'NIAM',main)+chunk(b'DIAM',maid)
        result=audit.world_roles(data)
        self.assertEqual(result['terrain_root'],{101});self.assertEqual(result['terrain_obj1'],{103})
        self.assertEqual(result['terrain_tex0'],{104});self.assertEqual(result['map_lighting'],{201})
        self.assertEqual(result['map_tex'],{205});self.assertEqual(result['map_wdl'],{206})
        with self.assertRaises(ValueError):audit.world_roles(data[:-1])
        with self.assertRaises(ValueError):audit.world_roles(data+chunk(b'REVM',b'bad'))

    def test_profiles_preserve_native_raw_type_bytes_and_locales(self):
        # Two entries use different world-file types. Keep the raw split fields.
        header=b'TSFM'+struct.pack('<5I',24,2,2,0,0)
        a=struct.pack('<4IB',1,0x173f6,0,0x12000000,39)+struct.pack('<I',775971)+b'a'*16
        b=struct.pack('<4IB',1,0xffffffff,0x10000000,0,0)+struct.pack('<I',15730590)+b'b'*16
        result=audit.profiles(header+a+b,{775971,15730590})
        self.assertEqual(result[775971][0]['raw_flags'],[0,0x12000000,39])
        self.assertEqual(result[15730590][0]['raw_flags'],[0x10000000,0,0])
        self.assertEqual(result[775971][0]['locale'],0x173f6)
        self.assertEqual(result[15730590][0]['ckey'],'62'*16)
