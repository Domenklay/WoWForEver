#!/usr/bin/env bash
# Run locally on the user's initialized Compose server. Never uploads backups.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
action=${1:-status}
if [ "$action" = update ]; then
    bash scripts/advancement-mod.sh build
    exec bash scripts/advancement-mod.sh install "${2:-/mnt/e/_classic_beta_}"
fi
mysql_world() { docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot world'; }
mysql_hotfixes() { docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot hotfixes'; }
remove_native_power_hotfix() {
    printf '%s\n' \
      "DELETE FROM hotfix_data WHERE TableHash=3224459983 AND RecordId IN (190031901,190031902);" \
      "DELETE FROM chr_classes_x_power_types WHERE ID IN (190031901,190031902);" | mysql_hotfixes
}
set_enabled() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
p=Path('.env');lines=p.read_text().splitlines();out=[];found=False
for line in lines:
    if line.startswith('ADVANCEMENT_ENABLED='):
        if not found:out.append('ADVANCEMENT_ENABLED='+sys.argv[1]);found=True
    elif line.startswith('SUBCLASS_ENABLED='):out.append('SUBCLASS_ENABLED=0')
    else:out.append(line)
if not found:out.append('ADVANCEMENT_ENABLED='+sys.argv[1])
p.write_text('\n'.join(out)+'\n')
PY
}
case "$action" in
  build) ;;
  status)
    docker compose ps
    docker compose logs --tail=300 worldserver | grep -E 'ForeverAdvancement|ready' || true
    exit ;;
  disable) ;;
  install|addon) client=${2:-/mnt/e/_classic_beta_} ;;
  rollback) backup=${2:?Usage: bash scripts/advancement-mod.sh rollback backups/advancement-TIMESTAMP}; ;;
  *) echo 'Usage: bash scripts/advancement-mod.sh {build|install [CLIENT]|update [CLIENT]|addon [CLIENT]|status|disable|rollback BACKUP}';exit 2 ;;
esac
command -v flock >/dev/null
umask 077
mkdir -p backups
exec 9>backups/content-port.lock
flock -n 9 || { echo 'Another advancement migration is running';exit 1; }
if [ "$action" = addon ]; then
    backup=$(mktemp -d "backups/advancement-ui-$(date +%Y%m%d-%H%M%S)-XXXXXX")
    python3 scripts/install-advancement-addon.py --client "$client" --backup "$backup/addon"
    echo "AddOn updated without rebuilding or restarting the server. Backup: $backup"
    echo "Rollback: bash scripts/advancement-mod.sh rollback $backup"
    exit
fi
if [ "$action" = build ]; then
    docker compose build worldserver
    exit
fi
if [ "$action" = disable ]; then
    set_enabled 0
    remove_native_power_hotfix
    docker compose up -d --no-deps --force-recreate worldserver
    echo 'Advancement disabled. Progress tables and AddOn kept.'
    exit
fi
if [ "$action" = rollback ]; then
    if [ -f "$backup/addon/advancement-addon.json" ] && [ ! -f "$backup/old-image.txt" ]; then
        python3 scripts/install-advancement-addon.py --backup "$backup/addon" --restore
        echo 'AddOn restored. Server and database were not changed.'
        exit
    fi
    test -f "$backup/old-image.txt" && test -f "$backup/world-bindings.sql"
    docker image inspect "$(cat "$backup/old-image.txt")" >/dev/null
    trap 'docker compose up -d --no-deps worldserver bnetserver web || true' ERR
    docker compose stop web bnetserver worldserver
    printf '%s\n' "DELETE FROM spell_script_names WHERE ScriptName IN ('spell_forever_subclass','spell_forever_advancement');" | mysql_world
    mysql_world < "$backup/world-bindings.sql"
    remove_native_power_hotfix
    if [ -f "$backup/native-power.sql" ]; then mysql_hotfixes < "$backup/native-power.sql"; fi
    docker tag "$(cat "$backup/old-image.txt")" forever-trinitycore:latest
    cp "$backup/env.before" .env
    if [ -f "$backup/addon/advancement-addon.json" ]; then
        python3 scripts/install-advancement-addon.py --backup "$backup/addon" --restore
    fi
    python3 scripts/subclass-log-config.py --backup "$backup" --restore
    docker compose up -d --no-deps --force-recreate worldserver bnetserver web
    echo 'Rolled back server image, native-power hotfix and AddOn. Both old and new progress tables retained.'
    exit
fi
python3 - "$client" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not (p/'WowB.exe').is_file():raise SystemExit('Client folder must contain WowB.exe')
for name in ('ForeverSubclass','ForeverAscension'):
    if (p/'Interface/AddOns'/name).is_symlink():raise SystemExit('Symlinked AddOn folder is not supported')
PY
label=$(docker image inspect --format '{{index .Config.Labels "org.wowforever.advancement"}}' forever-trinitycore:latest)
if [ "$label" = '1.10.0' ]; then :
else echo 'Built image is stale or missing native-power-slot support. Run: bash scripts/advancement-mod.sh build';exit 1;fi
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
backup=$(mktemp -d "backups/advancement-$(date +%Y%m%d-%H%M%S)-XXXXXX")
candidate="forever-trinitycore:advancement-candidate-$(basename "$backup")"
docker tag forever-trinitycore:latest "$candidate"
printf '%s\n' "$candidate" > "$backup/candidate-image.txt"
python3 scripts/preserve-container-image.py --container "$container" \
    --tag "forever-trinitycore:before-advancement-$(basename "$backup")" --backup "$backup"
cp .env "$backup/env.before"
git rev-parse HEAD > "$backup/source-commit.txt"
services_stopped=0
native_power_changed=0
finished=0
restore_on_error() {
    code=$?
    trap - EXIT
    if [ "$finished" = 0 ] && [ "$services_stopped" = 1 ]; then
        echo "Installation failed; restoring previous server. Backup: $backup" >&2
        docker compose logs --no-color --timestamps --tail=3000 worldserver > "$backup/failed-worldserver.log" 2>&1 || true
        docker compose ps -a > "$backup/failed-services.txt" 2>&1 || true
        if [ -f "$backup/world-bindings.sql" ]; then
            printf '%s\n' "DELETE FROM spell_script_names WHERE ScriptName IN ('spell_forever_subclass','spell_forever_advancement');" | mysql_world || true
            mysql_world < "$backup/world-bindings.sql" || true
        fi
        if [ "$native_power_changed" = 1 ]; then
            remove_native_power_hotfix || true
            if [ -f "$backup/native-power.sql" ]; then mysql_hotfixes < "$backup/native-power.sql" || true; fi
        fi
        cp "$backup/env.before" .env
        docker tag "$(cat "$backup/old-image.txt")" forever-trinitycore:latest || true
        if [ -f "$backup/addon/advancement-addon.json" ]; then
            python3 scripts/install-advancement-addon.py --backup "$backup/addon" --restore || true
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
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --no-create-info --skip-add-locks --skip-disable-keys --compact --no-tablespaces --set-gtid-purged=OFF --where="ScriptName IN ('\''spell_forever_subclass'\'','\''spell_forever_advancement'\'')" world spell_script_names
' > "$backup/world-bindings.sql.tmp"
mv "$backup/world-bindings.sql.tmp" "$backup/world-bindings.sql"
docker compose exec -T mysql sh -c '
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --no-create-info --skip-add-locks --skip-disable-keys --compact --no-tablespaces --set-gtid-purged=OFF --where="ID IN (190031901,190031902)" hotfixes chr_classes_x_power_types
' > "$backup/native-power.sql.tmp"
docker compose exec -T mysql sh -c '
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --no-create-info --skip-add-locks --skip-disable-keys --compact --no-tablespaces --set-gtid-purged=OFF --where="TableHash=3224459983 AND RecordId IN (190031901,190031902)" hotfixes hotfix_data
' >> "$backup/native-power.sql.tmp"
mv "$backup/native-power.sql.tmp" "$backup/native-power.sql"

docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot characters' < mods/forever-advancement/sql/characters.sql
mysql_world < mods/forever-advancement/sql/world.sql
native_power_changed=1
remove_native_power_hotfix
python3 scripts/install-advancement-addon.py --client "$client" --backup "$backup/addon"
python3 scripts/subclass-log-config.py --backup "$backup"
set_enabled 1
docker compose up -d --no-deps --force-recreate worldserver bnetserver web
container=$(docker compose ps -q worldserver)
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
for ((attempt=0;attempt<90;attempt++)); do
    logs=$(docker compose logs --since "$started" --tail=1200 worldserver)
    if grep -q 'ForeverAdvancement ready:' <<< "$logs" && grep -q 'worldserver-daemon.*ready' <<< "$logs"; then
        finished=1
        echo "ForeverAdvancement installed. Backup: $backup"
        echo 'Enable ForeverAscension in the game AddOns list, log in, and type /ascension.'
        exit 0
    fi
    if (( attempt % 5 == 0 )); then echo 'Waiting for worldserver and advancement catalogue...';fi
    sleep 2
done
echo 'worldserver did not confirm advancement startup; rolling back.' >&2
exit 1
