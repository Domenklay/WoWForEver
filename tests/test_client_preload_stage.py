import base64
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_client_preload_audit import module, source, snapshot, lab, manifest

stage = module('preload_stage_test', 'stage-client-preload.py')
VERSION = dict(file='1.60.1.70707', product='Version 1.60.1.70707')


class PreloadStageTests(unittest.TestCase):
    def test_verified_regional_files_are_staged_without_source_or_metadata_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory, include_china=True)
            before = snapshot(root)
            output = directory / 'staged'
            with patch.object(stage, 'windows_version', return_value=VERSION) as version:
                report = stage.stage(root, output, key)
            self.assertEqual(report['phase'], 'bootstrap-staged')
            self.assertTrue(report['exe_version_verified'])
            self.assertFalse(report['activated'])
            self.assertFalse(report['full_asset_integrity_verified'])
            self.assertFalse(report['server_compatibility_verified'])
            self.assertEqual(report['selected_install_tags'], ['Windows', 'x86_64', 'EU'])
            self.assertEqual(len(report['files']), 2)
            self.assertEqual(report['native_exe_versions'], VERSION)
            version.assert_called_once_with(output / '_forever_/Wow.exe')
            self.assertEqual((output / '_forever_/Wow.exe').read_bytes(), (root / '_forever_/Wow.exe').read_bytes())
            self.assertNotEqual((output / '_forever_/Wow.exe').stat().st_ino, (root / '_forever_/Wow.exe').stat().st_ino)
            self.assertNotEqual((output / '_forever_/wow_loader.dll').read_bytes(), (root / '_forever_/wow_loader.dll').read_bytes())
            self.assertEqual(json.loads((output / 'stage-report.json').read_text()), report)
            self.assertFalse((output / '.build.info').exists())
            self.assertFalse((output / 'Data').exists())
            self.assertFalse((output / '_forever_/WTF').exists())
            self.assertEqual(snapshot(root), before)

    def test_missing_cached_files_leave_an_explicit_incomplete_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory, resident=False)
            before = snapshot(root)
            with patch.object(stage, 'windows_version') as version:
                report = stage.stage(root, directory / 'stage', key)
            self.assertEqual(report['phase'], 'incomplete')
            self.assertEqual(len(report['failures']), 2)
            self.assertEqual(report['files'], [])
            self.assertFalse(report['exe_version_verified'])
            version.assert_not_called()
            self.assertEqual(snapshot(root), before)

    def test_corrupt_cached_executable_is_not_written_or_version_confirmed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory)
            store = stage.audit.open_store(root)
            wow = lab.asset(b'MZ-owned-synthetic-wow-binary')
            entry = store.entries[wow['ekey'][:9]]
            offset = int.from_bytes(entry[9:14], 'big') & ((1 << store.bits) - 1)
            data_path = root / 'Data/data/data.000'
            raw = bytearray(data_path.read_bytes())
            size = int.from_bytes(entry[14:18], 'little')
            raw[offset + size - 1] ^= 1
            data_path.write_bytes(raw)
            before = snapshot(root)
            output = directory / 'stage'
            with patch.object(stage, 'windows_version') as version:
                report = stage.stage(root, output, key)
            self.assertEqual(report['phase'], 'incomplete')
            self.assertFalse((output / '_forever_/Wow.exe').exists())
            self.assertEqual(report['failures'][0]['path'], 'Wow.exe')
            version.assert_not_called()
            self.assertEqual(snapshot(root), before)

    def test_wrong_or_unavailable_native_version_does_not_complete_the_stage(self):
        for result in (dict(file='1.60.1.70658', product='Version 1.60.1.70658'),
                       ValueError('Windows interop unavailable')):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                root, key = source(directory)
                before = snapshot(root)
                options = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch.object(stage, 'windows_version', **options):
                    report = stage.stage(root, directory / 'stage', key)
                self.assertEqual(report['phase'], 'incomplete')
                self.assertFalse(report['exe_version_verified'])
                self.assertFalse(report['activated'])
                self.assertIn('detail', report)
                self.assertEqual(snapshot(root), before)

    def test_changed_source_during_external_version_inspection_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory)
            def changed(_):
                path = root / '.build.info'
                path.write_bytes(path.read_bytes() + b'\n')
                return VERSION
            with patch.object(stage, 'windows_version', side_effect=changed):
                report = stage.stage(root, directory / 'stage', key)
            self.assertEqual(report['phase'], 'incomplete')
            self.assertIn('changed during inspection', report['detail'])

    def test_existing_destination_and_source_overlap_are_refused_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory)
            existing = directory / 'existing'
            existing.mkdir()
            (existing / 'keep').write_text('retained')
            before = snapshot(directory)
            for output in (existing, root / '_forever_/new-stage', root):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    stage.stage(root, output, key)
            self.assertEqual(snapshot(directory), before)

    def test_staging_resolves_directory_case_and_refuses_duplicate_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'Utils').mkdir()
            self.assertEqual(stage.destination_path(root, 'UTILS/LOCALES/a.pak'), root / 'Utils/LOCALES/a.pak')
        wow = lab.asset(b'MZ-owned-fixture')
        for names in (['Wow.exe', 'wow_loader.dll', 'WOW.EXE'],
                      ['Wow.exe', 'wow_loader.dll', 'Utils', 'utils/a.pak']):
            with self.subTest(names=names), self.assertRaises(ValueError):
                stage.selected_files(stage.audit.parse_install_manifest(manifest([(n, wow) for n in names])), 'EU')

    def test_space_check_precedes_creation_and_never_touches_existing_client(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory)
            before = snapshot(root)
            output = directory / 'stage'
            with patch.object(stage.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                    self.assertRaisesRegex(ValueError, 'Insufficient space'):
                stage.stage(root, output, key)
            self.assertFalse(output.exists())
            self.assertEqual(snapshot(root), before)

    def test_linked_destination_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root, key = source(directory)
            (directory / 'linked').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'without links'):
                stage.stage(root, directory / 'linked/staged', key)

    def test_native_string_versions_preserve_builds_above_65535_and_require_agreement(self):
        stage.require_build(VERSION, 70707)
        for versions in (dict(file='1.60.1.5171', product='Version 1.60.1.70707'),
                         dict(file='1.60.1.70707', product='Version 1.60.1.70658'),
                         dict(file='1.60.1.70707 1.60.1.70708', product='Version 1.60.1.70707'),
                         dict(file=None, product='Version 1.60.1.70707')):
            with self.subTest(versions=versions), self.assertRaises(ValueError):
                stage.require_build(versions, 70707)

    def test_windows_query_only_reads_encoded_literal_path_and_never_runs_game(self):
        result = SimpleNamespace(stdout=json.dumps(VERSION).encode())
        with patch.object(stage.shutil, 'which', return_value='/usr/bin/powershell.exe'), \
                patch.object(stage.subprocess, 'run', return_value=result) as run:
            versions = stage.windows_version(Path("/mnt/e/Owner's games/Wow.exe"))
        self.assertEqual(versions, VERSION)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand'])
        command = base64.b64decode(args[4]).decode('utf-16le')
        self.assertIn('Get-Item -LiteralPath $p', command)
        self.assertNotIn('Start-Process', command)
        self.assertNotIn("Owner's games", command)
        self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_metadata_context_keeps_inactive_target_config_but_omits_unrelated_fields(self):
        info = (b'Product!STRING:0|Active!DEC:1|Version!STRING:0|CDN Key!HEX:16|Session!STRING:0\n'
                b'wowf|1|1.60.1.70658|old-config|do-not-collect\n'
                b'wowf|0|1.60.1.70707|target-config|do-not-collect\n'
                b'other|1|2.0|other-config|do-not-collect\n')
        rows = stage.metadata_rows(info)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['CDN Key'], 'target-config')
        self.assertNotIn('Session', rows[0])
        self.assertNotIn('Session', rows[1])


if __name__ == '__main__': unittest.main()
