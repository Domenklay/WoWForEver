#!/usr/bin/env bash
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

stamp=$(date +%Y%m%d-%H%M%S)
out="backups/subclass-debug-$stamp.txt"
mkdir -p backups

{
  echo "ForeverSubclass diagnostic bundle"
  echo "Generated: $(date -Is)"
  echo "Repository HEAD: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "Repository short: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo

  echo "=== ADDON ==="
  if [ -f mods/forever-subclass/addon/ForeverSubclass/ForeverSubclass.toc ]; then
    grep -E '^## (Interface|Version|Title):' mods/forever-subclass/addon/ForeverSubclass/ForeverSubclass.toc || true
    echo "TOC files:"
    grep -E '\.lua$' mods/forever-subclass/addon/ForeverSubclass/ForeverSubclass.toc || true
  else
    echo "TOC missing"
  fi
  echo

  echo "=== RUNNING SERVER IMAGE ==="
  container=$(docker compose ps -q worldserver 2>/dev/null || true)
  if [ -n "$container" ]; then
    echo "Container: $container"
    image=$(docker inspect --format '{{.Image}}' "$container" 2>/dev/null || true)
    echo "Image ID: ${image:-unknown}"
    echo -n "Subclass label: "
    docker inspect --format '{{index .Config.Labels "org.wowforever.subclass"}}' "$container" 2>/dev/null || true
    echo -n "Created: "
    docker image inspect --format '{{.Created}}' "$image" 2>/dev/null || true
  else
    echo "worldserver container not found"
  fi
  echo

  echo "=== DOCTOR ==="
  bash scripts/subclass-doctor.sh 2>&1 || true
  echo

  echo "=== RECENT SUBCLASS SERVER LOGS ==="
  docker compose logs --no-color --timestamps --tail=4000 worldserver 2>&1 \
    | grep -Ei 'ForeverSubclass|Subclass|FSC1|FSR1|addon' \
    | tail -n 800 || true
  echo

  echo "=== SUBCLASS DATABASE SUMMARY ==="
  if docker compose ps --status running --services 2>/dev/null | grep -qx mysql; then
    docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -B -uroot characters -e "
      SELECT \"state_rows\",COUNT(*) FROM forever_character_subclass_state;
      SELECT \"class_rows\",COUNT(*) FROM forever_character_class_progress;
      SELECT \"spell_rows\",COUNT(*) FROM forever_character_subclass_spells;
      SELECT \"resource_rows\",COUNT(*) FROM forever_character_subclass_resources;
      SELECT guid,primary_class_id,IFNULL(active_subclass_id,0),IFNULL(xp_target_class_id,0) FROM forever_character_subclass_state ORDER BY guid LIMIT 50;
    "' 2>&1 || true
  else
    echo "mysql not running"
  fi
  echo

  echo "=== CLIENT ADDON INSTALL (if mounted) ==="
  client=${1:-/mnt/e/_classic_beta_/}
  toc="$client/Interface/AddOns/ForeverSubclass/ForeverSubclass.toc"
  if [ -f "$toc" ]; then
    echo "Client: $client"
    grep -E '^## (Interface|Version|Title):' "$toc" || true
    echo "Files:"
    find "$client/Interface/AddOns/ForeverSubclass" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort
  else
    echo "Installed addon TOC not found at: $toc"
  fi
} > "$out"

echo "$out"
