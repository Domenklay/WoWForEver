#pragma once
#include "AscensionCustomCatalog.h"
#include <set>

namespace ForeverAdvancementCustom
{
inline unsigned Canonical(unsigned entry)
{
    for (auto const& alias : Aliases) if (alias.entry == entry) return alias.canonical;
    return entry;
}
inline Rule const* Find(unsigned entry)
{
    entry = Canonical(entry);
    for (auto const& rule : Rules) if (rule.entry == entry) return &rule;
    return nullptr;
}
inline unsigned MagicBit(unsigned owner)
{
    switch (owner)
    {
        case 2: case 5: case 7: case 8: case 9: case 11: return 1u << (owner - 1);
        default: return 0;
    }
}
template<class Owner> unsigned MagicCount(unsigned primary, std::set<unsigned> const& purchases, Owner owner)
{
    unsigned mask = MagicBit(primary), count = 0;
    for (auto entry : purchases) if (!Find(entry)) mask |= MagicBit(owner(entry));
    for (; mask; mask &= mask - 1) ++count;
    return count;
}
inline bool RequirementsMet(Rule const& rule, unsigned count) { return count >= rule.requiredMagicClasses; }
// Missing handlers stay unavailable even if a native spell with the same ID exists.
inline bool CanUse(Rule const& rule, unsigned count) { return rule.implemented && RequirementsMet(rule, count); }
}
