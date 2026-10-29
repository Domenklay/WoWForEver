#!/usr/bin/env python3
"""Read selected spell tables from MPQ archives; never alter the client."""
import argparse
import ctypes as C
import ctypes.util
import hashlib
import json
import io
import shutil
import tempfile
from pathlib import Path
import sys
import zipfile

TABLES = ('Spell', 'SpellDuration', 'SpellCastTimes', 'SpellRange', 'SpellRadius',
          'SpellIcon', 'SpellCategory', 'SpellFocusObject', 'SpellItemEnchantment',
          'SpellShapeshiftForm', 'SpellDifficulty', 'SpellRuneCost', 'SpellVisual',
          'SpellVisualKit', 'Talent', 'TalentTab', 'SkillLine', 'SkillLineAbility',
          'CharacterAdvancement', 'CharacterAdvancementClassTypes', 'CharacterAdvancementEssence')
MAX_SIZE = 128 * 1024 * 1024


class Storm:
    def __init__(self, max_size=MAX_SIZE):
        self.max_size = max_size
        library = ctypes.util.find_library('storm')
        if not library:
            raise RuntimeError('StormLib not found. Ubuntu/WSL: sudo apt-get install libstorm9')
        self.lib = C.CDLL(library)
        signatures = {
            'SFileOpenArchive': ([C.c_char_p, C.c_uint32, C.c_uint32, C.POINTER(C.c_void_p)], C.c_bool),
            'SFileOpenFileEx': ([C.c_void_p, C.c_char_p, C.c_uint32, C.POINTER(C.c_void_p)], C.c_bool),
            'SFileGetFileSize': ([C.c_void_p, C.POINTER(C.c_uint32)], C.c_uint32),
            'SFileReadFile': ([C.c_void_p, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_void_p], C.c_bool),
            'SFileCloseFile': ([C.c_void_p], C.c_bool),
            'SFileCloseArchive': ([C.c_void_p], C.c_bool),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.lib, name); fn.argtypes = args; fn.restype = result

    def open(self, path):
        handle = C.c_void_p()
        # MPQ_OPEN_READ_ONLY. Opening an archive never changes it.
        if not self.lib.SFileOpenArchive(str(path).encode(), 0, 0x100, C.byref(handle)):
            raise RuntimeError('cannot open MPQ (unsupported, encrypted, or damaged archive)')
        return handle

    def close(self, handle):
        self.lib.SFileCloseArchive(handle)

    def read(self, archive, member):
        handle = C.c_void_p()
        if not self.lib.SFileOpenFileEx(archive, member.encode('ascii'), 0, C.byref(handle)):
            return None
        try:
            high = C.c_uint32()
            size = self.lib.SFileGetFileSize(handle, C.byref(high))
            if high.value or size == 0xFFFFFFFF or size > self.max_size:
                raise RuntimeError(f'table size {size} bytes exceeds limit {self.max_size} bytes')
            staged = tempfile.TemporaryFile()
            try:
                data = C.create_string_buffer(1024 * 1024)
                remaining = size
                while remaining:
                    count = min(remaining, len(data)); got = C.c_uint32()
                    if not self.lib.SFileReadFile(handle, data, count, C.byref(got), None) or got.value != count:
                        raise RuntimeError('table read failed (may require a base archive for a delta patch)')
                    staged.write(data.raw[:count]); remaining -= count
                staged.seek(0)
                return staged
            except BaseException:
                staged.close()
                raise
        finally:
            self.lib.SFileCloseFile(handle)


def extract(data_dir, output, reader, archive_name=None, tables=TABLES):
    data_dir = Path(data_dir).resolve(); output = Path(output).resolve()
    if not data_dir.is_dir():
        raise ValueError('Client Data folder does not exist')
    if output == data_dir or data_dir in output.parents:
        raise ValueError('Output must be outside the client Data folder')
    archives = sorted(p for p in data_dir.rglob('*') if p.is_file() and p.suffix.lower() == '.mpq')
    if archive_name:
        archives = [p for p in archives if p.name.casefold() == archive_name.casefold()]
    if any(name not in TABLES for name in tables):
        raise ValueError('Unknown table name')
    if not archives:
        raise ValueError('No MPQ archives found')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'format': 1, 'archives': [], 'tables': [], 'errors': [],
              'note': 'All distinct versions retained; archive precedence is not inferred. Delta patches are not composed.'}
    stored = set()
    # Exclusive creation protects previous exports and never overwrites them.
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in archives:
            relative = str(path.relative_to(data_dir)); handle = None
            report['archives'].append(relative)
            try:
                handle = reader.open(path)
                for name in tables:
                    member = 'DBFilesClient\\' + name + '.dbc'
                    try:
                        raw = reader.read(handle, member)
                        if raw is None:
                            continue
                        with io.BytesIO(raw) if isinstance(raw, bytes) else raw as content:
                            header = content.read(20)
                            if len(header) < 20 or header[:4] not in (b'WDBC', b'WDB2', b'WDB5', b'WDB6'):
                                raise RuntimeError('not a complete DBC/DB2 record (possibly a delta patch)')
                            content.seek(0); checksum = hashlib.sha256(); size = 0
                            while chunk := content.read(1024 * 1024):
                                checksum.update(chunk); size += len(chunk)
                            digest = checksum.hexdigest()
                            target = 'versions/' + digest + '/' + name + '.dbc'
                            if target not in stored:
                                content.seek(0)
                                with bundle.open(target, 'w', force_zip64=True) as destination:
                                    shutil.copyfileobj(content, destination, 1024 * 1024)
                                stored.add(target)
                            report['tables'].append({'archive': relative, 'member': member,
                                                     'file': target, 'sha256': digest, 'bytes': size})
                    except RuntimeError as exc:
                        report['errors'].append({'archive': relative, 'member': member, 'error': str(exc)})
            except RuntimeError as exc:
                report['errors'].append({'archive': relative, 'error': str(exc)})
            finally:
                if handle is not None:
                    reader.close(handle)
        bundle.writestr('manifest.json', json.dumps(report, ensure_ascii=False, indent=2))
    return report


def split_export(path, limit):
    path = Path(path)
    if path.stat().st_size <= limit:
        return []
    parts = []
    with path.open('rb') as source:
        index = 1
        while chunk := source.read(limit):
            part = path.with_name(path.name + f'.part{index:03d}')
            with part.open('xb') as destination:
                destination.write(chunk)
            parts.append(part); index += 1
    return parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--archive', help='Read only this MPQ filename (case insensitive)')
    parser.add_argument('--only', nargs='+', choices=TABLES, default=TABLES)
    parser.add_argument('--max-table-mib', type=int, default=128)
    parser.add_argument('--split-mib', type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.max_table_mib <= 2048 or not 1 <= args.split_mib <= 128:
        parser.error('Invalid table limit (1..2048 MiB) or part size (1..128 MiB)')
    try:
        report = extract(args.data, args.output, Storm(args.max_table_mib * 1024 * 1024), args.archive, args.only)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    spells = {r['sha256'] for r in report['tables'] if r['member'].endswith('\\Spell.dbc')}
    print(f'Archives: {len(report["archives"])}; tables: {len(report["tables"])}; distinct Spell.dbc: {len(spells)}; errors: {len(report["errors"])}')
    print('Export:', args.output.resolve())
    if not spells:
        print('No complete Spell.dbc found. Send manifest.json for diagnosis; export is incomplete.', file=sys.stderr)
        return 2
    parts = split_export(args.output, args.split_mib * 1024 * 1024)
    if parts:
        print('Upload these parts instead of the full ZIP:')
        for part in parts:
            print(part.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
