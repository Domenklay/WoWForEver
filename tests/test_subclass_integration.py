import ctypes
import ctypes.util
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
MODULE=ROOT/'mods/forever-subclass'

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

installer=load('addon_install','install-subclass-addon.py')
injector=load('inject_subclass','inject-subclass.py')

class SubclassIntegrationTests(unittest.TestCase):
    def test_source_injection_idempotent_and_does_not_copy_demo_main(self):
        with tempfile.TemporaryDirectory() as temp:
            core=Path(temp);folder=core/'src/server/scripts/Custom';folder.mkdir(parents=True)
            loader=folder/'custom_script_loader.cpp'
            loader.write_text('// Original notice\nvoid AddClassicScripts();\nvoid AddCustomScripts()\n{\n    AddClassicScripts();\n}\n')
            injector.inject(core,MODULE);first=loader.read_text();injector.inject(core,MODULE)
            self.assertEqual(loader.read_text(),first)
            self.assertEqual(first.count('    AddSC_forever_subclass();'),1)
            self.assertIn('    AddClassicScripts();',first)
            self.assertTrue(first.startswith('// Original notice'))
            cpp=sorted(p.name for p in (folder/'ForeverSubclass').rglob('*.cpp'))
            self.assertEqual(cpp,['ForeverSubclass.cpp','SubclassSystem.cpp'])
            injected=(folder/'ForeverSubclass/forever_subclass/SubclassSystem.hpp').read_text()
            vendored=(MODULE/'vendor/include/forever_subclass/SubclassSystem.hpp').read_text()
            self.assertIn('subclassUnlockPrimaryLevel = 10;',injected)
            self.assertIn('subclassUnlockPrimaryLevel = 40;',vendored)
            server=(folder/'ForeverSubclass/ForeverSubclass.cpp').read_text()
            self.assertIn('#include "ChatCommand.h"',server)
            self.assertIn('class ForeverSubclassCommandScript final : public CommandScript',server)
            self.assertIn('{ "fsub", HandleFsubCommand, rbac::RBAC_PERM_COMMAND_COMMANDS, Console::No }',server)
            self.assertIn('ForeverSubclass::Request(handler->GetSession()->GetPlayer(), text);',server)
            self.assertIn('auto& e=State(p);Snapshot(p,e);',server)
            self.assertEqual(server.count('new ForeverSubclassCommandScript();'),1)

    def test_addon_install_and_restore_preserve_game_and_previous_addon(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'_classic_beta_';client.mkdir()
            (client/'WowB.exe').write_bytes(b'untouched executable fixture')
            (root/'Data').mkdir();(root/'Data/sentinel').write_bytes(b'untouched CASC fixture')
            old=client/'Interface/AddOns/ForeverSubclass';old.mkdir(parents=True)
            (old/'previous.lua').write_text('-- previous user addon\n')
            backup=root/'backup';target=installer.install(client,backup)
            for name in ['ForeverSubclass.lua','ForeverSubclassDirectTransport.lua','ForeverSubclassTalents.lua',
                         'ForeverSubclassResourceHUD.lua','ForeverSubclassCastFeedback.lua',
                         'ForeverSubclassSpellBook.lua','ForeverSubclassActionBar.lua','ForeverSubclassDebug.lua']:
                self.assertTrue((target/name).exists(),name)
            toc=(target/'ForeverSubclass.toc').read_text()
            for name in ['ForeverSubclassTalents.lua','ForeverSubclassDirectTransport.lua','ForeverSubclassResourceHUD.lua',
                         'ForeverSubclassCastFeedback.lua','ForeverSubclassSpellBook.lua','ForeverSubclassActionBar.lua']:
                self.assertIn(name,toc)
            for stale in ['ForeverSubclassTalentTab.lua','ForeverSubclassTalentCompat.lua','ForeverSubclassPanelV2.lua',
                          'ForeverSubclassLegacySuppress.lua','ForeverSubclassInteractiveFix.lua','ForeverSubclassCommandTransport.lua']:
                self.assertNotIn(stale,toc)
            self.assertEqual((backup/'previous-addon/previous.lua').read_text(),'-- previous user addon\n')
            with self.assertRaises(FileExistsError):installer.install(client,backup)
            installer.restore(backup)
            self.assertEqual(sorted(p.name for p in target.iterdir()),['previous.lua'])
            self.assertEqual((client/'WowB.exe').read_bytes(),b'untouched executable fixture')
            self.assertEqual((root/'Data/sentinel').read_bytes(),b'untouched CASC fixture')

    def test_consolidated_talents_owns_visibility_and_matches_markup_labels(self):
        ui=(MODULE/'addon/ForeverSubclass/ForeverSubclassTalents.lua').read_text()
        self.assertIn('PlayerSpellsFrame.TalentsFrame',ui)
        self.assertIn('ForeverSubclassTalentTab',ui)
        self.assertIn('ForeverSubclassTalentPanel',ui)
        self.assertIn('text:find("Основное"',ui)
        self.assertIn('OnMouseDown',ui)
        self.assertIn('customActive=false',ui)
        self.assertNotIn('ForeverSubclassTalentClickProxy',ui)

    def test_subclass_spellbook_is_addon_owned_and_server_driven(self):
        spellbook=(MODULE/'addon/ForeverSubclass/ForeverSubclassSpellBook.lua').read_text()
        self.assertIn('PlayerSpellsFrame.SpellBookFrame',spellbook)
        self.assertIn('ForeverSubclassSpellBookTab',spellbook)
        self.assertIn('ForeverSubclassSpellBookPanel',spellbook)
        self.assertIn('send("cast "..self.spell.id)',spellbook)
        self.assertIn('if sp.selected then',spellbook)
        self.assertNotIn('LearnSpell',spellbook)

    def test_subclass_action_bar_has_real_spell_showtooltip(self):
        action=(MODULE/'addon/ForeverSubclass/ForeverSubclassActionBar.lua').read_text()
        self.assertIn('CreateMacro',action)
        self.assertIn('PickupMacro',action)
        self.assertIn('#showtooltip ',action)
        self.assertIn('INV_MISC_QUESTIONMARK',action)
        self.assertIn('/fsubcast',action)
        self.assertIn('RegisterForDrag',action)
        self.assertIn('InCombatLockdown',action)

    def test_secondary_resource_hud_predicts_then_resyncs(self):
        hud=(MODULE/'addon/ForeverSubclass/ForeverSubclassResourceHUD.lua').read_text()
        feedback=(MODULE/'addon/ForeverSubclass/ForeverSubclassCastFeedback.lua').read_text()
        self.assertIn('ForeverSubclassResourceHUD',hud)
        self.assertIn('kind=="POWER"',hud)
        self.assertIn('ForeverSubclassResourcePredictSpend',hud)
        self.assertIn('kind=="SPELL"',hud)
        self.assertIn('UnitPowerType',hud)
        self.assertIn('ForeverSubclassResourcePredictSpend',feedback)
        self.assertIn('base("status",true)',feedback)

    def test_direct_transport_uses_server_endpoint_without_ui_rewiring(self):
        transport=(MODULE/'addon/ForeverSubclass/ForeverSubclassDirectTransport.lua').read_text()
        self.assertIn('SERVER_TARGET="SERVER"',transport)
        self.assertIn('C_ChatInfo.SendAddonMessage',transport)
        self.assertIn('"WHISPER",SERVER_TARGET',transport)
        self.assertIn('learn%s+%d+',transport)
        self.assertIn('active%s+%d+',transport)
        self.assertIn('xp%s+%d+',transport)
        self.assertNotIn('wireButton',transport)
        self.assertNotIn('SetScript("OnClick"',transport)

    def test_core_patch_routes_fsc1_before_player_lookup(self):
        patch=(ROOT/'docker/patches/0004-forever-subclass-server-addon-endpoint.patch').read_text()
        self.assertIn('prefix == "FSC1"',patch)
        self.assertIn('OnPlayerAddonMessageSent(sender, type, prefix, text, sender)',patch)
        self.assertLess(patch.index('prefix == "FSC1"'),patch.index('switch (type)'))

    def test_new_addon_uninstall_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';client.mkdir();(client/'WowB.exe').write_bytes(b'exe')
            target=installer.install(client,root/'backup');installer.restore(root/'backup')
            self.assertFalse(target.exists())
            outside=root/'outside';outside.mkdir();(outside/'keep').write_text('keep')
            target.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):installer.install(client,root/'second')
            self.assertEqual((outside/'keep').read_text(),'keep')

    @unittest.skipUnless(shutil.which('g++'),'g++ required')
    def test_original_cpp_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            binary=Path(temp)/'test-subclass'
            subprocess.run(['g++','-std=c++17','-O2','-I',str(MODULE/'vendor/include'),
                            str(MODULE/'vendor/src/SubclassSystem.cpp'),str(MODULE/'vendor/tests/test_subclass.cpp'),
                            '-o',str(binary)],check=True,capture_output=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
            self.assertIn('All subclass',result.stdout)

    @unittest.skipUnless(ctypes.util.find_library('lua5.4'),'Lua 5.4 runtime required for API-double test')
    def test_addon_transport_is_server_authoritative(self):
        lua=ctypes.CDLL(ctypes.util.find_library('lua5.4'))
        lua.luaL_newstate.restype=ctypes.c_void_p;lua.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lua.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lua.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ssize_t,ctypes.c_void_p]
        lua.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];lua.lua_tolstring.restype=ctypes.c_char_p
        lua.lua_close.argtypes=[ctypes.c_void_p]
        state=lua.luaL_newstate();lua.luaL_openlibs(state)
        try:
            text='argAddon='+json.dumps(str(MODULE/'addon/ForeverSubclass/ForeverSubclass.lua'))+'\ndofile('+json.dumps(str(ROOT/'tests/fixtures/subclass-addon.lua'))+')'
            status=lua.luaL_loadstring(state,text.encode())
            if not status:status=lua.lua_pcallk(state,0,0,0,0,None)
            if status:self.fail(lua.lua_tolstring(state,-1,None).decode())
        finally:lua.lua_close(state)

if __name__=='__main__':unittest.main()
