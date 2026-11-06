#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

run_local() {
    local compiler=$1
    local source tmp rc
    for source in tests/policy_test.cpp tests/dungeon_policy_test.cpp; do
        tmp=$(mktemp)
        rc=0
        "$compiler" -std=c++17 -Wall -Wextra -Werror -pedantic "$source" -o "$tmp" || rc=$?
        if [ "$rc" -eq 0 ]; then
            "$tmp" || rc=$?
        fi
        rm -f -- "$tmp"
        if [ "$rc" -ne 0 ]; then
            echo "Failed: $source" >&2
            return "$rc"
        fi
    done
}

if command -v c++ >/dev/null 2>&1; then
    run_local c++
elif command -v g++ >/dev/null 2>&1; then
    run_local g++
elif command -v docker >/dev/null 2>&1; then
    echo 'Local C++ compiler not found; running the tests inside Docker.'
    docker run --rm \
        -v "$PWD:/work:ro" \
        -w /work \
        gcc:14-bookworm \
        sh -lc 'set -eu; for src in tests/policy_test.cpp tests/dungeon_policy_test.cpp; do g++ -std=c++17 -Wall -Wextra -Werror -pedantic "$src" -o /tmp/forever-scaling-policy-test; /tmp/forever-scaling-policy-test; done'
else
    echo 'Neither a local C++ compiler nor Docker is available.' >&2
    exit 1
fi

echo 'ForeverScaling and DungeonPolicy tests passed'
