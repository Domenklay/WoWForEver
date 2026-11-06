#!/usr/bin/env python3
"""Opt-in 70658 dungeon scaling. Run after inject-forever-scaling.py.

Never edits database rows, worldserver state or running containers.
"""
import argparse
import shutil
from pathlib import Path


def once(source, old, new, label):
    matches = source.count(old)
    if matches != 1:
        raise ValueError(f"{label}: expected one anchor, found {matches}")
    return source.replace(old, new, 1)


DUNGEON_HELPERS = r'''
// Locked per Creature until disengage or respawn.
static bool DungeonEnabled(Creature const* creature)
{
    return creature && EnvBool("FOREVER_SCALING_ENABLED", false) &&
        EnvBool("FOREVER_DUNGEON_SCALING_ENABLED", false) &&
        creature->GetMap() && creature->GetMap()->IsNonRaidDungeon() &&
        !creature->IsControlledByPlayer();
}

static forever_scaling::dungeon::EnemyKind DungeonKind(Creature const* creature)
{
    using forever_scaling::dungeon::EnemyKind;
    if (creature->IsDungeonBoss() || creature->isWorldBoss())
        return EnemyKind::Boss;
    if (creature->IsElite())
        return EnemyKind::Elite;
    return EnemyKind::Trash;
}

static uint8 CaptureDungeonPartySize(Creature const* creature, Unit const* target)
{
    if (!DungeonEnabled(creature) || !target)
        return 0;

    Player const* first = target->GetControllingPlayer();
    if (!first || !first->IsAlive() || first->IsGameMaster() ||
        !creature->IsHostileTo(first))
        return 0;

    Group const* group = first->GetGroup();
    uint8 eligible = 0;
    for (MapReference const& ref : creature->GetMap()->GetPlayers())
    {
        Player const* player = ref.GetSource();
        if (player && player->IsAlive() && !player->IsGameMaster() &&
            (player == first || (group && player->GetGroup() == group)))
            ++eligible;
    }
    return uint8(std::clamp<int>(eligible, 1, 5));
}

static double DungeonHealthFactor(Creature const* creature, uint8 partySize)
{
    return forever_scaling::dungeon::EncounterSnapshot(partySize)
        .HealthMultiplier(DungeonKind(creature));
}

static float DungeonDamageFactor(Creature const* creature, WorldObject const* target, uint8 partySize)
{
    if (!partySize || !DungeonEnabled(creature) || !target)
        return 1.0f;

    Unit const* unitTarget = target->ToUnit();
    Player const* player = unitTarget ? unitTarget->GetControllingPlayer() : nullptr;
    if (!player || player->IsGameMaster() || !creature->IsHostileTo(player))
        return 1.0f;

    return float(forever_scaling::dungeon::EncounterSnapshot(partySize)
        .DamageMultiplier(DungeonKind(creature)));
}
'''


def inject(core: Path, module: Path):
    core = core.resolve()
    header = core / 'src/server/game/Entities/Creature/Creature.h'
    source_path = core / 'src/server/game/Entities/Creature/Creature.cpp'
    policy_path = source_path.parent / 'ForeverDungeonPolicy.hpp'
    source = source_path.read_text()
    declaration = header.read_text()

    if '_foreverDungeonPartySize' in declaration:
        markers = ('#include "ForeverDungeonPolicy.hpp"', 'CaptureDungeonPartySize(',
                   'DungeonDamageFactor(this, target, _foreverDungeonPartySize)',
                   '_foreverDungeonOriginalMaxHealth')
        if not all(marker in source or marker in declaration for marker in markers):
            raise ValueError('Partial ForeverDungeon injection detected')
        shutil.copy2(module / 'server/DungeonPolicy.hpp', policy_path)
        return

    if 'namespace ForeverScalingCore' not in source:
        raise ValueError('Personal ForeverScaling must be injected first')

    declaration = once(
        declaration, '        bool _regenerateHealth; // Set on creation',
        '        uint8 _foreverDungeonPartySize = 0; // Locked until disengage/respawn\n'
        '        uint64 _foreverDungeonOriginalMaxHealth = 0;\n'
        '        bool _regenerateHealth; // Set on creation', 'Creature.h state')
    source = once(source, '#include "Map.h"\n',
                  '#include "Map.h"\n#include "ForeverDungeonPolicy.hpp"\n',
                  'Creature.cpp include')
    source = once(source, '} // namespace ForeverScalingCore\n\n',
                  DUNGEON_HELPERS + '} // namespace ForeverScalingCore\n\n',
                  'policy helpers')
    source = once(source,
                  'void Creature::AtEngage(Unit* target)\n{\n    Unit::AtEngage(target);',
                  '''void Creature::AtEngage(Unit* target)
{
    if (!_foreverDungeonPartySize)
    {
        uint8 partySize = ForeverScalingCore::CaptureDungeonPartySize(this, target);
        if (partySize)
        {
            _foreverDungeonPartySize = partySize;
            uint64 originalMax = GetMaxHealth();
            double factor = ForeverScalingCore::DungeonHealthFactor(this, partySize);
            uint64 scaledMax = forever_scaling::dungeon::EncounterSnapshot::ScaleUnsigned(originalMax, factor);
            if (scaledMax && scaledMax < originalMax)
            {
                _foreverDungeonOriginalMaxHealth = originalMax;
                uint64 scaledCurrent = forever_scaling::dungeon::EncounterSnapshot::ScaleUnsigned(GetHealth(), factor);
                SetMaxHealth(scaledMax);
                SetHealth(std::min(scaledMax, scaledCurrent));
                ResetPlayerDamageReq();
            }
        }
    }
    Unit::AtEngage(target);''', 'AtEngage')
    source = once(source,
                  'void Creature::AtDisengage()\n{\n    Unit::AtDisengage();',
                  '''void Creature::AtDisengage()
{
    if (_foreverDungeonPartySize)
    {
        if (_foreverDungeonOriginalMaxHealth && IsAlive() && GetMaxHealth())
        {
            double fraction = double(GetHealth()) / double(GetMaxHealth());
            uint64 restored = forever_scaling::dungeon::EncounterSnapshot::ScaleUnsigned(
                _foreverDungeonOriginalMaxHealth, fraction);
            SetMaxHealth(_foreverDungeonOriginalMaxHealth);
            SetHealth(restored);
            ResetPlayerDamageReq();
        }
        _foreverDungeonPartySize = 0;
        if (IsAlive())
            _foreverDungeonOriginalMaxHealth = 0;
    }
    Unit::AtDisengage();''', 'AtDisengage')
    source = once(source,
                  'void Creature::setDeathState(DeathState s)\n{\n    Unit::setDeathState(s);',
                  '''void Creature::setDeathState(DeathState s)
{
    if (s == JUST_RESPAWNED)
    {
        if (_foreverDungeonOriginalMaxHealth)
            SetMaxHealth(_foreverDungeonOriginalMaxHealth);
        _foreverDungeonOriginalMaxHealth = 0;
        _foreverDungeonPartySize = 0;
    }
    Unit::setDeathState(s);''', 'respawn')
    source = once(source,
                  '    return GetBaseDamageForLevel(levelForTarget) / GetBaseDamageForLevel(GetLevel());',
                  '''    float personalMultiplier = GetBaseDamageForLevel(levelForTarget) / GetBaseDamageForLevel(GetLevel());
    return personalMultiplier * ForeverScalingCore::DungeonDamageFactor(this, target, _foreverDungeonPartySize);''',
                  'target damage')
    # Write all source after verifying every anchor.
    header.write_text(declaration)
    source_path.write_text(source)
    shutil.copy2(module / 'server/DungeonPolicy.hpp', policy_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--module', type=Path, required=True)
    args = parser.parse_args()
    inject(args.core, args.module)
