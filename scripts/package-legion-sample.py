#!/usr/bin/env python3
"""Package a small, hash-checked format sample; never installs or modifies game resources."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

MAX_BYTES = 20 * 1024 * 1024


def safe_file(root, relative):
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or '..' in rel.parts or '\\' in relative or ':' in relative:
        raise ValueError(f'Unsafe relative path: {relative!r}')
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError(f'Path leaves export directory: {relative}')
    if not path.is_file():
        raise ValueError(f'Not a file: {relative}')
    return path


def select_files(manifest, tile):
    if manifest.get('format') != 'wowforever-legion-export-audit-v1' or manifest.get('errors'):
        raise ValueError('Expected an audit-v1 manifest without structural errors')
    if not re.fullmatch(r'\d{1,2}_\d{1,2}', tile) or any(int(v) > 63 for v in tile.split('_')):
        raise ValueError('Tile must have the form 23_33, with indices 0..63')
    records = manifest['files']
    by_path = {r['path']: r for r in records}
    if len(by_path) != len(records):
        raise ValueError('Duplicate paths in manifest')
    roots = [r['path'] for r in records if r['path'].lower().endswith('_' + tile + '.adt')]
    if len(roots) != 1:
        raise ValueError(f'Expected exactly one root ADT for tile {tile}; found {len(roots)}')
    root = PurePosixPath(roots[0])
    map_name = root.stem[:-(len(tile) + 1)]
    selected = []

    def add(name, required=True):
        if name not in by_path:
            if required:
                raise ValueError(f'Required sample file missing from manifest: {name}')
            return
        if name not in selected:
            selected.append(name)

    for suffix in ('.adt', '_tex0.adt', '_obj0.adt', '_obj1.adt', '_lod.adt'):
        add(str(root.with_name(root.stem + suffix)) if suffix != '.adt' else str(root), suffix in {'.adt', '_tex0.adt', '_obj0.adt'})
    for suffix in ('.wdt', '_lgt.wdt', '_occ.wdt', '_fogs.wdt', '_mpv.wdt'):
        add(str(root.with_name(map_name + suffix)), suffix == '.wdt')
    wmos = sorted(r['path'] for r in records if r['path'].endswith('.wmo') and 'MOHD' in r.get('chunks', []))
    if not wmos:
        raise ValueError('No root WMO in manifest')
    wmo = next((w for w in wmos if PurePosixPath(w).name.lower() == 'dalaran2.wmo'), wmos[0])
    add(wmo)
    wmo_path = PurePosixPath(wmo)
    groups = sorted(r['path'] for r in records if 'MOGP' in r.get('chunks', []) and PurePosixPath(r['path']).parent == wmo_path.parent and PurePosixPath(r['path']).stem.startswith(wmo_path.stem + '_'))
    if not groups:
        raise ValueError('No group geometry for selected WMO')
    for name in groups[:3]:
        add(name)
    models = sorted(r['path'] for r in records if r['path'].endswith('.m2'))
    # Prefer a small Dalaran model for inspection, not a whole city dependency closure.
    models.sort(key=lambda n: ('/dalaran/' not in n, by_path[n]['bytes'], n))
    model = None
    skins = []
    for candidate in models:
        p = PurePosixPath(candidate)
        matches = sorted(r['path'] for r in records if r['path'].endswith('.skin') and PurePosixPath(r['path']).parent == p.parent and PurePosixPath(r['path']).stem.startswith(p.stem))
        if matches:
            model, skins = candidate, matches
            break
    if model is None:
        raise ValueError('No M2 with a matching SKIN sample')
    add(model)
    for name in skins[:2]:
        add(name)
    textures = sorted((r for r in records if r['path'].endswith('.blp') and r['bytes'] <= 1024 * 1024), key=lambda r: (r['bytes'], r['path']))
    for row in textures[:2]:
        add(row['path'])
    # wow.export sidecars contain FileDataID mappings; keep only these exact sidecars.
    sidecars = [str(PurePosixPath(n).with_suffix('.manifest.json')) for n in (model, wmo)]
    sidecars.append(str(root.with_name('adt_' + tile + '_ModelPlacementInformation.csv')))
    return by_path, selected, sidecars


def package(root, manifest_path, output, tile):
    root = root.resolve(strict=True)
    output = output.resolve()
    if not root.is_dir() or output.is_relative_to(root):
        raise ValueError('Use an export directory and an output ZIP outside it')
    manifest = json.loads(manifest_path.read_text())
    by_path, selected, sidecars = select_files(manifest, tile)
    payload = []
    total = 0
    for relative in selected:
        row = by_path[relative]
        path = safe_file(root, relative)
        expected_size = row['bytes']
        if not isinstance(expected_size, int) or expected_size < 0 or total + expected_size > MAX_BYTES:
            raise ValueError('Sample exceeds the 20 MiB upload budget')
        if path.stat().st_size != expected_size:
            raise ValueError(f'Size changed since audit: {relative}')
        data = path.read_bytes()
        if len(data) != expected_size or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError(f'SHA-256 changed since audit: {relative}; regenerate the manifest')
        total += len(data)
        payload.append((relative, data, True))
    for relative in sidecars:
        if not root.joinpath(*PurePosixPath(relative).parts).exists():
            continue
        path = safe_file(root, relative)
        if path.stat().st_size > 512 * 1024:
            continue
        data = path.read_bytes()
        if total + len(data) > MAX_BYTES:
            raise ValueError('Sample sidecars exceed upload budget')
        total += len(data)
        payload.append((relative, data, False))
    index = {
        'format': 'wowforever-legion-format-sample-v1', 'tile': tile,
        'declared_build': manifest.get('declared_build'), 'declared_map_id': manifest.get('declared_map_id'),
        'complete_zone_or_dependency_closure': False,
        'source_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'files': [{'path': n, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'matched_audit': verified} for n, b, verified in payload],
        'note': 'Format research only; representative models/textures may not be dependencies of the chosen tile.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: never replace an existing sample or user file.
    archive = zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED)
    try:
        with archive:
            archive.writestr('sample-index.json', json.dumps(index, ensure_ascii=False, indent=2))
            for relative, data, _ in payload:
                archive.writestr('data/' + relative, data)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tile', default='23_33')
    args = parser.parse_args()
    try:
        index = package(args.directory, args.manifest, args.output, args.tile)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(f"Sample: {args.output}\nFiles: {len(index['files'])}; ZIP bytes: {args.output.stat().st_size}")
    print('Original files unchanged. This is not an installable zone package.')


if __name__ == '__main__':
    main()
