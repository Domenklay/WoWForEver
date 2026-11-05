import hashlib
import importlib.util
import io
from pathlib import Path
import sys
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


if __name__ == '__main__':
    unittest.main()
