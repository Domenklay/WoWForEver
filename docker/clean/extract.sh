#!/bin/bash
# /client is read-only; /output is a new, private extraction directory.
set -euo pipefail
test -f /client/.build.info
test -d /client/Data
test -d /client/_forever_
test -z "$(ls -A /output)"
cd /output
/opt/trinitycore/bin/mapextractor -i /client -o /output -p wowf
test -d dbc && test -d maps && test -d gt && test -d cameras
mkdir .vmap-work
cd .vmap-work
/opt/trinitycore/bin/vmap4extractor -d /client -p wowf
cd /output
mkdir vmaps
/opt/trinitycore/bin/vmap4assembler .vmap-work/Buildings vmaps
test -s vmaps/GameObjectModels.dtree
test -n "$(find maps -maxdepth 1 -type f -name '*.map' -print -quit)"
test -n "$(find vmaps -maxdepth 1 -type f -name '*.vmtree' -print -quit)"
printf 'Extraction complete: wowf, fresh dbc/gt/cameras/maps/vmaps\n'
