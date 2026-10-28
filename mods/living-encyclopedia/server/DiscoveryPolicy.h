#pragma once
#include <cstdint>
#include <string>
#include <unordered_set>
#include <vector>
#include <algorithm>

namespace encyclopedia {
enum class DiscoveryKind : uint8_t { Creature, Item, Achievement, Zone };
struct DiscoveryKey {
    DiscoveryKind kind;
    uint32_t entry;
    bool operator==(DiscoveryKey const& b) const { return kind == b.kind && entry == b.entry; }
};
struct DiscoveryHash {
    size_t operator()(DiscoveryKey const& k) const {
        return (static_cast<size_t>(k.entry) << 3) ^ static_cast<size_t>(k.kind);
    }
};
struct ZoneCreature {
    uint32_t creatureEntry;
    bool accessible;
    bool hidden;
};
struct ZoneSummary {
    uint32_t total = 0;
    uint32_t discovered = 0;
};
// Pure, deterministic catalogue filtering. Real spawn indexing and DB queries are separate.
inline ZoneSummary SummarizeZone(std::vector<ZoneCreature> const& creatures,
    std::unordered_set<DiscoveryKey, DiscoveryHash> const& discovered) {
    std::unordered_set<uint32_t> counted;
    ZoneSummary result;
    for (auto const& c : creatures) {
        if (!c.accessible || c.hidden || !c.creatureEntry || !counted.insert(c.creatureEntry).second)
            continue;
        ++result.total;
        if (discovered.count({DiscoveryKind::Creature, c.creatureEntry}))
            ++result.discovered;
    }
    return result;
}
struct DiscoveryAward {
    DiscoveryKind kind;
    uint32_t entry;
    uint32_t points;
};
// A local cache is NOT a transaction: production writes must use DB unique constraint
// and award points in the same SQL transaction, with retry-safe semantics.
inline bool RecordLocally(std::unordered_set<DiscoveryKey, DiscoveryHash>& seen,
    DiscoveryAward const& award, uint64_t& points) {
    if (!award.entry || !seen.insert({award.kind, award.entry}).second)
        return false;
    points += award.points;
    return true;
}
} // namespace encyclopedia
