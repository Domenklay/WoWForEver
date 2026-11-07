import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('services_trial_tests', ROOT / 'scripts/test-baseline-services.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)
IMAGE = 'sha256:' + 'a' * 64
NONCE = '012345abcdef'


def manifest():
    return dict(root='/home/test/server', core='b4e7b940593f6402a822d4fbcdf31331d16f73b6',
                client_build=70658, database_snapshot={'counts':['0','0','0'],'schema_sha256':'b'*64},
                gameplay={'source_sha256':'c'*64,'encyclopedia':'0.9.8-v2.1-smartai-abilities','scaling':'0.2.0'},
                images={s:{'id':IMAGE} for s in trial.base.SERVICES})


class BaselineServiceTests(unittest.TestCase):
    def test_archive_links_absolute_traversal_and_duplicate_members_cannot_escape(self):
        for name, link, repeat in [('fs/../../escape',False,False),('/fs/root',False,False),
                                   ('fs/x',True,False),('fs/x',False,True),('fs//x',False,False)]:
            with self.subTest(name=name,link=link,repeat=repeat), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                archive = folder / 'files.tar.gz'
                with tarfile.open(archive,'w:gz') as stream:
                    item = tarfile.TarInfo(name)
                    if link:
                        item.type=tarfile.SYMTYPE; item.linkname='/etc/passwd'
                        stream.addfile(item)
                    else:
                        item.size=1
                        stream.addfile(item,io.BytesIO(b'x'))
                        if repeat: stream.addfile(item,io.BytesIO(b'x'))
                work=folder/'trial'; work.mkdir()
                with self.assertRaises(ValueError):
                    trial.unpack(archive,work)
                self.assertFalse((folder/'escape').exists())

    def test_restored_sources_are_relocated_and_never_resolve_to_saved_live_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            restored=root/'fs/home/test/data'; restored.mkdir(parents=True)
            self.assertEqual(trial.relocated(root,'/home/test/data'),restored)
            for path in ('/home/test/../data','relative/path','//home/test/data'):
                with self.assertRaises(ValueError): trial.relocated(root,path)
            restored.rmdir(); restored.symlink_to('/etc')
            with self.assertRaises(ValueError): trial.relocated(root,'/home/test/data')

    def test_cleanup_checks_all_labels_before_removing_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            t=trial.ServicesTrial(manifest(),Path(temp),NONCE)
            t.allocated=True
            def owned(kind,name,role):
                if kind=='network': raise ValueError('foreign network')
                return {'Name':name}
            with patch.object(t,'owned',side_effect=owned), patch.object(trial.sql,'docker') as docker, \
                 patch.object(t.db,'cleanup') as cleanup:
                with self.assertRaisesRegex(ValueError,'foreign network'): t.cleanup()
                docker.assert_not_called(); cleanup.assert_not_called()

    def test_failed_preflight_does_not_delete_existing_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            t=trial.ServicesTrial(manifest(),Path(temp),NONCE)
            with patch.object(trial.sql,'docker') as docker, patch.object(t.db,'cleanup') as cleanup:
                t.cleanup()
                docker.assert_not_called(); cleanup.assert_called_once_with()

    def test_create_uses_only_internal_network_exact_image_readonly_restored_binds_and_no_ports(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            t=trial.ServicesTrial(manifest(),folder,NONCE)
            t.data=folder/'data'; t.certs=folder/'certs'; t.entry=folder/'entry.py'; t.ca=folder/'ca.crt'
            t.envs={s:folder/(s+'.env') for s in trial.SERVICES}
            with patch.object(trial.sql,'docker',return_value=''), patch.object(t,'check_container'):
                for service in trial.SERVICES: t.create(service)
            with patch.object(trial.sql,'docker',return_value='') as docker, patch.object(t,'check_container'):
                t.create('worldserver')
                args=docker.call_args_list[0].args
                self.assertIn('--pull=never',args); self.assertIn('--restart=no',args)
                self.assertIn(t.network,args); self.assertEqual(args[-2:],(IMAGE,'worldserver'))
                self.assertNotIn('-p',args); self.assertNotIn('--publish',args)
                mounts=[args[i+1] for i,v in enumerate(args) if v=='--mount']
                self.assertIn(trial.bind(t.data,trial.DATA),mounts)
                self.assertNotIn('/home/test/server',' '.join(args))

    def test_container_inspection_rejects_published_port_other_network_and_live_bind(self):
        with tempfile.TemporaryDirectory() as temp:
            t=trial.ServicesTrial(manifest(),Path(temp),NONCE)
            t.expected['worldserver']=[]
            def item():
                return {'Image':IMAGE,'HostConfig':{'NetworkMode':t.network,'RestartPolicy':{'Name':'no'}},
                        'NetworkSettings':{'Networks':{t.network:{}}},'Mounts':[]}
            for failure in ('port','network','livebind'):
                v=item()
                if failure=='port': v['HostConfig']['PortBindings']={'8085/tcp':[{'HostPort':'8085'}]}
                elif failure=='network': v['NetworkSettings']['Networks']['working-clean']={}
                else: v['Mounts']=[{'Type':'bind','Source':'/home/test/server/data','Destination':trial.DATA,'RW':False}]
                with self.subTest(failure=failure), patch.object(t,'owned',return_value=v):
                    with self.assertRaises(ValueError): t.check_container('worldserver')

    def test_cleanup_report_cannot_point_to_live_root(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'report.json'
            path.write_text(json.dumps({'format':trial.FORMAT,'nonce':NONCE,'images':manifest()['images']}))
            with patch.object(trial.sql,'docker') as docker:
                with self.assertRaises(ValueError): trial.cleanup_report(path)
                docker.assert_not_called()

    def test_failed_school_audit_ends_trial_before_sleeping_and_preserves_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            t=trial.ServicesTrial(manifest(),Path(temp),NONCE,candidate=IMAGE)
            t.advancement_version='1.14.1'
            item={'Id':'trial-world','State':{'Running':True,'StartedAt':'2026-11-07T00:00:00Z'}}
            line='ForeverAdvancement player school audit failed: class 1 has 1 schools, expected 3'
            report=dict(lines=[line],settings={},serverLogStatus='current-process-file')
            with patch.object(t,'check_container',return_value=item), patch.object(trial.module_readiness,'snapshot',return_value=report), patch.object(trial.time,'sleep') as pause:
                with self.assertRaisesRegex(trial.sql.TrialFailure,'class 1 has 1 schools'):
                    t.ready(600)
                pause.assert_not_called()

    def test_saved_credentials_are_replaced_and_only_archived_sources_mounted(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            t=trial.ServicesTrial(manifest(),folder,NONCE)
            root=folder/'fs/home/test/server'; root.mkdir(parents=True)
            certs=folder/'fs/home/test/certs'; (certs/'ca').mkdir(parents=True)
            for name in ('forever.cert.pem','forever.key.pem','ca/forever_root_ca.crt'):
                (certs/name).write_text('fixture')
            (root/'data').mkdir(); (root/'entry.py').write_text('fixture')
            worldenv={k:v for k,v in [('FOREVER_ADVANCEMENT_ENABLED','1'),('FOREVER_ENCYCLOPEDIA_ENABLED','1'),
                ('FOREVER_SCALING_ENABLED','1'),('FOREVER_SCALING_DAMAGE_GUARD','1'),
                ('FOREVER_SCALING_MIN_OFFSET','-9'),('FOREVER_SCALING_CREATURE_MAX_LEVEL','70')]}
            model={'services':{s:{'volumes':[],'environment':{}} for s in trial.SERVICES}}
            for service,target,source in [('worldserver',trial.DATA,'/home/test/server/data'),
                ('bnetserver',trial.CERTS,'/home/test/certs'),('bnetserver',trial.ENTRY,'/home/test/server/entry.py'),
                ('web',trial.CA,'/home/test/certs/ca/forever_root_ca.crt')]:
                model['services'][service]['volumes'].append({'type':'bind','source':source,'target':target})
            model['services']['worldserver']['environment']=worldenv
            model['services']['web']['environment']={'DB_PASSWORD':'oldpassword','GITHUB_TOKEN':'secret'}
            (root/'compose.private.json').write_text(json.dumps(model))
            state=dict(manifest(),client={'exe_build':70658},credentials={'database':'oldpassword'})
            (root/'state.json').write_text(json.dumps(state))
            t.prepare_sources()
            for service in trial.SERVICES:
                env=t.envs[service].read_text()
                self.assertIn('DB_PASSWORD='+t.password,env)
                self.assertNotIn('oldpassword',env); self.assertNotIn('GITHUB_TOKEN',env)
            self.assertEqual(t.data,root/'data')
            self.assertEqual(t.ca.stat().st_mode&0o777,0o644)

    def test_mysql_detaches_none_before_joining_only_the_new_private_network(self):
        with tempfile.TemporaryDirectory() as temp:
            t=trial.ServicesTrial(manifest(),Path(temp),NONCE)
            before={'NetworkSettings':{'Networks':{'none':{}}},'HostConfig':{}}
            after={'NetworkSettings':{'Networks':{t.network:{}}},'HostConfig':{}}
            with patch.object(t.db,'sql'), patch.object(t.db,'owned',side_effect=[before,after]), \
                 patch.object(t,'owned',return_value={'Internal':True,'Driver':'bridge'}), \
                 patch.object(trial.sql,'docker') as docker:
                t.attach_database()
                calls=[c.args for c in docker.call_args_list]
                detach=('network','disconnect','none',t.db.name)
                attach=('network','connect','--alias','mysql',t.network,t.db.name)
                self.assertLess(calls.index(detach),calls.index(attach))
                self.assertNotIn('working-clean',' '.join(str(c) for c in calls))

    def test_network_missing_is_distinguished_from_inspection_permission_failure(self):
        from types import SimpleNamespace
        for stderr,missing in [('Error response from daemon: network trial-name not found',True),
                               ('permission denied',False)]:
            result=SimpleNamespace(returncode=1,stdout='',stderr=stderr)
            with patch.object(trial.sql.subprocess,'run',return_value=result):
                if missing:
                    self.assertIsNone(trial.sql.docker('network','inspect','trial-name',missing=True))
                else:
                    with self.assertRaises(trial.sql.DockerFailure):
                        trial.sql.docker('network','inspect','trial-name',missing=True)

    def test_incomplete_or_wrong_build_manifest_fails_before_start(self):
        for change in ({'client_build':70707},{'images':{}},{'core':'unknown'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                trial.checked_manifest(dict(manifest(),**change))


if __name__=='__main__': unittest.main()
