import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import clean_game_tables as tables


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


clean = module('clean_forever', ROOT / 'scripts/clean-forever-server.py')
entry = module('clean_entry', ROOT / 'docker/clean/entrypoint.py')


def state(directory):
    return dict(format=clean.FORMAT, core=clean.CORE, project=clean.PROJECT, root=str(directory),
                compose=str(directory / 'compose.private.json'), phase='prepared', certs=str(directory / 'certs'),
                extraction=str(directory / 'extraction'), image='fixture-clean-core', web_image='fixture-web',
                client=dict(source=str(directory / 'original'), test=str(directory / 'copy'), exe_build=70790,
                            metadata_version='1.60.1.70658', build_key='a' * 32, exe_sha256='fixture'),
                credentials={key: 'b' * 48 for key in ('root', 'database', 'soap')}, previous=[])


def client(path, key='a' * 32):
    (path / 'Data/data').mkdir(parents=True)
    (path / '_forever_').mkdir()
    (path / '_forever_/Wow.exe').write_bytes(b'synthetic owned EXE fixture')
    (path / '.build.info').write_text('Product!STRING:0|Active!DEC:1|Version!STRING:0|Build Key!HEX:16\n'
                                    f'wowf|1|1.60.1.70658|{key}\n')


class CleanServerTests(unittest.TestCase):
    def extraction_fixture(self, root):
        # Layout used by the pinned upstream: localized DB2s and per-map VMAPs.
        for name in ('dbc/ruRU/Map.db2', 'gt/Xp.txt', 'cameras/FILE0001.xxx',
                     'maps/0000/0000_00_00.map', 'vmaps/0000/0000.vmtree',
                     'vmaps/GameObjectModels.dtree'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'owned nonempty extraction fixture')

    def validate_extraction(self, output):
        return subprocess.run(['bash', str(ROOT / 'docker/clean/extract.sh'), '--validate-only', str(output)],
                              capture_output=True, text=True)

    def test_extractor_accepts_upstream_nested_maps_and_localized_db2s(self):
        with tempfile.TemporaryDirectory(prefix='forever extraction ') as temp:
            root = Path(temp)
            self.extraction_fixture(root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = self.validate_extraction(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('does not certify full client file coverage', result.stdout)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_extractor_reports_missing_or_empty_payloads_instead_of_accepting_directories(self):
        for missing, expected in (('vmaps/0000/0000.vmtree', 'vmaps/*.vmtree'),
                                  ('maps/0000/0000_00_00.map', 'maps/*.map'),
                                  ('dbc/ruRU/Map.db2', 'dbc/*.db2'),
                                  ('gt/Xp.txt', 'gt/*.txt'),
                                  ('cameras/FILE0001.xxx', 'cameras/*.xxx'),
                                  ('vmaps/GameObjectModels.dtree', 'vmaps/GameObjectModels.dtree')):
            for empty in (False, True):
                with self.subTest(missing=missing, empty=empty), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    self.extraction_fixture(root)
                    if empty:
                        (root / missing).write_bytes(b'')
                    else:
                        (root / missing).unlink()
                    result = self.validate_extraction(root)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Extraction incomplete:', result.stderr)
                    self.assertIn(expected, result.stderr)

    def test_resuming_old_extraction_checkpoint_uses_fixed_script_without_recompiling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            s = state(root); s['phase'] = 'extracting'
            old_output = Path(s['extraction']); old_output.mkdir()
            (old_output / 'old-partial').write_bytes(b'preserve unfinished attempt')
            (root / 'server.sh').write_text('old checkout')
            clean.save(s)
            def compose(saved, *command, **kwargs):
                model = json.loads(Path(saved['compose']).read_text())
                extractor = model['services']['extractor']
                fixed = next(v for v in extractor['volumes'] if v['target'] == '/usr/local/bin/forever-clean-extract.sh')
                self.assertTrue(fixed['read_only'])
                self.assertEqual(fixed['source'], str(ROOT / 'docker/clean/extract.sh'))
                self.assertNotEqual(saved['extraction'], str(old_output))
                raise RuntimeError('fixture stops after checking extractor launch')
            args = SimpleNamespace(root=root)
            with patch.object(clean, 'identity', return_value=s['client']), \
                    patch.object(clean, 'storage_stamp', return_value=[]), \
                    patch.object(clean, 'compose', side_effect=compose), patch.object(clean, 'run') as run, patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError, 'fixture stops'):
                    clean.install(args)
            run.assert_not_called()
            self.assertEqual((old_output / 'old-partial').read_bytes(), b'preserve unfinished attempt')
            self.assertIn(str(ROOT / 'scripts/clean-forever-server.py'), (root / 'server.sh').read_text())
            self.assertEqual((root / 'server.sh').stat().st_mode & 0o777, 0o700)

    def test_initialized_checkpoint_repairs_only_missing_table_without_reimport_or_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); s = state(root)
            s['phase'] = 'initialized'; s['client']['exe_build'] = 70658
            original = Path(s['client']['source']); client(original)
            output = root / 'data'; (output / 'gt').mkdir(parents=True)
            for name in tables.REQUIRED:
                if name != tables.NAME:
                    (output / 'gt' / name).write_bytes(b'preserve existing extracted table')
            clean.write_private(output / '.clean-extraction.json',
                                dict(core=clean.CORE, exe_sha256='fixture', build_key='a' * 32))
            clean.save(s)
            body = b'Level\tMultiplier\r\n0\t1\r\n1\t1.25\r\n'
            before = {str(p.relative_to(original)): p.read_bytes() for p in original.rglob('*') if p.is_file()}
            commands = []
            def compose(saved, *command, **kwargs):
                commands.append(command)
                if 'worldserver' in command:
                    self.assertEqual((output / 'gt' / tables.NAME).read_bytes(), body)
                return ''
            def publish(command, **kwargs):
                self.assertEqual(command[:3], ['docker', 'run', '--rm'])
                self.assertIn('--read-only', command)
                self.assertIn('none', command)
                self.assertEqual(command.count('--mount'), 1)
                self.assertIn('type=bind,source=' + str(output / 'gt') + ',target=/output', command)
                self.assertEqual(command[command.index('--entrypoint') + 1], 'python3')
                writer = subprocess.run([sys.executable, '-c', tables.TABLE_WRITER, str(output / 'gt')],
                                        input=kwargs['data'], text=True, capture_output=True)
                self.assertEqual(writer.returncode, 0, writer.stderr)
                return ''
            with patch.object(clean, 'container', return_value={'State': {'Running': False}}), \
                    patch.object(clean, 'recover_game_table', return_value=(body, {'source': 'current-client-local-encoding'})), \
                    patch.object(clean, 'compose', side_effect=compose), patch.object(clean, 'run', side_effect=publish) as run, \
                    patch.object(clean, 'wait_world'), patch.object(clean, 'stop_previous'), patch('builtins.print'):
                clean.install(SimpleNamespace(root=root, timeout=1))
            run.assert_called_once()
            self.assertFalse(any('initialize' in command or 'extractor' in command for command in commands))
            self.assertEqual(clean.load_state(root / 'state.json')['phase'], 'ready')
            self.assertEqual(before, {str(p.relative_to(original)): p.read_bytes() for p in original.rglob('*') if p.is_file()})
            self.assertEqual((output / 'gt/xp.txt').read_bytes(), b'preserve existing extracted table')
            report = json.loads((output / '.clean-game-table-repair.json').read_text())
            self.assertFalse(report['client_modified'])
            self.assertFalse(report['databases_modified'])

    def test_other_missing_tables_stop_before_recovery_or_world_start(self):
        with tempfile.TemporaryDirectory() as temp:
            s = state(Path(temp))
            with patch.object(clean, 'recover_game_table') as recover, patch.object(clean, 'compose') as compose:
                with self.assertRaisesRegex(RuntimeError, 'Missing required GameTables'):
                    clean.ensure_game_tables(s)
            recover.assert_not_called()
            compose.assert_not_called()

    def exercise_install(self, directory, failure=None):
        events = []
        root = directory / 'clean'
        original, copied, certs = directory / 'source', directory / 'copy', directory / 'certs'
        original.mkdir(); copied.mkdir(); certs.mkdir()
        values = dict(source=str(original), test=str(copied), exe_build=70790, exe_sha256='fixture',
                      metadata_version='1.60.1.70658', build_key='a' * 32, product='wowf')
        args = SimpleNamespace(root=root, client=original, test_client=copied, client_build=70790,
                               old_state=directory / 'old-state.json', jobs=2, timeout=1)
        args.old_state.write_text('{}')
        def execute(command, **kwargs):
            if command[:2] == ['docker', 'build']:
                events.append('build')
                if failure == 'build':
                    raise RuntimeError('synthetic build failure')
            return ''
        def compose(s, *command, **kwargs):
            if 'extractor' in command:
                events.append('extract')
                if failure == 'extract':
                    raise RuntimeError('synthetic extraction failure')
                output = Path(s['extraction'])
                for name in ('dbc', 'gt', 'cameras', 'maps', 'vmaps'):
                    (output / name).mkdir()
                (output / 'vmaps/GameObjectModels.dtree').write_bytes(b'synthetic owned model fixture')
                for name in tables.REQUIRED:
                    (output / 'gt' / name).write_bytes(b'synthetic owned table fixture')
            if 'initialize' in command:
                events.append('initialize-start')
            return ''
        def initialized(*args):
            events.append('initialize-exit')
            if failure == 'import':
                raise RuntimeError('synthetic import still running')
        def ready(*args):
            events.append('world-ready')
        def stop(s):
            events.append('stop-old')
        with patch.object(clean, 'identity', return_value=values), \
                patch.object(clean, 'certificate_directory', return_value=certs), \
                patch.object(clean.shutil, 'disk_usage', return_value=SimpleNamespace(free=20 * 1024**3)), \
                patch.object(clean, 'run', side_effect=execute), patch.object(clean, 'compose', side_effect=compose), \
                patch.object(clean, 'storage_stamp', return_value=[]), \
                patch.object(clean, 'container', return_value={'State':{'Running':True}}), \
                patch.object(clean, 'wait_exit', side_effect=initialized), patch.object(clean, 'wait_world', side_effect=ready), \
                patch.object(clean, 'prepare_realm', side_effect=lambda s: events.append('single-fresh-realm')), \
                patch.object(clean, 'stop_previous', side_effect=stop), patch('builtins.print'):
            try:
                clean.install(args)
                error = None
            except RuntimeError as exc:
                error = exc
        return events, clean.load_state(root / 'state.json'), error

    def test_full_install_initializes_fresh_database_and_world_before_cutover(self):
        with tempfile.TemporaryDirectory() as temp:
            events, saved, error = self.exercise_install(Path(temp))
            self.assertIsNone(error)
            self.assertEqual(saved['phase'], 'ready')
            self.assertLess(events.index('initialize-exit'), events.index('stop-old'))
            self.assertLess(events.index('world-ready'), events.index('stop-old'))
            self.assertIn('single-fresh-realm', events)
            model = json.loads(Path(saved['compose']).read_text())
            self.assertEqual(model['services']['worldserver']['ports'], ['127.0.0.1:8085:8085'])
            self.assertTrue((Path(saved['root']) / 'server.sh').is_file())
            self.assertTrue((Path(saved['root']) / 'data/vmaps/GameObjectModels.dtree').is_file())

    def test_build_extraction_or_import_failure_never_stops_old_services(self):
        for failure in ('build', 'extract', 'import'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                events, saved, error = self.exercise_install(Path(temp), failure)
                self.assertIsNotNone(error)
                self.assertNotIn('stop-old', events)
                self.assertNotEqual(saved['phase'], 'ready')
                if failure == 'import':
                    self.assertEqual(saved['phase'], 'importing')

    def test_actual_exe_build_drives_protocol_despite_old_casc_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'source', Path(temp) / 'target'
            client(source); client(target)
            with patch.object(clean.shutil, 'which', return_value='/powershell.exe'), patch.object(clean, 'executable_build', return_value=70790):
                observed = clean.identity(source, target)
                self.assertEqual(observed['exe_build'], 70790)
                self.assertEqual(observed['metadata_version'], '1.60.1.70658')
                with self.assertRaises(ValueError):
                    clean.identity(source, target, 70658)

    def test_different_client_exe_or_casc_build_cannot_silently_select_another_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'source', Path(temp) / 'target'
            client(source); client(target)
            with patch.object(clean.shutil, 'which', return_value=None):
                with self.assertRaises(ValueError):
                    clean.identity(source, target)
                (target / '_forever_/Wow.exe').write_bytes(b'different executable')
                with self.assertRaisesRegex(ValueError, 'EXE differ'):
                    clean.identity(source, target, 70790)
                (target / '_forever_/Wow.exe').write_bytes((source / '_forever_/Wow.exe').read_bytes())
                p = target / '.build.info'
                p.write_text(p.read_text().replace('a' * 32, 'c' * 32))
                with self.assertRaisesRegex(ValueError, 'build keys differ'):
                    clean.identity(source, target, 70790)

    def test_new_model_has_no_old_databases_data_overrides_or_gameplay_modules(self):
        s = state(Path('/new-clean-root'))
        m = clean.model(s)
        self.assertEqual(set(m['volumes']), {'mysql-data', 'logs'})
        self.assertTrue(all(not value for value in m['volumes'].values()))
        self.assertFalse(any('ports' in service for service in m['services'].values()))
        for name in ('worldserver', 'bnetserver', 'initialize'):
            service = m['services'][name]
            self.assertEqual(service['image'], 'fixture-clean-core')
            self.assertEqual(set(service['environment']), {'DB_PASSWORD'})
            for volume in service['volumes']:
                self.assertNotIn('overrides', volume['target'])
                if volume['target'] == '/opt/trinitycore/data':
                    self.assertEqual(volume['source'], '/new-clean-root/data')
                    self.assertTrue(volume['read_only'])
        extractor = m['services']['extractor']
        self.assertEqual(extractor['network_mode'], 'none')
        self.assertTrue(extractor['read_only'])
        self.assertTrue(extractor['volumes'][0]['read_only'])
        published = clean.model(s, published=True)
        self.assertNotIn('ports', published['services']['mysql'])
        self.assertEqual(published['services']['worldserver']['ports'], ['127.0.0.1:8085:8085'])
        self.assertEqual(published['services']['bnetserver']['ports'], ['127.0.0.1:1119:1119', '127.0.0.1:8081:8081'])

    def test_configuration_uses_pristine_dist_and_only_required_infrastructure(self):
        env = {'DB_PASSWORD': 'b' * 48}
        config = entry.configuration('worldserver', env)
        self.assertEqual(config['RealmID'], '70')
        self.assertEqual(config['Realm.SuperDistrictID'], '2')
        self.assertEqual(config['Network.EnterEncryptedModeRegionGroup'], '8')
        self.assertFalse(any('Advancement' in key or 'Subclass' in key for key in config))
        self.assertEqual(entry.configuration('bnetserver', env)['Realm.AlsoAcceptBuilds'], '""')
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'worldserver.conf'
            p.with_suffix('.conf.dist').write_text('# owned fixture\nRealmID = 1\nOtherDefault = 9\n')
            entry.write_config(p, {'RealmID': '70', 'Expansion': '0'})
            self.assertEqual(p.read_text(), '# owned fixture\nRealmID = 70\nOtherDefault = 9\n\nExpansion = 0\n')
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_database_setup_targets_only_clean_mysql_and_keeps_native_auth_build_rows(self):
        commands = []
        results = iter(['1\n', '0\n0\n', '', '70\t70790\t137\n'])
        def execute(command, **kwargs):
            commands.append((command, kwargs.get('data', '')))
            return next(results)
        with patch.object(clean, 'container', return_value={'Id': 'clean-mysql'}), patch.object(clean, 'run', side_effect=execute):
            clean.prepare_realm(state(Path('/new')))
        self.assertTrue(all(command[:3] == ['docker', 'exec', '-i'] and command[3] == 'clean-mysql' for command, _ in commands))
        sql = '\n'.join(body for _, body in commands)
        self.assertIn('gamebuild=70790', sql)
        self.assertIn('DELETE FROM auth.realmlist WHERE id<>70', sql)
        self.assertNotIn('INSERT INTO', sql)
        self.assertNotIn('DELETE FROM `build_info`', sql)

    def test_owned_old_projects_are_stopped_only_after_import_is_confirmed(self):
        s = state(Path('/new'))
        stopped = []
        def execute(command, **kwargs):
            if command[:2] == ['docker', 'ps']:
                return 'old-world' if command[-1].endswith('=forever') else ''
            if command[:2] == ['docker', 'inspect']:
                return json.dumps([{'Id':'old-world', 'State':{'Running':True}, 'Config':{'Labels':{
                    'com.docker.compose.project':'forever', 'com.docker.compose.service':'worldserver'}}}])
            if command[:2] == ['docker', 'logs']:
                return 'First world database import in progress'
            if command[:2] == ['docker', 'stop']:
                stopped.append(command)
            return ''
        with patch.object(clean, 'run', side_effect=execute), patch.object(clean, 'save'):
            with self.assertRaisesRegex(RuntimeError, 'importing'):
                clean.stop_previous(s)
        self.assertFalse(stopped)

    def test_purge_is_scoped_and_never_forces_unowned_or_running_storage(self):
        s = state(Path('/new')); s['phase'] = 'ready'
        commands = []
        def execute(command, **kwargs):
            commands.append(command)
            if command[:3] == ['docker', 'volume', 'ls'] and command[-1].endswith('=forever'):
                return 'old-volume'
            if command[:3] == ['docker', 'volume', 'inspect']:
                return json.dumps([{'Labels':{'com.docker.compose.project':'unrelated'}}])
            return ''
        with patch.object(clean, 'run', side_effect=execute), patch.object(clean, 'wait_world'), patch.object(clean, 'save'):
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                clean.purge_old(s)
        self.assertNotIn(['docker', 'volume', 'rm', 'old-volume'], commands)
        self.assertFalse(any('prune' in command or '--force' in command for command in commands))
        self.assertFalse(any(any('label=com.docker.compose.project=forever-clean' == value for value in command) for command in commands))

    def test_restarting_during_initial_import_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            s = state(Path(temp)); s['phase'] = 'importing'
            clean.save(s)
            with patch.object(clean.sys, 'argv', ['tool', 'restart', '--root', temp]), patch.object(clean, 'compose') as called:
                with self.assertRaisesRegex(ValueError, 'initialization'):
                    clean.main()
            called.assert_not_called()

    def test_private_state_mode_and_project_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); s = state(root)
            clean.save(s)
            self.assertEqual((root / 'state.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(clean.load_state(root / 'state.json')['project'], clean.PROJECT)
            s['project'] = 'forever'; clean.save(s)
            with self.assertRaises(ValueError):
                clean.load_state(root / 'state.json')

    def test_tls_probe_keeps_certificate_and_hostname_verification(self):
        self.assertIn('ssl.create_default_context', clean.TLS_PROBE)
        self.assertIn('server_hostname="trinity.actual.battle.net"', clean.TLS_PROBE)
        self.assertNotIn('CERT_NONE', clean.TLS_PROBE)

    def test_docker_build_keeps_pristine_game_binaries_separate_from_readonly_extractor_adapter(self):
        text = (ROOT / 'docker/clean/Dockerfile').read_text()
        self.assertIn(clean.CORE, text)
        self.assertIn('-DTOOLS=0 -DSERVERS=1', text)
        self.assertIn('-DTOOLS=1 -DSERVERS=0', text)
        self.assertIn('sha256sum -c pristine-servers.sha256', text)
        self.assertNotIn('inject-advancement', text)
        self.assertNotIn('COPY mods/', text)
        self.assertNotIn('git apply', text)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose is unavailable')
    def test_generated_compose_is_accepted_by_actual_compose_parser(self):
        with tempfile.TemporaryDirectory() as temp:
            s = state(Path(temp))
            for published in (False, True):
                clean.write_private(Path(s['compose']), clean.model(s, published=published))
                result = subprocess.run(['docker', 'compose', '-f', s['compose'], 'config', '-q'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
