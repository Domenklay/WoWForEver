import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from casc_manifest_update import extend_encoding


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


audit = module('preload_audit_test', 'audit-client-preload.py')
storelib = module('preload_fixture_store', 'update-casc-sandbox.py')
lab = storelib.lab


def manifest(entries):
    mask = bytes([sum(0x80 >> i for i in range(len(entries)))])
    return (b'IN\x01\x10' + struct.pack('>HI', 2, len(entries)) +
            b'Windows\0\x00\x01' + mask + b'x86_64\0\x00\x02' + mask +
            b''.join(name.encode() + b'\0' + obj['ckey'] + struct.pack('>I', len(obj['content'])) for name, obj in entries))


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def source(directory, resident=True):
    root = directory / 'owned'
    with patch.object(lab, 'PRODUCT', 'wowf'):
        lab.write_store(root)
    store = storelib.Store(root, synthetic_only=False, product='wowf')
    old_ck, old_ek = (bytes.fromhex(v) for v in store.values['encoding'].split()[:2])
    wow = lab.asset(b'MZ-owned-synthetic-wow-binary')
    loader = lab.asset(b'MZ-owned-synthetic-new-loader')
    encoding = lab.asset(extend_encoding(store.read(old_ek, old_ck), [wow, loader]))
    install = lab.asset(manifest([('Wow.exe', wow), ('wow_loader.dll', loader)]))
    additions = [encoding, install] + ([wow, loader] if resident else [])
    archive = bytearray((root / 'Data/data/data.000').read_bytes())
    records = {i: list(bucket['records']) for i, bucket in store.buckets.items()}
    for obj in additions:
        offset = len(archive)
        raw = lab.storage_record(obj, offset)
        archive.extend(raw)
        records[lab.bucket(obj['ekey'])].append(obj['ekey'][:9] + offset.to_bytes(5, 'big') + struct.pack('<I', len(raw)))
    (root / 'Data/data/data.000').write_bytes(archive)
    for i, bucket in store.buckets.items():
        (root / 'Data/data' / f'{i:02x}00000002.idx').write_bytes(storelib.write_index(i, records[i], bucket['bits'], bucket['segment']))
    config = (f'build-name = WOW-70707patch1.60.1_Retail\nbuild-uid = wowf\n'
              f'install = {install["ckey"].hex()} {install["ekey"].hex()}\n'
              f'encoding = {encoding["ckey"].hex()} {encoding["ekey"].hex()}\n').encode()
    key = hashlib.md5(config).hexdigest()
    path = root / 'Data/config' / key[:2] / key[2:4] / key
    path.parent.mkdir(parents=True)
    path.write_bytes(config)
    (root / '_forever_').mkdir()
    (root / '_forever_/Wow.exe').write_bytes(wow['content'])
    (root / '_forever_/wow_loader.dll').write_bytes(b'MZ-old-synthetic-loader')
    return root, key


class PreloadAuditTests(unittest.TestCase):
    def test_real_synthetic_idx_encoding_and_install_are_read_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp))
            before = snapshot(root)
            report = audit.audit(root, key)
            self.assertEqual(report['status'], 'manifest-verified')
            rows = {e['path']: e for e in report['bootstrap']}
            self.assertTrue(rows['Wow.exe']['matches_active_file'])
            self.assertFalse(rows['wow_loader.dll']['matches_active_file'])
            self.assertTrue(all(e['verified_local_preload_copy'] for e in rows.values()))
            self.assertTrue(report['comparison_only'])
            self.assertFalse(report['activated'])
            self.assertFalse(report['full_asset_integrity_verified'])
            self.assertEqual(snapshot(root), before)

    def test_preloaded_assets_do_not_imply_bootstrap_is_present(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp), resident=False)
            before = snapshot(root)
            report = audit.audit(root / '_forever_', key)
            self.assertEqual(report['status'], 'manifest-verified')
            self.assertTrue(all(not e['verified_local_preload_copy'] for e in report['bootstrap']))
            self.assertTrue(report['bootstrap'][0]['matches_active_file'])
            self.assertEqual(snapshot(root), before)

    def test_modified_config_and_incorrect_target_build_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp))
            with self.assertRaisesRegex(ValueError, 'requested'):
                audit.audit(root, key, 99999)
            path = root / 'Data/config' / key[:2] / key[2:4] / key
            path.write_bytes(path.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                audit.audit(root, key)

    def test_install_paths_and_malformed_binary_fields_are_refused(self):
        wow = lab.asset(b'MZ-owned-fixture')
        for path in ('../Wow.exe', 'C:\\Wow.exe', '\\\\host\\file', 'Wow.exe:ads', 'Wow.exe.'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit.install_manifest(manifest([(path, wow)]))
        data = manifest([('Wow.exe', wow)])
        for invalid in (data[:-1], data + b'extra', b'IN\x02\x10' + data[4:]):
            with self.assertRaises(ValueError): audit.install_manifest(invalid)

    def test_msb_tag_masks_exclude_the_other_platform_bootstrap(self):
        win = lab.asset(b'MZ-windows'); mac = lab.asset(b'owned-mac')
        data = b'IN\x01\x10' + struct.pack('>HI', 3, 2)
        data += b'Windows\0\x00\x01\x80OSX\0\x00\x01\x40x86_64\0\x00\x02\xc0'
        for obj in (win, mac):
            data += b'Wow.exe\0' + obj['ckey'] + struct.pack('>I', len(obj['content']))
        rows = audit.install_manifest(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ckey'], win['ckey'].hex())


if __name__ == '__main__': unittest.main()
