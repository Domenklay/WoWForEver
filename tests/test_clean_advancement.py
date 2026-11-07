import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('clean_advancement_tests', ROOT / 'scripts/enable-clean-advancement.py')
adv = importlib.util.module_from_spec(spec); spec.loader.exec_module(adv)
spec = importlib.util.spec_from_file_location('adv_entrypoint_tests', ROOT / 'docker/clean/entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec); spec.loader.exec_module(entrypoint)


def fixture(root):
    state = dict(format=adv.clean.FORMAT, core=adv.clean.CORE, project='forever-clean', root=str(root),
                 compose=str(root / 'compose.private.json'), phase='ready', image='original-image',
                 certs=str(root / 'certs'), client=dict(exe_build=70658), credentials=dict(database='a' * 48))
    model = dict(name='forever-clean', services={
        'worldserver': dict(image='original-image', command=['worldserver'], environment={'DB_PASSWORD': 'a' * 48},
                            ports=['127.0.0.1:8085:8085'], volumes=[
                                dict(source='old-helper', target='/usr/local/bin/forever-clean-entrypoint.py'),
                                dict(source='same-data', target='/opt/trinitycore/data'),
                                dict(source='same-certs', target='/opt/trinitycore/certs')]),
        'mysql': dict(image='mysql-pinned', volumes=['existing-db:/var/lib/mysql']),
        'bnetserver': dict(image='original-image', ports=['127.0.0.1:1119:1119']),
        'web': dict(image='existing-web')}, volumes={'existing-db': {}})
    adv.clean.write_private(root / 'state.json', state)
    adv.clean.write_private(root / 'compose.private.json', model)
    (root / 'server.sh').write_text('# original controller\n')
    return state, model


class CleanAdvancementTests(unittest.TestCase):
    def test_candidate_preserves_databases_network_tls_and_all_other_services(self):
        with tempfile.TemporaryDirectory() as temp:
            state, before = fixture(Path(temp)); preserved = copy.deepcopy(before)
            target, model = adv.configure(state, before, 'candidate', Path(temp) / 'advancement/abcdef123456')
            self.assertEqual(before, preserved)
            for name in ('mysql', 'web', 'bnetserver'):
                self.assertEqual(model['services'][name], before['services'][name])
            world = model['services']['worldserver']
            self.assertEqual(world['ports'], before['services']['worldserver']['ports'])
            self.assertEqual(world['environment']['DB_PASSWORD'], 'a' * 48)
            self.assertEqual(world['environment']['FOREVER_ADVANCEMENT_ENABLED'], '1')
            self.assertEqual(world['volumes'], before['services']['worldserver']['volumes'][1:])
            self.assertEqual(target['client'], state['client'])
            self.assertEqual(target['core'], state['core'])
            adv.clean.save(target)
            self.assertEqual(adv.clean.load_state(Path(temp) / 'state.json'), target)

    def test_pristine_entrypoint_remains_disabled_and_advanced_start_cannot_import(self):
        environment = {'DB_PASSWORD': 'a' * 48}
        before = entrypoint.configuration('worldserver', environment)
        self.assertNotIn('ForeverAdvancement.Enable', before)
        after = entrypoint.configuration('worldserver', dict(environment, FOREVER_ADVANCEMENT_ENABLED='1'))
        self.assertEqual(after['ForeverAdvancement.Enable'], '1')
        self.assertEqual(after['Updates.AutoSetup'], '0')
        self.assertEqual(after['Updates.EnableDatabases'], '0')
        self.assertEqual(after['WorldServerPort'], '8085')
        self.assertNotIn('ForeverAdvancement.Enable', entrypoint.configuration('bnetserver', dict(environment, FOREVER_ADVANCEMENT_ENABLED='1')))

    def test_failed_build_cannot_stop_the_ready_server_or_change_any_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, _ = fixture(root); original = (root / 'compose.private.json').read_bytes()
            with patch.object(adv.clean, 'wait_world'), patch.object(adv, 'build', side_effect=RuntimeError('compile failed')), patch.object(adv.clean, 'compose') as compose:
                with self.assertRaisesRegex(RuntimeError, 'compile failed'): adv.install(root, 2)
            compose.assert_not_called()
            self.assertEqual(adv.clean.load_state(root / 'state.json'), state)
            self.assertEqual((root / 'compose.private.json').read_bytes(), original)
            self.assertFalse((root / adv.MARKER).exists())

    def run_install(self, root, failure=None):
        state, model = fixture(root)
        calls = []
        def sql(saved, body):
            calls.append(body)
            return '100\n' if 'SUM(DATA_LENGTH' in body else ''
        with patch.object(adv.clean, 'wait_world'), patch.object(adv, 'build', return_value='candidate-image'), \
             patch.object(adv, 'image', return_value={'Config': {'Labels': {'org.wowforever.core': state['core'], 'org.wowforever.advancement': 'none'}}}), \
             patch.object(adv.clean, 'compose') as compose, patch.object(adv.clean, 'sql', side_effect=sql), \
             patch.object(adv.upgrade, 'stop_running', return_value=['worldserver', 'bnetserver', 'web']), \
             patch.object(adv.upgrade, 'snapshot', return_value={'counts': ['2', '3', '4']}), \
             patch.object(adv.upgrade, 'dump_databases', return_value='fixture-backup-hash') as dump, \
             patch.object(adv, 'bindings', return_value=[[116, 'spell_forever_advancement']]), \
             patch.object(adv, 'wait_module', side_effect=failure):
            if failure:
                with self.assertRaisesRegex(RuntimeError, 'module failed'): adv.install(root, 2)
            else:
                adv.install(root, 2)
        return state, model, calls, compose, dump

    def test_install_retains_existing_volume_and_adds_only_owned_tables_and_bindings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model, calls, compose, dump = self.run_install(root)
            saved = adv.clean.load_state(root / 'state.json')
            self.assertEqual(saved['advancement']['version'], '1.11.0')
            self.assertEqual(saved['image'], 'candidate-image')
            changed = json.loads((root / 'compose.private.json').read_text())
            self.assertEqual(changed['services']['mysql'], model['services']['mysql'])
            self.assertEqual(changed['services']['bnetserver'], model['services']['bnetserver'])
            dump.assert_called_once()
            body = '\n'.join(calls)
            self.assertIn('CREATE TABLE IF NOT EXISTS forever_advancement_spells', body)
            self.assertNotIn('DROP TABLE', body)
            self.assertNotIn('TRUNCATE', body)
            self.assertNotIn('auth.realmlist', body)
            self.assertFalse((root / adv.MARKER).exists())
            self.assertTrue(Path(saved['advancement']['backup']).is_file())
            self.assertTrue(any('--force-recreate' in call.args and call.args[-1] == 'worldserver' for call in compose.call_args_list))

    def test_failed_module_readiness_restores_exact_compose_and_preserves_progress_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state, model, calls, compose, _ = self.run_install(root, RuntimeError('module failed'))
            self.assertEqual(adv.clean.load_state(root / 'state.json'), state)
            self.assertEqual(json.loads((root / 'compose.private.json').read_text()), model)
            self.assertEqual((root / 'server.sh').read_text(), '# original controller\n')
            self.assertFalse((root / adv.MARKER).exists())
            self.assertIn("INSERT INTO world.spell_script_names (spell_id,ScriptName) VALUES (116,'spell_forever_advancement')", calls[-1])
            self.assertNotIn('DROP TABLE', '\n'.join(calls))
            record = next((root / 'advancement').glob('*/install.json'))
            self.assertEqual(adv.load_backup(root, record)['phase'], 'failed-recovered')

    def test_other_core_or_module_image_cannot_be_activated(self):
        state = {'core': adv.clean.CORE}
        for labels in ({'org.wowforever.core': 'other', 'org.wowforever.advancement': 'none'},
                       {'org.wowforever.core': adv.clean.CORE, 'org.wowforever.advancement': '1.9.0'}):
            with self.assertRaises(ValueError): adv.check_image({'Config': {'Labels': labels}}, state, True)

    def test_lifecycle_cannot_race_an_interrupted_module_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root); (root / adv.MARKER).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'interrupted module'):
                adv.clean.execute(SimpleNamespace(action='start', root=root))

    def test_launcher_channels_keep_pinned_ascension_protocol_before_game_spawn(self):
        # Payload bytes are checked against immutable Git objects by addon-channels.yml,
        # not against mutable source folders or the obsolete 1.7 bundled manifests.
        spec=importlib.util.spec_from_file_location('adv_channel_check',ROOT/'scripts/update-addon-channel.py')
        channel_tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(channel_tool)
        catalog=channel_tool.validate(json.loads((ROOT/'addons/channels.json').read_text()))
        for release in catalog['channels'].values():
            manifest=next(m for m in release['addons'] if m['name']=='ForeverAscension')
            self.assertEqual(manifest['protocol'],3)
            self.assertEqual(manifest['sourcePath'],'mods/forever-advancement/addon/ForeverAscension')
            self.assertIn('ForeverAscension.toc',{f['name'] for f in manifest['files']})
        lib = (ROOT / 'app/src-tauri/src/lib.rs').read_text()
        self.assertLess(lib.index('addon::ensure('), lib.index('launch(app, settings).await'))


if __name__ == '__main__': unittest.main()
