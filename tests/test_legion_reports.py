"""Reports go to the work directory and exclude game payloads and settings."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import legion_reports as reports


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)/'work';self.client=self.work/'experiments/client'
        self.client.mkdir(parents=True)
        self.info=b'owned build metadata';(self.client/'.build.info').write_bytes(self.info)
        self.token='a'*32;self.ops=self.client/'legion-resource-operations';folder=self.ops/self.token;folder.mkdir(parents=True)
        (self.ops/'active.json').write_text(json.dumps(dict(operation=self.token)))
        journal=dict(format='wowforever-legion-resource-operation-v1',copy=str(self.client),phase='verified',
                     after_info_sha256=hashlib.sha256(self.info).hexdigest(),tvfs_entry_canary=True,added={'data.052':{}})
        (folder/'operation.json').write_text(json.dumps(journal));(folder/'result.json').write_text('{"owned":true}')
        self.logs=self.client/'_classic_beta_/Logs';self.logs.mkdir(parents=True)
        (self.logs/'Client.log').write_text('owned client trace')
        (self.logs/'Tact.log').write_text('Archive[52]: Fully Compacted')
        (self.client/'_classic_beta_/WowB.exe').write_bytes(b'owned executable placeholder')
        (self.client/'_classic_beta_/WTF').mkdir();(self.client/'_classic_beta_/WTF/Config.wtf').write_text('private settings')

    def test_collects_active_result_and_logs_into_standard_work_reports_without_client_writes(self):
        before={p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()}
        with patch.object(reports,'game_processes',return_value=dict(available=False)):
            archive=reports.collect(self.client)
        self.assertEqual(archive.parent,self.work/'reports')
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()),{'operation.json','result.json','summary.json','logs/Client.log','logs/Tact.log'})
            summary=json.loads(z.read('summary.json'))
            self.assertTrue(summary['active_is_tvfs_entry_canary']);self.assertTrue(summary['build_matches_operation'])
            self.assertEqual(summary['newest_archive_number_in_tact_log'],52)
            self.assertEqual(summary['capture_stage'],'after_user_test')
        self.assertEqual(before,{p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()})

    def test_log_tail_is_bounded_and_report_does_not_require_successful_canary(self):
        folder=self.ops/self.token;j=json.loads((folder/'operation.json').read_text());j['tvfs_entry_canary']=False
        (folder/'operation.json').write_text(json.dumps(j));(self.logs/'Client.log').write_bytes(b'head_'+b'x'*100)
        with patch.object(reports,'game_processes',return_value=dict(available=False)),patch.object(reports,'MAX_LOG_BYTES',32):
            archive=reports.collect(self.client)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('logs/Client.log'),b'x'*32)
            summary=json.loads(z.read('summary.json'));self.assertFalse(summary['active_is_tvfs_entry_canary'])
            self.assertTrue(next(x for x in summary['logs'] if x['name']=='Client.log')['tail_only'])

    def test_refuses_client_output_and_invalid_journal_pointer(self):
        with self.assertRaises(ValueError):reports.collect(self.client,self.client/'reports')
        (self.ops/'active.json').write_text('{"operation":"../foreign"}')
        with self.assertRaisesRegex(ValueError,'token'):reports.collect(self.client)
