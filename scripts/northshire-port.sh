#!/usr/bin/env bash
# Local content migration; run on the machine hosting the Docker Compose stack.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
port_dir=content/ports/northshire-335
case "${1:-}" in
  status)
    docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot world' <<'SQL'
SELECT ID,LogTitle FROM quest_template WHERE ID IN (7,900007);
SELECT QuestID,ObjectID,Amount FROM quest_objectives WHERE QuestID=900007;
SELECT guid,id,map,position_x,position_y,position_z FROM creature WHERE id=900197;
SQL
    exit ;;
  apply|rollback) action=$1 ;;
  *) echo "Usage: bash scripts/northshire-port.sh {status|apply|rollback}"; exit 2 ;;
esac
command -v flock >/dev/null
umask 077
mkdir -p backups
exec 9>backups/northshire-port.lock
flock -n 9 || { echo 'Another content migration is running'; exit 1; }
# Do not start services which the operator had intentionally stopped.
running=$(docker compose ps --status running --services)
for service in mysql worldserver bnetserver web; do
  if ! grep -qx "$service" <<< "$running"; then
    echo "Service $service must be running before migration. No changes made."
    exit 1
  fi
done
backup_dir=$(mktemp -d "backups/northshire-$(date +%Y%m%d-%H%M%S)-XXXXXX")
cleanup() {
  result=$?
  trap - EXIT
  if ! docker compose start worldserver bnetserver web; then
    echo 'Could not restart services; run: docker compose start worldserver bnetserver web' >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT
# Finish the first database import and log out of the game before running this script.
docker compose stop web bnetserver worldserver
# Save all account/character/world/hotfix data together, plus local configuration.
docker compose exec -T mysql sh -c '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot \
    --single-transaction --quick --routines --events --triggers \
    --no-tablespaces --set-gtid-purged=OFF \
    --databases auth characters world hotfixes
' | gzip > "$backup_dir/databases.sql.gz"
gzip -t "$backup_dir/databases.sql.gz"
tar -czf "$backup_dir/settings.tar.gz" .env certs overrides docker-compose.yml
git rev-parse HEAD > "$backup_dir/source-commit.txt"
echo "Backup: $backup_dir (contains private keys/passwords; keep local)"
docker compose exec -T mysql sh -c '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot world
' < "$port_dir/$action.sql"
echo "Completed: $action. Services will restart now."
