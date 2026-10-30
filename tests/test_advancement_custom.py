import ctypes.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_advancement as advancement
import test_advancement_rules as rules

MODULE=advancement.MODULE
load=advancement.load


class CustomCatalogTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'),'C++20 compiler required')
    def test_real_request_rejects_both_ids_without_purchases_or_resource_payment(self):
        source=(MODULE/'server/ForeverAdvancement.cpp').read_text()
        code=r'''
#include "CustomAbilityRules.h"
#include <chrono>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>
#include <cassert>
using uint32=unsigned;
using Clock=std::chrono::steady_clock;
struct Unit {};
struct CastTag {uint32 entry;};
struct CastSpellExtraArgs {explicit CastSpellExtraArgs(int){} CastSpellExtraArgs& SetCustomArg(CastTag){return *this;}};
constexpr int UNIT_STATE_CASTING=1,DIFFICULTY_NONE=0,TRIGGERED_IGNORE_POWER_COST=1,SPELL_CAST_OK=0;
struct Definition {uint32 entry,owner,spell,level;};
struct State {uint32 active=0;std::map<uint32,uint32> classes,talents;std::set<uint32> learned;Clock::time_point request{};};
struct Player:Unit {uint32 cls=1;int casts=0;uint32 GetClass(){return cls;}
 bool IsInCombat(){return false;}bool IsAlive(){return true;}bool HasUnitState(int){return false;}
 bool HasSpell(unsigned){return false;}Unit* GetSelectedUnit(){return this;}
 int CastSpell(Unit*,unsigned,CastSpellExtraArgs const&){++casts;return 0;}
};
struct SpellInfo {bool IsPositive()const{return true;}};
struct SpellMgr {SpellInfo info;SpellInfo const* GetSpellInfo(unsigned,int){return &info;}} manager;
auto sSpellMgr=&manager;
struct TalentDefinition {uint32 owner;};
std::map<uint32,std::vector<Definition>> Catalog;
std::recursive_mutex Mutex;bool Ready=true;uint32 Limit=8;State state;
std::string error;int saves=0;
State& Get(Player*){return state;}
bool SupportedClass(unsigned){return true;}
void Error(Player*,char const* text){error=text;}
void Send(Player*,std::string const&){}
namespace Trinity {template<class... T>std::string StringFormat(char const* text,T...){return text;}}
void Snapshot(Player*,State&,bool=false){}
Definition const* BestFor(Player*,State const&,uint32 id){auto it=Catalog.find(id);return it==Catalog.end()?nullptr:&it->second.front();}
bool CanCast(Player*,State const&,Definition const&){return true;}
void SyncTalents(Player*,State&){} void SyncBookSchools(Player*,State&){} void SyncSpellbook(Player*,State&){}
void Refresh(Player*,State&){} void Save(Player*,State const&){++saves;}
TalentDefinition const* Talent(unsigned,unsigned){return nullptr;}
bool TalentBuildValid(Player*,State const&){return true;}
uint32 Used(State const& s){return s.learned.size();}
'''+rules.function(source,'static uint32 CustomMagicCount(')+rules.function(source,'static void Request(')+r'''
int main(){
 Player p;Catalog[10]={{10,8,116,1}};Catalog[20]={{20,5,2050,1}};
 auto request=[&](std::string text){state.request={};error.clear();Request(&p,text);};
 state.learned={10};state.classes[5]=40;request("learn 1300");
 assert(error=="custom_class_requirements"&&state.learned==std::set<unsigned>{10}&&saves==0);
 state.learned={10,20};
 for(auto id:{1300,34782})for(auto action:{"learn ","cast "}){
  request(std::string(action)+std::to_string(id));
  assert(error=="custom_requires_port"&&state.learned==std::set<unsigned>({10,20})&&saves==0&&p.casts==0);
 }
 state.learned.insert(1300);request("unlearn 10");
 assert(error=="refund_custom_first"&&state.learned.count(10)&&saves==0);
 request("unlearn 34782");assert(error.empty()&&!state.learned.count(1300)&&saves==1);
 request("unlearn 10");assert(error.empty()&&state.learned==std::set<unsigned>{20}&&saves==2);
 p.cls=2;request("learn 1300");assert(error=="custom_requires_port"); // Main Paladin + Priest.
 p.cls=8;state.learned={10};request("cast 1300");assert(error=="custom_class_requirements");
 assert(p.casts==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'requests.cpp';path.write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror','-I',str(MODULE/'server'),str(path),'-o',str(root/'requests')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'requests')],check=True,capture_output=True)

    def test_custom_spell_is_excluded_from_native_seed_without_changing_source_catalog(self):
        rows=json.loads((MODULE/'catalog/CharacterAdvancementData.json').read_text())
        self.assertEqual([row['ID'] for row in rows if row['Spells']==[701463]],[1300,34782])
        header=(MODULE/'server/AscensionCatalog.h').read_text()
        self.assertNotIn('{1300,',header)
        self.assertNotIn('{34782,',header)
        self.assertIn('{109,8,1463,',header)
        self.assertNotIn("(701463,'spell_forever_advancement')",(MODULE/'sql/world.sql').read_text())

    def test_registry_rejects_repeated_aliases_unrelated_spells_and_unimplemented_activation(self):
        importer=load('import-ascension-content.py')
        rows=json.loads((MODULE/'catalog/CharacterAdvancementData.json').read_text())
        original=json.loads((MODULE/'catalog/CustomAbilities.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'catalog').mkdir()
            path=root/'catalog/CustomAbilities.json'
            for change in ({'aliases':[34782,34782]},{'spell':1463},{'implemented':True}):
                data=json.loads(json.dumps(original));data['abilities'][0].update(change)
                path.write_text(json.dumps(data))
                with self.subTest(change=change),self.assertRaises(ValueError):importer.custom_rules(root,rows)

    @unittest.skipUnless(shutil.which('g++'),'C++20 compiler required')
    def test_server_rules_deduplicate_purchases_and_count_only_distinct_ordinary_magic_classes(self):
        code='#include "CustomAbilityRules.h"\n#include <cassert>\n#include <map>\n'+r'''
using namespace ForeverAdvancementCustom;
int main() {
    assert(Canonical(34782)==1300&&Canonical(1300)==1300&&Canonical(109)==109);
    assert(Find(1300)==Find(34782)&&!Find(109)&&!Find(1463));
    std::set<unsigned> restored;
    for(auto id:{1300u,34782u,109u}) restored.insert(Canonical(id));
    assert(restored==std::set<unsigned>({109,1300}));
    std::map<unsigned,unsigned> owners={{10,8},{11,8},{20,5},{30,2},{40,1},{1300,8},{34782,8}};
    auto owner=[&](unsigned id){return owners.count(id)?owners.at(id):0;};
    assert(MagicCount(1,{},owner)==0);
    assert(MagicCount(1,{10,11},owner)==1);
    assert(MagicCount(1,{10,11,20},owner)==2);
    assert(MagicCount(2,{20},owner)==2); // Paladin is magical.
    assert(MagicCount(8,{10,11},owner)==1); // Main Mage is not counted twice.
    assert(MagicCount(1,{1300,34782,999},owner)==0);
    auto rule=Find(1300);
    assert(!RequirementsMet(*rule,1)&&RequirementsMet(*rule,2));
    assert(!CanUse(*rule,0)&&!CanUse(*rule,2)&&!CanUse(*rule,6));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'rules.cpp';source.write_text(code)
            subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror','-I',str(MODULE/'server'),str(source),'-o',str(root/'rules')],check=True,capture_output=True)
            subprocess.run([str(root/'rules')],check=True,capture_output=True)


@unittest.skipUnless(ctypes.util.find_library('lua5.4'),'Lua 5.4 required')
class CustomUITests(unittest.TestCase):
    lua=advancement.AdvancementUITests.lua
    def test_one_custom_card_no_mage_duplicate_and_native_mana_shield_is_retained(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 1 30 0 8');parse('ACTIVE 8');parse('CLASS 8 30 0 1000');parse('CATALOG')
parse('CUSTOM 1300 701463 2 1 0 0');parse('END')
selectedClass=8;selectedTab='Arcane';showAll=true;refresh()
local abilities=visible();local shield=false
for _,row in ipairs(abilities) do assert(row.Spells[1]~=701463);if row.Spells[1]==1463 then shield=true end end
assert(shield)
customButton.scripts.OnClick();assert(selectedClass==0)
abilities=visible();assert(#abilities==1 and abilities[1].ID==1300)
assert(not activateButton:IsShown() and not talentScroll:IsShown() and customHelp:IsShown())
local n=abilityNodes[1];assert(n.entry.ID==1300 and n.note.text:find('1/2',1,true))
local before=#sent;advance();n.scripts.OnClick(n,'LeftButton')
assert(#sent==before and message.text==errors.custom_class_requirements)
advance();n.scripts.OnDragStart(n);assert(#sent==before)
parse('STATE 1 30 0 8');parse('ACTIVE 8');parse('CUSTOM 1300 701463 2 2 0 0');parse('END')
advance();n.scripts.OnClick(n,'LeftButton');assert(#sent==before and message.text==errors.custom_requires_port)
assert(n.note.text:find('2/2',1,true))
''')

    def test_saved_aliases_have_one_card_and_refund_uses_canonical_id(self):
        self.lua(r'''
open();parse('PROTOCOL 3');parse('STATE 2 30 0 8');parse('ACTIVE 5');parse('CUSTOM 1300 701463 2 2 0 1')
parse('LEARNED 1300');parse('LEARNED 34782');parse('END')
assert(state.learned[1300] and not state.learned[34782])
customButton.scripts.OnClick();local abilities=visible();assert(#abilities==1)
advance();abilityNodes[1].scripts.OnClick(abilityNodes[1],'RightButton');assert(sent[#sent]=='unlearn 1300')
parse('STATE 2 30 0 8');parse('ACTIVE 5');parse('CUSTOM 1300 701463 2 1 0 0');parse('END')
assert(not state.learned[1300] and state.custom[1300].count==1)
''')

    def test_old_server_does_not_enable_custom_purchases(self):
        self.lua(r'''
open();parse('PROTOCOL 2');parse('STATE 1 30 0 8');parse('END');customButton.scripts.OnClick()
local before=#sent;advance();abilityNodes[1].scripts.OnClick(abilityNodes[1],'LeftButton')
assert(#sent==before and message.text:find('Обновите сервер',1,true))
''')
