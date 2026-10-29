#include "ScriptMgr.h"
#include "Creature.h"
#include "Player.h"
#include "Map.h"
#include "Log.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace ForeverScaling
{
enum class Rank
{
    Normal,
    Elite,
    RareElite,
    Boss
};

static bool EnvBool(char const* name, bool fallback)
{
    char const* raw = std::getenv(name);
    if (!raw || !*raw)
        return fallback;

    return std::strcmp(raw, "1") == 0 || std::strcmp(raw, "true") == 0 || std::strcmp(raw, "TRUE") == 0 ||
           std::strcmp(raw, "yes") == 0 || std::strcmp(raw, "YES") == 0 || std::strcmp(raw, "on") == 0 || std::strcmp(raw, "ON") == 0;
}

static int EnvInt(char const* name, int fallback, int low, int high)
{
    char const* raw = std::getenv(name);
    if (!raw || !*raw)
        return fallback;

    char* end = nullptr;
    long value = std::strtol(raw, &end, 10);
    if (!end || *end != '\0')
        return fallback;

    return std::clamp<int>(static_cast<int>(value), low, high);
}

static bool Enabled()
{
    static bool const value = EnvBool("FOREVER_SCALING_ENABLED", false);
    return value;
}

static bool DamageGuardEnabled()
{
    static bool const value = EnvBool("FOREVER_SCALING_DAMAGE_GUARD", true);
    return value;
}

static Rank RankOf(Creature const* creature)
{
    if (creature->IsDungeonBoss() || creature->isWorldBoss())
        return Rank::Boss;
    if (creature->HasClassification(CreatureClassifications::RareElite))
        return Rank::RareElite;
    if (creature->IsElite())
        return Rank::Elite;
    return Rank::Normal;
}

static uint32 CapPercent(Rank rank)
{
    switch (rank)
    {
        case Rank::Elite:
            return uint32(EnvInt("FOREVER_SCALING_CAP_ELITE", 30, 1, 100));
        case Rank::RareElite:
            return uint32(EnvInt("FOREVER_SCALING_CAP_RARE_ELITE", 40, 1, 100));
        case Rank::Boss:
            return uint32(EnvInt("FOREVER_SCALING_CAP_BOSS", 45, 1, 100));
        default:
            return uint32(EnvInt("FOREVER_SCALING_CAP_NORMAL", 20, 1, 100));
    }
}

class DamageGuard final : public UnitScript
{
public:
    DamageGuard() : UnitScript("forever_scaling_damage_guard") { }

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        if (!Enabled() || !DamageGuardEnabled() || !damage || !attacker || !victim)
            return;

        Player* player = victim->ToPlayer();
        Creature* creature = attacker->ToCreature();
        if (!player || !creature || creature->IsControlledByPlayer())
            return;

        Map* map = player->GetMap();
        if (!map || map->IsBattlegroundOrArena())
            return;

        uint64 maxHealth = player->GetMaxHealth();
        if (!maxHealth)
            return;

        uint64 cap = std::max<uint64>(1, maxHealth * CapPercent(RankOf(creature)) / 100);
        if (damage > cap)
            damage = uint32(std::min<uint64>(cap, std::numeric_limits<uint32>::max()));
    }
};
} // namespace ForeverScaling

void AddSC_forever_scaling()
{
    new ForeverScaling::DamageGuard();
    LOG_INFO("server.loading", "ForeverScaling: adapter registered (enabled={}, damageGuard={})",
        ForeverScaling::Enabled(), ForeverScaling::DamageGuardEnabled());
}
