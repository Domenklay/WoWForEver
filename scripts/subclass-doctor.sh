#!/usr/bin/env bash
# Read-only diagnostics for the ForeverSubclass runtime. Prints no passwords.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ok=1
pass() { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; ok=0; }
fail() { printf '[FAIL] %s\n' "$*"; ok=0; }

printf 'ForeverSubclass doctor\n'
printf 'Repository: %s\n\n' "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

if [ ! -f .env ]; then
    fail '.env not found'
else
    enabled=$(grep -E '^SUBCLASS_ENABLED=' .env | tail -n1 | cut -d= -f2- || true)
    if [ "$enabled" = "1" ]; then pass 'SUBCLASS_ENABLED=1';
    else warn "SUBCLASS_ENABLED=${enabled:-<unset>} (expected 1)"; fi
fi

if ! command -v docker >/dev/null 2>&1; then
    fail 'docker command not found'
    exit 1
fi

if docker compose ps --status running --services 2>/dev/null | grep -qx worldserver; then
    pass 'worldserver container is running'
else
    fail 'worldserver container is not running'
    docker compose ps 2>/dev/null || true
    exit 1
fi

container=$(docker compose ps -q worldserver 2>/dev/null)
image=$(docker inspect --format '{{.Image}}' "$container" 2>/dev/null || true)
label=$(docker inspect --format '{{index .Config.Labels "org.wowforever.subclass"}}' "$container" 2>/dev/null || true)
printf 'Running image: %s\n' "${image:-unknown}"
if [ -n "$label" ] && [ "$label" != '<no value>' ]; then
    pass "subclass image label: $label"
else
    warn 'running image has no org.wowforever.subclass label; it may be an old server image'
fi

logs=$(docker compose logs --no-color --tail=2500 worldserver 2>/dev/null || true)
if grep -q 'ForeverSubclass ready:' <<<"$logs"; then
    ready=$(grep 'ForeverSubclass ready:' <<<"$logs" | tail -n1)
    pass "$ready"
else
    fail 'worldserver log has no "ForeverSubclass ready:" line'
    for pattern in 'Subclass schema missing' 'Subclass catalogue empty' 'requires exactly one validated script binding'; do
        grep "$pattern" <<<"$logs" | tail -n5 || true
    done
fi

mysql_query() {
    local db=$1 sql=$2
    docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -N -B -uroot '"$db"' -e '"$(printf '%q' "$sql")" 2>/dev/null
}

if docker compose ps --status running --services 2>/dev/null | grep -qx mysql; then
    pass 'mysql container is running'
    missing=0
    for table in forever_character_class_progress forever_character_subclass_state forever_character_subclass_spells forever_character_subclass_resources; do
        count=$(docker compose exec -T mysql sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -N -B -uroot characters -e \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='characters' AND table_name='$table';\"" 2>/dev/null || echo 0)
        if [ "$count" = "1" ]; then pass "characters.$table exists"; else fail "characters.$table missing"; missing=1; fi
    done
    bindings=$(docker compose exec -T mysql sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -N -B -uroot world -e \"SELECT COUNT(*) FROM spell_script_names WHERE ScriptName='spell_forever_subclass';\"" 2>/dev/null || echo 0)
    if [ "${bindings:-0}" -gt 0 ] 2>/dev/null; then pass "world spell bindings: $bindings"; else fail 'no spell_forever_subclass bindings in world DB'; fi
else
    fail 'mysql container is not running'
fi

printf '\n'
if [ "$ok" = "1" ]; then
    printf 'RESULT: server-side subclass runtime looks ready. If the AddOn still waits, inspect addon-message transport next.\n'
    exit 0
else
    printf 'RESULT: server-side subclass runtime is incomplete. Do not recreate the character; repair/install the module.\n'
    printf 'Typical repair: bash scripts/subclass-mod.sh build && bash scripts/subclass-mod.sh install /mnt/e/_classic_beta_/\n'
    exit 1
fi
