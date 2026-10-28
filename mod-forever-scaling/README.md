# WoW Forever Scaling — design scaffold v0.1.0

Status: specification only; not compiled or deployed.

## Scope
World, dungeons and raids. Player level cap stays at 60. Never write scaled levels to creature_template or persistent spawn data.

## Level policy
For player level P and configured baseline B:
scaledLevel = clamp(B, max(1,P-9), min(serverCreatureLevelCap,P+10)).
A server creature level cap of at least 70 is required to support +10 at player level 60. If the core/client cannot support it, use a lower visible level with equivalent normalized stats.

Baseline defaults: normal P; elite P+5; rare elite P+7; bosses P+8. These are design defaults, not yet implemented. Use party encounter-level snapshot on combat engage; do not rescale active NPC on target changes. For mixed-level groups choose one encounter reference level and mitigate damage per recipient separately; never allow target switching to heal or reinitialize NPC.

## Damage guard
After mitigation, on NPC-to-player damage only, cap ordinary single-hit damage at:
normal 20%; elite 30%; rare elite 40%; boss 45% of victim max HP.
Never modify PvP, environmental damage, self-damage, fall damage or GM actions. Periodic and multi-hit damage require a rolling-window budget, not just per-hit caps. Explicit boss scripted lethal mechanics may need audited exceptions.
Apply the guard at a single authoritative damage stage, after armor/resistance, before health modification, with no double application.

## Compatibility checks required before implementation
Determine TrinityCore branch, client build, CreatureScript/UnitScript APIs, damage pipeline, creature stat recalculation, max supported creature level, spell scaling, threat, XP/loot, instance and raid scaling, group composition, and any existing modules.
Do not merge or enable without build + integration tests.

## Acceptance tests
P=10 => allowed [1,20]; P=60 => [51,70].
No health reset mid-combat; no PvP damage changes; NPC spells and DOT respect budgets; raids and world bosses keep mechanics; scaling does not affect summons or friendly NPCs; loot/XP abuse prevented; load test with many active creatures.
