"""Map hotfix planning, bounded file installation and failure rollback."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import legion_activation as plan

spec=importlib.util.spec_from_file_location('map_activation',ROOT/'scripts/activate-legion-map.py')
activation=importlib.util.module_from_spec(spec);spec.loader.exec_module(activation)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_model_names_change_without_modifying_transforms_or_bounds(self):
        for flag in [0,1]:
            header=struct.pack('<BBI7f',flag,0,9,1,2,3,0,0,0,1)
            if flag:header+=struct.pack('<6f',0,0,0,4,4,4)
            name=b'FILE00F00001.xxx'
            source=b'VMAP_4.E'+struct.pack('<I',1)+header+struct.pack('<I',len(name))+name
            rewritten,count=plan.tile_names(source,{name.decode()+'.vmo'})
            expected=b'legion1220_'+name
            self.assertEqual(rewritten,b'VMAP_4.E'+struct.pack('<I',1)+header+struct.pack('<I',len(expected))+expected)
            self.assertEqual(count,1)
            with self.assertRaises(ValueError):plan.tile_names(source,set())
            with self.assertRaises(ValueError):plan.tile_names(source[:-1],{name.decode()+'.vmo'})

    def test_sql_does_not_replace_existing_records_and_uses_custom_build(self):
        values={name:0 for name in plan.MAP_COLUMNS};values.update(ID=1220,Directory='ForeverDalaran',MapName="own ' quote")
        text=plan.apply_sql(values,12345,98)
        self.assertIn('START TRANSACTION;',text);self.assertIn('VALUES (98,1,12345,1220,1,0)',text)
        self.assertNotIn('REPLACE',text);self.assertNotIn('DELETE',text)
        self.assertIn('CONVERT(X\'',text);self.assertNotIn("own ' quote",text)
        with self.assertRaises(ValueError):plan.apply_sql(values,12345,0x80000000)
        with self.assertRaises(ValueError):plan.sql_literal(float('nan'))

    def test_map_template_preserves_original_semantics_and_rejects_existing_id(self):
        from test_legion_map_record import fixture
        from legion_map_db2 import MapTable,add_map
        data=fixture();before=MapTable(data).semantic
        table_hash,values=plan.map_values(data)
        self.assertEqual(table_hash,0xbd84cd62)
        self.assertEqual(values['WdtFileDataID'],15730590);self.assertEqual(values['ZmpFileDataID'],0)
        self.assertEqual(values['InstanceType'],0);self.assertEqual(values['ExpansionID'],0)
        self.assertEqual(MapTable(data).semantic,before)
        self.assertEqual(set(values),set(plan.MAP_COLUMNS))
        with self.assertRaisesRegex(ValueError,'already exists'):plan.map_values(add_map(data,1220,15730590))

    def test_rollback_rescues_only_experimental_map_and_sends_removal_push(self):
        text=plan.rollback_sql(12345,98)
        self.assertIn('WHERE c.map=1220;',text)
        self.assertIn('ID=1220 AND VerifiedBuild=0',text)
        self.assertIn('Id=98 AND TableHash=12345 AND RecordId=1220',text)
        self.assertIn('COALESCE(MAX(Id),0)+1,1,12345,1220,2,0',text)
        self.assertNotIn('TRUNCATE',text)

    def test_stage_rejects_path_traversal_and_changed_geometry(self):
        source=self.root/'source';source.mkdir();file=source/'own';file.write_bytes(b'owned')
        report=dict(format='wowforever-legion-geometry-extraction-v1',geometry_probe_passed=True,errors=[],
                    map_id=1220,wdt_file_data_id=15730590,client_metadata_unchanged=True,
                    tile=dict(world_tile_x=33,world_tile_y=23,raw_maid_index=2135),
                    compiled_core_revision='91d49b230f89c3ab4719f5b2b2d1e70ed36613c4',
                    source_install_operation='own',files=[dict(path='own',bytes=5,sha256='a'*64)])
        (source/'report.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'changed'):plan.stage_geometry(source,self.root/'out')
        with self.assertRaises(ValueError):plan.safe_file(source,'../own')
        link=source/'link';link.symlink_to(file)
        with self.assertRaises(ValueError):plan.safe_file(source,'link')

    def test_spawn_is_from_a_verified_surface_without_claiming_safe_arrival(self):
        point=activation.select_point(dict(samples=[dict(x=-800,y=4500,height=735),dict(x=-790,y=4500,height=735)]))
        self.assertEqual(point['z'],737);self.assertFalse(point['player_spawn_verified'])
        with self.assertRaises(ValueError):activation.select_point(dict(samples=[]))

    def test_rollback_removes_only_journaled_files_and_preserves_existing_world(self):
        data=self.root/'data';(data/'maps').mkdir(parents=True);(data/'vmaps/1220').mkdir(parents=True)
        original=data/'maps/0000_33_23.map';original.write_bytes(b'old world')
        new=data/'maps/1220_33_23.map';new.write_bytes(b'new tile')
        folder=self.root/'backup';folder.mkdir();script=plan.rollback_sql(12345,98);(folder/'rollback.sql').write_text(script)
        journal=dict(phase='ready',data=str(data),files=[dict(path='maps/'+new.name,sha256=plan.sha(new))],
                     sql_attempted=True,rollback_sql_sha256=hashlib.sha256(script.encode()).hexdigest())
        with patch.object(activation,'data_dir',return_value=data),patch.object(activation,'compose') as compose,patch.object(activation,'sql') as sql:
            activation.rollback(folder,journal)
            sql.assert_called_once_with(script)
            self.assertEqual(compose.call_args_list[0].args,('stop','web','bnetserver','worldserver'))
            self.assertEqual(compose.call_args_list[-1].args,('start',*activation.SERVICES))
        self.assertFalse(new.exists());self.assertEqual(original.read_bytes(),b'old world')
        self.assertEqual(journal['phase'],'rolled_back')

    def test_rollback_refuses_to_remove_foreign_modified_file(self):
        data=self.root/'data';data.mkdir();(data/'changed').write_bytes(b'foreign')
        journal=dict(phase='ready',data=str(data),files=[dict(path='changed',sha256='a'*64)])
        with patch.object(activation,'data_dir',return_value=data),patch.object(activation,'compose') as compose:
            with self.assertRaisesRegex(ValueError,'changed'):activation.rollback(self.root,journal)
            compose.assert_not_called()
        self.assertEqual((data/'changed').read_bytes(),b'foreign')

    def test_preparation_failure_does_not_stop_server(self):
        source=self.root/'source';source.mkdir();(source/'report.json').write_text('{}')
        values={name:0 for name in plan.MAP_COLUMNS}
        fake=SimpleNamespace(stdout='mysql\nworldserver\nbnetserver\nweb\n')
        data=self.root/'data';(data/'dbc/ruRU').mkdir(parents=True);(data/'dbc/ruRU/Map.db2').write_bytes(b'own')
        backups=self.root/'backups';backups.mkdir()
        with patch.object(activation,'ACTIVE',backups/'active.json'),patch.object(activation,'BACKUPS',backups),\
             patch.object(activation,'compose',return_value=fake) as compose,\
             patch.object(activation,'ready',return_value='91d49b230f89 worldserver-daemon ready'),\
             patch.object(activation,'data_dir',return_value=data),\
             patch.object(activation,'preflight_client',return_value=(self.root,{})),\
             patch.object(plan,'map_values',return_value=(12345,values)),\
             patch.object(activation,'schema_and_ids',return_value=(98,99)),\
             patch.object(plan,'stage_geometry',side_effect=ValueError('fixture preparation failed')):
            with self.assertRaisesRegex(ValueError,'preparation failed'):activation.apply(self.root,source)
            self.assertFalse(any(x.args and x.args[0]=='stop' for x in compose.call_args_list))

    def test_sql_failure_after_stop_automatically_removes_new_geometry_and_restarts(self):
        source=self.root/'source';source.mkdir();(source/'report.json').write_text('{}')
        data=self.root/'data';(data/'dbc/ruRU').mkdir(parents=True);(data/'dbc/ruRU/Map.db2').write_bytes(b'own')
        (data/'maps').mkdir();(data/'maps/0000_33_23.map').write_bytes(b'existing world')
        client=self.root/'client';client.mkdir();(client/'.build.info').write_bytes(b'unchanged build')
        backups=self.root/'backups';backups.mkdir()
        values={name:0 for name in plan.MAP_COLUMNS}
        def stage(src,dst):
            (dst/'maps').mkdir(parents=True);p=dst/'maps/1220_33_23.map';p.write_bytes(b'owned geometry')
            return dict(files=[dict(path='maps/'+p.name,sha256=plan.sha(p),bytes=p.stat().st_size)],source_report_sha256='a'*64)
        fake=SimpleNamespace(stdout='mysql\nworldserver\nbnetserver\nweb\n')
        with patch.object(activation,'ACTIVE',backups/'active.json'),patch.object(activation,'BACKUPS',backups),\
             patch.object(activation,'compose',return_value=fake) as compose,\
             patch.object(activation,'ready',return_value='91d49b230f89 worldserver-daemon ready'),\
             patch.object(activation,'world_logs',return_value='owned failure log'),\
             patch.object(activation,'data_dir',return_value=data),\
             patch.object(activation,'preflight_client',return_value=(client,dict(build_info_sha256=plan.sha(client/'.build.info')))),\
             patch.object(plan,'map_values',return_value=(12345,values)),\
             patch.object(activation,'schema_and_ids',return_value=(98,99)),\
             patch.object(plan,'stage_geometry',side_effect=stage),\
             patch.object(activation,'probe',return_value=dict(samples=[dict(x=-800,y=4500,height=735)])),\
             patch.object(activation,'dump'),\
             patch.object(activation,'sql',side_effect=[ValueError('owned SQL failure'),'']) as sql:
            with self.assertRaisesRegex(ValueError,'owned SQL failure'):activation.apply(client,source)
            self.assertEqual(sql.call_count,2)
            self.assertTrue(any(x.args==('start',*activation.SERVICES) for x in compose.call_args_list))
            _,journal=activation.active();self.assertEqual(journal['phase'],'rolled_back')
        self.assertFalse((data/'maps/1220_33_23.map').exists())
        self.assertEqual((data/'maps/0000_33_23.map').read_bytes(),b'existing world')
        self.assertEqual((client/'.build.info').read_bytes(),b'unchanged build')
