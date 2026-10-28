#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash scripts/advancement-mod.sh status
docker image inspect --format '{{index .Config.Labels "org.wowforever.advancement"}}' forever-trinitycore:latest
if [ -n "${1:-}" ]; then
  test -f "$1/Interface/AddOns/ForeverAscension/ForeverAscension.toc"
  echo 'ForeverAscension AddOn present'
fi
