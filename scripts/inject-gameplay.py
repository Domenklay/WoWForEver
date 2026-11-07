#!/usr/bin/env python3
"""Compose the existing Ascension, encyclopedia and optional scaling adapters."""
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def inject(core, scaling=True):
    core = Path(core)
    advancement = read_module('gameplay_advancement', ROOT / 'scripts/inject-advancement.py')
    advancement.inject(core, ROOT / 'mods/forever-advancement')
    encyclopedia = read_module('gameplay_encyclopedia', ROOT / 'mods/living-encyclopedia/server/inject.py')
    encyclopedia.inject(core, ROOT / 'mods/living-encyclopedia')
    if scaling:
        adapter = read_module('gameplay_scaling', ROOT / 'scripts/inject-forever-scaling.py')
        adapter.inject(core, ROOT / 'mod-forever-scaling')
        dungeon = read_module('gameplay_dungeon', ROOT / 'scripts/inject-forever-dungeons.py')
        dungeon.inject(core, ROOT / 'mod-forever-scaling')
    finder = read_module('gameplay_finder', ROOT / 'scripts/inject-forever-dungeon-finder.py')
    finder.inject(core, ROOT / 'mods/forever-dungeon-finder')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--without-scaling', action='store_true')
    args = parser.parse_args()
    inject(args.core, not args.without_scaling)
