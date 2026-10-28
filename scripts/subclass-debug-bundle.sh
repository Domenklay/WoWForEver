#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
client=${1:-/mnt/e/_classic_beta_}
reports=${2:-/mnt/e/WoWForEver-work/reports}
mkdir -p "$reports"
umask 077
out="$reports/advancement-debug-$(date +%Y%m%d-%H%M%S).txt"
{
    echo 'ForeverAdvancement diagnostic bundle'
    git rev-parse HEAD
    bash scripts/subclass-doctor.sh "$client" || true
    docker compose logs --no-color --tail=800 worldserver 2>&1 | grep -E 'ForeverAdvancement|ready|ERROR' || true
    docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -N -B -uroot characters -e "SELECT COUNT(*) AS learned_rows FROM forever_advancement_spells; SELECT COUNT(*) AS resource_rows FROM forever_advancement_resources;"' || true
    if [ -f "$client/Interface/AddOns/ForeverAscension/ForeverAscension.toc" ]; then
        cat "$client/Interface/AddOns/ForeverAscension/ForeverAscension.toc"
    fi
} > "$out"
echo "Diagnostic file: $out"
