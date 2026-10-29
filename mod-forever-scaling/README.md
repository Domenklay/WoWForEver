# WoW Forever Scaling v0.1.0

Status: integration candidate for the pinned TrinityCore Forever revision `91d49b230f89c3ab4719f5b2b2d1e70ed36613c4`. Policy tests pass. A full TrinityCore Docker compile is still required on the server before calling the module build-verified.

## Scope

The module is compiled into `worldserver` but is disabled until `FOREVER_SCALING_ENABLED=1`. It changes no creature database rows and writes no persistent scaled level to `creature_template` or spawn data.

It applies to hostile NPCs in the outdoor world, dungeons and raids. Battlegrounds/arenas and player-controlled creatures are excluded.

## Level policy

For player level `P`, the default allowed window is `P-9 .. P+10`, clamped to valid positive levels and the configured creature ceiling.

Default baselines:

- normal: `P`
- elite: `P+5`
- rare elite: `P+7`
- boss/world boss: `P+8`

The integration hooks the pinned core's existing per-target creature level, health, damage and armor multiplier path. Default creature ceiling is 70 so a level-60 player can encounter creatures up to 70. This must be confirmed against client behaviour during the first live test.

## Damage guard

`UnitScript::OnDamage` caps NPC-to-player damage events to a percentage of the victim's maximum HP:

- normal: 20%
- elite: 30%
- rare elite: 40%
- boss: 45%

Player-controlled attackers and battleground/arena combat are excluded. This v0.1.0 guard is per damage event; rolling-window handling for intentional rapid multi-hit/DoT mechanics and explicit scripted lethal-mechanic exceptions remain follow-up work after live combat logs are available.

## Install

Run from the initialized `~/WoWForEver` server checkout:

```bash
bash scripts/forever-scaling-mod.sh install
```

The installer:

1. runs policy/static checks;
2. preserves the currently running `worldserver` image and `.env`;
3. builds the new image inside Docker while the old server keeps running;
4. verifies image label `org.wowforever.scaling=0.1.0`;
5. enables scaling and recreates only `worldserver` after a successful build;
6. prints the exact rollback command and backup directory.

No host C++ compiler is required.

Useful commands:

```bash
bash scripts/forever-scaling-mod.sh status
bash scripts/forever-scaling-mod.sh disable
bash scripts/forever-scaling-mod.sh rollback backups/scaling-YYYYMMDD-HHMMSS
```

## First live acceptance test

Use a level-60 character and verify a normal hostile creature, an elite and a boss. Check visible level, max HP, outgoing/incoming damage and whether any spell or scripted mechanic bypasses the expected scaling. Also test a low-level character and a friendly NPC to confirm only hostile NPCs are affected.
