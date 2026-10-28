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
            for name in ['addon/ForeverAscension/Catalog.lua','server/AscensionCatalog.h','sql/world.sql']:
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
            self.assertIn('if (m_foreverAdvancementClassSkills.count(skillId)) return;',first)
            self.assertEqual(first.count('void Player::SyncForeverAdvancementClassSkills('),1)

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
function methods:IsShown() return self.shown~=false end
function methods:SetEnabled(value) self.enabled=value end
function methods:SetText(text) self.text=text end
function methods:GetText() return self.text or '' end
function methods:SetValue(value) self.value=value end
function methods:SetMinMaxValues(lo,hi) self.maximum=hi end
function methods:SetHeight(value) self.height=value end
function methods:GetHeight() return self.height or 10 end
function methods:SetSize(w,h) self.width=w;self.height=h end
function methods:GetFrameLevel() return 1 end
function methods:GetAlpha() return self.alpha or 1 end
function methods:SetAlpha(value) self.alpha=value end
function methods:HookScript(k,f) self.scripts[k]=f end
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
 if template=='BasicFrameTemplateWithInset' then o.TitleText=object('Font',nil,o) end
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
                          (MODULE/'addon/ForeverAscension/Portrait.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/CharacterStats.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/Integration.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/ForeverAscension.lua').read_text()+'\n'+assertions]:
                status=lib.luaL_loadstring(state,chunk.encode())
                if not status:status=lib.lua_pcallk(state,0,0,0,0,None)
                if status:self.fail(lib.lua_tolstring(state,-1,None).decode())
        finally:lib.lua_close(state)

    def test_real_catalog_menu_and_mixed_class_purchases_survive_filter_and_polls(self):
        self.lua(r'''
assert(#ForeverAscensionCatalog==23709)
SlashCmdList.FOREVERASCENSION('')
assert(named.ForeverAscensionWindow:IsShown() and sent[#sent]=='status')
assert(classButtons[8].icon.texture=='Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES')
local mage,priest
for _,row in ipairs(ForeverAscensionCatalog) do
 if row.Class=='Mage' and row.Type=='Ability' and row.Name=='Frostbolt' and not mage then mage=row.ID end
 if row.Class=='Priest' and row.Type=='Ability' and row.Name=='Flash Heal' and not priest then priest=row.ID end
end
assert(mage and priest)
parse('PROTOCOL 2');parse('STATE 1 20 2 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG')
parse('ENTRY '..mage..' 116 4 0 8');parse('ENTRY '..priest..' 2061 20 0 5')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100')
parse('LEARNED '..mage);parse('LEARNED '..priest);parse('END')
assert(state.learned[mage] and state.learned[priest])
assert(powerBars[1].value==400 and powerBars[2].value==90 and powerBars[3].value==25)
classButtons[5].scripts.OnClick()
assert(selectedClass==5 and state.learned[mage] and state.learned[priest])
parse('STATE 1 20 2 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('LEARNED '..mage);parse('LEARNED '..priest);parse('END')
assert(compatible[mage] and compatible[priest])
assert(not named.ForeverAscensionActions and not named.ForeverAscensionSpellbook)
selectedClass=8;selectedTab='Frost';page=1;filter='frostbolt';refresh()
local clicked=false
for _,n in ipairs(abilityNodes) do if n.entry and n.entry.ID==mage then advance();n.scripts.OnClick(n,'LeftButton');clicked=true end end
assert(clicked and sent[#sent]=='cast '..mage)
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
        self.lua(r"""
open();parse('PROTOCOL 2');parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG')
parse('TENTRY 398 3 10 1 0 8');parse('TPOINTS 9 2 11');parse('TALENT 398 2');parse('END')
selectedClass=8;selectedTab='Fire';refresh()
local found
for _,node in ipairs(talentNodes) do if node.entry and node.entry.ID==398 then found=node end end
assert(found and found.note.text=='2/3')
assert(found.points[1][2]==285 and found.points[1][3]==-14)
advance();found.scripts.OnClick(found,'LeftButton');assert(sent[#sent]=='talent 398')
advance();found.scripts.OnClick(found,'RightButton');assert(sent[#sent]=='untalent 398')
assert(state.talentFree==9 and state.talentTotal==11)
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
        self.lua(r"""
GetLocale=function() return 'ruRU' end
open();selectedClass=8;selectedTab='Frost';showAll=true;filter=fold('ЛЕДЯНАЯ СТРЕЛА')
local abilities=visible();local found=false
for _,row in ipairs(abilities) do if row.ID==10 then found=true end;assert(availableRow(row)) end
assert(found)
local seen={};for _,row in ipairs(abilities) do assert(not seen[row.Name]);seen[row.Name]=true end
""")

    def test_native_tree_uses_readable_nodes_and_scrolls_to_last_tier(self):
        self.lua(r"""
open();parse('PROTOCOL 2');parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('END')
talentScroll.height=403;selectedClass=8;selectedTab='Fire';refresh()
assert(talentCanvas.height>403,'keep talent nodes readable and scroll the long tree')
talentScroll.scripts.OnMouseWheel(talentScroll,-100)
assert(talentScroll.scroll>0)
for _,node in ipairs(talentNodes) do if node:IsShown() then
 assert(node.icon.width==36)
 assert(-node.points[1][3]+node.height<=talentCanvas.height)
end end
for _,frame in ipairs(frames) do
 assert(frame.texture~='Interface\\QuestFrame\\QuestBG','no stretched parchment')
 if type(frame.texture)=='string' then assert(not frame.texture:find('TalentFrame',1,true),'no stretched tree artwork') end
end
assert(summary.text:find(' | ',1,true))
assert(emptyAbilities.shadow[1]==0 and emptyAbilities.shadow[2]==0)
assert(schools.BeastMastery=='Повелитель зверей')
""")

    def test_native_drag_and_talent_neighbour_button_without_duplicate_spell_ui(self):
        self.lua(r"""
TalentMicroButton=CreateFrame('Button','TalentMicroButton',UIParent)
local picked;C_Spell={PickupSpell=function(spell) picked=spell end}
open();parse('PROTOCOL 2');parse('STATE 1 20 1 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG')
parse('ENTRY 10 116 4 1 8');parse('LEARNED 10');parse('END')
selectedClass=8;selectedTab='Frost';refresh()
local card;for _,node in ipairs(abilityNodes) do if node.entry and node.entry.ID==10 then card=node end end
assert(card);card.scripts.OnDragStart(card);assert(picked==116)
advance();card.scripts.OnClick(card,'LeftButton');assert(sent[#sent]=='cast 10')
advance();card.scripts.OnClick(card,'RightButton');assert(sent[#sent]=='unlearn 10')
for _,frame in ipairs(frames) do if frame.scripts.OnEvent then frame.scripts.OnEvent(frame,'PLAYER_LOGIN') end end
local micro=named.ForeverAscensionMicroButton;assert(micro and micro.parent==TalentMicroButton and micro.points[1][2]==TalentMicroButton)
assert(not named.ForeverAscensionSpellbook and not named.ForeverAscensionActions)
window:Hide();micro.scripts.OnClick();assert(window:IsShown());micro.scripts.OnClick();assert(not window:IsShown())
-- Missing modern pickup API falls back to the actual native book slot.
C_Spell=nil;PickupSpell=nil
GetSpellBookItemInfo=function(slot) if slot==1 then return 'SPELL',116 end end
PickupSpellBookItem=function(slot,book) picked=slot..':'..book end
assert(ForeverAscensionPickupSpell(116) and picked=='1:spell')
InCombatLockdown=function() return true end;assert(not ForeverAscensionPickupSpell(116))
""")

    def test_native_roots_are_visible_known_and_do_not_consume_a_purchase(self):
        self.lua(r"""
local picked;C_Spell={GetSpellName=function(id) if id==339 then return 'Гнев деревьев' end end,PickupSpell=function(id) picked=id end}
open();parse('PROTOCOL 2');parse('STATE 11 11 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG');parse('ENTRY 25 339 8 0 11');parse('KNOWN 25 339');parse('END')
selectedClass=11;selectedTab='Balance';refresh()
local card;for _,node in ipairs(abilityNodes) do if node.entry and node.entry.ID==25 then card=node end end
assert(card and card.name.text=='Гнев деревьев' and card.note.text=='Известно персонажу')
assert(state.used==0 and not state.learned[25])
advance();local count=#sent;card.scripts.OnClick(card,'LeftButton');assert(#sent==count)
card.scripts.OnDragStart(card);assert(picked==339)
parse('STATE 11 11 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('END');assert(not state.known[25],'known native spells must refresh, not accumulate forever')
""")

    def test_talent_window_button_attaches_after_delayed_frame_load_and_uses_native_tooltip_id(self):
        self.lua(r"""
open();parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG');parse('TENTRY 398 3 10 1 0 8 11069');parse('TALENT 398 2 12338');parse('END')
assert(compatible[398].spell==12338)
PlayerTalentFrame=CreateFrame('Frame','PlayerTalentFrame',UIParent)
for _,frame in ipairs(frames) do if frame.scripts.OnEvent then frame.scripts.OnEvent(frame,'ADDON_LOADED') end end
local button=ForeverAscensionTalentButton
assert(button and button.parent==PlayerTalentFrame and button.text=='Мультикласс')
assert(button.points[1][1]=='BOTTOMRIGHT' and button.points[1][4]==-24)
window:Hide();button.scripts.OnClick();assert(window:IsShown())
local previous=button
PlayerTalentFrame=CreateFrame('Frame','PlayerTalentFrameWithSearch',UIParent)
PlayerTalentFrame.SearchBox=CreateFrame('EditBox',nil,PlayerTalentFrame)
for _,frame in ipairs(frames) do if frame.scripts.OnEvent then frame.scripts.OnEvent(frame,'ADDON_LOADED') end end
button=ForeverAscensionTalentButton
assert(not previous:IsShown() and button.points[1][1]=='RIGHT')
assert(button.points[1][2]==PlayerTalentFrame.SearchBox and button.points[1][3]=='LEFT' and button.points[1][4]==-12)
""")

    def test_trait_description_uses_native_entry_rank_and_reports_actual_aura_values(self):
        self.lua(r"""
local requestedEntry,requestedRank,lines
C_Traits={GetTraitDescription=function(entry,rank) requestedEntry=entry;requestedRank=rank;return 'Снижение времени применения: '..(rank*2)..'%' end}
GameTooltip={SetOwner=function() end,SetText=function() end,AddLine=function(_,value) table.insert(lines,value) end,Show=function() end}
open();parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('CATALOG');parse('TENTRY 398 3 10 1 0 8 11069 700 500');parse('TALENT 398 2 11069');parse('TEFFECT 398 0 -4');parse('END')
selectedClass=8;selectedTab='Fire';refresh()
local node;for _,frame in ipairs(talentNodes) do if frame.entry and frame.entry.ID==398 then node=frame end end
lines={};tooltip(node)
assert(requestedEntry==500 and requestedRank==2)
local sawDescription,sawApplied=false,false
for _,line in ipairs(lines) do if line=='Снижение времени применения: 4%' then sawDescription=true end;if line=='Эффект 1: -4' then sawApplied=true end end
assert(sawDescription and sawApplied and state.effects[398][0]==-4)
parse('STATE 1 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('END');assert(not state.effects[398])
""")

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
open();parse('STATE 8 20 0 8');parse('ACTIVE 8');parse('CLASS 8 20 0 1000');parse('CLASS 5 20 0 1000');parse('END')
local row=byClass[8][1]
local b=abilityNodes[1];b.entry=row
advance();local count=#sent;b.scripts.OnClick(b,'LeftButton');assert(#sent==count)
compatible[row.ID]={owner=8,level=1,spell=116}
b.scripts.OnClick(b,'LeftButton');assert(#sent==count)
parse('ERROR ability_limit');assert(message.text==errors.ability_limit)
''')


if __name__=='__main__':unittest.main()
