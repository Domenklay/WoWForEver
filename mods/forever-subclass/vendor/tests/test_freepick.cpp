#include "forever_subclass/SubclassSystem.hpp"
#include <cassert>
#include <iostream>
using namespace forever;

int main() {
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
    std::cout << "Freepick: simultaneous purchases, shared resources, primary XP, refunds and persistence passed\n";
}
