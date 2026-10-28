#!/usr/bin/env bash
# Run locally on the user's initialized Compose server. Never uploads backups.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
action=${1:-status}
mysql_world() { docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot world'; }
set_enabled() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
p=Path('.env');lines=p.read_text().splitlines();out=[];found=False
for line in lines:
    if line.startswith('SUBCLASS_ENABLED='):
        if not found:out.append('SUBCLASS_ENABLED='+sys.argv[1]);found=True
    else:out.append(line)
if not found:out.append('SUBCLASS_ENABLED='+sys.argv[1])
p.write_text('\n'.join(out)+'\n')
PY
}
case "$action" in
  build) ;;
  status)
    docker compose ps
    docker compose logs --tail=300 worldserver | grep -E 'ForeverSubclass|Subclass|ready' || true
    exit ;;
  disable) ;;
  install) client=${2:-/mnt/e/_classic_beta_} ;;
  rollback) backup=${2:?Usage: bash scripts/subclass-mod.sh rollback backups/subclass-TIMESTAMP}; ;;
  *) echo 'Usage: bash scripts/subclass-mod.sh {build|install [CLIENT]|status|disable|rollback BACKUP}';exit 2 ;;
esac
command -v flock >/dev/null
umask 077
mkdir -p backups
exec 9>backups/content-port.lock
flock -n 9 || { echo 'Another subclass migration is running';exit 1; }
if [ "$action" = build ]; then
    docker compose build worldserver
    exit
fi
if [ "$action" = disable ]; then
    set_enabled 0
    docker compose up -d --no-deps --force-recreate worldserver
    echo 'Subclass gameplay disabled. Progress tables and AddOn kept.'
    exit
fi
if [ "$action" = rollback ]; then
    test -f "$backup/old-image.txt" && test -f "$backup/world-bindings.sql"
    docker image inspect "$(cat "$backup/old-image.txt")" >/dev/null
    trap 'docker compose up -d --no-deps worldserver bnetserver web || true' ERR
    docker compose stop web bnetserver worldserver
    printf '%s\n' "DELETE FROM spell_script_names WHERE ScriptName='spell_forever_subclass';" | mysql_world
    mysql_world < "$backup/world-bindings.sql"
    docker tag "$(cat "$backup/old-image.txt")" forever-trinitycore:latest
    set_enabled 0
    if [ -f "$backup/addon/addon-install.json" ]; then
        python3 scripts/install-subclass-addon.py --backup "$backup/addon" --restore
    fi
    python3 scripts/subclass-log-config.py --backup "$backup" --restore
    docker compose up -d --no-deps --force-recreate worldserver bnetserver web
    echo 'Rolled back server image and AddOn. Subclass progress retained for later use.'
    exit
fi
# No changes before basic prerequisites have been checked.
python3 - "$client" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not (p/'WowB.exe').is_file():raise SystemExit('Client folder must contain WowB.exe')
if (p/'Interface/AddOns/ForeverSubclass').is_symlink():raise SystemExit('Symlinked AddOn folder is not supported')
PY
label=$(docker image inspect --format '{{index .Config.Labels "org.wowforever.subclass"}}' forever-trinitycore:latest)
[ "$label" = '0.3.2-forever.5' ] || { echo 'Built image is stale or missing the reserved-rank SQL crash fix. Run: bash scripts/subclass-mod.sh build';exit 1; }
running=$(docker compose ps --status running --services)
for service in mysql worldserver bnetserver web; do
    if ! grep -qx "$service" <<< "$running"; then echo "Service $service must be running before installation";exit 1;fi
done
container=$(docker compose ps -q worldserver)
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
ready_logs=$(docker compose logs --since "$started" worldserver)
if ! grep -q 'worldserver-daemon.*ready' <<< "$ready_logs"; then
    echo 'Current worldserver must finish its initial import and report ready before installation.';exit 1
fi
backup=$(mktemp -d "backups/subclass-$(date +%Y%m%d-%H%M%S)-XXXXXX")
# Keep the built candidate reachable even after a rollback replaces :latest.
candidate="forever-trinitycore:subclass-candidate-$(basename "$backup")"
docker tag forever-trinitycore:latest "$candidate"
printf '%s\n' "$candidate" > "$backup/candidate-image.txt"
python3 scripts/preserve-container-image.py --container "$container" \
    --tag "forever-trinitycore:before-subclass-$(basename "$backup")" --backup "$backup"
cp .env "$backup/env.before"
git rev-parse HEAD > "$backup/source-commit.txt"
services_stopped=0
finished=0
restore_on_error() {
    code=$?
    trap - EXIT
    if [ "$finished" = 0 ] && [ "$services_stopped" = 1 ]; then
        echo "Installation failed; restoring previous server. Backup: $backup" >&2
        docker compose logs --no-color --timestamps --tail=3000 worldserver > "$backup/failed-worldserver.log" 2>&1 || true
        docker compose ps -a > "$backup/failed-services.txt" 2>&1 || true
        if [ -f "$backup/world-bindings.sql" ]; then
            printf '%s\n' "DELETE FROM spell_script_names WHERE ScriptName='spell_forever_subclass';" | mysql_world || true
            mysql_world < "$backup/world-bindings.sql" || true
        fi
        cp "$backup/env.before" .env
        docker tag "$(cat "$backup/old-image.txt")" forever-trinitycore:latest || true
        if [ -f "$backup/addon/addon-install.json" ]; then
            python3 scripts/install-subclass-addon.py --backup "$backup/addon" --restore || true
        fi
        python3 scripts/subclass-log-config.py --backup "$backup" --restore || true
        docker compose up -d --no-deps --force-recreate worldserver bnetserver web || true
    fi
    exit "$code"
}
trap restore_on_error EXIT
services_stopped=1
docker compose stop web bnetserver worldserver
echo "Saving database backup: $backup"
docker compose exec -T mysql sh -c '
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --quick --routines --events --triggers --no-tablespaces --set-gtid-purged=OFF --databases auth characters world hotfixes
' | gzip > "$backup/databases.sql.gz"
gzip -t "$backup/databases.sql.gz"
docker compose exec -T mysql sh -c '
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --no-create-info --skip-add-locks --skip-disable-keys --compact --no-tablespaces --set-gtid-purged=OFF --where="ScriptName='\''spell_forever_subclass'\''" world spell_script_names
' > "$backup/world-bindings.sql.tmp"
mv "$backup/world-bindings.sql.tmp" "$backup/world-bindings.sql"
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot characters' < mods/forever-subclass/sql/characters.sql
mysql_world < mods/forever-subclass/sql/world.sql
python3 scripts/install-subclass-addon.py --client "$client" --backup "$backup/addon"
python3 scripts/subclass-log-config.py --backup "$backup"
set_enabled 1
docker compose up -d --no-deps --force-recreate worldserver bnetserver web
container=$(docker compose ps -q worldserver)
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
for ((attempt=0;attempt<90;attempt++)); do
    logs=$(docker compose logs --since "$started" --tail=1200 worldserver)
    if grep -q 'ForeverSubclass ready:' <<< "$logs" && grep -q 'worldserver-daemon.*ready' <<< "$logs"; then
        finished=1
        echo "Subclass module installed. Backup: $backup"
        echo 'Enable ForeverSubclass in the game AddOns list, log in, and type /fsub.'
        exit 0
    fi
    if (( attempt % 5 == 0 )); then echo 'Waiting for worldserver and subclass catalogue...';fi
    sleep 2
done
echo 'worldserver did not confirm subclass startup; rolling back.' >&2
exit 1
