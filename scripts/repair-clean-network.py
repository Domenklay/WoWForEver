#!/usr/bin/env python3
"""Inspect/repair loopback world-port publication on an existing ready 70658 server.

No database import, build change, image build, volume deletion or client edits.
Only the owned worldserver is recreated. Private Compose backups stay local.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import sys

spec = importlib.util.spec_from_file_location('network_clean', Path(__file__).with_name('clean-forever-server.py'))
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)
EXPECTED = '127.0.0.1:8085:8085'


def command_error(state, error):
    """Expose the Docker operation and stderr, never resolved credentials."""
    if not isinstance(error, clean.CommandFailure):
        return str(error)
    command = error.command
    if command[:2] == ('docker', 'compose'):
        # Skip -p PROJECT -f PRIVATE_PATH, and never echo exec arguments/SQL.
        operation = command[6] if len(command) > 6 else 'unknown'
        label = 'docker compose ' + operation
    else:
        label = ' '.join(command[:2])
    text = error.stderr
    secrets_to_hide = set(str(v) for v in state.get('credentials', {}).values() if v)
    try:
        model = json.loads(Path(state['compose']).read_bytes())
        for service in model.get('services', {}).values():
            env = service.get('environment', {})
            entries = env.items() if isinstance(env, dict) else (item.split('=', 1) for item in env if '=' in item)
            for key, value in entries:
                if value and re.search(r'password|passwd|secret|token|credential', key, re.I):
                    secrets_to_hide.add(str(value))
    except (OSError, ValueError, TypeError):
        # Without the model we cannot safely expose arbitrary Compose errors.
        text = '(Docker details withheld: private Compose could not be read)'
    for secret in sorted(secrets_to_hide, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)((?:password|passwd|secret|token)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return f'{label} failed (exit {error.returncode}): ' + (text.strip()[-6000:] or '(Docker returned no stderr)')


def checked(root):
    root = root.resolve(strict=True)
    if (root / '.upgrade-in-progress.json').exists():
        raise ValueError('Recover the interrupted server upgrade first')
    state = clean.load_state(root / 'state.json')
    if state['phase'] != 'ready' or state['client']['exe_build'] != 70658:
        raise ValueError('This repair requires an existing ready 70658 installation')
    return state


def world_bindings(state):
    item = clean.container(state, 'worldserver')
    ports = (item or {}).get('NetworkSettings', {}).get('Ports', {}).get('8085/tcp') or []
    return [dict(address=p.get('HostIp'), port=p.get('HostPort')) for p in ports]


def published(bindings):
    return any(p == dict(address='127.0.0.1', port='8085') for p in bindings)


def host_health(state):
    result = {}
    context = ssl.create_default_context(cafile=str(Path(state['certs']) / 'ca/forever_root_ca.crt'))
    for name, port in [('bnet_tls', 1119), ('rest_tls', 8081), ('world_tcp', 8085)]:
        try:
            with socket.create_connection(('127.0.0.1', port), 4) as stream:
                if name.endswith('_tls'):
                    with context.wrap_socket(stream, server_hostname='trinity.actual.battle.net'):
                        pass
            result[name] = dict(ready=True)
        except OSError as error:
            result[name] = dict(ready=False, detail=str(error))
    return result


def status(state):
    bindings = world_bindings(state)
    return dict(format='forever-clean-network-v1', client_build=70658, world_bindings=bindings,
                world_published=published(bindings), host_checks=host_health(state), databases_reset=False)


def repair(state):
    path = Path(state['compose'])
    if path.is_symlink(): raise ValueError('Linked Compose file is unsupported')
    original = path.read_bytes()
    model = json.loads(original)
    if model.get('name') != state['project']:
        raise ValueError('Compose project differs from the ready server state')
    service = model['services']['worldserver']
    if service.get('image') != state['image'] or service.get('command') != ['worldserver']:
        raise ValueError('Unexpected worldserver image or command')
    bindings = world_bindings(state)
    if published(bindings):
        report = status(state)
        report.update(changed=False, note='World loopback publication already exists; no service recreated')
        return report
    # Do not stop or steal a port from another process or Compose project.
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', 8085))
        except OSError as error: raise ValueError('Host 127.0.0.1:8085 is occupied; no service changed') from error
    folder = Path(state['root']) / 'network-backups'
    if folder.is_symlink(): raise ValueError('Linked backup directory is unsupported')
    folder.mkdir(mode=0o700, exist_ok=True)
    backup = folder / ('compose-' + secrets.token_hex(6) + '.json')
    with backup.open('xb') as stream:
        os.chmod(backup, 0o600)
        stream.write(original)
    # Keep every other service, mount, credential, network and volume unchanged.
    service['ports'] = [EXPECTED]
    clean.write_private(path, model)
    recreate_started = False
    try:
        clean.compose(state, 'config', '-q')
        recreate_started = True
        clean.compose(state, 'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver')
        clean.wait_world(state, 180)
        report = status(state)
        if not report['world_published'] or not report['host_checks']['world_tcp']['ready']:
            raise RuntimeError('Worldserver did not acquire the required host loopback port')
        report.update(changed=True, backup=str(backup), note='Only worldserver publication repaired; MySQL, accounts, characters, TLS identity and client build retained')
        return report
    except Exception as failure:
        # Restore the exact private input, not a newly generated deployment.
        temp = path.with_suffix('.rollback')
        with temp.open('xb') as stream:
            os.chmod(temp, 0o600)
            stream.write(original)
        temp.replace(path)
        if not recreate_started:
            # Invalid Compose never reached Docker up; leave running services alone.
            raise
        try: clean.compose(state, 'up', '-d', '--no-build', '--no-deps', 'worldserver')
        except Exception as rollback:
            raise RuntimeError(command_error(state, failure) + '\nOriginal Compose restored, but restarting worldserver also failed: '
                               + command_error(state, rollback)) from failure
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'apply'))
    parser.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    args = parser.parse_args()
    os.umask(0o077)
    state = checked(args.root)
    if args.action == 'status':
        try: report = status(state)
        except clean.CommandFailure as error: raise RuntimeError(command_error(state, error)) from error
    else:
        lock_path = Path.home() / '.cache/forever-clean-control.lock'
        lock_path.parent.mkdir(exist_ok=True)
        with lock_path.open('a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another clean-server operation is running')
            # Revalidate while holding the lifecycle lock.
            state = checked(args.root)
            if (Path(state['root']) / '.advancement-in-progress.json').exists():
                raise ValueError('Recover the interrupted Advancement installation before network changes')
            try: report = repair(state)
            except clean.CommandFailure as error: raise RuntimeError(command_error(state, error)) from error
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print('Clean network repair stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
