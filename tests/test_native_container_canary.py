import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
import casc_native_container as native


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


experiment = load('empty_segment', 'casc-container-canary.py')
copier = load('native_fixture_copy', 'prepare-legion-client.py')


class NativeContainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.copy = self.root/'source', self.root/'copy'
        marker = native.lab.write_store(self.source)
        self.key = marker['build_key']
        folder = self.source/'Data/data'
        old_archive = (folder/'data.000').read_bytes()
        seed = bytearray(hashlib.md5(b'original synthetic metadata fixture seed').digest())
        seed[1] = 0
        slots, keys = bytearray(), []
        for bucket in range(16):
            for first in range(16):
                seed[0] = first
                if native.lab.bucket(seed) == (bucket-1) % 16:
                    key = bytes(seed)
                    break
            keys.append(key)
            slots.extend(native.service_header(key, 0, bucket*30))
        new_archive = bytearray(slots)
        relocated = {}
        for path in sorted(folder.glob('*.idx')):
            bucket = int(path.name[:2], 16)
            parsed = native.store.read_index(path.read_bytes(), bucket)
            rows = []
            for row in parsed['records']:
                previous = int.from_bytes(row[9:14], 'big')
                size = int.from_bytes(row[14:], 'little')
                if previous not in relocated:
                    record = old_archive[previous:previous+size]
                    position = len(new_archive)
                    new_archive.extend(native.lab.storage_record(
                        dict(ekey=record[:16][::-1], encoded=record[30:]), position))
                    relocated[previous] = position
                rows.append(row[:9]+relocated[previous].to_bytes(5, 'big')+row[14:])
            rows.append(keys[bucket][:9]+(bucket*30).to_bytes(5, 'big')+struct.pack('<I', 30))
            raw = bytearray(native.store.write_index(bucket, rows, parsed['bits'], parsed['segment']))
            high = low = 0
            for row in sorted(rows):
                high, low = native.lab.hashlittle2(row, high, low)
            struct.pack_into('<I', raw, 36, high)
            path.write_bytes(raw.ljust(65536, b'\0'))
        (folder/'data.000').write_bytes(new_archive)
        shared = bytearray(20480)
        struct.pack_into('<I', shared, 0, 5)
        struct.pack_into('<16I', shared, 0x110, *([1]*16))
        (folder/'shmem').write_bytes(shared)
        (self.source/'_classic_beta_').mkdir()
        (self.source/'_classic_beta_/WowB.exe').write_bytes(b'own fixture, no executable')
        copier.prepare(self.source, self.copy, self.key)
        self.before_source = self.snapshot(self.source)
        self.before_copy = self.snapshot(self.copy)
        self.controls = {native.lab.BASE_ID:dict(bytes=len(native.lab.BASE_TEXT), sha256=experiment.canary.sha(native.lab.BASE_TEXT))}
        self.row = dict(file_id=str(native.lab.BASE_ID), status='READ_OK', bytes=str(len(native.lab.BASE_TEXT)),
                        sha256=experiment.canary.sha(native.lab.BASE_TEXT), tag_mask='0', error='0')

    def snapshot(self, root):
        return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()
                and p.relative_to(root).parts[0] != 'casc-container-operations'}

    def apply(self):
        return experiment.apply(self.copy, 'unused-checker', self.controls, self.key, progress=lambda _:None)

    def test_metadata_only_apply_and_rollback_after_client_prunes_original_indexes(self):
        with patch.object(experiment.canary, 'native_check', return_value=[self.row]):
            journal = self.apply()
            self.assertEqual(len(journal['added']), 17)
            self.assertEqual((self.copy/'.build.info').read_bytes(), (self.source/'.build.info').read_bytes())
            self.assertEqual((self.copy/'Data/data/data.000').read_bytes(), (self.source/'Data/data/data.000').read_bytes())
            experiment.verify(self.copy, 'unused-checker')
            for path in (self.copy/'Data/data').glob('*00000001.idx'):
                path.unlink()
            (self.copy/'Data/data/data.001').write_bytes(b'client changed the experiment segment')
            (self.copy/'Data/data/RepairMarker.psv').write_bytes(b'client repair simulation')
            folder = experiment.rollback(self.copy)
            self.assertTrue(any(p.read_bytes() == b'client changed the experiment segment'
                                for p in folder.glob('after-*/data.001')))
            self.assertEqual(self.snapshot(self.copy), self.before_copy)
            self.assertEqual(self.snapshot(self.source), self.before_source)

    def test_post_write_failure_restores_original_metadata_and_archives(self):
        with patch.object(experiment.canary, 'native_check', side_effect=[[self.row], ValueError('postcheck failed')]):
            with self.assertRaisesRegex(ValueError, 'postcheck failed'):
                self.apply()
        self.assertEqual(self.snapshot(self.copy), self.before_copy)
        self.assertEqual(self.snapshot(self.source), self.before_source)

    def test_partial_candidate_write_failure_rolls_back(self):
        original_open = Path.open
        def fail_one(path, mode='r', *args, **kwargs):
            if path.name == '0200000002.idx' and mode == 'xb':
                raise OSError('simulated partial installation failure')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(experiment.canary, 'native_check', return_value=[self.row]), patch.object(Path, 'open', fail_one):
            with self.assertRaisesRegex(OSError, 'partial installation'):
                self.apply()
        self.assertEqual(self.snapshot(self.copy), self.before_copy)
        self.assertEqual(self.snapshot(self.source), self.before_source)

    def test_bad_prologue_refused_without_writing(self):
        path = self.copy/'Data/data/data.000'
        raw = bytearray(path.read_bytes())
        raw[29] ^= 1
        path.write_bytes(raw)
        before = self.snapshot(self.copy)
        with patch.object(experiment.canary, 'native_check', return_value=[self.row]):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                self.apply()
        self.assertEqual(self.snapshot(self.copy), before)

    def test_replay_existing_index_is_byte_exact(self):
        for path in (self.source/'Data/data').glob('*.idx'):
            raw = path.read_bytes()
            self.assertEqual(native.rewrite_index(raw, int(path.name[:2], 16)), raw)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'), 'Native CascLib checker required')
    def test_actual_casclib_reads_before_after_and_rollback(self):
        checker = os.environ['CASC_SANDBOX_CHECKER']
        result = experiment.apply(self.copy, checker, self.controls, self.key, progress=lambda _:None)
        self.assertEqual(result['native_before'], result['native_after'])
        experiment.verify(self.copy, checker)
        experiment.rollback(self.copy)
        experiment.canary.native_check(checker, self.copy, self.controls)
        self.assertEqual(self.snapshot(self.copy), self.before_copy)

    def test_rebound_new_segment_number_has_valid_all_slots(self):
        raw = (self.source/'Data/data/data.000').read_bytes()[:480]
        for number in (1, 3, 47, 48, 255):
            result = native.make_prologue(raw, 0, number)
            self.assertEqual(len(native.validate_prologue(result, number)), 16)
        with self.assertRaises(ValueError):
            native.make_prologue(raw, 0, 256)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'), 'Native CascLib checker required')
    def test_resource_upgrade_reads_new_file_and_rollback_restores_working_empty_segment(self):
        checker = os.environ['CASC_SANDBOX_CHECKER']
        experiment.apply(self.copy, checker, self.controls, self.key, progress=lambda _:None)
        before_resource = self.snapshot(self.copy)
        parent = experiment.active(self.copy)[0].name
        result = experiment.apply(self.copy, checker, self.controls, self.key, progress=lambda _:None, resource=True)
        self.assertEqual(result['mode'], 'resource')
        self.assertEqual(result['parent_operation'], parent)
        rows = experiment.verify(self.copy, checker)
        self.assertEqual({int(row['file_id']) for row in rows}, {native.lab.BASE_ID, experiment.canary.CANARY_ID})
        self.assertEqual(self.snapshot(self.source), self.before_source)
        # Simulate the original client failure: old IDX are pruned and repair state changes.
        for path in (self.copy/'Data/data').glob('*00000002.idx'):
            path.unlink()
        (self.copy/'Data/data/RepairMarker.psv').write_bytes(b'needs repair')
        experiment.rollback(self.copy)
        self.assertEqual(experiment.active(self.copy)[0].name, parent)
        self.assertEqual(self.snapshot(self.copy), before_resource)
        experiment.verify(self.copy, checker)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'), 'Native CascLib checker required')
    def test_resource_postcheck_failure_restores_parent_build_and_metadata(self):
        checker = os.environ['CASC_SANDBOX_CHECKER']
        experiment.apply(self.copy, checker, self.controls, self.key, progress=lambda _:None)
        before_resource = self.snapshot(self.copy)
        original_check = experiment.canary.native_check
        def reject_resource(checker, client, expected):
            if experiment.canary.CANARY_ID in expected:
                raise ValueError('resource postcheck failed')
            return original_check(checker, client, expected)
        with patch.object(experiment.canary, 'native_check', reject_resource):
            with self.assertRaisesRegex(ValueError, 'resource postcheck failed'):
                experiment.apply(self.copy, checker, self.controls, self.key, progress=lambda _:None, resource=True)
        self.assertEqual(self.snapshot(self.copy), before_resource)
        experiment.verify(self.copy, checker)

    def test_resource_upgrade_requires_installed_empty_segment_before_writes(self):
        with self.assertRaises(FileNotFoundError):
            experiment.apply(self.copy, 'unused-checker', self.controls, self.key, progress=lambda _:None, resource=True)
        self.assertEqual(self.snapshot(self.copy), self.before_copy)

    def test_observed_native_service_header_checksum_regressions(self):
        # Metadata values from the supplied, working container. No asset bodies.
        references = [
            ('0900a9ed876c985bf300000000000000', 0, 0, 'ed16645df4bee912'),
            ('0600a9ed876c985bf300000000000000', 0, 30, 'a44163b289783ca4'),
            ('0401001ab35f5c13c47c3673bf633f14', 1, 0, '91e0e8b2a5b9bd99'),
        ]
        for key, segment, offset, expected in references:
            self.assertEqual(native.service_header(bytes.fromhex(key), segment, offset)[22:].hex(), expected)

    def test_native_payload_framing_preserves_encoded_body(self):
        obj = native.lab.asset(b'own payload fixture')
        for segment in (0, 1, 2, 3, 48, 49):
            for offset in (480, 481, 510, 511):
                record = native.storage_record(obj, segment, offset)
                self.assertEqual(record[30:], obj['encoded'])
                self.assertEqual(struct.unpack_from('<IH', record, 16), (len(record), 0))
                self.assertEqual(struct.unpack_from('<I', record, 22)[0], native.lab.hashlittle(record[:22], 0x3D6BE971))
