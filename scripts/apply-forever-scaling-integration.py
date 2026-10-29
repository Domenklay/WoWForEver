#!/usr/bin/env python3
"""Apply minimal Forever Scaling wiring to the current local server checkout.

The local WoWForEver checkout can contain uncommitted integrations from other
modules. Therefore this patcher deliberately uses stable build/service
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

    if 'scripts/inject-forever-scaling.py' not in text:
        marker = '# BUILD_JOBS:'
        pos = exactly_once(text, marker, 'Dockerfile build-stage boundary')
        text = text[:pos] + SCALING_BUILD_BLOCK + text[pos:]

    if 'org.wowforever.scaling=' not in text:
        runtime_marker = '############################ runtime ############################\n'
        start = exactly_once(text, runtime_marker, 'Dockerfile runtime boundary') + len(runtime_marker)
        m = re.match(r'FROM[^\n]*\n', text[start:])
        if not m:
            raise SystemExit('Dockerfile runtime boundary: FROM line not found after runtime marker')
        insert = start + m.end()
        text = text[:insert] + 'LABEL org.wowforever.scaling="0.1.0"\n' + text[insert:]

    path.write_text(text)


def service_spans(text):
    """Return 2-space-indented Compose service blocks without parsing/reformatting YAML."""
    starts = list(re.finditer(r'(?m)^  ([A-Za-z0-9_.-]+):\s*$', text))
    for i, match in enumerate(starts):
        start = match.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        yield match.group(1), start, end, text[start:end]


def find_worldserver_service(text):
    candidates = []
    for name, start, end, block in service_spans(text):
        if name != 'worldserver':
            continue
        score = 0
        if re.search(r'(?m)^    command:\s*\[\s*["\']worldserver["\']\s*\]\s*$', block):
            score += 4
        if re.search(r'(?m)^    image:\s*forever-trinitycore(?::[^\s]+)?\s*$', block):
            score += 2
        if re.search(r'(?m)^    build:\s*$', block):
            score += 1
        if re.search(r'(?m)^    environment:\s*$', block):
            score += 1
        candidates.append((score, start, end, block))

    if not candidates:
        raise SystemExit('docker-compose: no top-level worldserver service candidate found')

    best_score = max(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == best_score]
    if best_score < 4:
        raise SystemExit(
            'docker-compose: worldserver candidates found, but none looks like the runnable worldserver service'
        )
    if len(best) != 1:
        details = ', '.join(str(item[0]) for item in candidates)
        raise SystemExit(
            f'docker-compose: worldserver service is ambiguous after content scoring (scores: {details})'
        )
    return best[0][1], best[0][2], best[0][3]


def patch_compose():
    path = Path('docker-compose.yml')
    text = path.read_text()
    if 'FOREVER_SCALING_ENABLED:' in text:
        return

    world_start, world_end, block = find_worldserver_service(text)

    env_match = re.search(r'(?m)^    environment:\s*$', block)
    if not env_match:
        raise SystemExit('docker-compose worldserver service: environment block not found')

    env_content_start = env_match.end()
    if env_content_start < len(block) and block[env_content_start] == '\n':
        env_content_start += 1

    boundary = re.search(r'(?m)^    [A-Za-z_][A-Za-z0-9_-]*:\s*', block[env_content_start:])
    if boundary:
        insert_rel = env_content_start + boundary.start()
    else:
        insert_rel = len(block)

    block = block[:insert_rel] + SCALING_ENV_LINES + block[insert_rel:]
    text = text[:world_start] + block + text[world_end:]
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

    # Verify the scaling variables landed in the actual runnable worldserver block.
    _, _, world_block = find_worldserver_service(compose)
    if 'FOREVER_SCALING_ENABLED:' not in world_block:
        raise SystemExit('ForeverScaling integration verification failed: variables are outside runnable worldserver')


if __name__ == '__main__':
    patch_dockerfile()
    patch_compose()
    verify()
    print('ForeverScaling Docker integration applied and verified')
