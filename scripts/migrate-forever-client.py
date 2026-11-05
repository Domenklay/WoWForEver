#!/usr/bin/env python3
"""Plan or independently clone a new Forever installation, without old CASC layers.

Supports an installation root or a game subdirectory with shared parent Data.
Unknown/ambiguous layouts produce a metadata report before any copy is started.
Run in WSL with both clients and launchers closed. No launcher settings are edited.
"""
import argparse
import base64
import csv
from datetime import datetime,timezone
import hashlib
import importlib.util
import io
import json
import ntpath
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


copier=load('prepare-legion-client.py')
FORMAT='wowforever-new-client-migration-plan-v1'
MARKER='forever-client-migration.json'
GAME_NAMES={'wow.exe','wowb.exe','wowf.exe','wowforever.exe','forever.exe'}


def windows_path(path):
    match=re.fullmatch(r'/mnt/([a-zA-Z])(?:/(.*))?',str(path))
    return match[1].upper()+':\\'+(match[2] or '').replace('/','\\') if match else None


def metadata(text):
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff')),delimiter='|'))
    if not rows:raise ValueError('Empty .build.info')
    columns={name.split('!')[0]:i for i,name in enumerate(rows[0])}
    if not {'Product','Active','Build Key'}<=columns.keys():raise ValueError('Unknown .build.info columns')
    result=[]
    for row in rows[1:]:
        if not row:continue
        if len(row)!=len(rows[0]):raise ValueError('Malformed .build.info row')
        if row[columns['Active']]!='1':continue
        item={key:row[columns[key]] for key in ('Product','Build Key','Version') if key in columns}
        if not re.fullmatch(r'[0-9a-fA-F]{32}',item['Build Key']):raise ValueError('Invalid active build key')
        item['Build Key']=item['Build Key'].lower();result.append(item)
    return result


def game_executables(folder,requested=None):
    if not folder.is_dir():return []
    if requested and (Path(requested).name!=requested or '\\' in requested or
                      not requested.casefold().endswith('.exe') or 'launcher' in requested.casefold()):
        raise ValueError('Select a game executable filename, not a launcher or path')
    return [p for p in sorted(folder.iterdir()) if p.is_file() and
            (p.name.casefold()==requested.casefold() if requested else p.name.casefold() in GAME_NAMES)]


def launcher_versions(paths):
    entries=[dict(path=str(p),windows_path=windows_path(p),file_version=None,product_version=None) for p in paths]
    if not entries or not shutil.which('powershell.exe'):return entries
    win=[r['windows_path'] for r in entries if r['windows_path']]
    if not win:return entries
    # Data goes through base64/JSON, never interpolated as executable PS code.
    payload=base64.b64encode(json.dumps(win).encode()).decode()
    script=("$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+payload+"'))|ConvertFrom-Json; "
            "@($p|ForEach-Object {$v=(Get-Item -LiteralPath $_ -ErrorAction Stop).VersionInfo; "
            "[pscustomobject]@{Path=$_;FileVersion=$v.FileVersion;ProductVersion=$v.ProductVersion}})|ConvertTo-Json -Compress")
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    try:
        raw=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                           capture_output=True,text=True,errors='replace',timeout=15,check=True)
        rows=json.loads(raw.stdout.lstrip('\ufeff'))
        if isinstance(rows,dict):rows=[rows]
        by_path={ntpath.normcase(r['Path']):r for r in rows}
        for entry in entries:
            got=by_path.get(ntpath.normcase(entry['windows_path'] or ''),{})
            entry.update(file_version=got.get('FileVersion'),product_version=got.get('ProductVersion'))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        pass  # Unavailable version metadata remains unknown, never inferred from the name.
    return entries


def addons_in(game):
    folder=game/'Interface/AddOns'
    if not folder.is_dir() or folder.is_symlink():return []
    return [p.name for p in sorted(folder.iterdir()) if p.is_dir() and not p.is_symlink()
            and any(f.suffix.lower()=='.toc' for f in p.iterdir() if f.is_file())]


def inspect(source,output,old_client,product=None,executable=None,query_launchers=True):
    requested=Path(source).resolve(strict=True);output=Path(output).resolve()
    old_client=Path(old_client).resolve()
    if not requested.is_dir():raise ValueError('Source must be a game or installation directory')
    result=dict(format=FORMAT,requested_source=str(requested),destination=str(output),old_client=str(old_client),
                preferred_launcher=dict(filename='ForeverLauncher.exe',requested_version='2.0.5',version_verified=False),
                beta_launcher_fallback_allowed=True,client_modified=False,server_modified=False,
                old_casc_layers_transferred=False,old_addons_transferred=False,status='NEEDS_INFORMATION',reasons=[])
    root=None;game=None
    if (requested/'Data').is_dir() and (requested/'.build.info').is_file():
        root=requested
        options=[requested] if game_executables(requested,executable) else []
        options += [p for p in requested.iterdir() if p.is_dir() and p.name.casefold() in
                    {'_forever_','_classic_beta_','_retail_'} and game_executables(p,executable)]
        preferred=[p for p in options if p.name.casefold()=='_forever_']
        if len(preferred)==1:game=preferred[0]
        elif len(options)==1:game=options[0]
        else:result['reasons'].append('Cannot choose one game folder; available: '+', '.join(str(p) for p in options))
    elif (requested.parent/'Data').is_dir() and (requested.parent/'.build.info').is_file():
        root=requested.parent;game=requested
    else:
        result['reasons'].append('Neither this folder nor its parent has both Data and .build.info')
        result['source_entries']=[p.name for p in sorted(requested.iterdir()) if p.name.casefold() in
                                  {'data','.build.info','_forever_','_classic_beta_'} or p.suffix.casefold()=='.exe']
    launchers=[]
    for folder in dict.fromkeys([requested,requested.parent]):
        for p in folder.iterdir():
            if p.is_file() and p.suffix.casefold()=='.exe' and 'forever' in p.name.casefold() and 'launcher' in p.name.casefold():
                launchers.append(p)
    result['launcher_candidates']=launcher_versions(launchers) if query_launchers else [dict(path=str(p),windows_path=windows_path(p),file_version=None,product_version=None) for p in launchers]
    result['preferred_launcher']['version_verified']=any(
        p['path'].casefold().endswith('/foreverlauncher.exe') and any(
            re.match(r'^2\.0\.5(?:\D|$)',str(p.get(k) or '').strip()) for k in ('file_version','product_version'))
        for p in result['launcher_candidates'])
    if root is None or game is None:return result
    result['source_root']=str(root);result['source_game']=str(game)
    if root.is_symlink() or (root/'Data').is_symlink() or (root/'.build.info').is_symlink() or game.is_symlink():
        raise ValueError('Linked source layout is unsupported')
    text=(root/'.build.info').read_text(encoding='utf-8-sig');active=metadata(text)
    result['active_builds']=active
    selected=[r for r in active if r['Product']==product] if product else active
    if len(selected)!=1:
        result['reasons'].append('Select exactly one active product using --product; see active_builds')
        return result
    chosen=selected[0];result['selected_build']=chosen
    exes=game_executables(game,executable)
    result['game_executables']=[p.name for p in sorted(game.iterdir()) if p.is_file() and p.suffix.casefold()=='.exe']
    if len(exes)!=1:
        result['reasons'].append('Select one game executable using --executable; see game_executables')
        return result
    game_part='.' if game==root else game.relative_to(root).as_posix()
    if game_part=='.':
        if root.parent==root or re.fullmatch(r'/mnt/[a-zA-Z]',str(root)):
            raise ValueError('Refusing a whole-drive root-game copy')
        parts=sorted(p.name for p in root.iterdir() if p.name.casefold() not in copier.EXCLUDED_DIRS|{'.git',
                     'legion-resource-operations','casc-canary-operations','casc-container-operations'}
                     and p.name not in {MARKER,'legion-client-copy.json'}
                     and not p.name.casefold().endswith(copier.EXCLUDED_SUFFIXES))
    else:
        parts=['.build.info','Data',game_part]
    layout=dict(parts=parts,game_part=game_part,executable=exes[0].name,product=chosen['Product'],
                marker_name=MARKER,report_format='wowforever-migrated-client-copy-v1')
    if any(output==root/p or (root/p) in output.parents for p in parts) or output==root:
        raise ValueError('Destination must be outside selected source trees')
    if output==old_client or output.is_relative_to(old_client):raise ValueError('Destination overlaps the old experiment')
    files=copier.inventory(root,parts,game_part);total=sum(row[0] for row in files.values())
    ancestor=output.parent
    while not ancestor.exists():ancestor=ancestor.parent
    result.update(status='READY_TO_CLONE',layout=layout,build_info_sha256=hashlib.sha256((root/'.build.info').read_bytes()).hexdigest(),
                  source_bytes=total,source_files=len(files),free_bytes=shutil.disk_usage(ancestor).free,
                  target_game=str(output/game_part),target_game_windows=windows_path(output/game_part),
                  target_executable=str(output/game_part/exes[0].name),source_addons=addons_in(game))
    old_game=old_client/'_classic_beta_'
    result['old_addons']=addons_in(old_game)
    result['old_addons_source']=str(old_game) if old_game.is_dir() else None
    result['next_step']='Clone only the new baseline; verify launcher path and ordinary-world entry before addon and CASC migration'
    return result


def save_report(report,folder):
    folder=Path(folder).resolve()
    for key in ('requested_source','old_client','destination'):
        p=Path(report[key])
        if folder==p or folder.is_relative_to(p):raise ValueError('Reports must be outside source and client folders')
    if report.get('layout'):
        for part in report['layout']['parts']:
            p=Path(report['source_root'])/part
            if folder==p or folder.is_relative_to(p):raise ValueError('Reports must be outside selected client data')
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/('Forever-client-migration-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
    with path.open('x') as stream:json.dump(report,stream,indent=2,ensure_ascii=False)
    return path


def clone(report,progress=print):
    if report.get('format')!=FORMAT or report.get('status')!='READY_TO_CLONE':
        raise ValueError('Migration layout is not ready; inspect the metadata report first')
    root=Path(report['source_root'])
    if hashlib.sha256((root/'.build.info').read_bytes()).hexdigest()!=report['build_info_sha256']:
        raise ValueError('New client build changed after inspection; create a fresh plan')
    result=copier.prepare(root,Path(report['destination']),report['selected_build']['Build Key'],progress,layout=report['layout'])
    result.update(old_client=report['old_client'],preferred_launcher=report['preferred_launcher'],
                  launcher_candidates=report['launcher_candidates'],source_game=report['source_game'],
                  old_addons_source=report.get('old_addons_source'),old_casc_layers_transferred=False,
                  old_addons_transferred=False,baseline_runtime_verified=False)
    copier.save_state(Path(report['destination'])/MARKER,result)
    return result


def migrate_addons(output,backup,source=None):
    output=Path(output).resolve(strict=True)
    marker=output/MARKER;report=json.loads(marker.read_text())
    if report.get('format')!='wowforever-migrated-client-copy-v1' or report.get('destination')!=str(output):
        raise ValueError('Expected this migration tool\'s verified new-client copy')
    if report.get('old_addons_transferred'):raise ValueError('Old AddOns already migrated; backup is recorded in the copy marker')
    layout=report['layout'];target=output/layout['game_part']
    for name in ('.build.info',(Path(layout['game_part'])/layout['executable']).as_posix()):
        if copier.file_hash(output/name)!=report['sha256'][name]:
            raise ValueError('New client build/executable changed; inspect before migrating AddOns')
    source=Path(source or report.get('old_addons_source') or '')
    if not source.is_dir():raise ValueError('Specify the installed old AddOns client using --addons-source')
    addon_helper=load('copy-client-addons.py')
    copied=addon_helper.copy_addons(source,target,backup,target_executable=layout['executable'],merge=True)
    report.update(old_addons_transferred=True,addon_migration_backup=str(Path(backup).resolve()),
                  migrated_addon_source=str(source),addon_migration_files=len(copied['copied_files']),
                  addon_runtime_compatibility_verified=False)
    copier.save_state(marker,report)
    return copied


def restore_addons(output):
    output=Path(output).resolve(strict=True);marker=output/MARKER
    report=json.loads(marker.read_text())
    if (report.get('format')!='wowforever-migrated-client-copy-v1' or report.get('destination')!=str(output)
            or not report.get('old_addons_transferred') or not report.get('addon_migration_backup')):
        raise ValueError('No active AddOn migration in this client; nothing changed')
    backup=Path(report['addon_migration_backup']);saved=json.loads((backup/'addon-copy.json').read_text())
    target=output/report['layout']['game_part']
    if Path(saved['target_client']).resolve()!=target.resolve():raise ValueError('AddOn backup belongs to another client')
    load('copy-client-addons.py').restore(backup)
    history=list(report.get('addon_restore_history',[]))+[str(backup)]
    report.update(old_addons_transferred=False,addon_restore_history=history,addon_runtime_compatibility_verified=False)
    copier.save_state(marker,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','clone','addons','restore-addons'])
    parser.add_argument('--source',type=Path,default=Path('/mnt/e/WoW_Forever/_forever_'))
    parser.add_argument('--output',type=Path,default=Path('/mnt/e/WoWForEver-work/experiments/Forever-client-v2'))
    parser.add_argument('--old-client',type=Path,default=Path('/mnt/e/WoWForEver-work/experiments/Forever-Legion-client-v1'))
    parser.add_argument('--product');parser.add_argument('--executable');parser.add_argument('--report-dir',type=Path)
    parser.add_argument('--addons-source',type=Path);parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='restore-addons':
            restore_addons(args.output)
            return
        if args.action=='addons':
            backup=args.backup or args.output.resolve().parent.parent/'backups'/('new-client-v2-addons-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            migrate_addons(args.output,backup,args.addons_source)
            print('ADDON FILES MIGRATED; check compatibility in game. Backup:',backup,flush=True)
            return
        report=inspect(args.source,args.output,args.old_client,args.product,args.executable)
        folder=args.report_dir or args.output.resolve().parent.parent/'reports'
        path=save_report(report,folder)
        print(json.dumps(report,indent=2,ensure_ascii=False),flush=True);print('Migration report:',path,flush=True)
        if args.action=='clone':
            clone(report,lambda s:print(s,flush=True))
            print('NEW BASELINE COPY VERIFIED. Select this copied game folder in launcher 2.0.5; use beta only if needed.',flush=True)
    except KeyboardInterrupt:
        parser.exit(130,'Migration interrupted; rerun the same clone command to resume.\n')
    except (ValueError,OSError,KeyError,TypeError) as error:
        parser.exit(1,'Client migration stopped: '+str(error)+'\n')


if __name__=='__main__':main()
