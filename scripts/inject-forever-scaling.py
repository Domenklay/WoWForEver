#!/usr/bin/env python3
"""Inject Forever Scaling into the pinned TrinityCore Forever source tree."""
import argparse
import re
import shutil
from pathlib import Path


def replace_once(text, old, new, description):
    count = text.count(old)
    if count != 1:
        raise ValueError(f'{description} was not found exactly once (found {count})')
    return text.replace(old, new, 1)


def patch_loader(core, module):
    loader = core / 'src/server/scripts/Custom/custom_script_loader.cpp'
    text = loader.read_text()
    declaration = 'void AddSC_forever_scaling();'
    call = '    AddSC_forever_scaling();'

    if declaration not in text:
        marker = 'void AddCustomScripts()'
        if text.count(marker) != 1:
            raise ValueError('Custom script loader layout is not recognized')
        text = text.replace(marker, declaration + '\n\n' + marker, 1)
    elif text.count(declaration) != 1:
        raise ValueError('Duplicate ForeverScaling declaration in custom loader')

    if call not in text:
        pattern = r'(void AddCustomScripts\(\)\s*\{\s*\n)'
        text, count = re.subn(pattern, r'\1' + call + '\n', text, count=1)
        if count != 1:
            raise ValueError('Cannot register ForeverScaling in AddCustomScripts')
    elif text.count(call) != 1:
        raise ValueError('Duplicate ForeverScaling registration in custom loader')

    target = loader.parent / 'ForeverScaling'
    target.mkdir(exist_ok=True)
    shutil.copy2(module / 'server/ForeverScaling.cpp', target / 'ForeverScaling.cpp')
    loader.write_text(text)


def patch_creature(core):
    path = core / 'src/server/game/Entities/Creature/Creature.cpp'
    source = path.read_text()

    source = replace_once(
        source,
        '#include "Log.h"\n',
        '#include "Log.h"\n#include "Map.h"\n',
        'Creature.cpp Log include',
    )
    source = replace_once(
        source,
        '#include <sstream>\n',
        '#include <algorithm>\n#include <cstdlib>\n#include <cstring>\n#include <sstream>\n#include <unordered_map>\n',
        'Creature.cpp standard include anchor',
    )

    helper = r'''namespace ForeverScalingCore
{
enum class Rank { Normal, Elite, RareElite, Boss };

struct EncounterState
{
    uint8 originalLevel = 1;
    uint8 scaledLevel = 1;
};

static std::unordered_map<uint64, EncounterState> Encounters;

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

static int RankOffset(Rank rank)
{
    switch (rank)
    {
        case Rank::Elite: return EnvInt("FOREVER_SCALING_ELITE_OFFSET", 5, -100, 100);
        case Rank::RareElite: return EnvInt("FOREVER_SCALING_RARE_ELITE_OFFSET", 7, -100, 100);
        case Rank::Boss: return EnvInt("FOREVER_SCALING_BOSS_OFFSET", 8, -100, 100);
        default: return EnvInt("FOREVER_SCALING_NORMAL_OFFSET", 0, -100, 100);
    }
}

static bool EnabledFor(Creature const* creature, WorldObject const* target)
{
    if (!EnvBool("FOREVER_SCALING_ENABLED", false) || !creature || !target)
        return false;

    Player const* player = target->ToPlayer();
    if (!player || creature->IsControlledByPlayer())
        return false;

    Map const* map = creature->GetMap();
    if (!map || map->IsBattlegroundOrArena())
        return false;

    return creature->IsHostileTo(player);
}

static uint8 LevelFor(Creature const* creature, Player const* player)
{
    int playerLevel = std::max(1, int(player->GetEffectiveLevel()));
    int minOffset = EnvInt("FOREVER_SCALING_MIN_OFFSET", -9, -100, 100);
    int maxOffset = EnvInt("FOREVER_SCALING_MAX_OFFSET", 10, -100, 100);
    if (maxOffset < minOffset)
        std::swap(minOffset, maxOffset);

    int creatureMax = EnvInt("FOREVER_SCALING_CREATURE_MAX_LEVEL", 70, 1, 255);
    int low = std::max(1, playerLevel + minOffset);
    int high = std::max(low, std::min(creatureMax, playerLevel + maxOffset));
    int baseline = playerLevel + RankOffset(RankOf(creature));
    return uint8(std::clamp(baseline, low, high));
}

static uint64 EncounterKey(Creature const* creature)
{
    return uint64(creature->GetGUID().GetCounter());
}

static uint8 LockedLevel(Creature const* creature)
{
    auto itr = Encounters.find(EncounterKey(creature));
    return itr == Encounters.end() ? 0 : itr->second.scaledLevel;
}

static void RescalePreservingHealth(Creature* creature, uint8 level)
{
    uint64 oldMax = creature->GetMaxHealth();
    uint64 oldHealth = creature->GetHealth();
    bool alive = creature->IsAlive();

    creature->SetLevel(level);
    creature->UpdateLevelDependantStats();

    if (!alive || !oldMax)
        return;

    uint64 newMax = creature->GetMaxHealth();
    uint64 newHealth = oldHealth >= oldMax ? newMax : (newMax * oldHealth / oldMax);
    creature->SetHealth(std::max<uint64>(1, std::min<uint64>(newHealth, newMax)));
}

static Player* EncounterPlayer(Creature* creature)
{
    Unit* victim = creature->GetVictim();
    if (!victim)
        return nullptr;
    return victim->GetCharmerOrOwnerPlayerOrPlayerItself();
}

static void UpdateEncounter(Creature* creature)
{
    uint64 key = EncounterKey(creature);
    auto itr = Encounters.find(key);

    if (!EnvBool("FOREVER_SCALING_ENABLED", false))
    {
        if (itr != Encounters.end() && creature->IsAlive())
            RescalePreservingHealth(creature, itr->second.originalLevel);
        Encounters.erase(key);
        return;
    }

    if (!creature->IsAlive())
    {
        Encounters.erase(key);
        return;
    }

    if (creature->IsEngaged())
    {
        if (itr != Encounters.end())
            return;

        Player* player = EncounterPlayer(creature);
        if (!player || !EnabledFor(creature, player))
            return;

        EncounterState state;
        state.originalLevel = creature->GetLevel();
        state.scaledLevel = LevelFor(creature, player);
        Encounters.emplace(key, state);
        RescalePreservingHealth(creature, state.scaledLevel);
        return;
    }

    if (itr != Encounters.end())
    {
        uint8 originalLevel = itr->second.originalLevel;
        Encounters.erase(itr);
        RescalePreservingHealth(creature, originalLevel);
    }
}

static void ForgetEncounter(Creature const* creature)
{
    Encounters.erase(EncounterKey(creature));
}
} // namespace ForeverScalingCore

'''
    source = replace_once(
        source,
        'CreatureMovementData::CreatureMovementData()',
        helper + 'CreatureMovementData::CreatureMovementData()',
        'Creature.cpp first implementation anchor',
    )

    for function in ('GetHealthMultiplierForTarget', 'GetDamageMultiplierForTarget', 'GetArmorMultiplierForTarget'):
        old = f'''float Creature::{function}(WorldObject const* target) const\n{{\n    if (!HasScalableLevels())\n        return 1.0f;\n\n    uint8 levelForTarget = GetLevelForTarget(target);'''
        new = f'''float Creature::{function}(WorldObject const* target) const\n{{\n    if (!HasScalableLevels() && !ForeverScalingCore::EnabledFor(this, target))\n        return 1.0f;\n\n    uint8 levelForTarget = GetLevelForTarget(target);'''
        source = replace_once(source, old, new, f'Creature::{function} scaling gate')

    level_anchor = '''uint8 Creature::GetLevelForTarget(WorldObject const* target) const\n{\n'''
    level_replacement = level_anchor + '''    if (uint8 lockedLevel = ForeverScalingCore::LockedLevel(this))\n        return lockedLevel;\n\n    if (ForeverScalingCore::EnabledFor(this, target))\n        return ForeverScalingCore::LevelFor(this, target->ToPlayer());\n\n'''
    source = replace_once(source, level_anchor, level_replacement, 'Creature::GetLevelForTarget entry')

    update_anchor = '''    GetThreatManager().Update(diff);\n\n    switch (m_deathState)'''
    update_replacement = '''    GetThreatManager().Update(diff);\n\n    // Lock one visible/stat level for the whole encounter. This avoids target-switch\n    // oscillation and makes classic fixed-level creatures visibly scale in combat.\n    ForeverScalingCore::UpdateEncounter(this);\n\n    switch (m_deathState)'''
    source = replace_once(source, update_anchor, update_replacement, 'Creature::Update encounter scaling anchor')

    remove_anchor = '''void Creature::RemoveFromWorld()\n{\n    if (IsInWorld())\n    {'''
    remove_replacement = '''void Creature::RemoveFromWorld()\n{\n    ForeverScalingCore::ForgetEncounter(this);\n    if (IsInWorld())\n    {'''
    source = replace_once(source, remove_anchor, remove_replacement, 'Creature::RemoveFromWorld scaling cleanup anchor')

    path.write_text(source)


def inject(core, module):
    core = Path(core).resolve()
    module = Path(module).resolve()
    patch_loader(core, module)
    patch_creature(core)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--module', type=Path, required=True)
    args = parser.parse_args()
    inject(args.core, args.module)
