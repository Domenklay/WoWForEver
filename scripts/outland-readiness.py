#!/usr/bin/env python3
"""Read-only Outland runtime/geometry/CASC report. Does not install or teleport."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, timeout=300, **kwargs)


def collect(client, output, runner=run):
    client=Path(client).resolve(strict=True)
    output=Path(output).resolve()
    if not (client/'.build.info').is_file() or not (client/'Data').is_dir():
        raise ValueError('Expected CASC root with .build.info and Data; normally /mnt/e')
    # Keep reports outside the installation; never create a directory inside the client.
    if output==client or any(output.is_relative_to((client/name).resolve()) for name in ('Data','_classic_beta_')):
        raise ValueError('Report directory must be outside Data and _classic_beta_')
    if output.exists():raise FileExistsError('Use a new report directory: '+str(output))
    output.mkdir(parents=True)
    report=dict(format='wowforever-outland-readiness-v2',map_id=530,client=str(client),checks={},
                playable_map_confirmed=False,negative_name_lookup_proves_absence=False,
                note='Read-only checks; resource dependencies, client rendering and VMAP coverage are not validated.')
    def check(label,command,stdin=None):
        try:
            result=runner(command,cwd=ROOT,input=stdin)
            (output/(label+'.stdout.log')).write_text(result.stdout)
            (output/(label+'.stderr.log')).write_text(result.stderr)
            value={'exit_code':result.returncode}
            try:value['result']=json.loads(result.stdout)
            except ValueError:value['text']=result.stdout.strip()
            report['checks'][label]=value
        except (OSError,subprocess.SubprocessError) as exc:
            report['checks'][label]={'error':str(exc)}
    check('runtime',['docker','compose','exec','-T','web','python','-'],'''import asyncio,json
from app.main import soap_command
print(json.dumps({'lookup':asyncio.run(soap_command('lookup map id 530'))}))
''')
    check('geometry',['docker','compose','exec','-T','worldserver','bash','-s'],'''set -eu
for d in maps vmaps mmaps; do
 echo "=== $d: Map 530 files (at most 30) ==="
 if [ -d /opt/trinitycore/data/$d ]; then
 find /opt/trinitycore/data/$d -type f \\( -name '0530*' -o -name '530*' \\) | head -30
 fi
done
''')
    image='forever-legion-casc-probe:local'
    try:
        inspected=runner(['docker','image','inspect','--format','{{.Id}}',image],cwd=ROOT)
        image_present=inspected.returncode==0
    except (OSError,subprocess.SubprocessError):
        image_present=False
    if not image_present:
        report['checks']['client']={'error':'Missing existing CASC probe image; no build or client changes performed'}
    else:
        check('client',['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=256m',
            '--mount',f'type=bind,src={client},dst=/wow,readonly',
            '--mount',f'type=bind,src={ROOT / "tools/terrain-335"},dst=/probe,readonly',
            '--entrypoint','/bin/sh',image,'-c',
            'set -e; c++ -std=c++20 -O2 -I/src/TrinityCore/dep/CascLib/src /probe/check-client-paths.cpp '
            '/src/TrinityCore/build/dep/CascLib/libcasc.a -lz -lcrypto -o /tmp/check-client-paths; '
            'exec /tmp/check-client-paths /wow'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return output/'report.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('client',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    print('Report:',collect(a.client,a.output))


if __name__=='__main__':main()
