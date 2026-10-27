"""Packaging tests use synthetic bytes, never game assets."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('package_sample', Path(__file__).resolve().parents[1] / 'scripts/package-legion-sample.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'exports'
        self.root.mkdir()
        self.manifest = self.home / 'reports' / 'manifest.json'
        self.manifest.parent.mkdir()
        self.output = self.home / 'samples' / 'sample.zip'
        paths = {
            'maps/test/test_23_33.adt': [],
            'maps/test/test_23_33_tex0.adt': [],
            'maps/test/test_23_33_obj0.adt': [],
            'maps/test/test.wdt': [],
            'models/dalaran2.wmo': ['MOHD', 'GFID'],
            'models/dalaran2_000.wmo': ['MOGP'],
            'models/test.m2': [], 'models/test00.skin': [], 'textures/test.blp': [],
        }
        rows = []
        for name, chunks in paths.items():
            data = ('synthetic: ' + name).encode()
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            rows.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'chunks': chunks})
        self.data = {'format': 'wowforever-legion-export-audit-v1', 'files': rows, 'errors': [], 'declared_build': 'synthetic'}
        self.manifest.write_text(json.dumps(self.data))

    def test_zip_checksums_and_originals_unchanged(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        index = module.package(self.root, self.manifest, self.output, '23_33')
        self.assertFalse(index['complete_zone_or_dependency_closure'])
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            for row in index['files']:
                payload = archive.read('data/' + row['path'])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), row['sha256'])
                self.assertTrue(row['matched_audit'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_changed_resource_rejected(self):
        path = self.root / 'maps/test/test_23_33.adt'
        data = path.read_bytes()
        path.write_bytes(b'X' + data[1:])
        with self.assertRaisesRegex(ValueError, 'SHA-256 changed'):
            module.package(self.root, self.manifest, self.output, '23_33')
        self.assertFalse(self.output.exists())

    def test_existing_output_preserved(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'keep this')
        with self.assertRaises(FileExistsError):
            module.package(self.root, self.manifest, self.output, '23_33')
        self.assertEqual(self.output.read_bytes(), b'keep this')

    def test_escape_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            module.safe_file(self.root.resolve(), '../reports/manifest.json')
        (self.root / 'escape').symlink_to(self.manifest)
        with self.assertRaises(ValueError):
            module.safe_file(self.root.resolve(), 'escape')

    def test_output_inside_export_rejected(self):
        with self.assertRaises(ValueError):
            module.package(self.root, self.manifest, self.root / 'sample.zip', '23_33')

    def test_optional_sidecar_hashed_separately(self):
        (self.root / 'models/test.manifest.json').write_text('{"fileDataID":123}')
        index = module.package(self.root, self.manifest, self.output, '23_33')
        row = next(row for row in index['files'] if row['path'] == 'models/test.manifest.json')
        self.assertFalse(row['matched_audit'])


if __name__ == '__main__':
    unittest.main()
