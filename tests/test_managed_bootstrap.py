import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('bootstrap_tests', ROOT / 'scripts/audit-managed-bootstrap.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


class Store:
    def __init__(self, keys):
        self.entries = {bytes.fromhex(k)[:9]: True for k in keys}
    def read(self, key, ckey):
        if key[:9] not in self.entries: raise ValueError('Missing local file')
        return b'fixture metadata'


def config():
    return {name: (bytes([i])*16).hex() + ' ' + (bytes([i+100])*16).hex() for i, name in enumerate(('encoding', 'install', 'download', 'size', 'root'), 1)}


class BootstrapTests(unittest.TestCase):
    def inspect(self, values, present):
        with patch.object(audit, 'Encoding') as encoding:
            encoding.return_value.rows.return_value = []
            return audit.inspect_bootstrap(values, Store(present))
    def test_verified_payloads_cannot_hide_a_missing_download_manifest(self):
        values = config(); keys = [v.split()[1] for k,v in values.items() if k != 'download']
        result = self.inspect(values, keys)
        self.assertFalse(result['bootstrap_complete'])
        self.assertEqual([r['name'] for r in result['missing_or_invalid']], ['download'])
        self.assertFalse(result['playable_verified'])
    def test_size_and_root_are_checked_separately_from_download_entries(self):
        values = config(); result = self.inspect(values, [values['encoding'].split()[1]])
        self.assertFalse(result['bootstrap_complete'])
        self.assertEqual({r['name'] for r in result['missing_or_invalid']}, {'install','download','size','root'})
    def test_duplicate_vfs_aliases_require_one_actual_object(self):
        values = config(); values['vfs-root'] = values['root']; values['vfs-1'] = values['root']
        result = self.inspect(values, [v.split()[1] for v in values.values()])
        self.assertTrue(result['bootstrap_complete'])
        self.assertEqual(result['distinct_checked_objects'], 5)
        self.assertEqual(result['declarations'], 7)
        self.assertFalse(result['full_asset_integrity_verified'])
    def test_invalid_manifest_paths_or_keys_cannot_be_silently_skipped(self):
        values = config(); values['download'] = '../outside'
        with self.assertRaises(ValueError): audit.declarations(values)


if __name__ == '__main__': unittest.main()
