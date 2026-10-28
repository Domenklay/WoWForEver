#include "../server/DiscoveryPolicy.h"
#include <cassert>
int main() {
    using namespace encyclopedia;
    std::unordered_set<DiscoveryKey, DiscoveryHash> known;
    uint64_t points = 0;
    assert(RecordLocally(known, {DiscoveryKind::Creature, 100, 1}, points));
    assert(!RecordLocally(known, {DiscoveryKind::Creature, 100, 1}, points));
    assert(RecordLocally(known, {DiscoveryKind::Item, 100, 1}, points));
    assert(points == 2);
    std::vector<ZoneCreature> zone = {{100,true,false}, {100,true,false},
        {200,true,false}, {300,false,false}, {400,true,true}};
    ZoneSummary s = SummarizeZone(zone, known);
    assert(s.total == 2 && s.discovered == 1);
    return 0;
}
