#include "forever_subclass/SubclassSystem.hpp"
#include <iostream>

using namespace forever;

int main() {
    SystemConfig cfg;
    cfg.subclassUnlockPrimaryLevel = 40;
    cfg.subclassAbilitySlots = 8;

    SubclassSystem system(cfg);
    system.registerSpell({1001, "Mortal Strike", ClassId::Warrior, 40, 0, PowerType::Rage, 30, true,
                          SpellEffectKind::Damage, 600.0, 0.0});
    system.registerSpell({2001, "Flash Heal", ClassId::Priest, 20, 1, PowerType::Mana, 250, true,
                          SpellEffectKind::Healing, 1000.0, 0.80});
    system.registerSpell({2002, "Renew", ClassId::Priest, 10, 1, PowerType::Mana, 140, true,
                          SpellEffectKind::Healing, 450.0, 0.35});
    system.registerSpell({2003, "Power Word: Shield", ClassId::Priest, 30, 2, PowerType::Mana, 300, true,
                          SpellEffectKind::Absorb, 800.0, 0.60});

    auto hero = system.createCharacter(1, ClassId::Warrior, 80);
    system.setStats(hero, CharacterStats{
        150, // Strength
        60,  // Agility
        80,  // Stamina
        120, // Intellect - works even though primary class is Warrior
        100, // Spirit - works while Priest subclass provides Mana
        50   // Flat spell power from gear/auras
    });

    std::string error;
    system.learnClass(hero, ClassId::Priest, &error);
    hero.classes[ClassId::Priest].level = 60; // demo shortcut; normal server uses grantXp().
    system.setActiveSubclass(hero, ClassId::Priest, &error);
    system.selectSubclassSpell(hero, 2001, &error);
    system.selectSubclassSpell(hero, 2002, &error);
    system.selectSubclassSpell(hero, 2003, &error);
    system.rebuildResourcePools(hero);

    std::cout << "Primary: " << toString(hero.primaryClass) << " " << +hero.classes[hero.primaryClass].level << "\n";
    std::cout << "Subclass: " << toString(*hero.activeSubclass) << " " << +hero.classes[*hero.activeSubclass].level << "\n";
    std::cout << "Secondary effectiveness: " << system.effectivenessFor(hero, ClassId::Priest) * 100.0 << "%\n";
    std::cout << "Intellect: " << hero.stats.intellect << ", Spirit: " << hero.stats.spirit << "\n";
    std::cout << "Effective spell power: " << system.spellPowerFor(hero) << "\n";
    std::cout << "Mana regen/sec (out of combat): " << system.manaRegenPerSecond(hero) << "\n";
    std::cout << "Resources:\n";
    for (const auto& [type, pool] : hero.resources)
        std::cout << "  " << toString(type) << ": " << pool.current << "/" << pool.maximum << "\n";

    hero.resources[PowerType::Rage].current = hero.resources[PowerType::Rage].maximum;

    auto strike = system.tryCast(hero, 1001);
    auto heal = system.tryCast(hero, 2001);
    std::cout << "Mortal Strike: " << (strike.ok ? "OK" : strike.error)
              << ", effectiveness=" << strike.effectiveness << "\n";
    std::cout << "Flash Heal: " << (heal.ok ? "OK" : heal.error)
              << ", effectiveness=" << heal.effectiveness
              << ", spellPower=" << heal.effectiveSpellPower
              << ", computedHeal=" << heal.computedEffect << "\n";

    return 0;
}
