#!/usr/bin/env python3
"""Compile the adapter and its modified core translation units using real CMake flags."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build', type=Path, required=True)
args = parser.parse_args()
units = ('ForeverAdvancement.cpp', 'Player.cpp', 'DB2Stores.cpp', 'HotfixHandler.cpp', 'ChatHandler.cpp')
commands = json.loads((args.build / 'compile_commands.json').read_text())
failed = []
for unit in units:
    matches = [item for item in commands if Path(item['file']).name == unit]
    if len(matches) != 1:
        raise SystemExit(f'Expected one real compile command for {unit}, found {len(matches)}')
    item = matches[0]
    original = item.get('arguments') or shlex.split(item['command'])
    command = []; skip = False
    for word in original:
        if skip: skip = False; continue
        if word == '-o': skip = True; continue
        if word == '-c': continue
        command.append(word)
    command.append('-fsyntax-only')
    print('Checking pinned 70658 source: ' + unit, flush=True)
    if subprocess.run(command, cwd=item['directory']).returncode:
        failed.append(unit)
if failed:
    raise SystemExit('Compilation failed: ' + ', '.join(failed))
print('Pinned 70658 adapter and all four modified core units compile successfully.')
