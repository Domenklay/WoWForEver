"""Reviewed release descriptors: client, core, extracted data and DB versions are distinct."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def release(identifier):
    catalog = json.loads((ROOT / 'releases/server-catalog.json').read_text())
    if catalog.get('format') != 'wowforever-server-releases-v1':
        raise ValueError('Unknown release catalog format')
    matches = [item for item in catalog['releases'] if item['id'] == identifier]
    if len(matches) != 1:
        raise ValueError('No reviewed release for that version; changing a build number is not a protocol upgrade')
    item = matches[0]
    if not re.fullmatch(r'[0-9a-f]{40}', item['core']) or not isinstance(item['client_build'], int):
        raise ValueError('Invalid pinned release identity')
    if not item.get('products') or set(item['products']) - {'wowf', 'wow_classic_beta'}:
        raise ValueError('Unsupported release products')
    database = item['database']
    if not database['from'] or not database['to']:
        raise ValueError('Explicit database versions are required')
    if database['from'] != database['to'] and not database['migrations']:
        raise ValueError('Database version changes require reviewed migrations')
    for migration in database['migrations']:
        migration_body(migration)
    return item


def migration_body(migration):
    if migration['database'] not in ('auth', 'world', 'characters', 'hotfixes'):
        raise ValueError('Unexpected migration database')
    relative = Path(migration['file'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Migration must be a repository-owned file')
    root = ROOT / 'releases/migrations'
    path = root / relative
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root.resolve()):
        raise ValueError('Linked or external migration is unsupported')
    if not 0 < path.stat().st_size <= 64 * 1024**2:
        raise ValueError('Unexpected migration size')
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != migration['sha256']:
        raise ValueError('Migration checksum changed; release needs review')
    return body.decode('utf-8-sig')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
