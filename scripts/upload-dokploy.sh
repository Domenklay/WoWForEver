#!/bin/sh
# Copies the game data and the server certificates to the Dokploy application (persistent files/ folder).
#
# Usage: ./scripts/upload-dokploy.sh user@server [DOKPLOY_APP_NAME]
#   e.g.  ./scripts/upload-dokploy.sh root@my-server
# Without DOKPLOY_APP_NAME, the Dokploy application holding this project is found automatically
# (otherwise: Dokploy, General tab, "App Name").
set -eu

TARGET="${1:?usage: $0 user@server [DOKPLOY_APP_NAME]}"
APP="${2:-}"
if [ -z "$APP" ]; then
    APPS=$(ssh "$TARGET" 'for d in /etc/dokploy/compose/*/; do grep -qs "forever-trinitycore" "$d/code/docker-compose.yml" && basename "$d"; done; true')
    case $(printf '%s\n' "$APPS" | grep -c .) in
        1) APP="$APPS"; echo "== Dokploy application found: $APP" ;;
        0) echo "No Dokploy application holds this project on $TARGET (deploy it once first, or give DOKPLOY_APP_NAME)." >&2; exit 1 ;;
        *) printf 'Several possible applications, give DOKPLOY_APP_NAME:\n%s\n' "$APPS" >&2; exit 1 ;;
    esac
fi
DIR="/etc/dokploy/compose/$APP/files"
cd "$(dirname "$0")/.."

for f in certs/forever.cert.pem certs/forever.key.pem certs/ca/forever_root_ca.crt data/vmaps/GameObjectModels.dtree; do
    [ -f "$f" ] || { echo "Missing on this machine: $f" >&2; exit 1; }
done

echo "== Checking the application $APP on $TARGET"
ssh "$TARGET" "test -d /etc/dokploy/compose/$APP" || { echo "Application not found: /etc/dokploy/compose/$APP" >&2; exit 1; }

# Docker creates an empty folder in place of a mounted file that did not exist yet: remove them
ssh "$TARGET" "for f in certs/forever.cert.pem certs/forever.key.pem certs/ca/forever_root_ca.crt; do \
    [ -d '$DIR'/\$f ] && rmdir '$DIR'/\$f 2>/dev/null; done; mkdir -p '$DIR/data' '$DIR/certs/ca'"

echo "== Game data (~700 MB)"
if command -v rsync >/dev/null 2>&1 && ssh "$TARGET" 'command -v rsync' >/dev/null 2>&1; then
    rsync -a --delete --info=progress2 data/ "$TARGET:$DIR/data/"
else
    # no rsync on the server: tar archive over SSH (the remote folder is emptied first)
    ssh "$TARGET" "find '$DIR/data' -mindepth 1 -delete"
    if command -v pv >/dev/null 2>&1; then
        tar -C data -cf - . | pv -s "$(du -sb data | cut -f1)" | ssh "$TARGET" "tar -C '$DIR/data' -xf -"
    else
        tar -C data -cf - . | ssh "$TARGET" "tar -C '$DIR/data' -xf -"
    fi
fi

echo "== Certificates (never the CA key)"
scp -q certs/forever.cert.pem certs/forever.key.pem "$TARGET:$DIR/certs/"
scp -q certs/ca/forever_root_ca.crt "$TARGET:$DIR/certs/ca/"
ssh "$TARGET" "chmod 644 '$DIR/certs/forever.cert.pem' '$DIR/certs/ca/forever_root_ca.crt'; chmod 600 '$DIR/certs/forever.key.pem'; ls -la '$DIR/certs' '$DIR/certs/ca'; du -sh '$DIR/data'"

echo "Done. Redeploy the application in Dokploy."
