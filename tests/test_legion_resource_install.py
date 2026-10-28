"""Native storage batch integration: owned payloads, failures and exact rollback."""
import hashlib
import importlib.util
import json
import os
import struct
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('resource_install',SCRIPTS/'install-legion-resources.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
spec=importlib.util.spec_from_file_location('container_fixture',Path(__file__).with_name('test_native_container_canary.py'))
fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)
from casc_manifest_update import Encoding


class ResourceBatchTests(unittest.TestCase):
    def setUp(self):
        original=fixture_module.native.lab.asset
        def two_frames(content):
            if content==b"DL\1\x10\0"+bytes(11):
                base=two_frames(fixture_module.native.lab.BASE_TEXT)
                # Real-shaped 30 tags and one-filled unused bitmap bits.
                content=(b"DL\1\x10\0"+struct.pack(">IH",1,30)+base['ekey']+
                         len(base['encoded']).to_bytes(5,'big')+b"\0")
                for n in range(30):
                    bitmap=0xff if 0x3fffe3ff&(1<<n) else 0x7f
                    content+=f'owned-tag-{n}'.encode()+b"\0\0\0"+bytes([bitmap])
                # Pinned CascLib checks four bytes remain before reading a two-byte tag type.
                content+=b"\0"
            obj=original(content)
            if content==fixture_module.native.lab.BASE_TEXT:
                middle=len(content)//2
                frames=[b'N'+content[:middle],b'N'+content[middle:]]
                head=b'BLTE'+struct.pack('>I',60)+b'\x0f\x00\x00\x02'
                for frame in frames:head+=struct.pack('>II',len(frame),len(frame)-1)+hashlib.md5(frame).digest()
                obj['encoded']=head+b''.join(frames);obj['ekey']=hashlib.md5(head).digest()
            return obj
        self.fixture=fixture_module.NativeContainerTests()
        with patch.object(fixture_module.native.lab,'asset',two_frames):self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root,self.client=self.fixture.root,self.fixture.copy
        self.package=self.root/'package';self.package.mkdir()
        self.report_path=self.package/'report.json'
        lab=installer.canary.lab
        self.bodies={'owned/shared.txt':lab.BASE_TEXT,'owned/private-same.txt':lab.BASE_TEXT,
                     'owned/private-new.txt':b'owned fresh private payload\n'}
        self.rows=[]
        for index,(path,body) in enumerate(self.bodies.items()):
            self.rows.append(dict(path=path,bytes=len(body),sha256=installer.canary.sha(body),
                ckey=hashlib.md5(body).hexdigest(),original_file_data_ids=[lab.BASE_ID if index==0 else 123+index],
                target_file_data_ids=[lab.BASE_ID if index==0 else 0xf00000+index],
                payload=None if index==0 else 'data/'+path))
        self.report=dict(format='wowforever-legion-private-resource-stage-v1',reference_parser_revision=2,
            typed_references_rewritten=True,target_build_info_sha256=installer.canary.sha((self.client/'.build.info').read_bytes()),
            files=self.rows,unresolved_additional_placement_ids=[])
        self.write_package()

    def write_package(self):
        self.report.pop('package_sha256',None)
        with zipfile.ZipFile(self.package/'private-resources.zip','w') as archive:
            for row in self.rows:
                if row['payload']:archive.writestr(row['payload'],self.bodies[row['path']])
            archive.writestr('private-resource-index.json',json.dumps(self.report))
        self.report['package_sha256']=installer.compare.sha_file(self.package/'private-resources.zip')
        self.report_path.write_text(json.dumps(self.report))

    def snapshot(self,path):
        return {p.relative_to(path):p.read_bytes() for p in path.rglob('*') if p.is_file()
                and p.relative_to(path).parts[0]!=installer.OPS}

    def apply(self):
        return installer.apply(self.client,self.report_path,os.environ['CASC_SANDBOX_CHECKER'],locale='enUS',
                               controls=self.fixture.controls,progress=lambda _:None)

    def test_bad_hash_duplicate_ids_and_shared_alias_fail_before_client_changes(self):
        snapshot=self.snapshot(self.client)
        self.rows[1]['target_file_data_ids']=self.rows[0]['target_file_data_ids']
        self.write_package()
        with self.assertRaisesRegex(ValueError,'Duplicate'):installer.read_package(self.report_path)
        self.assertEqual(snapshot,self.snapshot(self.client))
        self.rows[1]['target_file_data_ids']=[0xf00001];self.write_package()
        with (self.package/'private-resources.zip').open('ab') as out:out.write(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA mismatch'):installer.read_package(self.report_path)
        self.assertEqual(snapshot,self.snapshot(self.client))

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_actual_native_batch_adds_variant_preserves_originals_and_rolls_back_after_pruning(self):
        before=self.snapshot(self.client);source=self.snapshot(self.fixture.source)
        original_store=installer.canary.storelib.Store(self.client,synthetic_only=False)
        ck,ek=map(bytes.fromhex,original_store.values['encoding'].split())
        old=Encoding(original_store.read(ek,ck));base_ck=hashlib.md5(installer.canary.lab.BASE_TEXT).digest()
        old_row=dict(old.rows('c'))[base_ck]
        result=self.apply()
        self.assertEqual(result['private_resource_ids'],2)
        self.assertEqual(result['shared_resource_ids'],1)
        self.assertFalse(result['map_record_installed']);self.assertFalse(result['zone_playability_verified'])
        actual=installer.verify(self.client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None)
        self.assertEqual(actual[installer.canary.lab.BASE_ID]['tag_mask'],'3fffe3ff')
        self.assertEqual(installer.operation(self.client)[1]['download_default_tag_mask'],'3fffe3ff')
        store=installer.canary.storelib.Store(self.client,synthetic_only=False)
        ck,ek=map(bytes.fromhex,store.values['encoding'].split());encoding=Encoding(store.read(ek,ck))
        new_row=dict(encoding.rows('c'))[base_ck]
        self.assertEqual(new_row[0],2)
        self.assertIn(old_row[22:38],[new_row[i:i+16] for i in range(22,len(new_row),16)])
        self.assertEqual(source,self.snapshot(self.fixture.source))
        # The old client may prune IDX or change the new segment after launch failure.
        for path in (self.client/'Data/data').glob('*00000001.idx'):path.unlink()
        (self.client/'Data/data/RepairMarker.psv').write_bytes(b'owned repair simulation')
        (self.client/'Data/data/data.001').write_bytes(b'changed segment retained in quarantine')
        (self.client/'Data/data/data.002').write_bytes(b'archive created by failed game launch')
        folder=installer.rollback(self.client)
        self.assertTrue(list(folder.glob('after-*/data.001')))
        self.assertTrue(list(folder.glob('after-*/data.002')))
        self.assertEqual(before,self.snapshot(self.client))
        self.assertEqual(source,self.snapshot(self.fixture.source))
        installer.rollback(self.client)  # Idempotent.

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_native_postcheck_failure_rolls_back_every_modified_file(self):
        before=self.snapshot(self.client)
        with patch.object(installer,'verify',side_effect=ValueError('simulated postcheck failure')):
            with self.assertRaisesRegex(ValueError,'postcheck failure'):self.apply()
        self.assertEqual(before,self.snapshot(self.client))
        self.assertEqual(installer.operation(self.client)[1]['phase'],'rolled_back')

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_partial_index_write_failure_rolls_back(self):
        before=self.snapshot(self.client);original=Path.open
        def fail(path,mode='r',*args,**kwargs):
            if path.name=='0200000002.idx' and mode=='xb':raise OSError('simulated partial write')
            return original(path,mode,*args,**kwargs)
        with patch.object(Path,'open',fail):
            with self.assertRaisesRegex(OSError,'partial write'):self.apply()
        self.assertEqual(before,self.snapshot(self.client))

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_shared_hash_failure_and_wrong_copy_build_do_not_create_journal(self):
        before=self.snapshot(self.client)
        self.rows[0]['sha256']='0'*64;self.write_package()
        with self.assertRaisesRegex(ValueError,'Native read/hash'):self.apply()
        self.assertEqual(before,self.snapshot(self.client));self.assertFalse((self.client/installer.OPS).exists())
        self.report['target_build_info_sha256']='0'*64;self.write_package()
        with self.assertRaisesRegex(ValueError,'build differs'):self.apply()
        self.assertEqual(before,self.snapshot(self.client))


    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_batch_stacks_on_verified_resource_canary_and_restores_parent(self):
        checker=os.environ['CASC_SANDBOX_CHECKER'];parent=fixture_module.experiment
        parent.apply(self.client,checker,self.fixture.controls,self.fixture.key,progress=lambda _:None)
        parent.apply(self.client,checker,self.fixture.controls,self.fixture.key,progress=lambda _:None,resource=True)
        before=self.snapshot(self.client)
        self.report['target_build_info_sha256']=installer.canary.sha((self.client/'.build.info').read_bytes())
        self.write_package();self.apply()
        installer.canary.native_check(checker,self.client,{installer.canary.CANARY_ID:dict(
            bytes=len(installer.canary.CANARY_TEXT),sha256=installer.canary.sha(installer.canary.CANARY_TEXT))})
        installer.rollback(self.client)
        self.assertEqual(before,self.snapshot(self.client))
        parent.verify(self.client,checker)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_native_hundred_resource_batch_crosses_encoding_pages(self):
        for index in range(3,103):
            path=f'owned/batch-{index}.txt';body=f'own batch resource {index}'.encode()
            self.bodies[path]=body
            self.rows.append(dict(path=path,bytes=len(body),sha256=installer.canary.sha(body),
                ckey=hashlib.md5(body).hexdigest(),original_file_data_ids=[10000+index],
                target_file_data_ids=[0xf00000+index],payload='data/'+path))
        self.write_package();before=self.snapshot(self.client)
        result=self.apply()
        self.assertEqual(result['private_resource_ids'],102)
        self.assertEqual(result['native_verified_ids'],103)
        installer.rollback(self.client)
        self.assertEqual(before,self.snapshot(self.client))

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_collision_in_another_root_locale_is_refused_before_any_writes(self):
        native=fixture_module.native;old_root=native.lab.make_root
        def reserve(records):
            return installer.canary.append_root(old_root(records),{0xf00001:records[native.lab.BASE_ID]['ckey']},locale=128)
        other=fixture_module.NativeContainerTests()
        with patch.object(native.lab,'make_root',reserve):other.setUp()
        self.addCleanup(other.doCleanups)
        self.fixture=other;self.client=other.copy
        self.report['target_build_info_sha256']=installer.canary.sha((self.client/'.build.info').read_bytes())
        self.write_package();before=self.snapshot(self.client)
        with self.assertRaisesRegex(ValueError,'ROOT FileDataID conflict'):self.apply()
        self.assertEqual(before,self.snapshot(self.client));self.assertFalse((self.client/installer.OPS).exists())

    def test_encoding_variant_rejects_fabricated_ekey_and_size_conflict(self):
        from casc_manifest_update import extend_encoding
        lab=installer.canary.lab;old=lab.asset(b'own existing content');data=lab.make_encoding([old])
        bad=dict(old,ekey=bytes(16))
        with self.assertRaisesRegex(ValueError,'single N frame'):extend_encoding(data,[bad],allow_variants=True)
        bad=dict(lab.asset(b'other content'),ckey=old['ckey'])
        with self.assertRaisesRegex(ValueError,'fingerprint conflict'):extend_encoding(data,[bad],allow_variants=True)
