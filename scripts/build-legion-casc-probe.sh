#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

image=${1:-forever-legion-casc-probe:local}

tmp=$(mktemp "${TMPDIR:-/tmp}/wowforever-casc-probe.Dockerfile.XXXXXX")
trap 'rm -f "$tmp"' EXIT

python3 - "$tmp" <<'PY'
from pathlib import Path
import sys

source = Path('Dockerfile').read_text()
out = Path(sys.argv[1])

needle = '''FROM build AS legion-casc-probe
COPY tools/legion-casc-probe/probe.cpp /tmp/legion-casc-probe.cpp
RUN c++ -std=c++20 -O2 -I/src/TrinityCore/dep/CascLib/src \\
        /tmp/legion-casc-probe.cpp /src/TrinityCore/build/dep/CascLib/libcasc.a \\
        -lz -lcrypto -o /usr/local/bin/legion-casc-probe
'''

replacement = '''FROM build AS legion-casc-probe
COPY tools/legion-casc-probe/probe.cpp /tmp/legion-casc-probe.cpp
# The main TrinityCore build directory is a BuildKit cache mount. Its artifacts
# are intentionally not persisted into the build image, so rebuild only CascLib
# in a small ordinary /tmp build tree before linking the standalone probe.
RUN cmake -S /src/TrinityCore -B /tmp/legion-casc-build \\
        -DCMAKE_BUILD_TYPE=Release \\
        -DTOOLS=0 \\
        -DWITH_WARNINGS=0 \\
    && cmake --build /tmp/legion-casc-build --target casc -j2 \\
    && test -f /tmp/legion-casc-build/dep/CascLib/libcasc.a \\
    && c++ -std=c++20 -O2 -I/src/TrinityCore/dep/CascLib/src \\
        /tmp/legion-casc-probe.cpp /tmp/legion-casc-build/dep/CascLib/libcasc.a \\
        -lz -lcrypto -o /usr/local/bin/legion-casc-probe
'''

count = source.count(needle)
if count != 1:
    raise SystemExit(f'Cannot patch legion-casc-probe block safely: expected 1 exact block, found {count}')

out.write_text(source.replace(needle, replacement, 1))
PY

echo "Building ${image} with an isolated CascLib build..."
docker build --target legion-casc-probe -f "$tmp" -t "$image" .

docker image inspect "$image" >/dev/null
echo "CASC PROBE IMAGE READY: $image"
