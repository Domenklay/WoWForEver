#!/usr/bin/env python3
"""Install existing gameplay modules on ready 70658, preserving databases and TLS."""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gameplay_advancement', ROOT / 'scripts/enable-clean-advancement.py')
adv = importlib.util.module_from_spec(spec); spec.loader.exec_module(adv)
clean, network, upgrade = adv.clean, adv.network, adv.upgrade
FORMAT = 'forever-clean-gameplay-v1'
MARKER = '.gameplay-in-progress.json'
BOOK_VERSION = '0.9.8-v2.1-smartai-abilities'
SCALING_VERSION = '0.4.0'
FINDER_VERSION = '0.2.0'
CURRENT_ROOT = None


def source_id():
    paths = [p for folder in ('mods/forever-advancement/server', 'mods/forever-advancement/sql',
             'mods/living-encyclopedia/server', 'mods/living-encyclopedia/sql', 'mod-forever-scaling/server', 'mods/forever-dungeon-finder/server')
             for p in sorted((ROOT / folder).glob('*')) if p.is_file()]
    paths += [ROOT / p for p in ('scripts/inject-advancement.py', 'scripts/inject-gameplay.py',
              'scripts/inject-forever-scaling.py', 'scripts/inject-forever-dungeons.py', 'scripts/inject-forever-dungeon-finder.py', 'docker/gameplay/Dockerfile', 'docker/clean/entrypoint.py',
              'docker/patches/0004-forever-subclass-server-addon-endpoint.patch')]
    digest = hashlib.sha256()
    for p in paths: digest.update(str(p.relative_to(ROOT)).encode() + b'\0' + p.read_bytes() + b'\0')
    return digest.hexdigest()


def check_image(item, state, candidate=False):
    labels = item.get('Config', {}).get('Labels', {})
    previous = state.get('advancement', {})
    if labels.get('org.wowforever.core') != state['core']:
        raise ValueError('Image uses another core revision')
    expected = adv.VERSION if candidate else previous.get('version', 'none')
    if labels.get('org.wowforever.advancement') != expected:
        raise ValueError('Image does not match the saved Advancement state')
    if candidate:
        if (labels.get('org.wowforever.gameplay.source') != source_id()
            or labels.get('org.wowforever.advancement.source') != adv.source_id()
            or labels.get('org.wowforever.encyclopedia') != BOOK_VERSION
            or labels.get('org.wowforever.scaling') != SCALING_VERSION
            or labels.get('org.wowforever.dungeonfinder') != FINDER_VERSION):
            raise ValueError('Candidate module source/version labels do not match')
    elif previous and labels.get('org.wowforever.advancement.source') != previous['source_sha256']:
        raise ValueError('Active Advancement image differs from its saved identity')


def built_candidate(state, required=False):
    candidate = 'forever-trinitycore:gameplay-70658-' + source_id()[:12]
    try: cached = adv.image(candidate)
    except clean.CommandFailure:
        if required: raise ValueError('The matching built gameplay image is unavailable; no compilation or service changes were started')
        cached = None
    if cached is not None:
        check_image(cached, state, True)
        print('Reusing the verified built gameplay image; compilation skipped: ' + candidate, flush=True)
        return candidate
    return None


def build(state, jobs):
    cached = built_candidate(state)
    if cached: return cached
    old = adv.image(state['image']); check_image(old, state)
    runtime = 'forever-trinitycore:before-gameplay-' + old['Id'].split(':')[-1][:12]
    base = 'forever-trinitycore:gameplay-build-base-' + state['core'][:12]
    clean.run(['docker', 'tag', old['Id'], runtime])
    clean.run(['docker', 'build', '--progress=plain', '--target', 'build', '-f', str(ROOT / 'docker/clean/Dockerfile'),
               '--build-arg', 'TC_COMMIT=' + state['core'], '--build-arg', f'BUILD_JOBS={jobs}', '-t', base, str(ROOT)])
    candidate = 'forever-trinitycore:gameplay-70658-' + source_id()[:12]
    clean.run(['docker', 'build', '--progress=plain', '-f', str(ROOT / 'docker/gameplay/Dockerfile'),
               '--build-arg', 'CLEAN_BUILD_IMAGE=' + base, '--build-arg', 'CLEAN_RUNTIME_IMAGE=' + runtime,
               '--build-arg', 'GAMEPLAY_SOURCE=' + source_id(), '--build-arg', 'ADVANCEMENT_SOURCE=' + adv.source_id(),
               '--build-arg', f'BUILD_JOBS={jobs}', '-t', candidate, str(ROOT)])
    check_image(adv.image(candidate), state, True)
    return candidate


def configure(before, model, candidate, folder, scaling=True):
    target, result = adv.configure(before, model, candidate, folder)
    target['database_version'] = 'gameplay-1@' + before.get('database_version', 'pristine-' + before['core'][:12])
    target['gameplay'] = dict(version=1, source_sha256=source_id(), encyclopedia=BOOK_VERSION,
                              scaling=SCALING_VERSION if scaling else None, dungeonfinder=FINDER_VERSION, backup=str(folder / 'install.json'))
    result['services']['worldserver']['environment'].update(
        FOREVER_ENCYCLOPEDIA_ENABLED='1', FOREVER_SCALING_ENABLED='1' if scaling else '0',
        FOREVER_SCALING_DAMAGE_GUARD='1', FOREVER_SCALING_MIN_OFFSET='-3',
        FOREVER_DUNGEON_SCALING_ENABLED='0', FOREVER_DUNGEON_FINDER_ENABLED='0', FOREVER_SCALING_CREATURE_MAX_LEVEL='70')
    return target, result


def wait_module(state, timeout=180):
    patterns = list(adv.ready_patterns(state)) + ['ForeverEncyclopedia ready:']
    if state['gameplay'].get('scaling'):
        version = state['gameplay']['scaling'].rsplit('.', 1)[0]
        patterns.append('ForeverScaling ready: personal-virtual-v' + version + ' (enabled=true')
    return adv.module_readiness.wait(clean, state, patterns, timeout)


def checkpoint(record, phase):
    record['phase'] = phase
    clean.write_private(Path(record['directory']) / 'install.json', record)
    print('Gameplay: ' + phase, flush=True)


def load_backup(root, path):
    path = upgrade.direct(path)
    if path.parent.parent != root / 'advancement' or not re.fullmatch('[0-9a-f]{12}', path.parent.name):
        raise ValueError('Backup must belong to this server')
    r = json.loads(path.read_text())
    if (r.get('format') != FORMAT or r['root'] != str(root) or r['directory'] != str(path.parent)
        or r['before']['root'] != str(root) or r['before']['compose'] != str(root / 'compose.private.json')
        or upgrade.digest(r['before']) != r['before_digest']
        or hashlib.sha256(r['compose_before'].encode()).hexdigest() != r['compose_digest']):
        raise ValueError('Backup identity or checksum mismatch')
    return r


def rollback(record):
    root = Path(record['root']); marker = root / MARKER; path = str(Path(record['directory']) / 'install.json')
    if marker.exists() and json.loads(marker.read_text()).get('backup') != path:
        raise ValueError('Another gameplay operation owns the recovery marker')
    current = clean.load_state(root / 'state.json')
    if upgrade.digest(current) != record['before_digest'] and current.get('gameplay', {}).get('backup') != path:
        raise ValueError('Active server changed outside this installation')
    if record['phase'] in ('rolled-back', 'failed-recovered'): return
    check_image(adv.image(record['before']['image']), record['before'])
    clean.compose(current, 'stop', 'web', 'bnetserver', 'worldserver')
    if record.get('sql_changed'): adv.restore_bindings(record['before'], record['bindings_before'])
    upgrade.private_text(root / 'compose.private.json', record['compose_before'])
    clean.save(record['before'])
    upgrade.private_text(root / 'server.sh', record['control_before'], 0o700)
    if record['previous_running']:
        clean.compose(record['before'], 'up', '-d', '--no-build', '--no-deps', *record['previous_running'])
        clean.wait_world(record['before'], 180)
    marker.unlink(missing_ok=True); checkpoint(record, 'rolled-back')


def install(root, jobs, scaling=True, reuse_built_image=False):
    if any((root / name).exists() for name in (MARKER, adv.MARKER, '.upgrade-in-progress.json')):
        raise ValueError('Recover the interrupted server operation before installing modules')
    before = network.checked(root)
    if before.get('gameplay'):
        expected = SCALING_VERSION if scaling else None
        if before['gameplay']['source_sha256'] != source_id() or before['gameplay']['scaling'] != expected:
            raise ValueError('Another gameplay profile is active; use upgrade-clean-gameplay.py for a progress-preserving transition')
        wait_module(before); print('GAMEPLAY ALREADY ACTIVE; no changes.'); return
    if before['core'] != clean.CORE: raise ValueError('This release requires the pinned 70658 core')
    model_text = Path(before['compose']).read_text(); model = json.loads(model_text)
    world = model['services']['worldserver']
    if model.get('name') != before['project'] or world.get('image') != before['image'] or world.get('command') != ['worldserver']:
        raise ValueError('Unexpected owned worldserver configuration')
    clean.wait_world(before, 60)
    candidate = built_candidate(before, required=True) if reuse_built_image else build(before, jobs)
    if clean.load_state(root / 'state.json') != before or Path(before['compose']).read_text() != model_text:
        raise ValueError('Active installation changed during compilation')
    folder = root / 'advancement' / os.urandom(6).hex()
    if folder.parent.is_symlink(): raise ValueError('Linked backup directory is unsupported')
    folder.mkdir(parents=True, mode=0o700)
    target, target_model = configure(before, model, candidate, folder, scaling)
    record = dict(format=FORMAT, root=str(root), directory=str(folder), before=before, before_digest=upgrade.digest(before),
                  compose_before=model_text, compose_digest=hashlib.sha256(model_text.encode()).hexdigest(),
                  control_before=(root / 'server.sh').read_text(), target=target,
                  previous_running=upgrade.stop_running(before), sql_changed=False)
    checkpoint(record, 'prepared')
    clean.write_private(root / MARKER, dict(backup=str(folder / 'install.json')))
    try:
        clean.compose(before, 'stop', 'web', 'bnetserver', 'worldserver'); checkpoint(record, 'stopped')
        size = int(clean.sql(before, "SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes');\n").strip())
        if shutil.disk_usage(folder).free < max(1024**3, size): raise ValueError('Insufficient backup space')
        record['snapshot'] = upgrade.snapshot(before); record['bindings_before'] = adv.bindings(before)
        print('Saving private four-database backup; do not interrupt...', flush=True)
        record['database_sha256'] = upgrade.dump_databases(before, folder / 'databases-before.sql.gz')
        checkpoint(record, 'backed-up'); record['sql_changed'] = True; checkpoint(record, 'migrating')
        for database in ('characters', 'world'):
            clean.sql(before, 'USE `' + database + '`;\n' + (ROOT / 'mods/forever-advancement/sql' / (database + '.sql')).read_text())
        clean.sql(before, 'USE `characters`;\n' + (ROOT / 'mods/living-encyclopedia/sql/characters-v1.sql').read_text())
        clean.write_private(Path(before['compose']), target_model); clean.compose(target, 'config', '-q')
        clean.compose(target, 'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'worldserver')
        wait_module(target)
        if upgrade.snapshot(target)['counts'] != record['snapshot']['counts']:
            raise RuntimeError('Account/character counts changed unexpectedly')
        clean.save(target); upgrade.private_text(root / 'server.sh', upgrade.control_text(root), 0o700)
        if record['previous_running']: clean.compose(target, 'up', '-d', '--no-build', '--no-deps', *record['previous_running'])
        checkpoint(record, 'active'); (root / MARKER).unlink()
        print('GAMEPLAY ACTIVE: Ascension ' + adv.VERSION + ', Encyclopedia ' + BOOK_VERSION + ', Scaling ' + (SCALING_VERSION if scaling else 'disabled'))
        print('Backup/rollback record: ' + str(folder / 'install.json'))
    except Exception as original:
        # Preserve candidate evidence before rollback recreates its container.
        diagnostic = folder / 'startup-diagnostics.json'
        try:
            report = adv.module_readiness.snapshot(clean, target, clean.container(target, 'worldserver'), allow_stopped=True)
            clean.write_private(diagnostic, report)
            record['diagnostics'] = str(diagnostic)
            print('Candidate module diagnostics saved: ' + str(diagnostic), flush=True)
        except Exception as inspection:
            record['diagnostics_error'] = type(inspection).__name__
        record['failure'] = network.command_error(before, original)
        try: checkpoint(record, 'failed-before-rollback')
        except (OSError, ValueError): pass  # Reporting must never prevent recovery.
        try: rollback(record); checkpoint(record, 'failed-recovered')
        except Exception as recovery:
            raise RuntimeError(network.command_error(before, original) + '\nRecovery failed: ' + network.command_error(before, recovery)
                               + '\nBackup: ' + str(folder / 'install.json')) from original
        raise


def main():
    global CURRENT_ROOT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('install', 'status', 'rollback'))
    p.add_argument('--root', type=Path, default=Path.home() / 'WoWForEver-clean')
    p.add_argument('--jobs', type=int, choices=range(1, 9), default=2)
    p.add_argument('--scaling', action=argparse.BooleanOptionalAction, default=True)
    p.add_argument('--reuse-built-image', action='store_true', help='Require the matching cached image; never compile on this retry')
    p.add_argument('--backup', type=Path)
    args = p.parse_args(); os.umask(0o077); root = upgrade.direct(args.root); CURRENT_ROOT = root
    if args.action == 'status':
        state = network.checked(root)
        if state.get('gameplay'): wait_module(state)
        else: clean.wait_world(state, 30)
        print(json.dumps(dict(build=70658, advancement=state.get('advancement'), gameplay=state.get('gameplay'), databases_reset=False), indent=2)); return
    lock_path = Path.home() / '.cache/forever-clean-control.lock'; lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another clean-server operation is running')
        if args.action == 'install': install(root, args.jobs, args.scaling, args.reuse_built_image)
        elif args.backup: rollback(load_backup(root, args.backup))
        else: p.error('--backup is required for rollback')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        try: state = clean.load_state(CURRENT_ROOT / 'state.json'); detail = network.command_error(state, error)
        except Exception: detail = str(error)
        print('Gameplay setup stopped: ' + detail, file=sys.stderr); raise SystemExit(1)
