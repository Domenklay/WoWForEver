#!/usr/bin/env python3
"""Inject Forever Dungeon Finder into the pinned TrinityCore Forever tree."""
import argparse
import shutil
from pathlib import Path


def patch_loader(core: Path, module: Path) -> None:
    loader = core / 'src/server/scripts/Custom/custom_script_loader.cpp'
    text = loader.read_text()

    declaration = 'void AddSC_forever_dungeon_finder();'
    call = '    AddSC_forever_dungeon_finder();'

    if declaration not in text:
        marker = 'void AddCustomScripts()'
        if text.count(marker) != 1:
            raise ValueError('Custom script loader layout is not recognized')
        text = text.replace(marker, declaration + '\n\n' + marker, 1)
    elif text.count(declaration) != 1:
        raise ValueError('Duplicate ForeverDungeonFinder declaration in custom loader')

    if call not in text:
        marker = 'void AddCustomScripts()\n{\n'
        if text.count(marker) != 1:
            raise ValueError('Cannot locate AddCustomScripts body')
        text = text.replace(marker, marker + call + '\n', 1)
    elif text.count(call) != 1:
        raise ValueError('Duplicate ForeverDungeonFinder registration in custom loader')

    target = loader.parent / 'ForeverDungeonFinder'
    target.mkdir(exist_ok=True)
    shutil.copy2(module / 'server/ForeverDungeonFinder.cpp', target / 'ForeverDungeonFinder.cpp')
    loader.write_text(text)


def inject(core: Path, module: Path) -> None:
    core = core.resolve()
    module = module.resolve()
    source = module / 'server/ForeverDungeonFinder.cpp'
    if not source.is_file():
        raise SystemExit(f'Module source not found: {source}')
    patch_loader(core, module)
    print('ForeverDungeonFinder core integration applied')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--module', type=Path, required=True)
    args = parser.parse_args()
    inject(args.core, args.module)
