"""Read-only DOWNLOAD v1-v3 layout reader, following the pinned CascLib.

Tag bitmaps use MSB-first entry indices and big-endian uint16 types. No tag
semantics or tag assignments for new resources are inferred by this reader.
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
