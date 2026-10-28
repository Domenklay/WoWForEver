"""Typed ROOT/TVFS replacement, native reads, inheritance and rollback."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('type_repair',ROOT/'scripts/repair-legion-root-types.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
from casc_manifest_update import append_root,root_groups,Encoding


class TypeRepairTests(unittest.TestCase):
    def test_root_preserves_original_groups_keys_and_counts(self):
        initial=b'TSFM'+struct.pack('<5I',24,2,0,0,0)
        original=append_root(initial,{17:b'a'*16})
        raw=append_root(original,{0xf00000:b'b'*16,0xf00001:b'c'*16},locale=0xffffffff)
        plan={0xf00000:dict(locale=0x173f6,raw_flags=(0,0x12000000,39),ckey='62'*16),
              0xf00001:dict(locale=0x173f6,raw_flags=(0,0x14000000,34),ckey='63'*16)}
        new=repair.replace_root(raw,plan)
        self.assertEqual(new[:len(original)],original[:12]+raw[12:24]+original[24:])
        self.assertEqual([r['content_flags'] for r in list(root_groups(new))[1:]],[[0,0x12000000,39],[0,0x14000000,34]])
        self.assertEqual(len(new),len(raw)+17)
        bad=dict(plan);bad[0xf00000]=dict(plan[0xf00000],ckey='64'*16)
        with self.assertRaises(ValueError):repair.replace_root(raw,bad)
        with self.assertRaises(ValueError):repair.replace_root(raw,{0xf00000:plan[0xf00000]})
        with self.assertRaises(ValueError):repair.replace_root(new,plan)

    def test_tvfs_renames_only_bound_private_id_and_checks_ckey(self):
        plan={0xf00000:dict(locale=0x173f6,raw_flags=(0,0x12000000,39),ckey='62'*16)}
        change,seen=repair.tvfs_renamer(plan)
        self.assertEqual(change('FFFFFFFF10000000:00F00000'+'62'*16),'000173F6124E0000:00F00000'+'62'*16)
        self.assertEqual(change('.root'),'.root');self.assertEqual(seen,{0xf00000})
        with self.assertRaises(ValueError):change('FFFFFFFF10000000:00F00000'+'62'*16)
        change,_=repair.tvfs_renamer(plan)
        with self.assertRaises(ValueError):change('FFFFFFFF10000000:00F00000'+'63'*16)

    def test_missing_skin_uses_observed_kind_and_rejects_invalid_body(self):
        fid=0xf00000;body=b'SKINowned fixture';ckey=hashlib.md5(body).digest()
        row=dict(path='owned/new.skin',payload='data/owned/new.skin',target_file_data_ids=[fid],original_file_data_ids=[13])
        namespace=dict(resources=[dict(path=row['path'],target_file_data_id=fid,original_file_data_id=13,root_variants=[]),
            dict(path='owned/control.skin',target_file_data_id=14,original_file_data_id=14,
                 root_variants=[dict(locale=0x173f6,raw_flags=[0,0x12000000,9])])])
        audit=dict(private_resources=[dict(path=row['path'],file_data_ids=[fid],root_profiles={str(fid):[
            dict(locale=0xffffffff,raw_flags=[0x10000000,0,0],ckey=ckey.hex())]})])
        p,e=repair.policies(dict(files=[row]),namespace,audit,{fid:dict(ckey=ckey,content=body)})
        self.assertEqual(p[fid]['raw_flags'],(0,0x12000000,9));self.assertEqual(e,dict(same_kind_profile=1))
        with self.assertRaisesRegex(ValueError,'kind does not match'):
            repair.policies(dict(files=[row]),namespace,audit,{fid:dict(ckey=ckey,content=b'not a skin')})

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native checker required')
    def test_native_metadata_layer_preserves_payloads_and_restores_parent_on_rollback(self):
        from test_legion_resource_install import ResourceBatchTests
        fixture=ResourceBatchTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        namespace=dict(resources=[dict(path=r['path'],target_file_data_id=r['target_file_data_ids'][0],
                         original_file_data_id=r['original_file_data_ids'][0],
                         root_variants=[dict(locale=0x173f6,raw_flags=[0,0x12000000,4])]) for r in fixture.rows])
        np=fixture.root/'namespace.json';np.write_text(json.dumps(namespace))
        fixture.report['source_plan_sha256']=hashlib.sha256(np.read_bytes()).hexdigest();fixture.write_package()
        fixture.apply()
        parent_folder,parent=fixture.apply.__globals__['installer'].operation(fixture.client)
        archives={p.name:p.read_bytes() for p in (fixture.client/'Data/data').glob('data.[0-9][0-9][0-9]')}
        metadata=repair.install.container.metadata(fixture.client/'Data/data')
        info=(fixture.client/'.build.info').read_bytes()
        entries=[dict(path=r['path'],file_data_ids=r['target_file_data_ids'],root_profiles={
                      str(fid):[dict(locale=0xffffffff,raw_flags=[0x10000000,0,0],ckey=r['ckey'])]
                      for fid in r['target_file_data_ids']}) for r in fixture.rows if r['payload']]
        audit=dict(format='wowforever-legion-root-type-audit-v1',build_info_sha256=hashlib.sha256(info).hexdigest(),
                   private_resources=entries,native_world_roles={},reference_errors=[])
        ap=fixture.root/'audit.json';ap.write_text(json.dumps(audit))
        result=repair.apply(fixture.client,fixture.report_path,np,ap,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None)
        self.assertEqual(result['private_ids'],2)
        folder,journal=repair.install.operation(fixture.client)
        self.assertIn(parent_folder.name,journal['resource_ancestors'])
        for name,body in archives.items():self.assertEqual((fixture.client/'Data/data'/name).read_bytes(),body)
        rows=repair.install.verify(fixture.client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None)
        # New content reports the new flags. The same-CKey alias can report
        # its original node's flags, which is why ROOT is also checked by ID.
        fresh=fixture.rows[-1]['target_file_data_ids'][0]
        self.assertEqual(rows[fresh]['content_flags'],'12080000')
        self.assertEqual(rows[fresh]['locale_flags'],'173f6')
        with self.assertRaisesRegex(ValueError,'unrepaired'):
            repair.apply(fixture.client,fixture.report_path,np,ap,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None)
        repair.rollback(fixture.client)
        self.assertEqual(repair.install.operation(fixture.client)[0],parent_folder)
        self.assertEqual((fixture.client/'.build.info').read_bytes(),info)
        self.assertEqual(repair.install.container.metadata(fixture.client/'Data/data'),metadata)
        with patch.object(repair.install,'verify',side_effect=ValueError('owned native verification failure')):
            with self.assertRaisesRegex(ValueError,'owned native verification failure'):
                repair.apply(fixture.client,fixture.report_path,np,ap,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None)
        self.assertEqual(repair.install.operation(fixture.client)[0],parent_folder)
        self.assertEqual((fixture.client/'.build.info').read_bytes(),info)
        self.assertEqual(repair.install.container.metadata(fixture.client/'Data/data'),metadata)
        fixture_module=fixture.apply.__globals__['installer']
        fixture_module.rollback(fixture.client)
        self.assertEqual(fixture.fixture.snapshot(fixture.fixture.source),fixture.fixture.before_source)
