import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('local_login_cert', ROOT / 'scripts/repair-local-login-cert.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL is required')
class LocalLoginCertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.fixture_temp.name)
        ca = cls.fixture / 'ca'
        ca.mkdir()
        repair.command(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
                        '-keyout', str(ca / 'forever_root_ca.key'), '-out', str(ca / 'forever_root_ca.crt'),
                        '-subj', '/CN=Test Private Root', '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
                        '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-addext',
                        'nameConstraints=critical,permitted;DNS:actual.battle.net'])
        repair.command(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(cls.fixture / 'forever.key.pem'), '-out', str(cls.fixture / 'request.csr'),
                        '-subj', '/CN=trinity.actual.battle.net'])
        ext = cls.fixture / 'extensions'
        ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                       'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:trinity.actual.battle.net,DNS:*.actual.battle.net\n')
        leaf = cls.fixture / 'leaf.pem'
        repair.command(['openssl', 'x509', '-req', '-in', str(cls.fixture / 'request.csr'),
                        '-CA', str(ca / 'forever_root_ca.crt'), '-CAkey', str(ca / 'forever_root_ca.key'),
                        '-set_serial', '1', '-days', '2', '-extfile', str(ext), '-out', str(leaf)])
        (cls.fixture / 'forever.cert.pem').write_bytes(leaf.read_bytes() + (ca / 'forever_root_ca.crt').read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def setup_files(self, root):
        certs = root / 'certs'
        shutil.copytree(self.fixture, certs)
        backups = root / 'backups'
        state_dir = backups / 'server-refresh'
        state_dir.mkdir(parents=True)
        compose = state_dir / 'compose.private.json'
        compose.write_text(json.dumps({'services': {'bnetserver': {'volumes': [
            {'type': 'bind', 'source': str(certs), 'target': '/opt/trinitycore/certs'}]}}}))
        state = state_dir / 'state.json'
        state.write_text(json.dumps({'format': 'wowforever-server-refresh-v1', 'phase': 'ready',
                                     'project': 'forever-refresh-70658', 'compose': str(compose),
                                     'backup': str(state_dir)}))
        return certs, state

    def test_adds_ip_preserves_dns_and_ca_and_server_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, _ = self.setup_files(root)
            paths = ['forever.key.pem', 'ca/forever_root_ca.key', 'ca/forever_root_ca.crt']
            before = {p: (certs / p).read_bytes() for p in paths}
            with self.assertRaises(subprocess.CalledProcessError):
                repair.verify(certs, certs / 'forever.cert.pem', ip=True)
            content = repair.make_chain(certs, root)
            candidate = root / 'candidate.pem'
            candidate.write_bytes(content)
            repair.verify(certs, candidate)
            repair.verify(certs, candidate, ip=True)
            output = repair.command(['openssl', 'x509', '-in', str(candidate), '-noout', '-ext', 'subjectAltName'])
            self.assertIn('DNS:*.actual.battle.net', output)
            self.assertIn('IP Address:127.0.0.1', output)
            for p in paths:
                self.assertEqual((certs / p).read_bytes(), before[p])

    def test_wrong_certificate_key_pair_is_rejected_before_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, _ = self.setup_files(root)
            before = (certs / 'forever.cert.pem').read_bytes()
            shutil.copy2(certs / 'ca/forever_root_ca.key', certs / 'forever.key.pem')
            with self.assertRaisesRegex(ValueError, 'do not match'):
                repair.make_chain(certs, root)
            self.assertEqual((certs / 'forever.cert.pem').read_bytes(), before)

    def test_apply_restart_failure_restores_original_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, state = self.setup_files(root)
            before = (certs / 'forever.cert.pem').read_bytes()
            original_command = repair.command
            def command(args, **kwargs):
                return 'fixture-bnet' if args[0] == 'docker' else original_command(args, **kwargs)
            with patch.object(repair, 'command', side_effect=command), \
                    patch.object(repair, 'restart', side_effect=[RuntimeError('restart failed'), None]) as restarted, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'restart failed'):
                    repair.apply(state)
            self.assertEqual(restarted.call_count, 2)
            self.assertEqual((certs / 'forever.cert.pem').read_bytes(), before)

    def test_apply_and_rollback_retain_original_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, state = self.setup_files(root)
            before = (certs / 'forever.cert.pem').read_bytes()
            original_command = repair.command
            def command(args, **kwargs):
                return 'fixture-bnet' if args[0] == 'docker' else original_command(args, **kwargs)
            with patch.object(repair, 'command', side_effect=command), \
                    patch.object(repair, 'restart') as restarted, patch.object(repair, 'live_verify') as live, \
                    contextlib.redirect_stdout(io.StringIO()):
                repair.apply(state)
                live.assert_called_once()
                self.assertNotEqual((certs / 'forever.cert.pem').read_bytes(), before)
                backup = next((root / 'backups').glob('local-login-cert-*'))
                repair.rollback(backup)
                self.assertEqual(restarted.call_count, 2)
                self.assertEqual((certs / 'forever.cert.pem').read_bytes(), before)

    def test_live_tls_accepts_ip_with_normal_certificate_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, _ = self.setup_files(root)
            chain = root / 'candidate.pem'
            chain.write_bytes(repair.make_chain(certs, root))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            server = subprocess.Popen(['openssl', 's_server', '-quiet', '-accept', str(port),
                                       '-cert', str(chain), '-key', str(certs / 'forever.key.pem')],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(40):
                    try:
                        with socket.create_connection(('127.0.0.1', port), 0.2):
                            break
                    except OSError:
                        time.sleep(0.05)
                result = repair.command(['openssl', 's_client', '-connect', '127.0.0.1:' + str(port),
                                         '-servername', repair.HOST, '-verify_ip', repair.IP,
                                         '-CAfile', str(certs / 'ca/forever_root_ca.crt'),
                                         '-verify_return_error', '-brief'], input='')
                self.assertIsInstance(result, str)
            finally:
                server.terminate()
                server.wait(timeout=5)

    def test_restart_targets_only_bnetserver(self):
        with patch.object(repair, 'command') as called:
            repair.restart({'project': 'test-clone', 'compose': '/private/compose.json'})
            self.assertEqual(called.call_args.args[0][-3:], ['restart', '--no-deps', 'bnetserver'])

    def test_repeated_apply_reuses_already_valid_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            certs, _ = self.setup_files(root)
            repair.replace_cert(certs, repair.make_chain(certs, root))
            before = (certs / 'forever.cert.pem').read_bytes()
            self.assertIsNone(repair.make_chain(certs, root))
            self.assertEqual((certs / 'forever.cert.pem').read_bytes(), before)

    def test_san_parser_rejects_unhandled_names_without_dropping_them(self):
        with self.assertRaises(ValueError):
            repair.sans('X509v3 Subject Alternative Name:\n DNS:trinity.actual.battle.net, email:user@example.com')


if __name__ == '__main__':
    unittest.main()
