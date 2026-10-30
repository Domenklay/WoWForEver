"""Exporter contract with owned bytes; no Blizzard assets or rendering claims."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zone_export', ROOT/'scripts/export-zone-package.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ZonePackageExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = self.root/'client'
        self.operation = self.client/'legion-resource-operations/owned'
        self.before = self.operation/'before'
        self.before.mkdir(parents=True)
        self.data = self.client/'Data/data'
        self.data.mkdir(parents=True)
        self.output = self.root/'package'
        header = 'Product!STRING:0|Version!STRING:0|Build Key!HEX:16\n'
        self.info_before = (header+'wow_classic_beta|1.60.1.70532|before\n').encode()
        self.info_after = (header+'wow_classic_beta|1.60.1.70532|after\n').encode()
        (self.operation/'before.build.info').write_bytes(self.info_before)
        (self.client/'.build.info').write_bytes(self.info_after)
        shmem = bytearray(20480)
        (self.before/'shmem').write_bytes(shmem)
        struct.pack_into('<16I', shmem, 0x110, *([2]*16))
        (self.data/'shmem').write_bytes(shmem)
        for folder in (self.data, self.before):
            (folder/'0000000001.idx').write_bytes(b'owned original index')
        (self.data/'0000000002.idx').write_bytes(b'owned new index')
        (self.data/'data.001').write_bytes(b'owned new segment')
        self.config = 'Data/config/aa/bb/aabb'+'0'*28
        target = self.client/self.config
        target.parent.mkdir(parents=True)
        target.write_bytes(b'owned configuration')
        self.journal = dict(
            format='wowforever-legion-resource-operation-v1', phase='verified', copy=str(self.client),
            before_info_sha256=exporter.sha(self.operation/'before.build.info'),
            after_info_sha256=exporter.sha(self.client/'.build.info'),
            before={p.name:exporter.sha(p) for p in self.before.iterdir()},
            added={name:dict(bytes=(self.data/name).stat().st_size,sha256=exporter.sha(self.data/name))
                   for name in ('0000000002.idx','data.001')}, generations=[2]*16,
            configuration=dict(path=self.config, created=True, sha256=exporter.sha(target)))
        self.save_journal()

    def save_journal(self):
        (self.operation/'operation.json').write_text(json.dumps(self.journal))

    def export(self, **kwargs):
        return exporter.export(self.client,self.operation,kwargs.pop('output',self.output),
                               'owned-zone','Owned zone','0.1.0',**kwargs)

    def test_exports_one_transaction_with_exact_baseline_and_experimental_default(self):
        result = self.export()
        self.assertEqual(result['status'],'experimental')
        self.assertFalse(result['client_render_verified'])
        self.assertFalse(result['server_ready'])
        self.assertEqual(result['client_version'],'1.60.1.70532')
        self.assertEqual(set(result['base_files']),{
            '.build.info','Data/data/shmem','Data/data/0000000001.idx'})
        changes = {row['path']:row for row in result['files']}
        self.assertEqual(set(changes),{'.build.info','Data/data/shmem','Data/data/0000000002.idx',
                                      'Data/data/data.001',self.config})
        self.assertIsNone(changes['Data/data/data.001']['before'])
        self.assertEqual(changes['.build.info']['before'],result['base_files']['.build.info'])
        for row in changes.values():
            self.assertEqual(exporter.sha(self.output/'payload'/row['path']),row['after'])
        self.assertEqual((self.client/'.build.info').read_bytes(),self.info_after)

    def test_validation_must_bind_exact_candidate_and_explicit_booleans(self):
        proof = self.root/'validation.json'
        value = dict(format='wowforever-zone-validation-v1',candidate_build_info_sha256='wrong',
                     client_render_verified=True,server_ready=True)
        proof.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'exact candidate'):
            self.export(validation=proof)
        self.assertFalse(self.output.exists())
        value['candidate_build_info_sha256'] = self.journal['after_info_sha256']
        value['server_ready'] = 'yes'
        proof.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'boolean'):
            self.export(validation=proof)
        value['server_ready'] = True
        proof.write_text(json.dumps(value))
        self.assertEqual(self.export(validation=proof)['status'],'verified')

    def test_changed_metadata_or_missing_backup_stops_before_export(self):
        (self.data/'0000000001.idx').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Existing native index changed'):
            self.export()
        (self.data/'0000000001.idx').write_bytes(b'owned original index')
        (self.before/'0000000001.idx').unlink()
        with self.assertRaisesRegex(ValueError,'Incomplete metadata backup'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_output_cannot_be_in_client_or_git_and_changed_payload_is_rejected(self):
        for output in (self.client/'package',ROOT/'content/packages/owned-test'):
            with self.assertRaises(ValueError):
                self.export(output=output)
            self.assertFalse(output.exists())
        (self.data/'data.001').write_bytes(b'changed segment')
        with self.assertRaisesRegex(ValueError,'Added file changed'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_config_key_must_match_content_directory(self):
        self.journal['configuration']['path'] = 'Data/config/cc/dd/aabb'+'0'*28
        self.save_journal()
        with self.assertRaisesRegex(ValueError,'directory does not match'):
            self.export()

    def test_payload_symlink_is_rejected(self):
        target = self.root/'linked-segment'
        (self.data/'data.001').rename(target)
        (self.data/'data.001').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Linked paths'):
            self.export()
