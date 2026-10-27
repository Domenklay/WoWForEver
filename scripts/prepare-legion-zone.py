#!/usr/bin/env python3
"""Prepare a hash-verified, dependency-reviewed single-tile RAW candidate.

Does not install a map, modify a client/server, or prove format compatibility.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import struct
import tempfile
import zipfile
from collections import Counter, deque
from pathlib import Path, PurePosixPath

NATIVE = {'.adt', '.wdt', '.wmo', '.m2', '.skin', '.blp', '.anim', '.skel', '.bone', '.tex', '.wdl', '.pd4'}
DEFAULT_CATALOG = Path(__file__).parents[1]/'content/donors/legion-735/export-filedata.csv'


def normalized(name):
    name = name.replace('\\', '/').lower()
    if name.startswith('world/maps/'):
        name = name[6:]
    return name.replace(' ', '') if name.startswith('maps/') else name


def chunks(data, reverse=True):
    offset = 0
    while offset < len(data):
        if offset+8 > len(data):
            raise ValueError('Truncated chunk header')
        tag, size = struct.unpack_from('<4sI', data, offset)
        if size > len(data)-offset-8:
            raise ValueError('Chunk exceeds file bounds')
        yield (tag[::-1] if reverse else tag).decode('ascii'), data[offset+8:offset+8+size]
        offset += 8+size


def integers(data, stride=4, offset=0):
    if len(data) % stride or offset+4 > stride:
        raise ValueError('Invalid reference array length')
    return [struct.unpack_from('<I', data, i+offset)[0] for i in range(0, len(data), stride)]


class Planner:
    def __init__(self, directory, catalog=DEFAULT_CATALOG, map_id=1220, build='12.1.5.70575'):
        self.root = Path(directory).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Expected RAW export directory')
        self.paths = {}
        if not isinstance(map_id, int) or isinstance(map_id, bool) or map_id <= 0:
            raise ValueError('Map ID must be positive')
        self.map_id, self.build = map_id, build
        self.ids = {}
        self.catalog = {}
        self.sidecar_edges = {}
        self.edges = set()
        self.missing = set()
        self.errors = []
        self.limits = set()
        self.unplaced_models = {}
        self.selected = set()
        self.overrides = {}
        self.bindings = {}
        self.sidecars = []
        self.observed = {}
        self.unknown_ids = []
        for path in sorted(self.root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Linked export paths are unsupported: '+str(path))
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            if path.suffix.lower() in NATIVE:
                key = normalized(relative)
                if key in self.paths:
                    raise ValueError('Ambiguous export path: '+relative)
                self.paths[key] = relative
                match = re.fullmatch(r'(?:.*/)?unknown/(\d+)\.[a-z0-9]+', relative.lower())
                if match:
                    self.unknown_ids.append((int(match[1]), relative))
            elif path.name.lower().endswith('.manifest.json'):
                self.sidecars.append(relative)
        self.catalog_sha256 = hashlib.sha256(Path(catalog).read_bytes()).hexdigest()
        with Path(catalog).open(encoding='utf-8-sig', newline='') as incoming:
            for row in csv.reader(incoming, delimiter=';'):
                if len(row) != 2 or not row[0].isdigit() or not 0 < int(row[0]) <= 0xffffffff:
                    raise ValueError('Invalid FileDataID catalog row')
                fid, name = int(row[0]), normalized(row[1])
                if fid in self.catalog and self.catalog[fid] != name:
                    raise ValueError('Conflicting FileDataID catalog')
                self.catalog[fid] = name
        for fid, path in self.unknown_ids:
            self.bind(fid, path, 'wow.export-unknown-ID-filename')
        self.load_sidecars()

    def path(self, relative):
        p = self.root/relative
        if p.is_symlink() or not p.resolve(strict=True).is_relative_to(self.root) or not p.is_file():
            raise ValueError('File leaves export directory: '+relative)
        return p

    def read(self, relative):
        path = self.path(relative)
        if path.stat().st_size > 256*1024*1024:
            raise ValueError('Resource exceeds 256 MiB per-file limit: '+relative)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if relative in self.observed and self.observed[relative] != digest:
            raise ValueError('Source changed since dependency review: '+relative)
        self.observed[relative] = digest
        return data

    def bind(self, fid, relative, evidence):
        if not isinstance(fid, int) or isinstance(fid, bool) or not 0 < fid <= 0xffffffff:
            raise ValueError('Invalid FileDataID')
        old = self.ids.get(fid)
        if old and old != relative:
            if self.path(old).read_bytes() != self.path(relative).read_bytes():
                raise ValueError(f'FileDataID {fid} maps to different contents')
            return
        self.ids[fid] = relative
        self.bindings.setdefault(relative, set()).add((fid, evidence))

    def resolve_sidecar(self, owner, name):
        if not isinstance(name, str) or ':' in name or name.startswith(('/', '\\')):
            raise ValueError('Unsafe sidecar reference')
        name = name.replace('\\', '/')
        base = PurePosixPath(owner)
        found = set()
        # wow.export WMO manifests use a virtual directory named after the root
        # WMO, even when the actual manifest is beside that WMO in RAW output.
        for anchor in (self.root/base.parent, self.root/base.parent/base.stem):
            candidate = (anchor/name).resolve()
            if candidate.is_relative_to(self.root):
                key = normalized(candidate.relative_to(self.root).as_posix())
                if key in self.paths:
                    found.add(self.paths[key])
        if len(found) > 1:
            raise ValueError('Ambiguous sidecar reference: '+name)
        return next(iter(found), None)

    def load_sidecars(self):
        for relative in self.sidecars:
            p = self.path(relative)
            if p.stat().st_size > 8*1024*1024:
                raise ValueError('Oversized sidecar: '+relative)
            data = json.loads(self.read(relative).decode('utf-8-sig'))
            base = relative[:-len('.manifest.json')]
            matches = [self.paths[normalized(base+ext)] for ext in ('.m2', '.wmo', '.skel')
                       if normalized(base+ext) in self.paths]
            if len(matches) != 1:
                raise ValueError('Sidecar primary asset is missing or ambiguous: '+relative)
            owner = matches[0]
            self.bind(data['fileDataID'], owner, 'sidecar-primary')
            references = set()
            def walk(value):
                if isinstance(value, dict):
                    if 'fileDataID' in value and 'file' in value:
                        fid = value['fileDataID']
                        if fid:
                            references.add(fid)
                            resolved = self.resolve_sidecar(owner, value['file'])
                            if resolved:
                                self.bind(fid, resolved, 'sidecar-reference')
                    for item in value.values():
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)
            walk(data)
            self.sidecar_edges[owner] = references

    def lookup(self, fid):
        if fid in self.ids:
            return self.ids[fid]
        path = self.paths.get(self.catalog.get(fid))
        if path:
            existing = {entry[0] for entry in self.bindings.get(path, ())}
            if existing and fid not in existing:
                self.errors.append(f'Catalog ID {fid} conflicts with authoritative binding for {path}')
                return None
            self.bind(fid, path, 'catalog-name')
        return path

    def select_tile(self, tile):
        if not re.fullmatch(r'\d{1,2}_\d{1,2}', tile) or any(int(v) > 63 for v in tile.split('_')):
            raise ValueError('Tile must be two indices 0..63')
        y, x = map(int, tile.split('_'))
        candidates = [p for p in self.paths.values() if p.lower().endswith('_'+tile+'.adt')]
        if len(candidates) != 1:
            raise ValueError('Expected exactly one root ADT for '+tile)
        root = candidates[0]
        table = list(chunks(self.read(root)))
        if next((b for t,b in table if t == 'MVER'), None) != struct.pack('<I', 18):
            raise ValueError('Unsupported terrain ADT version')
        cells = [b for t,b in table if t == 'MCNK']
        if (len(cells) != 256 or any(len(b) < 128 for b in cells) or
                {struct.unpack_from('<II', b, 4) for b in cells} != {(i,j) for i in range(16) for j in range(16)}):
            raise ValueError('Root ADT must contain all 256 terrain cells')
        origins = [b for b in cells if len(b) >= 128 and struct.unpack_from('<II', b, 4) == (0, 0)]
        if len(origins) != 1:
            raise ValueError('Missing or ambiguous ADT cell origin')
        px, py = struct.unpack_from('<2f', origins[0], 104)
        if not all(math.isfinite(v) for v in (px, py)) or max(abs(px-(32-x)*1600/3), abs(py-(32-y)*1600/3)) > .1:
            raise ValueError('ADT world coordinates disagree with the exported tile name')
        base = root[:-len('_'+tile+'.adt')]
        wdt = self.paths.get(normalized(base+'.wdt'))
        if not wdt:
            raise ValueError('Main terrain WDT missing')
        blocks = list(chunks(self.read(wdt)))
        by_tag = {t:b for t,b in blocks}
        if len(by_tag) != len(blocks) or len(by_tag.get('MAID', b'')) != 4096*32 or len(by_tag.get('MAIN', b'')) != 4096*8 or len(by_tag.get('MPHD', b'')) != 32:
            raise ValueError('Unsupported WDT table layout')
        if not struct.unpack_from('<I', by_tag['MPHD'])[0] & 0x200:
            raise ValueError('WDT does not advertise FileDataID-based MAID references')
        # wow.export stores its entries at y*64+x after transposing the native
        # x-major MAID array. Exported filenames are y_x, not native raw rows.
        index = x*64+y
        ids = struct.unpack_from('<8I', by_tag['MAID'], index*32)
        self.tile = dict(export_tile=tile, world_tile_x=x, world_tile_y=y, raw_maid_index=index,
                         root_file_data_id=ids[0], geometry_origin=[px, py], declared_map_id=self.map_id)
        for fid, suffix in zip(ids[:5], ('.adt', '_obj0.adt', '_obj1.adt', '_tex0.adt', '_lod.adt')):
            path = self.paths.get(normalized(base+'_'+tile+suffix))
            if fid and path:
                if fid in self.catalog and self.catalog[fid] != normalized(path):
                    raise ValueError('MAID FileDataID/name disagrees with catalog: '+path)
                self.bind(fid, path, 'WDT-MAID-and-ADT-coordinate-check')
            if fid:
                self.edges.add((wdt, fid, 'MAID'))
        for fid in ids[5:]:
            if fid:
                self.edges.add((wdt, fid, 'MAID-map-texture'))
        aux = struct.unpack('<8I', by_tag['MPHD'])[1:]
        for fid, suffix in zip(aux, ('_lgt.wdt', '_occ.wdt', '_fogs.wdt', '_mpv.wdt', '.tex', '.wdl', '.pd4')):
            path = self.paths.get(normalized(base+suffix))
            if fid and path:
                self.bind(fid, path, 'WDT-MPHD')
            if fid:
                self.edges.add((wdt, fid, 'MPHD'))
        wdt_ids = [fid for fid,name in self.catalog.items() if name == normalized(wdt)]
        if len(wdt_ids) == 1:
            self.bind(wdt_ids[0], wdt, 'catalog-map-definition')
        else:
            self.limits.add('Main WDT FileDataID is unknown or ambiguous')
        # Preserve the source; only the staged package copy gets one-cell MAIN/MAID.
        clipped = bytearray()
        for tag, block in blocks:
            if tag in {'MAIN', 'MAID'}:
                stride = 8 if tag == 'MAIN' else 32
                value = bytearray(len(block))
                value[index*stride:(index+1)*stride] = block[index*stride:(index+1)*stride]
                block = bytes(value)
            clipped.extend(tag[::-1].encode()+struct.pack('<I', len(block))+block)
        self.overrides[wdt] = bytes(clipped)
        self.wdt = wdt
        return wdt

    def references(self, relative, data):
        suffix = Path(relative).suffix.lower()
        found = {(fid, 'sidecar') for fid in self.sidecar_edges.get(relative, ())}
        if suffix in {'.adt', '.wmo', '.wdt'}:
            blocks = list(chunks(data))
            named = {t:b for t,b in blocks}
            if suffix == '.wdt' and re.search(r'_(?:lgt|occ|fogs|mpv)\.wdt$', relative, re.I):
                if len(named.get('MVER', b'')) != 4:
                    raise ValueError('Missing auxiliary WDT version')
                version = struct.unpack('<I', named['MVER'])[0]
                self.limits.add(relative+f': auxiliary WDT v{version} internal references not fully parsed')
                return found
            if named.get('MVER') != struct.pack('<I', 17 if suffix == '.wmo' else 18):
                raise ValueError('Unexpected native world file version')
            placed_models = None
            if 'MODI' in named:
                model_ids = integers(named['MODI'])
                if 'MODD' in named:
                    placements = named['MODD']
                    if len(placements) % 40:
                        raise ValueError('Invalid WMO MODD placement block length')
                    used_indices = {struct.unpack_from('<I', placements, off)[0] & 0xffffff
                                    for off in range(0, len(placements), 40)}
                    if any(index >= len(model_ids) for index in used_indices):
                        raise ValueError('WMO MODD references an invalid MODI index')
                    placed_models = {model_ids[index] for index in used_indices} - {0}
                    unused = set(model_ids)-placed_models-{0}
                    self.unplaced_models[relative] = sorted(unused)
                    # Sidecars supplement native references but cannot make
                    # unplaced model table slots into placed decorations.
                    found = {(fid,kind) for fid,kind in found if fid not in unused}
                else:
                    self.limits.add(relative+': MODD absent; conservatively following all MODI entries')
            for tag, block in blocks:
                if tag == 'MODI' and placed_models is not None:
                    found.update((fid, 'MODI-placed-by-MODD') for fid in placed_models)
                elif tag in {'GFID', 'MODI', 'MDID', 'MHID'}:
                    found.update((fid, tag) for fid in integers(block) if fid)
                elif tag in {'MDDF', 'MODF'}:
                    stride, flag_offset, mask = (36,34,0x40) if tag == 'MDDF' else (64,56,0x8)
                    if len(block) % stride:
                        raise ValueError('Invalid placement block')
                    for off in range(0, len(block), stride):
                        if not struct.unpack_from('<H', block, off+flag_offset)[0] & mask:
                            self.limits.add(relative+': legacy named placement references not parsed')
                        else:
                            found.add((struct.unpack_from('<I', block, off)[0], tag))
                elif tag == 'MOMT':
                    if 'MOTX' in named:
                        self.limits.add(relative+': named WMO textures not parsed')
                    else:
                        for offset in (12,24,36):
                            found.update((fid, 'MOMT') for fid in integers(block, 64, offset) if fid)
                elif tag == 'MODN':
                    self.limits.add(relative+': named WMO doodads not parsed')
                elif tag in {'MLMD', 'MLMX', 'MTXF'}:
                    self.limits.add(relative+': '+tag+' references require additional review')
        elif suffix in {'.m2', '.skel'}:
            if data[:4] == b'MD20':
                self.limits.add(relative+': legacy MD20 external references not parsed')
            else:
                for tag, block in chunks(data, reverse=False):
                    if tag in {'SFID', 'TXID', 'SKID', 'BFID', 'PFID', 'RPID', 'GPID'}:
                        found.update((fid, tag) for fid in integers(block) if fid)
                    elif tag == 'AFID':
                        found.update((fid, tag) for fid in integers(block, 8, 4) if fid)
                    elif tag == 'SKPD':
                        if len(block) != 16:
                            raise ValueError('Unsupported SKPD parent skeleton layout')
                        found.add((struct.unpack_from('<I', block, 8)[0], tag))
        elif suffix in {'.tex', '.wdl', '.pd4'}:
            self.limits.add(relative+': auxiliary map dependencies not fully parsed')
        elif suffix == '.blp' and data[:4] not in {b'BLP1', b'BLP2'}:
            raise ValueError('Not a native BLP texture')
        return {(fid, kind) for fid,kind in found if fid}

    def review(self, tile):
        start = self.select_tile(tile)
        todo = deque([start])
        while todo:
            relative = todo.popleft()
            if relative in self.selected:
                continue
            self.selected.add(relative)
            data = self.overrides.get(relative)
            if data is None:
                data = self.read(relative)
            try:
                found = self.references(relative, data)
            except (ValueError, UnicodeError, struct.error) as exc:
                self.errors.append(relative+': '+str(exc))
                found = set()
            if relative == self.wdt:
                found.update((fid,kind) for owner,fid,kind in self.edges if owner == relative)
            for fid, kind in sorted(found):
                self.edges.add((relative, fid, kind))
                path = self.lookup(fid)
                if path:
                    todo.append(path)
                else:
                    self.missing.add(fid)
        return dict(format='wowforever-legion-tile-package-v1', tile=self.tile,
                    declared_donor_build=self.build, donor_build_independently_verified=False,
                    catalog_sha256=self.catalog_sha256, source_files_modified=False,
                    missing_from_export=[dict(file_data_id=fid, catalog_path=self.catalog.get(fid),
                                              referenced_by=sorted({owner for owner,i,_ in self.edges if i == fid}))
                                         for fid in sorted(self.missing)],
                    errors=self.errors, coverage_limits=sorted(self.limits),
                    unplaced_wmo_model_ids=self.unplaced_models,
                    known_reference_closure=not self.missing and not self.errors,
                    full_dependency_closure_proven=False, installable=False,
                    compatibility_with_forever_70532='not verified',
                    remaining_requirements=['native format and ROOT/tag policy validation',
                                            'client/server Map record', 'server maps/vmaps and safe arrival point'])


def prepare(directory, output, tile='23_33', catalog=DEFAULT_CATALOG, progress=print,
            map_id=1220, build='12.1.5.70575'):
    output = Path(output).resolve()
    root = Path(directory).resolve(strict=True)
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Output must be a NEW directory outside the RAW export')
    progress('Indexing RAW export, sidecars and FileDataID names...')
    planner = Planner(root, catalog, map_id, build)
    progress('Validating ADT coordinates and following binary resource dependencies...')
    report = planner.review(tile)
    output.parent.mkdir(parents=True, exist_ok=True)
    estimate = sum(planner.path(name).stat().st_size for name in planner.selected)
    if shutil.disk_usage(output.parent).free < estimate+256*1024*1024:
        raise ValueError('Insufficient free space for candidate package and 256 MiB reserve')
    stage = Path(tempfile.mkdtemp(prefix=output.name+'.partial-', dir=output.parent))
    rows = []
    try:
        with zipfile.ZipFile(stage/'tile-candidate.zip', 'x', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for index, relative in enumerate(sorted(planner.selected)):
                path = planner.path(relative)
                source = planner.read(relative)
                data = planner.overrides.get(relative, source)
                name = 'data/'+relative
                archive.writestr(name, data)
                # Confirm packaged bytes and unchanged source, not merely successful write().
                with archive.open(name) as incoming:
                    packed = hashlib.sha256()
                    for block in iter(lambda: incoming.read(1024*1024), b''):
                        packed.update(block)
                if packed.hexdigest() != hashlib.sha256(data).hexdigest() or planner.read(relative) != source:
                    raise ValueError('Source changed or ZIP verification failed: '+relative)
                rows.append(dict(path=relative, bytes=len(data), sha256=packed.hexdigest(), ckey=hashlib.md5(data).hexdigest(),
                                 source_sha256=hashlib.sha256(source).hexdigest(),
                                 file_data_ids=sorted({fid for fid,_ in planner.bindings.get(relative, ())}),
                                 file_data_id_bindings=[dict(file_data_id=fid, evidence=evidence)
                                                       for fid,evidence in sorted(planner.bindings.get(relative, ()))],
                                 transformation='single-cell MAIN/MAID' if relative in planner.overrides else None))
                if index % 100 == 0:
                    progress(f'Packaged and verified {index+1}/{len(planner.selected)} files')
            report['files'] = rows
            report['counts'] = dict(Counter(Path(row['path']).suffix.lower() for row in rows))
            report['bytes'] = sum(row['bytes'] for row in rows)
            report['references'] = [dict(source=owner, file_data_id=fid, kind=kind) for owner,fid,kind in sorted(planner.edges)]
            archive.writestr('package-index.json', json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        for relative in list(planner.observed):
            planner.read(relative)
        packed_hash = hashlib.sha256()
        with (stage/'tile-candidate.zip').open('rb') as incoming:
            for block in iter(lambda: incoming.read(1024*1024), b''):
                packed_hash.update(block)
        report['package_sha256'] = packed_hash.hexdigest()
        (stage/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage)
        raise
    progress('Candidate package: '+str(output/'tile-candidate.zip'))
    progress('Report: '+str(output/'report.json'))
    progress(f"Files: {len(rows)}; unresolved FileDataIDs: {len(report['missing_from_export'])}; installable: false")
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tile', default='23_33')
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--map-id', type=int, default=1220)
    parser.add_argument('--build', default='12.1.5.70575')
    args = parser.parse_args()
    try:
        prepare(args.directory, args.output, args.tile, args.catalog, map_id=args.map_id, build=args.build)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, f'Zone preparation stopped: {error}\n')
