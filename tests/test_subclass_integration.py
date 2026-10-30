import ctypes
import ctypes.util
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
MODULE=ROOT/'mods/forever-subclass'
ADDON=MODULE/'addon/ForeverSubclass'

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
            cpp=sorted(p.name for p in (folder/'ForeverSubclass').rglob('*.cpp'))
            self.assertEqual(cpp,['ForeverSubclass.cpp','SubclassSystem.cpp'])
            injected=(folder/'ForeverSubclass/forever_subclass/SubclassSystem.hpp').read_text()
            vendored=(MODULE/'vendor/include/forever_subclass/SubclassSystem.hpp').read_text()
            self.assertIn('subclassUnlockPrimaryLevel = 10;',injected)
            self.assertIn('subclassUnlockPrimaryLevel = 40;',vendored)
            server=(folder/'ForeverSubclass/ForeverSubclass.cpp').read_text()
            self.assertIn('#include "ChatCommand.h"',server)
            self.assertIn('class ForeverSubclassCommandScript final : public CommandScript',server)
            self.assertIn('ForeverSubclass::Request(handler->GetSession()->GetPlayer(), text);',server)
            self.assertIn('BASEPOWER {} {} {}',server)
            self.assertIn('3.0*seconds',server)
            self.assertIn('HasNativePowerSlot(Player* p,Powers power)',server)
            self.assertIn('p->GetPowerIndex(power)<MAX_POWERS_PER_CLASS',server)
            self.assertIn('HasNativePowerSlot(p,def.root.power)',server)
            self.assertIn('e.pools.erase(power)',server)
            self.assertEqual(server.count('new ForeverSubclassCommandScript();'),1)

    def test_server_adapter_has_multi_power_auto_ranks_pet_and_talents(self):
        server=(MODULE/'server/ForeverSubclass.cpp').read_text()
        schema=(MODULE/'sql/characters.sql').read_text()
        world=(MODULE/'sql/world.sql').read_text()
        self.assertIn('ClassPowers(Class id)',server)
        self.assertIn('{POWER_MANA,POWER_RAGE,POWER_ENERGY}',server)
        self.assertIn('BestRank(Entry const& e',server)
        self.assertIn('RootId(uint32 spell)',server)
        self.assertIn('TPOINTS',server)
        self.assertIn('TALENT {} {} {} {}',server)
        self.assertIn('SELECT class_id,talent_id,rank FROM forever_character_subclass_talents',server)
        self.assertIn('TameHunterPet',server)
        self.assertIn('CallHunterPet',server)
        self.assertIn('CreateTamedPetFrom',server)
        self.assertIn('FEATURE HUNTER_PET',server)
        self.assertIn('6807,11,10,POWER_RAGE',server)
        self.assertIn('1082,11,20,POWER_ENERGY',server)
        self.assertIn('forever_character_subclass_talents',schema)
        self.assertIn("(-6807,'spell_forever_subclass')",world)
        self.assertIn("(-1082,'spell_forever_subclass')",world)

    def test_staged_native_power_hotfix_only_targets_mage(self):
        sql=(MODULE/'sql/hotfixes-native-power-experiment.sql').read_text()
        installer=(ROOT/'scripts/subclass-mod.sh').read_text()
        doctor=(ROOT/'scripts/subclass-doctor.sh').read_text()
        self.assertIn('3224459983',sql)
        self.assertIn('190031901,1,8',sql)
        self.assertIn('190031902,3,8',sql)
        self.assertEqual(sql.count('ClassID'),1)
        self.assertNotIn(',1,1,@FSC_BUILD',sql)
        self.assertIn('SET @FSC_PUSH_ID := (SELECT COALESCE(MAX(`Id`),0)+1 FROM `hotfix_data`);',sql)
        self.assertIn('SET @FSC_UNIQUE_ID := (CRC32(UUID()) | 1);',sql)
        self.assertEqual(sql.count('@FSC_PUSH_ID,@FSC_UNIQUE_ID,@FSC_POWER_TABLE_HASH'),2)
        self.assertNotIn('@FSC_MAGE_RAGE_ID,1,@FSC_POWER_TABLE_HASH',sql)
        self.assertIn('hotfixes-native-power-experiment.sql',installer)
        self.assertIn('remove_native_power_hotfix',installer)
        self.assertIn('Mage native Rage/Energy DB2 rows = 2',doctor)
        self.assertIn('Mage native-power records published to client = 2',doctor)

    def test_addon_install_and_restore_is_clean_and_atomic(self):
        expected={
            'ForeverSubclass.toc','ForeverSubclassDirectTransport.lua','ForeverSubclassResourceHUD.lua',
            'ForeverSubclassCastFeedback.lua','ForeverSubclassTalents.lua','ForeverSubclassHunterPet.lua',
            'ForeverSubclassSpellBook.lua','ForeverSubclassActionBar.lua','ForeverSubclassTooltipGuard.lua',
            'ForeverSubclassDebug.lua',
        }
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'_classic_beta_';client.mkdir()
            (client/'WowB.exe').write_bytes(b'untouched executable fixture')
            (root/'Data').mkdir();(root/'Data/sentinel').write_bytes(b'untouched CASC fixture')
            old=client/'Interface/AddOns/ForeverSubclass';old.mkdir(parents=True)
            (old/'previous.lua').write_text('-- previous user addon\n')
            backup=root/'backup';target=installer.install(client,backup)
            self.assertEqual({p.name for p in target.iterdir() if p.is_file()},expected)
            toc=(target/'ForeverSubclass.toc').read_text()
            for name in expected-{'ForeverSubclass.toc'}:self.assertIn(name,toc)
            self.assertIn('0.10.1-freepick.2',toc)
            for stale in ['ForeverSubclass.lua','ForeverSubclassTalentTree.lua','ForeverSubclassTalentHostFix.lua',
                          'ForeverSubclassTalentTab.lua','ForeverSubclassTalentCompat.lua','ForeverSubclassPanelV2.lua',
                          'ForeverSubclassLegacySuppress.lua','ForeverSubclassInteractiveFix.lua','ForeverSubclassCommandTransport.lua']:
                self.assertNotIn(stale,toc);self.assertFalse((target/stale).exists())
            self.assertEqual((backup/'previous-addon/previous.lua').read_text(),'-- previous user addon\n')
            with self.assertRaises(FileExistsError):installer.install(client,backup)
            installer.restore(backup)
            self.assertEqual(sorted(p.name for p in target.iterdir()),['previous.lua'])
            self.assertEqual((client/'WowB.exe').read_bytes(),b'untouched executable fixture')
            self.assertEqual((root/'Data/sentinel').read_bytes(),b'untouched CASC fixture')

    def test_unified_talent_page_owns_visibility_abilities_and_tree(self):
        ui=(ADDON/'ForeverSubclassTalents.lua').read_text()
        self.assertIn('PlayerSpellsFrame',ui)
        self.assertIn('TalentsFrame',ui)
        self.assertIn('ForeverSubclassTalentTab',ui)
        self.assertIn('ForeverSubclassTalentPanel',ui)
        self.assertIn('text:find("Основное"',ui)
        self.assertIn('OnMouseDown',ui)
        self.assertIn('customActive=false',ui)
        self.assertIn('TPOINTS',ui)
        self.assertIn('TALENT',ui)
        self.assertIn('talentBranches',ui)
        self.assertIn('createTalentConnectors',ui)
        self.assertIn('modeTalents',ui)
        self.assertIn('send("talent "..id)',ui)
        self.assertIn('send("talentreset")',ui)
        self.assertIn('RegisterForDrag',ui)
        self.assertNotIn('ForeverSubclassTalentClickProxy',ui)
        self.assertFalse((ADDON/'ForeverSubclassTalentTree.lua').exists())
        self.assertFalse((ADDON/'ForeverSubclassTalentHostFix.lua').exists())

    def test_hunter_pet_controls_use_server_protocol(self):
        pet=(ADDON/'ForeverSubclassHunterPet.lua').read_text()
        self.assertIn('FEATURE',pet);self.assertIn('HUNTER_PET',pet)
        self.assertIn('send("tame")',pet);self.assertIn('send("petcall")',pet);self.assertIn('send("petdismiss")',pet)

    def test_subclass_spellbook_is_addon_owned_and_server_driven(self):
        spellbook=(ADDON/'ForeverSubclassSpellBook.lua').read_text()
        self.assertIn('PlayerSpellsFrame.SpellBookFrame',spellbook)
        self.assertIn('ForeverSubclassSpellBookTab',spellbook)
        self.assertIn('ForeverSubclassSpellBookPanel',spellbook)
        self.assertIn('send("cast "..self.spell.id)',spellbook)
        self.assertIn('if sp.selected then',spellbook)
        self.assertNotIn('LearnSpell',spellbook)

    def test_subclass_action_bar_renders_real_icon_tooltip_and_cooldown(self):
        action=(ADDON/'ForeverSubclassActionBar.lua').read_text()
        feedback=(ADDON/'ForeverSubclassCastFeedback.lua').read_text()
        self.assertIn('CreateMacro',action);self.assertIn('PickupMacro',action);self.assertIn('#showtooltip ',action)
        self.assertIn('spellTexture(id)',action);self.assertIn('GameTooltip.SetSpellByID',action)
        self.assertIn('CooldownFrameTemplate',action);self.assertIn('ForeverSubclassCooldownStart',action)
        self.assertIn('/fsubcast',action);self.assertIn('InCombatLockdown',action)
        self.assertNotIn('INV_MISC_QUESTIONMARK',action)
        self.assertIn('ForeverSubclassCooldownStart',feedback);self.assertIn('ForeverSubclassCooldownSync',feedback)

    def test_secondary_resource_hud_is_integrated_two_row_player_frame_block(self):
        hud=(ADDON/'ForeverSubclassResourceHUD.lua').read_text()
        feedback=(ADDON/'ForeverSubclassCastFeedback.lua').read_text()
        self.assertIn('local frame,mainBar,secondaryBar,nativeBar',hud)
        self.assertIn('built native-aware primary+secondary PlayerFrame power block',hud)
        self.assertIn('setStockVisible(false)',hud)
        self.assertIn('mainBar:SetPoint("TOPLEFT"',hud)
        self.assertIn('secondaryBar:SetPoint("TOPLEFT"',hud)
        self.assertIn('kind=="BASEPOWER"',hud)
        self.assertIn('hasNativeClientPower(kind)',hud)
        self.assertIn('live=hasNativeClientPower',hud)
        self.assertIn('RAGE_DECAY_PER_SECOND=3',hud)
        self.assertIn('pending.powers[power]',hud);self.assertIn('ForeverSubclassResourcePredictSpend',hud)
        self.assertIn('UnitPowerType',hud);self.assertIn('UnitPower("player"',hud)
        self.assertIn('ForeverSubclassResourcePredictSpend',feedback);self.assertIn('base("status",true)',feedback)

    def test_version_guards_require_native_power_slot_generation(self):
        docker=(ROOT/'Dockerfile').read_text()
        installer=(ROOT/'scripts/subclass-mod.sh').read_text()
        doctor=(ROOT/'scripts/subclass-doctor.sh').read_text()
        self.assertIn('0.4.0-freepick.1',docker)
        self.assertIn("[ \"$label\" = '0.4.0-freepick.1' ]",installer)
        self.assertIn("if [ \"$label\" = '0.3.6-forever.9' ]",doctor)

    def test_direct_transport_uses_server_endpoint_and_slow_idle_polling(self):
        transport=(ADDON/'ForeverSubclassDirectTransport.lua').read_text()
        self.assertIn('SERVER_TARGET="SERVER"',transport)
        self.assertIn('C_ChatInfo.SendAddonMessage',transport)
        self.assertIn('sendRaw(payload,SERVER_TARGET,quiet)',transport)
        self.assertIn('and 1.0 or 10.0',transport)
        self.assertNotIn('SetScript("OnClick"',transport)

    def test_debugger_captures_own_lua_errors_without_full_protocol_spam(self):
        debug=(ADDON/'ForeverSubclassDebug.lua').read_text()
        self.assertIn('seterrorhandler',debug);self.assertIn('LUA ERROR',debug)
        self.assertIn('/fsubdebug verbose',debug);self.assertIn('kind=="ERROR"',debug)

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

    @unittest.skipUnless(ctypes.util.find_library('lua5.4'),'Lua 5.4 runtime required for syntax test')
    def test_every_addon_lua_file_parses(self):
        lua=ctypes.CDLL(ctypes.util.find_library('lua5.4'))
        lua.luaL_newstate.restype=ctypes.c_void_p
        lua.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lua.luaL_loadstring.restype=ctypes.c_int
        lua.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];lua.lua_tolstring.restype=ctypes.c_char_p
        lua.lua_close.argtypes=[ctypes.c_void_p]
        for path in sorted(ADDON.glob('*.lua')):
            state=lua.luaL_newstate()
            try:
                status=lua.luaL_loadstring(state,path.read_bytes())
                if status:self.fail(f'{path.name}: '+lua.lua_tolstring(state,-1,None).decode())
            finally:lua.lua_close(state)

if __name__=='__main__':unittest.main()
