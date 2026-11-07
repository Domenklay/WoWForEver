import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
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
            record=dict(root=str(root),directory=str(directory),before=state,compose_before=json.dumps(model),control_before='original controller',previous_running=['worldserver','bnetserver','web'])
            with patch.object(t.game,'check_image'),patch.object(t.adv,'image'),patch.object(t.game,'wait_module'),patch.object(t.clean,'compose') as compose,patch.object(t.clean,'sql') as sql:
                t.rollback(root,record)
            sql.assert_not_called();self.assertEqual(json.loads((root/'compose.private.json').read_text()),model)
            self.assertEqual((root/'server.sh').read_text(),'original controller')
            self.assertEqual(t.clean.load_state(root/'state.json'),state)
            self.assertTrue(any('up' in c.args for c in compose.call_args_list))

    def test_apply_refuses_stale_state_and_failed_trial_before_any_file_or_sql_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,_=self.state(root)
            record=dict(before=state,directory=str(root/'advancement/abcdef123456'),phase='prepared',trial={'services_verified':False,'cleanup_verified':True})
            with patch.object(t.clean,'compose') as compose,patch.object(t.clean,'sql') as sql:
                with self.assertRaises(ValueError):t.apply(root,record)
            compose.assert_not_called();sql.assert_not_called()
