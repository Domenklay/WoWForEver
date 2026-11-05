"""Change an existing texture binding, without allocating a FileDataID.

Pure metadata transforms. Native profiles must match exactly; opaque TVFS
records and all existing paths stay intact. Runtime acceptance is unknown.
"""
import struct

from casc_manifest_update import root_groups
from casc_texture_variants import profiles


def binding_pairs(root, target, donor):
    if target == donor or not all(type(i) is int and 0 < i < 0xf00000 for i in (target, donor)):
        raise ValueError('Choose two different existing native texture IDs below the private range')
    found = profiles(root, {target, donor})
    def indexed(rows):
        result = {}
        for row in rows:
            key = (row['locale'], tuple(row['raw_flags']))
            if key in result:
                raise ValueError('Duplicate native ROOT profile')
            result[key] = row
        return result
    left, right = indexed(found[target]), indexed(found[donor])
    if not left or left.keys() != right.keys():
        raise ValueError('Native texture locale/type/variant profiles do not match')
    pairs = [dict(original=left[key], replacement=right[key]) for key in sorted(left)]
    if any(p['original']['ckey'] == p['replacement']['ckey'] for p in pairs):
        raise ValueError('Textures share content; choose a visibly different donor')
    return pairs


def redirect_root(root, target, donor):
    pairs = binding_pairs(root, target, donor)
    by_profile = {(p['original']['locale'], tuple(p['original']['raw_flags'])): p for p in pairs}
    result = bytearray(root)
    changed = 0
    for group in root_groups(root):
        fid = 0
        for index, (delta,) in enumerate(struct.iter_unpack('<I', memoryview(root)[group['ids_offset']:group['ckeys_offset']])):
            fid += delta
            if fid == target:
                pair = by_profile[(group['locale'], tuple(group['content_flags']))]
                offset = group['ckeys_offset'] + 16 * index
                result[offset:offset+16] = bytes.fromhex(pair['replacement']['ckey'])
                changed += 1
            fid += 1
    if changed != len(pairs):
        raise ValueError('ROOT binding count changed unexpectedly')
    result = bytes(result)
    after = profiles(result, {target, donor})
    before = profiles(root, {target, donor})
    # Preserve group order as well as all flags, IDs, counters and name hashes.
    expected = [dict(row, ckey=by_profile[(row['locale'], tuple(row['raw_flags']))]['replacement']['ckey'])
                for row in before[target]]
    if after[target] != expected or after[donor] != before[donor]:
        raise ValueError('ROOT redirect failed its postcondition')
    return result, pairs


def redirect_child(tvfs, data, target, donor, pairs):
    before = tvfs.parse_tvfs(data, raw_paths=True)
    leaves = before['leaves']
    aliases, rows = {}, []
    for pair in pairs:
        old_key = pair['original']['ckey'].upper()
        new_key = pair['replacement']['ckey'].upper()
        old = f'{target:08X}' + old_key
        source = f'{donor:08X}' + new_key
        added = f'{target:08X}' + new_key
        if old not in leaves:
            continue
        if source not in leaves:
            raise ValueError('Donor is absent from the target native TVFS directory')
        if added in leaves:
            raise ValueError('Redirect alias already exists; nothing changed')
        if added in aliases and aliases[added] != source:
            raise ValueError('Ambiguous native texture alias')
        aliases[added] = source
        rows.append(dict(original=old, donor=source, added=added, original_ckey=old_key.lower(),
                         replacement_ckey=new_key.lower()))
    if not aliases:
        return None, []
    result = tvfs.alias_tvfs_paths(data, aliases)
    after = tvfs.parse_tvfs(result, raw_paths=True)
    if any(after['leaves'][key] != value for key, value in leaves.items()):
        raise ValueError('An existing TVFS route changed')
    return result, rows
