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
def one(pattern, text, label):
    found=list(re.finditer(pattern,text,re.M))
    if len(found)!=1: raise SystemExit(f'{label}: expected one integration point, found {len(found)}')
    return found[0]

# Dockerfile integration is deliberately independent of the subclass adapter layout.
# The encyclopedia injector only needs to run after the core checkout/patches and before CMake.
p=Path('Dockerfile');s=p.read_text()
if '/encyclopedia-module/server/inject.py' not in s:
    block='''# Living Encyclopedia: independent Custom script injection.\nCOPY mods/living-encyclopedia /encyclopedia-module\nRUN python3 /encyclopedia-module/server/inject.py /src/TrinityCore --module /encyclopedia-module\n\n'''
    points=[]
    for pat in (r'(?m)^ARG BUILD_JOBS=.*$', r'(?m)^WORKDIR /src/TrinityCore/build\s*$'):
        found=list(re.finditer(pat,s))
        if len(found)==1:
            points=found;break
    if len(points)!=1: raise SystemExit('Dockerfile: cannot locate build-stage insertion point (BUILD_JOBS/WORKDIR)')
    m=points[0];s=s[:m.start()]+block+s[m.start():]

# Runtime label is metadata only; add it without depending on the subclass label text.
if 'org.wowforever.encyclopedia=' not in s:
    runtime=one(r'(?m)^############################ runtime ############################\s*$',s,'Dockerfile runtime stage')
    after=s[runtime.end():]
    fm=list(re.finditer(r'(?m)^FROM\s+ubuntu:\$\{UBUNTU_VERSION\}\s*$',after))
    if len(fm)!=1: raise SystemExit(f'Dockerfile runtime FROM: expected one after runtime marker, found {len(fm)}')
    m=fm[0];absolute_end=runtime.end()+m.end()
    s=s[:absolute_end]+'\nLABEL org.wowforever.encyclopedia="0.2.2-server-discovery"'+s[absolute_end:]
write(p,s)

# worldserver config flag: prefer the subclass neighborhood, but fall back to the end of configure_worldserver.
p=Path('docker/entrypoint.sh');s=p.read_text()
if 'ForeverEncyclopedia.Enable' not in s:
    candidates=list(re.finditer(r'(?m)^(\s*setkey\s+"\$f"\s+ForeverSubclass\.(?:Freepick|Enable)\s+.*)$',s))
    if candidates:
        m=candidates[-1]
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'setkey "$f" ForeverEncyclopedia.Enable "${ENCYCLOPEDIA_ENABLED:-0}"'
        s=s[:m.start()]+ins+s[m.end():]
    else:
        m=one(r'(?m)^(\s*apply_overrides\s+"\$f"\s+worldserver\s*)$',s,'entrypoint worldserver overrides')
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=indent+'setkey "$f" ForeverEncyclopedia.Enable "${ENCYCLOPEDIA_ENABLED:-0}"\n'+m.group(1)
        s=s[:m.start()]+ins+s[m.end():]
write(p,s)

# Compose flag: prefer the subclass environment, otherwise insert next to PACKET_LOG/SOAP in worldserver env.
p=Path('docker-compose.yml');s=p.read_text()
if 'ENCYCLOPEDIA_ENABLED:' not in s:
    candidates=list(re.finditer(r'(?m)^(\s*SUBCLASS_(?:FREEPICK|ENABLED):\s*.*)$',s))
    if candidates:
        m=candidates[-1]
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'ENCYCLOPEDIA_ENABLED: ${ENCYCLOPEDIA_ENABLED:-0}'
        s=s[:m.start()]+ins+s[m.end():]
    else:
        m=one(r'(?m)^(\s*PACKET_LOG:\s*.*)$',s,'docker-compose worldserver environment')
        indent=re.match(r'\s*',m.group(1)).group(0)
        ins=m.group(1)+'\n'+indent+'ENCYCLOPEDIA_ENABLED: ${ENCYCLOPEDIA_ENABLED:-0}'
        s=s[:m.start()]+ins+s[m.end():]
write(p,s)

# Reuse the already proven server-bound addon-message patch; add a second prefix only.
p=Path('docker/patches/0004-forever-subclass-server-addon-endpoint.patch');s=p.read_text()
if 'prefix == "FEC1"' not in s:
    old='if (type == CHAT_MSG_WHISPER && prefix == "FSC1")'
    new='if (type == CHAT_MSG_WHISPER && (prefix == "FSC1" || prefix == "FEC1"))'
    if s.count(old)!=1: raise SystemExit('addon endpoint patch: FSC1 condition not found exactly once')
    s=s.replace(old,new,1)
write(p,s)

print(f'Source integration repaired. Backup: {backup}')
PY

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

exec bash mods/living-encyclopedia/install-dev.sh install "$client"
