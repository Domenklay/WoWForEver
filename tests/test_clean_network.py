import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('network_test', ROOT / 'scripts/repair-clean-network.py')
network = importlib.util.module_from_spec(spec); spec.loader.exec_module(network)


def fixture(root):
    state = dict(root=str(root), compose=str(root / 'compose.private.json'), project='forever-clean',
                 image='pinned-image', certs=str(root / 'certs'), client={'exe_build': 70658}, phase='ready')
    model = dict(name='forever-clean', services={
        'worldserver': dict(image='pinned-image', command=['worldserver'], environment={'DB_PASSWORD': 'private-test'},
                            volumes=[{'source': 'owned-data', 'target': '/data'}]),
        'mysql': dict(volumes=['retained-database'], environment={'MYSQL_ROOT_PASSWORD': 'private-test'})},
                 volumes={'mysql-data': {}}, networks={'clean': {}})
    Path(state['compose']).write_text(json.dumps(model))
    return state, model


class CleanNetworkTests(unittest.TestCase):
    def test_missing_port_recreates_only_world_and_preserves_every_other_field(self):
        with tempfile.TemporaryDirectory() as temp:
            state, before = fixture(Path(temp))
            after = copy.deepcopy(before); after['services']['worldserver']['ports'] = [network.EXPECTED]
            report = dict(world_published=True, host_checks={'world_tcp': {'ready': True}}, databases_reset=False)
            with patch.object(network, 'world_bindings', return_value=[]), \
                 patch.object(network.clean, 'compose') as compose, \
                 patch.object(network.clean, 'wait_world') as wait, \
                 patch.object(network, 'status', return_value=report), \
                 patch.object(network.socket, 'socket'):
                result = network.repair(state)
            self.assertEqual(json.loads(Path(state['compose']).read_text()), after)
            self.assertEqual(json.loads(Path(result['backup']).read_text()), before)
            self.assertTrue(result['changed'])
            self.assertNotIn('private-test', json.dumps(result))
            self.assertEqual(compose.call_args_list[1].args[1:],
                             ('up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver'))
            self.assertEqual(compose.call_count, 2)
            wait.assert_called_once_with(state, 180)

    def test_existing_world_publication_is_a_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            state, _ = fixture(Path(temp)); before = Path(state['compose']).read_bytes()
            with patch.object(network, 'world_bindings', return_value=[{'address': '127.0.0.1', 'port': '8085'}]), \
                 patch.object(network, 'status', return_value={}), patch.object(network.clean, 'compose') as compose:
                result = network.repair(state)
            self.assertFalse(result['changed'])
            compose.assert_not_called()
            self.assertEqual(Path(state['compose']).read_bytes(), before)

    def test_port_owned_by_another_process_stops_without_changing_any_service(self):
        with tempfile.TemporaryDirectory() as temp:
            state, _ = fixture(Path(temp)); before = Path(state['compose']).read_bytes()
            with patch.object(network, 'world_bindings', return_value=[]), \
                 patch.object(network.socket, 'socket') as sock, patch.object(network.clean, 'compose') as compose:
                sock.return_value.__enter__.return_value.bind.side_effect = OSError('occupied')
                with self.assertRaisesRegex(ValueError, 'occupied'): network.repair(state)
            compose.assert_not_called()
            self.assertEqual(Path(state['compose']).read_bytes(), before)
            self.assertFalse((Path(temp) / 'network-backups').exists())

    def test_failed_recreate_restores_exact_private_compose(self):
        with tempfile.TemporaryDirectory() as temp:
            state, _ = fixture(Path(temp)); before = Path(state['compose']).read_bytes()
            with patch.object(network, 'world_bindings', return_value=[]), patch.object(network.socket, 'socket'), \
                 patch.object(network.clean, 'compose', side_effect=[None, RuntimeError('failed'), None]):
                with self.assertRaisesRegex(RuntimeError, 'failed'): network.repair(state)
            self.assertEqual(Path(state['compose']).read_bytes(), before)

    def test_unexpected_image_cannot_be_redeployed(self):
        with tempfile.TemporaryDirectory() as temp:
            state, _ = fixture(Path(temp)); state['image'] = 'another-image'
            with patch.object(network.clean, 'compose') as compose, self.assertRaisesRegex(ValueError, 'Unexpected'):
                network.repair(state)
            compose.assert_not_called()

    def test_only_actual_loopback_publication_counts(self):
        self.assertFalse(network.published([]))
        self.assertFalse(network.published([dict(address='0.0.0.0', port='8085')]))
        self.assertTrue(network.published([dict(address='127.0.0.1', port='8085')]))


if __name__ == '__main__': unittest.main()
