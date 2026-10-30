"""Collect client logs and active experiment metadata outside the client tree."""
from datetime import datetime, timezone
import hashlib
import json
import ntpath
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

LOGS=('Client.log','Tact.log','General.log','Hotfix.log','Connection.log','Model.log','gx.log')
MAX_LOG_BYTES=8*1024*1024


def default_root(client):
    client=Path(client).resolve()
    if client.parent.name!='experiments':
        raise ValueError('Use --output for a client outside the experiments directory')
    return client.parent.parent/'reports'


def game_processes():
    if not shutil.which('powershell.exe'):return dict(available=False,reason='PowerShell is unavailable')
    # Executable path only; command lines can contain authentication material.
    command="Get-CimInstance Win32_Process -Filter \"Name='WowB.exe'\" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                              capture_output=True,text=True,errors='replace',timeout=10,check=True)
        return dict(available=True,processes=json.loads(result.stdout) if result.stdout.strip() else [])
    except (OSError,ValueError,subprocess.SubprocessError):
        return dict(available=False,reason='Could not query game executable paths')


def process_identity(client, snapshot):
    """Compare paths only; never collect process command lines or credentials."""
    posix = str(Path(client)/'_classic_beta_/WowB.exe')
    match = re.fullmatch(r'/mnt/([a-zA-Z])/(.+)', posix)
    expected = match[1].upper()+':\\'+match[2].replace('/', '\\') if match else None
    result = dict(expected_executable_wsl=posix, expected_executable_windows=expected,
                  matching_test_copy_running=None, other_copy_running=None)
    if not snapshot.get('available') or not expected:
        return result
    rows = snapshot.get('processes', [])
    if isinstance(rows, dict): rows = [rows]
    if not isinstance(rows, list): return result
    paths = [r.get('ExecutablePath') for r in rows if isinstance(r,dict)]
    known = [p for p in paths if isinstance(p,str) and p]
    same = lambda p: ntpath.normcase(ntpath.normpath(p)) == ntpath.normcase(ntpath.normpath(expected))
    # Missing executable-path access is unknown, never proof of a wrong copy.
    unknown=len(known)<len(rows)
    result['matching_test_copy_running'] = True if any(map(same,known)) else None if unknown else False
    result['other_copy_running'] = True if any(not same(p) for p in known) else None if unknown else False
    return result


def collect(client,output=None,stage='after_user_test'):
    client=Path(client).resolve(strict=True)
    output=Path(output).resolve() if output is not None else default_root(client)
    if output.is_relative_to(client) or any(x.lower() in {'data','_classic_beta_'} for x in output.parts):
        raise ValueError('Reports must be outside client/server data trees')
    base=client/'legion-resource-operations'
    if base.is_symlink() or (base/'active.json').is_symlink():raise ValueError('Linked operation journal')
    token=json.loads((base/'active.json').read_text())['operation']
    if not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('Invalid operation token')
    folder=base/token
    if folder.is_symlink():raise ValueError('Linked operation folder')
    operation=folder/'operation.json'
    if operation.is_symlink():raise ValueError('Linked operation metadata')
    journal=json.loads(operation.read_text())
    if journal.get('format')!='wowforever-legion-resource-operation-v1' or journal.get('copy')!=str(client):
        raise ValueError('Operation journal belongs to another client')
    output.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target=Path(tempfile.mkdtemp(prefix='Dalaran-TVFS-texture-'+stamp+'-',dir=output))
    shutil.copyfile(operation,target/'operation.json')
    result=folder/'result.json'
    if result.is_file() and not result.is_symlink():shutil.copyfile(result,target/'result.json')
    entries=[];logroot=client/'_classic_beta_/Logs';(target/'logs').mkdir()
    build_mtime=(client/'.build.info').stat().st_mtime
    if (client/'_classic_beta_').is_symlink() or logroot.is_symlink():raise ValueError('Linked log directory')
    tact_max=None
    for name in LOGS:
        source=logroot/name
        if not source.is_file() or source.is_symlink():continue
        with source.open('rb') as stream:
            stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-MAX_LOG_BYTES));body=stream.read(MAX_LOG_BYTES)
        (target/'logs'/name).write_bytes(body)
        entries.append(dict(name=name,source_bytes=size,copied_bytes=len(body),tail_only=size>MAX_LOG_BYTES,
                            source_mtime_utc=datetime.fromtimestamp(source.stat().st_mtime,timezone.utc).isoformat(),
                            not_older_than_build_info=source.stat().st_mtime>=build_mtime))
        if name=='Tact.log':
            archives=[int(x) for x in re.findall(rb'Archive\[\s*(\d+)\]',body)]
            tact_max=max(archives) if archives else None
    info=(client/'.build.info').read_bytes()
    digest=hashlib.sha256(info).hexdigest()
    summary=dict(format='wowforever-legion-client-report-v1',client=str(client),operation=token,
                 capture_stage=stage,
                 phase=journal.get('phase'),active_is_tvfs_entry_canary=bool(journal.get('tvfs_entry_canary')),
                 build_info_sha256=digest,build_matches_operation=digest==journal.get('after_info_sha256'),
                 newest_archive_number_in_tact_log=tact_max,
                 operation_added_archives=[name for name in journal.get('added',{}) if re.fullmatch(r'data\.\d{3}',name)],
                 logs=entries,live_game_processes=game_processes(),client_modified=False,server_modified=False)
    summary['process_identity']=process_identity(client,summary['live_game_processes'])
    summary['build_info_mtime_utc']=datetime.fromtimestamp(build_mtime,timezone.utc).isoformat()
    summary['fresh_client_log_present']=any(e['name']=='Client.log' and e['not_older_than_build_info'] for e in entries)
    summary['fresh_tact_log_present']=any(e['name']=='Tact.log' and e['not_older_than_build_info'] for e in entries)
    summary['game_resource_loading_confirmed']=False
    (target/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    archive=target.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as dest:
        for path in sorted(target.rglob('*')):
            if path.is_file():dest.write(path,path.relative_to(target))
    return archive


def auto_collect(client,output=None):
    try:print('Shareable report: '+str(collect(client,output,stage='immediately_after_install_before_game_test')),flush=True)
    except (ValueError,OSError,KeyError,TypeError) as error:
        # A report-copy problem must not misrepresent a completed CASC install.
        print('Installation retained; report collection failed: '+str(error),flush=True)
