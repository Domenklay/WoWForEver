"""Real Docker transport/TLS/MySQL orchestration test with generated service fixtures.

The synthetic TCP servers do not emulate TrinityCore gameplay. Actual restored
TrinityCore startup must be verified on the user's private baseline separately.
"""
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('services_integration',ROOT/'scripts/test-baseline-services.py')
service=importlib.util.module_from_spec(spec); spec.loader.exec_module(service)

FIXTURE=r'''
import http.server,json,os,socket,ssl,sys,threading,time
from pathlib import Path
role=sys.argv[1] if len(sys.argv)>1 else 'web'
def tcp(port):
    s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',port)); s.listen()
    while True:
        c,_=s.accept(); c.close()
if role=='worldserver':
    if Path('/opt/trinitycore/data/fail').exists(): sys.exit(17)
    with socket.create_connection(('mysql',3306),5): pass
    log=Path('/opt/trinitycore/logs/Server.log')
    log.write_text('ForeverAdvancement ready:\nForeverAdvancement custom rules: 1 canonical abilities; protocol=3; version=1.11.0\nForeverEncyclopedia ready:\nForeverScaling ready: personal-virtual-v0.2 (enabled=true\n')
    config=Path('/opt/trinitycore/etc/worldserver.conf'); config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text('ForeverAdvancement.Enable = 1\nForeverEncyclopedia.Enable = 1\nLogger.scripts = 3,Console Server\nLogsDir = "/opt/trinitycore/logs"\nAppender.Server = 2,3,0,Server.log,w\n')
    tcp(8085)
elif role=='bnetserver':
    threading.Thread(target=tcp,args=(1119,),daemon=True).start()
    s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',8081)); s.listen()
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain('/opt/trinitycore/certs/forever.cert.pem','/opt/trinitycore/certs/forever.key.pem')
    while True:
        c,_=s.accept()
        try:
            with ctx.wrap_socket(c,server_side=True): pass
        except ssl.SSLError: c.close()
else:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/healthz': body=json.dumps({'ok':True}).encode()
            elif self.path=='/api/status':
                with socket.create_connection(('worldserver',8085),5): pass
                body=json.dumps({'online':True,'players':0}).encode()
            elif self.path=='/forever_root_ca.crt': body=Path('/certs/ca/forever_root_ca.crt').read_bytes()
            else: self.send_error(404); return
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass
    http.server.HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''


@unittest.skipUnless(os.environ.get('FOREVER_SERVICES_INTEGRATION')=='1','Real service fixture test is opt-in')
class RestoredServicesIntegration(unittest.TestCase):
    def test_saved_files_database_internal_services_tls_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='forever-service-fixture-') as temp:
            root=Path(temp); build=root/'build'; build.mkdir()
            (build/'fixture.py').write_text(FIXTURE)
            (build/'Dockerfile').write_text('FROM python:3.12-slim\nCOPY fixture.py /fixture.py\n'
                'ENTRYPOINT ["python3","/fixture.py"]\n'
                'LABEL org.wowforever.core="b4e7b940593f6402a822d4fbcdf31331d16f73b6" '
                'org.wowforever.gameplay.source="'+'c'*64+'" org.wowforever.advancement="1.11.0" '
                'org.wowforever.encyclopedia="0.9.8-v2.1-smartai-abilities" org.wowforever.scaling="0.2.0"\n')
            # No persistent public tag is allocated for the generated service image.
            service.sql.docker('build','--quiet','--iidfile',str(build/'image-id'),str(build))
            runtime=(build/'image-id').read_text().strip()
            mysql=json.loads(service.sql.docker('image','inspect','mysql:8.0'))[0]['Id']
            source_dir=root/'source'; source_dir.mkdir()
            source=service.sql.MysqlTrial(mysql,source_dir)
            try:
                source.start()
                source.sql(''.join('CREATE DATABASE `'+name+'`;\n' for name in service.sql.DATABASES)
                    +'CREATE TABLE auth.battlenet_accounts(id INT); INSERT INTO auth.battlenet_accounts VALUES(1);\n'
                    +'CREATE TABLE auth.account(id INT); INSERT INTO auth.account VALUES(1);\n'
                    +'CREATE TABLE auth.realmlist(id INT,gamebuild INT,contentSetId INT,flag INT);\n'
                    +'INSERT INTO auth.realmlist VALUES(70,70658,137,0);\n'
                    +'CREATE TABLE characters.characters(guid INT,online INT); INSERT INTO characters.characters VALUES(1,0);\n'
                    +''.join('CREATE TABLE characters.`'+name+'` (id INT); INSERT INTO characters.`'+name+'` VALUES(1);\n'
                             for name in service.sql.MODULE_TABLES))
                snapshot=service.sql.snapshot(source)
                backup=root/'backup'; backup.mkdir()
                cmd=['docker','exec',source.name,'sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot '
                    '--single-transaction --set-gtid-purged=OFF --databases auth world characters hotfixes']
                with gzip.open(backup/'databases-current.sql.gz','wb') as stream:
                    stream.write(subprocess.check_output(cmd,stderr=subprocess.DEVNULL))
                certs=root/'certs'; certs.mkdir()
                subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=trinity.actual.battle.net','-addext','subjectAltName=DNS:trinity.actual.battle.net',
                    '-keyout',str(certs/'key.pem'),'-out',str(certs/'cert.pem')],check=True,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                gameplay={'source_sha256':'c'*64,'encyclopedia':'0.9.8-v2.1-smartai-abilities','scaling':'0.2.0'}
                env=dict(FOREVER_ADVANCEMENT_ENABLED='1',FOREVER_ENCYCLOPEDIA_ENABLED='1',FOREVER_SCALING_ENABLED='1',
                    FOREVER_SCALING_DAMAGE_GUARD='1',FOREVER_SCALING_MIN_OFFSET='-9',FOREVER_SCALING_CREATURE_MAX_LEVEL='70')
                model={'services':{s:{'volumes':[],'environment':{}} for s in service.SERVICES}}
                for s,target,path in [('worldserver',service.DATA,'/fixture/server/data'),
                    ('bnetserver',service.CERTS,'/fixture/certs'),('bnetserver',service.ENTRY,'/fixture/entry.py'),
                    ('web',service.CA,'/fixture/certs/ca/forever_root_ca.crt')]:
                    model['services'][s]['volumes'].append({'type':'bind','source':path,'target':target})
                model['services']['worldserver']['environment']=env
                state={'core':'b4e7b940593f6402a822d4fbcdf31331d16f73b6','client':{'exe_build':70658},'gameplay':gameplay}
                files={'fs/fixture/server/state.json':json.dumps(state).encode(),
                    'fs/fixture/server/compose.private.json':json.dumps(model).encode(),
                    'fs/fixture/server/data/fixture':b'synthetic data',
                    'fs/fixture/entry.py':b'# generated entrypoint bind fixture',
                    'fs/fixture/certs/forever.cert.pem':(certs/'cert.pem').read_bytes(),
                    'fs/fixture/certs/forever.key.pem':(certs/'key.pem').read_bytes(),
                    'fs/fixture/certs/ca/forever_root_ca.crt':(certs/'cert.pem').read_bytes()}
                def pack():
                    with tarfile.open(backup/'server-files.tar.gz','w:gz') as archive:
                        for name,body in files.items():
                            item=tarfile.TarInfo(name); item.size=len(body); archive.addfile(item,io.BytesIO(body))
                pack()
                service.sql.docker('image','save','-o',str(backup/'docker-images.tar'),mysql,runtime)
                (backup/'RESTORE.ru.txt').write_text('Generated fixture, not a user server backup.')
                artifacts=['databases-current.sql.gz','server-files.tar.gz','docker-images.tar','RESTORE.ru.txt']
                m=dict(format=service.base.FORMAT,complete=True,root='/fixture/server',core=state['core'],client_build=70658,
                    gameplay=gameplay,database_snapshot=snapshot,
                    images={s:{'id':mysql if s=='mysql' else runtime} for s in service.base.SERVICES})
                def write_manifest():
                    m['artifacts']={name:service.base.artifact(backup/name) for name in artifacts}
                    (backup/'manifest.json').write_text(json.dumps(m))
                write_manifest()
                reports=root/'trials'
                result=service.run_check(backup,reports,60)
                self.assertTrue(result['services_verified']); self.assertTrue(result['cleanup_verified'])
                self.assertTrue(result['service_probes']['tls_verified'])
                self.assertFalse(result['client_login_verified']); self.assertFalse(result['full_server_restore_verified'])
                self.assertEqual(service.sql.snapshot(source),snapshot)
                self.assertTrue(source.owned('container')['State']['Running'])
                self.assertFalse(list(reports.glob('*/fs')))
                previous=set(reports.glob('*/report.json'))
                files['fs/fixture/server/data/fail']=b'exit during startup'; pack(); write_manifest()
                with self.assertRaises(service.sql.TrialFailure): service.run_check(backup,reports,60)
                failed_path,=set(reports.glob('*/report.json'))-previous
                failed=json.loads(failed_path.read_text())
                self.assertTrue(failed['cleanup_verified']); self.assertFalse(failed['services_verified'])
                self.assertEqual(service.sql.snapshot(source),snapshot)
                for r in (result,failed):
                    name=service.PREFIX+r['nonce']
                    self.assertIsNone(service.sql.docker('network','inspect',name+'-net',missing=True))
                    for s in service.SERVICES:
                        self.assertIsNone(service.sql.docker('container','inspect',name+'-'+s,missing=True))
            finally:
                source.cleanup()
                service.sql.docker('image','rm',runtime)


if __name__=='__main__': unittest.main()
