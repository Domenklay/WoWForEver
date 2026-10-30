#include "forever_subclass/SubclassSystem.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace forever;

int main() {
    auto absorption=resolveManaShieldAbsorption(1000,500,300,1.5);
    assert(absorption.absorbed==200&&absorption.manaSpent==300&&absorption.remaining==300);
    absorption=resolveManaShieldAbsorption(1000,50,1000,1.5);
    assert(absorption.absorbed==50&&absorption.manaSpent==75&&absorption.remaining==0);
    absorption=resolveManaShieldAbsorption(1,50,2,1.5);
    assert(absorption.absorbed==1&&absorption.manaSpent==2&&absorption.remaining==49);
    absorption=resolveManaShieldAbsorption(50,50,1,1.5);
    assert(absorption.absorbed==0&&absorption.manaSpent==0&&absorption.remaining==50);
    assert(resolveManaShieldAbsorption(0,50,100,1.5).absorbed==0);
    assert(resolveManaShieldAbsorption(50,0,100,1.5).absorbed==0);
    assert(resolveManaShieldAbsorption(50,50,0,1.5).absorbed==0);
    assert(resolveManaShieldAbsorption(50,50,100,0).absorbed==0);
    assert(resolveManaShieldAbsorption(50,50,100,std::numeric_limits<double>::infinity()).absorbed==0);
    assert(resolveManaShieldAbsorption(50,50,100,std::numeric_limits<double>::quiet_NaN()).absorbed==0);
    auto limit=std::numeric_limits<std::uint32_t>::max();
    absorption=resolveManaShieldAbsorption(limit,limit,limit,2);
    assert(absorption.absorbed==limit/2&&absorption.manaSpent==limit-1);
    SystemConfig cfg;cfg.freepickMode=true;cfg.subclassUnlockPrimaryLevel=10;cfg.subclassAbilitySlots=2;
    SubclassSystem system(cfg);
    system.registerSpell({2050,"Lesser Heal",ClassId::Priest,1,1,PowerType::Mana,30,true});
    system.registerSpell({116,"Frostbolt",ClassId::Mage,4,1,PowerType::Mana,25,true});
    system.registerSpell({686,"Shadow Bolt",ClassId::Warlock,1,1,PowerType::Mana,25,true});
    system.registerSpell({1,"Warrior native",ClassId::Warrior,1,1,PowerType::Rage,0,true});
    system.registerSpell({2,"Locked",ClassId::Mage,30,1,PowerType::Mana,1,true});
    auto c=system.createCharacter(42,ClassId::Warrior,20);std::string error;
    assert(system.learnClass(c,ClassId::Priest,&error));assert(system.learnClass(c,ClassId::Mage,&error));
    assert(system.setActiveSubclass(c,ClassId::Priest,&error));assert(system.selectSubclassSpell(c,2050,&error));
    assert(!system.tryCast(c,116).ok); // Registered is not purchased.
    assert(system.setActiveSubclass(c,ClassId::Mage,&error));assert(system.selectSubclassSpell(c,116,&error));
    assert(c.selectedSubclassSpells.size()==2);assert(c.primaryClass==ClassId::Warrior);
    assert(c.classes.at(ClassId::Warrior).level==20);assert(c.classes.at(ClassId::Priest).level==1);
    assert(system.usedSubclassSlots(c)==2);assert(!system.selectSubclassSpell(c,686,&error));
    assert(!system.selectSubclassSpell(c,1,&error));assert(!system.selectSubclassSpell(c,2,&error));
    assert(!system.selectSubclassSpell(c,999,&error));
    const int mana=c.resources.at(PowerType::Mana).current;
    assert(system.tryCast(c,2050).ok);assert(system.tryCast(c,116).ok);
    assert(c.resources.at(PowerType::Mana).current==mana-55);assert(c.resources.count(PowerType::Rage)==1);
    assert(system.effectivenessFor(c,ClassId::Priest)==1);assert(system.effectivenessFor(c,ClassId::Mage)==1);
    assert(!system.setXpTarget(c,ClassId::Mage,&error));
    auto xp=c.classes.at(ClassId::Warrior).xp;system.grantXp(c,12);assert(c.classes.at(ClassId::Warrior).xp==xp+12);
    c.inCombat=true;assert(!system.selectSubclassSpell(c,686,&error));assert(!system.unselectSubclassSpell(c,116));
    c.inCombat=false;c.inRestArea=false;assert(!system.unselectSubclassSpell(c,116));c.inRestArea=true;
    MemoryPersistence persistence;persistence.save(c);auto restored=persistence.load(42);assert(restored);
    assert(restored->selectedSubclassSpells==c.selectedSubclassSpells);assert(restored->resources.at(PowerType::Mana).current==mana-55);
    assert(system.clearActiveSubclass(c,&error));assert(system.tryCast(c,2050).ok);assert(system.tryCast(c,116).ok);
    auto drained=c.resources.at(PowerType::Mana).current;
    assert(system.unselectSubclassSpell(c,116));assert(!system.tryCast(c,116).ok);assert(system.usedSubclassSlots(c)==1);
    assert(system.selectSubclassSpell(c,686,&error));assert(c.resources.at(PowerType::Mana).current==drained); // No refill on refund/filter changes.
    c.resources.at(PowerType::Mana).current=0;assert(!system.tryCast(c,2050).ok);
    auto low=system.createCharacter(43,ClassId::Warrior,9);assert(!system.selectSubclassSpell(low,2050,&error));

    SystemConfig customCfg=cfg;customCfg.subclassAbilitySlots=8;
    SubclassSystem custom(customCfg);
    custom.registerSpell({2050,"Heal",ClassId::Priest,1,1,PowerType::Mana,0,true});
    custom.registerSpell({2054,"Another heal",ClassId::Priest,1,1,PowerType::Mana,0,true});
    custom.registerSpell({116,"Frostbolt",ClassId::Mage,1,1,PowerType::Mana,0,true});
    custom.registerSpell({686,"Shadow Bolt",ClassId::Warlock,1,1,PowerType::Mana,0,true});
    for(auto spell:customSpellCatalog()) { if(spell.spellId==1463) spell.implementationAvailable=false;custom.registerSpell(spell); }
    auto build=custom.createCharacter(44,ClassId::Warrior,80);
    assert(custom.learnClass(build,ClassId::Mage,&error));
    assert(custom.learnClass(build,ClassId::Priest,&error));
    assert(custom.representedMagicClasses(build)==0); // Learning/opening a class is not a purchase.
    assert(!custom.selectSubclassSpell(build,1463,&error));
    assert(custom.selectSubclassSpell(build,2050,&error));
    assert(custom.selectSubclassSpell(build,2054,&error));
    assert(custom.representedMagicClasses(build)==1); // Two spells of the same class count once.
    assert(!custom.meetsCustomRequirements(build,*custom.getSpell(1463),&error));
    assert(custom.selectSubclassSpell(build,116,&error));
    assert(custom.representedMagicClasses(build)==2);
    assert(custom.meetsCustomRequirements(build,*custom.getSpell(1463),&error));
    auto slots=custom.usedSubclassSlots(build);auto beforeMana=build.resources.at(PowerType::Mana).current;
    assert(!custom.selectSubclassSpell(build,1463,&error)); // Missing implementation is never purchasable.
    assert(error=="custom ability requires a Forever implementation");
    assert(custom.usedSubclassSlots(build)==slots);
    build.selectedSubclassSpells.insert(1463); // A forged/stale purchase cannot bypass runtime availability.
    assert(!custom.tryCast(build,1463).ok);
    assert(build.resources.at(PowerType::Mana).current==beforeMana);
    build.selectedSubclassSpells.erase(1463);
    assert(!custom.meetsCustomRequirements(build,*custom.getSpell(278016),&error));
    assert(custom.selectSubclassSpell(build,686,&error));
    assert(custom.meetsCustomRequirements(build,*custom.getSpell(278016),&error));

    // An isolated policy fixture verifies future implemented entries without enabling any live spell.
    auto shield=*custom.getSpell(1463);shield.implementationAvailable=true;custom.registerSpell(shield);
    assert(custom.selectSubclassSpell(build,1463,&error));
    auto count=custom.representedMagicClasses(build);
    assert(count==3); // A custom spell contributes no class of its own.
    assert(custom.unselectSubclassSpell(build,116,&error));
    assert(!custom.unselectSubclassSpell(build,686,&error));
    assert(error=="refund dependent custom abilities first");
    assert(build.selectedSubclassSpells.count(686));
    assert(custom.tryCast(build,1463).ok);
    auto invalid=build;invalid.selectedSubclassSpells.erase(686);
    assert(!custom.tryCast(invalid,1463).ok); // Cast checks prerequisites again.
    assert(custom.unselectSubclassSpell(build,1463,&error));
    assert(custom.unselectSubclassSpell(build,686,&error));
    auto paladin=custom.createCharacter(45,ClassId::Paladin,20);
    assert(custom.representedMagicClasses(paladin)==1);
    assert(custom.selectSubclassSpell(paladin,2050,&error));
    assert(custom.meetsCustomRequirements(paladin,shield,&error));
    assert(!custom.meetsCustomRequirements(paladin,*custom.getSpell(282083),&error));
    SubclassSystem legacy;
    assert(!legacy.meetsCustomRequirements(paladin,shield,&error));
    auto mage=custom.createCharacter(46,ClassId::Mage,20);
    assert(custom.selectSubclassSpell(mage,2050,&error));
    assert(!custom.tryCast(mage,1463).ok); // Owning the native class does not bypass a custom purchase.
    assert(custom.selectSubclassSpell(mage,1463,&error));
    assert(custom.tryCast(mage,1463).ok);
    auto login=custom.createCharacter(47,ClassId::Warrior,20);
    assert(custom.restoreSubclassSpells(login,{116,1463,2050},&error));
    assert(login.selectedSubclassSpells.count(1463)&&custom.representedMagicClasses(login)==2);
    auto saved=login.selectedSubclassSpells;
    assert(!custom.restoreSubclassSpells(login,{1463,999999},&error));
    assert(login.selectedSubclassSpells==saved); // A corrupt save never partially overwrites the loadout.
    shield.implementationAvailable=false;custom.registerSpell(shield);
    assert(custom.restoreSubclassSpells(login,{1463,2050,116},&error));
    assert(!custom.tryCast(login,1463).ok); // Missing runtime support preserves ownership, never casting.
    assert(custom.unselectSubclassSpell(login,1463,&error));
    std::cout << "Freepick: simultaneous purchases, shared resources, primary XP, refunds and persistence passed\n";
}
