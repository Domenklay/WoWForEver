import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_clean_advancement import fixture

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('progress_transition',ROOT/'scripts/upgrade-clean-gameplay.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)

class TransitionTests(unittest.TestCase):
    def state(self,root):
        state,model=fixture(root)
        state['advancement']=dict(version='1.11.0',protocol=3,source_sha256='b'*64,backup=str(root/'advancement/aaaaaaaaaaaa/install.json'))
        state['gameplay']=dict(version=1,source_sha256='c'*64,encyclopedia=t.game.BOOK_VERSION,scaling=t.game.SCALING_VERSION,backup=state['advancement']['backup'])
        t.clean.save(state)
        return state,model

    def test_only_the_ready_known_generation_can_enter_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,model=self.state(root)
            t.check_before(state,model)
            wrong=copy.deepcopy(state);wrong['advancement']['version']='1.12.0'
            with self.assertRaises(ValueError):t.check_before(wrong,model)
            (root/t.MARKER).write_text('{}')
            with self.assertRaises(ValueError):t.check_before(state,model)

    def test_failed_candidate_build_never_stops_or_changes_the_live_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,_=self.state(root)
            before=(root/'compose.private.json').read_bytes()
            with patch.object(t.game,'check_image'),patch.object(t.adv,'image'),patch.object(t.game,'wait_module'),patch.object(t.game,'build',side_effect=RuntimeError('build failed')),patch.object(t.clean,'compose') as compose:
                with self.assertRaises(RuntimeError):t.prepare(root,root/'backup',2)
            compose.assert_not_called();self.assertEqual(before,(root/'compose.private.json').read_bytes())
            self.assertEqual(t.clean.load_state(root/'state.json'),state)

    def test_rollback_restores_only_runtime_files_and_never_imports_old_sql(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,model=self.state(root);directory=root/'advancement/abcdef123456';directory.mkdir(parents=True)
            record=dict(phase='active',root=str(root),directory=str(directory),before=state,compose_before=json.dumps(model),control_before='original controller',previous_running=['worldserver','bnetserver','web'])
            with patch.object(t.game,'check_image'),patch.object(t.adv,'image'),patch.object(t.game,'wait_module'),patch.object(t.clean,'compose') as compose,patch.object(t.clean,'sql') as sql:
                t.rollback(root,record)
            sql.assert_not_called();self.assertEqual(json.loads((root/'compose.private.json').read_text()),model)
            self.assertEqual((root/'server.sh').read_text(),'original controller')
            self.assertEqual(t.clean.load_state(root/'state.json'),state)
            self.assertTrue(any('up' in c.args for c in compose.call_args_list))

    def test_cancelling_a_prepared_candidate_never_stops_the_live_server(self):
        with patch.object(t.clean,'compose') as compose,patch.object(t.clean,'sql') as sql:
            t.rollback(Path('/unused'),{'phase':'prepared'})
        compose.assert_not_called();sql.assert_not_called()

    def test_apply_refuses_stale_state_and_failed_trial_before_any_file_or_sql_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,_=self.state(root)
            record=dict(before=state,directory=str(root/'advancement/abcdef123456'),phase='prepared',trial={'services_verified':False,'cleanup_verified':True})
            with patch.object(t.clean,'compose') as compose,patch.object(t.clean,'sql') as sql:
                with self.assertRaises(ValueError):t.apply(root,record)
            compose.assert_not_called();sql.assert_not_called()

    def test_apply_adds_only_preferences_and_retains_all_other_services_and_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,model=self.state(root);directory=root/'advancement/abcdef123456';directory.mkdir(parents=True)
            original=(root/'compose.private.json').read_text();(root/'server.sh').write_text('old controller')
            record=dict(format=t.FORMAT,phase='prepared',root=str(root),directory=str(directory),before=state,
                        compose_before=original,control_before='old controller',trial={'services_verified':True,'cleanup_verified':True},
                        source_sha256=t.game.source_id(),advancement_sha256=t.adv.source_id(),candidate='sha256:'+'a'*64,candidate_tag='candidate')
            sql_calls=[]
            def sql(state,body):
                sql_calls.append(body);return '0' if 'SUM(DATA_LENGTH' in body else ''
            with patch.object(t.adv,'image',return_value={'Id':record['candidate']}),patch.object(t.game,'check_image'),patch.object(t.game,'wait_module'),patch.object(t.upgrade,'stop_running',return_value=['worldserver','bnetserver','web']),patch.object(t.clean,'compose'),patch.object(t.clean,'container',return_value={'State':{'Running':False}}),patch.object(t.upgrade,'snapshot',return_value={'counts':[1,2,3]}),patch.object(t,'fingerprints',return_value={'module':'1234'}),patch.object(t.upgrade,'dump_databases',return_value='a'*64),patch.object(t.clean,'sql',side_effect=sql),patch.object(t.shutil,'disk_usage',return_value=SimpleNamespace(free=10**12)):
                t.apply(root,record)
            current=json.loads((root/'compose.private.json').read_text())
            for service in ('mysql','bnetserver','web'):self.assertEqual(current['services'][service],model['services'][service])
            old_world=copy.deepcopy(model['services']['worldserver']);old_world['image']='candidate'
            self.assertEqual(current['services']['worldserver'],old_world)
            self.assertEqual(len(sql_calls),2);self.assertIn('CREATE TABLE IF NOT EXISTS forever_advancement_preferences',sql_calls[1])
            self.assertNotIn('DROP ',sql_calls[1]);self.assertNotIn('DELETE ',sql_calls[1])
            self.assertEqual(t.clean.load_state(root/'state.json')['advancement']['version'],'1.12.0')
            self.assertFalse((root/t.MARKER).exists())
