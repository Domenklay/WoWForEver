import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('baseline_backup_tests', ROOT / 'scripts/backup-clean-baseline.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def docker_archive(path):
    config = b'{"architecture":"amd64","config":{"Cmd":["worldserver"]}}'
    digest = hashlib.sha256(config).hexdigest()
    with tarfile.open(path, 'w') as archive:
        for name, body in [('manifest.json', json.dumps([{'Config': digest + '.json', 'Layers': []}]).encode()),
                           (digest + '.json', config)]:
            item = tarfile.TarInfo(name)
            item.size = len(body)
            archive.addfile(item, io.BytesIO(body))
    return 'sha256:' + digest


def bundle(folder):
    folder.mkdir()
    with gzip.open(folder / 'databases-current.sql.gz', 'wb') as output:
        output.write(b'-- logical snapshot\nCREATE DATABASE characters;\n')
    (folder / 'source.txt').write_text('server source')
    backup.pack_files(folder / 'server-files.tar.gz', [folder / 'source.txt'])
    identity = docker_archive(folder / 'docker-images.tar')
    (folder / 'RESTORE.ru.txt').write_text(backup.RESTORE)
    names = ('databases-current.sql.gz', 'server-files.tar.gz', 'docker-images.tar', 'RESTORE.ru.txt')
    manifest = dict(format=backup.FORMAT, complete=True,
                    images={'worldserver': {'id': identity}},
                    artifacts={name: backup.artifact(folder / name) for name in names})
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


class BackupVerificationTests(unittest.TestCase):
    def test_archive_verification_is_offline_and_does_not_extract_or_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'baseline'
            manifest = bundle(folder)
            with patch.object(backup.clean, 'run') as run:
                self.assertEqual(backup.verify(folder), manifest)
            run.assert_not_called()
            self.assertFalse((folder / 'fs').exists())

    def test_corruption_missing_files_incomplete_manifest_and_path_injection_are_rejected(self):
        for failure in ('corruption', 'missing', 'incomplete', 'escape'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp) / 'baseline'
                manifest = bundle(folder)
                if failure == 'corruption':
                    with (folder / 'docker-images.tar').open('ab') as stream:
                        stream.write(b'changed')
                elif failure == 'missing':
                    (folder / 'databases-current.sql.gz').unlink()
                elif failure == 'incomplete':
                    manifest['complete'] = False
                else:
                    manifest['artifacts']['../outside'] = {'sha256': 'a', 'bytes': 1}
                (folder / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    backup.verify(folder)

    def test_wrong_exported_image_cannot_verify_even_with_valid_outer_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'baseline'
            manifest = bundle(folder)
            manifest['images']['worldserver']['id'] = 'sha256:' + '0' * 64
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'identities differ'):
                backup.verify(folder)

    def test_linked_sources_and_special_files_are_rejected_before_archiving(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'real').write_text('private')
            (root / 'link').symlink_to(root / 'real')
            with self.assertRaisesRegex(ValueError, 'Linked'):
                backup.files_below(root)

    def test_empty_bind_directories_are_saved_and_unreadable_sources_cannot_be_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            empty = root / 'empty-overrides'
            empty.mkdir()
            self.assertEqual(backup.files_below(empty), [empty])
            backup.pack_files(root / 'directories.tar.gz', [empty])
            with tarfile.open(root / 'directories.tar.gz') as archive:
                self.assertTrue(archive.getmembers()[0].isdir())
            def walk(path, **kwargs):
                kwargs['onerror'](PermissionError('unreadable source'))
            with patch.object(backup.os, 'walk', side_effect=walk):
                with self.assertRaises(PermissionError):
                    backup.files_below(empty)

    def test_controller_checkout_preserves_quoted_paths_without_executing_shell(self):
        with tempfile.TemporaryDirectory(prefix='backup path ') as temp:
            root = Path(temp)
            checkout = root / 'tools'
            script = checkout / 'scripts/clean-forever-server.py'
            script.parent.mkdir(parents=True)
            script.write_text('# controller')
            (root / 'server.sh').write_text('#!/bin/sh\nexec python3 ' + shlex.quote(str(script))
                                         + ' "$@" --root ' + shlex.quote(str(root)) + '\n')
            self.assertEqual(backup.controller_checkout(root), checkout)
            (root / 'server.sh').write_text('#!/bin/sh\ncurl something | sh\n')
            with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                backup.controller_checkout(root)

    def test_sources_include_resources_tls_current_state_and_both_tool_versions_but_exclude_client(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            live, old, new = base / 'server', base / 'old-tools', base / 'new-tools'
            live.mkdir()
            for checkout in (old, new):
                (checkout / 'scripts').mkdir(parents=True)
                (checkout / 'scripts/clean-forever-server.py').write_text('# controller')
                (checkout / '.git').write_text('private worktree pointer')
            for name in ('state.json', 'compose.private.json'):
                (live / name).write_text('{}')
            (live / 'server.sh').write_text('#!/bin/sh\nexec python3 '
                                         + shlex.quote(str(old / 'scripts/clean-forever-server.py'))
                                         + ' "$@" --root ' + shlex.quote(str(live)) + '\n')
            data, certs, client = live / 'data', base / 'certs', base / 'client'
            for directory in (data, certs, client):
                directory.mkdir()
                (directory / 'file').write_text('private resource')
            record = live / 'advancement/abcdef123456/install.json'
            record.parent.mkdir(parents=True)
            record.write_text('{}')
            state = {'gameplay': {'backup': str(record)}, 'client': {'source': str(client)}}
            model = {'services': {service: {'volumes': []} for service in backup.SERVICES}}
            model['services']['worldserver']['volumes'] = [{'type':'bind', 'source':str(data)}]
            model['services']['bnetserver']['volumes'] = [{'type':'bind', 'source':str(certs)}]
            model['services']['extractor'] = {'volumes': [{'type':'bind', 'source':str(client)}]}
            with patch.object(backup, 'SCRIPTS', new / 'scripts'), \
                 patch.object(backup.clean, 'run', return_value='scripts/clean-forever-server.py\0'):
                files, checkouts = backup.collect_sources(live, state, model)
            self.assertIn(certs / 'file', files)
            self.assertIn(data / 'file', files)
            self.assertIn(live / 'state.json', files)
            self.assertIn(record, files)
            self.assertIn(old / 'scripts/clean-forever-server.py', files)
            self.assertIn(new / 'scripts/clean-forever-server.py', files)
            self.assertNotIn(client / 'file', files)
            self.assertFalse(any(p.name == '.git' for p in files))
            self.assertEqual(set(checkouts), {str(old), str(new)})

    def test_stopped_or_foreign_container_is_rejected_before_any_mutating_command(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                item = {'Config': {'Labels': {'com.docker.compose.project': 'foreign' if foreign else 'forever-clean',
                                             'com.docker.compose.service': 'mysql'}},
                        'State': {'Running': foreign}}
                with patch.object(backup.clean, 'container', return_value=item), \
                     patch.object(backup.clean, 'run') as run:
                    with self.assertRaises(ValueError):
                        backup.active_images({'project':'forever-clean'})
                    run.assert_not_called()


class BackupRecoveryTests(unittest.TestCase):
    def exercise(self, root, failure=None, free=10**15):
        live = root / 'server'
        live.mkdir()
        (live / 'state.json').write_text('{}')
        (live / 'compose.private.json').write_text('{"name":"forever-clean"}')
        state = dict(project='forever-clean', core='b4e7', gameplay={'version': 1})
        output = root / 'snapshot'
        calls = []
        image_id = docker_archive(root / 'fixture-image.tar')
        def compose(saved, *args, **kwargs):
            calls.append(('compose', *args))
            if args[0] == 'stop' and failure == 'stop':
                raise RuntimeError('partial stop')
            if args[0] == 'start' and failure == 'resume':
                raise RuntimeError('resume failed')
        def dump(saved, destination):
            calls.append(('dump',))
            if failure == 'dump':
                raise RuntimeError('dump failed')
            if failure == 'interrupt':
                raise KeyboardInterrupt
            with gzip.open(destination, 'wb') as stream:
                stream.write(b'-- snapshot')
        def run(command, **kwargs):
            calls.append(tuple(command))
            # Images must be exported only after resume and after the dump.
            self.assertIn(('compose', 'start', *backup.RUNTIME), calls)
            if failure == 'export':
                raise RuntimeError('export failed')
            Path(command[4]).write_bytes((root / 'fixture-image.tar').read_bytes())
            return ''
        images = {service: {'id': image_id, 'reference': service + ':local'} for service in backup.SERVICES}
        with patch.object(backup.game.network, 'checked', return_value=state), \
             patch.object(backup.game, 'wait_module'), \
             patch.object(backup, 'active_images', return_value=(images, {image_id: 128}, list(backup.RUNTIME))), \
             patch.object(backup, 'collect_sources', return_value=([live / 'state.json'], [])), \
             patch.object(backup.clean, 'sql', return_value='1024'), \
             patch.object(backup.shutil, 'disk_usage', return_value=type('Space', (), {'free': free})), \
             patch.object(backup.clean, 'compose', side_effect=compose), \
             patch.object(backup.clean, 'container', return_value={'State': {'Running': False}}), \
             patch.object(backup.upgrade, 'snapshot', return_value={'counts': ['1','2','3']}), \
             patch.object(backup.upgrade, 'dump_databases', side_effect=dump), \
             patch.object(backup.clean, 'run', side_effect=run):
            if failure in ('stop', 'dump', 'export', 'resume'):
                with self.assertRaises(RuntimeError):
                    backup.create(live, output)
            elif failure == 'interrupt':
                with self.assertRaises(KeyboardInterrupt):
                    backup.create(live, output)
            elif free == 0:
                with self.assertRaisesRegex(ValueError, 'Not enough'):
                    backup.create(live, output)
            else:
                backup.create(live, output)
        return output, calls

    def test_success_snapshots_current_data_resumes_before_export_and_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls = self.exercise(Path(temp))
            self.assertLess(calls.index(('dump',)), calls.index(('compose', 'start', *backup.RUNTIME)))
            self.assertTrue(backup.verify(output)['complete'])
            self.assertFalse((output / 'resume-required.json').exists())

    def test_partial_stop_dump_failure_and_interrupt_always_resume_original_services(self):
        for failure in ('stop', 'dump', 'interrupt', 'export'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                output, calls = self.exercise(Path(temp), failure)
                self.assertIn(('compose', 'start', *backup.RUNTIME), calls)
                self.assertFalse(json.loads((output / 'manifest.json').read_text())['complete'])
                self.assertFalse((output / 'resume-required.json').exists())

    def test_insufficient_space_does_not_pause_any_service(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls = self.exercise(Path(temp), free=0)
            self.assertFalse(output.exists())
            self.assertEqual(calls, [('compose', 'config', '-q')])

    def test_failed_resume_keeps_recovery_marker_and_never_exports_images_or_claims_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls = self.exercise(Path(temp), 'resume')
            self.assertTrue((output / 'resume-required.json').is_file())
            self.assertFalse(json.loads((output / 'manifest.json').read_text())['complete'])
            self.assertFalse(any(call[:3] == ('docker', 'image', 'save') for call in calls))

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'existing'
            folder.mkdir()
            (folder / 'keep').write_text('previous')
            with patch.object(backup.clean, 'compose') as compose:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    backup.create(Path(temp) / 'server', folder)
            compose.assert_not_called()
            self.assertEqual((folder / 'keep').read_text(), 'previous')

    def test_unmounted_windows_drive_is_rejected_before_any_state_read(self):
        with patch.object(backup.os.path, 'ismount', return_value=False), \
             patch.object(backup.game.network, 'checked') as checked:
            with self.assertRaisesRegex(ValueError, 'mounted Windows'):
                backup.create('/unused', '/mnt/e/WoWForEver-work/reports/new')
            checked.assert_not_called()


class BackupFinalizeTests(unittest.TestCase):
    def test_finalization_reuses_existing_hashes_and_never_calls_docker_or_sql(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'backup'
            manifest = bundle(folder)
            manifest['complete'] = False
            original = json.dumps(manifest)
            (folder / 'manifest.json').write_text(original)
            identities = {name: (backup.artifact(folder / name), (folder / name).stat().st_mtime_ns)
                          for name in manifest['artifacts']}
            with patch.object(backup.clean, 'run') as run, \
                 patch.object(backup.clean, 'compose') as compose, \
                 patch.object(backup.upgrade, 'dump_databases') as dump:
                backup.finalize(folder)
                backup.finalize(folder)
                run.assert_not_called()
                compose.assert_not_called()
                dump.assert_not_called()
            self.assertTrue(backup.verify(folder)['complete'])
            self.assertEqual((folder / 'manifest-before-finalize.json').read_text(), original)
            for name, identity in identities.items():
                self.assertEqual((backup.artifact(folder / name), (folder / name).stat().st_mtime_ns), identity)

    def test_oci_root_bundle_from_original_failed_check_can_be_finalized_without_resaving(self):
        from test_docker_archive_identity import SavedImage
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'backup'
            manifest = bundle(folder)
            saved = SavedImage()
            saved.write(folder / 'docker-images.tar', [saved.index])
            manifest.update(complete=False, images={'worldserver': {'id':saved.index['digest']}})
            manifest['artifacts']['docker-images.tar'] = backup.artifact(folder / 'docker-images.tar')
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            backup.finalize(folder)
            self.assertTrue(backup.verify(folder)['complete'])

    def test_corruption_partial_export_and_pending_resume_never_promote_a_failed_bundle(self):
        for reason in ('corrupt', 'partial', 'resume'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp) / 'backup'
                manifest = bundle(folder)
                manifest['complete'] = False
                if reason == 'corrupt':
                    with (folder / 'docker-images.tar').open('ab') as stream:
                        stream.write(b'changed')
                elif reason == 'partial':
                    del manifest['artifacts']['docker-images.tar']
                else:
                    (folder / 'resume-required.json').write_text('{}')
                original = json.dumps(manifest)
                (folder / 'manifest.json').write_text(original)
                with self.assertRaises(ValueError):
                    backup.finalize(folder)
                self.assertEqual((folder / 'manifest.json').read_text(), original)
                self.assertFalse((folder / 'manifest-before-finalize.json').exists())


if __name__ == '__main__':
    unittest.main()
