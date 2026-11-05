import hashlib
import importlib.util
import io
import json
import base64
from pathlib import Path
import sys
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import clean_game_tables as tables

spec = importlib.util.spec_from_file_location('table_fixture_store', ROOT / 'scripts/update-casc-sandbox.py')
storelib = importlib.util.module_from_spec(spec); spec.loader.exec_module(storelib)
lab = storelib.lab
BODY = b'Level\tMultiplier\r\n0\t1\r\n1\t1.25\r\n'


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def silent(*args, **kwargs):
    pass


class CleanGameTableTests(unittest.TestCase):
    def make_source(self, root):
        with patch.object(lab, 'PRODUCT', 'wowf'), patch.object(lab, 'BASE_ID', tables.FILE_ID), \
                patch.object(lab, 'BASE_TEXT', BODY):
            info = lab.write_store(root)
        return info

    def test_recover_reads_actual_synthetic_wowf_root_encoding_and_idx_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'
            info = self.make_source(source)
            before = snapshot(source)
            with patch.object(tables, 'download_matching_copy') as download:
                body, report = tables.recover(source, info['build_key'], silent)
            self.assertEqual(body, BODY)
            self.assertEqual(report['source'], 'current-client-local-encoding')
            self.assertEqual(report['selected_profile']['ckey'], hashlib.md5(BODY).hexdigest())
            self.assertEqual(report['rows'], 2)
            download.assert_not_called()
            self.assertEqual(snapshot(source), before)

    def test_duplicate_placeholders_including_encoding_and_root_do_not_block_readonly_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; info = self.make_source(source)
            original = storelib.Store(source, synthetic_only=False, product='wowf')
            for number, bucket in original.buckets.items():
                records = list(bucket['records'])
                records.extend(entry[:9] + bytes(5) + struct.pack('<I', 30) for entry in bucket['records'])
                path = source / 'Data/data' / f'{number:02x}00000001.idx'
                path.write_bytes(storelib.write_index(number, records, bucket['bits'], bucket['segment']))
            before = snapshot(source)
            # Existing experimental mutation paths retain strict conflict handling.
            with self.assertRaisesRegex(ValueError, 'Conflicting local EKey prefixes'):
                storelib.Store(source, synthetic_only=False, product='wowf')
            readonly = tables.open_store(source)
            self.assertGreater(len(readonly.alternate_entries), 1)
            ckey, ekey = readonly.values['encoding'].split()[:2]
            readonly.read(bytes.fromhex(ekey), bytes.fromhex(ckey))
            with patch.object(tables, 'download_matching_copy') as download:
                body, report = tables.recover(source, info['build_key'], silent)
            self.assertEqual(body, BODY)
            self.assertEqual(report['source'], 'current-client-local-encoding')
            self.assertEqual(snapshot(source), before)
            download.assert_not_called()

    def test_duplicate_prefix_with_wrong_full_ekey_is_rejected_before_valid_location_is_used(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; info = self.make_source(source)
            original = storelib.Store(source, synthetic_only=False, product='wowf')
            good = lab.asset(BODY)
            wrong = lab.asset(b'x' * len(BODY))
            data_path = source / 'Data/data/data.000'
            raw = bytearray(data_path.read_bytes())
            correct = lab.storage_record(good, len(raw))
            alternative = good['ekey'][:9] + len(raw).to_bytes(5, 'big') + struct.pack('<I', len(correct))
            # The synthetic table is the first record. Replace it with a valid
            # BLTE for a different full EKey, while retaining the old IDX prefix.
            bad_first = lab.storage_record(wrong, 0)
            self.assertEqual(len(bad_first), len(correct))
            raw[:len(bad_first)] = bad_first
            raw.extend(correct)
            data_path.write_bytes(raw)
            number = lab.bucket(good['ekey'])
            bucket = original.buckets[number]
            index = source / 'Data/data' / f'{number:02x}00000001.idx'
            index.write_bytes(storelib.write_index(number, bucket['records'] + [alternative], bucket['bits'], bucket['segment']))
            before = snapshot(source)
            with patch.object(tables, 'download_matching_copy') as download:
                body, _ = tables.recover(source, info['build_key'], silent)
            self.assertEqual(body, BODY)
            self.assertEqual(snapshot(source), before)
            download.assert_not_called()

    def test_all_invalid_duplicate_locations_fail_without_accepting_any_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; self.make_source(source)
            original = storelib.Store(source, synthetic_only=False, product='wowf')
            key = lab.asset(BODY)['ekey']
            entry = original.entries[key[:9]]
            number = lab.bucket(key); bucket = original.buckets[number]
            records = [row for row in bucket['records'] if row != entry]
            records.extend([key[:9] + bytes(5) + struct.pack('<I', 30),
                            key[:9] + (1).to_bytes(5, 'big') + struct.pack('<I', 30)])
            path = source / 'Data/data' / f'{number:02x}00000001.idx'
            path.write_bytes(storelib.write_index(number, records, bucket['bits'], bucket['segment']))
            before = snapshot(source)
            with self.assertRaisesRegex(ValueError, 'No verified local location for EKey'):
                tables.open_store(source).read(key, hashlib.md5(BODY).digest())
            self.assertEqual(snapshot(source), before)

    def offline_store(self, source):
        store = tables.open_store(source)
        key = lab.asset(BODY)['ekey'][:9]
        del store.entries[key]
        return store

    def test_public_copy_is_accepted_only_when_hash_is_in_current_root(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; info = self.make_source(source)
            store = self.offline_store(source)
            before = snapshot(source)
            matching = dict(tables.MATCHING_COPY, ckey=hashlib.md5(BODY).hexdigest())
            with patch.object(tables, 'open_store', return_value=store), patch.object(tables, 'MATCHING_COPY', matching), \
                    patch.object(tables, 'download_matching_copy', return_value=BODY) as download:
                body, report = tables.recover(source, info['build_key'], silent)
            self.assertEqual(body, BODY)
            self.assertEqual(report['source'], 'content-matched-public-copy')
            download.assert_called_once()
            self.assertEqual(snapshot(source), before)

    def test_another_builds_table_is_rejected_before_any_network_request(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; info = self.make_source(source)
            store = self.offline_store(source)
            with patch.object(tables, 'open_store', return_value=store), patch.object(tables, 'download_matching_copy') as download:
                with self.assertRaisesRegex(ValueError, 'does not match this client ROOT'):
                    tables.recover(source, info['build_key'], silent)
                download.assert_not_called()

    def test_wrong_download_content_rejected_despite_claimed_matching_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; info = self.make_source(source)
            store = self.offline_store(source)
            matching = dict(tables.MATCHING_COPY, ckey=hashlib.md5(BODY).hexdigest())
            with patch.object(tables, 'open_store', return_value=store), patch.object(tables, 'MATCHING_COPY', matching), \
                    patch.object(tables, 'download_matching_copy', return_value=BODY + b'changed'):
                with self.assertRaisesRegex(ValueError, 'does not match the current client ROOT'):
                    tables.recover(source, info['build_key'], silent)

    def test_download_is_limited_and_checksum_verified(self):
        matching = dict(tables.MATCHING_COPY, sha256=hashlib.sha256(BODY).hexdigest())
        with patch.object(tables, 'MATCHING_COPY', matching), \
                patch.object(tables.urllib.request, 'urlopen', return_value=io.BytesIO(BODY)):
            self.assertEqual(tables.download_matching_copy(), BODY)
        with patch.object(tables.urllib.request, 'urlopen', return_value=io.BytesIO(BODY)):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                tables.download_matching_copy()

    def test_changed_client_build_stops_before_recovery_or_download(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'client'; self.make_source(source)
            with patch.object(tables, 'download_matching_copy') as download:
                with self.assertRaisesRegex(ValueError, 'build key changed'):
                    tables.recover(source, '0' * 32, silent)
                download.assert_not_called()

    def test_empty_malformed_or_nonfinite_tables_are_rejected(self):
        for bad in (b'', b'not a game table', b'Level\tMultiplier\n',
                    b'Level\tMultiplier\n0\t1\n2\t2', b'Level\tMultiplier\n0\t1\n1\tnan',
                    b'Level\tMultiplier\n0\t1\n1\t-1'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tables.validate_table(bad)

    def test_container_writer_rejects_changed_payload_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            message = dict(body=base64.b64encode(BODY).decode(), sha256='0' * 64)
            args = [sys.executable, '-c', tables.TABLE_WRITER, temp]
            wrong = subprocess.run(args, input=json.dumps(message), text=True, capture_output=True)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertEqual(list(root.iterdir()), [])
            message['sha256'] = hashlib.sha256(BODY).hexdigest()
            target = root / tables.NAME
            target.write_bytes(b'existing extracted file')
            existing = subprocess.run(args, input=json.dumps(message), text=True, capture_output=True)
            self.assertNotEqual(existing.returncode, 0)
            self.assertEqual(target.read_bytes(), b'existing extracted file')


if __name__ == '__main__':
    unittest.main()
