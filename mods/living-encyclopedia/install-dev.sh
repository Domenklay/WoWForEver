#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
action=${1:-status}
client=${2:-/mnt/e/_classic_beta_}

set_env() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
p=Path('.env')
if not p.is_file(): raise SystemExit('.env not found')
value=sys.argv[1]
rows=[];found=False
for row in p.read_text().splitlines():
    if row.startswith('ENCYCLOPEDIA_ENABLED='):
        if not found:
            rows.append('ENCYCLOPEDIA_ENABLED='+value);found=True
    else:
        rows.append(row)
if not found:
    rows.append('ENCYCLOPEDIA_ENABLED='+value)
p.write_text('\n'.join(rows)+'\n')
PY
}

prepare_source() {
  mkdir -p backups
  local stamp="backups/encyclopedia-source-$(date +%Y%m%d-%H%M%S)"
  python3 - "$stamp" <<'PY'
from pathlib import Path
import datetime,re,shutil,sys
backup=Path(sys.argv[1]);backup.mkdir(parents=True,exist_ok=False)
paths=[Path('Dockerfile'),Path('docker/entrypoint.sh'),Path('docker-compose.yml')]
for p in paths:
    if not p.is_file(): raise SystemExit(f'missing required source file: {p}')
    q=backup/p;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)

def one(pattern,text,label):
    found=list(re.finditer(pattern,text,re.M))
    if len(found)!=1: raise SystemExit(f'{label}: expected one integration point, found {len(found)}')
    return found[0]

# Dockerfile: inject independently of whatever exact subclass installer version is present.
p=Path('Dockerfile');s=p.read_text()
if '/encyclopedia-module/server/inject.py' not in s:
    block='''# Living Encyclopedia: independent Custom script injection.\nCOPY mods/living-encyclopedia /encyclopedia-module\nRUN python3 /encyclopedia-module/server/inject.py /src/TrinityCore --module /encyclopedia-module\n\n'''
    points=[]
    for pat in (r'(?m)^ARG BUILD_JOBS=.*$',r'(?m)^WORKDIR /src/TrinityCore/build\s*$'):
        found=list(re.finditer(pat,s))
        if len(found)==1:
            points=found;break
    if len(points)!=1: raise SystemExit('Dockerfile: cannot locate build-stage insertion point (BUILD_JOBS/WORKDIR)')
    m=points[0];s=s[:m.start()]+block+s[m.start():]

if 'org.wowforever.encyclopedia=' not in s:
    runtime=one(r'(?m)^############################ runtime ############################\s*$',s,'Dockerfile runtime stage')
    after=s[runtime.end():]
    found=list(re.finditer(r'(?m)^FROM\s+ubuntu:\$\{UBUNTU_VERSION\}\s*$',after))
    if len(found)!=1: raise SystemExit(f'Dockerfile runtime FROM: expected one after runtime marker, found {len(found)}')
    m=found[0];pos=runtime.end()+m.end()
    s=s[:pos]+'\nLABEL org.wowforever.encyclopedia="0.2.3-server-discovery"'+s[pos:]
p.write_text(s)

# Runtime feature flag.
p=Path('docker/entrypoint.sh');s=p.read_text()
if 'ForeverEncyclopedia.Enable' not in s:
    candidates=list(re.finditer(r'(?m)^(\s*setkey\s+"\$f"\s+ForeverSubclass\.(?:Freepick|Enable)\s+.*)$',s))
    if candidates:
        m=candidates[-1];indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'setkey "$f" ForeverEncyclopedia.Enable "${ENCYCLOPEDIA_ENABLED:-0}"'
        s=s[:m.start()]+ins+s[m.end():]
    else:
        m=one(r'(?m)^(\s*apply_overrides\s+"\$f"\s+worldserver\s*)$',s,'entrypoint worldserver overrides')
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=indent+'setkey "$f" ForeverEncyclopedia.Enable "${ENCYCLOPEDIA_ENABLED:-0}"\n'+m.group(1)
        s=s[:m.start()]+ins+s[m.end():]
p.write_text(s)

# Compose environment flag.
p=Path('docker-compose.yml');s=p.read_text()
if 'ENCYCLOPEDIA_ENABLED:' not in s:
    candidates=list(re.finditer(r'(?m)^(\s*SUBCLASS_(?:FREEPICK|ENABLED):\s*.*)$',s))
    if candidates:
        m=candidates[-1];indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'ENCYCLOPEDIA_ENABLED: ${ENCYCLOPEDIA_ENABLED:-0}'
        s=s[:m.start()]+ins+s[m.end():]
    else:
        m=one(r'(?m)^(\s*PACKET_LOG:\s*.*)$',s,'docker-compose worldserver environment')
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'ENCYCLOPEDIA_ENABLED: ${ENCYCLOPEDIA_ENABLED:-0}'
        s=s[:m.start()]+ins+s[m.end():]
p.write_text(s)

print(f'Prepared encyclopedia source integration. Backup: {backup}')
PY
}

status() {
  docker compose ps
  docker compose logs --tail=300 worldserver | grep -E 'ForeverEncyclopedia|worldserver-daemon.*ready' || true
}

case "$action" in
  prepare)
    prepare_source
    ;;
  build)
    prepare_source
    bash mods/living-encyclopedia/tests/run-rules.sh
    python3 mods/living-encyclopedia/server/inject.py --self-test
    docker compose build worldserver
    ;;
  status)
    status
    ;;
  disable)
    set_env 0
    docker compose up -d --no-deps --force-recreate worldserver
    echo 'ForeverEncyclopedia disabled; discovery table and AddOn retained.'
    ;;
  install) ;;
  *)
    echo 'Usage: bash mods/living-encyclopedia/install-dev.sh {prepare|build|install [CLIENT]|status|disable}'
    exit 2
    ;;
esac

[ "$action" = install ] || exit 0

python3 - "$client" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not (p/'WowB.exe').is_file(): raise SystemExit('Client folder must contain WowB.exe')
PY

running=$(docker compose ps --status running --services)
for service in mysql worldserver; do
  grep -qx "$service" <<<"$running" || { echo "Service $service must be running before installation"; exit 1; }
done

mkdir -p backups
backup=$(mktemp -d "backups/encyclopedia-$(date +%Y%m%d-%H%M%S)-XXXXXX")
cp .env "$backup/env.before"
if docker image inspect forever-trinitycore:latest >/dev/null 2>&1; then
  old="forever-trinitycore:before-encyclopedia-$(basename "$backup")"
  docker tag forever-trinitycore:latest "$old"
  printf '%s\n' "$old" > "$backup/old-image.txt"
fi
addon="$client/Interface/AddOns/ForeverEncyclopedia"
mkdir -p "$backup/addon"
if [ -d "$addon" ]; then cp -a "$addon" "$backup/addon/ForeverEncyclopedia"; fi

prepare_source
bash mods/living-encyclopedia/tests/run-rules.sh
python3 mods/living-encyclopedia/server/inject.py --self-test

echo 'Building worldserver with ForeverEncyclopedia...'
docker compose build worldserver
candidate="forever-trinitycore:encyclopedia-candidate-$(basename "$backup")"
docker tag forever-trinitycore:latest "$candidate"
printf '%s\n' "$candidate" > "$backup/candidate-image.txt"

echo "Saving characters database backup: $backup/characters.sql.gz"
docker compose exec -T mysql sh -c '
 MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF characters
' | gzip > "$backup/characters.sql.gz"
gzip -t "$backup/characters.sql.gz"

docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot characters' \
  < mods/living-encyclopedia/sql/characters-v1.sql

mkdir -p "$client/Interface/AddOns"
rm -rf "$addon"
cp -a mods/living-encyclopedia/addon/ForeverEncyclopedia "$addon"
set_env 1

restore_on_error() {
  code=$?
  trap - EXIT
  if [ "$code" -ne 0 ]; then
    echo "Encyclopedia install failed; restoring previous runtime. Backup: $backup" >&2
    cp "$backup/env.before" .env || true
    if [ -f "$backup/old-image.txt" ]; then docker tag "$(cat "$backup/old-image.txt")" forever-trinitycore:latest || true; fi
    rm -rf "$addon" || true
    if [ -d "$backup/addon/ForeverEncyclopedia" ]; then cp -a "$backup/addon/ForeverEncyclopedia" "$addon" || true; fi
    docker compose up -d --no-deps --force-recreate worldserver || true
  fi
  exit "$code"
}
trap restore_on_error EXIT

docker compose up -d --no-deps --force-recreate worldserver
container=$(docker compose ps -q worldserver)
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
for ((attempt=0; attempt<90; attempt++)); do
  logs=$(docker compose logs --since "$started" --tail=1500 worldserver)
  if grep -q 'ForeverEncyclopedia ready:' <<<"$logs" && grep -q 'worldserver-daemon.*ready' <<<"$logs"; then
    trap - EXIT
    echo "ForeverEncyclopedia installed. Backup: $backup"
    echo "Client AddOn: $addon"
    echo 'Start the client, enable Forever Encyclopedia, log in and type /ency.'
    exit 0
  fi
  if grep -q 'ForeverEncyclopedia schema missing' <<<"$logs"; then
    echo 'worldserver reports missing encyclopedia schema' >&2
    exit 1
  fi
  sleep 2
done

echo 'worldserver did not confirm ForeverEncyclopedia startup' >&2
exit 1
