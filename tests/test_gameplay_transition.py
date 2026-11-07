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
        state['gameplay']=dict(version=1,source_sha256='c'*64,encyclopedia=t.game.BOOK_VERSION,scaling=t.ORIGINAL_SCALING_VERSION,backup=state['advancement']['backup'])
        t.clean.save(state)
        return state,model

    def test_only_the_ready_known_generation_can_enter_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,model=self.state(root)
            t.check_before(state,model)
            wrong=copy.deepcopy(state);wrong['advancement']['version']='1.13.0'
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

    def test_active_user_1_13_scaling_and_dungeonfinder_generation_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state,model=self.state(root)
            state['advancement']['version']='1.13.0'
            state['gameplay'].update(scaling='0.4.0',dungeonfinder='0.2.0',dungeon_solo_enabled=True,dungeon_finder_enabled=True)
            t.check_before(state,model)
            for key,value in [('scaling','0.2.0'),('dungeonfinder','0.1.0'),('dungeon_solo_enabled',False),('dungeon_finder_enabled',False)]:
                wrong=copy.deepcopy(state);wrong['gameplay'][key]=value
                with self.assertRaises(ValueError):t.check_before(wrong,model)

    def test_reuse_verified_trial_rejects_wrong_image_and_incomplete_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp); backed=home/'baseline';backed.mkdir()
            folder=home/'WoWForEver-restore-trials'/'forever-services-check-123456abcdef'
            folder.mkdir(parents=True);report_path=folder/'report.json'
            report=dict(format=t.trial.FORMAT,nonce='123456abcdef',phase='verified',
                        candidate_image='sha256:'+'a'*64,backup=str(backed),
                        database_verified=True,services_verified=True,cleanup_verified=True,
                        service_probes={'tls_verified':True},
                        world_readiness={'lines':[
                            'ForeverScaling ready: personal-virtual-v0.4 (enabled=true',
                            'ForeverDungeonFinder: direct-entry-v0.2 registered (enabled=true']})
            report_path.write_text(json.dumps(report))
            with patch.object(t.Path,'home',return_value=home):
                self.assertEqual(t.reuse_verified_trial(report_path,backed,report['candidate_image']),report)
                with self.assertRaisesRegex(ValueError,'match'):
                    t.reuse_verified_trial(report_path,backed,'sha256:'+'b'*64)
                report['cleanup_verified']=False;report_path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError,'match'):
                    t.reuse_verified_trial(report_path,backed,report['candidate_image'])
                report['cleanup_verified']=True;report['world_readiness']['lines']=[]
                report_path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError,'match'):
                    t.reuse_verified_trial(report_path,backed,report['candidate_image'])

    def test_prepare_writes_record_after_existing_trial_without_recompilation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state,model=self.state(root)
            original=(root/'compose.private.json').read_bytes()
            candidate='sha256:'+'a'*64
            report=dict(services_verified=True,cleanup_verified=True,candidate_image=candidate)
            verified=Path('/private/verified/report.json')
            with patch.object(t.game.network,'checked',return_value=state), \
                 patch.object(t.game,'wait_module'),patch.object(t.game,'check_image'), \
                 patch.object(t.adv,'image',return_value={'Id':candidate}), \
                 patch.object(t.game,'built_candidate',return_value='candidate') as cached, \
                 patch.object(t,'reuse_verified_trial',return_value=report) as reused, \
                 patch.object(t.trial,'run_check') as trial, patch.object(t.game,'build') as build, \
                 patch.object(t.clean,'compose') as compose:
                record=t.prepare(root,root/'baseline',2,True,verified)
            cached.assert_called_once()
            reused.assert_called_once_with(verified,root/'baseline',candidate)
            trial.assert_not_called();build.assert_not_called();compose.assert_not_called()
            self.assertEqual(record['phase'],'prepared')
            path=Path(record['directory'])/'transition.json'
            self.assertTrue(path.is_file())
            self.assertEqual(t.load_record(root,path)['candidate'],candidate)
            self.assertEqual((root/'compose.private.json').read_bytes(),original)
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
        for active in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);state,model=self.state(root);directory=root/'advancement/abcdef123456';directory.mkdir(parents=True)
                if active:
                    state['advancement']['version']='1.13.0'
                    state['gameplay'].update(scaling='0.4.0',dungeonfinder='0.2.0',dungeon_solo_enabled=True,dungeon_finder_enabled=True)
                    model['services']['worldserver']['environment']['FOREVER_SCALING_MIN_OFFSET']='-7'
                    t.clean.write_private(root/'compose.private.json',model);t.clean.save(state)
                original=(root/'compose.private.json').read_text();(root/'server.sh').write_text('old controller')
                record=dict(format=t.FORMAT,phase='prepared',root=str(root),directory=str(directory),before=state,
                            compose_before=original,control_before='old controller',trial={'services_verified':True,'cleanup_verified':True},
                            source_sha256=t.game.source_id(),advancement_sha256=t.adv.source_id(),candidate='sha256:'+'a'*64,candidate_tag='candidate')
                sql_calls=[]
                def sql(state,body):
                    sql_calls.append(body);return '0' if 'SUM(DATA_LENGTH' in body else ''
                with patch.object(t.adv,'image',return_value={'Id':record['candidate']}),patch.object(t.game,'check_image'),patch.object(t.game,'wait_module'),patch.object(t.adv.module_readiness,'wait'),patch.object(t.upgrade,'stop_running',return_value=['worldserver','bnetserver','web']),patch.object(t.clean,'compose'),patch.object(t.clean,'container',return_value={'State':{'Running':False}}),patch.object(t.upgrade,'snapshot',return_value={'counts':[1,2,3]}),patch.object(t,'fingerprints',return_value={'module':'1234'}),patch.object(t.upgrade,'dump_databases',return_value='a'*64),patch.object(t.clean,'sql',side_effect=sql),patch.object(t.shutil,'disk_usage',return_value=SimpleNamespace(free=10**12)):
                    t.apply(root,record)
                current=json.loads((root/'compose.private.json').read_text())
                if active:self.assertEqual(current['services']['worldserver']['environment'],model['services']['worldserver']['environment'])
                for service in ('mysql','bnetserver','web'):self.assertEqual(current['services'][service],model['services'][service])
                old_world=copy.deepcopy(model['services']['worldserver']);old_world['image']='candidate'
                if not active:
                    old_world['environment'].update(
                        FOREVER_SCALING_ENABLED='1', FOREVER_SCALING_DAMAGE_GUARD='1',
                        FOREVER_SCALING_MIN_OFFSET='-3', FOREVER_SCALING_CREATURE_MAX_LEVEL='70',
                        FOREVER_DUNGEON_SCALING_ENABLED='1', FOREVER_DUNGEON_FINDER_ENABLED='1')
                self.assertEqual(current['services']['worldserver'],old_world)
                self.assertEqual(len(sql_calls),2);self.assertIn('CREATE TABLE IF NOT EXISTS forever_advancement_preferences',sql_calls[1])
                self.assertNotIn('DROP ',sql_calls[1]);self.assertNotIn('DELETE ',sql_calls[1])
                saved=t.clean.load_state(root/'state.json')
                self.assertEqual(saved['advancement']['version'],'1.14.1')
                self.assertEqual(saved['gameplay']['scaling'],'0.4.0')
                self.assertEqual(saved['gameplay']['dungeonfinder'],'0.2.0')
                self.assertTrue(saved['gameplay']['dungeon_solo_enabled'])
                self.assertTrue(saved['gameplay']['dungeon_finder_enabled'])
                self.assertFalse((root/t.MARKER).exists())
