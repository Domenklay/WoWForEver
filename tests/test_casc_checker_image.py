"""Reader-image recovery and Docker availability without a daemon or client."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CheckerImageTests(unittest.TestCase):
    def invoke(self,mode,explicit=None):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);client=folder/'client';client.mkdir()
            docker=folder/'docker';log=folder/'calls.jsonl'
            docker.write_text('''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
with open(os.environ['FAKE_DOCKER_LOG'],'a') as f:f.write(json.dumps(args)+'\\n')
mode=os.environ['FAKE_DOCKER_MODE']
if args[0]=='version':
    if mode=='offline':print('Cannot connect to Docker daemon',file=sys.stderr);sys.exit(1)
    print('28.0');sys.exit(0)
if args[:2]==['image','inspect']:
    exists=args[2]==('forever-legion-casc-probe:local' if mode=='full' else 'forever-legion-casc-check:local')
    sys.exit(0 if mode not in ('missing','offline') and exists else 1)
if args[0]=='run':print('CHECKER_RUN');sys.exit(0)
sys.exit(2)
''')
            docker.chmod(0o755)
            env=dict(os.environ,PATH=str(folder)+os.pathsep+os.environ['PATH'],
                     FAKE_DOCKER_MODE=mode,FAKE_DOCKER_LOG=str(log))
            env.pop('CASC_CHECK_IMAGE',None)
            if explicit is not None:env['CASC_CHECK_IMAGE']=explicit
            result=subprocess.run(['bash',str(ROOT/'scripts/check-client-casc.sh'),str(client),'123'],
                                  env=env,text=True,capture_output=True)
            calls=[json.loads(line) for line in log.read_text().splitlines()]
            return result,calls

    def test_prefers_existing_full_probe(self):
        result,calls=self.invoke('full')
        self.assertEqual(result.returncode,0,result.stderr)
        run=next(c for c in calls if c[0]=='run')
        self.assertIn('forever-legion-casc-probe:local',run)

    def test_uses_standalone_reader_with_readonly_client_and_no_network(self):
        result,calls=self.invoke('minimal')
        self.assertEqual(result.returncode,0,result.stderr)
        run=next(c for c in calls if c[0]=='run')
        self.assertIn('forever-legion-casc-check:local',run)
        self.assertIn('--read-only',run)
        self.assertEqual(run[run.index('--network')+1],'none')
        self.assertTrue(any(',dst=/wow,readonly' in arg for arg in run))

    def test_missing_image_prints_only_standalone_build_instructions(self):
        result,calls=self.invoke('missing')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('docker/CascProbe.Dockerfile',result.stderr)
        self.assertFalse(any(c[0] in ('run','build') for c in calls))

    def test_explicit_image_is_not_replaced_by_another_image(self):
        result,calls=self.invoke('minimal','custom-missing:local')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('custom-missing:local',result.stderr)
        self.assertIn('explicitly selects',result.stderr)
        self.assertFalse(any(c[0]=='run' for c in calls))

    def test_unavailable_daemon_is_reported_instead_of_a_missing_image(self):
        result,calls=self.invoke('offline')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('daemon is unavailable',result.stderr)
        self.assertNotIn('Missing local probe image',result.stderr)
        self.assertEqual(len(calls),1)
