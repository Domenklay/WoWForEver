import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).parents[1]
DOCKER=r'''#!/usr/bin/env python3
import os,sys
a=sys.argv[1:]
if a[:2]==['compose','ps']:print('running-world')
elif a[:2]==['inspect','--format']:
 assert a[-1]=='running-world'
 print('2026-10-30T00:00:00Z' if 'StartedAt' in a[2] else os.environ['MOCK_SERVER_VERSION'])
elif a[:2]==['compose','logs']:
 assert '--since' in a and '2026-10-30T00:00:00Z' in a
 print('ForeverAdvancement ready: 20 abilities\nTrinityCore (worldserver-daemon) ready...')
 if os.environ['MOCK_RULES']=='1':print('ForeverAdvancement custom rules: 1 canonical abilities; protocol=3; version=1.11.0')
else:raise SystemExit('unexpected docker request')
'''


class AdvancementDoctorTests(unittest.TestCase):
    def run_doctor(self,server='1.11.0',addon='1.11.0',legacy=False,custom=True,rules=True):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/subclass-doctor.sh',root/'scripts/subclass-doctor.sh')
            (root/'docker').write_text(DOCKER);(root/'docker').chmod(0o755)
            client=root/'client';addons=client/'Interface/AddOns';target=addons/'ForeverAscension';target.mkdir(parents=True)
            (target/'ForeverAscension.toc').write_text('## Version: '+addon+'\n')
            if custom:(target/'CustomRules.lua').touch()
            if legacy:(addons/'ForeverSubclass').mkdir()
            environment=os.environ.copy();environment.update(PATH=str(root)+os.pathsep+environment['PATH'],MOCK_SERVER_VERSION=server,MOCK_RULES='1' if rules else '0')
            return subprocess.run(['bash',str(root/'scripts/subclass-doctor.sh'),str(client)],capture_output=True,text=True,env=environment)

    def test_current_running_server_and_single_addon_pass(self):
        result=self.run_doctor()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('legacy AddOn absent',result.stdout)

    def test_old_server_old_addon_duplicate_addon_and_missing_rules_fail(self):
        for settings in ({'server':'1.9.0'},{'addon':'1.9.0'},{'legacy':True},{'custom':False},{'rules':False}):
            with self.subTest(settings=settings):
                result=self.run_doctor(**settings)
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
