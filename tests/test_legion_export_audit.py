"""Synthetic native files only: no Blizzard client assets in these fixtures."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import json
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('legion_audit', Path(__file__).resolve().parents[1] / 'scripts/audit-legion-export.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def chunk(name, data):
    return name[::-1] + struct.pack('<I', len(data)) + data


class ExportAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        version = chunk(b'MVER', struct.pack('<I', 18))
        (self.root / 'test.wdt').write_bytes(version + chunk(b'MPHD', bytes(32)) + chunk(b'MAIN', bytes(32768)))
        (self.root / 'test_21_32.adt').write_bytes(version + chunk(b'MCNK', bytes(128)))
        for suffix in ('tex0', 'obj0'):
            (self.root / f'test_21_32_{suffix}.adt').write_bytes(version)
        (self.root / 'test.blp').write_bytes(b'BLP2' + bytes(20))

    def test_inventory_and_fingerprint(self):
        result = audit.audit(self.root, 'synthetic')
        self.assertEqual(result['root_terrain_tiles'], 1)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])
        for row in result['files']:
            self.assertEqual(len(row['sha256']), 64)
        self.assertFalse(result['build_and_map_independently_verified'])

    def test_truncated_chunk_rejected(self):
        (self.root / 'test.wdt').write_bytes(b'REVM' + struct.pack('<I', 100) + b'\0')
        result = audit.audit(self.root, 'synthetic')
        self.assertIn('bounds', result['errors'][0]['error'])

    def test_incomplete_terrain_wdt_rejected(self):
        (self.root / 'test.wdt').write_bytes(chunk(b'MVER', struct.pack('<I', 18)))
        self.assertIn('missing chunks', audit.audit(self.root, 'synthetic')['errors'][0]['error'])

    def test_missing_tile_companion_reported(self):
        (self.root / 'test_21_32_obj0.adt').unlink()
        self.assertTrue(any('companion' in w for w in audit.audit(self.root, 'synthetic')['warnings']))

    def test_model_dependency_warnings(self):
        (self.root / 'model.m2').write_bytes(b'MD21' + bytes(8))
        root_wmo = chunk(b'MVER', struct.pack('<I', 17)) + chunk(b'MOHD', bytes(64)) + chunk(b'GFID', struct.pack('<I', 123))
        (self.root / 'building.wmo').write_bytes(root_wmo)
        result = audit.audit(self.root, 'synthetic')
        self.assertTrue(any('SKIN' in w for w in result['warnings']))
        self.assertTrue(any('MOGP' in w for w in result['warnings']))
        (self.root / 'model00.skin').write_bytes(b'SKIN' + bytes(8))
        (self.root / 'building_000.wmo').write_bytes(chunk(b'MVER', struct.pack('<I',17)) + chunk(b'MOGP', bytes(68)))
        result = audit.audit(self.root, 'synthetic')
        self.assertEqual(result['wmo_group_files'], 1)
        self.assertEqual(result['warnings'], [])

    def test_cli_creates_report_directory(self):
        with tempfile.TemporaryDirectory() as reports:
            out = Path(reports) / 'nested' / 'reports' / 'manifest.json'
            result = subprocess.run([sys.executable, str(Path(audit.__file__)), str(self.root), '--output', str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(out.read_text())['root_terrain_tiles'], 1)

    def test_symlinks_not_read(self):
        (self.root / 'external.wdt').symlink_to('/does/not/exist')
        self.assertEqual(audit.audit(self.root, 'synthetic')['errors'], [])


if __name__ == '__main__':
    unittest.main()
