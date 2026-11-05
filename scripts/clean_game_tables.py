"""Recover the missing native GameTable from this client's active ROOT.

Source storage is read-only. A public byte-for-byte copy is usable only when its
content MD5 occurs under the expected FileDataID in the active client ROOT.
No game payload is stored in this repository; no replacement values are made up.
"""
import hashlib
import importlib.util
import math
from pathlib import Path
import struct
import urllib.request

from casc_manifest_update import Encoding, root_groups

REQUIRED = ('ArtifactKnowledgeMultiplier.txt', 'ArtifactLevelXP.txt', 'BarberShopCostBase.txt',
            'BaseMp.txt', 'BattlePetXP.txt', 'CombatRatings.txt', 'CombatRatingsMultByILvl.txt',
            'ItemLevelByLevel.txt', 'ItemSocketCostPerLevel.txt', 'HpPerSta.txt',
            'NPCManaCostScaler.txt', 'SpellScaling.txt', 'StaminaMultByILvl.txt', 'xp.txt')
NAME = 'ArtifactKnowledgeMultiplier.txt'
FILE_ID = 1582086  # Pinned upstream src/tools/map_extractor/System.cpp.
MATCHING_COPY = {
    'url': 'https://raw.githubusercontent.com/BarryBogs/WoW-Classic-Era-Extracted-XML-LUA-Files/'
           '89599b0cae89d6197e0811673b797099d6580fe1/gametables/artifactknowledgemultiplier.txt',
    'ckey': '3ddba55743f8e03b19332267dec01bed',
    'sha256': '78d34c761f26694ca74f08464afaaa8a2084f5a212d6ecbcedecc6ad019fac80',
}
MAX_TABLE = 1024 * 1024

# Used inside the already-built image: only the generated gt directory is mounted.
# The process has no network, database, certificate or client mounts.
TABLE_WRITER = r'''
import base64, hashlib, json, os, pathlib, sys
message = json.load(sys.stdin)
body = base64.b64decode(message['body'], validate=True)
if not 0 < len(body) <= 1024 * 1024 or hashlib.sha256(body).hexdigest() != message['sha256']:
    raise SystemExit('GameTable writer payload checksum mismatch')
directory = pathlib.Path(sys.argv[1])
target = directory / 'ArtifactKnowledgeMultiplier.txt'
pending = directory / '.ArtifactKnowledgeMultiplier.txt.verified-partial'
if target.is_symlink() or (target.exists() and target.stat().st_size):
    raise SystemExit('Existing nonempty GameTable is preserved')
if pending.is_symlink():
    raise SystemExit('Linked GameTable temporary file is unsupported')
with pending.open('wb') as stream:
    stream.write(body)
    stream.flush()
    os.fsync(stream.fileno())
pending.replace(target)
'''


def validate_table(body):
    if not 0 < len(body) <= MAX_TABLE:
        raise ValueError('Invalid ArtifactKnowledgeMultiplier table size')
    lines = body.decode('ascii').splitlines()
    if not lines or lines[0].split('\t') != ['Level', 'Multiplier'] or len(lines) < 3:
        raise ValueError('Unexpected ArtifactKnowledgeMultiplier columns or empty data')
    for expected, line in enumerate(lines[1:]):
        columns = line.split('\t')
        if len(columns) != 2 or int(columns[0]) != expected:
            raise ValueError('Invalid ArtifactKnowledgeMultiplier row layout')
        multiplier = float(columns[1])
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError('Invalid ArtifactKnowledgeMultiplier multiplier')
    return len(lines) - 1


def missing_tables(output):
    return [name for name in REQUIRED if not (output / 'gt' / name).is_file()
            or (output / 'gt' / name).stat().st_size == 0]


def profiles(root):
    found = []
    for group in root_groups(root):
        file_id = 0
        ids = memoryview(root)[group['ids_offset']:group['ckeys_offset']]
        for index, (delta,) in enumerate(struct.iter_unpack('<I', ids)):
            file_id += delta
            if file_id == FILE_ID:
                offset = group['ckeys_offset'] + 16 * index
                found.append(dict(ckey=root[offset:offset + 16].hex(), locale=group['locale'],
                                  raw_flags=group['content_flags']))
            file_id += 1
    return found


def read_content(store, encoding, ckey):
    wanted = bytes.fromhex(ckey)
    failures = []
    for key, row in encoding.rows('c'):
        if key != wanted:
            continue
        for index in range(row[0]):
            ekey = row[22 + 16 * index:38 + 16 * index]
            if ekey[:9] not in store.entries:
                continue
            try:
                return store.read(ekey, wanted)
            except (OSError, ValueError) as error:
                failures.append(str(error))
        raise ValueError('No readable local encoding: ' + '; '.join(failures[:3]))
    raise ValueError('Content key absent from active ENCODING')


def download_matching_copy():
    request = urllib.request.Request(MATCHING_COPY['url'], headers={'User-Agent': 'Forever-clean-game-table-repair'})
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read(MAX_TABLE + 1)
    if hashlib.sha256(body).hexdigest() != MATCHING_COPY['sha256']:
        raise ValueError('Pinned GameTable download SHA-256 mismatch')
    return body


def open_store(client):
    spec = importlib.util.spec_from_file_location('clean_readonly_store', Path(__file__).with_name('update-casc-sandbox.py'))
    storelib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(storelib)
    return storelib.Store(client, synthetic_only=False, product='wowf')


def recover(client, expected_build_key, progress=print):
    progress('Reading current wowf ROOT and FileDataID 1582086; client storage is read-only...', flush=True)
    store = open_store(client)
    if store.build_key != expected_build_key:
        raise ValueError('Client build key changed since the clean extraction')
    ckey, ekey = store.values['encoding'].split()[:2]
    encoding = Encoding(store.read(bytes.fromhex(ekey), bytes.fromhex(ckey)))
    root = read_content(store, encoding, store.values['root'].split()[0])
    candidates = profiles(root)
    if not candidates:
        raise ValueError('FileDataID 1582086 is absent from the current ROOT; no unverified substitute is allowed')
    # Prefer the ordinary profile when both variants are available locally.
    candidates.sort(key=lambda row: (row['raw_flags'][0] != 0, row['ckey']))
    failures = []
    for row in candidates:
        try:
            body = read_content(store, encoding, row['ckey'])
            if hashlib.md5(body).hexdigest() != row['ckey']:
                raise ValueError('Local table content does not match the current ROOT')
            rows = validate_table(body)
        except (OSError, ValueError, UnicodeError) as error:
            failures.append(dict(ckey=row['ckey'], error=str(error)))
            continue
        return body, dict(source='current-client-local-encoding', selected_profile=row, rows=rows,
                          profiles=candidates, local_read_failures=failures)
    # The public copy's date/version is not trusted as proof of compatibility.
    # Exact membership in this client's active ROOT is required before download.
    matching = next((row for row in candidates if row['ckey'] == MATCHING_COPY['ckey']), None)
    if matching is None:
        raise ValueError('No readable local table and the pinned public copy does not match this client ROOT: '
                         + '; '.join(row['ckey'] + ': ' + row['error'] for row in failures))
    progress('Local table unavailable; downloading a copy with the exact current-client content hash...', flush=True)
    body = download_matching_copy()
    if hashlib.md5(body).hexdigest() != matching['ckey']:
        raise ValueError('Downloaded GameTable does not match the current client ROOT')
    rows = validate_table(body)
    return body, dict(source='content-matched-public-copy', url=MATCHING_COPY['url'],
                      selected_profile=matching, rows=rows, profiles=candidates, local_read_failures=failures)
