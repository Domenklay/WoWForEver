import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('server_refresh', ROOT / 'scripts/refresh-forever-server.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def model():
    return {'name': 'forever', 'volumes': {'mysql-data': {'name': 'forever_mysql-data'},
                                         'logs': {'name': 'forever_logs'}},
            'networks': {'forever': {'name': 'forever_forever'}},
            'services': {
                'mysql': {'image': 'mysql:8.0', 'volumes': [
                    {'type': 'volume', 'source': 'mysql-data', 'target': '/var/lib/mysql'}]},
                'worldserver': {'image': 'forever-trinitycore:latest', 'build': {'context': '/old'},
                                'environment': {'CLIENT_BUILD': '70532'}, 'volumes': [
                                    {'type': 'bind', 'source': '/old/data', 'target': '/opt/trinitycore/data'}]},
                'bnetserver': {'image': 'forever-trinitycore:latest'},
                'web': {'build': {'context': '/old/web'}, 'image': 'forever-web'},
                'extractor': {'image': 'forever-trinitycore:latest'}}}


class ServerRefreshTests(unittest.TestCase):
    def test_clone_has_new_writable_storage_and_keeps_existing_data_readonly(self):
        old = model()
        result = refresh.isolated_model(old, {'mysql': 'sha256:mysql', 'web': 'sha256:web'},
                                        'candidate', refresh.PROJECT)
        self.assertEqual(old, model())
        self.assertEqual(set(result['services']), set(refresh.SERVICES))
        for section in ('networks', 'volumes'):
            self.assertTrue(all('name' not in item for item in result[section].values()))
        world = result['services']['worldserver']
        self.assertEqual(world['image'], 'candidate')
        self.assertEqual(world['environment']['CLIENT_BUILD'], '')
        self.assertEqual(world['environment']['ADVANCEMENT_ENABLED'], '1')
        self.assertTrue(world['volumes'][0]['read_only'])
        self.assertNotIn('build', world)
        self.assertEqual(result['services']['mysql']['image'], 'sha256:mysql')
        self.assertEqual(result['services']['web']['image'], 'sha256:web')

    def test_external_or_bind_database_cannot_accidentally_share_old_storage(self):
        for mutate in (
            lambda m: m['volumes']['mysql-data'].update(external=True),
            lambda m: m['volumes']['mysql-data'].update(driver_opts={'device': '/old/mysql'}),
            lambda m: m['services']['mysql']['volumes'][0].update(type='bind', source='/old/mysql'),
            lambda m: m['services']['worldserver'].update(network_mode='host'),
        ):
            original = model()
            mutate(original)
            with self.assertRaises(ValueError):
                refresh.isolated_model(original, {'mysql': 'mysql', 'web': 'web'}, 'next', refresh.PROJECT)

    def test_compose_password_and_healthcheck_escapes_are_preserved(self):
        original = model()
        original['services']['mysql']['environment'] = {'MYSQL_ROOT_PASSWORD': 'literal$$VALUE$${OTHER}$$$$'}
        original['services']['mysql']['healthcheck'] = {'test': ['CMD-SHELL', 'echo "$$MYSQL_ROOT_PASSWORD"']}
        result = refresh.isolated_model(original, {'mysql': 'mysql', 'web': 'web'}, 'next', refresh.PROJECT)
        mysql = result['services']['mysql']
        self.assertEqual(mysql['environment']['MYSQL_ROOT_PASSWORD'], 'literal$$VALUE$${OTHER}$$$$')
        self.assertEqual(mysql['healthcheck'], original['services']['mysql']['healthcheck'])

    def exercise(self, temp, failure=None):
        directory = Path(temp)
        client = directory / 'client'
        client.mkdir()
        (client / 'Wow.exe').touch()
        commands = []
        writes = []
        def command(args, **kwargs):
            commands.append(args)
            if args[0:2] == ['docker', 'compose'] and '--project-directory' in args:
                if 'config' in args:
                    return json.dumps(model())
                return 'old-' + args[-1]
            if args[:2] == ['docker', 'ps'] or args[:3] == ['docker', 'volume', 'ls']:
                return ''
            if 'ps' in args and args[-1] == 'mysql':
                return 'new-mysql'
            return ''
        def info(container):
            return {'Id': container, 'Image': 'image-' + container,
                    'State': {'Running': True}}
        def dump(container, path):
            if failure == 'backup':
                raise RuntimeError('backup failed')
            path.write_bytes(b'fixture-backup')
        def ready(*args):
            if failure == 'startup':
                raise RuntimeError('startup failed')
        def build(*args):
            if failure == 'build':
                raise RuntimeError('build failed')
        args = SimpleNamespace(old_project=directory, client=client, jobs=1, timeout=1)
        with patch.object(refresh, 'run', side_effect=command), \
                patch.object(refresh, 'inspect', side_effect=info), \
                patch.object(refresh, 'preflight'), patch.object(refresh, 'build', side_effect=build), \
                patch.object(refresh, 'dump_database', side_effect=dump), \
                patch.object(refresh, 'import_database') as imported, \
                patch.object(refresh, 'wait_mysql'), patch.object(refresh, 'wait_world', side_effect=ready), \
                patch.object(refresh, 'db_sql', side_effect=lambda c, d, s: writes.append((c, d, s))), \
                patch('builtins.print'):
            try:
                refresh.migrate(args)
                error = None
            except RuntimeError as exc:
                error = exc
        backup = next((directory / 'backups').glob('server-refresh-*'))
        return client, commands, writes, json.loads((backup / 'state.json').read_text()), error, imported

    def test_success_imports_and_changes_only_cloned_database_then_installs_new_client_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            client, commands, writes, state, error, imported = self.exercise(temp)
            self.assertIsNone(error)
            self.assertEqual(state['phase'], 'ready')
            self.assertTrue(state['addon_installed'])
            self.assertTrue((client / 'Interface/AddOns/ForeverAscension/ForeverAscension.toc').is_file())
            self.assertEqual({container for container, _, _ in writes}, {'new-mysql'})
            self.assertIn('forever_advancement_spells', writes[0][2])
            self.assertEqual(imported.call_args.args[0], 'new-mysql')
            self.assertNotIn(['docker', 'start', 'old-worldserver'], commands)
            self.assertNotIn('down', sum(commands, []))
            self.assertNotIn('-v', sum(commands, []))

    def test_backup_failure_restarts_old_containers_without_sql_or_ui_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            client, commands, writes, state, error, imported = self.exercise(temp, 'backup')
            self.assertIsNotNone(error)
            self.assertEqual(state['phase'], 'rolled-back')
            self.assertEqual(writes, [])
            imported.assert_not_called()
            self.assertFalse((client / 'Interface').exists())
            for name in refresh.GAME_SERVICES:
                self.assertIn(['docker', 'start', 'old-' + name], commands)

    def test_startup_failure_keeps_original_database_and_ui_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            client, commands, writes, state, error, _ = self.exercise(temp, 'startup')
            self.assertIsNotNone(error)
            self.assertEqual(state['phase'], 'rolled-back')
            self.assertEqual({container for container, _, _ in writes}, {'new-mysql'})
            self.assertFalse((client / 'Interface').exists())
            self.assertIn(['docker', 'start', 'old-worldserver'], commands)

    def test_build_failure_does_not_stop_original_containers(self):
        with tempfile.TemporaryDirectory() as temp:
            _, commands, writes, state, error, imported = self.exercise(temp, 'build')
            self.assertIsNotNone(error)
            self.assertFalse(state['old_stopped'])
            self.assertEqual(writes, [])
            imported.assert_not_called()
            self.assertNotIn('stop', sum(commands, []))

    def test_preflight_refuses_server_still_importing_databases(self):
        with patch.object(refresh, 'run', return_value='Importing world database...'), \
                patch.object(refresh, 'db_sql') as query:
            with self.assertRaisesRegex(RuntimeError, 'Initial database import'):
                refresh.preflight({'worldserver': {'Id': 'old-world'}})
            query.assert_not_called()

    def test_known_schema_crash_is_accepted_after_all_imports_completed(self):
        logs = ('Character database is up-to-date\nWorld database is up-to-date\n'
                'Hotfixes database is up-to-date\nTable characters.forever_advancement_spells does not exist')
        with patch.object(refresh, 'run', return_value=logs), \
                patch.object(refresh, 'db_sql', return_value='COUNT(*)\n4\n'):
            refresh.preflight({'worldserver': {'Id': 'old-world'}, 'mysql': {'Id': 'old-mysql'}})

    def test_ready_server_does_not_need_revision_banner_in_the_log_tail(self):
        info = {'RestartCount': 0, 'State': {'Status': 'running'}, 'Config': {'Labels': {
            'org.wowforever.core': refresh.CORE, 'org.wowforever.advancement': '1.11.0'}}}
        logs = 'ForeverAdvancement ready: catalogue\nversion=1.11.0\nworldserver-daemon ready\n'
        state = {'project': refresh.PROJECT, 'compose': '/private/compose.json'}
        with patch.object(refresh, 'inspect', return_value=info), \
                patch.object(refresh, 'run', side_effect=['container', logs]), \
                patch.object(refresh.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as network:
            refresh.wait_world(state, 1)
            self.assertIn('bnetserver', network.call_args.args[0][-1])
            self.assertIn('8085', network.call_args.args[0][-1])

    def test_wrong_running_image_is_rejected_even_if_ready_log_exists(self):
        state = {'project': refresh.PROJECT, 'compose': '/private/compose.json'}
        with patch.object(refresh, 'run', return_value='container'), \
                patch.object(refresh, 'inspect', return_value={'Config': {'Labels': {}}}):
            with self.assertRaisesRegex(RuntimeError, 'expected core and mod image'):
                refresh.wait_world(state, 1)


if __name__ == '__main__':
    unittest.main()
