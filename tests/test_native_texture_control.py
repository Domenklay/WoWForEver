"""Existing-ID control: exact metadata changes, owned storage and rollback.

The transaction test uses a Python storage reader in place of CascLib. It does
not establish acceptance by WowB.exe or native CascLib; no game files are used.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
from casc_native_texture_control import binding_pairs, redirect_root, redirect_child
from casc_texture_variants import profiles
from casc_manifest_update import Encoding, root_groups

spec = importlib.util.spec_from_file_location('native_texture_entry', SCRIPTS/'repair-legion-tvfs-entry.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

TARGET, DONOR = 123086, 123087


def group(fid, flag, key, locale=0x173f6, name=None):
    return (struct.pack('<4IBI', 1, locale, flag, 0x12000000 if name is None else 0x02000000, 4, fid)
            + key + (struct.pack('<Q', name) if name is not None else b''))


def root_fixture():
    return (b'TSFM'+struct.pack('<5I',24,2,5,1,0)+group(TARGET,1,b'b'*16)
            +group(DONOR,0,b'c'*16)+group(TARGET,0,b'a'*16)+group(DONOR,1,b'd'*16)
            +group(888,0,b'e'*16,name=123))


class NativeTextureMetadataTests(unittest.TestCase):
    def test_only_target_ckeys_change_in_mixed_root_groups(self):
        raw=root_fixture();result,pairs=redirect_root(raw,TARGET,DONOR)
        allowed=set()
        for g in root_groups(raw):
            if struct.unpack_from('<I',raw,g['ids_offset'])[0]==TARGET:
                allowed.update(range(g['ckeys_offset'],g['ckeys_offset']+16))
        self.assertEqual(len(result),len(raw))
        self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(raw,result)) if i not in allowed))
        before=profiles(raw,{TARGET,DONOR,888});after=profiles(result,{TARGET,DONOR,888})
        self.assertEqual(after[DONOR],before[DONOR]);self.assertEqual(after[888],before[888])
        self.assertEqual({r['ckey'] for r in after[TARGET]},{r['ckey'] for r in before[DONOR]})
        self.assertEqual(len(pairs),2)

    def test_incompatible_profiles_duplicate_profiles_and_identical_content_stop(self):
        with self.assertRaisesRegex(ValueError,'profiles do not match'):
            binding_pairs(root_fixture(),TARGET,999)
        raw=root_fixture();duplicate=bytearray(raw[:24]);struct.pack_into('<I',duplicate,12,6)
        raw=bytes(duplicate)+raw[24:]+group(TARGET,0,b'f'*16)
        with self.assertRaisesRegex(ValueError,'Duplicate'):binding_pairs(raw,TARGET,DONOR)
        with self.assertRaisesRegex(ValueError,'share content'):
            binding_pairs(root_fixture().replace(b'c'*16,b'a'*16),TARGET,DONOR)
        with self.assertRaisesRegex(ValueError,'different existing'):
            binding_pairs(root_fixture(),TARGET,0xf00000)

    def test_child_reuses_donor_row_and_preserves_opaque_records_and_old_paths(self):
        tvfs=entry.storelib.tvfs;est=b'';leaves={}
        for fid,key,body in [(TARGET,'61'*16,b'owned first'),(DONOR,'63'*16,b'owned second')]:
            est,leaves[f'{fid:08X}'+key.upper()]=entry.add_span(est,entry.install.canary.lab.asset(body))
        raw=bytearray(entry.storelib.encode_tvfs(leaves,est))
        cft_offset=struct.unpack_from('>I',raw,28)[0];raw[cft_offset+34]=2
        raw=bytes(raw);pairs=binding_pairs(root_fixture(),TARGET,DONOR)
        changed,rows=redirect_child(tvfs,raw,TARGET,DONOR,pairs)
        before=tvfs.parse_tvfs(raw,raw_paths=True);after=tvfs.parse_tvfs(changed,raw_paths=True)
        for table in ('vfs','cft','est'):self.assertEqual(after['tables'][table],before['tables'][table])
        for name,value in before['leaves'].items():self.assertEqual(after['leaves'][name],value)
        self.assertEqual(after['leaves'][rows[0]['added']],before['leaves'][rows[0]['donor']])
        with self.assertRaisesRegex(ValueError,'already exists'):redirect_child(tvfs,changed,TARGET,DONOR,pairs)
        with self.assertRaisesRegex(ValueError,'Donor is absent'):
            redirect_child(tvfs,entry.storelib.encode_tvfs({f'{TARGET:08X}'+('61'*16).upper():next(iter(leaves.values()))},est),TARGET,DONOR,pairs)


class NativeTextureTransactionTests(unittest.TestCase):
    def setUp(self):
        from test_native_container_canary import NativeContainerTests
        import casc_native_container as native
        self.native=native;lab=native.lab;write_store=lab.write_store;make_root=lab.make_root
        def typed_root(records):
            data=bytearray(make_root(records))
            # All owned records live in a single hashless group.
            struct.pack_into('<III',data,28,0x173f6,0,0x12000000);data[40]=4
            return bytes(data)
        self.fixture=NativeContainerTests()
        with patch.object(lab,'BASE_ID',TARGET),patch.object(lab,'NEW_ID',DONOR),\
             patch.object(lab,'BASE_TEXT',b'BLP2 owned texture A'),patch.object(lab,'NEW_TEXT',b'BLP2 owned texture B'),\
             patch.object(lab,'make_root',typed_root),\
             patch.object(lab,'write_store',side_effect=lambda path:write_store(path,added=True)):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.copy;install=entry.install
        self.scanner=patch.object(install,'scan',side_effect=self.scan);self.scanner.start();self.addCleanup(self.scanner.stop)
        store=entry.storelib.Store(self.client,synthetic_only=False)
        root=self.root_bytes(store);found=profiles(root,{TARGET,DONOR})
        est=b'';leaves={}
        for fid,rows in found.items():
            key=rows[0]['ckey'];body=install.load('audit-legion-root-types.py').read_content(store,Encoding(entry.configured(store,'encoding')),key)
            est,leaves[f'{fid:08X}'+key.upper()]=entry.add_span(est,install.canary.lab.asset(body))
        child=install.canary.lab.asset(entry.storelib.encode_tvfs(leaves,est))
        store.values['vfs-2']=child['ckey'].hex()+' '+child['ekey'].hex()
        store.values['vfs-2-size']=f'{len(child["content"])} {len(child["encoded"])}'
        store.config+='\nvfs-2 = '+store.values['vfs-2']+'\nvfs-2-size = '+store.values['vfs-2-size']+'\n'
        def nested(data):
            parsed=entry.storelib.tvfs.parse_tvfs(data);leaves=copy.deepcopy(parsed['leaves'])
            est,leaves['000173F600000000']=entry.add_span(parsed['tables']['est'],child)
            return entry.storelib.encode_tvfs(leaves,est)
        before=self.scan(None,self.client,[TARGET,DONOR],None,None)
        prepared,_=install.manifests(store,{}, {},before,{TARGET:before[TARGET]},lambda _:None,
            root_transform=lambda data:data,vfs_transform=nested,extra_assets=[child])
        config=install.canary.resource_configuration(store,prepared)
        meta=install.container.metadata(self.client/'Data/data');prologues={}
        for p in (self.client/'Data/data').glob('data.[0-9][0-9][0-9]'):
            with p.open('rb') as stream:prologues[int(p.name[5:])]=stream.read(480)
        files,shared=install.plan_segment(meta,prologues,prepared['additions'])
        for name,data in files.items():(self.client/'Data/data'/name).write_bytes(data)
        (self.client/'Data/data/shmem').write_bytes(shared)
        path=self.client/config['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(config['body'])
        (self.client/'.build.info').write_bytes(config['build_info'])
        self.token='a'*32;folder=self.client/install.OPS/self.token;folder.mkdir(parents=True)
        parent=dict(format=install.FORMAT,copy=str(self.client),phase='verified',root_types_repaired=True,
            tvfs_entry_canary=True,tvfs_canary_original_id=TARGET,tvfs_canary_new_id=DONOR,
            locale='ruRU',after_info_sha256=install.canary.sha(config['build_info']),
            expected_after={str(fid):dict(bytes=int(r['bytes']),sha256=r['sha256'],ckey=r['ckey'],tag_mask='0') for fid,r in before.items()})
        install.canary.checkpoint(folder/'operation.json',parent)
        install.canary.checkpoint(self.client/install.OPS/'active.json',dict(operation=self.token))

    def root_bytes(self,store):
        audit=entry.install.load('audit-legion-root-types.py')
        return audit.read_content(store,Encoding(entry.configured(store,'encoding')),store.values['root'].split()[0])

    def scan(self,checker,client,ids,locale,progress):
        store=entry.storelib.Store(client,synthetic_only=False);root=self.root_bytes(store)
        found=profiles(root,set(ids));encoding=Encoding(entry.configured(store,'encoding'))
        audit=entry.install.load('audit-legion-root-types.py');rows={}
        for fid in ids:
            key=found[fid][0]['ckey'];body=audit.read_content(store,encoding,key)
            rows[fid]=dict(file_id=str(fid),status='READ_OK',bytes=str(len(body)),sha256=hashlib.sha256(body).hexdigest(),ckey=key,tag_mask='0',error='0')
        return rows

    def snapshot(self):
        return {p.relative_to(self.client).as_posix():p.read_bytes() for p in self.client.rglob('*')
                if p.is_file() and p.relative_to(self.client).parts[0]!=entry.install.OPS}

    def test_plan_apply_failure_restore_and_exact_rollback(self):
        before=self.snapshot()
        result=entry.apply(self.client,'python-reader',old_id=TARGET,new_id=DONOR,native_control=True,dry_run=True,progress=lambda _:None)
        self.assertFalse(result['client_modified']);self.assertEqual(result['donor_id'],DONOR)
        self.assertEqual(self.snapshot(),before)
        with patch.object(entry.install,'verify',side_effect=ValueError('forced readback failure')):
            with self.assertRaisesRegex(ValueError,'forced readback'):
                entry.apply(self.client,'python-reader',old_id=TARGET,new_id=DONOR,native_control=True,donor_id=DONOR,progress=lambda _:None)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(entry.install.operation(self.client)[0].name,self.token)
        result=entry.apply(self.client,'python-reader',old_id=TARGET,new_id=DONOR,native_control=True,donor_id=DONOR,progress=lambda _:None)
        self.assertEqual(result['new_file_data_ids'],0)
        actual=self.scan(None,self.client,[TARGET,DONOR],None,None)
        self.assertEqual(actual[TARGET]['sha256'],actual[DONOR]['sha256'])
        with self.assertRaisesRegex(ValueError,'already active'):
            entry.apply(self.client,'python-reader',old_id=TARGET,new_id=DONOR,native_control=True,progress=lambda _:None)
        entry.rollback(self.client,native_control_only=True)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaisesRegex(ValueError,'No active native texture control'):
            entry.rollback(self.client,native_control_only=True)

    def test_probe_keeps_failed_native_rows_and_reads_only_two_ids_without_writes(self):
        before=self.snapshot()
        def failed(checker,client,ids,locale,progress):
            self.assertEqual(set(ids),{TARGET,DONOR})
            rows=self.scan(checker,client,ids,locale,progress)
            rows[TARGET]=dict(file_id=str(TARGET),status='OPEN_FAILED',bytes='0',sha256='-',ckey='-',tag_mask='-',error='2')
            return rows
        with patch.object(entry.install,'scan',side_effect=failed) as scan:
            result=entry.probe_native_control(self.client,'reader',DONOR,old_id=TARGET,progress=lambda _:None)
        self.assertEqual(scan.call_count,1)
        self.assertEqual(result['native_rows'][str(TARGET)]['status'],'OPEN_FAILED')
        self.assertEqual(len(result['local_payloads']),2)
        self.assertTrue(all(p['content_md5']==p['ckey'] for p in result['local_payloads']))
        self.assertFalse(result['client_modified']);self.assertEqual(self.snapshot(),before)

    def test_rejected_control_reports_actual_native_result_and_expected_keys(self):
        before=self.snapshot()
        def missing_key(checker,client,ids,locale,progress):
            rows=self.scan(checker,client,ids,locale,progress)
            if isinstance(ids,list):rows[TARGET]['ckey']='0'*32
            return rows
        with patch.object(entry.install,'scan',side_effect=missing_key):
            with self.assertRaisesRegex(ValueError,'native_result.*READ_OK') as error:
                entry.apply(self.client,'reader',old_id=TARGET,new_id=DONOR,native_control=True,dry_run=True,progress=lambda _:None)
        self.assertIn('expected_root_ckeys',str(error.exception))
        self.assertIn('native-control-probe',str(error.exception))
        self.assertEqual(self.snapshot(),before)
