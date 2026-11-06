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


def manifest(entries, tag_kinds=(1, 2), regions=None):
    def mask(indices):
        return bytes(sum(0x80 >> (i % 8) for i in range(start, min(start + 8, len(entries))) if i in indices)
                     for start in range(0, len(entries), 8))
    if regions is None: regions = {'EU': list(range(len(entries)))}
    tags = [('Windows', tag_kinds[0], range(len(entries))), ('x86_64', tag_kinds[1], range(len(entries)))]
    tags += [(name, 4, indices) for name, indices in regions.items()]
    return (b'IN\x01\x10' + struct.pack('>HI', len(tags), len(entries)) +
            b''.join(name.encode() + b'\0' + struct.pack('>H', kind) + mask(indices) for name, kind, indices in tags) +
            b''.join(name.encode() + b'\0' + obj['ckey'] + struct.pack('>I', len(obj['content'])) for name, obj in entries))


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def source(directory, resident=True, names=('Wow.exe', 'wow_loader.dll'), tag_kinds=(1, 2), include_china=False):
    root = directory / 'owned'
    with patch.object(lab, 'PRODUCT', 'wowf'):
        lab.write_store(root)
    store = storelib.Store(root, synthetic_only=False, product='wowf')
    old_ck, old_ek = (bytes.fromhex(v) for v in store.values['encoding'].split()[:2])
    wow = lab.asset(b'MZ-owned-synthetic-wow-binary')
    loader = lab.asset(b'MZ-owned-synthetic-new-loader')
    china = lab.asset(b'MZ-owned-synthetic-China-binary')
    assets = [wow, loader] + ([china] if include_china else [])
    encoding = lab.asset(extend_encoding(store.read(old_ek, old_ck), assets))
    entries = [(names[0], wow), (names[1], loader)]
    regions = None
    if include_china:
        entries.insert(0, ('Wow.exe', china))
        regions = {'EU': [1, 2], 'CN': [0, 2], 'US': [1, 2], 'KR': [1, 2], 'TW': [1, 2]}
    install = lab.asset(manifest(entries, tag_kinds, regions))
    additions = [encoding, install] + (assets if resident else [])
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

    def test_named_platform_and_architecture_masks_ignore_numeric_category_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp), tag_kinds=(2, 1))
            before = snapshot(root)
            report = audit.audit(root, key)
            self.assertEqual(report['status'], 'manifest-verified')
            self.assertEqual(report['windows_install_entries'], 2)
            self.assertTrue(all(e['verified_local_preload_copy'] for e in report['bootstrap']))
            self.assertEqual(report['install_manifest']['tags'][0]['kind'], 2)
            self.assertEqual(snapshot(root), before)

    def test_missing_exact_wow_preserves_manifest_candidates_without_path_guessing(self):
        for names in (('_forever_/Wow.exe', '_forever_/wow_loader.dll'),
                      ('WowB.exe', 'wow_loader.dll'), ('Wow.exe', 'WOW.EXE')):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temp:
                root, key = source(Path(temp), names=names)
                before = snapshot(root)
                report = audit.audit(root, key)
                self.assertEqual(report['status'], 'cannot-complete-local-audit')
                self.assertIn('executable_candidates', report['detail'])
                self.assertEqual([e['path'] for e in report['install_manifest']['executable_candidates']], list(names))
                self.assertEqual(report['install_manifest']['windows_x64_entries'], 2)
                self.assertEqual(report['bootstrap'], [])
                self.assertFalse(report['activation_ready'])
                self.assertEqual(snapshot(root), before)

    def test_platform_masks_do_not_select_an_untagged_or_other_architecture_exe(self):
        obj = lab.asset(b'MZ-owned-fixture')
        data = b'IN\x01\x10' + struct.pack('>HI', 4, 3)
        data += b'Windows\0\x00\x02\x80OSX\0\x00\x02\x40'
        data += b'x86_64\0\x00\x01\x40x86\0\x00\x01\x80'
        data += b''.join(b'Wow.exe\0' + obj['ckey'] + struct.pack('>I', len(obj['content'])) for _ in range(3))
        parsed = audit.parse_install_manifest(data)
        self.assertEqual(audit.install_manifest(data), [])
        candidates = audit.manifest_diagnostics(parsed)['executable_candidates']
        self.assertEqual(len(candidates), 3)
        self.assertFalse(any(e['selected_windows_x64'] for e in candidates))
        self.assertEqual(candidates[2]['tags'], [])

    def test_candidate_diagnostics_are_bounded_but_include_total(self):
        obj = lab.asset(b'MZ-owned-fixture')
        parsed = audit.parse_install_manifest(manifest([(f'Bin{i}.exe', obj) for i in range(70)]))
        details = audit.manifest_diagnostics(parsed)
        self.assertEqual(details['executable_candidates_total'], 70)
        self.assertEqual(len(details['executable_candidates']), 64)
        self.assertTrue(details['executable_candidates_truncated'])
        self.assertEqual(details['windows_x64_entries'], 70)

    def test_regional_wow_duplicates_choose_eu_or_cn_by_actual_masks(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp), include_china=True)
            before = snapshot(root)
            for region, matches_active in [('EU', True), ('CN', False), ('US', True), ('KR', True), ('TW', True)]:
                with self.subTest(region=region):
                    report = audit.audit(root, key, region=region)
                    self.assertEqual(report['status'], 'manifest-verified')
                    self.assertEqual(report['selected_install_tags'], ['Windows', 'x86_64', region])
                    self.assertEqual(report['audit_revision'], 3)
                    wow, loader = report['bootstrap']
                    self.assertEqual(wow['path'], 'Wow.exe')
                    self.assertEqual(wow['matches_active_file'], matches_active)
                    self.assertTrue(wow['verified_local_preload_copy'])
                    self.assertTrue(loader['verified_local_preload_copy'])
                    candidates = report['install_manifest']['executable_candidates']
                    selected_wow = [e for e in candidates if e['path'] == 'Wow.exe' and e['selected_for_region']]
                    self.assertEqual(len(selected_wow), 1)
                    self.assertEqual(selected_wow[0]['ckey'], wow['ckey'])
                    self.assertFalse(report['activated'])
            self.assertEqual(snapshot(root), before)

    def test_missing_region_does_not_fall_back_to_first_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root, key = source(Path(temp))
            before = snapshot(root)
            report = audit.audit(root, key, region='CN')
            self.assertEqual(report['status'], 'cannot-complete-local-audit')
            self.assertIn('region tag', report['detail'])
            self.assertEqual(report['bootstrap'], [])
            self.assertEqual(report['install_manifest']['requested_region'], 'CN')
            self.assertFalse(report['activation_ready'])
            self.assertEqual(snapshot(root), before)
            with self.assertRaisesRegex(ValueError, 'Unsupported install region'):
                audit.audit(root, key, region='AUTO')


if __name__ == '__main__': unittest.main()
