#!/usr/bin/env python3
"""Stage verified INSTALL files outside the owned client. Never activate or run it.

No downloads, CASC writes, server operations, config/metadata replacements or
hardlinks. A successful stage is not a complete or activated game installation.
"""
import argparse
import base64
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from casc_manifest_update import Encoding

spec = importlib.util.spec_from_file_location('stage_readonly_audit', Path(__file__).with_name('audit-client-preload.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def windows_version(path):
    """Read native string versions (70707 exceeds a 16-bit fixed-version field)."""
    if os.name == 'nt':
        winpath = str(path)
    else:
        match = re.fullmatch(r'/mnt/([a-zA-Z])/(.*)', str(path))
        if not match: raise ValueError('Staging must be on /mnt/<drive>/ for Windows version inspection')
        winpath = match[1].upper() + ':\\' + match[2].replace('/', '\\')
    if not shutil.which('powershell.exe'):
        raise ValueError('Windows PowerShell interop is unavailable; staged files are not version-confirmed')
    payload = base64.b64encode(winpath.encode('utf-8')).decode('ascii')
    script = ("$ErrorActionPreference='Stop';$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'));"
              "$v=(Get-Item -LiteralPath $p).VersionInfo;"
              "[pscustomobject]@{file=$v.FileVersion;product=$v.ProductVersion}|ConvertTo-Json -Compress")
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, timeout=30, check=True)
    versions = json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(versions, dict) or set(versions) != {'file', 'product'}:
        raise ValueError('Unexpected native Windows version response')
    return versions


def require_build(versions, expected):
    builds = []
    for name in ('file', 'product'):
        value = versions.get(name)
        if not isinstance(value, str): raise ValueError('Missing native EXE ' + name + ' version')
        matches = re.findall(r'(?<![\d.])1[.,]60[.,]1[.,](\d+)(?!\d)', value)
        if len(matches) != 1: raise ValueError('Ambiguous or missing native 1.60.1 EXE version')
        builds.append(int(matches[0]))
    if builds != [expected, expected]:
        raise ValueError('Native EXE versions do not match the requested build: ' + str(builds))


def selected_files(parsed, region):
    entries = audit.regional_entries(parsed, region)
    paths = [e['path'].casefold() for e in entries]
    if len(paths) != len(set(paths)): raise ValueError('Duplicate regional INSTALL destination')
    if paths.count('wow.exe') != 1 or paths.count('wow_loader.dll') != 1:
        raise ValueError('Expected one regional Wow.exe and wow_loader.dll')
    # Flat paths and parent directories must not alias each other on Windows.
    for path in paths:
        parts = path.split('/')
        if any('/'.join(parts[:i]) in paths for i in range(1, len(parts))):
            raise ValueError('INSTALL file/directory path collision')
    return entries


def destination_path(root, relative):
    at = root
    for part in relative.split('/'):
        matches = [p for p in at.iterdir() if p.name.casefold() == part.casefold()] if at.is_dir() else []
        if len(matches) > 1: raise ValueError('Case-ambiguous staging directory')
        at = matches[0] if matches else at / part
        if at.is_symlink(): raise ValueError('Linked staging path is unsupported')
    return at


def metadata_rows(info):
    """Public version/config identifiers only; do not collect installer sessions."""
    rows = list(csv.reader(info.decode('utf-8-sig').splitlines(), delimiter='|'))
    header = [value.split('!')[0] for value in rows[0]]
    wanted = {'Product', 'Active', 'Build Key', 'CDN Key', 'Install Key', 'Version', 'Tags', 'Branch'}
    values = [dict(zip(header, row)) for row in rows[1:]]
    return [{key: value for key, value in row.items() if key in wanted}
            for row in values if row.get('Product') == 'wowf']


def stage(client, destination, build_key=audit.TARGET_KEY, expected_build=70707, region='EU'):
    root, config_file, raw, config, active, before = audit.load_source(client, build_key, expected_build)
    destination = destination.absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('Use direct staging paths without links')
    parent = audit.direct(destination.parent)
    destination = parent / destination.name
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('Staging and source client must be separate')
    if destination.exists(): raise ValueError('Staging destination must not exist; existing files are never replaced')
    print('STAGING: reading verified local INSTALL and ENCODING...', file=sys.stderr, flush=True)
    store = audit.open_store(root)
    install_ck, install_ek = audit.pair(config, 'install')
    entries = selected_files(audit.parse_install_manifest(store.read(install_ek, install_ck)), region)
    required = sum(e['bytes'] for e in entries) + 256 * 1024**2
    if shutil.disk_usage(parent).free < required: raise ValueError('Insufficient space for separate INSTALL staging')
    ck, ek = audit.pair(config, 'encoding')
    encoding = Encoding(store.read(ek, ck))
    keys = {bytes.fromhex(e['ckey']) for e in entries}
    encoded = {}
    for ckey, entry in encoding.rows('c'):
        if ckey in keys:
            encoded[ckey] = [entry[22 + 16 * i:38 + 16 * i] for i in range(entry[0])]
        if len(encoded) == len(keys): break
    audit.unchanged(root, config_file, raw, before)
    destination.mkdir(mode=0o700)
    report = dict(format='wowforever-preload-stage-v1', phase='incomplete', source=str(root), destination=str(destination),
                  source_active_version=active.get('Version'), preload_build=expected_build, preload_build_key=build_key,
                  selected_install_tags=['Windows', 'x86_64', region], files=[], failures=[],
                  source_metadata_rows=metadata_rows(before[0]),
                  activated=False, exe_version_verified=False, full_asset_integrity_verified=False,
                  server_compatibility_verified=False)
    flavor = destination / '_forever_'
    flavor.mkdir()
    try:
        for index, entry in enumerate(entries, 1):
            print('STAGING: ' + str(index) + '/' + str(len(entries)) + ' ' + entry['path'], file=sys.stderr, flush=True)
            ckey = bytes.fromhex(entry['ckey'])
            failures = []
            data = None
            for ekey in encoded.get(ckey, []):
                try:
                    body = store.read(ekey, ckey)
                    if len(body) != entry['bytes'] or hashlib.md5(body).digest() != ckey:
                        raise ValueError('INSTALL file content/size mismatch')
                    data = body
                    break
                except (OSError, ValueError) as error:
                    failures.append(str(error))
            if data is None:
                report['failures'].append(dict(path=entry['path'], errors=failures[:3] or ['Content key is absent from target ENCODING']))
                continue
            path = destination_path(flavor, entry['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(data)
            if path.stat().st_size != entry['bytes'] or audit.md5_file(path) != entry['ckey']:
                raise ValueError('Staged file readback mismatch: ' + entry['path'])
            report['files'].append(dict(path=str(path.relative_to(destination)), ckey=entry['ckey'], bytes=len(data),
                                        sha256=hashlib.sha256(data).hexdigest()))
        audit.unchanged(root, config_file, raw, before)
        if report['failures']: raise ValueError('Some INSTALL files are not available as verified local copies; no activation performed')
        exe = destination_path(flavor, 'Wow.exe')
        report['native_exe_versions'] = windows_version(exe)
        require_build(report['native_exe_versions'], expected_build)
        # Recheck staged bytes after the external metadata query as well.
        for entry in report['files']:
            path = audit.direct(destination / entry['path'])
            if path.stat().st_size != entry['bytes'] or audit.md5_file(path) != entry['ckey']:
                raise ValueError('Staged content changed during version inspection')
        audit.unchanged(root, config_file, raw, before)
        report.update(phase='bootstrap-staged', exe_version_verified=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['detail'] = str(error)
    report['note'] = 'Only verified original INSTALL files were staged. No Data, .build.info, WTF, source installer settings or server state were changed. This folder is not an activated game installation.'
    with (destination / 'stage-report.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--build-key', default=audit.TARGET_KEY)
    parser.add_argument('--expected-build', type=int, default=70707)
    parser.add_argument('--region', choices=audit.REGIONS, default='EU')
    args = parser.parse_args()
    report = stage(args.client, args.destination, args.build_key, args.expected_build, args.region)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['phase'] == 'bootstrap-staged' else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Preload staging stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
