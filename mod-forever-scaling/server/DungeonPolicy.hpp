#pragma once
// Pure encounter-wide policy for Classic five-player dungeons.
// This header does NOT register hooks or change the running server.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace forever_scaling::dungeon
{
enum class EnemyKind { Trash, Elite, Boss };

struct Tuning
{
    // Classic dungeon baseline. Raid scaling is deliberately out of scope.
    int baselinePlayers = 5;
    double soloTrashHealth = 0.40;
    double soloEliteHealth = 0.50;
    double soloBossHealth = 0.55;
    double soloTrashDamage = 0.60;
    double soloEliteDamage = 0.65;
    double soloBossDamage = 0.75;
};

class EncounterSnapshot final
{
public:
    // Construct ONCE when an encounter starts. Never recalculate this snapshot
    // for joins, departures, deaths, disconnects or late reinforcements.
    explicit EncounterSnapshot(int eligiblePartyMembers, Tuning tuning = {})
        : baseline_(std::clamp(tuning.baselinePlayers, 1, 5)),
          partySize_(std::clamp(eligiblePartyMembers, 1, baseline_)),
          tuning_(tuning)
    {
    }

    int PartySize() const { return partySize_; }
    int BaselineSize() const { return baseline_; }

    double HealthMultiplier(EnemyKind kind) const
    {
        switch (kind)
        {
            case EnemyKind::Boss: return Linear(tuning_.soloBossHealth);
            case EnemyKind::Elite: return Linear(tuning_.soloEliteHealth);
            default: return Linear(tuning_.soloTrashHealth);
        }
    }

    double DamageMultiplier(EnemyKind kind) const
    {
        switch (kind)
        {
            case EnemyKind::Boss: return Linear(tuning_.soloBossDamage);
            case EnemyKind::Elite: return Linear(tuning_.soloEliteDamage);
            default: return Linear(tuning_.soloTrashDamage);
        }
    }

    static std::uint64_t ScaleUnsigned(std::uint64_t original, double multiplier)
    {
        if (original == 0)
            return 0;

        // Preserve at least one point for positive HP/damage, never exceed
        // the unscaled value, and avoid float -> uint64_t overflow.
        double safe = std::isfinite(multiplier) ? std::clamp(multiplier, 0.0, 1.0) : 1.0;
        long double scaled = std::ceil(static_cast<long double>(original) * safe);
        if (scaled >= static_cast<long double>(std::numeric_limits<std::uint64_t>::max()))
            return original;
        return std::min(original, std::max<std::uint64_t>(1, static_cast<std::uint64_t>(scaled)));
    }

private:
    double Linear(double soloFactor) const
    {
        double floor = std::isfinite(soloFactor) ? std::clamp(soloFactor, 0.0, 1.0) : 1.0;
        if (baseline_ == 1)
            return 1.0;
        return floor + (1.0 - floor) * (partySize_ - 1) / (baseline_ - 1);
    }

    const int baseline_;
    const int partySize_;
    const Tuning tuning_;
};
} // namespace forever_scaling::dungeon
