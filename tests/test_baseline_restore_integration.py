"""Opt-in real Docker/MySQL roundtrip using only generated test data."""
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('restore_integration', ROOT / 'scripts/test-baseline-restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


@unittest.skipUnless(os.environ.get('FOREVER_RESTORE_INTEGRATION') == '1', 'Real Docker/MySQL restore test is opt-in')
class BaselineRestoreIntegration(unittest.TestCase):
    def test_four_databases_and_module_rows_restore_from_archive_without_altering_source(self):
        with tempfile.TemporaryDirectory(prefix='forever-restore-integration-') as temp:
            root = Path(temp)
            image = json.loads(restore.docker('image','inspect','mysql:8.0'))[0]['Id']
            source_dir = root / 'source'; source_dir.mkdir()
            source = restore.MysqlTrial(image, source_dir)
            try:
                source.start()
                source.sql(''.join('CREATE DATABASE `' + name + '`;\n' for name in restore.DATABASES)
                           + 'CREATE TABLE auth.battlenet_accounts(id INT PRIMARY KEY);\n'
                           + 'CREATE TABLE auth.account(id INT PRIMARY KEY);\n'
                           + 'CREATE TABLE characters.characters(guid INT PRIMARY KEY);\n'
                           + 'INSERT INTO auth.battlenet_accounts VALUES (1),(2);\n'
                           + 'INSERT INTO auth.account VALUES (1),(2),(3);\n'
                           + 'INSERT INTO characters.characters VALUES (10),(20);\n'
                           + 'CREATE TABLE world.trial_world(id INT PRIMARY KEY);\n'
                           + 'CREATE DEFINER=`trinity`@`%` VIEW world.trial_view AS SELECT id FROM world.trial_world;\n'
                           + 'CREATE TABLE hotfixes.trial_hotfix(id INT PRIMARY KEY);\n'
                           + 'USE characters;\n'
                           + (ROOT / 'mods/forever-advancement/sql/characters.sql').read_text()
                           + (ROOT / 'mods/living-encyclopedia/sql/characters-v1.sql').read_text()
                           + 'INSERT INTO characters.forever_advancement_spells VALUES (10,1300);\n'
                           + 'INSERT INTO characters.forever_advancement_resources VALUES (10,0,125);\n'
                           + 'INSERT INTO characters.forever_advancement_class_progress VALUES (10,1,4,50);\n'
                           + 'INSERT INTO characters.forever_encyclopedia_discovery(account_id,kind,entry) VALUES (1,1,1933);\n'
                           + 'INSERT INTO characters.forever_encyclopedia_account(account_id,knowledge_total) VALUES (1,25);\n')
                expected = restore.snapshot(source)
                self.assertEqual(expected['counts'], ['2','3','2'])
                backup = root / 'baseline'; backup.mkdir()
                command = ['docker','exec',source.name,'sh','-c',
                           'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction '
                           '--routines --triggers --events --hex-blob --set-gtid-purged=OFF '
                           '--databases auth world characters hotfixes']
                with (backup / 'databases-current.sql.gz').open('wb') as output:
                    with gzip.GzipFile(fileobj=output,mode='wb') as compressed:
                        with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                            while block := process.stdout.read(1024*1024):
                                compressed.write(block)
                            self.assertEqual(process.wait(),0,'Fixture dump failed')
                with tarfile.open(backup / 'server-files.tar.gz','w:gz') as archive:
                    body = b'generated fixture only'
                    item = tarfile.TarInfo('fs/fixture.txt'); item.size = len(body)
                    archive.addfile(item,io.BytesIO(body))
                restore.docker('image','save','-o',str(backup / 'docker-images.tar'),image)
                (backup / 'RESTORE.ru.txt').write_text('Generated integration fixture; no private server data.')
                names = ('databases-current.sql.gz','server-files.tar.gz','docker-images.tar','RESTORE.ru.txt')
                manifest = dict(format=restore.baseline.FORMAT,complete=True,database_snapshot=expected,
                                images={'mysql':{'id':image,'reference':'mysql:8.0'}},
                                artifacts={name:restore.baseline.artifact(backup/name) for name in names})
                (backup / 'manifest.json').write_text(json.dumps(manifest))
                original_check = restore.check_restored
                def assert_values(trial, snapshot):
                    result = original_check(trial,snapshot)
                    self.assertEqual(trial.sql('SELECT current_value FROM characters.forever_advancement_resources;').strip(),'125')
                    self.assertEqual(trial.sql('SELECT knowledge_total FROM characters.forever_encyclopedia_account;').strip(),'25')
                    return result
                with patch.object(restore,'check_restored',side_effect=assert_values):
                    report = restore.run_check(backup)
                self.assertTrue(report['data_verified'])
                self.assertTrue(report['cleanup_verified'])
                self.assertEqual(report['module_rows']['forever_advancement_spells'],1)
                self.assertEqual(report['module_rows']['forever_encyclopedia_discovery'],1)
                self.assertEqual(restore.snapshot(source),expected,'Source database changed during trial')
                self.assertEqual(source.sql('SELECT current_value FROM characters.forever_advancement_resources;').strip(),'125')
                self.assertTrue(source.owned('container')['State']['Running'])
                trial_name = restore.PREFIX + report['nonce']
                self.assertIsNone(restore.docker('container','inspect',trial_name,missing=True))
                self.assertIsNone(restore.docker('volume','inspect',trial_name+'-data',missing=True))
                self.assertNotEqual(trial_name,source.name)
                # A valid archive hash is not enough: malformed SQL must fail,
                # clean up the disposable database, and leave the source running.
                bad = root / 'bad-baseline'; bad.mkdir()
                for name in names:
                    if name != 'databases-current.sql.gz':
                        os.link(backup/name,bad/name)
                with gzip.open(bad / 'databases-current.sql.gz','wb') as output:
                    output.write(b'CREATE DATABASE auth;\nTHIS IS INVALID SQL;\n')
                invalid = dict(manifest, artifacts={name:restore.baseline.artifact(bad/name) for name in names})
                (bad / 'manifest.json').write_text(json.dumps(invalid))
                previous_reports = set(root.glob('restore-test-*/report.json'))
                with self.assertRaises(restore.TrialFailure) as caught:
                    restore.run_check(bad)
                self.assertIn('ERROR 1064',str(caught.exception))
                failed_report_path, = set(root.glob('restore-test-*/report.json')) - previous_reports
                failed_report = json.loads(failed_report_path.read_text())
                self.assertFalse(failed_report['data_verified'])
                self.assertTrue(failed_report['cleanup_verified'])
                self.assertEqual(restore.snapshot(source),expected)
                self.assertTrue(source.owned('container')['State']['Running'])
            finally:
                source.cleanup()


if __name__ == '__main__':
    unittest.main()
