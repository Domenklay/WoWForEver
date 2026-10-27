import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


namespace=load('namespace_test','plan-legion-namespace.py')
copier=load('namespace_copier','prepare-legion-client.py')
lab=namespace.canary.lab


class NamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source,self.target=self.root/'source',self.root/'copy'
        make_root=lab.make_root
        def extra_locale(records):
            original=make_root(records)
            return namespace.canary.append_root(original,
                    {namespace.POOL_START:hashlib.md5(b'owned alternate-locale reservation').digest()},locale=128)
        with patch.object(lab,'make_root',extra_locale):
            marker=lab.write_store(self.source)
        shared=bytearray(20480)
        struct.pack_into('<I',shared,0,5)
        struct.pack_into('<16I',shared,0x110,*([1]*16))
        (self.source/'Data/data/shmem').write_bytes(shared)
        (self.source/'_classic_beta_').mkdir()
        (self.source/'_classic_beta_/WowB.exe').write_bytes(b'owned fixture; not an executable')
        copier.prepare(self.source,self.target,marker['build_key'])
        self.package=self.root/'package.json'
        self.comparison=self.root/'comparison.json'
        self.output=self.root/'private.json'
        self.new_id=1234
        self.write_reports()

    def write_reports(self):
        rows=[]
        for fid,body in ((lab.BASE_ID,lab.BASE_TEXT),(self.new_id,b'owned new texture')):
            rows.append(dict(path=f'own/{fid}.m2',file_data_ids=[fid],bytes=len(body),
                             ckey=hashlib.md5(body).hexdigest(),sha256=hashlib.sha256(body).hexdigest(),transformation=None))
        package=dict(package_sha256='a'*64,errors=[],coverage_limits=[],files=rows,
                     references=[dict(source=rows[0]['path'],file_data_id=self.new_id,kind='TXID')])
        self.package.write_text(json.dumps(package))
        resources=[dict(file_data_id=row['file_data_ids'][0],path=row['path'],package_ckey=row['ckey'],
                        package_sha256=row['sha256'],classification='identical' if index==0 else 'not_readable_requires_ROOT_check')
                   for index,row in enumerate(rows)]
        comparison=dict(format='wowforever-legion-client-comparison-v1',source_report_sha256=namespace.comparison.sha_file(self.package),
                        package_sha256=package['package_sha256'],client_build_info_sha256=namespace.comparison.sha_file(self.source/'.build.info'),
                        resources=resources,external_dependencies=[])
        self.comparison.write_text(json.dumps(comparison))

    def plan(self):
        return namespace.plan(self.comparison,self.package,self.target,self.output,progress=lambda _:None)

    def snapshot(self,path):
        return {p.relative_to(path):p.read_bytes() for p in path.rglob('*') if p.is_file()}

    def test_all_locale_reservations_and_parent_clone_without_client_writes(self):
        before=self.snapshot(self.target)
        source=self.snapshot(self.source)
        result=self.plan()
        self.assertEqual(result['private_ids'],2)
        ids={row['target_file_data_id'] for row in result['resources']}
        self.assertEqual(ids,{namespace.POOL_START+1,namespace.POOL_START+2})
        parent=next(row for row in result['resources'] if row['original_file_data_id']==lab.BASE_ID)
        self.assertEqual(parent['action'],'rewrite_references_then_rehash')
        self.assertFalse(result['references_rewritten'])
        self.assertFalse(result['installable'])
        self.assertEqual(self.snapshot(self.target),before)
        self.assertEqual(self.snapshot(self.source),source)

    def test_reserved_but_nonresident_donor_id_receives_a_different_private_id(self):
        self.new_id=namespace.POOL_START
        self.write_reports()
        result=self.plan()
        child=next(row for row in result['resources'] if row['original_file_data_id']==self.new_id)
        self.assertTrue(child['original_id_reserved_in_target'])
        self.assertNotEqual(child['target_file_data_id'],self.new_id)
        self.assertEqual(child['root_variants'][0]['locale'],128)

    def test_unrelated_copy_baseline_refused(self):
        path=self.target/'legion-client-copy.json'
        value=json.loads(path.read_text())
        value['sha256']['.build.info']='0'*64
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'baseline/source build'):
            self.plan()
        self.assertFalse(self.output.exists())

    def test_incomplete_comparison_cannot_allocate_ids(self):
        data=json.loads(self.comparison.read_text())
        data['resources'].pop()
        self.comparison.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'Incomplete/duplicate'):
            self.plan()

    def test_allocation_exhaustion_fails_instead_of_reusing_reserved_ids(self):
        with self.assertRaisesRegex(ValueError,'pool exhausted'):
            namespace.allocate({1,2},{100,101},start=100,end=103)

    def test_cycles_stop_and_shared_parent_is_cloned(self):
        package=json.loads(self.package.read_text())
        package['references'].append(dict(source=package['files'][1]['path'],file_data_id=lab.BASE_ID,kind='fixture-cycle'))
        self.package.write_text(json.dumps(package))
        data=json.loads(self.comparison.read_text())
        data['source_report_sha256']=namespace.comparison.sha_file(self.package)
        self.comparison.write_text(json.dumps(data))
        self.assertEqual(self.plan()['private_ids'],2)

    def test_target_index_change_prevents_publishing(self):
        inspect=namespace.inspect_root
        def change(store,*args,**kwargs):
            result=inspect(store,*args,**kwargs)
            path=next((self.target/'Data/data').glob('*.idx'))
            path.write_bytes(path.read_bytes()+b'changed during read')
            return result
        with patch.object(namespace,'inspect_root',change):
            with self.assertRaisesRegex(ValueError,'IDX changed'):
                self.plan()
        self.assertFalse(self.output.exists())

    def test_shmem_disagreement_cannot_select_stale_indexes(self):
        path=self.target/'Data/data/shmem'
        raw=bytearray(path.read_bytes())
        struct.pack_into('<I',raw,0x110,2)
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'shmem/index selection'):
            self.plan()
        self.assertFalse(self.output.exists())

    def test_external_root_match_does_not_imply_a_resident_payload(self):
        data=json.loads(self.comparison.read_text())
        key=hashlib.md5(b'owned alternate-locale reservation').hexdigest()
        data['external_dependencies']=[dict(file_data_id=namespace.POOL_START,native=dict(ckey=key,status='READ_OK'))]
        self.comparison.write_text(json.dumps(data))
        result=self.plan()
        entry=result['external_dependencies'][0]
        self.assertTrue(entry['target_root_matches_source'])
        self.assertIsNone(entry['encoding'])
        self.assertTrue(entry['requires_final_target_read_check'])
