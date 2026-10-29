#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
c++ -std=c++17 -Wall -Wextra -Werror "$root/tests/rules_test.cpp" -o "$tmp/rules"
c++ -std=c++17 -Wall -Wextra -Werror "$root/tests/discovery_test.cpp" -o "$tmp/discovery"
c++ -std=c++17 -Wall -Wextra -Werror "$root/tests/talent_test.cpp" -o "$tmp/talents"
"$tmp/rules"
"$tmp/discovery"
"$tmp/talents"
python3 "$root/tests/inject_test.py"
bash -n "$root/install-dev.sh"
echo "Encyclopedia standalone tests passed"
