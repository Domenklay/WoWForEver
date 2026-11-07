import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_clean_advancement import fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clean_gameplay_tests', ROOT / 'scripts/enable-clean-gameplay.py')
game = importlib.util.module_from_spec(spec); spec.loader.exec_module(game)


class GameplayTests(unittest.TestCase):
    def test_all_module_flags_preserve_database_volumes_ports_certificates_and_bnet(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model = fixture(root); original = copy.deepcopy(model)
            target, result = game.configure(state, model, 'candidate', root / 'advancement/abcdef123456')
            self.assertEqual(model, original)
            for service in ('mysql', 'bnetserver', 'web'):
                self.assertEqual(result['services'][service], model['services'][service])
            old, new = model['services']['worldserver'], result['services']['worldserver']
            self.assertEqual(old['ports'], new['ports']); self.assertEqual(old['volumes'][1:], new['volumes'])
            self.assertEqual(new['environment']['FOREVER_ENCYCLOPEDIA_ENABLED'], '1')
            self.assertEqual(new['environment']['FOREVER_SCALING_ENABLED'], '1')
            self.assertEqual(target['gameplay']['scaling'], '0.4.0')
            self.assertEqual(target['gameplay']['dungeonfinder'], '0.2.0')
            self.assertEqual(new['environment']['FOREVER_DUNGEON_SCALING_ENABLED'], '0')
            self.assertEqual(new['environment']['FOREVER_DUNGEON_FINDER_ENABLED'], '0')
            self.assertEqual(target['client'], state['client'])
            game.clean.save(target); self.assertEqual(game.clean.load_state(root / 'state.json'), target)

    def test_scaling_can_be_left_disabled_without_removing_book_or_ascension(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model = fixture(root)
            target, result = game.configure(state, model, 'candidate', root / 'advancement/abcdef123456', False)
            self.assertIsNone(target['gameplay']['scaling'])
            env = result['services']['worldserver']['environment']
            self.assertEqual(env['FOREVER_SCALING_ENABLED'], '0')
            self.assertEqual(env['FOREVER_ADVANCEMENT_ENABLED'], '1')
            self.assertEqual(env['FOREVER_ENCYCLOPEDIA_ENABLED'], '1')

    def test_failed_build_cannot_stop_the_running_world(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, _ = fixture(root)
            with patch.object(game.clean, 'wait_world'), patch.object(game, 'build', side_effect=RuntimeError('compile failed')), patch.object(game.clean, 'compose') as compose:
                with self.assertRaisesRegex(RuntimeError, 'compile failed'): game.install(root, 2)
            compose.assert_not_called(); self.assertEqual(game.clean.load_state(root / 'state.json'), state)
            self.assertFalse((root / game.MARKER).exists())

    def run_install(self, root, failure=None, previous_advancement=False):
        state, model = fixture(root)
        if previous_advancement:
            state['advancement'] = dict(version='1.11.0', protocol=3, source_sha256='b' * 64,
                                       backup=str(root / 'advancement/aaaaaaaaaaaa/install.json'))
            state['database_version'] = 'advancement-1.11.0@pristine'
            game.clean.save(state)
        calls = []
        def sql(saved, body):
            calls.append(body)
            return '100\n' if 'SUM(DATA_LENGTH' in body else ''
        labels = {'org.wowforever.core': state['core'], 'org.wowforever.advancement': '1.11.0' if previous_advancement else 'none'}
        if previous_advancement: labels['org.wowforever.advancement.source'] = 'b' * 64
        with patch.object(game.clean, 'wait_world'), patch.object(game, 'build', return_value='candidate'), \
             patch.object(game.adv, 'image', return_value={'Config': {'Labels': labels}}), \
             patch.object(game.clean, 'compose') as compose, patch.object(game.clean, 'sql', side_effect=sql), \
             patch.object(game.upgrade, 'stop_running', return_value=['worldserver','bnetserver','web']), \
             patch.object(game.upgrade, 'snapshot', return_value={'counts':['2','3','4']}), \
             patch.object(game.upgrade, 'dump_databases', return_value='private-backup') as dump, \
             patch.object(game.adv, 'bindings', return_value=[[116,'spell_forever_advancement']]), \
             patch.object(game, 'wait_module', side_effect=failure):
            if failure:
                with self.assertRaisesRegex(RuntimeError, 'module failed'): game.install(root, 2)
            else: game.install(root, 2)
        return state, model, calls, compose, dump

    def test_install_adds_book_tables_and_preserves_existing_advancement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model, calls, compose, dump = self.run_install(root, previous_advancement=True)
            saved = game.clean.load_state(root / 'state.json')
            self.assertEqual(saved['advancement']['version'], '1.14.1')
            self.assertEqual(saved['gameplay']['encyclopedia'], game.BOOK_VERSION)
            self.assertEqual(saved['image'], 'candidate'); dump.assert_called_once()
            body = '\n'.join(calls)
            self.assertIn('CREATE TABLE IF NOT EXISTS `forever_encyclopedia_discovery`', body)
            for forbidden in ('DROP TABLE', 'TRUNCATE', 'auth.realmlist', 'UPDATE characters.characters'):
                self.assertNotIn(forbidden, body)
            changed = json.loads((root / 'compose.private.json').read_text())
            self.assertEqual(changed['services']['mysql'], model['services']['mysql'])
            self.assertFalse((root / game.MARKER).exists())
            self.assertTrue(Path(saved['gameplay']['backup']).is_file())

    def test_failed_readiness_restores_the_exact_previous_image_and_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model, calls, _, _ = self.run_install(root, RuntimeError('module failed'), True)
            self.assertEqual(game.clean.load_state(root / 'state.json'), state)
            self.assertEqual(json.loads((root / 'compose.private.json').read_text()), model)
            self.assertEqual((root / 'server.sh').read_text(), '# original controller\n')
            record = next((root / 'advancement').glob('*/install.json'))
            self.assertEqual(game.load_backup(root, record)['phase'], 'failed-recovered')
            self.assertNotIn('DROP TABLE', '\n'.join(calls)); self.assertFalse((root / game.MARKER).exists())

    def test_normal_lifecycle_cannot_race_an_interrupted_gameplay_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root); (root / game.MARKER).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'enable-clean-gameplay'):
                game.clean.execute(SimpleNamespace(action='start', root=root))

    def test_both_launcher_channels_include_the_compatible_pinned_book(self):
        spec=importlib.util.spec_from_file_location('book_channel_check',ROOT/'scripts/update-addon-channel.py')
        channel_tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(channel_tool)
        catalog=channel_tool.validate(json.loads((ROOT/'addons/channels.json').read_text()))
        for release in catalog['channels'].values():
            manifest=next(m for m in release['addons'] if m['name']=='ForeverEncyclopedia')
            self.assertEqual(manifest['protocol'],1)
            self.assertEqual(manifest['sourcePath'],'mods/living-encyclopedia/addon/ForeverEncyclopedia')
            self.assertIn('ForeverEncyclopedia.toc',{f['name'] for f in manifest['files']})

    def test_readiness_requires_the_current_world_initialization_and_enabled_scaling(self):
        state = {'gameplay': {'scaling':'0.2.0'}}
        live = {'Id':'current-world', 'State': {'StartedAt':'current-start','Running':True}}
        for logs, success in [('ForeverEncyclopedia ready:\nForeverScaling ready: personal-virtual-v0.2 (enabled=true, damageGuard=true)', True),
                              ('ForeverEncyclopedia ready:\nForeverScaling: personal-virtual-v0.2 registered (enabled=true', False),
                              ('ForeverEncyclopedia ready:\nForeverScaling ready: personal-virtual-v0.2 (enabled=false', False)]:
            logs += '\n' + '\n'.join(game.adv.READY_PATTERNS)
            report = dict(lines=logs.splitlines(),settings={},serverLogStatus='current-process-file')
            with patch.object(game.clean, 'wait_world'), patch.object(game.clean, 'container', return_value=live), \
                 patch.object(game.adv.module_readiness, 'snapshot', return_value=report) as probe, \
                 patch.object(game.adv.module_readiness.time,'monotonic',side_effect=[0,181]):
                if success: game.wait_module(state)
                else:
                    with self.assertRaises(RuntimeError): game.wait_module(state)
                self.assertEqual(probe.call_args.args[2]['Id'], 'current-world')

    def test_a_matching_built_image_is_reused_without_compilation(self):
        state = dict(core=game.clean.CORE)
        labels = {'org.wowforever.core':game.clean.CORE,'org.wowforever.advancement':game.adv.VERSION,
                  'org.wowforever.advancement.source':game.adv.source_id(),
                  'org.wowforever.gameplay.source':game.source_id(),
                  'org.wowforever.encyclopedia':game.BOOK_VERSION,'org.wowforever.scaling':game.SCALING_VERSION,
                  'org.wowforever.dungeonfinder':game.FINDER_VERSION}
        with patch.object(game.adv,'image',return_value={'Config':{'Labels':labels}}), patch.object(game.clean,'run') as command:
            self.assertEqual(game.build(state,2),'forever-trinitycore:gameplay-70658-'+game.source_id()[:12])
            command.assert_not_called()
        labels['org.wowforever.gameplay.source']='foreign-source'
        with patch.object(game.adv,'image',return_value={'Config':{'Labels':labels}}), patch.object(game.clean,'run') as command:
            with self.assertRaises(ValueError):game.build(state,2)
            command.assert_not_called()

    def test_retry_requires_the_built_image_and_cannot_silently_start_a_full_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture(root)
            with patch.object(game.clean,'wait_world'), patch.object(game,'built_candidate',side_effect=ValueError('unavailable')) as cached, \
                 patch.object(game,'build') as build,patch.object(game.clean,'compose') as compose:
                with self.assertRaisesRegex(ValueError,'unavailable'):game.install(root,2,reuse_built_image=True)
                cached.assert_called_once();self.assertTrue(cached.call_args.kwargs['required'])
                build.assert_not_called();compose.assert_not_called();self.assertFalse((root/game.MARKER).exists())


if __name__ == '__main__': unittest.main()
