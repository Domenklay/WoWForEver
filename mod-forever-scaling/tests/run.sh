#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

run_local() {
    local compiler=$1
    local tmp
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    "$compiler" -std=c++17 -Wall -Wextra -Werror -pedantic tests/policy_test.cpp -o "$tmp"
    "$tmp"
}

if command -v c++ >/dev/null 2>&1; then
    run_local c++
elif command -v g++ >/dev/null 2>&1; then
    run_local g++
elif command -v docker >/dev/null 2>&1; then
    echo 'Local C++ compiler not found; running the test inside Docker.'
    docker run --rm \
        -v "$PWD:/work:ro" \
        -w /work \
        gcc:14-bookworm \
        sh -lc 'g++ -std=c++17 -Wall -Wextra -Werror -pedantic tests/policy_test.cpp -o /tmp/forever-scaling-policy-test && /tmp/forever-scaling-policy-test'
else
    echo 'Neither a local C++ compiler nor Docker is available.' >&2
    exit 1
fi

echo 'ForeverScaling policy tests passed'
