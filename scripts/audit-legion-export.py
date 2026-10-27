#!/usr/bin/env python3
"""Read-only inventory of a small wow.export RAW export. Does not install game data."""
import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

NATIVE = {'.wdt', '.adt', '.wmo', '.m2', '.blp', '.skin', '.anim', '.db2'}


def inspect_file(path):
    size = path.stat().st_size
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
        stream.seek(0)
        signature = stream.read(4)
        info = {'bytes': size, 'sha256': sha.hexdigest(), 'signature_hex': signature.hex()}
        if path.suffix.lower() in {'.wdt', '.adt', '.wmo'}:
            # Native world files use a stream of fourCC/uint32-size chunks.
            stream.seek(0)
            chunks = []
            while stream.tell() < size:
                header = stream.read(8)
                if len(header) != 8:
                    raise ValueError('truncated chunk header')
                tag, length = struct.unpack('<4sI', header)
                name = tag[::-1].decode('ascii', 'replace')
                if stream.tell() + length > size:
                    raise ValueError(f'{name} chunk exceeds file bounds')
                chunks.append(name)
                if name == 'MVER' and length == 4:
                    info['mver'] = struct.unpack('<I', stream.read(4))[0]
                else:
                    stream.seek(length, 1)
            if not chunks or chunks[0] != 'MVER':
                raise ValueError('expected native MVER chunk; possibly a converted or compressed file')
            info['chunks'] = sorted(set(chunks))
            auxiliary_wdt = re.search(r'_(?:lgt|occ|fogs|mpv)\.wdt$', path.name, re.I)
            if path.suffix.lower() == '.wdt' and not auxiliary_wdt:
                missing = {'MPHD', 'MAIN'} - set(chunks)
                if missing:
                    raise ValueError('terrain WDT missing chunks: ' + ', '.join(sorted(missing)))
            if re.search(r'_\d+_\d+\.adt$', path.name, re.I) and 'MCNK' not in chunks:
                raise ValueError('root ADT has no terrain MCNK chunks')
        elif path.suffix.lower() == '.blp' and signature not in {b'BLP1', b'BLP2'}:
            raise ValueError('expected a native BLP texture')
        elif path.suffix.lower() == '.m2' and signature not in {b'MD20', b'MD21'}:
            raise ValueError('expected a native M2 model')
        elif path.suffix.lower() == '.db2' and signature not in {b'WDB2', b'WDB5', b'WDB6', b'WDC1', b'WDC2', b'WDC3', b'WDC4', b'WDC5'}:
            raise ValueError('unrecognized DB2 signature')
        return info


def audit(root, build):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('export path must be a directory')
    files, errors = [], []
    paths = [p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and p.suffix.lower() in NATIVE]
    for path in paths:
        # Never follow a parent-directory symlink outside the selected export.
        if not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            files.append({'path': relative, **inspect_file(path)})
        except (ValueError, OSError) as exc:
            errors.append({'path': relative, 'error': str(exc)})
    counts = Counter(Path(row['path']).suffix.lower() for row in files)
    warnings = []
    if not counts['.wdt']:
        warnings.append('No native WDT; choose Export Raw in wow.export.')
    roots = [p for p in paths if re.search(r'_\d+_\d+\.adt$', p.name, re.I)]
    if not roots:
        warnings.append('No root terrain ADT tile detected.')
    names = {p.as_posix().lower() for p in paths}
    for p in roots:
        for suffix in ('_tex0.adt', '_obj0.adt'):
            sibling = p.with_name(p.stem + suffix).as_posix().lower()
            if sibling not in names:
                warnings.append(f'Missing companion for {p.relative_to(root)}: {suffix}')
    if not counts['.blp']:
        warnings.append('No BLP textures detected; asset dependencies may be incomplete.')
    return {
        'format': 'wowforever-legion-export-audit-v1',
        'declared_map_id': 1220,
        'declared_build': build,
        'build_and_map_independently_verified': False,
        'counts': dict(sorted(counts.items())),
        'root_terrain_tiles': len(roots),
        'errors': errors, 'warnings': warnings, 'files': files,
        'compatibility_with_forever_70532': 'not verified',
        'note': 'Structural inventory only; dependency closure and gameplay are not validated.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--build', default='unknown', help='Exact build displayed by wow.export; not inferred')
    parser.add_argument('--output', type=Path, required=True, help='JSON report outside the export directory')
    args = parser.parse_args()
    root = args.directory.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(root):
        parser.error('--output must be outside the export directory')
    result = audit(root, args.build)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False, indent=2))
    print(f'Report: {output}')
    return 1 if result['errors'] or not result['root_terrain_tiles'] or not result['counts'].get('.wdt') else 0


if __name__ == '__main__':
    raise SystemExit(main())
