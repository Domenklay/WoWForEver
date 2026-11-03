# Forever Dungeon Finder v0.1.0

Direct-entry dungeon browser for WoW Forever. It deliberately does **not** use the retail LFG queue/proposal protocol because the pinned Classic 1.60 client cannot safely consume the retail-format dungeon list. The pinned core itself currently sends those lists empty for this reason.

## What v0.1 does

- installs a client addon named `ForeverDungeonFinder`;
- opens with `/fd`, `/dungeon`, or the minimap button;
- shows the Classic dungeon list with search and details;
- provides separate **Enter solo** and **Enter current group** actions;
- performs no role check, matchmaking or queueing;
- uses a hidden registered addon-message prefix (`FDF`) to request entry;
- validates the requested map on the server as a non-raid dungeon;
- uses TrinityCore's ordinary instance teleport/binding path;
- group entry requires the current party leader and teleports the leader first;
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

Several Classic dungeon wings share a map ID. Scarlet Monastery (`map 189`) is represented as one aggregate entry in v0.1 and uses the map's default entrance trigger. Per-wing destination selection will be added after the base solo/group teleport path is confirmed on the live client.

## Install

From the initialized server checkout, with the Forever client at the default WSL path:

```bash
bash scripts/forever-dungeon-finder-mod.sh install /mnt/e/_classic_beta_
```

The installer preserves the running server image and previous addon folder before building. The existing worldserver remains running during compilation and is recreated only after the new image passes its label check.

Useful commands:

```bash
bash scripts/forever-dungeon-finder-mod.sh status
bash scripts/forever-dungeon-finder-mod.sh disable
bash scripts/forever-dungeon-finder-mod.sh rollback backups/dungeon-finder-YYYYMMDD-HHMMSS
```

## First acceptance test

1. Restart the WoW client after installation so the addon is loaded.
2. Open the addon list and confirm `Forever Dungeon Finder` is enabled.
3. Log in and run `/fd`.
4. Select Deadmines and test **Enter solo**.
5. Return, form a normal party, make the tester leader, and use **Enter group**.
6. Confirm every online party member lands in the same instance.
7. Confirm no LFG queue/role/proposal UI appears.
8. Confirm personalized ForeverScaling still differs correctly for two differently leveled party members.
