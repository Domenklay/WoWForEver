#include "../server/TalentRules.h"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <unordered_set>

int main()
{
    using namespace ForeverEncyclopedia::Talents;

    auto const& defs = All();
    assert(defs.size() >= 35);

    std::unordered_set<std::string_view> keys;
    for (TalentDef const& def : defs)
    {
        assert(!def.key.empty());
        assert(!def.branch.empty());
        assert(def.maxRank > 0);
        assert(def.baseCost > 0);
        assert(keys.insert(def.key).second);
        if (!def.prerequisite.empty())
            assert(Find(def.prerequisite) != nullptr);
        for (uint16_t rank = 1; rank < def.maxRank; ++rank)
            assert(Cost(def, rank) >= Cost(def, rank - 1));
    }

    assert(Find("identify_name"));
    assert(Cost(*Find("identify_name"), 0) == 1);
    assert(Cost(*Find("aegis_unlock"), 0) == 3);
    assert(Cost(*Find("mend_unlock"), 0) == 3);
    assert(Cost(*Find("insight_unlock"), 0) == 5);

    // Permanent mana stat: every complete 10 knowledge grants exactly +1 mana.
    assert(KnowledgeManaBonus(0) == 0);
    assert(KnowledgeManaBonus(9) == 0);
    assert(KnowledgeManaBonus(10) == 1);
    assert(KnowledgeManaBonus(9999) == 999);
    assert(KnowledgeManaBonus(10000) == 1000);

    // Percentage regeneration scales by 0.2% per rank and never exceeds 1% / 5 sec.
    assert(RegenBasisPoints(0) == 0);
    assert(RegenBasisPoints(1) == 20);
    assert(RegenBasisPoints(4) == 80);
    assert(RegenBasisPoints(5) == 100);
    assert(RegenBasisPoints(50) == 100);

    // Tooltip values and server-side calculations share the same formulas.
    assert(ShieldPercent(0, 0, 0) == 12);
    assert(ShieldPercent(5, 0, 0) == 22);
    assert(ShieldPercent(5, 5, 4) == 30);
    assert(ShieldCooldownSeconds(0) == 30);
    assert(ShieldCooldownSeconds(3) == 24);
    assert(ShieldCooldownSeconds(5) == 20);
    assert(HealPercent(0) == 25);
    assert(HealPercent(1) == 30);
    assert(HealPercent(3) == 40);
    assert(HealTriggerPercent(50, 5) == 70);
    assert(HealTriggerPercent(75, 5) == 80);
    assert(HealCooldownSeconds(0) == 25);
    assert(HealCooldownSeconds(5) == 15);
    assert(AmplifiedHeal(100, 0) == 100);
    assert(AmplifiedHeal(100, 1) == 110);
    assert(AmplifiedHeal(100, 5) == 150);
    assert(AmplifiedHeal(UINT32_MAX, 5) == UINT32_MAX);
    // Heal is capped before granting HP: no free HP, no overspend, no overheal.
    assert(AffordableNativeHeal(200, 500, 400, 0, 0) == 0);
    assert(AffordableNativeHeal(200, 500, 400, 50, 0) == 50);
    assert(AffordableNativeHeal(200, 500, 400, 150, 0) == 150);
    assert(AffordableNativeHeal(200, 500, 400, 500, 0) == 200);
    assert(AffordableNativeHeal(200, 100, 400, 500, 0) == 100);
    assert(AffordableNativeHeal(200, 500, 40, 500, 0) == 40);
    assert(AffordableNativeHeal(200, 500, 400, 500, 5) == 300);
    assert(AffordableNativeHeal(UINT32_MAX, UINT32_MAX, 100, 50, 5) == 50);
    assert(AffordableNativeHeal(UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, 5) == uint32_t(INT32_MAX));
    assert(ReservePercent(0) == 0);
    assert(ReservePercent(3) == 15);
    assert(ReservePercent(5) == 25);
    assert(Implemented("mend_power"));
    assert(Implemented("mana_reserve"));
    assert(Implemented("mana_overflow"));
    assert(Implemented("identify_abilities"));
    assert(!Implemented("insight_unlock"));
    assert(!Implemented("mana_conservation"));
    assert(!Implemented("aegis_group"));
    assert(!Implemented("identify_loot"));
    assert(Find("mana_overflow")->prerequisite == "mana_capacity");
    assert(Find("mana_overflow")->prerequisiteRank == 10);

    // The tree must offer an early benefit while retaining a long-tail sink.
    uint64_t masteryTotal = 0;
    for (std::string_view key : {"aegis_mastery", "mend_mastery", "insight_mastery", "wisdom_mastery", "knowledge_mastery"})
    {
        TalentDef const* def = Find(key);
        assert(def);
        for (uint16_t rank = 0; rank < def->maxRank; ++rank)
            masteryTotal += Cost(*def, rank);
    }
    assert(masteryTotal > 20000);

    assert(AppearanceThreshold("living_book") == 0);
    assert(AppearanceThreshold("archivist") == 100);
    assert(AppearanceThreshold("runekeeper") == 5000);

    std::cout << "Encyclopedia talent policy tests passed\n";
}
