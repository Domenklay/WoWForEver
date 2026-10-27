"""Observed native-container profile, deliberately restricted to small segments.

No game assets, installation, or claim of WowB.exe runtime compatibility.
Header checksum adaptation: CascLib, Copyright (c) 2014 Ladislav Zezula (MIT),
tools/legion-casc-probe/CASCLIB-LICENSE.txt. Absolute alignment and segment
addressing were matched against user-supplied metadata; lab code is separate.
"""
import struct

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('native_store', Path(__file__).with_name('update-casc-sandbox.py'))
store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(store)
lab = store.lab

_OFFSET_KEYS = (0x049396B8,0x72A82A9B,0xEE626CCA,0x9917754F,
                0x15DE40B1,0xF5A8A9B6,0x421EAC7E,0xA9D55C9A,
                0x317FD40C,0x04FAF80D,0x3D6BE971,0x52933CFD,
                0x27F64B7D,0xC6F5C11B,0xD5757E3A,0x6C388745)


def service_header(key, segment, offset):
    head = lab.storage_record(dict(ekey=key, encoded=b''), offset, flags=1)[:26]
    position = ((segment << 30) + offset + 30) & 0xffffffff
    encoded = (position ^ _OFFSET_KEYS[position & 15]).to_bytes(4, 'little')
    folded = bytearray(4)
    for index, value in enumerate(head):
        folded[index & 3] ^= value
    # Unlike the historical lab approximation, Agent's observed checksum uses
    # the combined archive position and absolute alignment of the offset mask.
    checksum = bytes(folded[(26+j)&3] ^ encoded[(offset+26+j)&3] for j in range(4))
    return head+checksum


def validate_prologue(raw, segment):
    if len(raw) != 480 or not 0 <= segment <= 255:
        raise ValueError('Only sixteen 30-byte slots and segment numbers <=255 are supported')
    rows = []
    for bucket in range(16):
        offset = bucket*30
        header = raw[offset:offset+30]
        key = header[:16][::-1]
        if struct.unpack_from('<IH', header, 16) != (30, 1):
            raise ValueError('Not a zero-payload, flag=1 segment slot')
        if key[1] != segment or lab.bucket(key) != (bucket-1) % 16:
            raise ValueError('Unsupported service key segment/bucket profile')
        if header != service_header(key, segment, offset):
            raise ValueError('Segment slot header checksum mismatch')
        rows.append(key)
    if any(key[2:] != rows[0][2:] for key in rows):
        raise ValueError('Inconsistent segment slot seed')
    return rows


def make_prologue(template, old_segment, new_segment):
    keys = validate_prologue(template, old_segment)
    if not 0 <= new_segment <= 255 or old_segment == new_segment:
        raise ValueError('Expected a different segment number <=255')
    output = bytearray()
    for bucket, original in enumerate(keys):
        key = bytearray(original)
        key[1] = new_segment
        matches = []
        for first in range(16):
            key[0] = first
            if lab.bucket(key) == (bucket-1) % 16:
                matches.append(bytes(key))
        if len(matches) != 1:
            raise ValueError('Ambiguous native service key')
        output.extend(service_header(matches[0], new_segment, bucket*30))
    validate_prologue(output, new_segment)
    return bytes(output)


def rewrite_index(raw, bucket, additions=()):
    parsed = store.read_index(raw, bucket)
    count = struct.unpack_from('<I', raw, 32)[0]
    if (parsed['layout'] != 'guarded' or len(raw) % 65536 or
            any(raw[40+count:]) or 'native-two-seed' not in parsed['checksum_modes']):
        raise ValueError('Unsupported native index allocation/checksum profile')
    records = sorted(parsed['records']+list(additions))
    if len({record[:9] for record in records}) != len(records):
        raise ValueError('Index prefix collision')
    high = low = 0
    for record in records:
        high, low = lab.hashlittle2(record, high, low)
    result = raw[:32]+struct.pack('<II', len(records)*18, high)+b''.join(records)
    if len(result) > len(raw):
        raise ValueError('Index allocation exhausted; expansion rules are not inferred')
    return result.ljust(len(raw), b'\0')


def plan_empty_segment(metadata, prologues):
    """Return new files and shmem. Does not write to a client directory."""
    shared = metadata['shmem']
    if len(shared) != 20480 or struct.unpack_from('<I', shared)[0] != 5:
        raise ValueError('Unsupported shmem profile')
    old_segments = sorted(prologues)
    if old_segments != list(range(len(old_segments))):
        raise ValueError('Expected contiguous existing segments')
    keys = {segment:validate_prologue(raw, segment) for segment,raw in prologues.items()}
    new_segment = old_segments[-1]+1
    prologue = make_prologue(prologues[old_segments[-1]], old_segments[-1], new_segment)
    new_keys = validate_prologue(prologue, new_segment)
    generations = struct.unpack_from('<16I', shared, 0x110)
    updated = bytearray(shared)
    payloads = {f'data.{new_segment:03d}':prologue}
    for bucket, generation in enumerate(generations):
        if generation >= 0xffffffff:
            raise ValueError('Index generation overflow')
        name = f'{bucket:02x}{generation:08x}.idx'
        raw = metadata[name]
        parsed = store.read_index(raw, bucket)
        if parsed['bits'] != 30:
            raise ValueError('Only the observed 30-bit offset profile is supported')
        records = {row[:9]:row for row in parsed['records']}
        for segment in old_segments:
            key = keys[segment][bucket][:9]
            expected = key+((segment << 30) | bucket*30).to_bytes(5, 'big')+struct.pack('<I', 30)
            if records.get(key) != expected:
                raise ValueError(f'Original service record missing: bucket {bucket}, segment {segment}')
        key = new_keys[bucket][:9]
        if key in records:
            raise ValueError('New segment service key already present')
        row = key+((new_segment << 30) | bucket*30).to_bytes(5, 'big')+struct.pack('<I', 30)
        payloads[f'{bucket:02x}{generation+1:08x}.idx'] = rewrite_index(raw, bucket, [row])
        struct.pack_into('<I', updated, 0x110+bucket*4, generation+1)
    return payloads, bytes(updated)
