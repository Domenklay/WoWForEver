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
