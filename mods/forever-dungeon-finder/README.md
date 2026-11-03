# Forever Dungeon Finder v0.1.0

Direct-entry dungeon browser for WoW Forever 1.60.1 (`## Interface: 16001`). Forever uses the Mainline-family addon API even though gameplay is vanilla-era.

The module deliberately does **not** use the retail LFG queue/proposal protocol. In the pinned server core, `SendLfgPlayerLockInfo` / `SendLfgPartyLockInfo` intentionally return empty data because retail-format LFG dungeon entries previously crashed this client. The addon therefore supplies its own safe browser while the server uses normal instance teleport/binding.

## What v0.1 does

- installs a client addon named `ForeverDungeonFinder`;
- opens with `/fd`, `/dungeon`, or the minimap button;
- shows the Classic dungeon list with search and details;
- provides separate **Войти соло** and **Войти группой (N)** actions;
- solo mode moves only the requesting player, even if that player currently belongs to a group;
- group mode moves the current online party and requires the party leader;
- performs no role check, matchmaking or queueing;
- uses a hidden registered addon-message prefix (`FDF`) to request entry;
- validates the requested map on the server as a non-raid dungeon;
- uses TrinityCore's ordinary instance teleport/binding path;
- refuses entry while affected participants are dead, in combat, falling/jumping, in PvP instances or on a vehicle;
- keeps the normal return point through `SetBattlegroundEntryPoint()` like TrinityCore's LFG teleport code.

The server feature is runtime-gated by:

```env
FOREVER_DUNGEON_FINDER_ENABLED=1
```

## Relationship to ForeverScaling

This branch is based on ForeverScaling 0.2.0. Enemy level/health presentation and combat scaling remain player-relative. Dungeon Finder v0.1 only handles choosing and entering an instance; player-count difficulty scaling is intentionally the next layer.

Planned next layer after direct-entry acceptance testing:

- snapshot active dungeon party size;
- scale shared enemy HP by party size;
- tune outgoing damage separately from HP scaling;
- scale bosses more aggressively than trash;
- expose dungeon difficulty profiles;
- scale loot/item level against the dungeon/player profile;
- lock encounter party-size scaling to prevent join/leave exploits.

## Current limitation

Several Classic dungeon wings share a map ID. Scarlet Monastery, Maraudon, Dire Maul and similar maps may resolve to the map's default entrance in v0.1. Per-wing destination selection will use LFG dungeon/template IDs after the base solo/group teleport path is confirmed on the live server.

## Install

From the initialized server checkout, with the Forever client at the default WSL path:

```bash
bash scripts/forever-dungeon-finder-mod.sh install /mnt/e/_classic_beta_
```

The installer validates the client path before the long build, preserves the running server image, current Docker/Compose files and any previous `ForeverDungeonFinder` addon folder, then builds while the existing worldserver remains live. It recreates only worldserver after the new image passes its label check.

Useful commands:

```bash
bash scripts/forever-dungeon-finder-mod.sh status
bash scripts/forever-dungeon-finder-mod.sh disable
bash scripts/forever-dungeon-finder-mod.sh rollback backups/dungeon-finder-YYYYMMDD-HHMMSS
```

## First acceptance test

1. Restart the WoW client after installation so the addon is loaded.
2. Confirm `Forever Dungeon Finder` is enabled in the addon list.
3. Log in and run `/fd` or click its minimap button.
4. Select Deadmines and test **Войти соло**.
5. Return, form a normal party, make the tester leader, and use **Войти группой (N)**.
6. Confirm every online party member lands in the same instance.
7. Confirm no LFG queue/role/proposal UI appears.
8. Confirm personalized ForeverScaling still differs correctly for two differently leveled party members.
