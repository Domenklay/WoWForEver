#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
c++ -std=c++17 -Wall -Wextra -Werror -pedantic tests/policy_test.cpp -o "$tmp"
"$tmp"
echo 'ForeverScaling policy tests passed'
