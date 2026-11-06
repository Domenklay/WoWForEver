import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import server_release_catalog as catalog

spec = importlib.util.spec_from_file_location('upgrade_test', ROOT / 'scripts/upgrade-forever-server.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
clean = upgrade.clean


def fixture(directory):
    root = directory / 'server'
    root.mkdir()
    (root / 'data').mkdir()
    (root / 'data/old.map').write_bytes(b'old extracted resources')
    source = directory / 'owned-client'
    (source / 'Data/data').mkdir(parents=True)
    (source / '_forever_').mkdir()
    (source / '_forever_/Wow.exe').write_bytes(b'synthetic owned EXE')
    (source / '.build.info').write_text('Product!STRING:0|Active!DEC:1|Version!STRING:0|Build Key!HEX:16\n'
                                       'wowf|1|1.60.1.70707|' + 'a' * 32 + '\n')
    (root / 'server.sh').write_text('#!/bin/sh\n# old controller\n')
    state = dict(format=clean.FORMAT, project=clean.PROJECT, core=clean.CORE, phase='ready', root=str(root),
                 compose=str(root / 'compose.private.json'), image='owned-pristine-image', web_image='owned-web',
                 certs=str(root / 'certs'), extraction=str(root / 'old-extraction'),
                 client=dict(source=str(source), test=str(directory / 'old-copy'), exe_build=70658,
                             metadata_version='1.60.1.70658', exe_sha256='b' * 64, build_key='b' * 32, product='wowf'),
                 credentials={key: 'c' * 48 for key in ('root', 'database', 'soap')}, previous=[])
    clean.write_private(Path(state['compose']), clean.model(state, published=True))
    clean.save(state)
    return root, source, state


def prepared(root, source):
    with patch.object(clean, 'executable_build', return_value=70707), patch('builtins.print'):
        plan = upgrade.plan_upgrade(root, source, 'forever-1.60.1.70707')
    output = Path(plan['target']['data_directory'])
    output.mkdir()
    clean.write_private(output / '.clean-extraction.json', dict(core=clean.CORE,
                        exe_sha256=plan['client']['exe_sha256'], build_key=plan['client']['build_key']))
    plan['phase'] = 'prepared'
    return plan


class UpgradeTests(unittest.TestCase):
    def test_preload_with_old_exe_is_rejected_before_creating_a_plan_or_touching_server(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, state = fixture(Path(temp))
            original = (root / 'state.json').read_bytes()
            with patch.object(clean, 'executable_build', return_value=70658), patch.object(clean, 'compose') as compose:
                with self.assertRaisesRegex(ValueError, 'activated.*70707'):
                    upgrade.plan_upgrade(root, source, 'forever-1.60.1.70707')
            self.assertEqual((root / 'state.json').read_bytes(), original)
            self.assertFalse((root / 'upgrades').exists())
            compose.assert_not_called()

    def test_new_exe_with_old_active_metadata_is_not_relabelled(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, _ = fixture(Path(temp))
            info = source / '.build.info'
            info.write_text(info.read_text().replace('70707', '70658'))
            original = info.read_bytes()
            with patch.object(clean, 'executable_build', return_value=70707):
                with self.assertRaisesRegex(ValueError, 'EXE and active'):
                    upgrade.plan_upgrade(root, source, 'forever-1.60.1.70707')
            self.assertEqual(info.read_bytes(), original)

    def test_plan_preserves_active_state_and_separates_data_and_db_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, before = fixture(Path(temp))
            original = (root / 'state.json').read_bytes()
            plan = prepared(root, source)
            self.assertEqual((root / 'state.json').read_bytes(), original)
            self.assertNotEqual(plan['target']['project'], before['project'])
            self.assertNotEqual(Path(plan['target']['data_directory']), root / 'data')
            self.assertEqual(plan['descriptor']['database']['migrations'], [])
            self.assertEqual(plan['descriptor']['database']['from'], plan['descriptor']['database']['to'])
            self.assertEqual(plan['client']['exe_build'], 70707)
            self.assertNotIn('70755', json.dumps(plan['old_compose']))

    def test_unknown_release_and_unknown_database_migration_chain_are_blocked(self):
        with self.assertRaisesRegex(ValueError, 'No reviewed release'):
            catalog.release('forever-1.60.1.99999')
        with tempfile.TemporaryDirectory() as temp:
            root, source, before = fixture(Path(temp))
            before['database_version'] = 'unexpected-schema'
            clean.save(before)
            with self.assertRaisesRegex(ValueError, 'migration chain'):
                upgrade.plan_upgrade(root, source, 'forever-1.60.1.70707')

    def test_unfinished_upgrade_blocks_lifecycle_and_new_plans(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, _ = fixture(Path(temp))
            clean.write_private(root / '.upgrade-in-progress.json', {'plan': 'interrupted'})
            with patch.object(clean, 'compose') as compose:
                with self.assertRaisesRegex(ValueError, 'interrupted'):
                    clean.execute(SimpleNamespace(root=root, action='restart'))
                with self.assertRaisesRegex(ValueError, 'unfinished'):
                    upgrade.plan_upgrade(root, source, 'forever-1.60.1.70707')
            compose.assert_not_called()

    def test_a_stale_or_tampered_plan_cannot_replace_the_active_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, before = fixture(Path(temp))
            plan = prepared(root, source)
            path = Path(plan['directory']) / 'plan.json'
            clean.write_private(path, plan)
            self.assertEqual(upgrade.load_plan(path)['target']['project'], plan['target']['project'])
            plan['before']['image'] = 'unreviewed'
            clean.write_private(path, plan)
            with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                upgrade.load_plan(path)
            before['web_image'] = 'changed-after-plan'
            clean.save(before)
            with self.assertRaisesRegex(ValueError, 'changed since planning'):
                upgrade.original_unchanged(plan)

    def test_prepared_generation_loads_and_lifecycle_uses_its_project_and_own_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, _ = fixture(Path(temp))
            plan = prepared(root, source)
            active = dict(plan['target'], compose=str(root / 'compose.private.json'))
            clean.save(active)
            self.assertEqual(clean.load_state(root / 'state.json')['release'], 'forever-1.60.1.70707')
            model = clean.model(active, published=True)
            self.assertEqual(model['name'], active['project'])
            self.assertEqual(model['services']['worldserver']['volumes'][0]['source'], active['data_directory'])
            self.assertEqual(model['services']['worldserver']['environment']['FOREVER_RELEASE_MANAGED'], '1')
            with patch.object(clean, 'run') as run:
                clean.compose(active, 'stop', 'worldserver')
            self.assertEqual(run.call_args.args[0][3], active['project'])
            active['data_directory'] = str(root / 'upgrades/../data')
            clean.save(active)
            with self.assertRaisesRegex(ValueError, 'state identity'):
                clean.load_state(root / 'state.json')

    def test_failed_clone_verification_returns_old_server_without_deleting_its_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, before = fixture(Path(temp))
            plan = prepared(root, source)
            old_compose = (root / 'compose.private.json').read_bytes()
            snapshots = [dict(counts=['1','1','1'], schema_sha256='a'), dict(counts=['0','0','0'], schema_sha256='a')]
            with patch.object(upgrade, 'client_unchanged'), patch.object(upgrade, 'image_identity'), \
                    patch.object(upgrade, 'stop_running', return_value=list(upgrade.RUNTIME)), \
                    patch.object(clean, 'compose') as compose, patch.object(clean, 'configure_compose'), \
                    patch.object(clean, 'sql', return_value='10'), patch.object(upgrade, 'snapshot', side_effect=snapshots), \
                    patch.object(upgrade, 'dump_databases', return_value='checked-sha'), \
                    patch.object(clean, 'container', return_value={'Image':'sha256:fixture'}), \
                    patch.object(upgrade, 'restore_databases'), patch.object(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=10**12)), \
                    patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError, 'clone differs'):
                    upgrade.apply(plan)
            self.assertEqual(clean.load_state(root / 'state.json'), before)
            self.assertEqual((root / 'compose.private.json').read_bytes(), old_compose)
            self.assertEqual((root / 'data/old.map').read_bytes(), b'old extracted resources')
            self.assertEqual(plan['phase'], 'failed-recovered')
            self.assertFalse(any('down' in call.args or 'rm' in call.args for call in compose.call_args_list))

    def test_apply_orders_quiesce_dump_clone_migrations_verification_and_cutover(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, _ = fixture(Path(temp))
            plan = prepared(root, source)
            events = []
            baseline = dict(counts=['2','2','3'], schema_sha256='same-schema')
            def compose(state, *args, **kwargs):
                events.append(('compose', state['project'], args))
                return ''
            def dump(*args): events.append(('dump',)); return 'backup-sha'
            def restore(*args): events.append(('restore',))
            def publish(*args): events.append(('publish',))
            with patch.object(upgrade, 'client_unchanged'), patch.object(upgrade, 'image_identity'), \
                    patch.object(upgrade, 'stop_running', return_value=list(upgrade.RUNTIME)), \
                    patch.object(clean, 'compose', side_effect=compose), patch.object(clean, 'configure_compose'), \
                    patch.object(clean, 'sql', return_value='10') as sql, patch.object(upgrade, 'snapshot', return_value=baseline), \
                    patch.object(upgrade, 'dump_databases', side_effect=dump), patch.object(upgrade, 'restore_databases', side_effect=restore), \
                    patch.object(clean, 'container', return_value={'Image':'sha256:fixture'}), patch.object(clean, 'wait_world'), \
                    patch.object(upgrade, 'publish', side_effect=publish), \
                    patch.object(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=10**12)), patch('builtins.print'):
                upgrade.apply(plan)
            self.assertEqual(plan['phase'], 'active')
            self.assertLess(next(i for i,e in enumerate(events) if e[0]=='compose' and e[2][0]=='stop'), events.index(('dump',)))
            self.assertLess(events.index(('dump',)), events.index(('restore',)))
            self.assertLess(events.index(('restore',)), events.index(('publish',)))
            queries = '\n'.join(call.args[1] for call in sql.call_args_list)
            self.assertIn('VALUES (70707,1,60,1,NULL)', queries)
            self.assertIn('WHERE id=70', queries)
            self.assertNotIn('DELETE FROM', queries)
            self.assertNotIn('70755', queries)

    def test_corrupt_snapshot_is_refused_before_mysql_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / 'snapshot.gz'
            snapshot.write_bytes(gzip.compress(b'fixture'))
            with patch.object(clean, 'container') as container, patch.object(upgrade.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    upgrade.restore_databases({}, snapshot, 'wrong-sha')
            container.assert_not_called()
            popen.assert_not_called()

    def test_rollback_preserves_post_upgrade_progress_and_handles_commit_checkpoint_crash(self):
        for phase in ('active', 'verified'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                root, source, before = fixture(Path(temp))
                plan = prepared(root, source)
                plan['phase'] = phase
                plan['previous_running'] = list(upgrade.RUNTIME)
                active = dict(plan['target'], compose=str(root / 'compose.private.json'))
                clean.save(active)
                clean.write_private(Path(active['compose']), clean.model(active, published=True))
                events = []
                with patch.object(clean, 'compose', side_effect=lambda *a, **kw: events.append(('compose', a))), \
                        patch.object(upgrade, 'dump_databases', side_effect=lambda *a: events.append(('dump', a)) or 'after-sha'), patch('builtins.print'):
                    upgrade.rollback(plan)
                self.assertEqual(plan['phase'], 'rolled-back')
                self.assertEqual(clean.load_state(root / 'state.json'), before)
                self.assertEqual(plan['rollback_backup_sha256'], 'after-sha')
                self.assertEqual(events[0][1][1], 'stop')
                self.assertEqual(events[1][0], 'dump')
                self.assertIn('databases-after-', str(events[1]))

    def test_reviewed_sql_migrations_need_local_paths_scope_and_matching_hash(self):
        for file in ('/tmp/arbitrary.sql', '../../arbitrary.sql'):
            with self.assertRaises(ValueError):
                catalog.migration_body(dict(database='world', file=file, sha256='a'*64))
        with self.assertRaises(ValueError):
            catalog.migration_body(dict(database='mysql', file='fixture.sql', sha256='a'*64))


if __name__ == '__main__':
    unittest.main()
