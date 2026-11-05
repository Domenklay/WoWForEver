import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('copy_addons',ROOT/'scripts/copy-client-addons.py')
copy=importlib.util.module_from_spec(spec);spec.loader.exec_module(copy)

class AddonCopyTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.source=self.client('main');self.target=self.client('test')
        self.addon(self.source,'ForeverSubclass','new code')
        self.addon(self.target,'ForeverSubclass','old code')
        self.addon(self.target,'OldTestAddon','old test')
        self.backup=self.root/'backups/first'

    def client(self,name):
        p=self.root/name;p.mkdir();(p/'WowB.exe').write_text('owned exe')
        (p/'WTF').mkdir();(p/'WTF/Config.wtf').write_text('owned settings')
        return p

    def addon(self,client,name,text):
        p=client/'Interface/AddOns'/name;p.mkdir(parents=True)
        (p/(name+'.toc')).write_text('## Version: owned-test')
        (p/'code.lua').write_text(text)
        return p

    def snapshot(self,root):return {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_copy_is_independent_and_restore_preserves_original_and_settings(self):
        original=self.snapshot(self.source);before=self.snapshot(self.target)
        copy.copy_addons(self.source,self.target,self.backup)
        main=self.source/'Interface/AddOns/ForeverSubclass/code.lua';test=self.target/'Interface/AddOns/ForeverSubclass/code.lua'
        self.assertEqual(test.read_text(),'new code')
        self.assertFalse((self.target/'Interface/AddOns/OldTestAddon').exists())
        test.write_text('test-only edit')
        self.assertEqual(main.read_text(),'new code')
        copy.restore(self.backup)
        self.assertEqual(self.snapshot(self.source),original)
        self.assertEqual(self.snapshot(self.target),before)
        self.assertEqual((self.backup/'after-before-restore/ForeverSubclass/code.lua').read_text(),'test-only edit')
        with self.assertRaises(FileExistsError):copy.restore(self.backup)

    def test_failed_install_switch_restores_previous_target(self):
        before=self.snapshot(self.target)
        real=copy.os.replace
        def fail(src,dst):
            if Path(src).name=='next':raise OSError('injected rename failure')
            return real(src,dst)
        with patch.object(copy.os,'replace',side_effect=fail):
            with self.assertRaises(OSError):copy.copy_addons(self.source,self.target,self.backup)
        self.assertEqual(self.snapshot(self.target),before)
        self.assertTrue((self.backup/'before/ForeverSubclass/code.lua').is_file())

    def test_refuses_same_client_links_and_backup_inside_client(self):
        with self.assertRaises(ValueError):copy.copy_addons(self.source,self.source,self.backup)
        with self.assertRaises(ValueError):copy.copy_addons(self.source,self.target,self.target/'backup')
        link=self.source/'Interface/AddOns/alias';link.symlink_to(self.source/'WTF',target_is_directory=True)
        with self.assertRaises(ValueError):copy.copy_addons(self.source,self.target,self.backup)

    def test_restore_refuses_tampered_backup(self):
        copy.copy_addons(self.source,self.target,self.backup)
        installed=self.snapshot(self.target)
        (self.backup/'before/ForeverSubclass/code.lua').write_text('tampered')
        with self.assertRaises(ValueError):copy.restore(self.backup)
        self.assertEqual(self.snapshot(self.target),installed)
