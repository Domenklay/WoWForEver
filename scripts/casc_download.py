"""DOWNLOAD v1-v3 reader and explicit v1 byte transform, following pinned CascLib.

Tag bitmaps use MSB-first entry indices and big-endian uint16 types. No tag
semantics or tag assignments for new resources are inferred. These functions
never open a client installation or write files.
"""
import hashlib
import struct


class Download:
    def __init__(self, data):
        if len(data) < 11 or data[:2] != b'DL' or data[2] not in (1, 2, 3):
            raise ValueError('Unsupported DOWNLOAD header')
        self.data = data
        self.version, self.key_bytes, self.checksums = data[2:5]
        self.header_bytes = {1: 11, 2: 12, 3: 16}[self.version]
        if len(data) < self.header_bytes:
            raise ValueError('Truncated DOWNLOAD header')
        if not 1 <= self.key_bytes <= 16 or self.checksums not in (0, 1):
            raise ValueError('Unsupported DOWNLOAD key/checksum profile')
        self.count = struct.unpack_from('>I', data, 5)[0]
        self.tag_count = struct.unpack_from('>H', data, 9)[0]
        self.flag_bytes = data[11] if self.version >= 2 else 0
        self.entry_bytes = self.key_bytes + 6 + self.checksums * 4 + self.flag_bytes
        self.entries_end = self.header_bytes + self.count * self.entry_bytes
        if self.entries_end > len(data):
            raise ValueError('Truncated DOWNLOAD entry table')
        self.bitmap_bytes = (self.count + 7) // 8
        self.tags = []
        pos = self.entries_end
        for index in range(self.tag_count):
            end = data.find(b'\0', pos)
            if end < 0:
                raise ValueError(f'DOWNLOAD tag {index}: unterminated name')
            name = data[pos:end]
            pos = end + 1
            if pos + 2 + self.bitmap_bytes > len(data):
                raise ValueError(f'DOWNLOAD tag {index}: truncated type/bitmap')
            kind = struct.unpack_from('>H', data, pos)[0]
            pos += 2
            bitmap = memoryview(data)[pos:pos+self.bitmap_bytes]
            self.tags.append(dict(name=name.decode('utf-8', errors='backslashreplace'),
                                  name_hex=name.hex(), type=kind, bitmap=bitmap))
            pos += self.bitmap_bytes
        # The existing synthetic lab pads its empty v1 header to CascLib's
        # 16-byte C struct. Unknown nonzero/long trailers are not guessed away.
        self.padding = data[pos:]
        if len(self.padding) > 15 or any(self.padding):
            raise ValueError('Unsupported DOWNLOAD trailing data')

    def tag_indices(self, entry):
        if not 0 <= entry < self.count:
            raise ValueError('DOWNLOAD entry index out of bounds')
        offset, bit = entry // 8, 0x80 >> (entry % 8)
        return [index for index, tag in enumerate(self.tags) if tag['bitmap'][offset] & bit]

    def summary(self):
        tags = []
        remainder = self.count % 8
        for index, tag in enumerate(self.tags):
            bitmap = tag['bitmap']
            unused = int(bitmap[-1]) & ((1 << (8-remainder))-1) if bitmap and remainder else 0
            tags.append(dict(index=index, name=tag['name'], name_hex=tag['name_hex'],
                             type=tag['type'], bitmap_bytes=len(bitmap),
                             bitmap_sha256=hashlib.sha256(bitmap).hexdigest(),
                             member_count=int.from_bytes(bitmap, 'big').bit_count()-unused.bit_count(),
                             unused_bits_value=unused))
        return dict(bytes=len(self.data), md5=hashlib.md5(self.data).hexdigest(),
                    version=self.version, ekey_bytes=self.key_bytes,
                    entry_has_checksum=self.checksums, entry_count=self.count,
                    tag_count=self.tag_count, flag_bytes=self.flag_bytes,
                    tags_parsed=True, tags=tags, padding_bytes=len(self.padding),
                    tag_assignment_policy_verified=False,
                    supported_by_lab_updater=(self.version == 1 and self.key_bytes == 16
                                             and not self.checksums and not self.tag_count))

    def references(self, keys):
        """Describe tag memberships of known config EKeys without dumping rows."""
        wanted = {}
        result = {}
        for name, key in keys.items():
            if len(key) != 16:
                raise ValueError('Expected full reference EKey')
            wanted.setdefault(key[:self.key_bytes], []).append(name)
            result[name] = dict(ekey=key.hex(), match_count=0, matches=[])
        for index, pos in enumerate(range(self.header_bytes, self.entries_end, self.entry_bytes)):
            names = wanted.get(self.data[pos:pos+self.key_bytes])
            if names is None:
                continue
            item = dict(entry_index=index,
                        encoded_bytes=int.from_bytes(self.data[pos+self.key_bytes:pos+self.key_bytes+5], 'big'),
                        raw_priority=self.data[pos+self.key_bytes+5], tag_indices=self.tag_indices(index))
            for name in names:
                result[name]['match_count'] += 1
                if len(result[name]['matches']) < 8:
                    result[name]['matches'].append(item)
        return result


def append_download(data, rows):
    """Append v1 entries with EXPLICIT tag indices; preserve all old memberships.

    Pure byte transform, not a client installer. In particular, an empty tag
    list is an explicit choice, not permission to guess platform/locale tags.
    """
    source = Download(data)
    if (source.version, source.key_bytes, source.checksums, source.flag_bytes) != (1,16,0,0):
        raise ValueError('DOWNLOAD append supports only checksumless full-key v1')
    rows = list(rows)
    if not rows:
        return data
    if source.count + len(rows) > 0xffffffff:
        raise ValueError('DOWNLOAD entry count overflow')
    keys, seen = {}, set()
    for index, row in enumerate(rows):
        key = row['ekey']
        if not isinstance(key, bytes) or len(key) != 16 or key in seen:
            raise ValueError('Invalid/duplicate new DOWNLOAD EKey')
        if type(row['encoded_bytes']) is not int or not 0 < row['encoded_bytes'] < 1 << 40:
            raise ValueError('Invalid DOWNLOAD encoded size')
        if type(row['priority']) is not int or not 0 <= row['priority'] <= 255:
            raise ValueError('Invalid DOWNLOAD priority')
        tags = row.get('tag_indices')
        if (not isinstance(tags, (list, tuple)) or
                any(type(t) is not int or not 0 <= t < source.tag_count for t in tags) or
                len(set(tags)) != len(tags)):
            raise ValueError('Explicit valid DOWNLOAD tag indices required')
        keys[index] = key
        seen.add(key)
    if any(ref['match_count'] for ref in source.references(keys).values()):
        raise ValueError('New DOWNLOAD EKey already exists')
    count = source.count + len(rows)
    header = bytearray(data[:source.header_bytes])
    struct.pack_into('>I', header, 5, count)
    result = bytearray(header)
    result.extend(data[source.header_bytes:source.entries_end])
    for row in rows:
        result.extend(row['ekey']+row['encoded_bytes'].to_bytes(5,'big')+bytes([row['priority']]))
    for tag_index, tag in enumerate(source.tags):
        bitmap = bytearray((count+7)//8)
        bitmap[:source.bitmap_bytes] = tag['bitmap']
        # Native manifests may fill unused bits with ones (the real 70532
        # profile does). They MUST NOT become memberships of appended entries.
        if source.count % 8:
            bitmap[source.bitmap_bytes-1] &= (0xff << (8-source.count%8)) & 0xff
        for offset, row in enumerate(rows, source.count):
            if tag_index in row['tag_indices']:
                bitmap[offset//8] |= 0x80 >> (offset%8)
        result.extend(bytes.fromhex(tag['name_hex'])+b'\0'+tag['type'].to_bytes(2,'big')+bitmap)
    result.extend(source.padding)
    updated = bytes(result)
    Download(updated)  # Verify the complete new layout before returning bytes.
    return updated
