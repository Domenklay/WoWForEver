"""Pure planners for the one-tile server hotfix experiment (no deployment)."""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct

from legion_map_db2 import MapTable

MAP_ID = 1220
WDT_ID = 15730590
PREFIX = 'legion1220_'
MAP_COLUMNS = ('ID Directory MapName MapDescription0 MapDescription1 PvpShortDescription '
               'PvpLongDescription CorpseX CorpseY MapType InstanceType ExpansionID AreaTableID '
               'LoadingScreenID TimeOfDayOverride ParentMapID CosmeticParentMapID TimeOffset '
               'MinimapIconScale CorpseMapID MaxPlayers WindSettingsID ZmpFileDataID WdtFileDataID '
               'OceanLiquidTypeID NavigationMaxDistance PreloadFileDataID Flags1 Flags2 Flags3').split()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_file(root, relative):
    p = Path(relative)
    if p.is_absolute() or not p.parts or any(x in {'..', '.'} for x in p.parts):
        raise ValueError('Unsafe geometry path')
    result = root / p
    if any(x.is_symlink() for x in [root, result, *result.parents]):
        raise ValueError('Linked geometry paths are unsupported')
    if not result.is_file():
        raise ValueError('Missing geometry: ' + str(p))
    return result


def tile_names(data, models):
    """Rewrite only length-prefixed ModelSpawn names; preserve IDs and bounds."""
    if len(data) < 12 or data[:8] != b'VMAP_4.E':
        raise ValueError('Unexpected VMAP tile header')
    count = struct.unpack_from('<I', data, 8)[0]
    if count > 100000:
        raise ValueError('Too many VMAP spawns')
    result = bytearray(data[:12]); offset = 12
    for _ in range(count):
        if offset + 34 > len(data):
            raise ValueError('Truncated VMAP spawn')
        start = offset
        offset += 34 + (24 if data[start] & 1 else 0)
        if offset + 4 > len(data):
            raise ValueError('Truncated VMAP name length')
        length = struct.unpack_from('<I', data, offset)[0]
        if not 0 < length <= 480 or offset + 4 + length > len(data):
            raise ValueError('Invalid VMAP name bounds')
        name = data[offset+4:offset+4+length].decode('ascii')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name + '.vmo' not in models:
            raise ValueError('Missing or unsafe VMAP model: ' + name)
        new = (PREFIX + name).encode('ascii')
        result += data[start:offset] + struct.pack('<I', len(new)) + new
        offset += 4 + length
    if offset != len(data):
        raise ValueError('Unexpected VMAP tile trailing bytes')
    return bytes(result), count


def stage_geometry(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    report_bytes = (source/'report.json').read_bytes()
    report = json.loads(report_bytes)
    if (report.get('format') != 'wowforever-legion-geometry-extraction-v1' or
            not report.get('geometry_probe_passed') or report.get('errors') or
            report.get('map_id') != MAP_ID or report.get('wdt_file_data_id') != WDT_ID or
            report['tile']['world_tile_x'] != 33 or report['tile']['world_tile_y'] != 23 or
            report['tile']['raw_maid_index'] != 2135 or
            report.get('compiled_core_revision') != '91d49b230f89c3ab4719f5b2b2d1e70ed36613c4' or
            not report.get('client_metadata_unchanged')):
        raise ValueError('Expected the successful Dalaran tile geometry report')
    records = {}
    for row in report['files']:
        if row['path'] in records:
            raise ValueError('Duplicate geometry report path')
        p = safe_file(source, row['path'])
        if p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
            raise ValueError('Geometry changed: ' + row['path'])
        records[row['path']] = p
    models = {p.name for name, p in records.items() if re.fullmatch(r'vmaps/[A-Za-z0-9_.-]+\.vmo', name)}
    if not models or 'maps/1220_33_23.map' not in records or 'vmaps/1220/1220.vmtree' not in records:
        raise ValueError('Missing terrain, collision tree or models')
    # Old extraction reports did not inventory .vmtileidx. They are required by
    # this core: validate and copy them together with every reported VMAP tile.
    planned = {}
    for relative, p in records.items():
        if relative.startswith('vmaps/') and p.name in models:
            planned['vmaps/'+PREFIX+p.name] = p
        elif re.fullmatch(r'vmaps/1220/1220_\d{2}_\d{2}\.vmtile', relative):
            body, count = tile_names(p.read_bytes(), models)
            planned[relative] = body
            idx_relative = relative + 'idx'
            idx = safe_file(source, idx_relative)
            data = idx.read_bytes()
            if (len(data) != 12+4*count or data[:8] != b'VMAP_4.E' or
                    struct.unpack_from('<I', data, 8)[0] != count):
                raise ValueError('VMAP spawn index does not match tile: '+idx_relative)
            planned[idx_relative] = data
        elif relative in {'maps/1220.tilelist', 'maps/1220_33_23.map', 'vmaps/1220/1220.vmtree'}:
            planned[relative] = p
        else:
            raise ValueError('Unexpected geometry file: '+relative)
    if 'vmaps/1220/1220_33_23.vmtile' not in planned:
        raise ValueError('Central collision tile missing')
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for relative, value in sorted(planned.items()):
        target = destination/relative; target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, Path): shutil.copyfile(value, target)
        else: target.write_bytes(value)
        files.append(dict(path=relative, bytes=target.stat().st_size, sha256=sha(target)))
    return dict(source_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
                source_install_operation=report['source_install_operation'], files=files,
                model_names_isolated=True, original_geometry_modified=False)


def sql_literal(value):
    if isinstance(value, str):
        # Hex UTF-8 literals do not depend on MySQL backslash escaping modes.
        return "CONVERT(X'"+value.encode('utf-8').hex()+"' USING utf8mb4)" if value else "''"
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError('Invalid SQL scalar')
    return repr(value)


def map_values(data):
    table = MapTable(data)
    if MAP_ID in table.reserved:
        raise ValueError('Map 1220 already exists in server DB2')
    row = list(table.semantic[0])
    if row[8] != 0:  # InstanceType, not MapType
        raise ValueError('Map zero is not an outdoor template')
    values = [MAP_ID, 'ForeverDalaran', 'Dalaran (Legion test)', '', '', '', '']
    # Corpse is an array of two floats. MapTable returns the packed raw words.
    corpse = row[6]
    if corpse != 0:
        raise ValueError('Unsupported nonzero packed corpse coordinate template')
    values += [0.0, 0.0]
    values += row[7:16]
    values += [struct.unpack('<f', struct.pack('<I', row[16]))[0]]
    values += row[17:25]
    values += list(row[25])
    if len(values) != len(MAP_COLUMNS):
        raise ValueError('Unexpected Map field count')
    result = dict(zip(MAP_COLUMNS, values))
    # Sign extension is needed for scalar palette values decoded as uint32.
    for name, width in [('LoadingScreenID',16),('TimeOfDayOverride',16),('ParentMapID',16),
                        ('CosmeticParentMapID',16),('CorpseMapID',16),('WindSettingsID',16),
                        ('ZmpFileDataID',32),('WdtFileDataID',32),('OceanLiquidTypeID',32),
                        ('NavigationMaxDistance',32),('PreloadFileDataID',32),
                        ('Flags1',32),('Flags2',32),('Flags3',32)]:
        value = result[name] & ((1 << width)-1)
        result[name] = value-(1 << width) if value & (1 << (width-1)) else value
    result.update(WdtFileDataID=WDT_ID, ZmpFileDataID=0, PreloadFileDataID=0, ExpansionID=0)
    return table.table_hash, result


def apply_sql(values, table_hash, push_id):
    if set(values) != set(MAP_COLUMNS) or not 0 < push_id < 0x7fffffff:
        raise ValueError('Invalid activation SQL input')
    columns = ','.join('`'+x+'`' for x in MAP_COLUMNS+['VerifiedBuild'])
    vals = ','.join(sql_literal(values[x]) for x in MAP_COLUMNS)+',0'
    return (f'START TRANSACTION;\nINSERT INTO hotfixes.`map` ({columns}) VALUES ({vals});\n'
            'INSERT INTO hotfixes.map_locale (ID,locale,MapName_lang,MapDescription0_lang,MapDescription1_lang,'
            'PvpShortDescription_lang,PvpLongDescription_lang,VerifiedBuild) '
            f"VALUES (1220,'ruRU',{sql_literal('Даларан (Legion test)')},'','','','',0);\n"
            f'INSERT INTO hotfixes.hotfix_data (Id,UniqueId,TableHash,RecordId,Status,VerifiedBuild) '
            f'VALUES ({push_id},1,{table_hash},1220,1,0);\nCOMMIT;\n')


def rollback_sql(table_hash, push_id):
    # A fresh removal push invalidates the client's realm-specific hotfix cache.
    # Move only characters on the experimental map; preserve all other progress.
    return f'''START TRANSACTION;
UPDATE characters.characters c LEFT JOIN characters.character_homebind h ON h.guid=c.guid
SET c.map=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.mapId,0),
 c.position_x=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.posX,-8949.95),
 c.position_y=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.posY,-132.493),
 c.position_z=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.posZ,83.5312),
 c.orientation=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.orientation,0),
 c.zone=IF(h.mapId IS NOT NULL AND h.mapId<>1220,h.zoneId,12),c.instance_id=0
WHERE c.map=1220;
DELETE FROM hotfixes.`map` WHERE ID=1220 AND VerifiedBuild=0;
DELETE FROM hotfixes.map_locale WHERE ID=1220 AND VerifiedBuild=0 AND locale='ruRU';
DELETE FROM hotfixes.hotfix_data WHERE Id={push_id} AND TableHash={table_hash} AND RecordId=1220;
INSERT INTO hotfixes.hotfix_data (Id,UniqueId,TableHash,RecordId,Status,VerifiedBuild)
SELECT COALESCE(MAX(Id),0)+1,1,{table_hash},1220,2,0 FROM hotfixes.hotfix_data;
COMMIT;
'''
