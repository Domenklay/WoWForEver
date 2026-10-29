#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
client=${1:-/mnt/e/_classic_beta_}

python3 - <<'PY'
from pathlib import Path
import re, shutil, datetime

stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup=Path('backups')/f'encyclopedia-source-repair-{stamp}'
backup.mkdir(parents=True, exist_ok=False)
paths=[Path('Dockerfile'),Path('docker/entrypoint.sh'),Path('docker-compose.yml'),Path('docker/patches/0004-forever-subclass-server-addon-endpoint.patch')]
for p in paths:
    if not p.is_file(): raise SystemExit(f'missing required source file: {p}')
    q=backup/p;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)

def write(path, s): Path(path).write_text(s)

# Dockerfile: accept the current server source and a previous partially prepared run.
p=Path('Dockerfile');s=p.read_text()
if '/encyclopedia-module/server/inject.py' not in s:
    pat=r'(?m)^(RUN\s+python3\s+/tmp/inject-subclass\.py\s+/src/TrinityCore\s+--module\s+/subclass-module\s*)$'
    m=list(re.finditer(pat,s))
    if len(m)!=1: raise SystemExit('Dockerfile: cannot locate subclass injector uniquely')
    insertion=m[0].group(1)+'\n\n# Living Encyclopedia is injected independently after the subclass adapter.\nCOPY mods/living-encyclopedia /encyclopedia-module\nRUN python3 /encyclopedia-module/server/inject.py /src/TrinityCore --module /encyclopedia-module'
    s=s[:m[0].start()]+insertion+s[m[0].end():]
if 'org.wowforever.encyclopedia=' not in s:
    pat=r'(?m)^(LABEL\s+org\.wowforever\.subclass=.*)$'
    m=list(re.finditer(pat,s))
    if len(m)!=1: raise SystemExit('Dockerfile: cannot locate subclass label uniquely')
    insertion=m[0].group(1)+'\nLABEL org.wowforever.encyclopedia="0.2.1-server-discovery"'
    s=s[:m[0].start()]+insertion+s[m[0].end():]
write(p,s)

# entrypoint: insert config next to subclass config without depending on exact subclass version.
p=Path('docker/entrypoint.sh');s=p.read_text()
if 'ForeverEncyclopedia.Enable' not in s:
    pat=r'(?m)^(\s*setkey\s+"\$f"\s+ForeverSubclass\.Freepick\s+.*)$'
    m=list(re.finditer(pat,s))
    if len(m)!=1: raise SystemExit('entrypoint: cannot locate ForeverSubclass.Freepick uniquely')
    insertion=m[0].group(1)+'\n    setkey "$f" ForeverEncyclopedia.Enable "${ENCYCLOPEDIA_ENABLED:-0}"'
    s=s[:m[0].start()]+insertion+s[m[0].end():]
write(p,s)

# compose: expose feature flag to worldserver.
p=Path('docker-compose.yml');s=p.read_text()
if 'ENCYCLOPEDIA_ENABLED:' not in s:
    pat=r'(?m)^(\s*SUBCLASS_FREEPICK:\s*.*)$'
    m=list(re.finditer(pat,s))
    if len(m)!=1: raise SystemExit('docker-compose.yml: cannot locate SUBCLASS_FREEPICK uniquely')
    indent=re.match(r'\s*',m[0].group(1)).group(0)
    insertion=m[0].group(1)+'\n'+indent+'ENCYCLOPEDIA_ENABLED: ${ENCYCLOPEDIA_ENABLED:-0}'
    s=s[:m[0].start()]+insertion+s[m[0].end():]
write(p,s)

# Shared server-bound addon endpoint. Patch source itself must remain a valid git patch.
p=Path('docker/patches/0004-forever-subclass-server-addon-endpoint.patch');s=p.read_text()
if 'prefix == "FEC1"' not in s:
    old='if (type == CHAT_MSG_WHISPER && prefix == "FSC1")'
    new='if (type == CHAT_MSG_WHISPER && (prefix == "FSC1" || prefix == "FEC1"))'
    if s.count(old)!=1: raise SystemExit('addon endpoint patch: FSC1 condition not found exactly once')
    s=s.replace(old,new,1)
write(p,s)

print(f'Source integration repaired. Backup: {backup}')
PY

# Validate source-level pieces before a Docker build.
bash mods/living-encyclopedia/tests/run-rules.sh
python3 mods/living-encyclopedia/server/inject.py --self-test
python3 - <<'PY'
from pathlib import Path
checks={
'Dockerfile':['/encyclopedia-module/server/inject.py','org.wowforever.encyclopedia='],
'docker/entrypoint.sh':['ForeverEncyclopedia.Enable'],
'docker-compose.yml':['ENCYCLOPEDIA_ENABLED:'],
'docker/patches/0004-forever-subclass-server-addon-endpoint.patch':['prefix == "FEC1"'],
}
for f,needles in checks.items():
    s=Path(f).read_text()
    for n in needles:
        if n not in s: raise SystemExit(f'{f}: missing {n}')
print('Encyclopedia source integration checks passed')
PY

# Continue through the normal installer; its prepare_source is now idempotent because all markers exist.
exec bash mods/living-encyclopedia/install-dev.sh install "$client"
