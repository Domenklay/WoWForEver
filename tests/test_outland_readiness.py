import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('outland_readiness',ROOT/'scripts/outland-readiness.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class OutlandReadinessTests(unittest.TestCase):
    def client(self,root):
        root.mkdir();(root/'.build.info').write_text('owned test');(root/'Data').mkdir()
        return root

    def test_negative_name_lookup_and_missing_map_never_claim_playability(self):
        calls=[]
        def run(cmd,**kw):
            calls.append((cmd,kw))
            if 'inspect' in cmd:out='owned-image-id'
            elif 'run' in cmd:out=json.dumps({'storage_opened':True,'negative_name_lookup_proves_absence':False,'files':[{'path':'test','status':'OPEN_FAILED','error':2}]})
            elif 'web' in cmd:out=json.dumps({'lookup':'No maps found!'})
            else:out='=== maps: Map 530 files (at most 30) ==='
            return subprocess.CompletedProcess(cmd,0,out,'')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=self.client(root/'client')
            path=module.collect(client,root/'reports',run)
            report=json.loads(path.read_text())
            self.assertFalse(report['playable_map_confirmed'])
            self.assertFalse(report['negative_name_lookup_proves_absence'])
            docker=next(cmd for cmd,_ in calls if 'run' in cmd)
            self.assertIn('--read-only',docker);self.assertIn('none',docker)
            self.assertIn(f'type=bind,src={client},dst=/wow,readonly',docker)
            self.assertEqual(sorted(x.name for x in client.iterdir()),['.build.info','Data'])
            self.assertEqual(report['checks']['runtime']['result']['lookup'],'No maps found!')

    def test_missing_docker_still_writes_report(self):
        def run(*a,**kw):raise FileNotFoundError('docker missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=self.client(root/'client')
            report=json.loads(module.collect(client,root/'reports',run).read_text())
            self.assertIn('error',report['checks']['runtime'])
            self.assertIn('error',report['checks']['client'])

    def test_refuses_output_inside_game_data_and_reusing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=self.client(root/'client')
            for out in (client/'Data'/'report',client/'_classic_beta_'/'report',client):
                with self.assertRaises(ValueError):module.collect(client,out)
            out=root/'reports';out.mkdir()
            with self.assertRaises(FileExistsError):module.collect(client,out)
