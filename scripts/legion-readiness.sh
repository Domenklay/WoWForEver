#!/usr/bin/env bash
# Read-only report. Does not teleport, patch client files, change DB data, or restart services.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo '=== Legion / Broken Isles: runtime Map record 1220 ==='
docker compose exec -T web python - <<'PY'
import asyncio
from app.main import soap_command
try:
    print(asyncio.run(soap_command('lookup map id 1220')))
except Exception as exc:
    print('Runtime map lookup failed: '+str(exc))
    raise SystemExit(1)
PY
echo '=== Extracted server geometry (read-only) ==='
docker compose exec -T worldserver bash -s <<'SH'
set -eu
data=/opt/trinitycore/data
printf 'Broken Isles terrain tiles: '
find "$data/maps" -maxdepth 1 -type f -name '1220_*.map' | wc -l
printf 'Broken Isles vmap files: '
find "$data/vmaps" -maxdepth 1 -type f -name '1220*' | wc -l
printf 'Broken Isles mmap files (optional while pathfinding is off): '
if [ -d "$data/mmaps" ]; then
  find "$data/mmaps" -maxdepth 1 -type f -name '1220*' | wc -l
else
  echo 0
fi
echo 'Sample Legion terrain/vmap files (at most 12):'
find "$data/maps" "$data/vmaps" -maxdepth 1 -type f -name '1220*' | LC_ALL=C sort | awk 'NR<=12'
echo 'Extracted Map.db2 files:'
find "$data/dbc" -type f -iname 'Map.db2' -print
echo 'Control: Eastern Kingdoms terrain tiles:'
find "$data/maps" -maxdepth 1 -type f -name '0000_*.map' | wc -l
SH
printf '\nPresence is a prerequisite, not proof of complete client assets or a playable zone.\n'
