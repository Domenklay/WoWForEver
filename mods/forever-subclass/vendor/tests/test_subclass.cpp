#include "forever_subclass/SubclassSystem.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

using namespace forever;

static bool near(double a, double b) { return std::fabs(a - b) < 0.0001; }

int main() {
    SubclassSystem system;
    system.registerSpell({2001, "Flash Heal", ClassId::Priest, 20, 1, PowerType::Mana, 250, true,
                          SpellEffectKind::Healing, 1000.0, 0.80});
    system.registerSpell({2002, "Renew", ClassId::Priest, 10, 1, PowerType::Mana, 100, true,
                          SpellEffectKind::Healing, 450.0, 0.35});
    system.registerSpell({2003, "Shield", ClassId::Priest, 30, 2, PowerType::Mana, 300, true,
                          SpellEffectKind::Absorb, 800.0, 0.60});

    std::string err;
    auto low = system.createCharacter(1, ClassId::Warrior, 39);
    assert(!system.learnClass(low, ClassId::Priest, &err));

    auto c = system.createCharacter(2, ClassId::Warrior, 80);
    system.setStats(c, CharacterStats{150, 60, 80, 120, 100, 50});
    assert(system.learnClass(c, ClassId::Priest, &err));
    c.classes[ClassId::Priest].level = 60;
    assert(system.setActiveSubclass(c, ClassId::Priest, &err));
    assert(system.selectSubclassSpell(c, 2001, &err));
    assert(system.selectSubclassSpell(c, 2002, &err));
    assert(system.selectSubclassSpell(c, 2003, &err));
    assert(system.usedSubclassSlots(c) == 4);
    assert(near(system.effectivenessFor(c, ClassId::Priest), 0.75));

    system.rebuildResourcePools(c);
    assert(c.resources.count(PowerType::Rage) == 1);
    assert(c.resources.count(PowerType::Mana) == 1);
    assert(c.resources.at(PowerType::Mana).maximum == 7000); // 5200 base + 120 INT * 15
    assert(c.resources.at(PowerType::Health).maximum == 13800); // 13000 base + 80 STA * 10
    assert(near(system.spellPowerFor(c), 170.0)); // 50 flat + 120 INT * 1
    assert(near(system.manaRegenPerSecond(c), 20.0)); // 100 SPI * 0.2
    assert(system.canUseArmorFromClass(c, ClassId::Warrior));
    assert(!system.canUseArmorFromClass(c, ClassId::Priest));

    auto before = c.resources[PowerType::Mana].current;
    auto cast = system.tryCast(c, 2001);
    assert(cast.ok);
    assert(near(cast.effectiveness, 0.75));
    assert(near(cast.effectiveSpellPower, 170.0));
    assert(near(cast.computedEffect, 852.0)); // (1000 + 170*0.8) * 0.75
    assert(c.resources[PowerType::Mana].current == before - 250);

    // Spirit regen works for the hybrid mana pool.
    c.resources[PowerType::Mana].current = 6000;
    assert(system.regenerateMana(c, 10.0) == 200);
    assert(c.resources[PowerType::Mana].current == 6200);

    // In combat only 30% of the prototype Spirit regen remains.
    c.inCombat = true;
    assert(near(system.manaRegenPerSecond(c), 6.0));
    assert(system.regenerateMana(c, 10.0) == 60);
    assert(!system.clearActiveSubclass(c, &err));

    MemoryPersistence mem;
    mem.save(c);
    auto loaded = mem.load(c.guid);
    assert(loaded.has_value());
    assert(loaded->classes.at(ClassId::Priest).level == 60);
    assert(loaded->stats.intellect == 120);
    assert(loaded->stats.spirit == 100);

    std::cout << "All subclass + hybrid stat prototype tests passed.\n";
    return 0;
}
