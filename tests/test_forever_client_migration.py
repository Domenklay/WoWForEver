"""New-client layouts, independent resumable copies and addon migration."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('forever_migration',SCRIPTS/'migrate-forever-client.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
KEY='ab'*16


class ForeverMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.drive=Path(self.temp.name)/'drive';self.drive.mkdir()
        self.root=self.drive/'WoW_Forever';self.root.mkdir()
        self.game=self.root/'_forever_';self.game.mkdir()
        (self.game/'WowF.exe').write_bytes(b'owned new executable fixture')
        (self.root/'Data/data').mkdir(parents=True)
        (self.root/'Data/data/data.000').write_bytes(b'owned new CASC archive')
        (self.root/'.build.info').write_text('Product!STRING:0|Active!DEC:1|Build Key!HEX:16|Version!STRING:0\n'
                                             'wow_forever|1|'+KEY+'|1.61.0.71000\n')
        (self.root/'ForeverLauncher.exe').write_bytes(b'owned launcher fixture')
        self.output=self.drive/'WoWForEver-work/experiments/Forever-client-v2'
        self.old=self.drive/'WoWForEver-work/experiments/Forever-Legion-client-v1'
        (self.old/'_classic_beta_/Interface/AddOns/ForeverAscension').mkdir(parents=True)
        (self.old/'_classic_beta_/WowB.exe').write_bytes(b'owned old executable')
        (self.old/'_classic_beta_/Interface/AddOns/ForeverAscension/ForeverAscension.toc').write_text('## Interface: 160000\n')
        (self.old/'_classic_beta_/WTF').mkdir()
        (self.old/'_classic_beta_/WTF/Config.wtf').write_text('old settings must not replace the new baseline')

    def inspect(self,source=None,**kwargs):
        return migration.inspect(source or self.game,self.output,self.old,query_launchers=False,**kwargs)

    def test_shared_parent_data_copies_only_new_product_and_is_independent(self):
        (self.root/'unrelated.txt').write_text('keep outside clone')
        (self.root/'_classic_beta_').mkdir();(self.root/'_classic_beta_/WowB.exe').write_bytes(b'other client')
        report=self.inspect()
        self.assertEqual(report['status'],'READY_TO_CLONE')
        self.assertEqual(report['layout']['parts'],['.build.info','Data','_forever_'])
        self.assertEqual(report['selected_build']['Product'],'wow_forever')
        self.assertFalse(report['preferred_launcher']['version_verified'])
        copied=migration.clone(report,lambda _:None)
        self.assertEqual(copied['format'],'wowforever-migrated-client-copy-v1')
        self.assertTrue((self.output/migration.MARKER).is_file())
        self.assertFalse((self.output/'legion-client-copy.json').exists())
        self.assertFalse((self.output/'unrelated.txt').exists())
        self.assertFalse((self.output/'_classic_beta_').exists())
        self.assertFalse((self.output/'_forever_/Interface/AddOns/ForeverAscension').exists())
        src=self.root/'Data/data/data.000';dst=self.output/'Data/data/data.000'
        self.assertNotEqual(src.stat().st_ino,dst.stat().st_ino)
        dst.write_bytes(b'changes in new test client')
        self.assertEqual(src.read_bytes(),b'owned new CASC archive')
        self.assertTrue((self.old/'_classic_beta_/WowB.exe').is_file())

    def test_installation_root_with_nested_game_is_detected(self):
        report=self.inspect(self.root)
        self.assertEqual(report['status'],'READY_TO_CLONE')
        self.assertEqual(report['source_game'],str(self.game))

    def test_self_contained_root_game_and_bom_build_info(self):
        standalone=self.drive/'standalone';self.root.rename(standalone)
        (standalone/'_forever_/WowF.exe').rename(standalone/'WowF.exe')
        (standalone/'_forever_').rmdir()
        info=standalone/'.build.info';info.write_text('\ufeff'+info.read_text())
        report=self.inspect(standalone)
        self.assertEqual(report['layout']['game_part'],'.')
        migration.clone(report,lambda _:None)
        self.assertTrue((self.output/'WowF.exe').is_file())
        self.assertTrue((self.output/'ForeverLauncher.exe').is_file())
        self.assertEqual((self.output/'.build.info').read_bytes(),info.read_bytes())

    def test_multiple_products_require_selection_before_copy(self):
        info=self.root/'.build.info';info.write_text(info.read_text()+'wow_classic_beta|1|'+'cd'*16+'|1.60.1.70532\n')
        report=self.inspect()
        self.assertEqual(report['status'],'NEEDS_INFORMATION')
        with self.assertRaisesRegex(ValueError,'not ready'):migration.clone(report)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.inspect(product='wow_forever')['status'],'READY_TO_CLONE')

    def test_source_build_change_after_plan_and_existing_destination_are_preserved(self):
        report=self.inspect();info=self.root/'.build.info';before=info.read_text()
        info.write_text(before.replace(KEY,'ef'*16))
        with self.assertRaisesRegex(ValueError,'build changed'):migration.clone(report)
        self.assertFalse(self.output.exists());info.write_text(before)
        self.output.mkdir(parents=True);keep=self.output/'keep';keep.write_text('existing destination')
        with self.assertRaises(FileExistsError):migration.clone(report)
        self.assertEqual(keep.read_text(),'existing destination')

    def test_linked_data_and_overlap_old_client_are_refused(self):
        with self.assertRaisesRegex(ValueError,'old experiment'):
            migration.inspect(self.game,self.old/'new',self.old,query_launchers=False)
        data=self.root/'Data';data.rename(self.root/'real-data');data.symlink_to(self.root/'real-data',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Linked'):self.inspect()

    def test_resume_reuses_verified_data_with_new_layout(self):
        report=self.inspect();original_open=Path.open
        def interrupt(path,*args,**kwargs):
            if path==self.game/'WowF.exe':raise OSError('simulated copy interruption')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',autospec=True,side_effect=interrupt):
            with self.assertRaisesRegex(OSError,'interruption'):migration.clone(report,lambda _:None)
        partial=self.output.with_name(self.output.name+'.partial')
        self.assertTrue((partial/'client/Data/data/data.000').is_file())
        def do_not_recopy_data(path,*args,**kwargs):
            self.assertNotEqual(path,self.root/'Data/data/data.000')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',autospec=True,side_effect=do_not_recopy_data):
            migration.clone(report,lambda _:None)
        self.assertTrue((self.output/'_forever_/WowF.exe').is_file())

    def test_addon_migration_supports_new_executable_and_restores_new_stock_addons(self):
        addons=self.game/'Interface/AddOns/Stock';addons.mkdir(parents=True)
        (addons/'Stock.toc').write_text('## Interface: 170000\n')
        (self.game/'WTF').mkdir();(self.game/'WTF/Config.wtf').write_text('new baseline settings')
        report=self.inspect();migration.clone(report,lambda _:None)
        backup=self.drive/'backups/first'
        migration.migrate_addons(self.output,backup)
        target=self.output/'_forever_'
        self.assertTrue((target/'Interface/AddOns/ForeverAscension/ForeverAscension.toc').is_file())
        self.assertTrue((target/'Interface/AddOns/Stock/Stock.toc').is_file())
        self.assertEqual((target/'WTF/Config.wtf').read_text(),'new baseline settings')
        self.assertTrue((backup/'before/Stock/Stock.toc').is_file())
        migration.restore_addons(self.output)
        self.assertTrue((target/'Interface/AddOns/Stock/Stock.toc').is_file())
        self.assertFalse((target/'Interface/AddOns/ForeverAscension').exists())
        self.assertFalse(json.loads((self.output/migration.MARKER).read_text())['old_addons_transferred'])
        with self.assertRaisesRegex(ValueError,'No active AddOn migration'):migration.restore_addons(self.output)

    def test_partial_copy_cannot_reuse_hardlinks_to_the_source(self):
        report=self.inspect();original_open=Path.open
        def interrupt(path,*args,**kwargs):
            if path==self.game/'WowF.exe':raise OSError('simulated interruption')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',autospec=True,side_effect=interrupt):
            with self.assertRaises(OSError):migration.clone(report,lambda _:None)
        staged=self.output.with_name(self.output.name+'.partial')/'client/Data/data/data.000'
        staged.unlink();os.link(self.root/'Data/data/data.000',staged)
        with self.assertRaisesRegex(ValueError,'Hardlinked'):migration.clone(report,lambda _:None)
        self.assertFalse(self.output.exists())

    def test_reports_cannot_be_written_into_selected_data(self):
        report=self.inspect()
        with self.assertRaisesRegex(ValueError,'selected client data'):
            migration.save_report(report,self.root/'Data/reports')
        self.assertFalse((self.root/'Data/reports').exists())

    def test_unknown_layout_produces_report_without_copying(self):
        unknown=self.drive/'unknown';unknown.mkdir();(unknown/'ForeverLauncher.exe').write_bytes(b'owned launcher')
        report=self.inspect(unknown)
        self.assertEqual(report['status'],'NEEDS_INFORMATION')
        self.assertFalse(self.output.exists())

    def test_version_2050_is_not_reported_as_205(self):
        wrong=[dict(path=str(self.root/'ForeverLauncher.exe'),file_version='2.0.50.0',product_version='2.0.50')]
        with patch.object(migration,'launcher_versions',return_value=wrong):
            report=migration.inspect(self.game,self.output,self.old)
        self.assertFalse(report['preferred_launcher']['version_verified'])
