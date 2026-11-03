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
    test -f .env || { echo '.env not found. Run from the initialized WoWForEver checkout.' >&2; exit 1; }
}

preflight() {
    python3 - <<'PY'
from pathlib import Path
for name in (
    'scripts/apply-forever-dungeon-finder-integration.py',
    'scripts/inject-forever-dungeon-finder.py',
):
    compile(Path(name).read_text(), name, 'exec')
for name in (
    'mods/forever-dungeon-finder/server/ForeverDungeonFinder.cpp',
    'mods/forever-dungeon-finder/client/ForeverDungeonFinder/ForeverDungeonFinder.toc',
    'mods/forever-dungeon-finder/client/ForeverDungeonFinder/Core.lua',
):
    if not Path(name).is_file() or not Path(name).stat().st_size:
        raise SystemExit(f'Missing/empty required file: {name}')
print('ForeverDungeonFinder integration files passed preflight')
PY
    docker compose config -q
}

image_label() {
    docker image inspect --format '{{index .Config.Labels "org.wowforever.dungeonfinder"}}' forever-trinitycore:latest 2>/dev/null || true
}

image_ready() {
    test "$(image_label)" = "$version"
}

check_label() {
    local label
    label=$(image_label)
    test "$label" = "$version" || { echo "Expected dungeon-finder image label $version, got: ${label:-missing}" >&2; exit 1; }
}

build_or_reuse_image() {
    if image_ready; then
        echo "ForeverDungeonFinder $version image already exists; skipping Docker rebuild."
        return 0
    fi

    local rc=0
    set +e
    docker compose build worldserver
    rc=$?
    set -e

    if [ "$rc" -eq 0 ]; then
        check_label
        return 0
    fi

    echo "Docker build returned exit code $rc; checking whether export completed before the Docker API error..." >&2
    if image_ready; then
        echo "Docker export reported an error, but forever-trinitycore:latest is complete and has dungeon-finder label $version; continuing."
        return 0
    fi

    echo "Docker did not leave a usable ForeverDungeonFinder image." >&2
    return "$rc"
}

restore_source_files() {
    local backup=$1
    test -f "$backup/Dockerfile.before" && cp "$backup/Dockerfile.before" Dockerfile
    test -f "$backup/docker-compose.yml.before" && cp "$backup/docker-compose.yml.before" docker-compose.yml
}

restore_addon() {
    local backup=$1
    test -f "$backup/client-path.txt" || return 0
    local client addon_dir
    client=$(cat "$backup/client-path.txt")
    addon_dir="$client/Interface/AddOns/ForeverDungeonFinder"
    rm -rf "$addon_dir" || true
    if test -d "$backup/addon.before"; then
        mkdir -p "$(dirname "$addon_dir")"
        cp -a "$backup/addon.before" "$addon_dir"
    fi
}

validate_client() {
    local client=$1
    test -d "$client" || { echo "WoW client path not found: $client" >&2; exit 1; }
    test -d "$client/Interface" || mkdir -p "$client/Interface"
    mkdir -p "$client/Interface/AddOns"
    test -w "$client/Interface/AddOns" || { echo "Client AddOns directory is not writable: $client/Interface/AddOns" >&2; exit 1; }
}

install_addon() {
    local backup=$1 client=$2
    local source_dir="mods/forever-dungeon-finder/client/ForeverDungeonFinder"
    local addons_dir="$client/Interface/AddOns"
    local addon_dir="$addons_dir/ForeverDungeonFinder"

    printf '%s\n' "$client" > "$backup/client-path.txt"
    if test -d "$addon_dir"; then
        cp -a "$addon_dir" "$backup/addon.before"
    fi

    rm -rf "$addon_dir"
    cp -a "$source_dir" "$addon_dir"
    test -f "$addon_dir/ForeverDungeonFinder.toc"
    test -f "$addon_dir/Core.lua"
    echo "ForeverDungeonFinder addon installed to: $addon_dir"
}

case "$action" in
    status)
        require_env
        echo "FOREVER_DUNGEON_FINDER_ENABLED=$(grep -m1 '^FOREVER_DUNGEON_FINDER_ENABLED=' .env | cut -d= -f2- || echo 0)"
        echo "IMAGE_DUNGEON_FINDER_LABEL=$(image_label)"
        docker compose ps worldserver
        docker compose logs --tail=160 worldserver | grep -E 'ForeverDungeonFinder|worldserver-daemon.*ready' || true
        ;;

    build)
        require_env
        python3 scripts/apply-forever-dungeon-finder-integration.py
        preflight
        build_or_reuse_image
        check_label
        echo 'ForeverDungeonFinder image is ready. Runtime feature has not been enabled or restarted.'
        ;;

    disable)
        require_env
        set_env FOREVER_DUNGEON_FINDER_ENABLED 0
        docker compose up -d --no-deps --force-recreate worldserver
        echo 'ForeverDungeonFinder server feature disabled; client addon remains installed.'
        ;;

    rollback)
        require_env
        backup=${2:?Usage: bash scripts/forever-dungeon-finder-mod.sh rollback backups/dungeon-finder-TIMESTAMP}
        test -f "$backup/old-image.txt" && test -f "$backup/env.before" || { echo 'Invalid dungeon-finder backup directory.' >&2; exit 1; }
        old_image=$(cat "$backup/old-image.txt")
        docker image inspect "$old_image" >/dev/null
        cp "$backup/env.before" .env
        restore_source_files "$backup"
        restore_addon "$backup"
        docker tag "$old_image" forever-trinitycore:latest
        docker compose up -d --no-deps --force-recreate worldserver
        echo "ForeverDungeonFinder rollback restored $old_image, server config and previous addon state"
        ;;

    install)
        require_env
        command -v docker >/dev/null
        command -v python3 >/dev/null

        client=${2:-${WOW_CLIENT_PATH:-/mnt/e/_classic_beta_}}
        validate_client "$client"

        container=$(docker compose ps -q worldserver)
        test -n "$container" || { echo 'worldserver must already be running before installation.' >&2; exit 1; }

        umask 077
        mkdir -p backups
        backup="backups/dungeon-finder-$(date +%Y%m%d-%H%M%S)"
        mkdir "$backup"
        cp .env "$backup/env.before"
        cp Dockerfile "$backup/Dockerfile.before"
        cp docker-compose.yml "$backup/docker-compose.yml.before"
        git rev-parse HEAD > "$backup/source-commit.txt" 2>/dev/null || true

        activated=0
        image_preserved=0
        addon_touched=0
        restore_on_error() {
            code=$?
            trap - EXIT
            cp "$backup/env.before" .env || true
            restore_source_files "$backup" || true
            if [ "$addon_touched" = 1 ]; then
                restore_addon "$backup" || true
            fi
            if [ "$image_preserved" = 1 ]; then
                old_image=$(cat "$backup/old-image.txt")
                if docker image inspect "$old_image" >/dev/null 2>&1; then
                    if ! docker tag "$old_image" forever-trinitycore:latest; then
                        echo "WARNING: Docker API did not allow restoring the latest image tag. The running old worldserver container was not recreated." >&2
                    fi
                else
                    echo "WARNING: preserved rollback image is temporarily unavailable from the Docker API. The running old worldserver container was not recreated." >&2
                fi
            fi
            if [ "$activated" = 1 ]; then
                docker compose up -d --no-deps --force-recreate worldserver || true
            fi
            echo "Dungeon finder installation failed. Source/config/addon rollback attempted from $backup" >&2
            exit "$code"
        }
        trap restore_on_error EXIT

        python3 scripts/apply-forever-dungeon-finder-integration.py
        preflight

        python3 scripts/preserve-container-image.py \
            --container "$container" \
            --tag "forever-trinitycore:before-dungeon-finder-$(basename "$backup")" \
            --backup "$backup"
        image_preserved=1

        # The existing worldserver stays live. If an earlier export already left
        # a correctly labelled image, avoid recompiling it.
        build_or_reuse_image
        check_label

        set_env FOREVER_DUNGEON_FINDER_ENABLED 1
        addon_touched=1
        install_addon "$backup" "$client"

        activated=1
        docker compose up -d --no-deps --force-recreate worldserver

        trap - EXIT
        echo "ForeverDungeonFinder $version installed and enabled."
        echo "Client addon: $client/Interface/AddOns/ForeverDungeonFinder"
        echo "Rollback: bash scripts/forever-dungeon-finder-mod.sh rollback $backup"
        docker compose logs --tail=120 worldserver | grep -E 'ForeverDungeonFinder|worldserver-daemon.*ready' || true
        ;;

    *)
        echo 'Usage: bash scripts/forever-dungeon-finder-mod.sh {status|build|install [CLIENT_PATH]|disable|rollback BACKUP}' >&2
        exit 2
        ;;
esac
