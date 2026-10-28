#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ "${1:-}" = rollback ] && [ -f "${2:-}/addon/addon-install.json" ]; then
    exec bash scripts/subclass-legacy.sh "$@"
fi
if [ "${1:-}" = install-freepick ]; then shift;set -- install "$@";fi
exec bash scripts/advancement-mod.sh "$@"
