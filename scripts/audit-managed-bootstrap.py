#!/usr/bin/env python3
"""Read-only native startup-manifest audit. No network or client writes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from casc_manifest_update import Encoding

spec = importlib.util.spec_from_file_location('bootstrap_readonly', Path(__file__).with_name('audit-client-preload.py'))
preload = importlib.util.module_from_spec(spec); spec.loader.exec_module(preload)
BUILD_KEY = '165410aca770316ea0f88100bb4830c2'


def declarations(config):
    names = [name for name in ('encoding', 'install', 'download', 'size', 'root') if name in config]
    names += sorted(name for name in config if name.startswith('vfs-') and not name.endswith('-size'))
    result = []
    for name in names:
        values = config[name].split()
        if not 1 <= len(values) <= 2 or not all(re.fullmatch('[0-9a-f]{32}', v) for v in values):
            raise ValueError('Invalid bootstrap key: ' + name)
        result.append(dict(name=name, ckey=values[0], ekey=values[1] if len(values) == 2 else None))
    if not {'encoding', 'install', 'download', 'root'} <= {row['name'] for row in result}:
        raise ValueError('Missing required startup manifest declarations')
    return result


def inspect_bootstrap(config, store):
    rows = declarations(config)
    encoding_error = None
    try:
        ck, ek = preload.pair(config, 'encoding')
        encoding = Encoding(store.read(ek, ck))
        unresolved = {bytes.fromhex(r['ckey']) for r in rows if not r['ekey']}
        if unresolved:
            for key, entry in encoding.rows('c'):
                if key in unresolved:
                    for row in rows:
                        if bytes.fromhex(row['ckey']) == key and not row['ekey']:
                            row['ekey'] = entry[22:38].hex()
                    unresolved.remove(key)
                    if not unresolved: break
    except (OSError, ValueError, KeyError) as error:
        encoding_error = str(error)
    checked = {}
    for row in rows:
        if not row['ekey']:
            row.update(status='unresolved', detail=encoding_error or 'CKey is not resolvable through local ENCODING')
            continue
        identity = (row['ckey'], row['ekey'])
        if identity not in checked:
            if bytes.fromhex(row['ekey'])[:9] not in store.entries:
                checked[identity] = dict(status='missing-local-object')
            else:
                try:
                    body = store.read(bytes.fromhex(row['ekey']), bytes.fromhex(row['ckey']))
                    checked[identity] = dict(status='verified-local', decoded_bytes=len(body))
                except (OSError, ValueError, KeyError) as error:
                    checked[identity] = dict(status='invalid-local-object', detail=str(error))
        row.update(checked[identity])
    bad = [r for r in rows if r['status'] != 'verified-local']
    return dict(bootstrap_complete=not bad, declarations=len(rows), distinct_checked_objects=len(checked),
                verified_declarations=len(rows) - len(bad), missing_or_invalid=bad[:32],
                missing_or_invalid_total=len(bad), missing_or_invalid_truncated=len(bad) > 32,
                main_manifests=[r for r in rows if not r['name'].startswith('vfs-')],
                full_asset_integrity_verified=False, playable_verified=False)


def audit(selected, build_key=BUILD_KEY):
    root, config_path, original, config, active, before = preload.load_source(selected, build_key, 70658)
    if active.get('Build Key') != build_key or active.get('Version') != '1.60.1.70658':
        raise ValueError('Audit requires the active managed 70658 build, not a preload')
    print('READ ONLY: reading local index generations and bootstrap manifests...', file=sys.stderr, flush=True)
    store = preload.open_store(root)
    report = dict(format='forever-managed-bootstrap-audit-v1', source=str(root), build=70658,
                  build_key=build_key, read_only=True, network_requests=0)
    report.update(inspect_bootstrap(config, store))
    cdn_key = active.get('CDN Key', '')
    if re.fullmatch('[0-9a-f]{32}', cdn_key):
        path = root / 'Data/config' / cdn_key[:2] / cdn_key[2:4] / cdn_key
        raw = preload.direct(path).read_bytes()
        if hashlib.md5(raw).hexdigest() != cdn_key: raise ValueError('CDN config checksum mismatch')
        cdn = dict(line.split(' = ', 1) for line in raw.decode().splitlines() if ' = ' in line)
        report['cdn_index_summary'] = {name: len(cdn.get(name, '').split()) for name in
                                      ('archives', 'archives-index-size', 'patch-archives', 'patch-archives-index-size')}
    preload.unchanged(root, config_path, original, before)
    print('READ ONLY: complete. No installation files changed.', file=sys.stderr, flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    args = parser.parse_args()
    try: print(json.dumps(audit(args.client), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps(dict(format='forever-managed-bootstrap-audit-v1', read_only=True, status='audit-incomplete', detail=str(error)), ensure_ascii=False, indent=2))
        raise SystemExit(1)
