#!/usr/bin/env python3
"""Temporarily enable subclass startup logging without rebuilding the image."""
import argparse
import json
import re
from pathlib import Path

KEY = re.compile(r'^\s*Logger\.scripts\s*=')


def enable(path, backup):
    path, backup = Path(path).resolve(), Path(backup)
    report = backup/'log-config.json'
    if report.exists():
        raise FileExistsError(report)
    text = path.read_text() if path.exists() else ''
    lines = text.splitlines(keepends=True)
    backup.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'path':str(path), 'existed':path.exists(),
                                 'previous_lines':[line for line in lines if KEY.match(line)]}, indent=2)+'\n')
    kept = ''.join(line for line in lines if not KEY.match(line))
    if kept and not kept.endswith('\n'):
        kept += '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kept+'Logger.scripts = 3,Console Server\n')


def restore(backup):
    report = Path(backup)/'log-config.json'
    if not report.exists():
        return
    saved = json.loads(report.read_text())
    path = Path(saved['path'])
    text = path.read_text() if path.exists() else ''
    kept = ''.join(line for line in text.splitlines(keepends=True) if not KEY.match(line))
    previous = ''.join(saved['previous_lines'])
    if kept and previous and not kept.endswith('\n'):
        kept += '\n'
    result = kept+previous
    if not saved['existed'] and not result.strip():
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--path', type=Path, default=Path('overrides/worldserver.conf'))
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if args.restore:
        restore(args.backup)
    else:
        enable(args.path, args.backup)
