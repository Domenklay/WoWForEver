import hashlib
import importlib.util
import json
import os
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
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


canary=load('canary','casc-copy-canary.py')
copier=load('copier','prepare-legion-client.py')
lab=canary.lab


def snapshot(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and
            p.relative_to(root).parts[0]!='casc-canary-operations'}


@unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
class CopyCanaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.copy=self.root/'copy'
        # Model the real profile: thirty tags with all unused trailing bits set.
        # Eleven entries reproduce the real profile's five padding bits and
        # give the pinned reader >=4 bytes for the final tag type+bitmap.
        raw=b'DL\1\x10\0'+struct.pack('>IH',11,30)
        base=lab.asset(lab.BASE_TEXT)
        for i in range(11):
            key=base['ekey'] if i==0 else hashlib.md5(f'unrelated {i}'.encode()).digest()
            size=len(base['encoded']) if i==0 else 100
            raw+=key+size.to_bytes(5,'big')+b'\0'
        for i in range(30):raw+=f'tag-{i}'.encode()+b'\0'+i.to_bytes(2,'big')+b'\xff\xff'
        original_asset=lab.asset
        def tagged_asset(body):return original_asset(raw if body==b'DL\1\x10\0'+bytes(11) else body)
        def mixed_root(records):
            obj=records[lab.BASE_ID];key=obj['ckey']
            return (b'TSFM'+struct.pack('<5I',24,2,2,1,0)+
                    struct.pack('<4IBI',1,2,0,0,0,lab.BASE_ID)+key+struct.pack('<Q',12345)+
                    struct.pack('<4IBI',1,256,0x10000000,0,0,lab.BASE_ID)+key)
        with patch.object(lab,'asset',side_effect=tagged_asset),patch.object(lab,'make_root',side_effect=mixed_root):
            marker=lab.write_store(self.source)
        (self.source/'_classic_beta_').mkdir()
        (self.source/'_classic_beta_/WowB.exe').write_bytes(b'own executable fixture; not a game client')
        self.key=marker['build_key'];copier.prepare(self.source,self.copy,self.key)
        self.controls={lab.BASE_ID:dict(bytes=len(lab.BASE_TEXT),sha256=hashlib.sha256(lab.BASE_TEXT).hexdigest())}
        self.checker=os.environ['CASC_SANDBOX_CHECKER'];self.source_before=snapshot(self.source)

    def run_apply(self):
        return canary.apply(self.copy,self.checker,self.controls,self.key,progress=lambda text:None)

    def test_native_addition_keeps_existing_bytes_and_rollback_restores_copy(self):
        before=snapshot(self.copy)
        result=self.run_apply()
        self.assertFalse(result['dalaran_installed'])
        self.assertEqual({p['locale'] for p in result['root_profiles'][str(lab.BASE_ID)]},{2,256})
        self.assertEqual(int(result['native_before'][0]['tag_mask'],16),(1<<30)-1)
        self.assertEqual(result['native_after'][0]['tag_mask'],result['native_before'][0]['tag_mask'])
        self.assertEqual(result['native_after'][-1]['file_id'],str(canary.CANARY_ID))
        self.assertEqual(result['native_after'][-1]['sha256'],hashlib.sha256(canary.CANARY_TEXT).hexdigest())
        after=snapshot(self.copy)
        for name,value in before.items():
            if name!='.build.info':self.assertEqual(after[name],value)
        self.assertEqual(snapshot(self.source),self.source_before)
        with self.assertRaisesRegex(ValueError,'rollback first'):self.run_apply()
        canary.rollback(self.copy)
        self.assertEqual(snapshot(self.copy),before)
        self.assertEqual(snapshot(self.source),self.source_before)

    def test_failed_post_switch_check_automatically_restores_all_client_files(self):
        before=snapshot(self.copy);native=canary.native_check;calls=[]
        def fail_after(checker,path,expected):
            calls.append(1)
            if len(calls)==2:raise ValueError('simulated native storage failure')
            return native(checker,path,expected)
        with patch.object(canary,'native_check',side_effect=fail_after):
            with self.assertRaisesRegex(ValueError,'simulated native'):
                self.run_apply()
        self.assertEqual(snapshot(self.copy),before)
        self.assertEqual(json.loads(canary.operation_file(self.copy).read_text())['phase'],'rolled_back')
        native(self.checker,self.copy,self.controls)

    def test_missing_marker_baseline_mismatch_and_failed_precheck_never_change_data(self):
        before=snapshot(self.copy)
        with self.assertRaises(FileNotFoundError):
            canary.apply(self.source,self.checker,self.controls,self.key,progress=lambda text:None)
        with patch.object(canary,'native_check',side_effect=ValueError('precheck failed')):
            with self.assertRaisesRegex(ValueError,'precheck failed'):self.run_apply()
        self.assertEqual(snapshot(self.copy),before)
        self.assertFalse((self.copy/'casc-canary-operations').exists())
        info=self.copy/'.build.info';info.write_bytes(info.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'baseline'):self.run_apply()
        self.assertEqual(snapshot(self.source),self.source_before)

    def test_interrupted_operation_can_be_rolled_back_from_its_journal(self):
        before=snapshot(self.copy);native=canary.native_check;calls=[]
        def interrupt_after(checker,path,expected):
            calls.append(1)
            if len(calls)==2:raise ValueError('interrupted after switch')
            return native(checker,path,expected)
        # Model abrupt termination by preventing in-process cleanup; the next
        # invocation must be able to recover using only the saved journal.
        with patch.object(canary,'native_check',side_effect=interrupt_after),patch.object(canary,'rollback_files'):
            with self.assertRaisesRegex(ValueError,'interrupted'):self.run_apply()
        self.assertNotEqual(snapshot(self.copy)['.build.info'],before['.build.info'])
        canary.rollback(self.copy)
        self.assertEqual(snapshot(self.copy),before)
