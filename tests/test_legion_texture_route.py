"""Read-only texture diagnosis with owned bytes and no game installation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('texture_route', ROOT/'scripts/audit-legion-texture-route.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TextureRouteTests(unittest.TestCase):
    def test_variant_coverage_distinguishes_content_keys_flags_and_locales(self):
        a = dict(locale=0x173f6, raw_flags=[0, 0x12000000, 4], ckey='11'*16)
        b = dict(locale=0x173f6, raw_flags=[1, 0x12000000, 4], ckey='22'*16)
        self.assertEqual(audit.variant_coverage([a,b], [a]), [b])
        self.assertEqual(audit.variant_coverage([a,b], [b,a]), [])
        self.assertEqual(audit.variant_coverage([a], [dict(a,locale=2)]), [a])
        self.assertEqual(audit.variant_coverage([a], [dict(a,ckey=b['ckey'])]), [a])

    def test_child_routes_require_same_row_not_just_a_private_name(self):
        from test_legion_tvfs_entry import fixture_directory
        store, obj, child, _ = fixture_directory()
        result = audit.child_routes(child['content'])
        self.assertEqual(len(result['pairs']), 1)
        self.assertFalse(result['pairs'][0]['same_vfs_row'])
        changed, _ = audit.canary.mirror_child(child['content'])
        result = audit.child_routes(changed)
        self.assertTrue(result['pairs'][0]['same_vfs_row'])
        parsed = audit.canary.storelib.tvfs.parse_tvfs(changed)
        self.assertEqual(result['pairs'][0]['ckey'], obj['ckey'].hex())
        self.assertEqual(result['table_layout']['path']['bytes'], len(parsed['tables']['path']))

    def test_complete_report_preserves_client_and_records_unproven_variant_gap(self):
        from test_legion_tvfs_entry import fixture_directory
        store, obj, _, _ = fixture_directory()
        store.values['encoding'] = store.values['vfs-root']
        store.values['root'] = 'aa'*16
        root = b'TSFM' + struct.pack('<5I', 24, 2, 3, 0, 0)
        for fid, flags, key in [(123086,0,obj['ckey']), (123086,1,b'x'*16), (15728640,0,obj['ckey'])]:
            root += struct.pack('<4IBI', 1, 0x173f6, flags, 0x12000000, 4, fid) + key
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp)/'client'
            (client/'Data/data').mkdir(parents=True)
            (client/'.build.info').write_bytes(b'owned build info')
            (client/'Data/data/shmem').write_bytes(b'owned metadata')
            journal = dict(phase='verified', after_info_sha256=hashlib.sha256(b'owned build info').hexdigest(),
                           tvfs_entry_canary=True, tvfs_layout_canary=True,
                           tvfs_canary_original_id=123086, tvfs_canary_new_id=15728640,
                           tvfs_canary_directories=[dict(directory='000173F600000000',build_config_key='vfs-2')])
            output = Path(tmp)/'reports/audit.json'
            before = {str(p.relative_to(client)):p.read_bytes() for p in client.rglob('*') if p.is_file()}
            with patch.object(audit.install.canary,'copy_identity',return_value=(client,None)), \
                 patch.object(audit.install,'operation',return_value=(Path('owned-operation'),journal)), \
                 patch.object(audit.canary.storelib,'Store',return_value=store), \
                 patch.object(audit,'Encoding',return_value=object()), \
                 patch.object(audit.root_audit,'read_content',side_effect=lambda s,e,k:root if k=='aa'*16 else b'BLP2owned'):
                result = audit.audit(client,output,lambda _:None)
                with self.assertRaisesRegex(ValueError,'NEW report'):
                    audit.audit(client,output,lambda _:None)
            after = {str(p.relative_to(client)):p.read_bytes() for p in client.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(result['native_profiles_missing_from_private_root'][0]['raw_flags'][0], 1)
            self.assertTrue(result['directories'][0]['top_level_reference_matches'])
            self.assertFalse(result['client_modified'])
            self.assertFalse(result['green_texture_cause_proven'])
            self.assertFalse(result['engine_selected_variant_known'])
            self.assertNotIn('hex', result['payloads'][0])

    def test_reapplying_layout_explains_it_is_already_active_before_any_changes(self):
        journal = dict(phase='verified', root_types_repaired=True, tvfs_entry_canary=True, tvfs_layout_canary=True)
        with patch.object(audit.install.canary,'copy_identity',return_value=(Path('/unused'),None)), \
             patch.object(audit.install,'operation',return_value=(Path('/unused-operation'),journal)), \
             patch.object(audit.install,'scan') as scan:
            with self.assertRaisesRegex(ValueError,'already active; nothing changed'):
                audit.canary.apply(Path('/unused'),Path('/unused-checker'),layout_only=True)
            scan.assert_not_called()
