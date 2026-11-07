import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('addon_channel_tool',ROOT/'scripts/update-addon-channel.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)

class AddonChannelTests(unittest.TestCase):
    def catalog(self): return json.loads((ROOT/'addons/channels.json').read_text())
    def test_initial_channels_are_real_complete_compatible_payloads(self):
        c=tool.validate(self.catalog())
        self.assertEqual(c['channels']['stable']['addons'],c['channels']['testing']['addons'])
        for m in c['channels']['stable']['addons']:
            folder=ROOT/m['sourcePath']
            toc=(folder/(m['name']+'.toc')).read_text()
            loaded={line.strip().replace('\\','/') for line in toc.splitlines() if line.strip() and not line.startswith('#')}
            self.assertEqual(loaded|{m['name']+'.toc'},{f['name'] for f in m['files']})
            for f in m['files']:
                body=(folder/f['name']).read_bytes()
                self.assertEqual(len(body),f['size']);self.assertEqual(hashlib.sha256(body).hexdigest(),f['sha256'])
    def test_unsafe_or_incompatible_sets_fail_validation(self):
        for kind in ('protocol','build','branch','path','duplicate','traversal','executable'):
            with self.subTest(kind=kind):
                c=self.catalog();r=c['channels']['testing'];m=r['addons'][0]
                if kind=='protocol':m['protocol']=4
                if kind=='build':r['clientBuild']=70707
                if kind=='branch':m['sourceCommit']='main'
                if kind=='path':m['sourcePath']='mods/../../WTF'
                if kind=='duplicate':r['addons'][1]=copy.deepcopy(m)
                if kind=='traversal':m['files'][0]['name']='../user.lua'
                if kind=='executable':m['files'][0]['name']='addon.exe'
                with self.assertRaises(ValueError):tool.validate(c)
    def test_pinning_reads_committed_payload_and_rejects_wrong_toc_version(self):
        with tempfile.TemporaryDirectory() as temp:
            repo=Path(temp)
            def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
            git('init');git('config','user.email','fixture@example.test');git('config','user.name','Fixture')
            name='ForeverEncyclopedia';folder=repo/tool.PATHS[name];folder.mkdir(parents=True)
            toc=folder/(name+'.toc');toc.write_text('## Version: 1.0-test\nMain.lua\n');(folder/'Main.lua').write_text('-- committed\n')
            git('add','.');git('commit','-m','fixture');commit=git('rev-parse','HEAD')
            (folder/'Main.lua').write_text('-- uncommitted local changes\n')
            m=tool.pin(repo,name,commit,'1.0-test')
            main=next(f for f in m['files'] if f['name']=='Main.lua')
            self.assertEqual(main['sha256'],hashlib.sha256(b'-- committed\n').hexdigest())
            with self.assertRaises(ValueError):tool.pin(repo,name,commit,'wrong-version')
    def test_whole_set_promotion_leaves_testing_and_source_files_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'channels.json';c=self.catalog();c['channels']['testing']['release']='testing-next';c['channels']['testing']['addons'][0]['version']='1.11.0-test'
            path.write_text(json.dumps(c));before=copy.deepcopy(c['channels']['testing'])
            subprocess.run(['python3',str(ROOT/'scripts/update-addon-channel.py'),'--catalog',str(path),'promote','--release','approved-next'],check=True,stdout=subprocess.DEVNULL)
            after=tool.validate(json.loads(path.read_text()))
            self.assertEqual(after['channels']['testing'],before)
            self.assertEqual(after['channels']['stable']['addons'],before['addons'])
    def test_refresh_ticket_occurs_after_downloads_and_uses_no_password_in_game_arguments(self):
        lib=(ROOT/'app/src-tauri/src/lib.rs').read_text().split('async fn start(app:')[1].split('/// macOS:')[0]
        self.assertLess(lib.index('addon::ensure('),lib.index('api.launcher_login('))
        self.assertIn('game_account_for_login(&session.email, &login)',lib)
        args=(ROOT/'app/src-tauri/src/game.rs').read_text().split('fn launch_args(')[1].split('#[cfg(test)]')[0]
        self.assertNotIn('login_ticket',args);self.assertNotIn('password',args)

if __name__=='__main__':unittest.main()
