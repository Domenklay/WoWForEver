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


@unittest.skipUnless(shutil.which('g++'),'C++20 compiler required')
class AdvancementRuleTests(unittest.TestCase):
    def test_real_resource_and_mixed_class_cast_policy(self):
        source=SOURCE.read_text()
        functions='\n'.join(function(source,name) for name in ['static bool Native(', 'static int32 Scale(',
            'static void Refresh(', 'static int32 Available(', 'static Definition const* Best(',
            'static uint32 Used(', 'static int32 Cost(', 'static bool CanCast('])
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
constexpr int MAX_POWERS_PER_CLASS=6,CLASS_PRIEST=5,STAT_SPIRIT=4,DIFFICULTY_NONE=0;
constexpr std::array<Powers,3> PowersList={POWER_MANA,POWER_RAGE,POWER_ENERGY};
struct Definition { uint32 entry,owner,spell,level; };
struct Pool {int32 current=0,maximum=0;double fraction=0;};
struct State {std::set<uint32> learned;std::map<Powers,Pool> pools;Clock::time_point updated=Clock::now();};
struct Player {
 uint32 cls=1,level=20;bool combat=false,alive=true;
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
struct SpellInfo {
 PowerCost cost;
 PowerCost const* CalcPowerCost(Powers power,bool,Player*,int) const {return power==POWER_MANA?&cost:nullptr;}
 int GetSchoolMask() const {return 1;}
};
struct SpellMgr {SpellInfo info;SpellInfo const* GetSpellInfo(uint32,int) {return &info;}} spellMgr;
auto sSpellMgr=&spellMgr;
std::map<uint32,std::vector<Definition>> Catalog;
'''+functions+r'''
int main() {
 Player p;State s;Refresh(&p,s);
 assert(s.pools.size()==2 && !s.pools.count(POWER_RAGE));
 assert(Available(&p,s,POWER_MANA)==550 && Available(&p,s,POWER_ENERGY)==100);
 assert(Available(&p,s,POWER_RAGE)==25);
 Catalog[10]={{10,8,116,4},{10,8,205,26}};Catalog[20]={{20,5,2061,20}};
 s.learned={10,20};assert(Used(s)==2);
 auto mage=Best(10,20);auto priest=Best(20,20);
 assert(mage->spell==116 && Best(10,30)->spell==205 && !Best(10,1));
 assert(CanCast(&p,s,*mage) && CanCast(&p,s,*priest));
 s.learned.erase(10);assert(!CanCast(&p,s,*mage));s.learned.insert(10);
 s.pools[POWER_MANA].current=29;assert(!CanCast(&p,s,*mage));
 s.pools[POWER_MANA].current=30;assert(CanCast(&p,s,*mage));
 p.cls=8;assert(!CanCast(&p,s,*mage));p.cls=1;
 p.alive=false;assert(!CanCast(&p,s,*mage));p.alive=true;
 p.level=1;assert(!CanCast(&p,s,*mage));p.level=20;
 s.pools[POWER_ENERGY].current=0;s.updated=Clock::now()-std::chrono::seconds(1);Refresh(&p,s);
 assert(s.pools[POWER_ENERGY].current>=9 && s.pools[POWER_ENERGY].current<=11);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'test.cpp').write_text(code)
            compile=subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(compile.returncode,0,compile.stderr)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
