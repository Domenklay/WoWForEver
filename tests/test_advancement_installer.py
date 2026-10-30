import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).parents[1]
FAKE_DOCKER=r'''#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:];text=' '.join(args)
with open(os.environ['FAKE_DOCKER_LOG'],'a') as f:
 f.write(text+'\n')
 if args[:3]==['compose','exec','-T'] and 'mysqldump' not in text:
  f.write(sys.stdin.read()+'\n')
if args[:2]==['image','inspect']:
 print(os.environ.get('FAKE_IMAGE_VERSION','1.11.0'))
elif args[:2]==['inspect','--format']:
 print('2026-10-28T00:00:00Z')
elif args[:2]==['compose','ps']:
 print('mysql\nworldserver\nbnetserver\nweb' if '--services' in args else 'fixture-container')
elif args[:2]==['compose','logs']:
 print('worldserver-daemon fixture ready\nForeverAdvancement ready: 2 compatible Ascension abilities; 8 slots\nForeverAdvancement custom rules: 1 canonical abilities; protocol=3; version=1.11.0')
elif 'mysqldump' in text:
 if os.environ.get('FAKE_FAILURE')=='backup' and '--databases' in text:sys.exit(1)
 print('-- fixture SQL dump')
elif args[:2]==['compose','up'] and os.environ.get('FAKE_FAILURE')=='startup':
 flag=Path(os.environ['FAKE_DOCKER_LOG']+'.failed')
 if not flag.exists():flag.touch();sys.exit(1)
'''


class AdvancementInstallerTests(unittest.TestCase):
    def run_install(self,root,failure='',action='install',image_version='1.11.0'):
        scripts=root/'scripts';scripts.mkdir()
        for name in ['advancement-mod.sh','install-advancement-addon.py','subclass-log-config.py']:
            shutil.copy2(ROOT/'scripts'/name,scripts/name)
        (scripts/'preserve-container-image.py').write_text('import sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index("--backup")+1]);(p/"old-image.txt").write_text("previous-image\\n")\n')
        module=root/'mods/forever-advancement';(module/'sql').mkdir(parents=True)
        for name in ['characters.sql','world.sql']:shutil.copy2(ROOT/'mods/forever-advancement/sql'/name,module/'sql'/name)
        addon=module/'addon/ForeverAscension';addon.mkdir(parents=True);(addon/'ForeverAscension.toc').write_text('## Title: Fixture\n')
        client=root/'client';client.mkdir();(client/'WowB.exe').touch();old=client/'Interface/AddOns/ForeverSubclass';old.mkdir(parents=True);(old/'user.lua').write_text('old user UI')
        (root/'.env').write_text('SUBCLASS_ENABLED=1\nUNRELATED=preserved\n')
        fake=root/'bin';fake.mkdir();(fake/'docker').write_text(FAKE_DOCKER);(fake/'docker').chmod(0o755)
        (fake/'git').write_text('#!/bin/sh\necho fixture-source-commit\n');(fake/'git').chmod(0o755)
        env=os.environ.copy();env.update(PATH=str(fake)+os.pathsep+env['PATH'],FAKE_DOCKER_LOG=str(root/'docker.log'),FAKE_FAILURE=failure,FAKE_IMAGE_VERSION=image_version)
        result=subprocess.run(['bash',str(scripts/'advancement-mod.sh'),action,str(client)],env=env,capture_output=True,text=True,timeout=20)
        return result,client,(root/'docker.log').read_text() if (root/'docker.log').exists() else ''

    def test_successful_migration_creates_backups_and_replaces_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,client,log=self.run_install(root)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((client/'Interface/AddOns/ForeverSubclass').exists())
            self.assertTrue((client/'Interface/AddOns/ForeverAscension').is_dir())
            self.assertIn('ADVANCEMENT_ENABLED=1',(root/'.env').read_text())
            backup=next((root/'backups').glob('advancement-*'))
            self.assertTrue((backup/'databases.sql.gz').is_file())
            self.assertEqual((backup/'addon/ForeverSubclass/user.lua').read_text(),'old user UI')
            self.assertLess(log.index('mysqldump'),log.index('CREATE TABLE IF NOT EXISTS'))
            self.assertNotIn('DROP TABLE',log)
            self.assertIn('spell_forever_custom_mana_shield',log)
            self.assertIn('aura_forever_custom_mana_shield',log)

    def test_old_image_is_rejected_before_stopping_services_or_replacing_addons(self):
        with tempfile.TemporaryDirectory() as temp:
            result,client,log=self.run_install(Path(temp),image_version='1.9.0')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Built image is stale',result.stdout)
            self.assertNotIn('compose stop',log)
            self.assertTrue((client/'Interface/AddOns/ForeverSubclass/user.lua').is_file())

    def test_addon_only_update_and_rollback_never_invoke_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,client,log=self.run_install(root,action='addon')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(log,'')
            self.assertTrue((client/'Interface/AddOns/ForeverAscension').is_dir())
            self.assertEqual((root/'.env').read_text(),'SUBCLASS_ENABLED=1\nUNRELATED=preserved\n')
            backup=next((root/'backups').glob('advancement-ui-*'))
            env=os.environ.copy();env.update(PATH=str(root/'bin')+os.pathsep+env['PATH'],FAKE_DOCKER_LOG=str(root/'docker.log'))
            result=subprocess.run(['bash',str(root/'scripts/advancement-mod.sh'),'rollback',str(backup)],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((client/'Interface/AddOns/ForeverSubclass/user.lua').read_text(),'old user UI')
            self.assertFalse((client/'Interface/AddOns/ForeverAscension').exists())
            self.assertFalse((root/'docker.log').exists())

    def test_backup_failure_does_not_remove_existing_power_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,client,log=self.run_install(root,'backup')
            self.assertNotEqual(result.returncode,0)
            self.assertTrue((client/'Interface/AddOns/ForeverSubclass/user.lua').is_file())
            self.assertNotIn('DELETE FROM hotfix_data',log)
            self.assertEqual((root/'.env').read_text(),'SUBCLASS_ENABLED=1\nUNRELATED=preserved\n')

    def test_startup_failure_restores_original_addon_and_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,client,log=self.run_install(root,'startup')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((client/'Interface/AddOns/ForeverSubclass/user.lua').read_text(),'old user UI')
            self.assertFalse((client/'Interface/AddOns/ForeverAscension').exists())
            self.assertEqual((root/'.env').read_text(),'SUBCLASS_ENABLED=1\nUNRELATED=preserved\n')
            self.assertIn('previous-image forever-trinitycore:latest',log)


if __name__=='__main__':unittest.main()
