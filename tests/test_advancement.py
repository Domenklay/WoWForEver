import ctypes
import ctypes.util
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).parents[1]
MODULE=ROOT/'mods/forever-advancement'


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class AdvancementTests(unittest.TestCase):
    def test_catalog_retains_all_original_fields_and_reproducible_outputs(self):
        importer=load('import-ascension-content.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['catalog','addon/ForeverAscension','server','sql']:(root/name).mkdir(parents=True)
            for name in [p.name for p in (MODULE/'catalog').glob('*.json')]:
                shutil.copy2(MODULE/'catalog'/name,root/'catalog'/name)
            result=importer.generate(root)
            self.assertEqual(result['entries'],23709)
            root_row=next(line for line in (root/'server/AscensionCatalog.h').read_text().splitlines() if line.startswith('{25,11,339,'))
            self.assertIn(json.dumps('Гнев деревьев',ensure_ascii=True),root_row)
            for name in ['addon/ForeverAscension/Catalog.lua','server/AscensionCatalog.h','sql/world.sql','addon/ForeverAscension/CustomRules.lua','server/AscensionCustomCatalog.h']:
                self.assertEqual((root/name).read_bytes(),(MODULE/name).read_bytes())
            data=json.loads((root/'catalog/CharacterAdvancementData.json').read_text())
            data.append(data[0]);(root/'catalog/CharacterAdvancementData.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):importer.generate(root)

    def test_archive_member_paths_are_not_extracted(self):
        importer=load('import-ascension-content.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['catalog','addon/ForeverAscension','server','sql']:(root/name).mkdir(parents=True)
            archive=root/'content.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('../outside','untrusted')
                for name in ['CharacterAdvancementData.json','SpellRankData.json']:
                    z.writestr('Content/'+name,(MODULE/'catalog'/name).read_bytes())
            importer.import_archive(archive,root)
            self.assertFalse((root.parent/'outside').exists())

    def test_new_addon_replaces_old_and_rollback_preserves_both(self):
        installer=load('install-advancement-addon.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';client.mkdir();(client/'WowB.exe').write_bytes(b'unchanged')
            addons=client/'Interface/AddOns';addons.mkdir(parents=True)
            for name in installer.NAMES:
                (addons/name).mkdir();(addons/name/'custom.lua').write_text(name)
            backup=root/'backup';target=installer.install(client,backup)
            self.assertTrue((target/'Catalog.lua').is_file())
            self.assertFalse((addons/'ForeverSubclass').exists())
            with self.assertRaises(FileExistsError):installer.install(client,backup)
            (target/'user.lua').write_text('new user changes')
            installer.restore(backup)
            for name in installer.NAMES:self.assertEqual((addons/name/'custom.lua').read_text(),name)
            self.assertEqual((backup/'before-restore/ForeverAscension/user.lua').read_text(),'new user changes')
            self.assertEqual((client/'WowB.exe').read_bytes(),b'unchanged')

    def test_first_install_rollback_and_symlink_rejection(self):
        installer=load('install-advancement-addon.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';client.mkdir();(client/'WowB.exe').touch()
            installer.install(client,root/'backup');installer.restore(root/'backup')
            self.assertFalse((client/'Interface/AddOns/ForeverAscension').exists())
            (client/'Interface/AddOns/ForeverSubclass').symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):installer.install(client,root/'second')

    def test_repeated_addon_install_keeps_one_current_folder_and_preserves_edits_in_backup(self):
        installer=load('install-advancement-addon.py')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client=root/'client';client.mkdir();(client/'WowB.exe').touch()
            target=installer.install(client,root/'first')
            (target/'user.lua').write_text('local edits')
            installer.install(client,root/'second')
            self.assertEqual([p.name for p in target.parent.iterdir()],['ForeverAscension'])
            self.assertFalse((target/'user.lua').exists())
            self.assertEqual((root/'second/ForeverAscension/user.lua').read_text(),'local edits')
            self.assertIn('## Version: 1.13.2',(target/'ForeverAscension.toc').read_text())
            installer.restore(root/'second')
            self.assertEqual((target/'user.lua').read_text(),'local edits')
            self.assertFalse((target.parent/'ForeverSubclass').exists())

    def test_injection_adds_native_class_schools_without_automatic_learning(self):
        injector=load('inject-advancement.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);custom=root/'src/server/scripts/Custom';custom.mkdir(parents=True)
            (custom/'custom_script_loader.cpp').write_text('void AddCustomScripts()\n{\n}\n')
            player=root/'src/server/game/Entities/Player';player.mkdir(parents=True)
            (player/'Player.h').write_text('        void SetSkill(uint32 id, uint16 step, uint16 newVal, uint16 maxVal);\n        SkillStatusMap mSkillStatus;\n        Optional<PlayerSpellTrait> GetTraitInfoForSpell(uint32 spellId) const;')
            (player/'Player.cpp').write_text("""void Player::SetSkill(uint32 id, uint16 step, uint16 newVal, uint16 maxVal)
{
    LearnSkillRewardedSpells(id, newVal, Races(GetRace()));
    LearnSkillRewardedSpells(id, newVal, Races(GetRace()));
    if (std::vector<SkillLineAbilityEntry const*> const* skillLineAbilities = sDB2Manager.GetSkillLineAbilitiesBySkill(id)) {}
}
bool Player::IsClassicProfessionChildSkill() {}
void Player::_SaveSkills()
{
        if (itr->second.uState == SKILL_UNCHANGED) {}
}
void Player::LearnSkillRewardedSpells(uint32 skillId, uint32 skillValue, Races race)
{
}
Optional<PlayerSpellTrait> Player::GetTraitInfoForSpell(uint32 spellId) const
{
    return {};
}
void Player::SetReputation() {}
""")
            db2=root/'src/server/game/DataStores/DB2Stores.cpp';db2.parent.mkdir(parents=True)
            db2.write_text('void DB2Manager::InsertNewHotfix(uint32 tableHash, uint32 recordId)\n{\n    HotfixRecord hotfixRecord;\n}\n')
            injector.inject(root);first=(player/'Player.cpp').read_text();injector.inject(root)
            self.assertEqual(db2.read_text().count('hotfixRecord.HotfixStatus = HotfixRecord::Status::Valid;'),1)
            self.assertEqual((player/'Player.cpp').read_text(),first)
            self.assertIn('bool advancementEdit = false',(player/'Player.h').read_text())
            self.assertEqual(first.count('if (!advancementEdit) LearnSkillRewardedSpells'),2)
            self.assertIn('m_foreverAdvancementClassSkills.count(itr->first) ||',first)
            self.assertIn('if (m_foreverAdvancementClassSkills.count(skillId) || m_foreverAdvancementEquipmentSkills.count(skillId)) return;',first)
            self.assertEqual(first.count('void Player::SyncForeverAdvancementClassSkills('),1)

    def test_client_book_serialization_injection_is_idempotent_for_both_packet_paths(self):
        injector=load('inject-advancement.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            custom=root/'src/server/scripts/Custom';custom.mkdir(parents=True)
            (custom/'custom_script_loader.cpp').write_text('void AddCustomScripts()\n{\n}\n')
            data=root/'src/server/game/DataStores';data.mkdir(parents=True)
            header=data/'DB2Stores.h'
            header.write_text('class DB2Manager {\n    DB2StorageBase const* GetStorage(uint32 type) const;\n    int32 _maxHotfixId = 0;\n};\n')
            source=data/'DB2Stores.cpp'
            source.write_text('#include "DB2Stores.h"\nvoid DB2Manager::InsertNewHotfix(uint32 tableHash, uint32 recordId)\n{\n    HotfixRecord hotfixRecord;\n}\n')
            handler=root/'src/server/game/Handlers/HotfixHandler.cpp';handler.parent.mkdir(parents=True)
            handler.write_text('store->WriteRecord(record.RecordID, GetSessionDbcLocale(), dbReply.Data);\nstorage->WriteRecord(uint32(hotfixRecord.RecordID), GetSessionDbcLocale(), hotfixQueryResponse.HotfixContent);\n')
            injector.inject(root)
            first=[p.read_text() for p in (header,source,handler)]
            injector.inject(root)
            self.assertEqual(first,[p.read_text() for p in (header,source,handler)])
            self.assertEqual(source.read_text().count('void DB2Manager::WriteForeverAdvancementClientRecord('),1)
            self.assertEqual(handler.read_text().count('sDB2Manager.WriteForeverAdvancementClientRecord('),2)
            self.assertNotIn('->WriteRecord(',handler.read_text())

    def test_injection_removes_old_engine_and_is_repeatable(self):
        injector=load('inject-advancement.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);custom=root/'src/server/scripts/Custom';custom.mkdir(parents=True)
            loader=custom/'custom_script_loader.cpp'
            loader.write_text('void AddSC_forever_subclass();\nvoid AddCustomScripts()\n{\n    AddSC_forever_subclass();\n}\n')
            manager=root/'src/server/game/Globals/ObjectMgr.h';manager.parent.mkdir(parents=True)
            manager.write_text('class ObjectMgr {\n        SpellScriptsBounds GetSpellScriptsBounds(uint32 spellId);\n};')
            spell_header=root/'src/server/game/Spells/Spell.h';spell_header.parent.mkdir(parents=True)
            spell_header.write_text('class Spell {\n        std::any m_customArg;\n};')
            (custom/'ForeverSubclass').mkdir();(custom/'ForeverSubclass/old.cpp').touch()
            injector.inject(root);first=loader.read_text();injector.inject(root)
            self.assertEqual(loader.read_text(),first)
            self.assertNotIn('forever_subclass',first)
            self.assertEqual(first.count('    AddSC_forever_advancement();'),1)
            self.assertFalse((custom/'ForeverSubclass').exists())
            self.assertEqual(manager.read_text().count('void RegisterForeverAdvancementBinding('),1)
            self.assertEqual(spell_header.read_text().count('void IgnorePowerCostForForeverAdvancement('),1)


MOCK=r'''
_G=_G or _ENV
unpack=table.unpack
frames={};named={};sent={};SlashCmdList={};UISpecialFrames={}
local methods={}
function methods:SetScript(k,f) self.scripts[k]=f end
function methods:SetPoint(...) self.points=self.points or {};table.insert(self.points,{...}) end
function methods:ClearAllPoints() self.points={} end
function methods:SetTexture(value) self.texture=value end
function methods:SetTexCoord(...) self.texcoords={...} end
function methods:SetShadowOffset(x,y) self.shadow={x,y} end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false end
function methods:SetShown(value) self.shown=value end
function methods:IsShown() return self.shown~=false end
function methods:SetEnabled(value) self.enabled=value end
function methods:SetText(text) self.text=text end
function methods:GetText() return self.text or '' end
function methods:SetValue(value) self.value=value end
function methods:SetMinMaxValues(lo,hi) self.maximum=hi end
function methods:SetHeight(value) self.height=value end
function methods:SetWidth(value) self.width=value end
function methods:GetHeight() return self.height or 10 end
function methods:GetWidth() return self.width or 1020 end
function methods:GetFrameStrata() return self.strata or "MEDIUM" end
function methods:GetScript(k) return self.scripts[k] end
function methods:SetParent(parent) self.parent=parent end
function methods:SetSize(w,h) self.width=w;self.height=h end
function methods:SetScale(value) self.scale=value end
function methods:SetFont(path,size,flags) self.fontSize=size end
function methods:GetFrameLevel() return self.level or 1 end
function methods:SetFrameLevel(value) self.level=value end
function methods:SetFrameStrata(value) self.strata=value end
function methods:GetAlpha() return self.alpha or 1 end
function methods:SetAlpha(value) self.alpha=value end
function methods:HookScript(k,f)
 local old=self.scripts[k];self.scripts[k]=function(...) if old then old(...) end;return f(...) end
end
function methods:GetChildren()
 local out={};for _,f in ipairs(frames) do if f.parent==self then out[#out+1]=f end end;return table.unpack(out)
end
function methods:GetObjectType() return self.kind end
function methods:GetParent() return self.parent end
function methods:GetLeft() return self.left end
function methods:GetRight() return self.right end
function methods:GetBottom() return self.bottom end
function methods:GetTop() return self.top end
function methods:SetVerticalScroll(value) self.scroll=value end
function methods:GetVerticalScroll() return self.scroll or 0 end
local function object(kind,name,parent)
 local o={kind=kind,name=name,parent=parent,scripts={}}
 setmetatable(o,{__index=function(_,key) return methods[key] or (key:match('^[A-Z]') and function() end) end})
 table.insert(frames,o);if name then named[name]=o;_G[name]=o end;return o
end
function methods:CreateTexture() return object('Texture',nil,self) end
function methods:CreateFontString() return object('Font',nil,self) end
function CreateFrame(kind,name,parent,template)
 local o=object(kind,name,parent)
 o.template=template
 if template=='BasicFrameTemplateWithInset' then o.TitleText=object('Font',nil,o) end
 if template=='TabSystemButtonArtTemplate' then o.Text=object('Font',nil,o);o.RotatedTextures={} end
 return o
end
UIParent=CreateFrame('Frame');PlayerFrame=CreateFrame('Frame');PlayerFrameManaBar=CreateFrame('StatusBar',nil,PlayerFrame);CharacterFrame=CreateFrame('Frame')
GameTooltip=object('Tooltip')
local now=100
function GetTime() return now end
function advance() now=now+1 end
function UnitName() return 'Tester' end
function GetUnitName() return 'Tester-Realm' end
function UnitAffectingCombat() return false end
function UnitPowerMax(_,power) return power==1 and 100 or 0 end
function UnitPower() return 25 end
C_ChatInfo={RegisterAddonMessagePrefix=function() end,SendAddonMessage=function(prefix,text,channel,target) table.insert(sent,text);return true end}
'''


@unittest.skipUnless(ctypes.util.find_library('lua5.4'),'Lua 5.4 required')
class AdvancementUITests(unittest.TestCase):
    def lua(self,assertions):
        lib=ctypes.CDLL(ctypes.util.find_library('lua5.4'))
        lib.luaL_newstate.restype=ctypes.c_void_p;lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_void_p]
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p];state=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(state)
            for chunk in [MOCK,(MODULE/'addon/ForeverAscension/Catalog.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/CustomRules.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/Portrait.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/CharacterStats.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/Integration.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/Presentation.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/ForeverAscension.lua').read_text()+'\n'+assertions]:
                status=lib.luaL_loadstring(state,chunk.encode())
                if not status:status=lib.lua_pcallk(state,0,0,0,0,None)
                if status:self.fail(lib.lua_tolstring(state,-1,None).decode())
        finally:lib.lua_close(state)

    def test_scrolling_abilities_keep_all_rows_and_do_not_follow_talent_branch_filter(self):
        self.lua(r'''
open();parse('STATE 1 40 0 8');parse('ACTIVE 8');parse('CLASS 8 40 0 1000');parse('CATALOG NATIVE');parse('TREES')
for i=1,30 do parse('NATIVE '..i..' 8 '..(100+i)..' 1 0 1 0 1 available') end
parse('NATIVE 1000 8 2000 10 1 5 700 1 available');parse('NATIVE 1001 8 2001 10 1 5 701 1 available')
parse('TREE arcane d0a2d0b0d0b9d0bdd0b0d18f');parse('TNODE 1000 arcane 0 0');parse('TNODE 1001 fire 1 1');parse('TEDGE 1001 1000');parse('END')
selectedClass=8;selectedTab='arcane';refresh();local abilities,talents=visible();assert(#abilities==30 and #talents==1)
assert(#abilityNodes>=30 and abilityNodes[30].entry.ID==30 and abilityCanvas:GetHeight()>=1620)
abilityScroll.height=400;abilityScroll.scripts.OnMouseWheel(abilityScroll,-100);assert(abilityScroll.scroll>=1200)
assert(not previous:IsShown() and not nextPage:IsShown() and not classButtons[12] and not classButtons[13])
selectedTab='fire';refresh();abilities,talents=visible();assert(#abilities==30 and #talents==1 and talents[1].ID==1001)
advance();talentNodes[1].scripts.OnClick(talentNodes[1],'LeftButton');assert(sent[#sent]=='talent 1001')
''')

    def test_native_menu_remains_usable_on_the_current_server_without_donor_data(self):
        self.lua(r'''
open();parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CATALOG');parse('ENTRY 10 116 4 0 8');parse('TENTRY 398 3 10 1 0 8 11069');parse('END')
selectedClass=8;selectedTab='Forever';refresh();assert(byId[10] and not byId[398]);assert(not xpShareButton:IsShown())
local abilities,talents=visible();assert(#abilities==1 and #talents==0);advance();abilityNodes[1].scripts.OnClick(abilityNodes[1],'LeftButton');assert(sent[#sent]=='learn 10')
parse('STATE 1 20 1 8');parse('ENTRY 10 116 4 1 8');parse('LEARNED 10');parse('END');assert(#byClass[8]==1)
''')

    def test_real_catalog_menu_and_mixed_class_purchases_survive_filter_and_polls(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
assert(byId[100] and byId[101] and not byId[1300]);assert(#byClass[8]==2)
parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('CLASS 5 20 0 1000');parse('LEARNED 100');parse('END');assert(byId[101] and state.learned[100])
selectedClass=5;selectedTab='Forever';filter='';refresh();advance();abilityNodes[1].scripts.OnClick(abilityNodes[1],'LeftButton');assert(sent[#sent]=='learn 101')
''')

    def test_activate_subclass_and_independent_progress_in_menu(self):
        self.lua(r"""
open();parse('PROTOCOL 2');parse('STATE 11 60 0 8')
parse('ACTIVE 8');parse('CLASS 8 40 0 0');parse('CLASS 1 12 50 1000');parse('TPOINTS 31 0 31');parse('END')
selectedClass=8;refresh();assert(not activateButton.enabled and progressText.text:find('40/40',1,true))
selectedClass=1;refresh();advance();activateButton.scripts.OnClick();assert(sent[#sent]=='activate 1')
assert(state.classes[8].level==40 and state.classes[1].xp==50)
selectedClass=11;refresh();advance();activateButton.scripts.OnClick();assert(sent[#sent]=='activate 0')
""")

    def test_talent_grid_ranks_and_server_purchase_messages(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
assert(talentNodes[1].entry.ID==200);advance();local count=#sent;talentNodes[1].scripts.OnClick(talentNodes[1],'LeftButton');assert(#sent==count)
assert(message.text:find('не поддерживается',1,true));assert(not talentPoints:IsShown())
''')

    def test_portrait_resources_survive_switch_and_missing_native_bar(self):
        self.lua(r"""
PlayerFrameManaBar=nil;PlayerFrame.ManaBar=nil;PlayerFrame.manabar=nil;PlayerFrame.PlayerFrameContent=nil
open();parse('STATE 11 20 0 8');parse('ACTIVE 8')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100');parse('END')
local portrait=named.ForeverAscensionPortraitResources
assert(portrait and portrait:IsShown() and portrait.parent==PlayerFrame)
assert(portrait.points[1][2]==PlayerFrame and portrait.width==122)
parse('STATE 11 20 0 8');parse('ACTIVE 0')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100');parse('END')
assert(portrait:IsShown() and powerBars[1].value==400 and powerBars[2].value==90 and powerBars[3].value==25)
""")

    def test_portrait_supports_lowercase_native_manabar(self):
        self.lua(r"""
local actual=PlayerFrameManaBar;PlayerFrameManaBar=nil;PlayerFrame.manabar=actual
open();parse('STATE 11 20 0 8');parse('ACTIVE 0')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100');parse('END')
assert(named.ForeverAscensionPortraitResources.points[1][2]==actual and actual.alpha==0)
""")

    def test_portrait_resources_replace_native_power_bar_and_stats_keep_text_values(self):
        self.lua(r"""
UnitStat=function(_,index) return index*10,index*10+5 end
UnitHealth=function() return 300 end;UnitHealthMax=function() return 500 end
GetCritChance=function() return 12.5 end
open();parse('PROTOCOL 2');parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100');parse('REGEN 4 1.2');parse('END')
local portrait=named.ForeverAscensionPortraitResources
assert(portrait and portrait.parent==PlayerFrame and portrait.points[1][2]==PlayerFrameManaBar)
assert(PlayerFrameManaBar.alpha==0)
assert(not named.ForeverAscensionResources,'the old floating block must be gone')
for _,frame in ipairs(frames) do if frame.scripts.OnEvent then frame.scripts.OnEvent(frame,'PLAYER_LOGIN') end end
named.ForeverAscensionStatsToggle.scripts.OnClick()
assert(named.ForeverAscensionCharacterStats:IsShown())
local actual={};for _,row in ipairs(ForeverAscensionStatRows) do actual[row.title]=row.value.text end
assert(actual['Здоровье']=='300 / 500' and actual['Мана']=='400 / 500')
assert(actual['Сила']=='15')
local sawPercent=false;for _,row in ipairs(ForeverAscensionStatRows) do if row.title=='Критический удар' and row.value.text=='12.5%' then sawPercent=true end end;assert(sawPercent)
assert(actual['Мана / сек.']=='4' and actual['Мана / сек. в бою']=='1.2')
""")

    def test_russian_search_is_case_insensitive_and_deprecated_duplicates_are_hidden(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
C_Spell={GetSpellName=function(id) return id==116 and 'Ледяная стрела' or 'Другое' end}
filter=fold('ЛЕДЯНАЯ СТРЕЛА');local abilities=visible();assert(#abilities==1 and abilities[1].ID==100)
assert(not customButton:IsShown());assert(#customRows==0)
''')

    def test_native_tree_uses_readable_nodes_and_scrolls_to_last_tier(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
parse('STATE 1 20 0 8');parse('CATALOG NATIVE')
for i=1,80 do parse('NATIVE '..(1000+i)..' 8 116 1 1 1 700 0 native_rules_required') end
parse('END');selectedClass=8;selectedTab='Forever';talentScroll.height=403;refresh()
assert(talentCanvas.height>403);talentScroll.scripts.OnMouseWheel(talentScroll,-100);assert(talentScroll.scroll>0)
for _,n in ipairs(talentNodes) do if n:IsShown() then assert(n.icon.width==36) end end
''')

    def test_native_drag_and_talent_neighbour_button_without_duplicate_spell_ui(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
local picked;C_Spell={PickupSpell=function(id) picked=id end};local n=abilityNodes[1];n.scripts.OnDragStart(n);assert(picked==116)
advance();n.scripts.OnClick(n,'LeftButton');assert(sent[#sent]=='cast 100');advance();n.scripts.OnClick(n,'RightButton');assert(sent[#sent]=='unlearn 100')
assert(not named.ForeverAscensionSpellbook and not named.ForeverAscensionActions)
''')

    def test_native_roots_are_visible_known_and_do_not_consume_a_purchase(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
parse('STATE 8 20 0 8');parse('KNOWN 100 116');parse('END');refresh();local n=abilityNodes[1];advance();local count=#sent;n.scripts.OnClick(n,'LeftButton');assert(#sent==count)
''')

    def test_talent_window_button_attaches_after_delayed_frame_load_and_uses_native_tooltip_id(self):
        self.lua(r'''

open();PlayerTalentFrame=CreateFrame('Frame','PlayerTalentFrame',UIParent)
PlayerTalentFrame.Pages={CreateFrame('Frame',nil,PlayerTalentFrame)};PlayerTalentFrame.Tabs={CreateFrame('Button',nil,PlayerTalentFrame)}
PlayerTalentFrame.SelectPage=function(self,id) self.currentPage=id;for i,p in ipairs(self.Pages) do p:SetShown(i==id) end;local p=self.Pages[id];if p.scripts.OnShow then p.scripts.OnShow(p) end end
for _,f in ipairs(frames) do if f.scripts.OnEvent then f.scripts.OnEvent(f,'ADDON_LOADED') end end
assert(#PlayerTalentFrame.Pages==2 and #PlayerTalentFrame.Tabs==2)
ForeverAscensionTalentButton.scripts.OnClick();assert(PlayerTalentFrame:IsShown() and window.parent==ForeverAscensionTalentPage)
assert(PlayerTalentFrame.currentPage==2 and not window.title:IsShown() and not window.close:IsShown())
PlayerTalentFrame:SelectPage(1);assert(not ForeverAscensionTalentPage:IsShown())
''')

    def test_camelot_tab_is_in_the_visible_loadout_strip_not_the_hidden_retail_tab_system(self):
        self.lua(r'''
open();WOW_PROJECT_ID=18
PlayerSpellsFrame=CreateFrame('Frame','PlayerSpellsFrame',UIParent)
local root=PlayerSpellsFrame;local retailTabs=0
root.AddNamedTab=function() retailTabs=retailTabs+1 end
root.SetTab=function(self,id) self.active=id end;root.talentTabID=2
root.TalentsFrame=CreateFrame('Frame',nil,root)
local host=root.TalentsFrame;host.ButtonsParent=CreateFrame('Frame',nil,host)
local canvas=host.ButtonsParent;canvas:SetFrameLevel(1000)
local strip=CreateFrame('Frame',nil,host);host.TabSystem=strip;strip:SetSize(301,32)
local primary=CreateFrame('Button',nil,strip);primary:SetText('Основное');primary.right=200
local secondary=CreateFrame('Button',nil,strip);secondary:SetText('Дополнительное');secondary.right=350
local nativeClicks=0;secondary:SetScript('OnClick',function() nativeClicks=nativeClicks+1 end)
local tree=CreateFrame('Frame',nil,host);local footer=CreateFrame('Button',nil,host)
local hidden=CreateFrame('Frame',nil,host);hidden:Hide()
ForeverAscensionNativeTalentTab.Install()
assert(retailTabs==0,'hidden retail TabSystem must not receive the new tab')
local tab=ForeverAscensionTalentButton;local page=ForeverAscensionTalentPage
assert(tab.parent==host and page.parent==host,'tab must not be clipped or panned with the node canvas')
assert(tab:GetFrameLevel()>canvas:GetFrameLevel() and page:GetFrameLevel()>canvas:GetFrameLevel())
assert(tab.points[1][2]==strip,'tab follows the confirmed 301x32 native loadout strip')
SlashCmdList.FOREVERASCENSION('')
assert(root.active==2 and root:IsShown() and host:IsShown())
assert(window.parent==page and page:IsShown() and not tree:IsShown() and not footer:IsShown() and not canvas:IsShown())
assert(tab:IsShown() and primary:IsShown() and secondary:IsShown())
secondary.scripts.OnClick(secondary)
assert(nativeClicks==1,'native handler preserved')
assert(not page:IsShown() and tree:IsShown() and footer:IsShown() and not hidden:IsShown())
tab.scripts.OnClick(tab);ForeverAscensionToggle()
assert(not page:IsShown() and tree:IsShown(),'toggle must restore the native tree, not leave a blank page')
tab.scripts.OnClick(tab);host.scripts.OnHide(host)
assert(not page:IsShown() and tree:IsShown() and not hidden:IsShown())
local count=#frames;ForeverAscensionNativeTalentTab.Install();assert(#frames==count)
''')

    def test_camelot_waits_for_delayed_buttons_parent_instead_of_adding_hidden_tabs(self):
        self.lua(r'''
WOW_PROJECT_ID=18;PlayerSpellsFrame=CreateFrame('Frame','PlayerSpellsFrame',UIParent)
local root=PlayerSpellsFrame;root.TalentsFrame=CreateFrame('Frame',nil,root)
root.AddNamedTab=function() error('must not attach to hidden retail tab system') end
assert(not ForeverAscensionNativeTalentTab.Install())
root.SetTab=function(self,id) self.active=id end;root.talentTabID=2
SlashCmdList.FOREVERASCENSION('');assert(window==nil,'delayed native load must not open a standalone window')
root.TalentsFrame.ButtonsParent=CreateFrame('Frame',nil,root.TalentsFrame)
assert(not ForeverAscensionNativeTalentTab.Install(),'node canvas alone is not the tab strip')
root.TalentsFrame.TabSystem=CreateFrame('Frame',nil,root.TalentsFrame)
for _,f in ipairs(frames) do if f.scripts.OnEvent then f.scripts.OnEvent(f,'ADDON_LOADED') end end
assert(ForeverAscensionTalentButton.parent==root.TalentsFrame)
assert(window.parent==ForeverAscensionTalentPage and root.active==2)
''')

    def test_embedded_presentation_fills_native_page_without_shrinking_text_or_nested_dialog(self):
        self.lua(r'''
local parent=CreateFrame('Frame',nil,UIParent);parent:SetSize(1208,635)
ForeverAscensionShowIn(parent)
parse('STATE 8 21 1 8');parse('CATALOG');parse('ENTRY 10 116 1 0 8');parse('END')
assert(window.scale==1 and window.width==1208 and window.height==635)
assert(window.foreverFill.texture=='Interface\\Buttons\\WHITE8X8')
assert(uiRefs.abilityWidth>280 and uiRefs.talentWidth>500)
assert(classButtons[6].name.fontSize==14 and abilityNodes[1].name.fontSize==14)
assert(abilityNodes[1].height==60 and uiRefs.emptyTitle.fontSize==20)
local last=classButtons[order[#order]]
assert(-last.points[1][5]+last.height<=uiRefs.sidebar.height,'all class rows fit inside the sidebar')
assert(uiRefs.emptyCard:IsShown() and uiRefs.nativeTalents:IsShown() and not talentScroll:IsShown())
assert(not talentEmpty:IsShown(),'small technical text is replaced by a readable empty state')
for _,size in ipairs({{1020,600},{1208,635}}) do
 parent:SetSize(size[1],size[2]);parent.scripts.OnSizeChanged(parent)
 assert(window.scale==1 and window.width==size[1] and uiRefs.talents.points[1][4]+uiRefs.talents.width<=size[1]-15)
end
''')

    def test_presentation_keeps_real_trees_and_legacy_server_states_distinct(self):
        self.lua(r'''
local parent=CreateFrame('Frame',nil,UIParent);parent:SetSize(1208,635);ForeverAscensionShowIn(parent)
parse('STATE 1 21 0 8');parse('ACTIVE 8');parse('CLASS 8 21 0 1000');parse('CATALOG');parse('ENTRY 10 116 1 0 8');parse('END')
assert(uiRefs.emptyCard:IsShown() and not uiRefs.nativeTalents:IsShown())
parse('STATE 1 21 0 8');parse('ACTIVE 8');parse('CLASS 8 21 0 1000');parse('CATALOG NATIVE');parse('TREES')
parse('NATIVE 1000 8 2000 10 1 5 700 1 available');parse('TREE arcane d0a2d0b0d0b9d0bdd0b0d18f');parse('TNODE 1000 arcane 0 0');parse('END')
assert(not uiRefs.emptyCard:IsShown() and talentScroll:IsShown() and tabButtons[1]:IsShown())
assert(tabButtons[1].parent==uiRefs.talents and tabButtons[1].width>=140)
''')

    def test_modern_talent_button_anchors_to_content_and_closes_root(self):
        self.lua(r'''

open();PlayerSpellsFrame=CreateFrame('Frame','PlayerSpellsFrame',UIParent)
local host=PlayerSpellsFrame;host.nativePages={CreateFrame('Frame',nil,host)};host.nativeButtons={CreateFrame('Button',nil,host)};host.active=1
host.AddNamedTab=function(self,text,page) local id=#self.nativePages+1;self.nativePages[id]=page;local b=CreateFrame('Button',nil,self);b:SetText(text);b:SetScript('OnClick',function() self:SetTab(id) end);self.nativeButtons[id]=b;return id end
host.GetTabButton=function(self,id) return self.nativeButtons[id] end
host.GetTab=function(self) return self.active end
host.IsInspecting=function() return false end
host.IsTabAvailable=function(self,id) return id==1 end
host.UpdateFrameTitle=function(self) self.title='Native' end
host.SetTitle=function(self,text) self.title=text end
host.SetTab=function(self,id) self.active=id;for i,p in ipairs(self.nativePages) do p:SetShown(i==id) end;local p=self.nativePages[id];if p.scripts.OnShow then p.scripts.OnShow(p) end;self:UpdateFrameTitle() end
for _,f in ipairs(frames) do if f.scripts.OnEvent then f.scripts.OnEvent(f,'ADDON_LOADED') end end
assert(#host.nativePages==2 and ForeverAscensionTalentButton.text=='Мультикласс')
ForeverAscensionNativeTalentTab.Open();assert(host:IsShown() and host:GetTab()==2 and host:IsTabAvailable(2))
assert(window.parent==ForeverAscensionTalentPage and host.title=='Таланты: Мультикласс')
host:SetTab(1);assert(host.title=='Native' and not ForeverAscensionTalentPage:IsShown())
ForeverAscensionNativeTalentTab.Install();assert(#host.nativePages==2,'idempotent native tab integration')
''')

    def test_trait_description_uses_native_entry_rank_and_reports_actual_aura_values(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
local entry;C_Traits={GetTraitDescription=function(id,rank) entry=id;return 'Native description' end}
GameTooltip={SetOwner=function()end,SetText=function()end,AddLine=function()end,Show=function()end};tooltip(talentNodes[1]);assert(entry==700)
''')

    def test_native_book_report_reads_client_api_without_replacing_it(self):
        self.lua(r"""
GetBuildInfo=function() return '1.60.1','70532' end
GetNumSpellTabs=function() return 1 end
GetSpellTabInfo=function() return 'Общие',134400,0,10 end
C_SpellBook={GetNumSpellBookSkillLines=function() return 1 end,GetSpellBookSkillLineInfo=function() return {name='Общие',itemIndexOffset=0,numSpellBookItems=10} end}
local original=GetSpellTabInfo;local native=C_SpellBook.GetSpellBookSkillLineInfo
local report=ForeverAscensionNativeBookReport()
assert(report:find('70532',1,true) and report:find('Общие',1,true) and report:find('numSpellBookItems=10',1,true))
assert(GetSpellTabInfo==original and C_SpellBook.GetSpellBookSkillLineInfo==native)
assert(ForeverAscensionUI.nativeSpellbookReport==report)
local count=#sent;SlashCmdList.FOREVERASCENSION('bookdebug')
local debugFrame=named.ForeverAscensionBookDebug
assert(debugFrame and debugFrame.edit.text==report and debugFrame.edit.height>=400 and #sent==count)
""")

    def test_unadapted_talents_and_native_primary_cannot_be_purchased(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('XP_SHARE 1 90');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG NATIVE')
parse('NATIVE 100 8 116 4 0 1 0 1 available');parse('NATIVE 101 5 2061 5 0 1 0 1 available')
parse('NATIVE 200 8 999 10 1 3 700 0 native_rules_required');parse('NATIVE 300 3 200 1 0 1 0 0 unsupported_resource')
parse('LEARNED 100');parse('END');selectedClass=8;selectedTab='Forever';refresh()
selectedClass=3;selectedTab='Forever';showAll=true;refresh();advance();local count=#sent;abilityNodes[1].scripts.OnClick(abilityNodes[1],'LeftButton');assert(#sent==count)
parse('STATE 8 20 0 8');parse('END');selectedClass=8;refresh();advance();count=#sent;abilityNodes[1].scripts.OnClick(abilityNodes[1],'LeftButton');assert(#sent==count)
''')


if __name__=='__main__':unittest.main()
