#!/usr/bin/env python3
"""Safe 70658 FDF-only worldserver rebuild/swap. No database migrations."""
import argparse
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = Path.home() / 'WoWForEver-clean'
EXPECTED_SOURCE_PREFIX = 'af619309eb0e'
EXPECTED_IMAGE = 'forever-trinitycore:gameplay-70658-af619309eb0e'
FMT = 'forever-fdf-diagnostic-hotfix-v1'

def load_tools():
    spec = importlib.util.spec_from_file_location('fdf_gameplay_tool', ROOT / 'scripts/enable-clean-gameplay.py')
    game = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(game)
    return game

def check_state(game, state, *, new=False):
    if (state.get('project') != 'forever-clean' or state.get('core') != game.clean.CORE
        or state.get('phase') != 'ready' or state.get('client', {}).get('exe_build') != 70658
        or state.get('advancement', {}).get('version') != '1.13.0'
        or state.get('gameplay', {}).get('scaling') != '0.4.0'
        or state.get('gameplay', {}).get('dungeonfinder') != '0.2.0'
        or state.get('database_version') != 'gameplay-1.13@pristine-b4e7b940593f'):
        raise ValueError('Expected pinned 70658 / Ascension 1.13 / Scaling 0.4 / FDF 0.2')
    if not new and (state['image'] != EXPECTED_IMAGE or not state['gameplay']['source_sha256'].startswith(EXPECTED_SOURCE_PREFIX)):
        raise ValueError('Active gameplay identity differs from documented baseline; no changes made')
    if not new and any((Path(state['root']) / name).exists() for name in
            ('.gameplay-in-progress.json', '.gameplay-upgrade-in-progress.json',
             '.upgrade-in-progress.json', '.fdf-hotfix-in-progress.json')):
        raise ValueError('Another server update is in progress')

def has_ping(image):
    # Version-specific long log markers distinguish this upgrade from the
    # already-running first diagnostic image. Short PONG may be optimized away.
    binary = '/opt/trinitycore/bin/worldserver'
    check = ('grep -aqF "ForeverDungeonFinder transport-v2 received:" ' + binary +
             ' && grep -aqF "ForeverDungeonFinder v2 response:" ' + binary)
    result = subprocess.run(
        ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', '/bin/sh', image,
         '-c', check],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode not in (0, 1):
        raise ValueError('Docker could not inspect the candidate worldserver binary')
    return result.returncode == 0

def read_record(root, filename):
    directory = (root / 'fdf-hotfix').resolve()
    path = filename.resolve(strict=True)
    if path.parent.parent != directory or path.name != 'record.json':
        raise ValueError('Record outside fdf-hotfix directory')
    record = json.loads(path.read_text())
    if record.get('format') != FMT or record.get('root') != str(root) or record.get('directory') != str(path.parent):
        raise ValueError('Invalid FDF hotfix record')
    return record

def save_record(game, record):
    game.clean.write_private(Path(record['directory']) / 'record.json', record)

def prepare(game, root, jobs):
    before = game.clean.load_state(root / 'state.json')
    check_state(game, before)
    existing_compose = (root / 'compose.private.json').read_text()
    model = json.loads(existing_compose)
    if model['services']['worldserver']['image'] != before['image']:
        raise ValueError('Worldserver Compose image differs from saved state')
    live = game.clean.container(before, 'worldserver')
    if not live or not live['State']['Running'] or live['Config']['Image'] != before['image']:
        raise ValueError('Unexpected running worldserver; no changes made')
    game.check_image(game.adv.image(before['image']), before)
    if has_ping(before['image']):
        raise ValueError('Old image already contains FDF transport-v2; inspect deployed worldserver')
    game.wait_module(before)
    if game.adv.source_id() != before['advancement']['source_sha256']:
        raise ValueError('Advancement source differs from installed version')
    candidate = game.build(before, jobs)
    game.check_image(game.adv.image(candidate), before, candidate=True)
    if not has_ping(candidate):
        raise ValueError('New worldserver lacks FDF transport-v2 markers; live service unchanged')
    if (game.clean.load_state(root / 'state.json') != before
        or (root / 'compose.private.json').read_text() != existing_compose):
        raise ValueError('Live server changed during compilation; no swap performed')
    folder = root / 'fdf-hotfix' / secrets.token_hex(6)
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(format=FMT, root=str(root), directory=str(folder), phase='prepared',
                  before_state=before, before_compose=existing_compose,
                  candidate=candidate, candidate_id=game.adv.image(candidate)['Id'],
                  source_sha256=game.source_id(), advancement_sha256=game.adv.source_id())
    save_record(game, record)
    print('FDF PREPARED: ' + str(folder / 'record.json'), flush=True)
    return record

def rollback(game, root, record):
    before = record['before_state']
    current = game.clean.load_state(root / 'state.json')
    current_compose = json.loads((root / 'compose.private.json').read_text())
    allowed = (before['image'], record['candidate'])
    if current['image'] not in allowed or current_compose['services']['worldserver']['image'] not in allowed:
        raise ValueError('Server changed separately; automatic rollback refused')
    game.clean.write_private(root / 'compose.private.json', json.loads(record['before_compose']))
    game.clean.save(before)
    game.clean.compose(before, 'config', '-q')
    game.clean.compose(before, 'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver')
    game.wait_module(before)
    (root / '.fdf-hotfix-in-progress.json').unlink(missing_ok=True)
    record['phase'] = 'rolled-back'
    save_record(game, record)
    print('FDF ROLLBACK OK: old worldserver restored; databases untouched.', flush=True)

def apply(game, root, record):
    if record['phase'] != 'prepared':
        raise ValueError('Record not in prepared state')
    before = record['before_state']
    check_state(game, before)
    if (game.clean.load_state(root / 'state.json') != before
        or (root / 'compose.private.json').read_text() != record['before_compose']):
        raise ValueError('Server state changed since build; no changes made')
    if game.source_id() != record['source_sha256'] or game.adv.source_id() != record['advancement_sha256']:
        raise ValueError('Source changed since build')
    if game.adv.image(record['candidate'])['Id'] != record['candidate_id'] or not has_ping(record['candidate']):
        raise ValueError('Candidate Docker image changed or lacks FDF transport-v2')
    marker = root / '.fdf-hotfix-in-progress.json'
    if marker.exists():
        raise ValueError('Another FDF update is in progress')
    new_state = copy.deepcopy(before)
    new_state['image'] = record['candidate']
    new_state['gameplay']['source_sha256'] = record['source_sha256']
    new_model = json.loads(record['before_compose'])
    new_model['services']['worldserver']['image'] = record['candidate']
    game.clean.write_private(marker, {'record': str(Path(record['directory']) / 'record.json')})
    record['phase'] = 'switching'
    save_record(game, record)
    try:
        game.clean.write_private(root / 'compose.private.json', new_model)
        game.clean.compose(new_state, 'config', '-q')
        game.clean.compose(new_state, 'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver')
        game.wait_module(new_state)
        if not has_ping(new_state['image']):
            raise RuntimeError('FDF transport-v2 absent from active image')
        game.clean.save(new_state)
        record['phase'] = 'active'
        save_record(game, record)
        marker.unlink()
        print('FDF HOTFIX ACTIVE: updated worldserver, no database migrations.', flush=True)
        print('ROLLBACK RECORD: ' + str(Path(record['directory']) / 'record.json'), flush=True)
    except BaseException:
        try:
            rollback(game, root, record)
        except Exception as error:
            print('Automatic rollback incomplete: ' + str(error), file=sys.stderr)
            print('Recovery record: ' + str(Path(record['directory']) / 'record.json'), file=sys.stderr)
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'install', 'rollback'))
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, 9))
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    root = SERVER_ROOT.resolve(strict=True)
    game = load_tools()
    lock = Path.home() / '.cache/forever-clean-control.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action in ('prepare', 'install'):
            record = prepare(game, root, args.jobs)
            if args.action == 'install':
                apply(game, root, record)
        else:
            if not args.record:
                parser.error('--record is required')
            record = read_record(root, args.record)
            if args.action == 'apply':
                apply(game, root, record)
            else:
                rollback(game, root, record)

if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('FDF HOTFIX STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
