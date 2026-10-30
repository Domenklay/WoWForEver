#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
container=$(docker compose ps -q worldserver)
test -n "$container"
version=$(docker inspect --format '{{index .Config.Labels "org.wowforever.advancement"}}' "$container")
echo "Running ForeverAdvancement: $version"
if [ "$version" != '1.11.0' ]; then echo 'Server update required: expected ForeverAdvancement 1.11.0' >&2;exit 1;fi
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
logs=$(docker compose logs --since "$started" worldserver)
if ! grep -q 'ForeverAdvancement ready:' <<< "$logs" || ! grep -q 'worldserver-daemon.*ready' <<< "$logs" || ! grep -q 'ForeverAdvancement custom rules: 1 canonical abilities; protocol=3; version=1.11.0' <<< "$logs"; then
  echo 'Current worldserver has not confirmed the advancement catalogue and custom rules.' >&2;exit 1
fi
if [ -n "${1:-}" ]; then
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
addons=Path(sys.argv[1])/'Interface/AddOns'
toc=addons/'ForeverAscension/ForeverAscension.toc'
if not toc.is_file():raise SystemExit('ForeverAscension AddOn is missing')
version=next((row.split(':',1)[1].strip() for row in toc.read_text().splitlines() if row.startswith('## Version:')),None)
if version!='1.11.0':raise SystemExit('AddOn update required: expected ForeverAscension 1.11.0')
if (addons/'ForeverSubclass').exists():raise SystemExit('Legacy ForeverSubclass is still present; use the advancement installer')
if not (toc.parent/'CustomRules.lua').is_file():raise SystemExit('CustomRules.lua is missing')
print('ForeverAscension 1.11.0 installed; legacy AddOn absent')
PY
fi
echo 'Ready: one advancement module and the current custom rules.'
