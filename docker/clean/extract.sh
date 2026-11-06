#!/bin/bash
# /client is read-only; /output is a new, private extraction directory.
set -euo pipefail
trap 'printf "Extraction failed at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

validate_output() {
    local output="$1" folder pattern
    for folder in dbc gt cameras maps vmaps; do
        if [[ ! -d "$output/$folder" ]]; then
            printf 'Extraction incomplete: missing directory %s\n' "$folder" >&2
            return 1
        fi
    done
    if [[ ! -s "$output/vmaps/GameObjectModels.dtree" ]]; then
        printf 'Extraction incomplete: missing or empty vmaps/GameObjectModels.dtree\n' >&2
        return 1
    fi
    for pattern in 'dbc/*.db2' 'gt/*.txt' 'cameras/*.xxx' 'maps/*.map' 'vmaps/*.vmtree'; do
        folder="${pattern%%/*}"
        # Modern upstream stores terrain and VMAP trees under per-map directories.
        # Require nonempty payloads, but do not assume they live in the top directory.
        if [[ -z "$(find "$output/$folder" -type f -name "${pattern#*/}" -size +0c -print -quit)" ]]; then
            printf 'Extraction incomplete: no nonempty %s payloads (searched recursively)\n' "$pattern" >&2
            return 1
        fi
    done
}

if [[ "${1:-}" == '--validate-only' && "$#" == 2 ]]; then
    validate_output "$2"
    printf 'Extracted data structure verified. This does not certify full client file coverage.\n'
    exit 0
elif [[ "$#" != 0 ]]; then
    printf 'Usage: %s [--validate-only OUTPUT]\n' "$0" >&2
    exit 2
fi
test -f /client/.build.info
test -d /client/Data
product="${FOREVER_CASC_PRODUCT:-wowf}"
case "$product" in
    wowf) test -d /client/_forever_ ;;
    wow_classic_beta) test -d /client/_classic_beta_ ;;
    *) printf 'Unsupported CASC product\n' >&2; exit 2 ;;
esac
test -z "$(ls -A /output)"
cd /output
/opt/trinitycore/bin/mapextractor -i /client -o /output -p "$product"
test -d dbc && test -d maps && test -d gt && test -d cameras
mkdir .vmap-work
cd .vmap-work
/opt/trinitycore/bin/vmap4extractor -d /client -p "$product"
cd /output
mkdir vmaps
/opt/trinitycore/bin/vmap4assembler .vmap-work/Buildings vmaps
validate_output /output
printf 'Extraction complete: %s, fresh dbc/gt/cameras/maps/vmaps\n' "$product"
