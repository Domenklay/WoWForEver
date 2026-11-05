#!/usr/bin/env python3
"""Add a localhost IP SAN to the existing server certificate, keeping its CA and private key."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time

HOST = 'trinity.actual.battle.net'
IP = '127.0.0.1'


def command(args, *, timeout=20, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs).stdout


def compose(state):
    return ['docker', 'compose', '-p', state['project'], '-f', state['compose']]


def load_state(path):
    state = json.loads(path.read_text())
    if state.get('format') != 'wowforever-server-refresh-v1' or state.get('phase') != 'ready':
        raise ValueError('Expected the ready server-refresh state.json')
    model = json.loads(Path(state['compose']).read_text())
    mounts = [m for m in model['services']['bnetserver']['volumes']
              if m.get('target') == '/opt/trinitycore/certs' and m.get('type') == 'bind']
    if len(mounts) != 1:
        raise ValueError('Expected one existing certificate directory bind')
    return state, Path(mounts[0]['source']).resolve(strict=True)


def sans(text):
    entries = []
    for token in ' '.join(text.splitlines()[1:]).split(','):
        token = token.strip()
        if not token:
            continue
        if token.startswith('DNS:') and re.fullmatch(r'[A-Za-z0-9.*_-]+', token[4:]):
            item = token
        elif token.startswith('IP Address:'):
            item = 'IP:' + str(ipaddress.ip_address(token[len('IP Address:'):]))
        else:
            raise ValueError('Unsupported existing SAN; certificate was not replaced')
        if item not in entries:
            entries.append(item)
    if 'DNS:' + HOST not in entries:
        raise ValueError('Existing certificate does not contain the expected server hostname')
    return entries


def verify(cert_dir, chain, *, ip=False):
    args = ['openssl', 'verify', '-CAfile', str(cert_dir / 'ca/forever_root_ca.crt'),
            '-verify_ip' if ip else '-verify_hostname', IP if ip else HOST, str(chain)]
    command(args)


def make_chain(cert_dir, work):
    cert = cert_dir / 'forever.cert.pem'
    key = cert_dir / 'forever.key.pem'
    root = cert_dir / 'ca/forever_root_ca.crt'
    ca_key = cert_dir / 'ca/forever_root_ca.key'
    for path in (cert, key, root, ca_key):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Required original certificate/key is missing or linked: ' + str(path))
    verify(cert_dir, cert)
    public = command(['openssl', 'x509', '-in', str(cert), '-noout', '-pubkey'])
    key_public = command(['openssl', 'pkey', '-in', str(key), '-passin', 'pass:', '-pubout'])
    if public.strip() != key_public.strip():
        raise ValueError('Existing server certificate and key do not match')
    entries = sans(command(['openssl', 'x509', '-in', str(cert), '-noout', '-ext', 'subjectAltName']))
    if 'IP:' + IP in entries:
        verify(cert_dir, cert, ip=True)
        return None
    entries.append('IP:' + IP)
    extensions = work / 'server.ext'
    extensions.write_text('basicConstraints=critical,CA:FALSE\n'
                          'keyUsage=critical,digitalSignature,keyEncipherment\n'
                          'extendedKeyUsage=serverAuth\nsubjectAltName=' + ','.join(entries) + '\n')
    # Preserve the existing subject and server private key. No new CA, no copied private keys.
    csr = work / 'server.csr'
    command(['openssl', 'x509', '-x509toreq', '-in', str(cert), '-signkey', str(key),
             '-passin', 'pass:', '-out', str(csr)])
    leaf = work / 'server.crt'
    command(['openssl', 'x509', '-req', '-in', str(csr), '-CA', str(root), '-CAkey', str(ca_key),
             '-passin', 'pass:', '-set_serial', '0x' + secrets.token_hex(16), '-days', '825',
             '-sha256', '-extfile', str(extensions), '-out', str(leaf)])
    chain = work / 'chain.pem'
    chain.write_bytes(leaf.read_bytes().rstrip() + b'\n' + root.read_bytes().rstrip() + b'\n')
    verify(cert_dir, chain)
    verify(cert_dir, chain, ip=True)
    return chain.read_bytes()


def replace_cert(cert_dir, content):
    with tempfile.NamedTemporaryFile(dir=cert_dir, prefix='.localhost-cert-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, cert_dir / 'forever.cert.pem')
        finally:
            temporary.unlink(missing_ok=True)


def restart(state):
    command(compose(state) + ['restart', '--no-deps', 'bnetserver'])


def live_verify(state):
    args = compose(state) + ['exec', '-T', 'bnetserver', 'openssl', 's_client',
            '-connect', IP + ':1119', '-servername', HOST, '-verify_ip', IP,
            '-CAfile', '/opt/trinitycore/certs/ca/forever_root_ca.crt', '-verify_return_error', '-brief']
    for attempt in range(20):
        try:
            command(args, input='', timeout=5)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 19:
                raise RuntimeError('Live TLS verification failed after bnetserver restart')
            if attempt % 5 == 0:
                print('Waiting for bnetserver TLS...', flush=True)
            time.sleep(2)


def apply(state_path):
    state, cert_dir = load_state(state_path)
    if not command(compose(state) + ['ps', '-q', 'bnetserver']).strip():
        raise ValueError('Expected the running refreshed bnetserver')
    old = (cert_dir / 'forever.cert.pem').read_bytes()
    with tempfile.TemporaryDirectory(prefix='.local-login-', dir=cert_dir) as temporary:
        content = make_chain(cert_dir, Path(temporary))
    if content is None:
        live_verify(state)
        print('LOCAL TLS ALREADY OK: existing certificate accepts ' + HOST + ' and ' + IP)
        return
    backup = Path(state['backup']).parent / ('local-login-cert-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
    backup.mkdir(mode=0o700)
    (backup / 'certificate.before.pem').write_bytes(old)
    record = {'format': 'wowforever-local-login-cert-v1', 'state': str(state_path.resolve()),
              'new_sha256': hashlib.sha256(content).hexdigest()}
    (backup / 'repair.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Backup: ' + str(backup), flush=True)
    if (cert_dir / 'forever.cert.pem').read_bytes() != old:
        raise RuntimeError('Certificate changed concurrently; no replacement was made')
    try:
        replace_cert(cert_dir, content)
        print('Certificate updated. Restarting only bnetserver...', flush=True)
        restart(state)
        live_verify(state)
    except BaseException:
        replace_cert(cert_dir, old)
        print('Repair failed; original certificate restored.', file=sys.stderr)
        restart(state)
        raise
    print('LOCAL TLS OK: same CA and server key; certificate accepts ' + HOST + ' and ' + IP)
    print('Rollback: ' + shlex.join([sys.executable, str(Path(__file__).resolve()), 'rollback', '--backup', str(backup)]))


def rollback(backup):
    record = json.loads((backup / 'repair.json').read_text())
    if record.get('format') != 'wowforever-local-login-cert-v1':
        raise ValueError('Expected a local login certificate backup')
    state, cert_dir = load_state(Path(record['state']))
    current = (cert_dir / 'forever.cert.pem').read_bytes()
    previous = (backup / 'certificate.before.pem').read_bytes()
    if current == previous:
        print('Original certificate is already restored.')
        return
    if hashlib.sha256(current).hexdigest() != record['new_sha256']:
        raise ValueError('Certificate changed after this repair; automatic rollback refused')
    replace_cert(cert_dir, previous)
    restart(state)
    print('Original certificate restored; databases and worldserver were not changed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('apply').add_argument('--state', type=Path, required=True)
    sub.add_parser('rollback').add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'apply':
        lock_dir = args.state.resolve().parent.parent
    else:
        lock_dir = args.backup.resolve().parent
    with (lock_dir / 'content-port.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        apply(args.state) if args.action == 'apply' else rollback(args.backup)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('Stopped: ' + (str(error) or 'interrupted'), file=sys.stderr)
        sys.exit(1)
