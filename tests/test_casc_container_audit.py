import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('container_audit', SCRIPTS/'audit-casc-container.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ContainerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = self.root/'client'
        self.folder = self.client/'Data/data'
        self.folder.mkdir(parents=True)
        shared = bytearray(20480)
        struct.pack_into('<I', shared, 0, 5)
        struct.pack_into('<16I', shared, 0x110, *([7]*16))
        (self.folder/'shmem').write_bytes(shared)
        headers = bytearray()
        for bucket in range(16):
            key = hashlib.md5(f'own metadata fixture {bucket}'.encode()).digest()
            headers.extend(key[::-1]+struct.pack('<IH', 30, 1)+bytes(8))
            row = key[:9]+(bucket*30).to_bytes(5, 'big')+struct.pack('<I', 30)
            (self.folder/f'{bucket:02x}00000007.idx').write_bytes(
                audit.store.write_index(bucket, [row], 30, 0))
        (self.folder/'data.000').write_bytes(headers+b'own test body; must not be included')
        self.package = self.client/'reports/metadata.zip'

    def test_collection_preserves_source_and_includes_only_header_slots(self):
        before = {p.name:p.read_bytes() for p in self.folder.iterdir()}
        audit.collect(self.client, self.package)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()}, before)
        with zipfile.ZipFile(self.package) as package:
            self.assertFalse(any(n.endswith('data.000') for n in package.namelist()))
            self.assertNotIn(b'own test body', package.read('segment-headers.json'))
        report = audit.analyze(self.package)
        self.assertTrue(report['complete_16_buckets'])
        self.assertFalse(report['client_runtime_compatibility_proven'])
        for index in report['indexes']:
            self.assertEqual(len(index['zero_payload_records']), 1)
            self.assertTrue(index['zero_payload_records'][0]['sampled_header_matches'])

    def test_rejects_body_bytes_in_header_area_without_creating_package(self):
        path = self.folder/'data.000'
        raw = bytearray(path.read_bytes())
        struct.pack_into('<H', raw, 20, 0)
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Unexpected segment header slot'):
            audit.collect(self.client, self.package)
        self.assertFalse(self.package.exists())

    def test_rejects_unexpected_package_member(self):
        audit.collect(self.client, self.package)
        with zipfile.ZipFile(self.package, 'a') as package:
            package.writestr('../../unexpected', b'do not extract')
        with self.assertRaisesRegex(ValueError, 'Unexpected metadata member'):
            audit.analyze(self.package)

    def test_real_client_apply_is_paused_before_any_access(self):
        path = self.root/'nonexistent client'
        run = subprocess.run([sys.executable, str(SCRIPTS/'casc-copy-canary.py'), 'apply', str(path)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn('apply paused', run.stderr)
        self.assertFalse(path.exists())
