import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import module_readiness as ready
spec = importlib.util.spec_from_file_location('readiness_clean',ROOT/'scripts/clean-forever-server.py')
clean = importlib.util.module_from_spec(spec);spec.loader.exec_module(clean)
START = '2026-11-06T21:00:00.000000000Z'
START_SECONDS = 1793998800


class ModuleReadinessTests(unittest.TestCase):
    def file_probe(self, root, append=False, stale=False):
        config=root/'worldserver.conf'; log=root/'Server.log'
        config.write_text('ForeverAdvancement.Enable = 1\nLogger.scripts = 3,Console Server\n'
                          +'LogsDir = "'+str(root)+'"\nAppender.Server = 2,2,0,Server.log,'+('a' if append else 'w')
                          +'\nLoginDatabaseInfo = "mysql;password-that-must-not-leave"\n')
        log.write_text('ForeverAdvancement ready: fixture\n'+'irrelevant startup line\n'*6000)
        os.utime(log,(START_SECONDS+(2 if not stale else -20),)*2)
        out=subprocess.check_output([sys.executable,'-c',ready.PROBE,str(config),START],text=True)
        self.assertNotIn('password-that-must-not-leave',out);self.assertNotIn('LoginDatabaseInfo',out)
        return json.loads(out)

    def test_current_file_finds_a_marker_outside_the_docker_tail_without_secret_config(self):
        with tempfile.TemporaryDirectory() as temp:
            result=self.file_probe(Path(temp))
            self.assertEqual(result['serverLogStatus'],'current-process-file')
            self.assertEqual(result['lines'],['ForeverAdvancement ready: fixture'])

    def test_file_evidence_from_earlier_processes_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for kwargs,status in [({'stale':True},'older-than-current-process'),({'append':True},'not-truncate-mode')]:
                result=self.file_probe(Path(temp),**kwargs)
                self.assertEqual(result['serverLogStatus'],status);self.assertEqual(result['lines'],[])

    def test_stderr_is_merged_only_for_docker_log_reads(self):
        with patch.object(clean.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='module error from stderr',stderr=None)) as run:
            self.assertEqual(clean.run(['docker','logs','current'],capture=True,merge_log_streams=True),'module error from stderr')
            self.assertIs(run.call_args.kwargs['stderr'],subprocess.STDOUT)
        with patch.object(clean.subprocess,'run') as run:
            with self.assertRaises(ValueError):clean.run(['docker','compose','config'],capture=True,merge_log_streams=True)
            run.assert_not_called()

    def test_combined_evidence_is_scoped_and_secrets_are_redacted(self):
        service=Mock(); item={'Id':'current','Config':{'Image':'candidate'},'State':{'StartedAt':START,'Running':True}}
        service.run.return_value='ForeverAdvancement schema missing; token=private-value\nprivate unrelated log'
        service.compose.return_value=json.dumps(dict(settings={},serverLogStatus='current-process-file',
            lines=['ForeverScaling ready: password=private-value']))
        report=ready.snapshot(service,{'credentials':{'database':'private-value'}},item)
        self.assertNotIn('private-value',str(report));self.assertNotIn('unrelated',str(report))
        self.assertIn(START,service.run.call_args.args[0]);self.assertTrue(service.run.call_args.kwargs['merge_log_streams'])

    def test_a_late_marker_is_awaited_without_restarting_the_world(self):
        service=Mock();service.container.return_value={'Id':'current','State':{'StartedAt':START,'Running':True}}
        pending=dict(lines=['first'],settings={},serverLogStatus='current-process-file')
        complete=dict(pending,lines=['first','second'])
        with patch.object(ready,'snapshot',side_effect=[pending,complete]), patch.object(ready.time,'sleep') as pause:
            result=ready.wait(service,{},['first','second'],20)
        self.assertEqual(result,complete);self.assertEqual(pause.call_count,1);service.wait_world.assert_called_once()

    def test_restarts_and_missing_protocol_cannot_pass_as_ready(self):
        service=Mock();live={'Id':'current','State':{'StartedAt':START,'Running':True}}
        service.container.side_effect=[live,dict(live,Id='another')]
        report=dict(lines=['ready','protocol'],settings={},serverLogStatus='current-process-file')
        with patch.object(ready,'snapshot',return_value=report):
            with self.assertRaisesRegex(RuntimeError,'changed'):ready.wait(service,{},['ready','protocol'])
        service.container.side_effect=None;service.container.return_value=live
        with patch.object(ready,'snapshot',return_value=dict(report,lines=['ready'])):
            with self.assertRaisesRegex(RuntimeError,'protocol'):ready.wait(service,{},['ready','protocol'],0)

    def test_explicit_initialization_failures_are_not_hidden_by_a_successful_tcp_probe(self):
        service=Mock();service.container.return_value={'Id':'current','State':{'StartedAt':START,'Running':True}}
        report=dict(lines=['ForeverAdvancement schema missing: owned-table'],settings={},serverLogStatus='current-process-file')
        with patch.object(ready,'snapshot',return_value=report):
            with self.assertRaisesRegex(RuntimeError,'schema missing'):ready.wait(service,{},['ready'])

    def test_failure_capture_keeps_stopped_process_errors_before_recreation(self):
        service=Mock();service.run.return_value='ForeverAdvancement schema missing: table'
        item={'Id':'failed-candidate','Config':{'Image':'candidate'},'State':{'StartedAt':START,'Running':False,'ExitCode':1}}
        report=ready.snapshot(service,{},item,allow_stopped=True)
        self.assertEqual(report['exitCode'],1);self.assertIn('schema missing',report['lines'][0])
        service.compose.assert_not_called()


if __name__=='__main__':unittest.main()
