#pragma once
#include <algorithm>
#include <cstdint>

namespace ForeverAdvancementExperience
{
// Integer carry preserves 90/10 over repeated small rewards. Return unaccepted XP.
template<class Progress, class Required>
std::uint32_t Grant(Progress& progress, std::uint32_t cap, std::uint32_t incoming,
                    bool enabled, std::uint32_t& carry, Required required)
{
    if (!enabled || !incoming || progress.level >= cap) return incoming;
    std::uint64_t scaled = std::uint64_t(incoming) * 90 + carry;
    std::uint64_t allocated = scaled / 100, remaining = allocated;
    carry = scaled % 100;
    while (remaining && progress.level < cap)
    {
        std::uint64_t need = required(progress.level);
        if (!need || progress.xp >= need) break;
        auto take = std::min(remaining, need - progress.xp);
        progress.xp += take; remaining -= take;
        if (progress.xp == need) { ++progress.level; progress.xp = 0; }
    }
    if (remaining || progress.level >= cap) carry = 0;
    return incoming - std::uint32_t(allocated - remaining);
}
}
