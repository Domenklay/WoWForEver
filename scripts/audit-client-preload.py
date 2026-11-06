#!/usr/bin/env python3
"""Read-only audit of a cached preload's IN/ENCODING and Windows x64 bootstrap.

No download, activation, extraction, repair or .build.info update. A package
version alone never establishes a different EXE/protocol version. Does not
validate all game assets or certify a complete playable installation.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

from casc_manifest_update import Encoding

TARGET_KEY = '7feb61f3c994bcb168526b8db521514a'


def direct(path):
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Use direct paths without links')
    return path.resolve(strict=True)


def pair(config, name):
    fields = config.get(name, '').split()
    if len(fields) < 2 or not all(re.fullmatch('[0-9a-f]{32}', value) for value in fields[:2]):
        raise ValueError('Expected a verified CKey/EKey pair for ' + name)
    return tuple(bytes.fromhex(value) for value in fields[:2])


def parse_install_manifest(body):
    """IN v1, big endian sizes and MSB-first tag masks. No unsafe path accepted."""
    if len(body) > 16 * 1024**2 or len(body) < 10 or body[:4] != b'IN\x01\x10':
        raise ValueError('Unsupported or truncated install manifest')
    tags_count, count = struct.unpack_from('>HI', body, 4)
    if not 0 < count <= 100000 or tags_count > 1024:
        raise ValueError('Install manifest limits exceeded')
    position = 10
    def take(size):
        nonlocal position
        end = position + size
        if end > len(body): raise ValueError('Truncated install manifest field')
        value = body[position:end]; position = end
        return value
    def string():
        nonlocal position
        end = body.find(b'\0', position, min(len(body), position + 4096))
        if end < 0: raise ValueError('Unterminated install manifest string')
        value = body[position:end].decode('utf-8'); position = end + 1
        return value
    tags = []
    for _ in range(tags_count):
        name = string(); kind = struct.unpack('>H', take(2))[0]
        tags.append((name, kind, take((count + 7) // 8)))
    for wanted in ('Windows', 'x86_64'):
        if sum(name == wanted for name, _, _ in tags) != 1:
            raise ValueError('Exactly one Windows and x86_64 tag must be explicitly present')
    entries = []
    for index in range(count):
        name = string()
        parts = name.replace('\\', '/').split('/')
        if (not name or name.startswith(('/', '\\')) or ':' in name or
            any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in parts)):
            raise ValueError('Unsafe install path')
        ckey = take(16); size = struct.unpack('>I', take(4))[0]
        covers = [(tag, kind) for tag, kind, mask in tags if mask[index // 8] & (0x80 >> (index % 8))]
        # Numeric tag categories vary between products. Select by the actual
        # named masks, rather than assuming Windows=1 and architecture=2.
        selected = {'Windows', 'x86_64'} <= {tag for tag, _ in covers}
        entries.append(dict(path='/'.join(parts), ckey=ckey.hex(), bytes=size,
                            tags=[dict(name=tag, kind=kind) for tag, kind in covers],
                            selected_windows_x64=selected))
    if position != len(body):
        raise ValueError('Trailing install manifest bytes require review')
    return dict(tags=[dict(name=name, kind=kind,
                           entries=sum(bool(mask[i // 8] & (0x80 >> (i % 8))) for i in range(count)))
                      for name, kind, mask in tags], entries=entries)


def install_manifest(body):
    return [dict(path=e['path'], ckey=e['ckey'], bytes=e['bytes'])
            for e in parse_install_manifest(body)['entries'] if e['selected_windows_x64']]


def manifest_diagnostics(parsed):
    entries = parsed['entries']
    candidates = [e for e in entries if e['path'].lower().endswith('.exe') or
                  e['path'].rsplit('/', 1)[-1].lower() == 'wow_loader.dll']
    return dict(tags=parsed['tags'], entries=len(entries),
                windows_x64_entries=sum(e['selected_windows_x64'] for e in entries),
                executable_candidates=candidates[:64], executable_candidates_total=len(candidates),
                executable_candidates_truncated=len(candidates) > 64)


def open_store(root):
    spec = importlib.util.spec_from_file_location('preload_readonly_store', Path(__file__).with_name('update-casc-sandbox.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Store(root, synthetic_only=False, product='wowf', allow_duplicate_locations=True)


def stamp(root):
    return ((root / '.build.info').read_bytes(),
            [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in sorted((root / 'Data/data').iterdir())])


def md5_file(path):
    md5 = hashlib.md5()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024): md5.update(block)
    return md5.hexdigest()


def audit(selected, build_key=TARGET_KEY, expected_build=70707):
    root = direct(selected)
    if root.is_file(): root = root.parent
    if root.name == '_forever_': root = root.parent
    direct(root / 'Data/data')
    if not re.fullmatch('[0-9a-f]{32}', build_key): raise ValueError('Invalid target build key')
    config_file = direct(root / 'Data/config' / build_key[:2] / build_key[2:4] / build_key)
    raw = config_file.read_bytes()
    if len(raw) > 1024**2 or hashlib.md5(raw).hexdigest() != build_key:
        raise ValueError('Preload build config hash mismatch')
    config = dict(line.split(' = ', 1) for line in raw.decode('utf-8').splitlines() if ' = ' in line)
    match = re.fullmatch(r'WOW-(\d+)patch1\.60\.1_[A-Za-z0-9_]+', config.get('build-name', ''))
    if not match or int(match[1]) != expected_build:
        raise ValueError('Cached config is not the requested Forever package build')
    if config.get('build-uid') != 'wowf': raise ValueError('Preload product is not wowf')
    rows = list(csv.reader(direct(root / '.build.info').read_text(encoding='utf-8-sig').splitlines(), delimiter='|'))
    if not rows or any(len(row) != len(rows[0]) for row in rows[1:]): raise ValueError('Malformed .build.info')
    header = [k.split('!')[0] for k in rows[0]]
    active = [dict(zip(header, row)) for row in rows[1:]]
    active = [row for row in active if row.get('Product') == 'wowf' and row.get('Active') == '1']
    if len(active) != 1: raise ValueError('Expected one active wowf row')
    before = stamp(root)
    report = dict(format='wowforever-preload-audit-v1', audit_revision=2, source=str(root), active_metadata_version=active[0].get('Version'),
                  active_build_key=active[0].get('Build Key'), preload_build=expected_build, preload_build_key=build_key,
                  comparison_only=True, activated=False, activation_ready=False,
                  protocol_build_verified=False, full_asset_integrity_verified=False, bootstrap=[])
    try:
        print('READ ONLY: loading local CASC index generations...', file=sys.stderr, flush=True)
        store = open_store(root)
        print('READ ONLY: validating the target INSTALL manifest...', file=sys.stderr, flush=True)
        install_ckey, install_ekey = pair(config, 'install')
        parsed = parse_install_manifest(store.read(install_ekey, install_ckey))
        report['install_manifest'] = manifest_diagnostics(parsed)
        entries = [dict(path=e['path'], ckey=e['ckey'], bytes=e['bytes'])
                   for e in parsed['entries'] if e['selected_windows_x64']]
        report['windows_install_entries'] = len(entries)
        wanted = [entry for entry in entries if entry['path'].lower() in ('wow.exe', 'wow_loader.dll')]
        if sum(entry['path'].lower() == 'wow.exe' for entry in wanted) != 1 or len(wanted) != len({e['path'].lower() for e in wanted}):
            raise ValueError('Cannot select one root Windows x64 Wow.exe; see install_manifest tags and executable_candidates. No path or tag substitution was performed.')
        print('READ ONLY: comparing active bootstrap files with the target manifest...', file=sys.stderr, flush=True)
        for entry in wanted:
            current = root / '_forever_' / entry['path']
            if current.exists(): current = direct(current)
            row = dict(entry, matches_active_file=current.is_file() and current.stat().st_size == entry['bytes'] and md5_file(current) == entry['ckey'],
                       verified_local_preload_copy=False, local_read_errors=[])
            report['bootstrap'].append(row)
        ck, ek = pair(config, 'encoding')
        print('READ ONLY: validating target ENCODING (this package declares ' + config.get('encoding-size', '?') + ' bytes)...', file=sys.stderr, flush=True)
        encoding = Encoding(store.read(ek, ck))
        missing = {bytes.fromhex(entry['ckey']): entry for entry in report['bootstrap']}
        for key, entry in encoding.rows('c'):
            if key not in missing: continue
            row = missing.pop(key)
            for i in range(entry[0]):
                ekey = entry[22 + 16 * i:38 + 16 * i]
                try:
                    data = store.read(ekey, key)
                    if len(data) != row['bytes']: raise ValueError('Bootstrap size mismatch')
                    row['verified_local_preload_copy'] = True
                    break
                except (OSError, ValueError) as error:
                    if len(row['local_read_errors']) < 3: row['local_read_errors'].append(str(error))
                    continue
            if not missing: break
        report['status'] = 'manifest-verified'
        print('READ ONLY: bootstrap audit finished; no client files changed.', file=sys.stderr, flush=True)
        report['note'] = 'Bootstrap hashes are from the target manifest. A matching old EXE does not imply a new protocol version. No activation or download was performed.'
    except (OSError, ValueError, KeyError) as error:
        report['status'] = 'cannot-complete-local-audit'
        report['detail'] = str(error)
    if stamp(root) != before:
        raise ValueError('Client storage changed during audit; close the game/source launcher and retry')
    if config_file.read_bytes() != raw:
        raise ValueError('Preload config changed during audit')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--build-key', default=TARGET_KEY)
    parser.add_argument('--expected-build', type=int, default=70707)
    args = parser.parse_args()
    print(json.dumps(audit(args.client, args.build_key, args.expected_build), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError) as error:
        print('Preload audit stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
