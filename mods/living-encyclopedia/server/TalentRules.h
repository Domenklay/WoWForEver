#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace ForeverEncyclopedia::Talents
{
struct TalentDef
{
    std::string_view key;
    std::string_view branch;
    uint16_t maxRank;
    uint32_t baseCost;
    uint32_t stepCost;
    uint32_t quadraticCost;
    std::string_view prerequisite;
    uint16_t prerequisiteRank;
};

inline uint64_t Cost(TalentDef const& def, uint16_t currentRank)
{
    uint64_t r = currentRank;
    return uint64_t(def.baseCost) + uint64_t(def.stepCost) * r + uint64_t(def.quadraticCost) * r * r;
}

template <class RankMapT>
inline uint16_t Rank(RankMapT const& ranks, std::string_view key)
{
    auto it = ranks.find(std::string(key));
    return it == ranks.end() ? 0 : uint16_t(it->second);
}

inline uint64_t KnowledgeManaBonus(uint64_t totalKnowledge)
{
    return totalKnowledge / 10;
}

inline uint32_t RegenBasisPoints(uint16_t rank)
{
    // 0.2% maximum mana per rank, hard-capped at 1% / 5 sec.
    return rank >= 5 ? 100u : uint32_t(rank) * 20u;
}

inline std::vector<TalentDef> const& All()
{
    // Early ranks are intentionally cheap. Mastery ranks are the long-term
    // sink for accounts that eventually accumulate tens of thousands of knowledge.
    static std::vector<TalentDef> const defs = {
        // Protection
        {"aegis_unlock", "protection", 1, 3, 0, 0, "", 0},
        {"aegis_strength", "protection", 5, 2, 2, 0, "aegis_unlock", 1},
        {"aegis_efficiency", "protection", 5, 3, 3, 0, "aegis_unlock", 1},
        {"aegis_reflex", "protection", 5, 5, 5, 0, "aegis_unlock", 1},
        {"aegis_group", "protection", 1, 60, 0, 0, "aegis_strength", 3},
        {"aegis_overcharge", "protection", 4, 35, 20, 5, "aegis_strength", 5},
        {"aegis_mastery", "protection", 15, 100, 20, 1, "aegis_overcharge", 4},

        // Healing
        {"mend_unlock", "healing", 1, 3, 0, 0, "", 0},
        {"mend_power", "healing", 5, 2, 2, 0, "mend_unlock", 1},
        {"mend_efficiency", "healing", 5, 3, 3, 0, "mend_unlock", 1},
        {"mend_reflex", "healing", 5, 5, 5, 0, "mend_unlock", 1},
        {"mend_group", "healing", 1, 60, 0, 0, "mend_power", 3},
        {"mend_deep", "healing", 3, 40, 25, 5, "mend_power", 5},
        {"mend_mastery", "healing", 15, 100, 20, 1, "mend_deep", 3},

        // Support
        {"insight_unlock", "support", 1, 5, 0, 0, "", 0},
        {"insight_duration", "support", 5, 3, 3, 0, "insight_unlock", 1},
        {"insight_efficiency", "support", 5, 4, 4, 0, "insight_unlock", 1},
        {"insight_reflex", "support", 5, 8, 6, 1, "insight_unlock", 1},
        {"insight_group", "support", 1, 75, 0, 0, "insight_duration", 3},
        {"insight_cleanse", "support", 1, 150, 0, 0, "insight_group", 1},
        {"insight_mastery", "support", 15, 110, 22, 1, "insight_cleanse", 1},

        // Wisdom / mana economy
        {"mana_capacity", "wisdom", 10, 2, 2, 0, "", 0},
        {"mana_combat_regen", "wisdom", 5, 5, 5, 0, "mana_capacity", 2},
        {"mana_rest_regen", "wisdom", 5, 3, 3, 0, "mana_capacity", 2},
        {"mana_reserve", "wisdom", 5, 10, 8, 1, "mana_capacity", 5},
        {"mana_conservation", "wisdom", 5, 20, 15, 2, "mana_reserve", 3},
        {"mana_overflow", "wisdom", 5, 60, 30, 3, "mana_conservation", 5},
        {"wisdom_mastery", "wisdom", 15, 100, 20, 1, "mana_overflow", 5},

        // Knowledge / bestiary information. First benefit costs a single point.
        {"identify_name", "knowledge", 1, 1, 0, 0, "", 0},
        {"identify_rank", "knowledge", 1, 3, 0, 0, "identify_name", 1},
        {"identify_stats", "knowledge", 1, 5, 0, 0, "identify_rank", 1},
        {"identify_abilities", "knowledge", 1, 10, 0, 0, "identify_stats", 1},
        {"identify_resists", "knowledge", 1, 20, 0, 0, "identify_abilities", 1},
        {"identify_loot", "knowledge", 1, 35, 0, 0, "identify_resists", 1},
        {"identify_locations", "knowledge", 1, 60, 0, 0, "identify_loot", 1},
        {"identify_rares", "knowledge", 1, 120, 0, 0, "identify_locations", 1},
        {"knowledge_mastery", "knowledge", 15, 90, 18, 1, "identify_rares", 1},
    };
    return defs;
}

inline TalentDef const* Find(std::string_view key)
{
    for (TalentDef const& def : All())
        if (def.key == key)
            return &def;
    return nullptr;
}

inline uint32_t AppearanceThreshold(std::string_view key)
{
    if (key == "living_book") return 0;
    if (key == "archivist") return 100;
    if (key == "knowledge_spirit") return 500;
    if (key == "small_construct") return 1500;
    if (key == "runekeeper") return 5000;
    return UINT32_MAX;
}
}
