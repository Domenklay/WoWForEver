#!/usr/bin/env python3
"""Apply the minimal Forever Scaling wiring to the current local server checkout."""
from pathlib import Path


def replace_once(text, old, new, description):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{description}: expected one anchor, found {count}')
    return text.replace(old, new, 1)


def patch_dockerfile():
    path = Path('Dockerfile')
    text = path.read_text()

    if 'scripts/inject-forever-scaling.py' not in text:
        anchor = 'RUN python3 /tmp/inject-subclass.py /src/TrinityCore --module /subclass-module\n'
        block = anchor + '''\n# Forever Scaling uses the pinned core's per-target creature stat path and a UnitScript damage guard.\n# It is compiled into the image but disabled at runtime until FOREVER_SCALING_ENABLED=1.\nCOPY mod-forever-scaling /forever-scaling-module\nCOPY scripts/inject-forever-scaling.py /tmp/inject-forever-scaling.py\nRUN python3 /tmp/inject-forever-scaling.py /src/TrinityCore --module /forever-scaling-module\n'''
        text = replace_once(text, anchor, block, 'Dockerfile subclass injection anchor')

    if 'org.wowforever.scaling=' not in text:
        anchor = 'LABEL org.wowforever.subclass="0.4.0-freepick.1"\n'
        replacement = 'LABEL org.wowforever.subclass="0.4.0-freepick.1" \\\n      org.wowforever.scaling="0.1.0"\n'
        text = replace_once(text, anchor, replacement, 'Dockerfile runtime label anchor')

    path.write_text(text)


def patch_compose():
    path = Path('docker-compose.yml')
    text = path.read_text()
    if 'FOREVER_SCALING_ENABLED:' in text:
        return

    anchor = '      SUBCLASS_FREEPICK: ${SUBCLASS_FREEPICK:-0}\n'
    block = anchor + '''      FOREVER_SCALING_ENABLED: ${FOREVER_SCALING_ENABLED:-0}\n      FOREVER_SCALING_DAMAGE_GUARD: ${FOREVER_SCALING_DAMAGE_GUARD:-1}\n      FOREVER_SCALING_MIN_OFFSET: ${FOREVER_SCALING_MIN_OFFSET:--9}\n      FOREVER_SCALING_MAX_OFFSET: ${FOREVER_SCALING_MAX_OFFSET:-10}\n      FOREVER_SCALING_CREATURE_MAX_LEVEL: ${FOREVER_SCALING_CREATURE_MAX_LEVEL:-70}\n      FOREVER_SCALING_NORMAL_OFFSET: ${FOREVER_SCALING_NORMAL_OFFSET:-0}\n      FOREVER_SCALING_ELITE_OFFSET: ${FOREVER_SCALING_ELITE_OFFSET:-5}\n      FOREVER_SCALING_RARE_ELITE_OFFSET: ${FOREVER_SCALING_RARE_ELITE_OFFSET:-7}\n      FOREVER_SCALING_BOSS_OFFSET: ${FOREVER_SCALING_BOSS_OFFSET:-8}\n      FOREVER_SCALING_CAP_NORMAL: ${FOREVER_SCALING_CAP_NORMAL:-20}\n      FOREVER_SCALING_CAP_ELITE: ${FOREVER_SCALING_CAP_ELITE:-30}\n      FOREVER_SCALING_CAP_RARE_ELITE: ${FOREVER_SCALING_CAP_RARE_ELITE:-40}\n      FOREVER_SCALING_CAP_BOSS: ${FOREVER_SCALING_CAP_BOSS:-45}\n'''
    text = replace_once(text, anchor, block, 'docker-compose subclass environment anchor')
    path.write_text(text)


if __name__ == '__main__':
    patch_dockerfile()
    patch_compose()
    print('ForeverScaling Docker integration applied')
