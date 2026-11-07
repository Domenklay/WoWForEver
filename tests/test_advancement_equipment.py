from pathlib import Path
import shutil,subprocess,tempfile,unittest

ROOT=Path(__file__).parents[1]

@unittest.skipUnless(shutil.which('g++'),'C++20 compiler needed')
class EquipmentTests(unittest.TestCase):
 def test_transient_proficiency_never_removes_original_or_newly_trained_native_skills(self):
  code=r'''
#include <cassert>
#include <map>
#include <set>
#include <vector>
#include <cstdint>
using uint32=uint32_t;using uint16=uint16_t;
constexpr int PLAYERSPELL_REMOVED=9,PLAYERSPELL_TEMPORARY=5,SKILL_UNCHANGED=0,DIFFICULTY_NONE=0;
constexpr int ITEM_CLASS_WEAPON=2,ITEM_CLASS_ARMOR=4,SPELL_EFFECT_PROFICIENCY=1,SPELL_EFFECT_DUAL_WIELD=2;
struct SpellInfo {int EquippedItemClass=0;uint32 EquippedItemSubClassMask=0;int effect=1;bool HasEffect(int e)const{return e==effect;}};
struct Ability {uint32 SkillLine;};
struct Manager {
 std::map<uint32,SpellInfo> infos;std::multimap<uint32,Ability*> links;
 SpellInfo const* GetSpellInfo(uint32 id,int){auto it=infos.find(id);return it==infos.end()?nullptr:&it->second;}
 auto GetSkillLineAbilityMapBounds(uint32 id){return links.equal_range(id);}
} manager;
auto sSpellMgr=&manager;
struct PlayerSpell {int state=0;};struct Status {int uState=1;};
struct Player {
 std::set<uint32> m_foreverAdvancementEquipmentSkills,skills;std::map<uint32,Status> mSkillStatus;
 uint32 m_WeaponProficiency=1,m_ArmorProficiency=1,m_foreverAdvancementWeapons=0,m_foreverAdvancementArmor=0,m_foreverAdvancementOwner=0;
 bool m_foreverAdvancementDual=false,dual=false;
 std::map<uint32,PlayerSpell> m_spells;std::vector<uint32> removed;
 bool HasSkill(uint32 id)const{return skills.count(id);}
 void SetSkill(uint32 id,int,uint16 value,uint16,bool edit){assert(edit);if(value)skills.insert(id);else{skills.erase(id);removed.push_back(id);}}
 bool CanDualWield()const{return dual;}void SetCanDualWield(bool value){dual=value;}
 bool IsInWorld(){return true;}void SendProficiency(int,uint32){}
 void SyncForeverAdvancementEquipment(uint32,std::set<uint32> const&,uint16,uint32,uint32,bool);
};
'''+(ROOT/'mods/forever-advancement/server/PlayerEquipment.inc').read_text()+r'''
int main(){
 Player p;p.skills={43};p.SyncForeverAdvancementEquipment(3,{43,44},5,3,3,true);
 assert(p.skills==std::set<uint32>({43,44})&&p.m_foreverAdvancementEquipmentSkills==std::set<uint32>({44}));
 assert(p.m_WeaponProficiency==3&&p.m_ArmorProficiency==3&&p.dual);
 p.SyncForeverAdvancementEquipment(0,{},1,0,0,false);
 assert(p.skills==std::set<uint32>({43})&&p.m_WeaponProficiency==1&&p.m_ArmorProficiency==1&&!p.dual);
 p.SyncForeverAdvancementEquipment(3,{44},5,2,2,true);
 manager.infos[201]={ITEM_CLASS_WEAPON,2,SPELL_EFFECT_PROFICIENCY};Ability sword{44};manager.links.emplace(201,&sword);p.m_spells[201]={0};
 p.SyncForeverAdvancementEquipment(0,{},1,0,0,false);
 assert(p.skills.count(44)&&p.m_WeaponProficiency==3&&p.m_ArmorProficiency==1);
 assert(p.m_foreverAdvancementEquipmentSkills.empty()&&p.m_foreverAdvancementOwner==0);
 Player rogue;rogue.dual=true;rogue.SyncForeverAdvancementEquipment(0,{},1,0,0,false);assert(rogue.dual);
}
'''
  with tempfile.TemporaryDirectory() as folder:
   src=Path(folder)/'gear.cpp';src.write_text(code);binary=Path(folder)/'gear'
   result=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   result=subprocess.run([str(binary)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
