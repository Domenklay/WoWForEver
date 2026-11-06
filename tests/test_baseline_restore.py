import importlib.util
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('baseline_restore_tests', ROOT / 'scripts/test-baseline-restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
IMAGE = 'sha256:' + 'a'*64
NONCE = 'abcdef123456'


class BaselineRestoreTests(unittest.TestCase):
    def test_cleanup_refuses_foreign_container_or_volume_before_any_removal(self):
        for foreign in ('container', 'volume'):
            with self.subTest(foreign=foreign), tempfile.TemporaryDirectory() as temp:
                trial = restore.MysqlTrial(IMAGE, Path(temp), NONCE)
                def docker(*args, **kwargs):
                    kind = args[0]
                    self.assertEqual(args[1], 'inspect')
                    token = 'working-server' if kind == foreign else NONCE
                    labels = {restore.LABEL:token, restore.LABEL+'.role':kind}
                    item = {'Name': trial.name if kind == 'container' else trial.volume,
                            'Config':{'Labels':labels}, 'Labels':labels}
                    return json.dumps([item])
                with patch.object(restore, 'docker', side_effect=docker):
                    with self.assertRaisesRegex(ValueError, 'ownership mismatch'):
                        trial.cleanup(force=True)

    def test_cleanup_does_not_remove_anything_if_start_never_allocated_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = restore.MysqlTrial(IMAGE, Path(temp), NONCE)
            with patch.object(restore, 'docker') as docker:
                trial.cleanup()
                docker.assert_not_called()

    def test_start_uses_a_fresh_volume_no_host_mounts_no_ports_and_no_network(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = restore.MysqlTrial(IMAGE, Path(temp), NONCE)
            calls = []
            def docker(*args, **kwargs):
                calls.append((args, kwargs))
                if args[:2] == ('image','inspect'):
                    return json.dumps([{'Id':IMAGE,'Os':'linux'}])
                if args[:2] == ('container','create'):
                    for required in ('--pull=never','--network=none','--restart=no','--cpus=1','--memory=1g'):
                        self.assertIn(required, args)
                    self.assertFalse(any('type=bind' in value or value in ('-p','--publish','--volumes-from') for value in args))
                    self.assertIn('type=volume,source='+trial.volume+',target=/var/lib/mysql,volume-nocopy',args)
                if args[0] == 'exec':
                    self.assertEqual(args[1], '-i')
                    return '1\n'
                return ''
            item = {'Image':IMAGE,'HostConfig':{'NetworkMode':'none','PortBindings':{},'Binds':[]},
                    'Mounts':[{'Type':'volume','Name':trial.volume,'Destination':'/var/lib/mysql'}],
                    'State':{'Running':True}}
            with patch.object(restore, 'docker', side_effect=docker), \
                 patch.object(trial, 'owned', side_effect=[None,None,item,item]), \
                 patch.object(trial, 'sql'):
                trial.start()
            self.assertTrue(trial.can_cleanup)
            self.assertTrue(trial.owns_env)
            self.assertIn(('container','start',trial.name),[args for args,_ in calls])

    def test_failed_isolation_check_cannot_start_the_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = restore.MysqlTrial(IMAGE, Path(temp), NONCE)
            image = json.dumps([{'Id':IMAGE,'Os':'linux'}])
            with patch.object(restore, 'docker', return_value=image) as docker, \
                 patch.object(trial, 'owned', side_effect=[None,None,{'Image':IMAGE,'HostConfig':{'NetworkMode':'bridge'}}]):
                with self.assertRaisesRegex(ValueError, 'isolation'):
                    trial.start()
            self.assertFalse(any(call.args[:2] == ('container','start') for call in docker.call_args_list))

    def test_snapshot_uses_the_same_schema_hash_as_the_original_backup(self):
        class Trial:
            def sql(self, query):
                return '2\n4\n8\n' if query == restore.COUNTS_SQL else 'auth\taccount\tid\tint\tNO\t<NULL>\tauto_increment\n'
        trial = Trial()
        with patch.object(restore.baseline.upgrade.clean, 'sql', side_effect=lambda state,query: trial.sql(query)):
            expected = restore.baseline.upgrade.snapshot({})
        self.assertEqual(restore.snapshot(trial), expected)

    def exercise(self, folder, failure=None):
        backup = folder / 'backup'; backup.mkdir()
        with gzip.open(backup / 'databases-current.sql.gz','wb') as stream:
            stream.write(b'SELECT 1;\n')
        expected = {'counts':['2','4','8'], 'schema_sha256':'b'*64}
        manifest = {'database_snapshot':expected,'images':{'mysql':{'id':IMAGE}}}
        with patch.object(restore.baseline, 'verify', return_value=manifest), \
             patch.object(restore.MysqlTrial, 'start') as start, \
             patch.object(restore.MysqlTrial, 'require_space'), \
             patch.object(restore.MysqlTrial, 'restore', side_effect=RuntimeError('import') if failure == 'import' else None), \
             patch.object(restore, 'check_restored', side_effect=ValueError('snapshot differs') if failure == 'compare' else None,
                          return_value=(expected, {name:1 for name in restore.MODULE_TABLES})), \
             patch.object(restore.MysqlTrial, 'cleanup') as cleanup:
            if failure:
                with self.assertRaises((ValueError, RuntimeError)):
                    restore.run_check(backup)
            else:
                report = restore.run_check(backup)
                self.assertTrue(report['data_verified'])
                self.assertTrue(report['cleanup_verified'])
                self.assertFalse(report['full_server_restore_verified'])
            start.assert_called_once(); cleanup.assert_called_once()
        report_path = next(folder.glob('restore-test-*/report.json'))
        return json.loads(report_path.read_text())

    def test_trial_reports_verification_and_cleans_up_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            report = self.exercise(Path(temp))
            self.assertEqual(report['phase'], 'verified')

    def test_import_or_comparison_failure_still_cleans_up_and_cannot_claim_success(self):
        for failure in ('import','compare'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                report = self.exercise(Path(temp), failure)
                self.assertFalse(report['data_verified'])
                self.assertTrue(report['cleanup_verified'])
                self.assertEqual(report['phase'], 'failed')

    def test_corrupt_backup_never_creates_a_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(restore.baseline, 'verify', side_effect=ValueError('checksum')), \
                 patch.object(restore.MysqlTrial, 'start') as start:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    restore.run_check(Path(temp))
                start.assert_not_called()

    def test_missing_snapshot_cannot_create_trial_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(restore.baseline, 'verify', return_value={}), \
                 patch.object(restore.MysqlTrial, 'start') as start:
                with self.assertRaisesRegex(ValueError, 'snapshot'):
                    restore.run_check(Path(temp))
                start.assert_not_called()

    def test_cleanup_report_cannot_select_a_live_server_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            path.write_text(json.dumps({'format':restore.FORMAT,'nonce':NONCE,'image':IMAGE}))
            with patch.object(restore, 'docker') as docker:
                with self.assertRaisesRegex(ValueError, 'report path'):
                    restore.cleanup_report(path)
                docker.assert_not_called()

    def test_trial_space_check_uses_the_new_volume_and_rejects_low_space(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = restore.MysqlTrial(IMAGE, Path(temp), NONCE)
            with patch.object(trial, 'owned'), \
                 patch.object(restore, 'docker', return_value='Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 1024 900 124 90% /var/lib/mysql\n') as docker:
                with self.assertRaisesRegex(ValueError, 'Not enough trial-volume space'):
                    trial.require_space(1024)
                self.assertEqual(docker.call_args.args,('exec',trial.name,'df','-Pk','/var/lib/mysql'))


if __name__ == '__main__':
    unittest.main()
