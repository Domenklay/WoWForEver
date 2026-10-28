#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace forever_scaling {
enum class Rank { Normal, Elite, RareElite, Boss };
struct Config {
    int minOffset = -9;
    int maxOffset = 10;
    int maxCreatureLevel = 70;
    double normalCap = .20;
    double eliteCap = .30;
    double rareEliteCap = .40;
    double bossCap = .45;
};
inline int Offset(Rank rank) {
    switch(rank) {
        case Rank::Elite: return 5;
        case Rank::RareElite: return 7;
        case Rank::Boss: return 8;
        default: return 0;
    }
}
inline int Level(int playerLevel, Rank rank, Config const& c = {}) {
    int p = std::max(1, playerLevel);
    int low = std::max(1, p + c.minOffset);
    int high = std::max(low, std::min(c.maxCreatureLevel, p + c.maxOffset));
    return std::clamp(p + Offset(rank), low, high);
}
inline double CapFraction(Rank rank, Config const& c = {}) {
    switch(rank) {
        case Rank::Elite: return c.eliteCap;
        case Rank::RareElite: return c.rareEliteCap;
        case Rank::Boss: return c.bossCap;
        default: return c.normalCap;
    }
}
// Applies only after caller has verified NPC -> player, and after mitigation.
// Caller must handle periodic and multi-hit rolling budgets separately.
inline uint64_t GuardSingleHit(uint64_t mitigated, uint64_t victimMaxHealth,
                               Rank rank, Config const& c = {}) {
    if (!victimMaxHealth) return 0;
    double fraction = std::clamp(CapFraction(rank, c), 0.0, 1.0);
    auto cap = static_cast<uint64_t>(std::floor(victimMaxHealth * fraction));
    return std::min(mitigated, cap);
}
} // namespace forever_scaling
