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
        '#include <algorithm>\n#include <cstdlib>\n#include <cstring>\n#include <sstream>\n',
        'Creature.cpp standard include anchor',
    )

    helper = r'''namespace ForeverScalingCore
{
enum class Rank { Normal, Elite, RareElite, Boss };

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
    level_replacement = level_anchor + '''    if (ForeverScalingCore::EnabledFor(this, target))\n        return ForeverScalingCore::LevelFor(this, target->ToPlayer());\n\n'''
    source = replace_once(source, level_anchor, level_replacement, 'Creature::GetLevelForTarget entry')

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
