import importlib.util
from pathlib import Path
import struct
import unittest

spec=importlib.util.spec_from_file_location('prepare',Path(__file__).parents[1]/'scripts/prepare-ascension-spells.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

def dbc(records):
    raw=b''.join(struct.pack('<234I',*r) for r in records)
    strings=b'\0Mana-forged Barrier\0Description\0'
    return struct.pack('<4s4I',b'WDBC',len(records),234,936,len(strings))+raw+strings

class SpellPrepareTests(unittest.TestCase):
    def test_decode_signed_float_text_and_dependencies_without_activation(self):
        first=[0]*234;first[0]=701463;first[71]=6;first[95]=97;first[80]=0xFFFFFFFF
        first[101]=struct.unpack('<I',struct.pack('<f',1.5))[0]
        first[136]=1;first[170]=20;first[116]=277423
        second=[0]*234;second[0]=277423;second[71]=114;second[116]=701463
        data=prepare.SpellDBC(dbc([first,second]));rows,missing=prepare.prepare(data,{701463,999})
        self.assertEqual(set(rows),{701463,277423});self.assertEqual(missing,[999])
        self.assertEqual(rows[701463]['names'][0],'Mana-forged Barrier')
        effect=rows[701463]['effects'][0]
        self.assertEqual(effect['base_points'],-1);self.assertEqual(effect['value_multiplier'],1.5)
        self.assertEqual(rows[701463]['raw_words'],first)

    def test_bad_layout_truncation_duplicates_and_string_bounds_fail(self):
        first=[0]*234;first[0]=1
        with self.assertRaises(ValueError):prepare.SpellDBC(dbc([first])[:-1])
        with self.assertRaises(ValueError):prepare.SpellDBC(dbc([first,first]))
        bad=bytearray(dbc([first]));struct.pack_into('<I',bad,8,222)
        with self.assertRaises(ValueError):prepare.SpellDBC(bad)
        first[136]=0xFFFFFFFF
        with self.assertRaises(ValueError):prepare.SpellDBC(dbc([first])).spell(1)
