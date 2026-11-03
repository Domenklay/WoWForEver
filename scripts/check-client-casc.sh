#!/usr/bin/env bash
# Compile only the tiny checker using the already-built probe image; no core rebuild.
set -euo pipefail
client=$(realpath "${1:?Usage: check-client-casc.sh CLIENT_ROOT FILE_ID ...}")
shift
[ "$#" -gt 0 ]
probe_sources=$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/legion-casc-probe" && pwd)
if ! docker version --format '{{.Server.Version}}' >/dev/null; then
    echo 'Docker daemon is unavailable in the current context. Start Docker or restore the intended context; no client changes have been made.' >&2
    exit 1
fi
if [ -n "${CASC_CHECK_IMAGE:-}" ]; then
    image=$CASC_CHECK_IMAGE
elif docker image inspect forever-legion-casc-probe:local >/dev/null 2>&1; then
    image=forever-legion-casc-probe:local
else
    image=forever-legion-casc-check:local
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Missing local probe image: $image. No client changes have been made." >&2
    echo 'From this tool checkout, build the standalone reader (no worldserver/bnetserver build):' >&2
    echo 'docker build -f docker/CascProbe.Dockerfile -t forever-legion-casc-check:local .' >&2
    if [ -n "${CASC_CHECK_IMAGE:-}" ]; then
        echo 'CASC_CHECK_IMAGE explicitly selects another image; set it to the reader you built before retrying.' >&2
    fi
    exit 1
fi
docker run --rm --network none --read-only --cap-drop ALL \
    --env "CASC_CHECK_LOCALE=${CASC_CHECK_LOCALE:-all}" \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=256m \
    --mount "type=bind,src=$client,dst=/wow,readonly" \
    --mount "type=bind,src=$probe_sources,dst=/probe,readonly" \
    --entrypoint /bin/sh "$image" -c '
      set -e
      if [ -x /usr/local/bin/check-storage ] && [ -f /probe-build/check-storage.cpp ] && \
          cmp -s /probe/check-storage.cpp /probe-build/check-storage.cpp; then
        exec /usr/local/bin/check-storage /wow "$@"
      fi
      c++ -std=c++20 -O2 -I/src/TrinityCore/dep/CascLib/src \
        /probe/check-storage.cpp /src/TrinityCore/build/dep/CascLib/libcasc.a \
        -lz -lcrypto -o /tmp/check-storage
      exec /tmp/check-storage /wow "$@"
    ' check-client-casc "$@"
