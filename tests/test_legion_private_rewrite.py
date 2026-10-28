"""Typed binary rewrites and transactional staging, using owned synthetic bytes."""
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('private_rewrite', SCRIPTS/'rewrite-legion-package.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def chunk(tag, body, reverse=False):
    return (tag[::-1] if reverse else tag).encode() + struct.pack('<I',len(body)) + body


class PrivateRewriteTests(unittest.TestCase):
    def test_m2_typed_slots_leave_embedded_payload_and_animation_numbers_unchanged(self):
        data = (chunk('MD21', b'MD20'+struct.pack('<I',123)) + chunk('TXID',struct.pack('<II',123,0)) +
                chunk('AFID',struct.pack('<HHI',123,4,123)) + chunk('SKPD',struct.pack('<4I',1,123,123,123)))
        body, changes = mod.rewrite('own.m2',data,{123:15728640},{(123,'TXID'),(123,'AFID'),(123,'SKPD')})
        self.assertEqual(len(changes),3)
        self.assertEqual(len(body),len(data))
        self.assertIn(b'MD20'+struct.pack('<I',123),body)
        self.assertIn(struct.pack('<HHI',123,4,15728640),body)
        self.assertIn(struct.pack('<4I',1,123,15728640,123),body)

    def test_placement_flags_and_modi_indexes_are_not_ids(self):
        entry = bytearray(36)
        struct.pack_into('<II',entry,0,123,123)
        flagged = bytearray(entry)
        struct.pack_into('<H',flagged,34,0x40)
        doodad = bytearray(40)
        struct.pack_into('<I',doodad,0,123)
        data = (chunk('MDDF',entry+flagged,True)+chunk('MODI',struct.pack('<II',123,9),True)+
                chunk('MODD',doodad,True))
        body, changes = mod.rewrite('own.wmo',data,{123:15728640},{(123,'MDDF'),(123,'MODI-placed-by-MODD')})
        self.assertEqual(len(changes),2)
        self.assertEqual(body[8:44],entry)
        self.assertEqual(body[-40:],doodad)
        self.assertEqual(struct.unpack_from('<I',body,8+36+4)[0],123)

    def test_wdt_keeps_flags_tile_layout_and_external_ids(self):
        mphd = struct.pack('<8I',0x3ca,123,0,0,0,0,0,0)
        maid = bytearray(4096*32)
        struct.pack_into('<8I',maid,2135*32,123,124,0,0,0,555,0,0)
        data = chunk('MPHD',mphd,True)+chunk('MAID',maid,True)
        body, changes = mod.rewrite('test.wdt',data,{123:15728640,124:15728641},
                                    {(123,'MPHD'),(123,'MAID'),(124,'MAID')})
        self.assertEqual(len(changes),3)
        self.assertEqual(struct.unpack_from('<I',body,8)[0],0x3ca)
        self.assertEqual(body[-20:],data[-20:])
        self.assertIn(struct.pack('<8I',15728640,15728641,0,0,0,555,0,0),body)

    def test_unlocated_or_sidecar_only_rewrites_are_refused(self):
        for refs in ({(123,'TXID')},{(123,'sidecar')}):
            with self.assertRaises(ValueError):
                mod.rewrite('own.m2',chunk('MD21',b'owned'),{123:15728640},refs)
        with self.assertRaisesRegex(ValueError,'bounds'):
            mod.reference_slots('own.adt',b'FDDM'+struct.pack('<I',500))
        with self.assertRaisesRegex(ValueError,'array'):
            mod.reference_slots('own.m2',chunk('TXID',b'x'))

    def fixture(self, home):
        package = home/'source'
        package.mkdir()
        bodies = {'own/model.m2':chunk('MD21',b'owned model')+chunk('TXID',struct.pack('<I',101)),
                  'own/a.blp':b'BLP2owned texture','own/shared.blp':b'BLP2shared texture'}
        files=[]
        for fid,(name,body) in zip((100,101,102),bodies.items()):
            files.append(dict(path=name,bytes=len(body),file_data_ids=[fid],sha256=hashlib.sha256(body).hexdigest(),
                              source_sha256=hashlib.sha256(body).hexdigest(),ckey=hashlib.md5(body).hexdigest()))
        report=dict(format='wowforever-legion-tile-package-v1',errors=[],files=files,bytes=sum(map(len,bodies.values())),
                    references=[dict(source='own/model.m2',file_data_id=101,kind='TXID')],missing_from_export=[],
                    coverage_limits=['owned opaque sample remains unparsed'],tile={'export_tile':'23_33'})
        with zipfile.ZipFile(package/'tile-candidate.zip','w') as archive:
            for name,body in bodies.items():archive.writestr('data/'+name,body)
            archive.writestr('package-index.json',json.dumps(report))
        report['package_sha256']=mod.compare.sha_file(package/'tile-candidate.zip')
        (package/'report.json').write_text(json.dumps(report))
        plan=dict(format='wowforever-legion-private-id-plan-v1',package_sha256=report['package_sha256'],
                  private_ids=2,target_build_info_sha256='a'*64,external_dependencies=[],
                  resources=[dict(original_file_data_id=row['file_data_ids'][0],target_file_data_id=15728540+row['file_data_ids'][0]
                                  if index<2 else 102,path=row['path'],donor_ckey=row['ckey']) for index,row in enumerate(files)])
        plan_path=home/'plan.json';plan_path.write_text(json.dumps(plan))
        return package/'report.json',plan_path,bodies

    def test_stage_only_private_payloads_verifies_hashes_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);report,plan,bodies=self.fixture(home)
            before={p:p.read_bytes() for p in home.rglob('*') if p.is_file()}
            out=home/'delta'
            result=mod.prepare(report,plan,out,progress=lambda _:None)
            self.assertEqual(result['counts'],dict(private_payload_files=2,shared_file_candidates=1,
                                                   rewritten_files=1,rewritten_reference_slots=1))
            self.assertFalse(result['installable']);self.assertFalse(result['client_modified'])
            self.assertEqual(result['coverage_limits'],['owned opaque sample remains unparsed'])
            with zipfile.ZipFile(out/'private-resources.zip') as archive:
                self.assertNotIn('data/own/shared.blp',archive.namelist())
                self.assertIn(struct.pack('<I',15728641),archive.read('data/own/model.m2'))
                inner=json.loads(archive.read('private-resource-index.json'))
                self.assertEqual(inner,{k:v for k,v in result.items() if k!='package_sha256'})
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            with self.assertRaisesRegex(ValueError,'NEW'):
                mod.prepare(report,plan,out,progress=lambda _:None)

    def test_shared_parent_or_duplicate_target_fails_without_partial_output(self):
        for duplicate in (False,True):
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as temp:
                home=Path(temp);report,plan,_=self.fixture(home)
                data=json.loads(plan.read_text())
                data['resources'][0]['target_file_data_id']=15728641 if duplicate else 100
                data['private_ids']=2 if duplicate else 1
                plan.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    mod.prepare(report,plan,home/'delta',progress=lambda _:None)
                self.assertFalse((home/'delta').exists())
                self.assertFalse(list(home.glob('delta.partial-*')))

    def test_mismatching_plan_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);report,plan,_=self.fixture(home)
            data=json.loads(plan.read_text());data['resources'][0]['donor_ckey']='0'*32
            plan.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'fingerprint'):
                mod.prepare(report,plan,home/'delta',progress=lambda _:None)
            self.assertFalse((home/'delta').exists())
