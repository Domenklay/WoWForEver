import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_legion',Path(__file__).parents[1]/'scripts/prepare-legion-client.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
KEY = 'ab'*16


class LegionClientCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'drive';self.root.mkdir()
        (self.root/'Data/data').mkdir(parents=True)
        (self.root/'Data/data/data.000').write_bytes(b'original CASC bytes')
        (self.root/'_classic_beta_').mkdir()
        (self.root/'_classic_beta_/WowB.exe').write_bytes(b'original executable')
        (self.root/'.build.info').write_text('Product!STRING:0|Active!DEC:1|Build Key!HEX:16\n'
                                            'wow_classic_beta|1|'+KEY+'\n')
        (self.root/'unrelated.txt').write_text('do not copy the entire drive')
        self.output = self.root/'WoWForEver-work/experiments/client-v1'

    def test_verified_independent_copy_excludes_work_folder_and_unrelated_drive_files(self):
        result = helper.prepare(self.root,self.output,KEY)
        self.assertEqual(result['files'],3)
        self.assertFalse(result['game_data_patch_installed'])
        self.assertFalse((self.output/'unrelated.txt').exists())
        self.assertFalse((self.output/'WoWForEver-work').exists())
        source = self.root/'Data/data/data.000';copied = self.output/'Data/data/data.000'
        self.assertEqual(source.read_bytes(),copied.read_bytes())
        self.assertNotEqual(source.stat().st_ino,copied.stat().st_ino)
        copied.write_bytes(b'test patch changes only the copy')
        self.assertEqual(source.read_bytes(),b'original CASC bytes')
        saved = json.loads((self.output/'legion-client-copy.json').read_text())
        self.assertEqual(saved['build_key'],KEY)

    def test_existing_output_and_copy_into_source_data_refused(self):
        self.output.mkdir(parents=True);(self.output/'keep').write_bytes(b'keep')
        with self.assertRaises(FileExistsError):helper.prepare(self.root,self.output,KEY)
        self.assertEqual((self.output/'keep').read_bytes(),b'keep')
        with self.assertRaisesRegex(ValueError,'selected client tree'):
            helper.prepare(self.root,self.root/'Data/recursive-copy',KEY)
        self.assertFalse((self.root/'Data/.recursive-copy.copy.lock').exists())

    def test_build_change_insufficient_space_and_symlinks_fail_before_copy(self):
        with self.assertRaisesRegex(ValueError,'Build changed'):
            helper.prepare(self.root,self.output,'cd'*16)
        with patch.object(helper.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError,'free space'):
                helper.prepare(self.root,self.output,KEY)
        (self.root/'Data/linked-folder').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlinked'):
            helper.prepare(self.root,self.output,KEY)
        self.assertFalse(self.output.exists())

    def test_source_change_during_copy_leaves_no_completed_destination(self):
        original_chmod = helper.os.chmod
        def mutate(path, mode, **kwargs):
            original_chmod(path,mode,**kwargs)
            if str(path).endswith('Data/data/data.000'):
                (self.root/'Data/data/data.000').write_bytes(b'changed by running launcher')
        with patch.object(helper.os,'chmod',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'Source changed'):
                helper.prepare(self.root,self.output,KEY)
        self.assertFalse(self.output.exists())
        partial = self.output.with_name(self.output.name+'.partial')
        self.assertTrue((partial/'state.json').exists())
        helper.prepare(self.root,self.output,KEY)
        self.assertEqual((self.output/'Data/data/data.000').read_bytes(),b'changed by running launcher')

    def test_cache_and_temporary_client_files_excluded_but_data_is_strict(self):
        cache = self.root/'_classic_beta_/cAcHe/ADB/ruRU';cache.mkdir(parents=True)
        (cache/'CollectableSourceEncounterSparse32288.tmp').write_bytes(b'disappearing cache')
        (self.root/'_classic_beta_/log.tmp').write_bytes(b'ignored')
        (self.root/'Data/data/important.tmp').write_bytes(b'not a game cache')
        original_chmod = helper.os.chmod
        def remove_cache_during_copy(path,mode,**kwargs):
            original_chmod(path,mode,**kwargs)
            if str(path).endswith('Data/data/data.000'):
                (cache/'CollectableSourceEncounterSparse32288.tmp').unlink(missing_ok=True)
        with patch.object(helper.os,'chmod',side_effect=remove_cache_during_copy):
            result = helper.prepare(self.root,self.output,KEY)
        self.assertEqual(result['files'],4)
        self.assertFalse((self.output/'_classic_beta_/cAcHe').exists())
        self.assertFalse((self.output/'_classic_beta_/log.tmp').exists())
        self.assertEqual((self.output/'Data/data/important.tmp').read_bytes(),b'not a game cache')

    def interrupt_at_executable(self):
        original_open = Path.open
        def interrupted(path,*args,**kwargs):
            if path==self.root/'_classic_beta_/WowB.exe':
                raise FileNotFoundError('simulated interruption after Data copy')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',autospec=True,side_effect=interrupted):
            with self.assertRaises(FileNotFoundError):
                helper.prepare(self.root,self.output,KEY)
        return self.output.with_name(self.output.name+'.partial')

    def test_resume_verifies_saved_data_without_reading_source_or_requiring_full_free_space(self):
        partial = self.interrupt_at_executable()
        self.assertTrue((partial/'client/Data/data/data.000').exists())
        original_open = Path.open
        def track(path,*args,**kwargs):
            self.assertNotEqual(path,self.root/'Data/data/data.000','Data must be reused, not recopied')
            return original_open(path,*args,**kwargs)
        free = 256*1024*1024+(self.root/'_classic_beta_/WowB.exe').stat().st_size
        with patch.object(Path,'open',autospec=True,side_effect=track), \
                patch.object(helper.shutil,'disk_usage',return_value=SimpleNamespace(free=free)):
            helper.prepare(self.root,self.output,KEY)
        self.assertTrue(self.output.exists())
        self.assertFalse(partial.exists())

    def test_corrupted_saved_file_is_recopied(self):
        partial = self.interrupt_at_executable()
        (partial/'client/Data/data/data.000').write_bytes(b'damaged saved copy')
        report = helper.prepare(self.root,self.output,KEY)
        self.assertEqual((self.output/'Data/data/data.000').read_bytes(),b'original CASC bytes')
        self.assertEqual(report['files'],3)

    def test_foreign_partial_directory_is_not_adopted(self):
        partial = self.output.with_name(self.output.name+'.partial');partial.mkdir(parents=True)
        (partial/'state.json').write_text('{"format":"other"}')
        (partial/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'different source'):
            helper.prepare(self.root,self.output,KEY)
        self.assertEqual((partial/'keep').read_bytes(),b'keep')
