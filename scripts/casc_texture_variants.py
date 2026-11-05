"""One-texture ROOT variant transform; no file IO or payload substitution."""
import struct

from casc_manifest_update import root_groups


def profiles(data, wanted):
    found = {fid: [] for fid in wanted}
    for group in root_groups(data):
        fid = 0
        for index, (delta,) in enumerate(struct.iter_unpack('<I', memoryview(data)[group['ids_offset']:group['ckeys_offset']])):
            fid += delta
            if fid in found:
                offset = group['ckeys_offset'] + index * 16
                found[fid].append(dict(locale=group['locale'], raw_flags=group['content_flags'],
                                       ckey=data[offset:offset+16].hex()))
            fid += 1
    return found


def mirror_alternate(data, original_id, private_id):
    """Append the source's missing flag-1 profile, keeping all old groups intact.

    No assertion is made about the meaning of flag 1 or its selection by WowB.
    Referenced alternate content can be nonresident, just as for the source ID.
    """
    if original_id == private_id or not all(0 < fid <= 0xffffffff for fid in (original_id, private_id)):
        raise ValueError('Invalid texture ID pair')
    observed = profiles(data, {original_id, private_id})
    source, target = observed[original_id], observed[private_id]
    base = [p for p in source if p['raw_flags'][0] == 0]
    alternate = [p for p in source if p['raw_flags'][0] == 1]
    if len(source) != 2 or len(base) != 1 or len(alternate) != 1 or target != base:
        raise ValueError('Expected two native variants and exactly the matching private base variant')
    base, added = base[0], alternate[0]
    if (base['locale'] != added['locale'] or base['raw_flags'][1:] != added['raw_flags'][1:]
            or not base['raw_flags'][1] & 0x10000000):
        raise ValueError('Unsupported native variant locale/type/name profile')
    count = struct.unpack_from('<I', data, 12)[0]
    if count == 0xffffffff:
        raise ValueError('ROOT record count overflow')
    group = struct.pack('<4IBI', 1, added['locale'], *added['raw_flags'], private_id)
    group += bytes.fromhex(added['ckey'])
    header = bytearray(data[:24])
    struct.pack_into('<I', header, 12, count + 1)
    result = bytes(header) + data[24:] + group
    check = profiles(result, {original_id, private_id})
    if check[original_id] != source or check[private_id] != target + [added]:
        raise ValueError('ROOT variant transform failed its postcondition')
    return result, added
