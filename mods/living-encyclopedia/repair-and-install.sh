#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
client=${1:-/mnt/e/_classic_beta_}

echo 'Repair path now uses the same idempotent installer as normal installation.'
echo 'The subclass-owned 0004 addon endpoint patch is left untouched.'
exec bash mods/living-encyclopedia/install-dev.sh install "$client"
