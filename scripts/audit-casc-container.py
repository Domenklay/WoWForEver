#!/usr/bin/env python3
"""Read-only native-container metadata collection and offline analysis.

Reports observations, not an installer or proof of WowB.exe compatibility.
Never extracts archive members or writes to a client installation.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import struct
import zipfile
from pathlib import Path
from casc_native_container import service_header

SPEC = importlib.util.spec_from_file_location('container_store', Path(__file__).with_name('update-casc-sandbox.py'))
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)
INDEX = re.compile(r'metadata/([0-9a-f]{2})([0-9a-f]{8})\.idx')


def analyze(package):
    indexes = []
    with zipfile.ZipFile(package) as archive:
        members = archive.infolist()
        if len({m.filename for m in members}) != len(members):
            raise ValueError('Duplicate archive members')
        if sum(m.file_size for m in members) > 64*1024*1024:
            raise ValueError('Metadata package exceeds 64 MiB')
        allowed = {'metadata/shmem', 'segment-headers.json'}
        if any(not INDEX.fullmatch(m.filename) and m.filename not in allowed for m in members):
            raise ValueError('Unexpected metadata member')
        headers = json.loads(archive.read('segment-headers.json'))
        segments = {}
        for name, item in sorted(headers.items()):
            if not re.fullmatch(r'data\.\d{3}', name):
                raise ValueError('Invalid segment name')
            raw = bytes.fromhex(item.get('first_480_bytes', item.get('first_30_bytes', '')))
            if len(raw) not in (30, 480):
                raise ValueError('Expected exactly 30 or 480 header bytes')
            slots = []
            for offset in range(0, len(raw), 30):
                record = raw[offset:offset+30]
                slots.append(dict(offset=offset, key_prefix=record[:16][::-1][:9].hex(),
                                  record_bytes=int.from_bytes(record[16:20], 'little'),
                                  flags=int.from_bytes(record[20:22], 'little'),
                                  native_header_checksums_match=(record == service_header(
                                      record[:16][::-1], int(name[5:]), offset))))
            segments[name] = dict(bytes=item['bytes'], sampled_slots=slots)
        shared = archive.read('metadata/shmem')
        if len(shared) != 20480 or struct.unpack_from('<I', shared)[0] != 5:
            raise ValueError('Unsupported shmem profile; expected observed v5, 20480 bytes')
        # Observed offsets in this client profile; never used to edit shmem.
        generations = list(struct.unpack_from('<16I', shared, 0x110))
        for item in members:
            match = INDEX.fullmatch(item.filename)
            if not match:
                continue
            bucket, generation = (int(value, 16) for value in match.groups())
            if bucket > 15:
                raise ValueError('Invalid index bucket')
            raw = archive.read(item)
            parsed = store.read_index(raw, bucket)
            zero_payload, payload_bucket_mismatch = [], 0
            for row in parsed['records']:
                location = int.from_bytes(row[9:14], 'big')
                segment, offset = location >> parsed['bits'], location & ((1 << parsed['bits'])-1)
                length = int.from_bytes(row[14:], 'little')
                if length == 30:
                    known = segments.get(f'data.{segment:03d}', {}).get('sampled_slots', [])
                    samples = [sample for sample in known if sample['offset'] == offset]
                    matches = bool(samples and samples[0]['key_prefix'] == row[:9].hex()
                                   and samples[0]['record_bytes'] == 30 and samples[0]['flags'] == 1)
                    zero_payload.append(dict(segment=segment, offset=offset, key_prefix=row[:9].hex(),
                                             sampled_header_matches=matches))
                elif store.lab.bucket(row[:9]) != bucket:
                    payload_bucket_mismatch += 1
            count = struct.unpack_from('<I', raw, 32)[0]
            tail = raw[40+count:] if count else b''
            indexes.append(dict(bucket=bucket, generation=generation, bytes=len(raw),
                                sha256=hashlib.sha256(raw).hexdigest(), layout=parsed['layout'],
                                checksum_modes=parsed['checksum_modes'],
                                aligned_to_64k=len(raw) % 65536 == 0,
                                trailing_bytes=len(tail), trailing_all_zero=not any(tail),
                                records=len(parsed['records']), payload_bucket_mismatches=payload_bucket_mismatch,
                                zero_payload_records=zero_payload))
    return dict(format='wowforever-native-container-observations-v1',
                package_sha256=hashlib.sha256(Path(package).read_bytes()).hexdigest(),
                indexes=sorted(indexes, key=lambda row: (row['bucket'], row['generation'])),
                segments=segments, observed_shmem_index_generations=generations,
                complete_16_buckets={row['bucket'] for row in indexes} == set(range(16)),
                client_runtime_compatibility_proven=False)


def collect(client, output):
    client = client.resolve(strict=True)
    folder = client/'Data/data'
    if folder.is_symlink() or output.resolve().is_relative_to(client/'Data') or output.resolve() == client/'.build.info':
        raise ValueError('Use a report destination outside the source client tree')
    shared = (folder/'shmem').read_bytes()
    if len(shared) != 20480 or struct.unpack_from('<I', shared)[0] != 5:
        raise ValueError('Unsupported shmem profile')
    selected = {'metadata/shmem':shared}
    for bucket, generation in enumerate(struct.unpack_from('<16I', shared, 0x110)):
        path = folder/f'{bucket:02x}{generation:08x}.idx'
        if path.is_symlink() or path.stat().st_size > 4*1024*1024:
            raise ValueError('Unsupported index file')
        selected['metadata/'+path.name] = path.read_bytes()
    headers = {}
    for path in sorted(folder.glob('data.[0-9][0-9][0-9]')):
        if path.is_symlink():
            raise ValueError('Linked data archive')
        with path.open('rb') as incoming:
            raw = incoming.read(480)
        if len(raw) != 480:
            raise ValueError('Short segment header area')
        # The supplied snapshot showed one 30-byte, flag=1 record per bucket.
        # Refuse to package any body bytes if this observation does not hold.
        for offset in range(0, 480, 30):
            if struct.unpack_from('<IH', raw, offset+16) != (30, 1):
                raise ValueError(f'Unexpected segment header slot: {path.name}+{offset}; nothing packaged')
        headers[path.name] = dict(bytes=path.stat().st_size, first_480_bytes=raw.hex())
    if not headers:
        raise ValueError('No archive headers')
    for name, raw in selected.items():
        if (folder/Path(name).name).read_bytes() != raw:
            raise ValueError('Metadata changed; close the game and launchers before collecting')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as outgoing:
        with zipfile.ZipFile(outgoing, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in selected.items():
                archive.writestr(name, raw)
            archive.writestr('segment-headers.json', json.dumps(headers, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    audit = commands.add_parser('analyze')
    audit.add_argument('package', type=Path)
    audit.add_argument('--output', type=Path, required=True)
    gather = commands.add_parser('collect')
    gather.add_argument('client', type=Path)
    gather.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'collect':
            print('Metadata package:', collect(args.client, args.output))
        else:
            result = analyze(args.package)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x') as outgoing:
                json.dump(result, outgoing, indent=2)
                outgoing.write('\n')
            print('Observation report:', args.output)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Container metadata audit stopped: {error}\n')
