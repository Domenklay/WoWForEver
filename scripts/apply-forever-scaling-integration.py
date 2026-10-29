#!/usr/bin/env python3
"""Apply minimal Forever Scaling wiring to the current local server checkout.

The local WoWForEver checkout can contain uncommitted integrations from other
modules.  Therefore this patcher deliberately uses stable build/service
boundaries instead of depending on the exact subclass-adapter lines.
"""
from pathlib import Path
import re


SCALING_BUILD_BLOCK = '''# Forever Scaling uses the pinned core's per-target creature stat path and a UnitScript damage guard.
# It is compiled into the image but disabled at runtime until FOREVER_SCALING_ENABLED=1.
COPY mod-forever-scaling /forever-scaling-module
COPY scripts/inject-forever-scaling.py /tmp/inject-forever-scaling.py
RUN python3 /tmp/inject-forever-scaling.py /src/TrinityCore --module /forever-scaling-module

'''

SCALING_ENV_LINES = '''      FOREVER_SCALING_ENABLED: ${FOREVER_SCALING_ENABLED:-0}
      FOREVER_SCALING_DAMAGE_GUARD: ${FOREVER_SCALING_DAMAGE_GUARD:-1}
      FOREVER_SCALING_MIN_OFFSET: ${FOREVER_SCALING_MIN_OFFSET:--9}
      FOREVER_SCALING_MAX_OFFSET: ${FOREVER_SCALING_MAX_OFFSET:-10}
      FOREVER_SCALING_CREATURE_MAX_LEVEL: ${FOREVER_SCALING_CREATURE_MAX_LEVEL:-70}
      FOREVER_SCALING_NORMAL_OFFSET: ${FOREVER_SCALING_NORMAL_OFFSET:-0}
      FOREVER_SCALING_ELITE_OFFSET: ${FOREVER_SCALING_ELITE_OFFSET:-5}
      FOREVER_SCALING_RARE_ELITE_OFFSET: ${FOREVER_SCALING_RARE_ELITE_OFFSET:-7}
      FOREVER_SCALING_BOSS_OFFSET: ${FOREVER_SCALING_BOSS_OFFSET:-8}
      FOREVER_SCALING_CAP_NORMAL: ${FOREVER_SCALING_CAP_NORMAL:-20}
      FOREVER_SCALING_CAP_ELITE: ${FOREVER_SCALING_CAP_ELITE:-30}
      FOREVER_SCALING_CAP_RARE_ELITE: ${FOREVER_SCALING_CAP_RARE_ELITE:-40}
      FOREVER_SCALING_CAP_BOSS: ${FOREVER_SCALING_CAP_BOSS:-45}
'''


def exactly_once(text, needle, description):
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f'{description}: expected one anchor, found {count}')
    return text.index(needle)


def patch_dockerfile():
    path = Path('Dockerfile')
    text = path.read_text()

    # Put the source integration after all existing core injectors/patches but
    # before CMake starts.  This survives local changes to subclass/encyclopedia
    # integrations as long as the build stage keeps its BUILD_JOBS boundary.
    if 'scripts/inject-forever-scaling.py' not in text:
        marker = '# BUILD_JOBS:'
        pos = exactly_once(text, marker, 'Dockerfile build-stage boundary')
        text = text[:pos] + SCALING_BUILD_BLOCK + text[pos:]

    # A standalone runtime label is safer than rewriting another module's LABEL.
    if 'org.wowforever.scaling=' not in text:
        runtime_marker = '############################ runtime ############################\n'
        start = exactly_once(text, runtime_marker, 'Dockerfile runtime boundary') + len(runtime_marker)
        m = re.match(r'FROM[^\n]*\n', text[start:])
        if not m:
            raise SystemExit('Dockerfile runtime boundary: FROM line not found after runtime marker')
        insert = start + m.end()
        text = text[:insert] + 'LABEL org.wowforever.scaling="0.1.0"\n' + text[insert:]

    path.write_text(text)


def patch_compose():
    path = Path('docker-compose.yml')
    text = path.read_text()
    if 'FOREVER_SCALING_ENABLED:' in text:
        return

    # Restrict all edits to the worldserver service.  Do not depend on the
    # presence or exact wording of subclass environment variables.
    world_start = exactly_once(text, '  worldserver:\n', 'docker-compose worldserver service')
    next_service = text.find('\n  bnetserver:', world_start)
    if next_service < 0:
        raise SystemExit('docker-compose worldserver service: bnetserver boundary not found')

    block = text[world_start:next_service]
    env_rel = block.find('    environment:\n')
    if env_rel < 0:
        raise SystemExit('docker-compose worldserver service: environment block not found')

    # Find the next service-level key (four-space indentation) after environment.
    env_content_start = env_rel + len('    environment:\n')
    boundary = re.search(r'^    [A-Za-z_][A-Za-z0-9_-]*:', block[env_content_start:], re.M)
    if not boundary:
        raise SystemExit('docker-compose worldserver service: environment block end not found')
    insert_rel = env_content_start + boundary.start()

    block = block[:insert_rel] + SCALING_ENV_LINES + block[insert_rel:]
    text = text[:world_start] + block + text[next_service:]
    path.write_text(text)


def verify():
    docker = Path('Dockerfile').read_text()
    compose = Path('docker-compose.yml').read_text()
    required = {
        'Dockerfile injector COPY': 'COPY scripts/inject-forever-scaling.py /tmp/inject-forever-scaling.py',
        'Dockerfile injector RUN': 'RUN python3 /tmp/inject-forever-scaling.py /src/TrinityCore --module /forever-scaling-module',
        'Dockerfile scaling label': 'org.wowforever.scaling="0.1.0"',
        'Compose runtime enable': 'FOREVER_SCALING_ENABLED:',
        'Compose damage guard': 'FOREVER_SCALING_DAMAGE_GUARD:',
    }
    for name, needle in required.items():
        haystack = docker if name.startswith('Dockerfile') else compose
        if needle not in haystack:
            raise SystemExit(f'ForeverScaling integration verification failed: {name}')


if __name__ == '__main__':
    patch_dockerfile()
    patch_compose()
    verify()
    print('ForeverScaling Docker integration applied and verified')
