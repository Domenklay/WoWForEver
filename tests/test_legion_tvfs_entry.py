"""Native nested TVFS routing and a journaled canary on owned CASC data."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('tvfs_canary',ROOT/'scripts/repair-legion-tvfs-entry.py')
canary=importlib.util.module_from_spec(spec);spec.loader.exec_module(canary)
lib=canary.storelib


def fixture_directory(old_id=123086,new_id=15728640):
    obj=canary.install.canary.lab.asset(b'owned texture placeholder, no game assets')
    est,spans=canary.add_span(b'',obj)
    name=f'{old_id:08X}'+obj['ckey'].hex().upper()
    body=lib.encode_tvfs({name:spans,'unrelated':spans},est)
    child=canary.install.canary.lab.asset(body)
    root_est,child_spans=canary.add_span(b'',child)
    root_est,private_spans=canary.add_span(root_est,obj)
    root=canary.install.canary.lab.asset(lib.encode_tvfs({
        '.root':private_spans,'000173F600000000':child_spans,
        f'000173F612080000:{new_id:08X}'+obj['ckey'].hex().upper():private_spans},root_est))
    objects={root['ekey']:root['content'],child['ekey']:child['content']}
    store=SimpleNamespace(values={'vfs-root':root['ckey'].hex()+' '+root['ekey'].hex(),
        'vfs-1':root['ckey'].hex()+' '+root['ekey'].hex(),
        'vfs-2':child['ckey'].hex()+' '+child['ekey'].hex()},read=lambda ek,ck:objects[ek])
    return store,obj,child,root


class TvfsEntryTests(unittest.TestCase):
    def test_patched_cft_is_preserved_opaque_when_mirroring_a_native_path(self):
        store,obj,child,root=fixture_directory()
        opaque=bytearray(child['content']);cft_offset=struct.unpack_from('>I',opaque,28)[0]
        # The parser must not interpret or drop unknown patch metadata.
        opaque[cft_offset+34]=2
        with self.assertRaisesRegex(ValueError,'Patched CFT'):lib.tvfs.parse_tvfs(opaque)
        before=lib.tvfs.parse_tvfs(opaque,raw_paths=True)
        candidate,rows=canary.mirror_child(opaque)
        after=lib.tvfs.parse_tvfs(candidate,raw_paths=True)
        self.assertEqual(candidate[:12],opaque[:12])
        self.assertEqual(candidate[20:len(opaque)],opaque[20:])
        for table in ('vfs','cft','est'):self.assertEqual(after['tables'][table],before['tables'][table])
        for name,value in before['leaves'].items():self.assertEqual(after['leaves'][name],value)
        self.assertEqual(after['leaves'][rows[0]['added']],before['leaves'][rows[0]['original']])

    def test_layout_repack_preserves_opaque_tables_and_native_physical_order(self):
        store,obj,child,root=fixture_directory()
        opaque=bytearray(child['content']);cft_offset=struct.unpack_from('>I',opaque,28)[0]
        opaque[cft_offset+34]=2
        mirrored,rows=canary.mirror_child(opaque)
        before=lib.tvfs.parse_tvfs(mirrored,raw_paths=True)
        candidate=lib.tvfs.repack_tvfs_like(mirrored,opaque)
        after=lib.tvfs.parse_tvfs(candidate,raw_paths=True)
        self.assertEqual(before['tables'],after['tables']);self.assertEqual(before['leaves'],after['leaves'])
        fields=(12,20,28,38)
        native_order=sorted(fields,key=lambda i:struct.unpack_from('>I',opaque,i)[0])
        actual_order=sorted(fields,key=lambda i:struct.unpack_from('>I',candidate,i)[0])
        self.assertEqual(actual_order,native_order)
        self.assertEqual(struct.unpack_from('>I',candidate,12)[0],46)
        self.assertLess(len(candidate),len(mirrored))
        self.assertEqual(lib.tvfs.repack_tvfs_like(candidate,opaque),candidate)
        with self.assertRaisesRegex(ValueError,'trailing unknown'):
            lib.tvfs.repack_tvfs_like(mirrored,bytes(opaque)+b'extra')

    def test_mirrors_native_spans_inside_child_and_removes_only_flat_canary(self):
        store,obj,child,root=fixture_directory();plan=canary.plan(store,lambda _:None)
        new_root=lib.tvfs.parse_tvfs(plan['candidate'])['leaves']
        old_root=lib.tvfs.parse_tvfs(root['content'])['leaves']
        self.assertEqual(new_root['.root'],old_root['.root']);self.assertEqual(len(plan['removed']),1)
        self.assertFalse(any('00F00000' in key for key in new_root))
        new_child=lib.tvfs.parse_tvfs(plan['children'][0]['content'])['leaves']
        old_child=lib.tvfs.parse_tvfs(child['content'])['leaves']
        for key,value in old_child.items():self.assertEqual(new_child[key],value)
        original=f'{123086:08X}'+obj['ckey'].hex().upper()
        added=f'{15728640:08X}'+obj['ckey'].hex().upper()
        self.assertNotIn(added,old_child);self.assertEqual(new_child[added],old_child[original])
        self.assertEqual(plan['replacements']['000173F600000000']['source_config_key'],'vfs-2')

    def test_rejects_unregistered_or_missing_native_directory_before_writes(self):
        store,_,_,_=fixture_directory();del store.values['vfs-2']
        with self.assertRaisesRegex(ValueError,'not consistently listed'):canary.plan(store,lambda _:None)
        store,_,_,_=fixture_directory()
        with self.assertRaisesRegex(ValueError,'No native RU TVFS'):canary.plan(store,lambda _:None,old_id=42)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native checker required')
    def test_native_append_readback_and_exact_canary_rollback(self):
        from test_legion_resource_install import ResourceBatchTests
        f=ResourceBatchTests();f.setUp();self.addCleanup(f.doCleanups);f.apply()
        install=canary.install;client=f.client
        folder,parent=install.operation(client)
        old_id=install.canary.lab.BASE_ID;new_id=f.rows[1]['target_file_data_ids'][0]
        store=lib.Store(client,synthetic_only=False)
        root=install.canary.lab.asset(install.load('audit-legion-root-types.py').read_content(
            store,install.load('audit-legion-root-types.py').Encoding(canary.configured(store,'encoding')),
            store.values['root'].split()[0]))
        parsed=lib.tvfs.parse_tvfs(canary.configured(store,'vfs-root'));leaves=copy.deepcopy(parsed['leaves'])
        fake=next(name for name in leaves if name.startswith('FFFFFFFF10000000:'+f'{new_id:08X}'))
        child=install.canary.lab.asset(lib.encode_tvfs({f'{old_id:08X}'+f.rows[1]['ckey'].upper():leaves[fake]},parsed['tables']['est']))
        est,leaves['000173F600000000']=canary.add_span(parsed['tables']['est'],child)
        vfs=install.canary.lab.asset(lib.encode_tvfs(leaves,est))
        encoding=install.canary.lab.asset(install.canary.extend_encoding(canary.configured(store,'encoding'),[child,vfs],allow_variants=True))
        store.values['vfs-2']=child['ckey'].hex()+' '+child['ekey'].hex()
        store.values['vfs-2-size']=f'{len(child["content"])} {len(child["encoded"])}'
        store.config+='\nvfs-2 = '+store.values['vfs-2']+'\nvfs-2-size = '+store.values['vfs-2-size']+'\n'
        prepared=dict(root=root,vfs=vfs,encoded=encoding,download=install.canary.lab.asset(canary.configured(store,'download')))
        config=install.canary.resource_configuration(store,prepared)
        meta=install.container.metadata(client/'Data/data');prologues={}
        for p in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
            with p.open('rb') as source:prologues[int(p.name[5:])]=source.read(480)
        files,shared=install.plan_segment(meta,prologues,[child,vfs,encoding])
        for name,data in files.items():(client/'Data/data'/name).write_bytes(data)
        (client/'Data/data/shmem').write_bytes(shared)
        path=client/config['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(config['body'])
        (client/'.build.info').write_bytes(config['build_info'])
        parent.update(root_types_repaired=True,after_info_sha256=install.canary.sha(config['build_info']))
        install.canary.checkpoint(folder/'operation.json',parent)
        before=install.container.metadata(client/'Data/data');info=(client/'.build.info').read_bytes()
        archives={p.name:p.read_bytes() for p in (client/'Data/data').glob('data.[0-9][0-9][0-9]')}
        result=canary.apply(client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None,old_id=old_id,new_id=new_id)
        self.assertEqual(result['new_id'],new_id)
        current=lib.Store(client,synthetic_only=False)
        self.assertEqual(current.values['vfs-2'],store.values['vfs-2'])
        self.assertIn('vfs-3',current.values)
        new_root=lib.tvfs.parse_tvfs(canary.configured(current,'vfs-root'))['leaves']
        new_child=lib.tvfs.parse_tvfs(canary.configured(current,'vfs-3'))['leaves']
        self.assertNotIn(fake,new_root)
        self.assertEqual(new_child[f'{new_id:08X}'+f.rows[1]['ckey'].upper()],new_child[f'{old_id:08X}'+f.rows[1]['ckey'].upper()])
        for name,data in archives.items():self.assertEqual((client/'Data/data'/name).read_bytes(),data)
        entry_folder,entry_journal=install.operation(client)
        entry_metadata=install.container.metadata(client/'Data/data');entry_info=(client/'.build.info').read_bytes()
        with patch.object(install,'verify',side_effect=ValueError('layout readback failure')):
            with self.assertRaisesRegex(ValueError,'layout readback failure'):
                canary.apply(client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None,old_id=old_id,new_id=new_id,layout_only=True)
        self.assertEqual(install.operation(client)[0],entry_folder)
        self.assertEqual((client/'.build.info').read_bytes(),entry_info)
        self.assertEqual(install.container.metadata(client/'Data/data'),entry_metadata)
        layout_result=canary.apply(client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None,old_id=old_id,new_id=new_id,layout_only=True)
        self.assertTrue(layout_result['tvfs_layout_only'])
        layout_store=lib.Store(client,synthetic_only=False)
        layout_child=lib.tvfs.parse_tvfs(canary.configured(layout_store,'vfs-4'),raw_paths=True)
        self.assertEqual(layout_child['leaves'],lib.tvfs.parse_tvfs(canary.configured(current,'vfs-3'),raw_paths=True)['leaves'])
        with self.assertRaisesRegex(ValueError,'already active; nothing changed'):
            canary.apply(client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None,old_id=old_id,new_id=new_id,layout_only=True)
        canary.rollback(client)
        self.assertEqual(install.operation(client)[0],entry_folder)
        self.assertEqual((client/'.build.info').read_bytes(),entry_info)
        self.assertEqual(install.container.metadata(client/'Data/data'),entry_metadata)
        canary.rollback(client)
        self.assertEqual(install.operation(client)[0],folder)
        self.assertEqual((client/'.build.info').read_bytes(),info)
        self.assertEqual(install.container.metadata(client/'Data/data'),before)
        with patch.object(install,'verify',side_effect=ValueError('owned readback failure')):
            with self.assertRaisesRegex(ValueError,'owned readback failure'):
                canary.apply(client,os.environ['CASC_SANDBOX_CHECKER'],progress=lambda _:None,old_id=old_id,new_id=new_id)
        self.assertEqual(install.operation(client)[0],folder)
        self.assertEqual((client/'.build.info').read_bytes(),info)
        self.assertEqual(install.container.metadata(client/'Data/data'),before)
