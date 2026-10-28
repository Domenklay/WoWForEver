#!/usr/bin/env python3
"""Enable Map 1220 by server hotfix, isolated geometry and journaled rollback."""
import argparse
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import legion_activation as plan

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT/'backups'
ACTIVE = BACKUPS/'legion-map-active.json'
FORMAT = 'wowforever-legion-map-activation-v1'
SERVICES = ['worldserver', 'bnetserver', 'web']
TELE_NAME = 'DalaranLegionTest'


def compose(*args, **kwargs):
    return subprocess.run(['docker','compose',*args], cwd=ROOT, check=True, **kwargs)


def sql(text):
    script = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot -N -B'
    return compose('exec','-T','mysql','sh','-c',script, input=text, text=True,
                   capture_output=True).stdout


def save(folder, journal):
    temporary = folder/'operation.json.tmp'
    temporary.write_text(json.dumps(journal, indent=2)+'\n'); temporary.replace(folder/'operation.json')


def active():
    if ACTIVE.is_symlink(): raise ValueError('Linked journal pointer')
    token = json.loads(ACTIVE.read_text())['operation']
    if not re.fullmatch(r'legion-map-[A-Za-z0-9_-]+', token): raise ValueError('Invalid journal token')
    folder = BACKUPS/token
    if folder.is_symlink() or (folder/'operation.json').is_symlink(): raise ValueError('Linked journal')
    journal = json.loads((folder/'operation.json').read_text())
    if journal.get('format') != FORMAT: raise ValueError('Unknown activation journal')
    return folder, journal


def data_dir(require_no_mmap=False):
    config = json.loads(compose('config','--format','json',capture_output=True,text=True).stdout)
    rows = [x for x in config['services']['worldserver']['volumes']
            if x['target']=='/opt/trinitycore/data' and x['type']=='bind']
    if len(rows)!=1: raise ValueError('Expected a local server data bind mount')
    if require_no_mmap and str(config['services']['worldserver'].get('environment',{}).get('MMAP_PATHFINDING','0'))!='0':
        raise ValueError('This single-tile experiment requires MMAP_PATHFINDING=0 (no navigation mesh yet)')
    data = Path(rows[0]['source']).resolve(strict=True)
    if not (data/'dbc/ruRU/Map.db2').is_file(): raise ValueError('Server ruRU Map.db2 is missing')
    return data


def world_logs():
    cid = compose('ps','-q','worldserver',capture_output=True,text=True).stdout.strip()
    started = subprocess.run(['docker','inspect','--format','{{.State.StartedAt}}',cid],
                             check=True,capture_output=True,text=True).stdout.strip()
    return compose('logs','--no-color','--since',started,'worldserver',capture_output=True,text=True).stdout


def ready(timeout):
    until = time.monotonic()+timeout
    while True:
        logs = world_logs()
        if re.search(r'worldserver-daemon.*ready',logs): return logs
        if time.monotonic()>=until: raise ValueError('worldserver did not report ready')
        print('Waiting for worldserver...',flush=True); time.sleep(3)


def lookup():
    code = "import asyncio; from app.main import soap_command; print(asyncio.run(soap_command('lookup map id 1220')))"
    return compose('exec','-T','web','python','-c',code,capture_output=True,text=True).stdout


def dump(folder):
    command = ['exec','-T','mysql','sh','-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --quick '
        '--routines --events --triggers --no-tablespaces --set-gtid-purged=OFF '
        '--databases auth characters world hotfixes']
    print('Saving database backup...',flush=True)
    with gzip.open(folder/'databases.sql.gz','wb') as target:
        process = subprocess.Popen(['docker','compose',*command],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            shutil.copyfileobj(process.stdout,target)
            error = process.stderr.read(); code = process.wait()
        finally:
            process.stdout.close(); process.stderr.close()
        if code: raise ValueError('Database backup failed: '+error.decode(errors='replace')[-1000:])
    with gzip.open(folder/'databases.sql.gz','rb') as source:
        for _ in iter(lambda:source.read(1024*1024),b''): pass


def schema_and_ids(table_hash):
    required = set(plan.MAP_COLUMNS)|{'VerifiedBuild'}
    columns = {r.split('\t')[0] for r in sql('SHOW COLUMNS FROM hotfixes.`map`;').splitlines()}
    if not required<=columns: raise ValueError('Map hotfix schema is missing columns: '+str(sorted(required-columns)))
    count = sql(f'SELECT (SELECT COUNT(*) FROM hotfixes.`map` WHERE ID=1220)+'
                '(SELECT COUNT(*) FROM hotfixes.map_locale WHERE ID=1220)+'
                f'(SELECT COUNT(*) FROM hotfixes.hotfix_data WHERE TableHash={table_hash} AND RecordId=1220 AND Status<>2)+'
                f"(SELECT COUNT(*) FROM world.game_tele WHERE name='{TELE_NAME}');")
    if int(count.strip()): raise ValueError('Map 1220, its hotfix or test teleport already exists; no overwrite')
    push = int(sql('SELECT COALESCE(MAX(Id),0)+1 FROM hotfixes.hotfix_data;').strip())
    tele = int(sql('SELECT COALESCE(MAX(id),0)+1 FROM world.game_tele;').strip())
    if not 0<push<0x7fffffff or not 0<tele<0xffffffff: raise ValueError('No available hotfix/teleport ID')
    return push,tele


def select_point(probe):
    samples = probe['samples']
    valid = [s for s in samples if all(type(s[k]) in {float,int} and -20000<float(s[k])<20000 for k in ('x','y','height'))]
    if not valid: raise ValueError('No finite collision candidate')
    # Prefer a broad, nearly level surface with nearby successful rays.
    def score(s):
        near = [x for x in valid if 0<(x['x']-s['x'])**2+(x['y']-s['y'])**2<70**2]
        level = sum(abs(x['height']-s['height'])<2 for x in near)
        return (-level,(s['x']+800)**2+(s['y']-4500)**2)
    s = min(valid,key=score)
    return dict(x=s['x'],y=s['y'],z=s['height']+2,orientation=0,map=1220,
                collision_candidate_only=True,player_spawn_verified=False)


def probe(folder):
    command = ['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
               '--security-opt','no-new-privileges','--user',f'{os.getuid()}:{os.getgid()}',
               '--ulimit','core=0','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=512m',
               '--mount',f'type=bind,src={folder/"geometry"},dst=/geometry,readonly',
               '--mount',f'type=bind,src={ROOT/"tools/legion-geometry"},dst=/geometry-code,readonly',
               '--mount',f'type=bind,src={folder},dst=/out','--entrypoint','python3',
               'forever-legion-casc-probe:local','-B','/geometry-code/probe-staged.py']
    print('Checking isolated collision models with native server code...',flush=True)
    with (folder/'native-probe.log').open('w') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
    return json.loads((folder/'native-probe.json').read_text())


def preflight_client(client,geometry_report,progress=print):
    spec = importlib.util.spec_from_file_location('legion_resource_install',ROOT/'scripts/install-legion-resources.py')
    install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)
    client,_ = install.canary.copy_identity(client)
    folder,journal = install.operation(client)
    allowed_operations=[folder.name,*journal.get('resource_ancestors',[])]
    if (journal['phase']!='verified' or geometry_report['source_install_operation'] not in allowed_operations or
            journal['source_report_sha256']!=geometry_report['source_resource_report_sha256'] or
            plan.sha(client/'.build.info')!=journal['after_info_sha256']):
        raise ValueError('Test copy no longer matches the geometry resource layer')
    expected = {int(k):v for k,v in journal['expected_after'].items()}
    actual = install.scan(ROOT/'scripts/check-client-casc.sh',client,expected,journal['locale'],progress)
    install.check_rows(actual,expected)
    return client,dict(build_info_sha256=plan.sha(client/'.build.info'),native_verified_ids=len(actual))


def rollback(folder,journal,automatic=False):
    if journal['phase']=='rolled_back': return
    data = Path(journal['data'])
    if data!=data_dir(): raise ValueError('Server data location changed; restore from saved journal manually')
    for row in journal['files']:
        target = data/row['path']
        if target.exists() and (target.is_symlink() or plan.sha(target)!=row['sha256']):
            raise ValueError('Installed file changed; refusing to remove: '+row['path'])
    # Stop first; rescue only players in map 1220 before removing the map record.
    compose('stop','web','bnetserver','worldserver')
    if journal.get('sql_attempted'):
        script = (folder/'rollback.sql').read_text()
        if hashlib.sha256(script.encode()).hexdigest()!=journal['rollback_sql_sha256']:
            raise ValueError('Rollback SQL backup changed')
        sql(script)
    for row in journal['files']:
        target = data/row['path']
        if target.exists(): target.unlink()
    target = data/'vmaps/1220'
    if target.is_dir() and not any(target.iterdir()): target.rmdir()
    journal['phase']='rolled_back';save(folder,journal)
    compose('start',*SERVICES)
    print('Rolled back Map 1220; other character progress retained. Backup: '+str(folder),flush=True)


def apply(client,geometry):
    if ACTIVE.exists():
        _,old = active()
        if old['phase']!='rolled_back': raise ValueError('An activation already exists; use status or rollback')
    running = set(compose('ps','--status','running','--services',capture_output=True,text=True).stdout.split())
    if not {'mysql',*SERVICES}<=running: raise ValueError('mysql, worldserver, bnetserver and web must already be running')
    logs = ready(0)
    if '91d49b230f89' not in logs: raise ValueError('Running core revision differs from the geometry profile')
    data = data_dir(require_no_mmap=True)
    if list((data/'maps').glob('1220*')) or (data/'vmaps/1220').exists():
        raise ValueError('Server already has map 1220 geometry; no overwrite')
    geometry = Path(geometry).resolve(strict=True)
    source_report = json.loads((geometry/'report.json').read_text())
    client,identity = preflight_client(client,source_report)
    table_hash, values = plan.map_values((data/'dbc/ruRU/Map.db2').read_bytes())
    push,tele = schema_and_ids(table_hash)
    folder = Path(tempfile.mkdtemp(prefix='legion-map-',dir=BACKUPS))
    print('Activation backup: '+str(folder),flush=True)
    staged = plan.stage_geometry(geometry,folder/'geometry')
    for row in staged['files']:
        if (data/row['path']).exists(): raise ValueError('Geometry destination already exists: '+row['path'])
    native = probe(folder); point = select_point(native)
    installation = plan.apply_sql(values,table_hash,push).replace('COMMIT;','')
    installation += ('INSERT INTO world.game_tele (id,position_x,position_y,position_z,orientation,map,name) VALUES '
                     f"({tele},{point['x']},{point['y']},{point['z']},0,1220,'{TELE_NAME}');\nCOMMIT;\n")
    restoration = plan.rollback_sql(table_hash,push).replace('COMMIT;',
        f"DELETE FROM world.game_tele WHERE id={tele} AND name='{TELE_NAME}';\nCOMMIT;")
    (folder/'apply.sql').write_text(installation);(folder/'rollback.sql').write_text(restoration)
    journal = dict(format=FORMAT,phase='prepared',data=str(data),client=str(client),identity=identity,
                   files=staged['files'],source_report_sha256=staged['source_report_sha256'],
                   table_hash=table_hash,push_id=push,teleport_id=tele,teleport_name=TELE_NAME,
                   point=point,sql_attempted=False,client_casc_modified=False,
                   rollback_sql_sha256=hashlib.sha256(restoration.encode()).hexdigest(),
                   client_hotfix_acceptance_verified=False,player_spawn_verified=False)
    save(folder,journal)
    temp = ACTIVE.with_suffix('.tmp');temp.write_text(json.dumps(dict(operation=folder.name))+'\n');temp.replace(ACTIVE)
    try:
        compose('stop','web','bnetserver','worldserver')
        journal['phase']='stopped';save(folder,journal)
        dump(folder)
        # Recheck after disconnecting clients; all earlier work was read-only.
        if schema_and_ids(table_hash)!=(push,tele): raise ValueError('Hotfix/teleport IDs changed during preparation')
        for row in staged['files']:
            source = folder/'geometry'/row['path'];target = data/row['path']
            if target.exists() or plan.sha(source)!=row['sha256']: raise ValueError('Geometry changed before deployment')
            new_parent=not target.parent.exists()
            target.parent.mkdir(parents=True,exist_ok=True)
            if new_parent:target.parent.chmod(0o755)
            # Complete and hash the new file before making it visible. An
            # interrupted copy must not obstruct a hash-checked rollback.
            fd,name = tempfile.mkstemp(prefix='.legion-copy-',dir=target.parent)
            temporary=Path(name)
            try:
                with os.fdopen(fd,'wb') as out,source.open('rb') as src: shutil.copyfileobj(src,out)
                if plan.sha(temporary)!=row['sha256']: raise ValueError('Copied geometry hash mismatch')
                temporary.chmod(0o644)
                os.link(temporary,target)  # exclusive: never replace an existing file
            finally:
                temporary.unlink(missing_ok=True)
        journal['sql_attempted']=True;save(folder,journal);sql(installation)
        journal['phase']='installed';save(folder,journal)
        compose('start',*SERVICES)
        ready(180)
        found = lookup();(folder/'map-lookup.txt').write_text(found)
        if '1220' not in found or not any(x in found for x in ('Dalaran','Даларан')):
            raise ValueError('Runtime map lookup did not confirm the new map')
        if plan.sha(client/'.build.info')!=identity['build_info_sha256']: raise ValueError('Test client changed concurrently')
        journal['phase']='ready';save(folder,journal)
        print('MAP 1220 ENABLED ON SERVER. Client receives the hotfix on next login.',flush=True)
        print('Native client acceptance and arrival still require your test.',flush=True)
        print('Backup/report: '+str(folder/'operation.json'),flush=True)
        print('Teleport after login: python3 scripts/activate-legion-map.py visit KAY',flush=True)
    except BaseException:
        try:
            (folder/'failed-worldserver.log').write_text(world_logs())
            rollback(folder,journal,automatic=True)
        except BaseException as error:
            print('Automatic rollback did not finish: '+str(error)+'; backup: '+str(folder),file=sys.stderr)
        raise
    return folder


def visit(name,home=False):
    if not re.fullmatch(r'[A-Za-zА-Яа-яЁё]{2,12}',name): raise ValueError('Expected a character name')
    folder,journal = active()
    if not home and journal['phase']!='ready': raise ValueError('Map activation is not ready')
    # Console permission stays on the server; the player need not become a GM.
    code = ('import asyncio,sys; from app.main import soap_command; '
            "print(asyncio.run(soap_command('tele name '+sys.argv[1]+' '+sys.argv[2])))")
    answer = compose('exec','-T','web','python','-c',code,name,'$home' if home else TELE_NAME,
                     capture_output=True,text=True).stdout
    print(answer)
    (folder/'last-teleport.txt').write_text(answer)


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_subparsers(dest='action',required=True)
    ap=actions.add_parser('apply');ap.add_argument('client',type=Path);ap.add_argument('--geometry',type=Path,required=True)
    actions.add_parser('status');actions.add_parser('rollback')
    vp=actions.add_parser('visit');vp.add_argument('name')
    hp=actions.add_parser('home');hp.add_argument('name')
    args=parser.parse_args()
    try:
        BACKUPS.mkdir(exist_ok=True)
        with (BACKUPS/'content-port.lock').open('a') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='apply':
                token=hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
                with (Path(tempfile.gettempdir())/('wowforever-casc-edit-'+token+'.lock')).open('a') as casclock:
                    fcntl.flock(casclock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    apply(args.client,args.geometry)
            elif args.action=='rollback':rollback(*active())
            elif args.action=='visit':visit(args.name)
            elif args.action=='home':visit(args.name,home=True)
            else:
                folder,journal=active();print(json.dumps(journal,indent=2));print(lookup())
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,subprocess.SubprocessError) as error:
        parser.exit(1,'Legion activation stopped: '+str(error)+'\n')
