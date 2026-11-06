#include "../server/DungeonPolicy.hpp"
#include "../server/ScalingPolicy.hpp"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>
#include <type_traits>

using forever_scaling::dungeon::EncounterSnapshot;
using forever_scaling::dungeon::EnemyKind;
using forever_scaling::dungeon::Tuning;

static bool Near(double a, double b)
{
    return std::abs(a - b) < 1e-12;
}

int main()
{
    static_assert(!std::is_copy_assignable<EncounterSnapshot>::value,
                  "An active encounter snapshot must not be reassigned");

    EncounterSnapshot solo(1);
    assert(solo.PartySize() == 1);
    assert(Near(solo.HealthMultiplier(EnemyKind::Trash), 0.40));
    assert(Near(solo.HealthMultiplier(EnemyKind::Elite), 0.50));
    assert(Near(solo.HealthMultiplier(EnemyKind::Boss), 0.55));
    assert(Near(solo.DamageMultiplier(EnemyKind::Trash), 0.60));
    assert(Near(solo.DamageMultiplier(EnemyKind::Boss), 0.75));

    EncounterSnapshot duo(2);
    assert(Near(duo.HealthMultiplier(EnemyKind::Trash), 0.55));
    assert(Near(duo.HealthMultiplier(EnemyKind::Boss), 0.6625));
    assert(Near(duo.DamageMultiplier(EnemyKind::Boss), 0.8125));

    for (int n = 1; n <= 5; ++n)
    {
        EncounterSnapshot snapshot(n);
        assert(snapshot.PartySize() == n);
        for (auto kind : { EnemyKind::Trash, EnemyKind::Elite, EnemyKind::Boss })
        {
            assert(snapshot.HealthMultiplier(kind) > 0.0);
            assert(snapshot.HealthMultiplier(kind) <= 1.0);
            assert(snapshot.DamageMultiplier(kind) > 0.0);
            assert(snapshot.DamageMultiplier(kind) <= 1.0);
        }
        if (n > 1)
        {
            EncounterSnapshot previous(n-1);
            assert(snapshot.HealthMultiplier(EnemyKind::Boss) >
                   previous.HealthMultiplier(EnemyKind::Boss));
            assert(snapshot.DamageMultiplier(EnemyKind::Trash) >
                   previous.DamageMultiplier(EnemyKind::Trash));
        }
    }

    EncounterSnapshot full(5);
    assert(Near(full.HealthMultiplier(EnemyKind::Trash), 1.0));
    assert(Near(full.HealthMultiplier(EnemyKind::Boss), 1.0));
    assert(Near(full.DamageMultiplier(EnemyKind::Trash), 1.0));
    assert(Near(full.DamageMultiplier(EnemyKind::Boss), 1.0));
    assert(EncounterSnapshot(0).PartySize() == 1);
    assert(EncounterSnapshot(-99).PartySize() == 1);
    assert(EncounterSnapshot(99).PartySize() == 5);

    Tuning custom;
    custom.baselinePlayers = 3;
    EncounterSnapshot trio(3, custom);
    assert(trio.PartySize() == 3);
    assert(Near(trio.HealthMultiplier(EnemyKind::Boss), 1.0));
    assert(EncounterSnapshot(99, custom).PartySize() == 3);

    assert(EncounterSnapshot::ScaleUnsigned(1000, solo.HealthMultiplier(EnemyKind::Trash)) == 400);
    assert(EncounterSnapshot::ScaleUnsigned(1000, solo.HealthMultiplier(EnemyKind::Boss)) == 550);
    assert(EncounterSnapshot::ScaleUnsigned(1000, full.HealthMultiplier(EnemyKind::Boss)) == 1000);
    assert(EncounterSnapshot::ScaleUnsigned(101, 0.4) == 41);
    assert(EncounterSnapshot::ScaleUnsigned(999, 0.55) == 550);
    assert(EncounterSnapshot::ScaleUnsigned(0, 0.5) == 0);
    assert(EncounterSnapshot::ScaleUnsigned(1, 0.4) == 1);
    assert(EncounterSnapshot::ScaleUnsigned(100, 5.0) == 100);
    assert(EncounterSnapshot::ScaleUnsigned(100, -2.0) == 1);
    assert(EncounterSnapshot::ScaleUnsigned(100, std::numeric_limits<double>::quiet_NaN()) == 100);
    assert(EncounterSnapshot::ScaleUnsigned(std::numeric_limits<std::uint64_t>::max(), 1.0) ==
           std::numeric_limits<std::uint64_t>::max());

    // The shared encounter snapshot never alters the existing per-player level:
    // one level-6 NPC is still level 11 for a level-20 player and level 51 for 60.
    const forever_scaling::Config levelPolicy{};
    assert(forever_scaling::Level(20, 6, forever_scaling::Rank::Normal, levelPolicy) == 11);
    assert(forever_scaling::Level(60, 6, forever_scaling::Rank::Normal, levelPolicy) == 51);
    assert(solo.PartySize() == 1); // a new group must create a new snapshot
}
