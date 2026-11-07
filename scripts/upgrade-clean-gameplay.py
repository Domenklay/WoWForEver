#!/usr/bin/env python3
"""Progress-preserving 70658 upgrade to Ascension 1.13 + Dungeon Scaling 0.4; trial before cutover."""
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

ROOT=Path(__file__).resolve().parents[1]
def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

game=module('gameplay_upgrade_tools','enable-clean-gameplay.py')
trial=module('gameplay_upgrade_trial','test-baseline-services.py')
clean,adv,upgrade=game.clean,game.adv,game.upgrade
FORMAT='forever-gameplay-transition-v1'
MARKER='.gameplay-upgrade-in-progress.json'
ORIGINAL_SCALING_VERSION='0.2.0'
NEW_DUNGEONFINDER_VERSION='0.2.0'


def check_before(state,model):
    if (state.get('core')!=clean.CORE or state.get('phase')!='ready'
        or state.get('advancement',{}).get('version') not in ('1.11.0','1.12.0')
        or state.get('gameplay',{}).get('version')!=1
        or state['gameplay'].get('encyclopedia')!=game.BOOK_VERSION
        or state['gameplay'].get('scaling')!=ORIGINAL_SCALING_VERSION
        or state['gameplay'].get('dungeonfinder') not in (None, '')
        or state['gameplay'].get('dungeon_solo_enabled')
        or state['gameplay'].get('dungeon_finder_enabled')):
        raise ValueError('Requires the ready 70658 server: Scaling 0.2.0, Advancement 1.11/1.12 and unchanged encyclopedia')
    if model.get('name')!=state['project'] or model['services']['worldserver'].get('image')!=state['image']:
        raise ValueError('Live Compose identity differs')
    if any((Path(state['root'])/n).exists() for n in (MARKER,game.MARKER,adv.MARKER,'.upgrade-in-progress.json')):
        raise ValueError('Recover the existing operation before preparing an upgrade')


def fingerprints(state):
    # Exact module table content, not just account/character counts. Stored privately.
    names=trial.sql.MODULE_TABLES
    body='CHECKSUM TABLE '+','.join('characters.`'+n+'`' for n in names)+' EXTENDED;\n'
    lines=clean.sql(state,body).splitlines()
    values={}
    for line in lines:
        name,value=line.split('\t')
        if value=='NULL' or not value.isdecimal(): raise ValueError('Cannot checksum current module progress')
        values[name]=value
    if set(values)!={'characters.'+n for n in names}:raise ValueError('Module checksum coverage differs')
    return values


def load_record(root,path):
    path=upgrade.direct(path)
    if path.parent.parent!=root/'advancement' or path.name!='transition.json' or not re.fullmatch('[0-9a-f]{12}',path.parent.name):
        raise ValueError('Transition record must belong to this server')
    record=json.loads(path.read_text())
    if (record.get('format')!=FORMAT or record.get('root')!=str(root)
        or record.get('directory')!=str(path.parent) or upgrade.digest(record['before'])!=record['before_digest']
        or hashlib.sha256(record['compose_before'].encode()).hexdigest()!=record['compose_digest']):
        raise ValueError('Transition identity/checksum mismatch')
    return record


def save(record,phase):
    record['phase']=phase
    clean.write_private(Path(record['directory'])/'transition.json',record)
    print('Gameplay transition: '+phase,flush=True)


def reuse_verified_trial(path, backup, candidate_id):
    """Reuse only a completed, isolated trial of THIS exact image and backup.

    The trial must be inside the private restore-trials area, must already be
    cleaned, and must prove its world, database, TLS, and service probes passed.
    Neither this helper nor prepare touches the live database or Docker stack.
    """
    path=upgrade.direct(path)
    parent=upgrade.direct(Path.home()/'WoWForEver-restore-trials')
    if (path.name!='report.json' or path.parent.parent!=parent
        or not re.fullmatch(r'forever-services-check-[0-9a-f]{12}',path.parent.name)):
        raise ValueError('Verified trial report is outside the owned private trial folder')
    report=json.loads(path.read_text())
    if (report.get('format')!=trial.FORMAT or
        report.get('nonce')!=path.parent.name.removeprefix('forever-services-check-')
        or report.get('phase')!='verified'
        or report.get('candidate_image')!=candidate_id
        or report.get('backup')!=str(upgrade.direct(backup))
        or not all(report.get(key) is True for key in
                   ('database_verified','services_verified','cleanup_verified'))
        or report.get('service_probes',{}).get('tls_verified') is not True
        or not report.get('world_readiness',{}).get('lines')):
        raise ValueError('Verified trial does not match this candidate image and backup')
    markers='\\n'.join(report['world_readiness']['lines'])
    for marker in ('ForeverScaling ready: personal-virtual-v0.4 (enabled=true',
                   'ForeverDungeonFinder: direct-entry-v0.2 registered (enabled=true'):
        if marker not in markers:
            raise ValueError('Verified trial lacks a required enabled module marker')
    print('REUSING VERIFIED CANDIDATE TRIAL: '+str(path),flush=True)
    return report


def prepare(root,backup,jobs,reuse=False,verified_trial=None):
    before=game.network.checked(root);text=Path(before['compose']).read_text();model=json.loads(text)
    check_before(before,model);game.check_image(adv.image(before['image']),before)
    game.wait_module(before)
    candidate=game.built_candidate(before,required=True) if reuse else game.build(before,jobs)
    item=adv.image(candidate);game.check_image(item,before,candidate=True)
    # Restored files and SQL belong exclusively to the labelled trial, with no host ports.
    if verified_trial and not reuse:
        raise ValueError('--verified-trial requires --reuse-built-image')
    report=(reuse_verified_trial(verified_trial,backup,item['Id']) if verified_trial else
            trial.run_check(backup,Path.home()/'WoWForEver-restore-trials',candidate=item['Id']))
    if not report.get('services_verified') or not report.get('cleanup_verified') or report.get('candidate_image')!=item['Id']:
        raise ValueError('Candidate clone trial was not verified and cleaned')
    if clean.load_state(root/'state.json')!=before or Path(before['compose']).read_text()!=text:
        raise ValueError('Live installation changed while the candidate was tested')
    # direct() requires the path to ALREADY exist (resolve(strict=True)).
    # Validate an existing private parent first, create the nonce folder, then
    # validate the newly created path. The previous order raised FileNotFoundError
    # after the candidate clone had been successfully tested.
    parent=root/'advancement'
    if parent.is_symlink():
        raise ValueError('Linked advancement directory is unsupported')
    parent.mkdir(mode=0o700,exist_ok=True)
    upgrade.direct(parent)
    folder=parent/os.urandom(6).hex()
    folder.mkdir(mode=0o700)
    upgrade.direct(folder)
    record=dict(format=FORMAT,root=str(root),directory=str(folder),before=before,before_digest=upgrade.digest(before),
                compose_before=text,compose_digest=hashlib.sha256(text.encode()).hexdigest(),
                control_before=(root/'server.sh').read_text(),candidate=item['Id'],candidate_tag=candidate,
                source_sha256=game.source_id(),advancement_sha256=adv.source_id(),trial=report)
    save(record,'prepared')
    print('PREPARED GAMEPLAY UPGRADE: '+str(folder/'transition.json'),flush=True)
    return record


def rollback(root,record):
    if record.get('phase') in ('prepared','rolled-back'):
        print('No active transition to roll back; services unchanged',flush=True);return
    if record.get('phase') not in ('starting','backed-up','active'):
        raise ValueError('Unknown transition phase')
    path=str(Path(record['directory'])/'transition.json');marker=root/MARKER
    if marker.exists() and json.loads(marker.read_text()).get('record')!=path:
        raise ValueError('Another transition owns the recovery marker')
    current=clean.load_state(root/'state.json')
    if current!=record['before'] and current.get('gameplay',{}).get('transition')!=path:
        raise ValueError('Current server no longer belongs to this transition')
    game.check_image(adv.image(record['before']['image']),record['before'])
    clean.compose(current,'stop','web','bnetserver','worldserver')
    upgrade.private_text(root/'compose.private.json',record['compose_before'])
    clean.save(record['before']);upgrade.private_text(root/'server.sh',record['control_before'],0o700)
    if record.get('previous_running'):
        clean.compose(record['before'],'up','-d','--no-build','--no-deps',*record['previous_running'])
        game.wait_module(record['before'])
    # The extra preferences table stays. No SQL dump is imported and no progress is rewound.
    marker.unlink(missing_ok=True);save(record,'rolled-back')


def apply(root,record):
    before=record['before'];path=str(Path(record['directory'])/'transition.json')
    if record['phase']!='prepared' or not record['trial'].get('services_verified') or not record['trial'].get('cleanup_verified'):
        raise ValueError('Apply requires a prepared, successful isolated trial')
    if record['source_sha256']!=game.source_id() or record['advancement_sha256']!=adv.source_id():
        raise ValueError('Use the exact tools/source that prepared this transition')
    if clean.load_state(root/'state.json')!=before or Path(before['compose']).read_text()!=record['compose_before']:
        raise ValueError('Live server changed since preparation')
    if adv.image(record['candidate_tag'])['Id']!=record['candidate']:raise ValueError('Candidate tag changed since preparation')
    check_before(before,json.loads(record['compose_before']));game.check_image(adv.image(record['candidate']),before,candidate=True)
    size=int(clean.sql(before,"SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ('auth','world','characters','hotfixes');").strip())
    if shutil.disk_usage(root).free<max(1024**3,2*size):raise ValueError('Not enough space for the current four-database backup')
    game.wait_module(before)
    record['previous_running']=upgrade.stop_running(before)
    clean.write_private(root/MARKER,{'record':path});save(record,'starting')
    try:
        clean.compose(before,'stop','web','bnetserver','worldserver')
        for service in record['previous_running']:
            if clean.container(before,service)['State']['Running']:raise ValueError('A live database writer did not stop')
        record['snapshot']=upgrade.snapshot(before);record['progress_before']=fingerprints(before)
        record['database_sha256']=upgrade.dump_databases(before,Path(record['directory'])/'databases-before.sql.gz')
        save(record,'backed-up')
        clean.sql(before,'USE characters;\n'+(ROOT/'mods/forever-advancement/sql/preferences.sql').read_text())
        target=copy.deepcopy(before);target['image']=record['candidate_tag']
        target['advancement'].update(version=adv.VERSION,protocol=3,source_sha256=adv.source_id())
        target['gameplay'].update(source_sha256=game.source_id(), transition=path,
                                  scaling=game.SCALING_VERSION, dungeonfinder=NEW_DUNGEONFINDER_VERSION,
                                  dungeon_solo_enabled=True, dungeon_finder_enabled=True)
        target['database_version']='gameplay-1.13@pristine-'+before['core'][:12]
        model=json.loads(record['compose_before']);model['services']['worldserver']['image']=record['candidate_tag']
        # Only the worldserver module toggles change: credentials, ports,
        # named database volumes, bind mounts and every other service stay put.
        world_env=model['services']['worldserver']['environment']
        world_env.update(FOREVER_SCALING_ENABLED='1', FOREVER_SCALING_DAMAGE_GUARD='1',
                         FOREVER_SCALING_MIN_OFFSET='-3', FOREVER_SCALING_CREATURE_MAX_LEVEL='70',
                         FOREVER_DUNGEON_SCALING_ENABLED='1', FOREVER_DUNGEON_FINDER_ENABLED='1')
        # bnet, MySQL, web, all mounts, credentials, ports and environment remain exact.
        clean.write_private(Path(before['compose']),model);clean.compose(target,'config','-q')
        clean.compose(target,'up','-d','--no-build','--no-deps','--force-recreate','worldserver')
        game.wait_module(target)
        # The FDF module is the actual teleport dispatcher. Refuse cutover if
        # its startup registration is missing from the candidate image.
        adv.module_readiness.wait(clean, target, ['ForeverDungeonFinder: direct-entry-v0.2 registered (enabled=true)'], 90)
        if fingerprints(target)!=record['progress_before'] or upgrade.snapshot(target)['counts']!=record['snapshot']['counts']:
            raise ValueError('Account/character/module progress changed during initialization')
        clean.save(target);upgrade.private_text(root/'server.sh',upgrade.control_text(root),0o700)
        if record['previous_running']:clean.compose(target,'up','-d','--no-build','--no-deps',*record['previous_running'])
        save(record,'active');(root/MARKER).unlink()
        print('GAMEPLAY UPGRADED: Ascension 1.13.0, Scaling 0.4.0, DungeonFinder 0.2.0 (solo+group enabled); character progress retained',flush=True)
    except BaseException:
        try:
            clean.write_private(Path(record['directory'])/'startup-diagnostics.json',adv.module_readiness.snapshot(clean,before,clean.container(before,'worldserver'),allow_stopped=True))
        except Exception:pass
        rollback(root,record)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','apply','rollback'))
    p.add_argument('--root',type=Path,default=Path.home()/'WoWForEver-clean');p.add_argument('--baseline',type=Path)
    p.add_argument('--record',type=Path);p.add_argument('--jobs',type=int,default=2);p.add_argument('--reuse-built-image',action='store_true')
    p.add_argument('--verified-trial',type=Path,help='Reuse a previously successful, cleaned trial of the exact cached image (prepare only)')
    args=p.parse_args();os.umask(0o077);root=upgrade.direct(args.root)
    if not 1<=args.jobs<=8:p.error('--jobs must be 1..8')
    lock_path=Path.home()/'.cache/forever-clean-control.lock';lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='prepare':
            if not args.baseline:p.error('--baseline is required')
            prepare(root,args.baseline,args.jobs,args.reuse_built_image,args.verified_trial)
        else:
            if args.verified_trial: p.error('--verified-trial is valid only for prepare')
            if not args.record:p.error('--record is required')
            record=load_record(root,args.record)
            (apply if args.action=='apply' else rollback)(root,record)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError) as e:
        # Avoid raw Docker/SQL/credential-bearing output on the terminal.
        print('Gameplay transition stopped: '+(str(e) if isinstance(e,ValueError) else type(e).__name__)+'. Check the private transition record.',file=sys.stderr)
        raise SystemExit(1)
