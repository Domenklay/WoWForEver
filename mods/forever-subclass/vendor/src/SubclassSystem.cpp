#include "forever_subclass/SubclassSystem.hpp"

#include <cmath>
#include <limits>
#include <sstream>

namespace forever {

namespace {
void setError(std::string* target, std::string message) {
    if (target) *target = std::move(message);
}
}

void MemoryPersistence::save(const CharacterState& state) {
    states_[state.guid] = state;
}

std::optional<CharacterState> MemoryPersistence::load(std::uint64_t guid) {
    auto it = states_.find(guid);
    if (it == states_.end()) return std::nullopt;
    return it->second;
}

SubclassSystem::SubclassSystem(SystemConfig config) : config_(config) {}

ManaShieldAbsorption resolveManaShieldAbsorption(std::uint32_t damage, std::uint32_t remaining,
                                                std::uint32_t mana, double manaPerDamage) {
    ManaShieldAbsorption result{0, 0, remaining};
    if (!std::isfinite(manaPerDamage) || manaPerDamage <= 0) return result;
    auto affordable = static_cast<std::uint32_t>(std::min<double>(
        std::numeric_limits<std::uint32_t>::max(), std::floor(mana / manaPerDamage)));
    result.absorbed = std::min({damage, remaining, affordable});
    result.manaSpent = static_cast<std::uint32_t>(std::min<double>(mana, std::ceil(result.absorbed * manaPerDamage)));
    result.remaining -= result.absorbed;
    return result;
}

void SubclassSystem::registerSpell(SpellDefinition spell) {
    spells_[spell.spellId] = std::move(spell);
}

const SpellDefinition* SubclassSystem::getSpell(std::uint32_t spellId) const {
    auto it = spells_.find(spellId);
    return it == spells_.end() ? nullptr : &it->second;
}

CharacterState SubclassSystem::createCharacter(std::uint64_t guid, ClassId primaryClass, std::uint8_t primaryLevel) const {
    CharacterState result;
    result.guid = guid;
    result.primaryClass = primaryClass;
    result.xpTargetClass = primaryClass;
    result.classes[primaryClass] = ClassProgress{std::min(primaryLevel, config_.maxClassLevel), 0};
    rebuildResourcePools(result);
    return result;
}

bool SubclassSystem::learnClass(CharacterState& c, ClassId classId, std::string* error) const {
    if (classId == ClassId::Unknown) {
        setError(error, "unknown class");
        return false;
    }
    if (c.classes.count(classId)) return true;
    auto primary = c.classes.find(c.primaryClass);
    if (primary == c.classes.end() || primary->second.level < config_.subclassUnlockPrimaryLevel) {
        setError(error, "primary class has not reached subclass unlock level");
        return false;
    }
    c.classes[classId] = ClassProgress{1, 0};
    return true;
}

bool SubclassSystem::canSwitch(const CharacterState& c, std::string* error) const {
    if (c.inCombat && !config_.allowSwitchInCombat) {
        setError(error, "cannot switch subclass in combat");
        return false;
    }
    if (config_.requireRestAreaToSwitchSubclass && !c.inRestArea) {
        setError(error, "subclass can only be switched in a rest area");
        return false;
    }
    return true;
}

bool SubclassSystem::setActiveSubclass(CharacterState& c, ClassId classId, std::string* error) const {
    if (!canSwitch(c, error)) return false;
    if (classId == c.primaryClass) {
        setError(error, "primary class cannot also be the active subclass");
        return false;
    }
    if (!c.classes.count(classId)) {
        setError(error, "class has not been learned");
        return false;
    }
    c.activeSubclass = classId;
    if (!config_.freepickMode) c.selectedSubclassSpells.clear();
    rebuildResourcePools(c);
    return true;
}

bool SubclassSystem::clearActiveSubclass(CharacterState& c, std::string* error) const {
    if (!canSwitch(c, error)) return false;
    c.activeSubclass.reset();
    if (!config_.freepickMode) c.selectedSubclassSpells.clear();
    rebuildResourcePools(c);
    return true;
}

bool SubclassSystem::setXpTarget(CharacterState& c, ClassId classId, std::string* error) const {
    if (config_.freepickMode && classId != c.primaryClass) {
        setError(error, "Freepick XP belongs to the primary class");
        return false;
    }
    if (!c.classes.count(classId)) {
        setError(error, "cannot train a class that has not been learned");
        return false;
    }
    c.xpTargetClass = classId;
    return true;
}

std::uint64_t SubclassSystem::xpToNext(std::uint8_t level) {
    if (level >= 80) return 0;
    // Prototype curve: intentionally independent from Blizzard tables.
    // Integration adapter can replace this with the server's real XP table.
    const std::uint64_t l = level;
    return 1000ULL + 225ULL * l + 35ULL * l * l;
}

std::uint8_t SubclassSystem::grantXp(CharacterState& c, std::uint64_t amount) {
    if (!c.xpTargetClass) return 0;
    auto it = c.classes.find(*c.xpTargetClass);
    if (it == c.classes.end()) return 0;

    auto& p = it->second;
    std::uint8_t levelsGained = 0;
    while (amount > 0 && p.level < config_.maxClassLevel) {
        const auto need = xpToNext(p.level);
        const auto remaining = need > p.xp ? need - p.xp : 0;
        if (amount < remaining) {
            p.xp += amount;
            amount = 0;
        } else {
            amount -= remaining;
            p.xp = 0;
            ++p.level;
            ++levelsGained;
        }
    }
    rebuildResourcePools(c);
    return levelsGained;
}

std::uint8_t SubclassSystem::usedSubclassSlots(const CharacterState& c) const {
    std::uint32_t used = 0;
    for (auto id : c.selectedSubclassSpells) {
        auto spell = getSpell(id);
        if (spell) used += spell->slotCost;
    }
    return static_cast<std::uint8_t>(std::min<std::uint32_t>(used, 255));
}

std::uint32_t SubclassSystem::representedClassMask(const CharacterState& c) const {
    auto bit = [](ClassId id) -> std::uint32_t {
        auto value = static_cast<unsigned>(id);
        return value > 0 && value < 32 ? 1u << value : 0;
    };
    auto mask = bit(c.primaryClass);
    for (auto id : c.selectedSubclassSpells) {
        auto spell = getSpell(id);
        if (spell && !spell->custom && spell->secondaryAllowed) mask |= bit(spell->ownerClass);
    }
    return mask;
}

std::uint8_t SubclassSystem::representedMagicClasses(const CharacterState& c) const {
    auto mask = representedClassMask(c);
    std::uint8_t count = 0;
    for (auto id : {ClassId::Paladin, ClassId::Priest, ClassId::Shaman, ClassId::Mage,
                    ClassId::Warlock, ClassId::Druid})
        if (mask & (1u << static_cast<unsigned>(id))) ++count;
    return count;
}

bool SubclassSystem::meetsCustomRequirements(const CharacterState& c, const SpellDefinition& spell,
                                            std::string* error) const {
    if (!spell.custom) return true;
    if (!config_.freepickMode) {
        setError(error, "custom abilities require Freepick");
        return false;
    }
    if (representedMagicClasses(c) < spell.requiredMagicClasses ||
        (representedClassMask(c) & spell.requiredClassMask) != spell.requiredClassMask) {
        setError(error, "custom class requirements not met");
        return false;
    }
    return true;
}

std::vector<SpellDefinition> customSpellCatalog() {
    std::vector<SpellDefinition> result;
    auto add = [&](std::uint32_t id, const char* name, std::uint8_t level, std::uint8_t magic, std::uint32_t mask) {
        SpellDefinition spell;
        spell.spellId = id;
        spell.name = name;
        spell.ownerClass = ClassId::Unknown;
        spell.requiredClassLevel = level;
        spell.custom = true;
        spell.requiredMagicClasses = magic;
        spell.requiredClassMask = mask;
        // DBC references and WotLK effects are not an implementation for the Forever client/core.
        spell.implementationAvailable = false;
        result.push_back(spell);
    };
    // Only Freepick records corroborated by the donor's Freepick SQL are eligible here.
    add(1463, "Mana Shield", 10, 2, 0);
    result.back().ownerClass = ClassId::Mage;
    result.back().implementationAvailable = true;
    add(982085, "Cold Seeking Missiles", 10, 2, 1u << unsigned(ClassId::Mage));
    add(278016, "Big Flaming Grimfire", 10, 2, (1u << unsigned(ClassId::Mage)) | (1u << unsigned(ClassId::Warlock)));
    add(282083, "Lunar Synergy", 10, 2, (1u << unsigned(ClassId::Mage)) | (1u << unsigned(ClassId::Druid)));
    return result;
}

bool SubclassSystem::selectSubclassSpell(CharacterState& c, std::uint32_t spellId, std::string* error) const {
    return selectSpell(c, spellId, error, false);
}

bool SubclassSystem::restoreSubclassSpells(CharacterState& c, const std::vector<std::uint32_t>& spells,
                                          std::string* error) const {
    auto restored = c;
    restored.selectedSubclassSpells.clear();
    // SQL ID order is not a dependency order: Mana Shield (1463) precedes Lesser Heal (2050).
    for (bool custom : {false, true}) {
        for (auto id : spells) {
            auto spell = getSpell(id);
            if (!spell) {
                setError(error, "saved spell is not registered: " + std::to_string(id));
                return false;
            }
            if (spell->custom == custom && !selectSpell(restored, id, error, true)) return false;
        }
    }
    c = std::move(restored);
    return true;
}

bool SubclassSystem::selectSpell(CharacterState& c, std::uint32_t spellId, std::string* error, bool restoring) const {
    if (!config_.freepickMode && !c.activeSubclass) {
        setError(error, "no active subclass");
        return false;
    }
    const auto* spell = getSpell(spellId);
    if (!spell) {
        setError(error, "spell is not registered");
        return false;
    }
    if (!meetsCustomRequirements(c, *spell, error)) return false;
    if (spell->custom && !spell->implementationAvailable && !restoring) {
        setError(error, "custom ability requires a Forever implementation");
        return false;
    }
    if ((!spell->custom && spell->ownerClass == c.primaryClass) || !spell->secondaryAllowed ||
        (!config_.freepickMode && spell->ownerClass != *c.activeSubclass)) {
        setError(error, "spell is not available to the active subclass");
        return false;
    }
    auto cp = c.classes.find(config_.freepickMode ? c.primaryClass : *c.activeSubclass);
    if (cp == c.classes.end() || cp->second.level < spell->requiredClassLevel) {
        setError(error, "subclass level is too low for this spell");
        return false;
    }
    if (config_.freepickMode && (!canSwitch(c, error) || cp->second.level < config_.subclassUnlockPrimaryLevel)) {
        setError(error, "Freepick purchases require level 10 and a rest area outside combat");
        return false;
    }
    if (c.selectedSubclassSpells.count(spellId)) return true;
    if (static_cast<unsigned>(usedSubclassSlots(c)) + spell->slotCost > config_.subclassAbilitySlots) {
        setError(error, "not enough subclass ability slots");
        return false;
    }
    c.selectedSubclassSpells.insert(spellId);
    rebuildResourcePools(c);
    return true;
}

bool SubclassSystem::unselectSubclassSpell(CharacterState& c, std::uint32_t spellId, std::string* error) const {
    if (config_.freepickMode && !canSwitch(c, nullptr)) return false;
    const bool removed = c.selectedSubclassSpells.erase(spellId) > 0;
    if (removed && config_.freepickMode) {
        for (auto id : c.selectedSubclassSpells) {
            auto spell = getSpell(id);
            if (spell && !meetsCustomRequirements(c, *spell)) {
                c.selectedSubclassSpells.insert(spellId);
                setError(error, "refund dependent custom abilities first");
                return false;
            }
        }
    }
    if (removed) rebuildResourcePools(c);
    return removed;
}

PowerType SubclassSystem::nativePower(ClassId c) {
    switch (c) {
        case ClassId::Warrior: return PowerType::Rage;
        case ClassId::Rogue: return PowerType::Energy;
        case ClassId::Hunter: return PowerType::Focus;
        case ClassId::DeathKnight: return PowerType::RunicPower;
        case ClassId::Paladin:
        case ClassId::Priest:
        case ClassId::Shaman:
        case ClassId::Mage:
        case ClassId::Warlock:
        case ClassId::Monk:
        case ClassId::Druid:
        case ClassId::DemonHunter:
            return PowerType::Mana;
        default: return PowerType::Other;
    }
}

std::int32_t SubclassSystem::defaultPowerMaximum(PowerType type, std::uint8_t level) {
    switch (type) {
        case PowerType::Health: return 1000 + static_cast<std::int32_t>(level) * 150;
        case PowerType::Mana: return 1000 + static_cast<std::int32_t>(level) * 70;
        case PowerType::Rage: return 100;
        case PowerType::Energy: return 100;
        case PowerType::Focus: return 100;
        case PowerType::RunicPower: return 100;
        default: return 100;
    }
}

std::vector<PowerType> SubclassSystem::activePowerTypes(const CharacterState& c) const {
    std::vector<PowerType> result{PowerType::Health};
    auto pushUnique = [&result](PowerType p) {
        if (std::find(result.begin(), result.end(), p) == result.end()) result.push_back(p);
    };
    pushUnique(nativePower(c.primaryClass));
    if (config_.freepickMode) pushUnique(PowerType::Mana); // One shared pool, independent of the catalogue filter.
    else if (c.activeSubclass) pushUnique(nativePower(*c.activeSubclass));
    for (auto spellId : c.selectedSubclassSpells) {
        if (const auto* s = getSpell(spellId)) pushUnique(s->powerType);
    }
    return result;
}

void SubclassSystem::setStats(CharacterState& c, CharacterStats stats) const {
    c.stats = stats;
    rebuildResourcePools(c);
}

void SubclassSystem::rebuildResourcePools(CharacterState& c) const {
    std::unordered_map<PowerType, ResourcePool> newPools;
    std::uint8_t primaryLevel = 1;
    if (auto it = c.classes.find(c.primaryClass); it != c.classes.end()) primaryLevel = it->second.level;

    for (PowerType type : activePowerTypes(c)) {
        std::uint8_t basisLevel = primaryLevel;
        if (!config_.freepickMode && c.activeSubclass && type == nativePower(*c.activeSubclass)) {
            if (auto it = c.classes.find(*c.activeSubclass); it != c.classes.end()) basisLevel = it->second.level;
        }

        double maximum = static_cast<double>(defaultPowerMaximum(type, basisLevel));
        if (type == PowerType::Health)
            maximum += static_cast<double>(std::max(c.stats.stamina, 0)) * config_.healthPerStamina;
        else if (type == PowerType::Mana)
            maximum += static_cast<double>(std::max(c.stats.intellect, 0)) * config_.manaPerIntellect;

        const auto maximumInt = static_cast<std::int32_t>(std::max(0.0, std::floor(maximum)));
        auto old = c.resources.find(type);
        std::int32_t current = maximumInt;
        if (old != c.resources.end()) {
            // If the pool was full before a stat/max change, keep it full. Otherwise keep the old absolute value.
            current = (old->second.current >= old->second.maximum)
                ? maximumInt
                : std::min(old->second.current, maximumInt);
        }
        newPools[type] = ResourcePool{current, maximumInt};
    }
    c.resources = std::move(newPools);
}

double SubclassSystem::spellPowerFor(const CharacterState& c) const {
    const double intellectPower = static_cast<double>(std::max(c.stats.intellect, 0)) * config_.spellPowerPerIntellect;
    return std::max(0.0, static_cast<double>(c.stats.flatSpellPower) + intellectPower);
}

double SubclassSystem::manaRegenPerSecond(const CharacterState& c) const {
    if (!c.resources.count(PowerType::Mana)) return 0.0;
    double regen = static_cast<double>(std::max(c.stats.spirit, 0)) * config_.manaRegenPerSecondPerSpirit;
    if (c.inCombat) regen *= config_.inCombatManaRegenMultiplier;
    return std::max(0.0, regen);
}

std::int32_t SubclassSystem::regenerateMana(CharacterState& c, double seconds) const {
    if (seconds <= 0.0) return 0;
    auto it = c.resources.find(PowerType::Mana);
    if (it == c.resources.end()) return 0;

    const auto before = it->second.current;
    const auto gained = static_cast<std::int32_t>(std::floor(manaRegenPerSecond(c) * seconds));
    it->second.current = std::min(it->second.maximum, it->second.current + std::max(gained, 0));
    return it->second.current - before;
}

double SubclassSystem::calculateSpellEffect(const CharacterState& c, const SpellDefinition& spell) const {
    const double classEfficiency = effectivenessFor(c, spell.ownerClass);
    if (classEfficiency <= 0.0) return 0.0;

    double raw = spell.baseEffect;
    switch (spell.effectKind) {
        case SpellEffectKind::Damage:
        case SpellEffectKind::Healing:
        case SpellEffectKind::Absorb:
            raw += spellPowerFor(c) * spell.spellPowerCoefficient;
            break;
        case SpellEffectKind::Utility:
            break;
    }
    return std::max(0.0, raw * classEfficiency);
}

double SubclassSystem::effectivenessFor(const CharacterState& c, ClassId sourceClass) const {
    if (sourceClass == c.primaryClass) return 1.0;
    if (config_.freepickMode) {
        for (auto id : c.selectedSubclassSpells)
            if (auto spell = getSpell(id); spell && spell->ownerClass == sourceClass)
                return std::clamp(config_.secondaryEffectivenessMultiplier, 0.0, 1.0);
        return 0.0;
    }
    if (!c.activeSubclass || sourceClass != *c.activeSubclass) return 0.0;
    auto p = c.classes.find(c.primaryClass);
    auto s = c.classes.find(sourceClass);
    if (p == c.classes.end() || s == c.classes.end() || p->second.level == 0) return 0.0;
    const double ratio = static_cast<double>(s->second.level) / static_cast<double>(p->second.level);
    return std::clamp(ratio * config_.secondaryEffectivenessMultiplier, 0.0, 1.0);
}

CastResult SubclassSystem::tryCast(CharacterState& c, std::uint32_t spellId) const {
    CastResult r;
    const auto* spell = getSpell(spellId);
    if (!spell) {
        r.error = "spell is not registered";
        return r;
    }
    if (!meetsCustomRequirements(c, *spell, &r.error)) return r;
    if (spell->custom && !spell->implementationAvailable) {
        r.error = "custom ability requires a Forever implementation";
        return r;
    }

    bool allowed = false;
    auto cp = c.classes.find(config_.freepickMode ? c.primaryClass : spell->ownerClass);
    if (cp != c.classes.end() && cp->second.level >= spell->requiredClassLevel) {
        if (!spell->custom && spell->ownerClass == c.primaryClass) {
            allowed = true;
        } else if ((config_.freepickMode || (c.activeSubclass && spell->ownerClass == *c.activeSubclass)) && c.selectedSubclassSpells.count(spellId)) {
            allowed = true;
        }
    }
    if (!allowed) {
        r.error = "spell is not available in the current class loadout";
        return r;
    }

    auto poolIt = c.resources.find(spell->powerType);
    if (poolIt == c.resources.end()) {
        r.error = "required power type is not active";
        return r;
    }
    if (poolIt->second.current < spell->powerCost) {
        r.error = "not enough resource";
        return r;
    }

    poolIt->second.current -= spell->powerCost;
    r.ok = true;
    r.effectiveness = effectivenessFor(c, spell->ownerClass);
    r.remainingResource = poolIt->second.current;
    r.effectiveSpellPower = spellPowerFor(c);
    r.computedEffect = calculateSpellEffect(c, *spell);
    return r;
}

bool SubclassSystem::canUseArmorFromClass(const CharacterState& c, ClassId armorClass) const {
    return armorClass == c.primaryClass;
}

std::string toString(ClassId id) {
    switch (id) {
        case ClassId::Warrior: return "Warrior";
        case ClassId::Paladin: return "Paladin";
        case ClassId::Hunter: return "Hunter";
        case ClassId::Rogue: return "Rogue";
        case ClassId::Priest: return "Priest";
        case ClassId::DeathKnight: return "DeathKnight";
        case ClassId::Shaman: return "Shaman";
        case ClassId::Mage: return "Mage";
        case ClassId::Warlock: return "Warlock";
        case ClassId::Monk: return "Monk";
        case ClassId::Druid: return "Druid";
        case ClassId::DemonHunter: return "DemonHunter";
        default: return "Unknown";
    }
}

std::string toString(PowerType type) {
    switch (type) {
        case PowerType::Health: return "Health";
        case PowerType::Mana: return "Mana";
        case PowerType::Rage: return "Rage";
        case PowerType::Energy: return "Energy";
        case PowerType::Focus: return "Focus";
        case PowerType::RunicPower: return "RunicPower";
        default: return "Other";
    }
}

} // namespace forever
