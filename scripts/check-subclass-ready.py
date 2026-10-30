#!/usr/bin/env python3
"""Check current-container startup logs without exposing their contents."""

import argparse
import re
import sys


def assess(logs: str, mode: str) -> tuple[int, str]:
    if mode not in ('legacy', 'freepick'):
        raise ValueError('unsupported subclass mode')
    module_ready = 'ForeverSubclass ready:' in logs
    world_ready = re.search(r'\(worldserver-daemon\)\s+ready\b', logs) is not None
    if not module_ready or not world_ready:
        return 1, 'Waiting for worldserver and subclass catalogue.'
    freepick = 'Freepick ability prototype enabled' in logs
    if mode == 'freepick' and not freepick:
        return 2, 'Freepick mode was overridden or did not start.'
    if mode == 'legacy' and freepick:
        return 2, 'Legacy mode was overridden by Freepick.'
    if freepick:
        shield = re.findall(r'Freepick custom Mana Shield: (available|unavailable)\b', logs)
        if not shield:
            return 2, 'Custom Mana Shield readiness was not reported; check the server image and script bindings.'
        if shield[-1] != 'available':
            return 2, 'Custom Mana Shield is unavailable; check native spell data and both script bindings.'
        return 0, 'Freepick and custom Mana Shield are ready.'
    return 0, 'Legacy subclass runtime is ready.'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('legacy', 'freepick'))
    args = parser.parse_args()
    code, message = assess(sys.stdin.read(), args.mode)
    print(message)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
