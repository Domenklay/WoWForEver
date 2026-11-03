#!/usr/bin/env python3
"""Wire Forever Dungeon Finder into the current local WoWForEver checkout.

The checkout may contain integrations from other modules, so this patcher uses
stable build/runtime/service boundaries and only inserts this feature's lines.
"""
from pathlib import Path
import re

VERSION = '0.1.0'

BUILD_BLOCK = '''# Forever Dungeon Finder: direct solo/current-party instance entry without LFG queueing.
COPY mods/forever-dungeon-finder /forever-dungeon-finder-module
COPY scripts/inject-forever-dungeon-finder.py /tmp/inject-forever-dungeon-finder.py
RUN python3 /tmp/inject-forever-dungeon-finder.py /src/TrinityCore --module /forever-dungeon-finder-module

'''

ENV_LINE = '      FOREVER_DUNGEON_FINDER_ENABLED: ${FOREVER_DUNGEON_FINDER_ENABLED:-0}\n'


def exactly_once(text: str, needle: str, description: str) -> int:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f'{description}: expected one anchor, found {count}')
    return text.index(needle)


def patch_dockerfile() -> None:
    path = Path('Dockerfile')
    text = path.read_text()

    if 'scripts/inject-forever-dungeon-finder.py' not in text:
        marker = '# BUILD_JOBS:'
        pos = exactly_once(text, marker, 'Dockerfile build-stage boundary')
        text = text[:pos] + BUILD_BLOCK + text[pos:]

    pattern = r'LABEL org\.wowforever\.dungeonfinder="[^"]+"'
    replacement = f'LABEL org.wowforever.dungeonfinder="{VERSION}"'
    text, count = re.subn(pattern, replacement, text)
    if count > 1:
        raise SystemExit(f'Dockerfile dungeon-finder label: expected at most one, found {count}')

    if count == 0:
        runtime_marker = '############################ runtime ############################\n'
        start = exactly_once(text, runtime_marker, 'Dockerfile runtime boundary') + len(runtime_marker)
        from_match = re.match(r'FROM[^\n]*\n', text[start:])
        if not from_match:
            raise SystemExit('Dockerfile runtime boundary: FROM line not found')
        insert = start + from_match.end()
        text = text[:insert] + replacement + '\n' + text[insert:]

    path.write_text(text)


def service_spans(text: str):
    starts = list(re.finditer(r'(?m)^  ([A-Za-z0-9_.-]+):\s*$', text))
    for i, match in enumerate(starts):
        start = match.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        yield match.group(1), start, end, text[start:end]


def find_worldserver_service(text: str):
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
        raise SystemExit('docker-compose: no top-level worldserver service found')

    best_score = max(item[0] for item in candidates)
    if best_score < 4:
        scores = ', '.join(str(item[0]) for item in candidates)
        raise SystemExit(f'docker-compose: worldserver candidates do not look runnable (scores: {scores})')

    # Local installers can leave overlay/duplicate service blocks. Docker compose
    # validation runs afterwards; choose the last strongest runnable candidate.
    best = [item for item in candidates if item[0] == best_score]
    return best[-1][1], best[-1][2], best[-1][3]


def patch_compose() -> None:
    path = Path('docker-compose.yml')
    text = path.read_text()

    world_start, world_end, block = find_worldserver_service(text)
    if 'FOREVER_DUNGEON_FINDER_ENABLED:' not in block:
        env_match = re.search(r'(?m)^    environment:\s*$', block)
        if not env_match:
            raise SystemExit('docker-compose worldserver service: environment block not found')

        content_start = env_match.end()
        if content_start < len(block) and block[content_start] == '\n':
            content_start += 1

        boundary = re.search(r'(?m)^    [A-Za-z_][A-Za-z0-9_-]*:\s*', block[content_start:])
        insert = content_start + boundary.start() if boundary else len(block)
        block = block[:insert] + ENV_LINE + block[insert:]
        text = text[:world_start] + block + text[world_end:]
        path.write_text(text)


def verify() -> None:
    docker = Path('Dockerfile').read_text()
    compose = Path('docker-compose.yml').read_text()

    requirements = {
        'Dockerfile module COPY': 'COPY mods/forever-dungeon-finder /forever-dungeon-finder-module',
        'Dockerfile injector RUN': 'RUN python3 /tmp/inject-forever-dungeon-finder.py /src/TrinityCore --module /forever-dungeon-finder-module',
        'Dockerfile image label': f'org.wowforever.dungeonfinder="{VERSION}"',
        'Compose runtime switch': 'FOREVER_DUNGEON_FINDER_ENABLED:',
    }
    for name, needle in requirements.items():
        haystack = docker if name.startswith('Dockerfile') else compose
        if needle not in haystack:
            raise SystemExit(f'ForeverDungeonFinder integration verification failed: {name}')

    _, _, world_block = find_worldserver_service(compose)
    if 'FOREVER_DUNGEON_FINDER_ENABLED:' not in world_block:
        raise SystemExit('ForeverDungeonFinder variable is outside the runnable worldserver block')


if __name__ == '__main__':
    patch_dockerfile()
    patch_compose()
    verify()
    print(f'ForeverDungeonFinder {VERSION} Docker integration applied and verified')
