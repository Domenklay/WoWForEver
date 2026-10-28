import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

SOURCE=Path(__file__).parents[1]/'mods/forever-advancement/server/ForeverAdvancement.cpp'


def function(source,signature):
    start=source.index(signature);end=source.index('{',start)+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]


UTF8_UTIL_STUB=r'''
#include <codecvt>
#include <locale>
#include <cwctype>
#include <clocale>
#include <string>
bool Utf8toWStr(char const* text,std::wstring& out) {
 try {out=std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(text);return true;}
 catch(...) {return false;}
}
void wstrToLower(std::wstring& text) {
 std::setlocale(LC_CTYPE,"C.UTF-8");for(auto& c:text)c=std::towlower(c);
}
'''


@unittest.skipUnless(shutil.which('g++'),'C++20 compiler required')
class AdvancementRuleTests(unittest.TestCase):
    def test_name_resolution_rejects_wrong_class_rank_and_ambiguity(self):
        source=SOURCE.read_text()
        code=r'''#include <algorithm>
#include <array>
#include <cassert>
#include <map>
#include <set>
#include <string>
#include <string_view>
#include <vector>
using uint32=unsigned;
constexpr int DIFFICULTY_NONE=0,TOTAL_LOCALES=2;
struct LocalizedString {std::array<char const*,2> Str;};
struct SpellInfo {uint32 Id,SpellFamilyName;LocalizedString const* SpellName;};
struct SpellMgr {
 std::map<uint32,SpellInfo> spells;std::map<uint32,uint32> ranks;
 SpellInfo const* GetSpellInfo(uint32 id,int) {auto it=spells.find(id);return it==spells.end()?nullptr:&it->second;}
 uint32 GetSpellRank(uint32 id) {return ranks[id];}
} manager;
auto sSpellMgr=&manager;
using NameIndex=std::map<std::wstring,std::vector<SpellInfo const*>>;
'''+UTF8_UTIL_STUB+function(source,'static std::wstring NameKey(')+function(source,'static bool SourceNameMatches(')+function(source,'static std::string NativeNames(')+function(source,'static uint32 ClassFamily(')+function(source,'static SpellInfo const* ResolveSpell(')+r'''
int main() {
 LocalizedString frost={{"Frostbolt","Ледяная стрела"}},wrong={{"Something else",nullptr}};
 manager.spells.emplace(116,SpellInfo{116,3,&wrong});
 manager.spells.emplace(500,SpellInfo{500,3,&frost});manager.ranks[500]=1;
 std::array<char const*,9> names={"FROSTBOLT","Ледяная Стрела"};
 NameIndex index;index[NameKey("Frostbolt")]={&manager.spells.at(500)};
 assert(ResolveSpell(116,8,1,names,index)->Id==500);
 assert(!ResolveSpell(116,5,1,names,index));assert(!ResolveSpell(116,8,2,names,index));
 manager.spells.emplace(501,SpellInfo{501,3,&frost});manager.ranks[501]=1;
 index[NameKey("Frostbolt")].push_back(&manager.spells.at(501));
 assert(!ResolveSpell(116,8,1,names,index));
 // A Russian-only native store must accept title-case archive names.
 frost.Str[0]="";NameIndex russian;russian[NameKey("Ледяная стрела")]={&manager.spells.at(500)};
 assert(ResolveSpell(116,8,1,names,russian)->Id==500);
 assert(NativeNames(&manager.spells.at(500)).find("1:Ледяная стрела")!=std::string::npos);
 assert(NativeNames(nullptr)=="<missing>");
 LocalizedString empty={{"",""}};SpellInfo unnamed{1,3,&empty};
 assert(NativeNames(&unnamed)=="<empty all locales>");
 assert(NameKey("Удар В Спину")==NameKey("Удар в спину"));
 assert(NameKey("СНЕЖНАЯ БУРЯ")==NameKey("Снежная буря"));
 assert(NameKey("ÉCLAIR DE GIVRE")==NameKey("éclair de givre"));
 assert(NameKey("Ледяная стрела")!=NameKey("Огненная стрела"));
 assert(NameKey(nullptr).empty()&&NameKey("").empty());
 // A known, matching native ID takes precedence over ambiguous name searches.
 assert(ResolveSpell(500,8,1,names,index)->Id==500);
 assert(!ResolveSpell(999,8,1,{},index));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_native_spellbook_ownership_login_rank_upgrade_and_refund(self):
        source=SOURCE.read_text()
        code=r'''#include <algorithm>
#include <any>
#include <mutex>
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
using uint32=uint32_t;
constexpr int PLAYERSPELL_TEMPORARY=5,PERMANENT=0;
struct PlayerSpell {int state;};
namespace WorldPackets::Spells {
 struct LearnedSpellInfo {uint32 SpellID;bool Favorite;};
 struct LearnedSpells {std::vector<LearnedSpellInfo> ClientLearnedSpellData;bool SuppressMessaging=false;LearnedSpells* Write(){return this;}};
 struct UnlearnedSpells {std::vector<uint32> SpellID;UnlearnedSpells* Write(){return this;}};
}
struct Player {
 Player* ToPlayer(){return this;}
 uint32 cls=1,level=20;bool world=true;std::map<uint32,PlayerSpell> spells;
 std::vector<uint32> added,removed;
 uint32 GetClass(){return cls;}uint32 GetLevel(){return level;}
 bool IsInWorld(){return world;}bool HasSpell(uint32 id){return spells.count(id);}
 auto const& GetSpellMap(){return spells;}
 void AddTemporarySpell(uint32 id){spells.try_emplace(id,PlayerSpell{PLAYERSPELL_TEMPORARY});}
 void RemoveTemporarySpell(uint32 id){auto it=spells.find(id);if(it!=spells.end()&&it->second.state==PLAYERSPELL_TEMPORARY)spells.erase(it);}
 void SendDirectMessage(WorldPackets::Spells::LearnedSpells* p){for(auto row:p->ClientLearnedSpellData)added.push_back(row.SpellID);}
 void SendDirectMessage(WorldPackets::Spells::UnlearnedSpells* p){for(auto id:p->SpellID)removed.push_back(id);}
};
struct State {std::set<uint32> learned,bookSpells;};
struct Definition {uint32 entry,owner,spell,level;};
std::map<uint32,std::vector<Definition>> Catalog;
'''+''.join(function(source,name) for name in ['static Definition const* Best(', 'static bool TemporaryBookSpell(', 'static void SyncSpellbook(Player* p,State& s)\n{','static uint32 BookEntry('])+r'''
namespace ForeverAdvancement {}
struct CastTag {uint32 entry;};
bool Ready=true;std::recursive_mutex Mutex;State* current;
State& Get(Player*) {return *current;}
struct SpellInfo {uint32 Id=116;};
struct MockSpell {std::any m_customArg;bool triggered=false,ignored=false;void* m_CastItem=nullptr;
 bool IsTriggered(){return triggered;}void IgnorePowerCostForForeverAdvancement(){ignored=true;}};
struct Loader {
 Player* player;MockSpell* spell;SpellInfo info;
 Player* GetCaster(){return player;}MockSpell* GetSpell(){return spell;}SpellInfo* GetSpellInfo(){return &info;}
'''+function(source,'    bool Load() override').replace(' override','')+r'''
};
int main() {
 Player p;State s;Catalog[10]={{10,8,116,4},{10,8,205,26}};Catalog[20]={{20,5,2061,1}};
 s.learned={10,20};p.spells[2061]={PERMANENT};SyncSpellbook(&p,s);
 assert(p.HasSpell(116)&&p.HasSpell(2061)&&s.bookSpells==std::set<uint32>{116});
 current=&s;MockSpell cast;Loader loader{&p,&cast,{116}};
 assert(loader.Load()&&cast.ignored&&std::any_cast<CastTag>(cast.m_customArg).entry==10);
 cast={};cast.triggered=true;assert(loader.Load()&&!cast.ignored&&!cast.m_customArg.has_value());
 cast={};cast.m_CastItem=&p;assert(loader.Load()&&!cast.ignored);
 cast={};loader.info.Id=2061;assert(loader.Load()&&!cast.ignored&&!cast.m_customArg.has_value());
 cast={};cast.m_customArg=CastTag{10};loader.info.Id=116;assert(loader.Load()&&!cast.ignored);
 cast={};cast.m_customArg=42;assert(loader.Load()&&!cast.ignored&&std::any_cast<int>(cast.m_customArg)==42);
 assert(p.added==std::vector<uint32>{116}&&BookEntry(&p,s,116)==10&&BookEntry(&p,s,2061)==0);
 SyncSpellbook(&p,s);assert(p.added.size()==1);
 p.level=26;SyncSpellbook(&p,s);assert(!p.HasSpell(116)&&p.HasSpell(205));
 assert(BookEntry(&p,s,116)==0&&BookEntry(&p,s,205)==10&&p.removed.back()==116);
 s.learned.clear();SyncSpellbook(&p,s);assert(!p.HasSpell(205)&&p.HasSpell(2061)&&s.bookSpells.empty());
 assert(p.removed.back()==205);
 // Purchase remains authoritative across relog. A native spell is never removed.
 p.spells.clear();s.bookSpells.clear();s.learned={10};p.world=false;auto packets=p.added.size();
 SyncSpellbook(&p,s);assert(p.HasSpell(205)&&p.added.size()==packets);
 // A spell promoted by another system to permanent stops belonging to this module.
 p.world=true;p.spells[205].state=PERMANENT;auto removed=p.removed.size();
 SyncSpellbook(&p,s);assert(s.bookSpells.empty()&&BookEntry(&p,s,205)==0);
 s.learned.clear();SyncSpellbook(&p,s);assert(p.HasSpell(205)&&p.removed.size()==removed);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_native_school_skills_are_transient_and_never_grant_other_spells(self):
        source=SOURCE.read_text()
        code=r'''#include <algorithm>
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
using uint32=uint32_t;
constexpr int SKILL_CATEGORY_CLASS=7,SKILL_UNCHANGED=0;
struct Skill {uint32 ID,CategoryID,ParentSkillLineID;};
struct Skills {std::map<uint32,Skill> rows;Skill const* LookupEntry(uint32 id){auto it=rows.find(id);return it==rows.end()?nullptr:&it->second;}} sSkillLineStore;
struct Ability {uint32 SkillLine;int ClassMask;};
struct Spells {std::multimap<uint32,Ability const*> rows;auto GetSkillLineAbilityMapBounds(uint32 id){return rows.equal_range(id);}} manager;
auto sSpellMgr=&manager;
struct Definition {uint32 entry,owner,spell,level;};
std::map<uint32,std::vector<Definition>> Catalog;
struct State {std::set<uint32> learned;};
struct Status {int uState=1;};
struct Player {
 uint32 cls=1,level=20;std::set<uint32> m_foreverAdvancementClassSkills,skills;
 std::map<uint32,Status> mSkillStatus;int rewarded=0,removedSpells=0;
 uint32 GetLevel(){return level;}uint32 GetClass(){return cls;}
 bool HasSkill(uint32 id){return skills.count(id);}
 void SetSkill(uint32 id,int,int value,int,bool edit=false) {
  if(value) {skills.insert(id);if(!edit)++rewarded;}
  else {skills.erase(id);if(!edit)++removedSpells;}
  mSkillStatus[id]={1};
 }
 void SyncForeverAdvancementClassSkills(std::set<uint32> const& desired);
};
'''+(SOURCE.parent/'PlayerBookSchools.inc').read_text()+''.join(function(source,name) for name in ['static Definition const* Best(','static void SyncBookSchools(Player* p,State const& s)\n{'])+r'''
int main() {
 Player p;State s;
 sSkillLineStore.rows={{6,{6,7,0}},{8,{8,7,0}},{56,{56,7,0}},{200,{200,11,0}},{201,{201,7,200}}};
 Ability frost{6,128},fire{8,128},holy{56,16},profession{200,0},child{201,128},wrongClass{56,16};
 manager.rows={{116,&frost},{116,&profession},{116,&child},{116,&wrongClass},{133,&fire},{2061,&holy}};
 Catalog={{10,{{10,8,116,4}}},{11,{{11,8,133,4}}},{20,{{20,5,2061,1}}}};
 p.skills.insert(8);s.learned={10,11};SyncBookSchools(&p,s);
 assert(p.skills==std::set<uint32>({6,8})&&p.m_foreverAdvancementClassSkills==std::set<uint32>{6});
 assert(!p.rewarded&&!p.removedSpells);
 s.learned.insert(20);SyncBookSchools(&p,s);assert(p.HasSkill(56));
 s.learned.erase(10);SyncBookSchools(&p,s);assert(!p.HasSkill(6)&&p.mSkillStatus[6].uState==SKILL_UNCHANGED);
 s.learned.clear();SyncBookSchools(&p,s);assert(p.skills==std::set<uint32>{8}&&p.m_foreverAdvancementClassSkills.empty());
 p.SyncForeverAdvancementClassSkills({200,201,999});assert(p.skills==std::set<uint32>{8});
 assert(!p.rewarded&&!p.removedSpells);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_real_resource_and_mixed_class_cast_policy(self):
        source=SOURCE.read_text()
        functions='\n'.join(function(source,name) for name in ['static bool Native(', 'static int32 Scale(',
            'static void Refresh(', 'static int32 Available(', 'static Definition const* Best(',
            'static uint32 Used(', 'static int32 Cost(', 'static bool CompatibleCosts(', 'static bool CanCast(',
            'static TalentDefinition const* Talent(', 'static uint32 TalentBudget(', 'static uint32 TalentSpent(',
            'static uint32 LowerTierSpent(', 'static bool TalentBuildValid(', 'static void SyncTalents(Player* p,State& s)\n{', 'static std::wstring NameKey(', 'static bool SourceNameMatches('])
        code=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <map>
#include <set>
#include <vector>
#include <cstdint>
using uint32=uint32_t;using int32=int32_t;using uint64=uint64_t;
using Clock=std::chrono::steady_clock;
enum Powers {POWER_MANA=0,POWER_RAGE=1,POWER_ENERGY=3};
constexpr int MAX_POWERS_PER_CLASS=6,CLASS_PRIEST=5,STAT_SPIRIT=4,DIFFICULTY_NONE=0,SPELL_ATTR1_USE_ALL_MANA=1;
constexpr std::array<Powers,3> PowersList={POWER_MANA,POWER_RAGE,POWER_ENERGY};
struct Definition { uint32 entry,owner,spell,level; };
struct TalentDefinition {uint32 entry,owner,spell,rank,level,cost,investment,tab;};
struct Pool {int32 current=0,maximum=0;double fraction=0;};
struct State {std::set<uint32> learned;std::map<uint32,uint32> talents;std::set<uint32> ownedAuras;bool syncing=false;std::map<Powers,Pool> pools;Clock::time_point updated=Clock::now();};
struct Player {
 uint32 cls=1,level=20;bool combat=false,alive=true;
 std::set<uint32> auras,spells,removed;
 bool HasAura(uint32 id) const {return auras.count(id);}
 bool HasSpell(uint32 id) const {return spells.count(id);}
 bool AddAura(uint32 id,Player*) {auras.insert(id);return true;}
 int GetGUID() const {return 1;}
 void RemoveAurasDueToSpell(uint32 id,int) {auras.erase(id);removed.insert(id);}
 int GetPowerIndex(Powers power) const {return power==POWER_RAGE?0:MAX_POWERS_PER_CLASS;}
 int GetMaxPower(Powers power) const {return power==POWER_RAGE?1000:0;}
 int GetPower(Powers power) const {return power==POWER_RAGE?250:0;}
 uint32 GetLevel() const {return level;}uint32 GetClass() const {return cls;}
 double GetManaBonusFromIntellect() const {return 50;}
 double GetStat(int) const {return 20;}
 bool IsInCombat() const {return combat;}bool IsAlive() const {return alive;}
};
struct ObjectMgr {void GetPlayerClassLevelInfo(int cls,int,uint32& base) {assert(cls==5);base=500;}} objectMgr;
auto sObjectMgr=&objectMgr;
struct PowerCost {int Amount=30;};
struct SpellPowerEntry {int PowerType=0,ManaPerSecond=0,PowerPctPerSecond=0,OptionalCost=0,OptionalCostPct=0,RequiredAuraSpellID=0,PowerCostPct=0,PowerCostMaxPct=0,ManaCost=20,ManaCostPerLevel=0;};
struct LocalizedString {std::array<char const*,3> Str={};};
struct SpellInfo {
 LocalizedString const* SpellName=nullptr;
 std::array<SpellPowerEntry const*,2> PowerCosts={};
 bool HasAttribute(int) const {return false;}
 PowerCost cost;mutable PowerCost adjustedCost;
 PowerCost const* CalcPowerCost(Powers power,bool,Player*,int) const {return power==POWER_MANA?&cost:nullptr;}
 PowerCost const* CalcPowerCost(SpellPowerEntry const* row,bool,Player*,int) const {adjustedCost.Amount=row->ManaCost;return &adjustedCost;}
 int GetSchoolMask() const {return 1;}
};
struct SpellMgr {SpellInfo info;SpellInfo const* GetSpellInfo(uint32,int) {return &info;}} spellMgr;
auto sSpellMgr=&spellMgr;
std::map<uint32,std::vector<Definition>> Catalog;
std::map<uint32,std::vector<TalentDefinition>> TalentCatalog;
uint32 TalentCap=71;
'''+UTF8_UTIL_STUB+functions+r'''
int main() {
 Player p;State s;Refresh(&p,s);
 LocalizedString nativeNames;nativeNames.Str[1]="Ледяная стрела";spellMgr.info.SpellName=&nativeNames;
 std::array<char const*,9> aliases={"Frostbolt","Ледяная стрела","","","","","","",""};
 assert(SourceNameMatches(&spellMgr.info,aliases));nativeNames.Str[1]="Другое заклинание";
 assert(!SourceNameMatches(&spellMgr.info,aliases));spellMgr.info.SpellName=nullptr;assert(!SourceNameMatches(&spellMgr.info,aliases));
 assert(s.pools.size()==2 && !s.pools.count(POWER_RAGE));
 assert(Available(&p,s,POWER_MANA)==550 && Available(&p,s,POWER_ENERGY)==100);
 assert(Available(&p,s,POWER_RAGE)==25);
 Catalog[10]={{10,8,116,4},{10,8,205,26}};Catalog[20]={{20,5,2061,20}};
 s.learned={10,20};assert(Used(s)==2);
 auto mage=Best(10,20);auto priest=Best(20,20);
 assert(mage->spell==116 && Best(10,30)->spell==205 && !Best(10,1));
 assert(CanCast(&p,s,*mage) && CanCast(&p,s,*priest));
 SpellPowerEntry unsupported;unsupported.PowerType=4;spellMgr.info.PowerCosts[0]=&unsupported;
 assert(!CanCast(&p,s,*mage));unsupported.PowerType=0;unsupported.OptionalCost=10;
 assert(!CanCast(&p,s,*mage));unsupported.OptionalCost=0;unsupported.PowerCostPct=10;
 assert(CanCast(&p,s,*mage));assert(Cost(&p,&spellMgr.info,POWER_MANA)==70);
 unsupported.PowerType=3;assert(!CanCast(&p,s,*mage));spellMgr.info.PowerCosts[0]=nullptr;
 s.learned.erase(10);assert(!CanCast(&p,s,*mage));s.learned.insert(10);
 s.pools[POWER_MANA].current=29;assert(!CanCast(&p,s,*mage));
 s.pools[POWER_MANA].current=30;assert(CanCast(&p,s,*mage));
 p.cls=8;assert(!CanCast(&p,s,*mage));p.cls=1;
 p.alive=false;assert(!CanCast(&p,s,*mage));p.alive=true;
 p.level=1;assert(!CanCast(&p,s,*mage));p.level=20;
 s.pools[POWER_ENERGY].current=0;s.updated=Clock::now()-std::chrono::seconds(1);Refresh(&p,s);
 assert(s.pools[POWER_ENERGY].current>=9 && s.pools[POWER_ENERGY].current<=11);
 TalentCatalog[100]={{100,8,11069,1,10,1,0,10},{100,8,12338,2,10,1,0,10},{100,8,12339,3,10,1,0,10}};
 TalentCatalog[101]={{101,8,11083,1,15,1,3,10}};
 TalentCatalog[200]={{200,5,14908,1,10,1,0,20}};
 s.talents={{100,2},{200,1}};assert(TalentSpent(s)==3 && TalentBuildValid(&p,s));
 s.talents[101]=1;assert(!TalentBuildValid(&p,s));s.talents[100]=3;assert(TalentBuildValid(&p,s));
 s.talents[100]=2;assert(!TalentBuildValid(&p,s));s.talents.erase(101);
 p.level=11;assert(TalentBudget(&p)==2 && !TalentBuildValid(&p,s));p.level=20;
 s.talents={{100,1}};p.auras.insert(11069);SyncTalents(&p,s);
 assert(!s.ownedAuras.count(11069));s.talents.clear();SyncTalents(&p,s);assert(p.auras.count(11069));
 p.auras.clear();s.talents[100]=1;SyncTalents(&p,s);assert(s.ownedAuras.count(11069));
 s.talents[100]=2;SyncTalents(&p,s);assert(!p.auras.count(11069)&&p.auras.count(12338));
 s.talents.clear();SyncTalents(&p,s);assert(!p.auras.count(12338));
 s.talents[100]=1;p.cls=8;assert(!TalentBuildValid(&p,s));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            compile=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(compile.returncode,0,compile.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
