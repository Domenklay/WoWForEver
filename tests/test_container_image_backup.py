import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'preserve_image', Path(__file__).parents[1]/'scripts/preserve-container-image.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ContainerImageBackupTests(unittest.TestCase):
    def check_path(self, available, tag_fails=False):
        calls = []
        def docker(command, **kwargs):
            calls.append(command)
            args = command[1:]
            if args == ['inspect', 'running-world']:
                output, code = json.dumps([{'Image': 'sha256:old-manifest', 'Config': {
                    'Entrypoint':['/usr/local/bin/entrypoint.sh'], 'Cmd':['worldserver'],
                    'WorkingDir':'/opt/trinitycore/bin', 'User':''}}]), 0
            elif args == ['image', 'inspect', 'sha256:old-manifest']:
                output, code = '[]', 0 if available else 1
            elif args == ['image', 'inspect', 'server:unique-backup']:
                output, code = json.dumps([{'Id': 'sha256:preserved'}]), 0
            elif args[0] == 'tag':
                output, code = '', 1 if tag_fails else 0
            else:
                output, code = '', 0
            return subprocess.CompletedProcess(command, code, output, '')
        with patch.object(helper.subprocess, 'run', side_effect=docker):
            result = helper.preserve('running-world', 'server:unique-backup')
        self.assertEqual(result['rollback_reference'], 'server:unique-backup')
        self.assertEqual(result['saved_image_id'], 'sha256:preserved')
        self.assertFalse(result['volumes_included'])
        self.assertFalse(any('latest' in arg for call in calls for arg in call))
        return result, calls

    def test_original_image_is_tagged_when_available(self):
        result, calls = self.check_path(True)
        self.assertEqual(result['method'], 'original-image-tag')
        self.assertIn(['docker','tag','sha256:old-manifest','server:unique-backup'], calls)
        self.assertFalse(any('commit' in call for call in calls))

    def test_missing_manifest_snapshots_exact_running_container(self):
        result, calls = self.check_path(False)
        self.assertEqual(result['method'], 'container-filesystem-export-import')
        export = next(c for c in calls if c[1]=='export')
        self.assertEqual(export[-1], 'running-world')
        imported = next(c for c in calls if c[1]=='import')
        self.assertEqual(imported[-1], 'server:unique-backup')
        self.assertIn('ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]', imported)
        self.assertIn('CMD ["worldserver"]', imported)
        self.assertIn('ENV LD_LIBRARY_PATH=/opt/trinitycore/lib', imported)
        self.assertFalse(any('commit' in call for call in calls))
        self.assertFalse(any('tag' in call for call in calls))

    def test_failed_snapshot_aborts_before_reporting_backup(self):
        def docker(command, **kwargs):
            if command[1] == 'inspect':
                return subprocess.CompletedProcess(command, 0, json.dumps([{
                    'Image':'sha256:missing', 'Config':{'Entrypoint':['/usr/local/bin/entrypoint.sh']}}]), '')
            if command[1] == 'image':
                return subprocess.CompletedProcess(command, 1, '', 'No such image')
            raise subprocess.CalledProcessError(1, command, stderr='snapshot failed')
        with patch.object(helper.subprocess, 'run', side_effect=docker):
            with self.assertRaises(subprocess.CalledProcessError):
                helper.preserve('running-world', 'server:unique-backup')

    def test_inspect_succeeds_but_tag_fails_uses_snapshot(self):
        result, calls = self.check_path(True, tag_fails=True)
        self.assertEqual(result['method'], 'container-filesystem-export-import')
        self.assertTrue(any(c[1]=='export' for c in calls))

    def test_unrecognized_entrypoint_refuses_fallback(self):
        def docker(command, **kwargs):
            if command[1] == 'inspect':
                return subprocess.CompletedProcess(command, 0, json.dumps([{
                    'Image':'sha256:missing', 'Config':{'Entrypoint':['other-program']}}]), '')
            self.assertEqual(command[1:3], ['image','inspect'])
            return subprocess.CompletedProcess(command, 1, '', 'No such image')
        with patch.object(helper.subprocess, 'run', side_effect=docker):
            with self.assertRaisesRegex(ValueError, 'Unexpected server entrypoint'):
                helper.preserve('running-world', 'server:unique-backup')
