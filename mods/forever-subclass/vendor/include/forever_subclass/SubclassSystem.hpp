#pragma once

#include <algorithm>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace forever {

enum class ClassId : std::uint8_t {
    Warrior = 1,
    Paladin = 2,
    Hunter = 3,
    Rogue = 4,
    Priest = 5,
    DeathKnight = 6,
    Shaman = 7,
    Mage = 8,
    Warlock = 9,
    Monk = 10,
    Druid = 11,
    DemonHunter = 12,
    Unknown = 255
};

enum class PowerType : std::uint8_t {
    Health,
    Mana,
    Rage,
    Energy,
    Focus,
    RunicPower,
    Other
};

enum class SpellEffectKind : std::uint8_t {
    Utility,
    Damage,
    Healing,
    Absorb
};

struct CharacterStats {
    std::int32_t strength = 0;
    std::int32_t agility = 0;
    std::int32_t stamina = 0;
    std::int32_t intellect = 0;
    std::int32_t spirit = 0;
    std::int32_t flatSpellPower = 0;
};

struct SystemConfig {
    bool freepickMode = false; // Separate opt-in mode; primary class and XP remain native.
    std::uint8_t maxClassLevel = 80;
    std::uint8_t subclassUnlockPrimaryLevel = 40;
    std::uint8_t subclassAbilitySlots = 8;
    double secondaryEffectivenessMultiplier = 1.0; // ratio secondary/primary is applied separately
    bool requireRestAreaToSwitchSubclass = true;
    bool allowSwitchInCombat = false;

    // Prototype stat formulas. Replace/tune these from the selected Forever core/DB2 rules.
    double healthPerStamina = 10.0;
    double manaPerIntellect = 15.0;
    double spellPowerPerIntellect = 1.0;
    double manaRegenPerSecondPerSpirit = 0.20;
    double inCombatManaRegenMultiplier = 0.30;
};

struct SpellDefinition {
    std::uint32_t spellId = 0;
    std::string name;
    ClassId ownerClass = ClassId::Unknown;
    std::uint8_t requiredClassLevel = 1;
    std::uint8_t slotCost = 1;
    PowerType powerType = PowerType::Mana;
    std::int32_t powerCost = 0;
    bool secondaryAllowed = true;
    SpellEffectKind effectKind = SpellEffectKind::Utility;
    double baseEffect = 0.0;
    double spellPowerCoefficient = 0.0;
    bool custom = false;
    std::uint8_t requiredMagicClasses = 0;
    std::uint32_t requiredClassMask = 0;
    bool implementationAvailable = true;
};

struct ClassProgress {
    std::uint8_t level = 1;
    std::uint64_t xp = 0;
};

struct ResourcePool {
    std::int32_t current = 0;
    std::int32_t maximum = 0;
};

struct CharacterState {
    std::uint64_t guid = 0;
    ClassId primaryClass = ClassId::Unknown;
    std::optional<ClassId> activeSubclass;
    std::optional<ClassId> xpTargetClass;
    std::unordered_map<ClassId, ClassProgress> classes;
    std::unordered_set<std::uint32_t> selectedSubclassSpells;
    std::unordered_map<PowerType, ResourcePool> resources;
    CharacterStats stats;
    bool inCombat = false;
    bool inRestArea = true;
};

struct CastResult {
    bool ok = false;
    std::string error;
    double effectiveness = 0.0;
    std::int32_t remainingResource = 0;
    double effectiveSpellPower = 0.0;
    double computedEffect = 0.0;
};

struct ManaShieldAbsorption {
    std::uint32_t absorbed = 0;
    std::uint32_t manaSpent = 0;
    std::uint32_t remaining = 0;
};

ManaShieldAbsorption resolveManaShieldAbsorption(std::uint32_t damage, std::uint32_t remaining,
                                                std::uint32_t mana, double manaPerDamage);

class ISubclassPersistence {
public:
    virtual ~ISubclassPersistence() = default;
    virtual void save(const CharacterState& state) = 0;
    virtual std::optional<CharacterState> load(std::uint64_t guid) = 0;
};

class MemoryPersistence final : public ISubclassPersistence {
public:
    void save(const CharacterState& state) override;
    std::optional<CharacterState> load(std::uint64_t guid) override;
private:
    std::unordered_map<std::uint64_t, CharacterState> states_;
};

class SubclassSystem {
public:
    explicit SubclassSystem(SystemConfig config = {});

    void registerSpell(SpellDefinition spell);
    const SpellDefinition* getSpell(std::uint32_t spellId) const;

    CharacterState createCharacter(std::uint64_t guid, ClassId primaryClass, std::uint8_t primaryLevel = 1) const;
    bool learnClass(CharacterState& character, ClassId classId, std::string* error = nullptr) const;
    bool setActiveSubclass(CharacterState& character, ClassId classId, std::string* error = nullptr) const;
    bool clearActiveSubclass(CharacterState& character, std::string* error = nullptr) const;
    bool setXpTarget(CharacterState& character, ClassId classId, std::string* error = nullptr) const;
    std::uint8_t grantXp(CharacterState& character, std::uint64_t xp);

    bool selectSubclassSpell(CharacterState& character, std::uint32_t spellId, std::string* error = nullptr) const;
    bool restoreSubclassSpells(CharacterState& character, const std::vector<std::uint32_t>& spells,
                              std::string* error = nullptr) const;
    bool unselectSubclassSpell(CharacterState& character, std::uint32_t spellId, std::string* error = nullptr) const;
    std::uint8_t usedSubclassSlots(const CharacterState& character) const;
    std::uint32_t representedClassMask(const CharacterState& character) const;
    std::uint8_t representedMagicClasses(const CharacterState& character) const;
    bool meetsCustomRequirements(const CharacterState& character, const SpellDefinition& spell,
                                 std::string* error = nullptr) const;

    std::vector<PowerType> activePowerTypes(const CharacterState& character) const;
    void setStats(CharacterState& character, CharacterStats stats) const;
    void rebuildResourcePools(CharacterState& character) const;
    double spellPowerFor(const CharacterState& character) const;
    double manaRegenPerSecond(const CharacterState& character) const;
    std::int32_t regenerateMana(CharacterState& character, double seconds) const;
    double calculateSpellEffect(const CharacterState& character, const SpellDefinition& spell) const;
    CastResult tryCast(CharacterState& character, std::uint32_t spellId) const;

    double effectivenessFor(const CharacterState& character, ClassId sourceClass) const;
    bool canUseArmorFromClass(const CharacterState& character, ClassId armorClass) const;

    static std::uint64_t xpToNext(std::uint8_t level);
    const SystemConfig& config() const { return config_; }

private:
    bool selectSpell(CharacterState& character, std::uint32_t spellId, std::string* error, bool restoring) const;
    bool canSwitch(const CharacterState& character, std::string* error) const;
    static PowerType nativePower(ClassId classId);
    static std::int32_t defaultPowerMaximum(PowerType type, std::uint8_t classLevel);

    SystemConfig config_;
    std::unordered_map<std::uint32_t, SpellDefinition> spells_;
};

std::string toString(ClassId id);
std::string toString(PowerType type);
std::vector<SpellDefinition> customSpellCatalog();

} // namespace forever
