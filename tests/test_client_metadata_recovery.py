import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('metadata_recovery', SCRIPTS/'restore-client-copy-metadata.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class MetadataRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.copy = root/'source', root/'copy'
        for base in (self.source, self.copy):
            (base/'Data/data').mkdir(parents=True)
            (base/'.build.info').write_bytes(b'verified build')
            (base/'Data/data/data.000').write_bytes(b'unchanged archive')
            (base/'Data/data/shmem').write_bytes(b'state')
            for bucket in range(16):
                (base/'Data/data'/f'{bucket:02x}0000005c.idx').write_bytes(bytes([bucket])*80)
        self.marker = dict(format='wowforever-legion-client-copy-v1', source=str(self.source),
                           destination=str(self.copy), sha256={})
        for path in self.source.rglob('*'):
            if path.is_file():
                self.marker['sha256'][path.relative_to(self.source).as_posix()] = recovery.canary.sha(path.read_bytes())
        (self.copy/'legion-client-copy.json').write_text(json.dumps(self.marker))
        self.before_source = self.snapshot(self.source)

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}

    def damage(self):
        data = self.copy/'Data/data'
        (data/'000000005c.idx').unlink()
        (data/'0000000001.idx').write_bytes(b'empty replacement')
        (data/'RepairMarker.psv').write_bytes(b'needs repair')
        (data/'shmem').write_bytes(b'changed')

    def test_recovers_pruned_index_and_state_with_complete_backup(self):
        self.damage()
        before = self.snapshot(self.copy/'Data/data')
        backup = recovery.restore(self.copy)
        self.assertEqual(self.snapshot(backup/'before'), {k:v for k,v in before.items() if k != 'data.000'})
        self.assertEqual(self.snapshot(self.copy/'Data/data'), self.snapshot(self.source/'Data/data'))
        self.assertEqual(self.snapshot(self.source), self.before_source)
        self.assertIsNone(recovery.restore(self.copy))

    def test_rejects_archive_difference_before_writing(self):
        self.damage()
        (self.copy/'Data/data/data.000').write_bytes(b'other archive')
        before = self.snapshot(self.copy)
        with self.assertRaisesRegex(ValueError, 'Archive sizes'):
            recovery.restore(self.copy)
        self.assertEqual(self.snapshot(self.copy), before)

    def test_rejects_unverified_source_index(self):
        self.damage()
        (self.source/'Data/data/000000005c.idx').write_bytes(b'new source generation')
        before = self.snapshot(self.copy)
        with self.assertRaisesRegex(ValueError, 'Source index differs'):
            recovery.restore(self.copy)
        self.assertEqual(self.snapshot(self.copy), before)

    def test_failed_replacement_restores_all_previous_metadata(self):
        self.damage()
        before = self.snapshot(self.copy/'Data/data')
        replace = recovery.os.replace
        def fail_once(source, destination):
            if Path(source).parent.name == 'staged' and Path(source).name == '010000005c.idx':
                raise OSError('simulated storage failure')
            return replace(source, destination)
        with patch.object(recovery.os, 'replace', fail_once):
            with self.assertRaisesRegex(OSError, 'simulated storage'):
                recovery.restore(self.copy)
        self.assertEqual(self.snapshot(self.copy/'Data/data'), before)
        self.assertEqual(self.snapshot(self.source), self.before_source)
