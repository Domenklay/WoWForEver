"""Native-shaped synthetic resources; no game assets in fixtures."""
import csv
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('zone_package', Path(__file__).parents[1]/'scripts/prepare-legion-zone.py')
zone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zone)


def chunk(tag, body, reverse=True):
    return (tag[::-1] if reverse else tag).encode()+struct.pack('<I', len(body))+body


class ZonePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home/'exports'
        self.root.mkdir()
        self.output = self.home/'packages/tile'
        self.catalog = self.home/'catalog.csv'
        self.names = {}
        self.mver = chunk('MVER', struct.pack('<I', 18))
        self.wmover = chunk('MVER', struct.pack('<I', 17))
        cells = bytearray(self.mver)
        for i in range(16):
            for j in range(16):
                cell = bytearray(128)
                struct.pack_into('<II', cell, 4, i, j)
                struct.pack_into('<3f', cell, 104, (32-33)*1600/3-i*100/3,
                                 (32-23)*1600/3-j*100/3, 0)
                cells.extend(chunk('MCNK', cell))
        self.write(100, 'maps/test/test_23_33.adt', cells)
        placement = bytearray(36)
        struct.pack_into('<I', placement, 0, 200)
        struct.pack_into('<H', placement, 34, 0x40)
        wmo = bytearray(64)
        struct.pack_into('<I', wmo, 0, 300)
        struct.pack_into('<H', wmo, 56, 8)
        self.write(101, 'maps/test/test_23_33_obj0.adt',
                   self.mver+chunk('MDDF', placement)+chunk('MODF', wmo))
        self.write(102, 'maps/test/test_23_33_tex0.adt',
                   self.mver+chunk('MDID', struct.pack('<I', 400))+chunk('MHID', struct.pack('<I', 401)))
        maid, main = bytearray(4096*32), bytearray(4096*8)
        struct.pack_into('<8I', maid, (33*64+23)*32, 100,101,0,102,0,0,0,0)
        struct.pack_into('<8I', maid, (23*64+33)*32, 999,998,0,997,0,0,0,0)
        struct.pack_into('<I', main, (33*64+23)*8, 1)
        struct.pack_into('<I', main, (23*64+33)*8, 1)
        self.write(900, 'maps/test/test.wdt', self.mver+chunk('MPHD', struct.pack('<8I', 0x200,0,0,0,0,0,0,0))+
                   chunk('MAIN', main)+chunk('MAID', maid))
        self.write(200, 'models/model.m2', chunk('MD21', b'own synthetic embedded header', False)+
                   chunk('SFID', struct.pack('<I', 210), False)+chunk('TXID', struct.pack('<I', 400), False)+
                   chunk('AFID', struct.pack('<HHI', 1,2,220), False))
        self.write(210, 'models/model00.skin', b'SKIN'+bytes(40))
        self.write(220, 'models/model.anim', b'own animation fixture')
        material = bytearray(64)
        struct.pack_into('<I', material, 12, 400)
        self.write(300, 'models/root.wmo', self.wmover+chunk('MOHD', bytes(64))+
                   chunk('MOMT', material)+chunk('GFID', struct.pack('<I', 301))+chunk('MODI', struct.pack('<I', 200)))
        self.write(301, 'models/root_000.wmo', self.wmover+chunk('MOGP', bytes(68)))
        self.write(400, 'textures/a.blp', b'BLP2'+bytes(64))
        self.write(401, 'textures/height.blp', b'BLP2'+bytes(64))
        (self.root/'models/model.manifest.json').write_text(json.dumps(dict(
            fileDataID=200, textures=[dict(fileDataID=400, file='../textures/a.blp')],
            skins=[dict(fileDataID=210, file='model00.skin')])))
        (self.root/'models/root.manifest.json').write_text(json.dumps(dict(
            fileDataID=300, groups=[dict(fileDataID=301, file='..\\root_000.wmo')])))
        self.save_catalog()

    def write(self, fid, relative, data):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.names[fid] = relative

    def save_catalog(self):
        with self.catalog.open('w', newline='') as stream:
            csv.writer(stream, delimiter=';', lineterminator='\n').writerows(sorted(self.names.items()))

    def run_package(self):
        return zone.prepare(self.root, self.output, catalog=self.catalog, progress=lambda _:None)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_axis_binary_dependencies_clipped_wdt_checksums_and_source_preserved(self):
        before = self.snapshot()
        report = self.run_package()
        self.assertTrue(report['known_reference_closure'])
        self.assertFalse(report['installable'])
        self.assertFalse(report['full_dependency_closure_proven'])
        self.assertEqual(report['tile']['root_file_data_id'], 100)
        self.assertEqual(report['tile']['raw_maid_index'], 33*64+23)
        self.assertNotIn(999, {row['file_data_id'] for row in report['references']})
        self.assertIn(220, {row['file_data_id'] for row in report['references']})
        with zipfile.ZipFile(self.output/'tile-candidate.zip') as archive:
            self.assertIsNone(archive.testzip())
            for row in report['files']:
                body = archive.read('data/'+row['path'])
                self.assertEqual(hashlib.sha256(body).hexdigest(), row['sha256'])
                self.assertEqual(hashlib.md5(body).hexdigest(), row['ckey'])
            wdt = dict(zone.chunks(archive.read('data/maps/test/test.wdt')))
            self.assertEqual(sum(bool(v[0]) for v in struct.iter_unpack('<II', wdt['MAIN'])), 1)
            self.assertEqual(struct.unpack_from('<I', wdt['MAID'], (33*64+23)*32)[0], 100)
            self.assertEqual(struct.unpack_from('<I', wdt['MAID'], (23*64+33)*32)[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_missing_binary_texture_is_explicit_even_if_other_textures_exist(self):
        (self.root/'textures/height.blp').unlink()
        report = self.run_package()
        self.assertFalse(report['known_reference_closure'])
        missing = {row['file_data_id']:row for row in report['missing_from_export']}
        self.assertIn(401, missing)
        self.assertIn('maps/test/test_23_33_tex0.adt', missing[401]['referenced_by'])

    def test_sidecar_cannot_hide_a_missing_binary_skin(self):
        path = self.root/'models/model.m2'
        data = path.read_bytes().replace(struct.pack('<I', 210), struct.pack('<I', 211))
        path.write_bytes(data)
        report = self.run_package()
        self.assertIn(211, {row['file_data_id'] for row in report['missing_from_export']})

    def test_unknown_decimal_export_names_supply_ids_without_catalog_entries(self):
        self.write(450, 'unknown/450.blp', b'BLP2'+bytes(64))
        p = self.root/'models/model.m2'
        p.write_bytes(p.read_bytes()+chunk('TXID', struct.pack('<I', 450), False))
        report = self.run_package()
        self.assertTrue(report['known_reference_closure'])
        self.assertIn('unknown/450.blp', {row['path'] for row in report['files']})

    def test_existing_output_and_symlinks_are_rejected(self):
        self.output.mkdir(parents=True)
        (self.output/'keep').write_bytes(b'existing result')
        with self.assertRaisesRegex(ValueError, 'NEW directory'):
            self.run_package()
        self.assertEqual((self.output/'keep').read_bytes(), b'existing result')
        (self.root/'linked.blp').symlink_to(self.root/'textures/a.blp')
        with self.assertRaisesRegex(ValueError, 'Linked export'):
            zone.Planner(self.root, self.catalog)

    def test_changed_source_after_graph_review_cleans_partial_package(self):
        original = zipfile.ZipFile.writestr
        changed = False
        def mutate(archive, name, data, *args, **kwargs):
            nonlocal changed
            result = original(archive, name, data, *args, **kwargs)
            if not changed:
                path = self.root/'models/model.m2'
                path.write_bytes(path.read_bytes()+b'changed after review')
                changed = True
            return result
        with patch.object(zipfile.ZipFile, 'writestr', mutate):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                self.run_package()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_coordinate_mismatch_refused_before_package_creation(self):
        p = self.root/'maps/test/test_23_33.adt'
        p.rename(p.with_name('test_33_23.adt'))
        with self.assertRaisesRegex(ValueError, 'coordinates disagree'):
            zone.prepare(self.root, self.output, tile='33_23', catalog=self.catalog, progress=lambda _:None)
        self.assertFalse(self.output.exists())

    def test_sidecar_virtual_directory_ambiguity_is_not_guessed(self):
        self.write(999, 'root_000.wmo', self.wmover+chunk('MOGP', bytes(68)))
        with self.assertRaisesRegex(ValueError, 'Ambiguous sidecar'):
            self.run_package()

    def test_conflicting_filedataid_sidecars_refused(self):
        p = self.root/'models/root.manifest.json'
        data = json.loads(p.read_text())
        data['fileDataID'] = 200
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'different contents'):
            self.run_package()

    def test_auxiliary_wdt_different_version_is_reported_as_coverage_limit(self):
        path = self.root/'maps/test/test.wdt'
        blocks = list(zone.chunks(path.read_bytes()))
        changed = []
        for tag, data in blocks:
            if tag == 'MPHD':
                data = bytearray(data)
                struct.pack_into('<I', data, 4, 500)
            changed.append(chunk(tag, data))
        path.write_bytes(b''.join(changed))
        self.write(500, 'maps/test/test_lgt.wdt', chunk('MVER', struct.pack('<I', 20)))
        self.save_catalog()
        report = self.run_package()
        self.assertEqual(report['errors'], [])
        self.assertTrue(any('auxiliary WDT v20' in value for value in report['coverage_limits']))
        self.assertIn('maps/test/test_lgt.wdt', {row['path'] for row in report['files']})
