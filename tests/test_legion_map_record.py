"""Synthetic WDC5 tables exercise ID zero, relative strings and opaque reserves."""
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from legion_map_db2 import MapTable,add_map
spec=importlib.util.spec_from_file_location('map_candidate',SCRIPTS/'prepare-legion-map-record.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def fixture():
    # Unpacked fields use their native widths; two scalar palettes plus flags.
    widths=[32]*6+[64,8,8,8,16,16,16,16,16,8,32,16,8,16,0,0,32,32,32,0]
    bit=0;cols=[]
    for i,width in enumerate(widths):
        cols.append([bit,width,0,0,0,0,0]);bit+=width
    packed=(bit+7)//8
    cols[20]=[packed*8,1,8,3,0,1,0]
    cols[21]=[packed*8+1,2,8,3,1,2,0]
    cols[25]=[packed*8+3,1,12,4,3,1,3]
    size=packed+1
    strings=b'\0OwnLand\0Own name\0OtherLand\0Other name\0'
    rows=[]
    for index,(directory,name) in enumerate(((1,9),(18,28))):
        row=bytearray(size)
        for f,offset in enumerate((directory,name,0,0,0,0)):
            struct.pack_into('<I',row,f*4,3*size+offset-index*size-f*4)
        row[packed]=1|(1<<1)  # ZMP=100, WDT=500.
        rows.append(bytes(row))
    # Correct synthetic string offsets by finding the requested values explicitly.
    for i in range(2):
        row=bytearray(rows[i]);names=(b'OwnLand',b'Own name') if i==0 else (b'OtherLand',b'Other name')
        for f,value in enumerate(names):struct.pack_into('<I',row,f*4,3*size+strings.index(value)-i*size-f*4)
        rows[i]=bytes(row)
    palettes=struct.pack('<7I',0,100,0,500,0,0,0)
    prefix=struct.pack('<2I',1,777)
    body_start=204+80+104+624+len(palettes)+len(prefix)
    clear=b''.join(rows)+strings+struct.pack('<2I',0,1)
    opaque=bytes(size)+b'opaque\0'+bytes(4)
    sections=[(0,body_start,2,len(strings),0,8,0,0,0),
              (0x12345678,body_start+len(clear),1,7,0,4,0,0,0)]
    header=b'WDC5'+struct.pack('<I',5)+b'owned synthetic schema'.ljust(128,b'\0')
    header+=struct.pack('<9IHh7I',3,26,size,len(strings)+7,0xbd84cd62,0xd43afac3,0,777,256,
                        4,0,26,packed,0,624,0,len(palettes),2)
    return header+b''.join(struct.pack('<Q8I',*s) for s in sections)+bytes(104)+\
           b''.join(struct.pack('<HH5I',*c) for c in cols)+palettes+prefix+clear+opaque


class MapRecordTests(unittest.TestCase):
    def test_new_record_preserves_old_rows_opaque_sections_and_zero_id_position(self):
        source=fixture();old=MapTable(source)
        result=add_map(source,1220,15730590);new=MapTable(result)
        self.assertEqual(len(old.semantic),2);self.assertEqual(len(new.semantic),3)
        self.assertEqual(new.records[0][0],0)
        self.assertEqual(new.semantic[1220][:2],('ForeverDalaran','Dalaran (Legion test)'))
        self.assertEqual(new.semantic[1220][20:22],(0,15730590))
        for fid,value in old.semantic.items():self.assertEqual(new.semantic[fid],value)
        self.assertIn(777,new.reserved)
        a,b=old.section_headers[1],new.section_headers[2]
        self.assertEqual(source[a[1]:],result[b[1]:b[1]+len(source)-a[1]])
        self.assertEqual(len(result)-len(source),80+4+old.record_size+4+38)

    def test_existing_and_opaque_map_ids_and_bad_names_are_refused(self):
        for mid in (1,777):
            with self.assertRaisesRegex(ValueError,'reserved'):add_map(fixture(),mid,15730590)
        for value in ('','../bad','bad/name'):
            with self.assertRaises(ValueError):add_map(fixture(),1220,15730590,directory=value)
        with self.assertRaisesRegex(ValueError,'directory'):add_map(fixture(),1220,15730590,directory='ownland')
        with self.assertRaises(ValueError):add_map(fixture(),1220,99)

    def test_changed_layout_truncation_and_full_palette_are_rejected(self):
        source=fixture()
        for data in (source[:180],source[:-1]):
            with self.assertRaises((ValueError,struct.error)):MapTable(data)
        changed=bytearray(source);struct.pack_into('<I',changed,156,0)
        with self.assertRaisesRegex(ValueError,'schema'):MapTable(changed)
        old=MapTable(source);changed=bytearray(source)
        struct.pack_into('<I',changed,old.column_start+21*24+16,1)
        with self.assertRaisesRegex(ValueError,'full'):add_map(changed,1220,15730590)

    @unittest.skipUnless(os.environ.get('MAP_DB2_NATIVE_CHECKER'),'native DB2 loader checker not configured')
    def test_core_loader_retains_id_zero_and_all_old_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);source=fixture();candidate=add_map(source,1220,15730590)
            tables=[]
            for name,data in [('source',source),('candidate',candidate)]:
                p=home/name;p.write_bytes(data)
                process=subprocess.run([os.environ['MAP_DB2_NATIVE_CHECKER'],str(p)],text=True,capture_output=True)
                self.assertEqual(process.returncode,0,process.stderr)
                tables.append({line.split('\t')[0]:line for line in process.stdout.splitlines()})
            self.assertEqual(len(tables[0]),2);self.assertEqual(len(tables[1]),3)
            for fid,row in tables[0].items():self.assertEqual(tables[1][fid],row)

    def test_cli_verifies_wdt_and_writes_only_separate_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);package=home/'resources';package.mkdir()
            map_path=home/'Map.db2';map_path.write_bytes(fixture())
            main=bytearray(4096*8);struct.pack_into('<I',main,2135*8,1)
            maid=bytearray(4096*32)
            def chunk(tag,data):return tag[::-1].encode()+struct.pack('<I',len(data))+data
            body=(chunk('MVER',struct.pack('<I',18))+chunk('MPHD',struct.pack('<8I',0x200,0,0,0,0,0,0,0))+
                  chunk('MAIN',main)+chunk('MAID',maid))
            row=dict(path='maps/own/own.wdt',payload='data/maps/own/own.wdt',target_file_data_ids=[15730590],
                     bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),ckey=hashlib.md5(body).hexdigest())
            report=dict(format='wowforever-legion-private-resource-stage-v1',reference_parser_revision=2,
                        files=[row],tile=dict(declared_map_id=1220,raw_maid_index=2135),unresolved_additional_placement_ids=[42],
                        target_build_info_sha256=hashlib.sha256(b'owned build').hexdigest())
            with zipfile.ZipFile(package/'private-resources.zip','w') as archive:
                archive.writestr(row['payload'],body);archive.writestr('private-resource-index.json',json.dumps(report))
            report['package_sha256']=cli.comparison.sha_file(package/'private-resources.zip')
            rp=package/'report.json';rp.write_text(json.dumps(report))
            before={p:p.read_bytes() for p in home.rglob('*') if p.is_file()}
            result=cli.prepare(map_path,rp,home/'candidate',progress=lambda _:None)
            self.assertFalse(result['installable']);self.assertFalse(result['client_modified'])
            self.assertEqual(result['wdt_file_data_id'],15730590)
            self.assertEqual(result['unresolved_placement_ids'],[42])
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            with self.assertRaisesRegex(ValueError,'NEW'):cli.prepare(map_path,rp,home/'candidate')

            client=home/'client';client.mkdir();(client/'.build.info').write_bytes(b'owned build')
            source_sha=hashlib.sha256(map_path.read_bytes()).hexdigest()
            native={42:dict(status='OPEN_FAILED',error='2'),1349477:dict(status='READ_OK',sha256=source_sha)}
            with patch.object(cli.comparison,'scan',return_value=native) as scan:
                matched=cli.prepare(map_path,rp,home/'matched',client,progress=lambda _:None)
                self.assertEqual(scan.call_args.args[2],[42,1349477])
                self.assertTrue(matched['source_build_match_verified'])
                self.assertEqual(matched['additional_placement_checks'][0]['native']['status'],'OPEN_FAILED')
                self.assertFalse(matched['installable'])
            native[1349477]=dict(status='READ_FAILED',error='1007')
            with patch.object(cli.comparison,'scan',return_value=native):
                missing=cli.prepare(map_path,rp,home/'unmatched',client,progress=lambda _:None)
                self.assertFalse(missing['source_build_match_verified'])
                self.assertEqual(missing['source_map_native_check']['status'],'READ_FAILED')
