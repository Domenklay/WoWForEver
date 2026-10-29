#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

action=${1:-status}
version=0.1.0

set_env() {
    local key=$1 value=$2
    python3 - "$key" "$value" <<'PY'
from pathlib import Path
import sys
key, value = sys.argv[1], sys.argv[2]
p = Path('.env')
rows = p.read_text().splitlines()
out = []
found = False
for row in rows:
    if row.startswith(key + '='):
        if not found:
            out.append(f'{key}={value}')
            found = True
    else:
        out.append(row)
if not found:
    out.append(f'{key}={value}')
p.write_text('\n'.join(out) + '\n')
PY
}

require_env() {
    test -f .env || { echo '.env not found. Run this from the initialized WoWForEver server.' >&2; exit 1; }
}

check_label() {
    local label
    label=$(docker image inspect --format '{{index .Config.Labels "org.wowforever.scaling"}}' forever-trinitycore:latest 2>/dev/null || true)
    test "$label" = "$version" || { echo "Expected scaling image label $version, got: ${label:-missing}" >&2; exit 1; }
}

case "$action" in
    status)
        require_env
        echo "FOREVER_SCALING_ENABLED=$(grep -m1 '^FOREVER_SCALING_ENABLED=' .env | cut -d= -f2- || echo 0)"
        echo "IMAGE_SCALING_LABEL=$(docker image inspect --format '{{index .Config.Labels "org.wowforever.scaling"}}' forever-trinitycore:latest 2>/dev/null || echo missing)"
        docker compose ps worldserver
        docker compose logs --tail=120 worldserver | grep -E 'ForeverScaling|worldserver-daemon.*ready' || true
        ;;
    build)
        require_env
        bash mod-forever-scaling/tests/run.sh
        docker compose build worldserver
        check_label
        echo 'ForeverScaling image built. Gameplay has not been enabled or restarted.'
        ;;
    disable)
        require_env
        set_env FOREVER_SCALING_ENABLED 0
        docker compose up -d --no-deps --force-recreate worldserver
        echo 'ForeverScaling disabled; compiled adapter remains in the image.'
        ;;
    rollback)
        require_env
        backup=${2:?Usage: bash scripts/forever-scaling-mod.sh rollback backups/scaling-TIMESTAMP}
        test -f "$backup/old-image.txt" && test -f "$backup/env.before" || { echo 'Invalid scaling backup directory.' >&2; exit 1; }
        old_image=$(cat "$backup/old-image.txt")
        docker image inspect "$old_image" >/dev/null
        cp "$backup/env.before" .env
        docker tag "$old_image" forever-trinitycore:latest
        docker compose up -d --no-deps --force-recreate worldserver
        echo "ForeverScaling rollback restored $old_image"
        ;;
    install)
        require_env
        command -v docker >/dev/null
        command -v python3 >/dev/null
        bash mod-forever-scaling/tests/run.sh

        container=$(docker compose ps -q worldserver)
        test -n "$container" || { echo 'worldserver must already be running before scaling installation.' >&2; exit 1; }

        umask 077
        mkdir -p backups
        backup="backups/scaling-$(date +%Y%m%d-%H%M%S)"
        mkdir "$backup"
        cp .env "$backup/env.before"
        git rev-parse HEAD > "$backup/source-commit.txt" 2>/dev/null || true
        python3 scripts/preserve-container-image.py \
            --container "$container" \
            --tag "forever-trinitycore:before-scaling-$(basename "$backup")" \
            --backup "$backup"

        activated=0
        restore_on_error() {
            code=$?
            trap - EXIT
            old_image=$(cat "$backup/old-image.txt")
            cp "$backup/env.before" .env
            docker tag "$old_image" forever-trinitycore:latest || true
            if [ "$activated" = 1 ]; then
                docker compose up -d --no-deps --force-recreate worldserver || true
            fi
            echo "Scaling installation failed. Previous image/config restored from $backup" >&2
            exit "$code"
        }
        trap restore_on_error EXIT

        # Building changes the image tag but does not touch the currently running container.
        docker compose build worldserver
        check_label
        set_env FOREVER_SCALING_ENABLED 1
        set_env FOREVER_SCALING_DAMAGE_GUARD 1
        activated=1
        docker compose up -d --no-deps --force-recreate worldserver

        trap - EXIT
        echo "ForeverScaling $version installed and enabled."
        echo "Rollback: bash scripts/forever-scaling-mod.sh rollback $backup"
        docker compose logs --tail=100 worldserver | grep -E 'ForeverScaling|worldserver-daemon.*ready' || true
        ;;
    *)
        echo 'Usage: bash scripts/forever-scaling-mod.sh {status|build|install|disable|rollback BACKUP}' >&2
        exit 2
        ;;
esac
