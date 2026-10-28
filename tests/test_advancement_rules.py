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
using TalentOwners=std::map<uint32,std::set<std::pair<uint32,uint32>>>;
'''+UTF8_UTIL_STUB+function(source,'static std::wstring NameKey(')+function(source,'static bool SourceNameMatches(')+function(source,'static std::string NativeNames(')+function(source,'static uint32 ClassFamily(')+function(source,'static SpellInfo const* ResolveSpell(')+function(source,'static SpellInfo const* ResolveNativeTalent(')+r'''
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
 TalentOwners owners={{500,{{8,1}}},{501,{{5,2}}}};
 manager.spells.at(500).SpellFamilyName=0;manager.spells.at(500).SpellName=&wrong;
 assert(ResolveNativeTalent(500,8,1,owners)->Id==500);
 assert(!ResolveNativeTalent(500,5,1,owners));assert(!ResolveNativeTalent(500,8,2,owners));
 assert(!ResolveNativeTalent(999,8,1,owners));
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
struct ClassProgress {uint32 level=1;uint64_t xp=0;};
struct State {uint32 active=8;std::map<uint32,ClassProgress> classes;std::set<uint32> learned,bookSpells;};
struct Definition {uint32 entry,owner,spell,level;};
std::map<uint32,std::vector<Definition>> Catalog;
'''+''.join(function(source,name) for name in ['static uint32 ClassLevel(', 'static Definition const* Best(', 'static Definition const* BestFor(', 'static bool TemporaryBookSpell(', 'static void SyncSpellbook(Player* p,State& s)\n{','static uint32 BookEntry('])+r'''
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
 Player p;State s;s.classes[8].level=40;s.classes[5].level=40;Catalog[10]={{10,8,116,4},{10,8,205,26}};Catalog[20]={{20,5,2061,1}};
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
struct Ability {uint32 SkillLine;int ClassMask;uint32 ID=0;};
using SkillLineAbilityEntry=Ability;
std::map<uint32,Ability*> sSkillLineAbilityStore;std::vector<uint32> published;
#define TC_LOG_INFO(...) do {} while(false)
template<class T> struct DB2HotfixGenerator {
 explicit DB2HotfixGenerator(std::map<uint32,Ability*>&) {}
 void ApplyHotfix(uint32 id,void(*fix)(T*),bool notify) {assert(notify);fix(sSkillLineAbilityStore.at(id));published.push_back(id);}
};
struct Spells {std::multimap<uint32,Ability const*> rows;auto GetSkillLineAbilityMapBounds(uint32 id){return rows.equal_range(id);}} manager;
auto sSpellMgr=&manager;
struct Definition {uint32 entry,owner,spell,level;};
std::map<uint32,std::vector<Definition>> Catalog;
struct ClassProgress {uint32 level=1;uint64_t xp=0;};
struct State {uint32 active=8;std::map<uint32,ClassProgress> classes;std::set<uint32> learned;};
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
'''+(SOURCE.parent/'PlayerBookSchools.inc').read_text()+''.join(function(source,name) for name in ['static uint32 ClassLevel(', 'static Definition const* Best(', 'static Definition const* BestFor(','static void SyncBookSchools(Player* p,State const& s)\n{','static void PublishBookMetadata('])+r'''
int main() {
 Player p;State s;s.classes[8].level=40;s.classes[5].level=40;
 sSkillLineStore.rows={{6,{6,7,0}},{8,{8,7,0}},{56,{56,7,0}},{200,{200,11,0}},{201,{201,7,200}}};
 Ability frost{6,128,1},fire{8,128,2},holy{56,16,3},profession{200,0,4},child{201,128,5},wrongClass{56,16,6};
 sSkillLineAbilityStore={{1,&frost},{2,&fire},{3,&holy},{4,&profession},{5,&child},{6,&wrongClass}};
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
 PublishBookMetadata();assert(published==std::vector<uint32>({1,2,3}));
 assert(frost.ClassMask==0&&fire.ClassMask==0&&holy.ClassMask==0);
 assert(child.ClassMask==128&&wrongClass.ClassMask==16&&profession.ClassMask==0);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_combat_traits_resolve_without_legacy_talent_rows(self):
        source=SOURCE.read_text()
        code=r'''#include <cassert>
#include <map>
#include <set>
#include <vector>
using uint32=unsigned;
constexpr int DIFFICULTY_NONE=0;
struct SpellInfo {};
struct Spells {SpellInfo const* GetSpellInfo(uint32,int){return nullptr;}} spellMgr;[[maybe_unused]] auto sSpellMgr=&spellMgr;
[[maybe_unused]] int NativeNames(SpellInfo const*){return 0;}
constexpr int SKILL_CATEGORY_CLASS=7;
template<class... T> void MockLog(T const&...) {}
#define TC_LOG_INFO(...) MockLog(__VA_ARGS__)
template<class T> struct Store {
 std::vector<T const*> rows;
 auto begin()const{return rows.begin();}auto end()const{return rows.end();}
 T const* LookupEntry(uint32 id){for(auto row:rows)if(row->ID==id)return row;return nullptr;}
};
struct Skill {uint32 ID;int CategoryID;};Store<Skill> sSkillLineStore;
struct SkillTree {uint32 ID,SkillLineID,TraitTreeID;};Store<SkillTree> sSkillLineXTraitTreeStore;
struct Info {int ClassMask;};
struct Manager {std::map<uint32,std::vector<Info const*>> infos;auto GetSkillRaceClassInfo(uint32 id){return infos[id];}} sDB2Manager;
struct NodeLink {uint32 ID,TraitNodeID,TraitNodeEntryID;};Store<NodeLink> sTraitNodeXTraitNodeEntryStore;
struct Node {uint32 ID,TraitTreeID;};Store<Node> sTraitNodeStore;
struct Entry {uint32 ID;int MaxRanks,TraitDefinitionID;};Store<Entry> sTraitNodeEntryStore;
struct Definition {uint32 ID;int SpellID,VisibleSpellID;};Store<Definition> sTraitDefinitionStore;
'''+source[source.index('struct NativeTrait {'):source.index('static void PublishBookMetadata()')]+r'''
int main() {
 Skill mage{237,7},profession{200,11};sSkillLineStore.rows={&mage,&profession};
 Info mageClass{128};sDB2Manager.infos[237]={&mageClass};sDB2Manager.infos[200]={&mageClass};
 SkillTree combat{1,237,500},trade{2,200,501};sSkillLineXTraitTreeStore.rows={&combat,&trade};
 Node node{10,500},tradeNode{11,501};sTraitNodeStore.rows={&node,&tradeNode};
 Entry entry{20,3,30},tradeEntry{21,5,31},invalidRank{22,128,32};sTraitNodeEntryStore.rows={&entry,&tradeEntry,&invalidRank};
 Definition definition{30,11069,0},tradeDef{31,900,0},invalidDef{32,901,0};sTraitDefinitionStore.rows={&definition,&tradeDef,&invalidDef};
 NodeLink link{40,10,20},tradeLink{41,11,21},bad{42,10,22};sTraitNodeXTraitNodeEntryStore.rows={&link,&tradeLink,&bad};
 auto traits=LoadNativeTraits();auto result=ResolveTrait(11069,8,1,traits);
 assert(result&&result->definition==30&&result->spell==11069&&result->entry==20&&result->max==3);
 assert(ResolveTrait(11069,8,3,traits)&&!ResolveTrait(11069,8,4,traits));
 assert(!ResolveTrait(11069,11,1,traits)&&!ResolveTrait(900,8,1,traits)&&!ResolveTrait(901,8,1,traits));
 auto duplicate=*result;duplicate.definition=99;traits[11069].push_back(duplicate);
 assert(!ResolveTrait(11069,8,1,traits));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_trait_rank_bridge_preserves_native_config_and_never_learns_spells(self):
        code=r'''#include <cassert>
#include <map>
#include <optional>
using uint32=unsigned;using int32=int;
template<class T> using Optional=std::optional<T>;
struct PlayerSpellTrait {int DefinitionId,Rank;};
struct PlayerSpell {Optional<PlayerSpellTrait> Trait;};
namespace Trinity::Containers {
 template<class T> auto MapGetValuePtr(T const& map,uint32 id)->typename T::mapped_type const* {auto it=map.find(id);return it==map.end()?nullptr:&it->second;}
}
struct Player {
 std::map<uint32,PlayerSpell> m_spells;
 std::map<uint32,PlayerSpellTrait> m_foreverAdvancementTraits;
 bool HasSpell(uint32 id){return m_spells.count(id);}
 Optional<PlayerSpellTrait> GetTraitInfoForSpell(uint32 spellId)const;
 void SetForeverAdvancementTrait(uint32 spell,int32 definition,int32 rank);
};
'''+(SOURCE.parent/'PlayerTraits.inc').read_text()+r'''
int main() {
 Player p;p.SetForeverAdvancementTrait(100,700,2);
 assert(p.GetTraitInfoForSpell(100)->Rank==2&&p.m_spells.empty());
 p.SetForeverAdvancementTrait(100,700,3);assert(p.GetTraitInfoForSpell(100)->Rank==3);
 p.SetForeverAdvancementTrait(100,0,0);assert(!p.GetTraitInfoForSpell(100));
 p.SetForeverAdvancementTrait(100,0x800000,1);assert(!p.GetTraitInfoForSpell(100));
 p.SetForeverAdvancementTrait(100,700,128);assert(!p.GetTraitInfoForSpell(100));
 p.m_spells[100].Trait=PlayerSpellTrait{800,1};p.SetForeverAdvancementTrait(100,700,2);
 assert(p.GetTraitInfoForSpell(100)->DefinitionId==800&&p.GetTraitInfoForSpell(100)->Rank==1);
 p.m_foreverAdvancementTraits[100]={700,2};assert(p.GetTraitInfoForSpell(100)->DefinitionId==800);
 p.m_spells[100].Trait.reset();assert(!p.GetTraitInfoForSpell(100));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_native_ability_identity_uses_class_skill_not_machine_translation(self):
        source=SOURCE.read_text()
        code=r'''#include <array>
#include <cassert>
#include <map>
#include <vector>
using uint32=unsigned;
constexpr int DIFFICULTY_NONE=0,SKILL_CATEGORY_CLASS=7;
struct LocalizedString {std::array<char const*,2> Str;};
struct SpellInfo {uint32 Id,SpellFamilyName;LocalizedString const* SpellName;};
struct Ability {uint32 SkillLine;int ClassMask;};
struct Skill {uint32 ID;int CategoryID;uint32 ParentSkillLineID;};
struct SkillStore {std::map<uint32,Skill> rows;Skill const* LookupEntry(uint32 id){auto it=rows.find(id);return it==rows.end()?nullptr:&it->second;}} sSkillLineStore;
struct ClassInfo {int ClassMask;};
struct Manager {std::map<uint32,std::vector<ClassInfo const*>> rows;auto GetSkillRaceClassInfo(uint32 id){return rows[id];}} sDB2Manager;
struct Spells {
 std::map<uint32,SpellInfo> spells;std::multimap<uint32,Ability const*> rows;
 SpellInfo const* GetSpellInfo(uint32 id,int){auto it=spells.find(id);return it==spells.end()?nullptr:&it->second;}
 auto GetSkillLineAbilityMapBounds(uint32 id){return rows.equal_range(id);}
} manager;auto sSpellMgr=&manager;
'''+function(source,'static uint32 ClassFamily(')+function(source,'static SpellInfo const* NativeClassSpell(')+r'''
int main() {
 LocalizedString native={{"","Гнев"}},empty={{"",""}};
 manager.spells={{5176,{5176,7,&native}},{126,{126,0,&native}},{900,{900,7,&native}},{901,{901,7,&empty}}};
 sSkillLineStore.rows={{574,{574,7,0}},{354,{354,7,0}},{200,{200,11,0}}};
 ClassInfo druid{1024},warlock{256};sDB2Manager.rows={{574,{&druid}},{354,{&warlock}},{200,{&druid}}};
 Ability nature{574,1024},demonology{354,256},profession{200,1024};
 manager.rows={{5176,&nature},{126,&demonology},{900,&profession},{901,&nature}};
 assert(NativeClassSpell(5176,11)->Id==5176);assert(!NativeClassSpell(5176,8));
 assert(NativeClassSpell(126,9)->Id==126);assert(!NativeClassSpell(126,11));
 assert(!NativeClassSpell(900,11)&&!NativeClassSpell(901,11)&&!NativeClassSpell(999,11));
 nature.ClassMask=128;assert(!NativeClassSpell(5176,11));
 nature.ClassMask=0;assert(NativeClassSpell(5176,11));sDB2Manager.rows[574].clear();assert(!NativeClassSpell(5176,11));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_subclass_xp_redirect_independent_progress_and_level_cap(self):
        source=SOURCE.read_text()
        code=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <map>
using uint32=uint32_t;using uint64=uint64_t;
struct ClassProgress {uint32 level=1;uint64 xp=0;};
struct State {uint32 active=0;std::map<uint32,ClassProgress> classes;};
struct Player {uint32 level=60,cls=11;uint32 GetLevel(){return level;}uint32 GetClass(){return cls;}};
struct ObjectMgr {uint32 GetXPForLevel(uint32 level){return level*100;}} manager;
auto sObjectMgr=&manager;
'''+''.join(function(source,name) for name in ['static uint32 ClassLevel(', 'static uint32 ActiveLevel(', 'static void GrantClassXP('])+r'''
int main() {
 Player p;State s;uint32 amount=500;
 GrantClassXP(&p,s,amount);assert(amount==500&&s.classes.empty());
 s.active=8;GrantClassXP(&p,s,amount);assert(amount==0&&s.classes[8].level==3&&s.classes[8].xp==200);
 s.active=1;amount=50;GrantClassXP(&p,s,amount);
 assert(s.classes[1].level==1&&s.classes[1].xp==50&&s.classes[8].xp==200);
 auto restored=s;s=restored;s.active=8;amount=100;GrantClassXP(&p,s,amount);
 assert(s.classes[8].level==4&&s.classes[8].xp==0);
 amount=UINT32_MAX;GrantClassXP(&p,s,amount);
 assert(s.classes[8].level==40&&s.classes[8].xp==0&&ActiveLevel(&p,s)==40);
 amount=500;GrantClassXP(&p,s,amount);assert(amount==0&&s.classes[8].level==40);
 p.level=11;s.active=5;amount=UINT32_MAX;GrantClassXP(&p,s,amount);
 assert(s.classes[5].level==11&&s.classes[5].xp==0);
 p.level=12;amount=100;GrantClassXP(&p,s,amount);assert(s.classes[5].xp==100);
 assert(ClassLevel(&p,s,11)==12&&ClassLevel(&p,s,2)==1);
 assert(s.classes[1].xp==50&&s.classes[8].level==40);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_real_resource_and_mixed_class_cast_policy(self):
        source=SOURCE.read_text()
        functions='\n'.join(function(source,name) for name in ['static uint32 ClassLevel(', 'static uint32 ActiveLevel(', 'static bool Native(', 'static int32 Scale(',
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
struct TalentDefinition {uint32 entry,owner,spell,rank,level,cost,investment,tab;uint32 trait=0,traitEntry=0;};
struct Pool {int32 current=0,maximum=0;double fraction=0;};
struct ClassProgress {uint32 level=1;uint64_t xp=0;};
struct State {uint32 active=8;std::map<uint32,ClassProgress> classes;std::set<uint32> learned;std::map<uint32,uint32> talents;std::set<uint32> ownedAuras;std::map<uint32,std::pair<uint32,uint32>> ownedTraits;bool syncing=false;std::map<Powers,Pool> pools;Clock::time_point updated=Clock::now();};
struct Player {
 uint32 cls=1,level=20;bool combat=false,alive=true;
 std::set<uint32> auras,spells,removed;
 std::map<uint32,std::pair<uint32,uint32>> traits;
 std::map<uint32,uint32> appliedRanks;
 void SetForeverAdvancementTrait(uint32 spell,int definition,int rank) {if(definition&&rank&&!HasSpell(spell))traits[spell]={unsigned(definition),unsigned(rank)};else traits.erase(spell);}
 bool HasAura(uint32 id) const {return auras.count(id);}
 bool HasSpell(uint32 id) const {return spells.count(id);}
 bool AddAura(uint32 id,Player*) {auras.insert(id);appliedRanks[id]=traits.count(id)?traits[id].second:0;return true;}
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
 Player p;State s;s.classes[8].level=40;s.classes[5].level=40;Refresh(&p,s);
 p.level=60;assert(TalentBudget(&p,s)==31);p.level=20;
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
 s.talents={{100,2},{200,1}};assert(TalentSpent(s)==2 && TalentBuildValid(&p,s));
 s.talents[101]=1;assert(!TalentBuildValid(&p,s));s.talents[100]=3;assert(TalentBuildValid(&p,s));
 s.talents[100]=2;assert(!TalentBuildValid(&p,s));s.talents.erase(101);
 p.level=11;assert(TalentBudget(&p,s)==2 && TalentBuildValid(&p,s));p.level=20;
 s.talents={{100,1}};p.auras.insert(11069);SyncTalents(&p,s);
 assert(!s.ownedAuras.count(11069));s.talents.clear();SyncTalents(&p,s);assert(p.auras.count(11069));
 p.auras.clear();s.talents[100]=1;SyncTalents(&p,s);assert(s.ownedAuras.count(11069));
 s.talents[100]=2;SyncTalents(&p,s);assert(!p.auras.count(11069)&&p.auras.count(12338));
 s.active=5;s.talents[200]=1;SyncTalents(&p,s);assert(!p.auras.count(12338)&&p.auras.count(14908));
 s.active=8;SyncTalents(&p,s);assert(p.auras.count(12338)&&!p.auras.count(14908));
 s.active=0;SyncTalents(&p,s);assert(!p.auras.count(12338)&&TalentBudget(&p,s)==0);
 s.active=8;SyncTalents(&p,s);
 s.talents.clear();SyncTalents(&p,s);assert(!p.auras.count(12338));
 s.talents[100]=1;p.cls=8;assert(!TalentBuildValid(&p,s));p.cls=1;
 TalentCatalog[300]={{300,8,900,1,10,1,0,30,700},{300,8,900,2,10,1,0,30,700},{300,8,900,3,10,1,0,30,700}};
 s.talents={{300,1}};SyncTalents(&p,s);assert(p.appliedRanks[900]==1&&s.ownedTraits.at(900).second==1);
 s.talents[300]=2;SyncTalents(&p,s);assert(p.appliedRanks[900]==2&&p.removed.count(900));
 s.talents[300]=1;SyncTalents(&p,s);assert(p.appliedRanks[900]==1);
 s.talents.clear();SyncTalents(&p,s);assert(!p.auras.count(900)&&!p.traits.count(900));
 p.auras.insert(900);s.talents={{300,1}};SyncTalents(&p,s);assert(!s.ownedAuras.count(900)&&!p.traits.count(900));
 s.talents.clear();SyncTalents(&p,s);assert(p.auras.count(900));
 p.auras.clear();s.talents={{300,1}};SyncTalents(&p,s);p.spells.insert(900);
 s.talents.clear();SyncTalents(&p,s);assert(p.auras.count(900)&&!p.traits.count(900));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            compile=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(compile.returncode,0,compile.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
