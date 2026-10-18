#!/usr/bin/env python3
"""Prints packets of a TrinityCore PKT 3.1 log (worldserver PacketLogFile), as hex + text.

Usage: pkt-dump.py World.pkt [OPCODE_HEX ...]
  without opcodes: client packets of ADD_FRIEND, PARTY_INVITE, CHAT_MESSAGE_WHISPER and their server answers
  e.g. pkt-dump.py World.pkt 430100 430030
Opcodes are the server's internal values (Opcodes.h), not the classic client ones.
"""
import struct
import sys

NAMES = {
    0x430100: 'CMSG_ADD_FRIEND',
    0x430030: 'CMSG_PARTY_INVITE',
}


def hexdump(data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = ' '.join(f'{b:02x}' for b in chunk)
        text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'  {i:04x}  {hexpart:<47}  {text}')
    return '\n'.join(lines)


def packets(path):
    with open(path, 'rb') as f:
        head = f.read(3 + 2 + 1 + 4 + 4 + 40 + 4 + 4 + 4)
        if head[:3] != b'PKT':
            sys.exit('not a PKT file')
        build = struct.unpack_from('<I', head, 6)[0]
        optional = struct.unpack_from('<I', head, 62)[0]
        f.read(optional)
        print(f'# build {build}')
        while True:
            h = f.read(20)
            if len(h) < 20:
                return
            direction, conn, ticks, optsize, length = struct.unpack('<5I', h)
            f.read(optsize)
            opcode = struct.unpack('<I', f.read(4))[0]
            data = f.read(length - 4)
            yield ('C>S' if direction == 0x47534d43 else 'S>C'), ticks, opcode, data


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    wanted = {int(o, 16) for o in sys.argv[2:]} or set(NAMES)
    show_answers = len(sys.argv) == 2
    pending = 0
    for direction, ticks, opcode, data in packets(sys.argv[1]):
        if direction == 'C>S' and opcode in wanted:
            print(f'\n{direction} t={ticks} {NAMES.get(opcode, hex(opcode))} ({len(data)} bytes)\n{hexdump(data)}')
            pending = 3 if show_answers else 0
        elif direction == 'S>C' and pending:
            pending -= 1
            print(f'  answer S>C opcode {opcode:#x} ({len(data)} bytes)\n{hexdump(data[:64])}')


if __name__ == '__main__':
    main()
