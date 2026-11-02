#!/usr/bin/env python3
"""Inject Forever Scaling into the pinned TrinityCore Forever source tree.

v0.2 uses TrinityCore's target-dependent level/stat path instead of mutating the
physical Creature level.  This allows the same creature to be scaled differently
for different players at the same time.
"""
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
    int originalLevel = std::max(1, int(creature->GetLevel()));
    int minOffset = EnvInt("FOREVER_SCALING_MIN_OFFSET", -9, -100, 100);
    int creatureMax = EnvInt("FOREVER_SCALING_CREATURE_MAX_LEVEL", 70, 1, 255);

    // Forever progression rule: preserve the creature's original level unless it
    // fell below the minimum-XP floor for this particular player.
    // Examples: player 11 + creature 6 => 6; player 20 + creature 6 => 11;
    // player 60 + creature 6 => 51.  The physical Creature level is never changed.
    int minimumXpLevel = std::max(1, playerLevel + minOffset);
    int raisedLevel = std::min(creatureMax, minimumXpLevel);
    return uint8(std::clamp(std::max(originalLevel, raisedLevel), 1, 255));
}
} // namespace ForeverScalingCore

'''
    source = replace_once(
        source,
        'CreatureMovementData::CreatureMovementData()',
        helper + 'CreatureMovementData::CreatureMovementData()',
        'Creature.cpp first implementation anchor',
    )

    # Enable TrinityCore's existing target-dependent virtual health/damage/armor
    # ratios for fixed-level classic creatures covered by ForeverScaling.
    for function in ('GetHealthMultiplierForTarget', 'GetDamageMultiplierForTarget', 'GetArmorMultiplierForTarget'):
        old = f'''float Creature::{function}(WorldObject const* target) const\n{{\n    if (!HasScalableLevels())\n        return 1.0f;\n\n    uint8 levelForTarget = GetLevelForTarget(target);'''
        new = f'''float Creature::{function}(WorldObject const* target) const\n{{\n    if (!HasScalableLevels() && !ForeverScalingCore::EnabledFor(this, target))\n        return 1.0f;\n\n    uint8 levelForTarget = GetLevelForTarget(target);'''
        source = replace_once(source, old, new, f'Creature::{function} scaling gate')

    # The virtual level is computed independently for every viewing/attacking player.
    level_anchor = '''uint8 Creature::GetLevelForTarget(WorldObject const* target) const\n{\n'''
    level_replacement = level_anchor + '''    if (ForeverScalingCore::EnabledFor(this, target))\n        return ForeverScalingCore::LevelFor(this, target->ToPlayer());\n\n'''
    source = replace_once(source, level_anchor, level_replacement, 'Creature::GetLevelForTarget entry')

    path.write_text(source)


def patch_update_fields(core):
    """Make classic fixed-level creature level/health viewer-dependent on the wire.

    TrinityCore already normalizes combat through GetHealthMultiplierForTarget,
    GetDamageMultiplierForTarget and GetArmorMultiplierForTarget.  Classic fixed
    creatures, however, normally serialize one raw Level/Health/MaxHealth value to
    every client.  For ForeverScaling creatures we serialize the virtual values for
    the receiving player so two group members can see the same shared creature at
    different effective levels and absolute HP while preserving the same HP percent.
    """
    path = core / 'src/server/game/Entities/Object/Updates/UpdateFields.cpp'
    source = path.read_text()

    source = replace_once(
        source,
        '#include "ClassicOpcodes.h"\n',
        '#include "ClassicOpcodes.h"\n#include "Creature.h"\n',
        'UpdateFields.cpp ClassicOpcodes include',
    )

    helper = r'''static Creature const* ForeverScalingViewerCreature(Unit const* owner, Player const* receiver)
{
    if (!owner || !receiver)
        return nullptr;

    Creature const* creature = owner->ToCreature();
    if (!creature || creature->HasScalableLevels() || creature->IsControlledByPlayer())
        return nullptr;

    // GetLevelForTarget/GetHealthMultiplierForTarget contain the authoritative
    // ForeverScaling enabled/hostility/BG checks. Friendly or excluded creatures
    // therefore naturally resolve to their raw level and multiplier 1.0.
    return creature;
}

static int32 ForeverScalingViewerLevel(int32 rawLevel, Player const* receiver, Unit const* owner)
{
    if (Creature const* creature = ForeverScalingViewerCreature(owner, receiver))
        return int32(creature->GetLevelForTarget(receiver));
    return rawLevel;
}

static int64 ForeverScalingViewerHealth(int64 rawHealth, Player const* receiver, Unit const* owner)
{
    if (rawHealth <= 0)
        return rawHealth;

    if (Creature const* creature = ForeverScalingViewerCreature(owner, receiver))
    {
        double multiplier = creature->GetHealthMultiplierForTarget(receiver);
        if (multiplier > 0.0 && multiplier != 1.0)
            return int64(double(rawHealth) * multiplier + 0.5);
    }

    return rawHealth;
}

'''
    source = replace_once(
        source,
        'void UnitData::WriteCreate(EnumFlag<UpdateFieldFlag> fieldVisibilityFlags, ByteBuffer& data, Player const* receiver, Unit const* owner) const\n{',
        helper + 'void UnitData::WriteCreate(EnumFlag<UpdateFieldFlag> fieldVisibilityFlags, ByteBuffer& data, Player const* receiver, Unit const* owner) const\n{',
        'UpdateFields.cpp UnitData::WriteCreate anchor',
    )

    source = replace_once(
        source,
        '''    data << uint32(OverrideDisplayPowerID);\n    data << int64(Health);\n    for (uint32 i = 0; i < 10; ++i)''',
        '''    data << uint32(OverrideDisplayPowerID);\n    data << ForeverScalingViewerHealth(int64(Health), receiver, owner);\n    for (uint32 i = 0; i < 10; ++i)''',
        'UpdateFields.cpp create health',
    )
    source = replace_once(
        source,
        '''    data << int64(MaxHealth);\n    data << int32(Level);\n    data << int32(EffectiveLevel);''',
        '''    data << ForeverScalingViewerHealth(int64(MaxHealth), receiver, owner);\n    data << ForeverScalingViewerLevel(int32(Level), receiver, owner);\n    data << ForeverScalingViewerLevel(int32(EffectiveLevel), receiver, owner);''',
        'UpdateFields.cpp create max health/level',
    )

    source = replace_once(
        source,
        '''        if (changesMask[38])\n        {\n            data << int64(Health);\n        }\n        if (changesMask[39])\n        {\n            data << int64(MaxHealth);\n        }\n        if (changesMask[40])\n        {\n            data << int32(Level);\n        }\n        if (changesMask[41])\n        {\n            data << int32(EffectiveLevel);\n        }''',
        '''        if (changesMask[38])\n        {\n            data << ForeverScalingViewerHealth(int64(Health), receiver, owner);\n        }\n        if (changesMask[39])\n        {\n            data << ForeverScalingViewerHealth(int64(MaxHealth), receiver, owner);\n        }\n        if (changesMask[40])\n        {\n            data << ForeverScalingViewerLevel(int32(Level), receiver, owner);\n        }\n        if (changesMask[41])\n        {\n            data << ForeverScalingViewerLevel(int32(EffectiveLevel), receiver, owner);\n        }''',
        'UpdateFields.cpp update health/level',
    )

    path.write_text(source)


def inject(core, module):
    core = Path(core).resolve()
    module = Path(module).resolve()
    patch_loader(core, module)
    patch_creature(core)
    patch_update_fields(core)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--module', type=Path, required=True)
    args = parser.parse_args()
    inject(args.core, args.module)
