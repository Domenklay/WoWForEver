"""Offline Map.db2 WDC5 adapter; preserves opaque sections and old records.

Adds an unencrypted record section after the first clear section, plus a
string-only section last. Adjusts early clear string pointers and preserves
all opaque section bytes. Keeps ID zero at record zero for the core ID repair.
Actual game acceptance of the new section arrangement still requires testing.
"""
import struct

HEADER = 204
LAYOUT = 0xD43AFAC3


class MapTable:
    def __init__(self, data):
        self.data = data
        if len(data) < HEADER or data[:8] != b'WDC5\x05\0\0\0':
            raise ValueError('Expected WDC5 version 5')
        h = struct.unpack_from('<9IHh7I', data, 136)
        (self.count, self.fields, self.record_size, self.string_size, self.table_hash, self.layout,
         self.min_id, self.max_id, self.locale, flags, index, total, self.packed_offset,
         parents, columns_size, common_size, pallet_size, sections) = h
        if (self.layout != LAYOUT or self.fields != 26 or total != 26 or flags != 4 or index != 0 or
                parents or common_size or columns_size != 26*24 or not 1 <= sections <= 32 or
                not 32 <= self.record_size <= 512):
            raise ValueError('Unsupported Map.db2 schema/section layout')
        # Header IndexField is ignored with the external-ID flag (0x4).
        self.section_count = sections
        self.section_headers = [list(struct.unpack_from('<Q8I', data, HEADER+40*i)) for i in range(sections)]
        self.field_start = HEADER+40*sections
        self.column_start = self.field_start+26*4
        self.columns = [list(struct.unpack_from('<HH5I', data, self.column_start+24*i)) for i in range(26)]
        for bit, width, extra, kind, pbit, pwidth, array in self.columns:
            if (kind not in {0,1,3,4,5} or
                    (kind == 0 and (not 0 < width <= 128 or bit+width > self.record_size*8)) or
                    (kind != 0 and (not 0 < pwidth <= 32 or self.packed_offset*8+pbit+pwidth > self.record_size*8))):
                raise ValueError('Unsupported Map field bit range')
        self.palette_start = self.column_start+columns_size
        offset = self.palette_start
        self.palettes = {}
        for kind in (3, 4):
            for i, col in enumerate(self.columns):
                if col[3] == kind:
                    if col[2] % 4 or offset+col[2] > len(data):
                        raise ValueError('Invalid palette size')
                    self.palettes[i] = (offset, list(struct.unpack_from('<'+'I'*(col[2]//4), data, offset)))
                    offset += col[2]
        if offset != self.palette_start+pallet_size:
            raise ValueError('Palette size/header mismatch')
        for field in range(6):
            if self.columns[field][:4] != [field*32, 32, 0, 0]:
                raise ValueError('Unsupported Map string column')
        self.reserved = set()
        for section in self.section_headers:
            if section[0]:
                n = struct.unpack_from('<I', data, offset)[0]
                offset += 4
                if n > self.count or offset+n*4 > len(data):
                    raise ValueError('Invalid opaque section ID list')
                self.reserved.update(struct.unpack_from('<'+'I'*n, data, offset))
                offset += n*4
        self.body_start = offset
        self.records = []
        self.strings = bytearray()
        virtual = 0
        for section in self.section_headers:
            tact, start, count, strings, catalog, ids_size, parent, sparse_count, copies = section
            if catalog or parent or sparse_count or copies or ids_size != count*4 or start != offset:
                raise ValueError('Unsupported or noncontiguous section body')
            end = start+count*self.record_size+strings+ids_size
            if end > len(data):
                raise ValueError('Truncated section body')
            ids = struct.unpack_from('<'+'I'*count, data, start+count*self.record_size+strings)
            self.strings.extend(data[start+count*self.record_size:start+count*self.record_size+strings])
            if not tact:
                for i, fid in enumerate(ids):
                    if fid in self.reserved:
                        raise ValueError('Duplicate or opaque-reserved map ID')
                    self.reserved.add(fid)
                    row = data[start+i*self.record_size:start+(i+1)*self.record_size]
                    self.records.append((fid, virtual+i*self.record_size, row))
            virtual += count*self.record_size
            offset = end
        if (offset != len(data) or virtual != self.count*self.record_size or
                len(self.strings) != self.string_size):
            raise ValueError('Map section/header size mismatch')
        self.semantic = {fid: self.decode_row(pos, row) for fid, pos, row in self.records}

    def decode_row(self, position, row):
        result = []
        word = int.from_bytes(row, 'little')
        for i, col in enumerate(self.columns):
            bit, width, extra, kind, packed_bit, packed_width, array = col
            if kind == 0:
                value = (word >> bit) & ((1 << width)-1)
            elif kind in {1, 5, 3, 4}:
                value = (word >> (self.packed_offset*8+packed_bit)) & ((1 << packed_width)-1)
                if kind in {3, 4}:
                    values = self.palettes[i][1]
                    start = value*(array if kind == 4 else 1)
                    count = array if kind == 4 else 1
                    if start+count > len(values):
                        raise ValueError('Palette index out of bounds')
                    value = tuple(values[start:start+count]) if kind == 4 else values[start]
                elif kind == 5 and value & (1 << (packed_width-1)):
                    value -= 1 << packed_width
            else:
                raise ValueError('Unsupported Map column compression')
            if i < 6:
                if value:
                    start = position+bit//8+value-self.count*self.record_size
                    if not 0 <= start < len(self.strings):
                        raise ValueError('String pointer leaves virtual string pool')
                    end = self.strings.find(0, start)
                    if end < 0:
                        raise ValueError('Unterminated map string')
                    value = bytes(self.strings[start:end]).decode('utf-8')
                else:
                    value = ''
            result.append(value)
        return tuple(result)


def add_map(data, map_id, wdt_id, directory='ForeverDalaran', name='Dalaran (Legion test)', template_id=0):
    if not isinstance(map_id, int) or isinstance(map_id, bool) or not 0 < map_id <= 0xffffffff:
        raise ValueError('Invalid Map ID')
    if not isinstance(wdt_id, int) or isinstance(wdt_id, bool) or not 0x00f00000 <= wdt_id < 0x00ffff00:
        raise ValueError('Expected a private WDT FileDataID')
    if not directory or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in directory):
        raise ValueError('Directory must be a simple unique identifier')
    if not name or '\0' in name or len(name.encode('utf-8')) > 256:
        raise ValueError('Invalid map name')
    source = MapTable(data)
    if map_id in source.reserved:
        raise ValueError('Map ID already reserved, including opaque sections')
    if any(row[0].lower() == directory.lower() for row in source.semantic.values()):
        raise ValueError('Map directory already exists')
    template = next((row for fid, _, row in source.records if fid == template_id), None)
    if template is None:
        raise ValueError('Expected a readable template map')
    col = source.columns[21]
    if col[3] != 3 or not 0 < col[5] < 32:
        raise ValueError('WdtFileDataID must use a supported scalar palette')
    start, palette = source.palettes[21]
    if wdt_id in palette:
        raise ValueError('Private WDT ID already occurs in Map palette')
    if len(palette) >= 1 << col[5]:
        raise ValueError('WDT palette is full; packed fields must not be widened implicitly')
    if source.section_headers[0][0] or not source.section_headers[0][2] or source.records[0][0] != 0:
        raise ValueError('Expected an initial clear section; map zero must remain first')
    if source.section_count > 30:
        raise ValueError('No room for two prototype sections')
    strings = b'\0'+directory.encode('ascii')+b'\0'+name.encode('utf-8')+b'\0'
    record = bytearray(template)
    offsets = [1, len(directory)+2, 0, 0, 0, 0]
    base = (source.count+1-source.section_headers[0][2])*source.record_size+source.string_size
    for field, string_offset in enumerate(offsets):
        struct.pack_into('<I', record, field*4, base+string_offset-field*4)
    bit = source.packed_offset*8+col[4]
    word = int.from_bytes(record, 'little')
    mask = ((1 << col[5])-1) << bit
    word = (word & ~mask) | (len(palette) << bit)
    zmp = source.columns[20]
    if zmp[3] != 3 or 0 not in source.palettes[20][1]:
        raise ValueError('Cannot clear the template map ZMP reference')
    zbit = source.packed_offset*8+zmp[4]
    zmask = ((1 << zmp[5])-1) << zbit
    word = (word & ~zmask) | (source.palettes[20][1].index(0) << zbit)
    record = word.to_bytes(source.record_size, 'little')
    header = bytearray(data[:HEADER])
    struct.pack_into('<I', header, 136, source.count+1)
    struct.pack_into('<I', header, 148, source.string_size+len(strings))
    struct.pack_into('<II', header, 160, min(source.min_id, map_id), max(source.max_id, map_id))
    struct.pack_into('<I', header, 196, struct.unpack_from('<I', header, 196)[0]+4)
    struct.pack_into('<I', header, 200, source.section_count+2)
    columns = bytearray(data[source.column_start:source.palette_start])
    struct.pack_into('<I', columns, 21*24+4, col[2]+4)
    insertion = start+col[2]
    palettes = data[source.palette_start:insertion]+struct.pack('<I', wdt_id)+data[insertion:source.body_start]
    prefix_size = source.body_start+80+4
    section_headers = []
    bodies = bytearray()
    old_bodies = []
    for index, old in enumerate(source.section_headers):
        size = old[2]*source.record_size+old[3]+old[5]
        body = bytearray(data[old[1]:old[1]+size])
        if index == 0:
            for row in range(old[2]):
                for field in range(6):
                    offset = row*source.record_size+field*4
                    value = struct.unpack_from('<I', body, offset)[0]
                    if value:
                        struct.pack_into('<I', body, offset, value+source.record_size)
        changed = old[:]
        changed[1] = prefix_size+len(bodies)
        section_headers.append(changed)
        old_bodies.append(bytes(body))
        bodies.extend(body)
        if index == 0:
            section_headers.append([0,prefix_size+len(bodies),1,0,0,4,0,0,0])
            bodies.extend(record+struct.pack('<I', map_id))
    section_headers.append([0,prefix_size+len(bodies),0,len(strings),0,0,0,0,0])
    result = (bytes(header)+b''.join(struct.pack('<Q8I', *s) for s in section_headers)+
              data[source.field_start:source.column_start]+bytes(columns)+palettes+bytes(bodies)+strings)
    checked = MapTable(result)
    if any(checked.semantic.get(fid) != values for fid, values in source.semantic.items()):
        raise ValueError('Existing map semantics changed')
    old_headers = [checked.section_headers[0]]+checked.section_headers[2:-1]
    for expected, new in zip(old_bodies, old_headers):
        if expected != result[new[1]:new[1]+len(expected)]:
            raise ValueError('Old section bytes changed outside adjusted clear string pointers')
    if checked.semantic[map_id][0:2] != (directory, name) or checked.semantic[map_id][21] != wdt_id:
        raise ValueError('New map record failed semantic round-trip')
    return result
