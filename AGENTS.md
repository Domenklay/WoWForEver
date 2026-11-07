# Instructions for assistants — current WoWForEver

Updated 2026-11-07, Europe/Moscow. Start with:

1. [Current server handoff](https://github.com/Domenklay/WoWForEver/blob/main/docs/CURRENT-SERVER.ru.md).
2. [Machine-readable state](https://github.com/Domenklay/WoWForEver/blob/main/docs/current-server.json).
3. The component guide linked from the handoff.

**Working code: `codex/native-cdn-70658-20261106`.** Main also publishes these
entry points; its legacy code is not the deployed implementation. Use a separate
checkout/worktree of the working branch. Historical 70450/70532, root Compose and
old install-dev instructions do not describe the active ready generation.

## Confirmed state

- User PC: Windows + Ubuntu/WSL + Docker Desktop. A cloud workspace or Git access
  does not give access to that PC. Never claim user deployment from cloud tests.
- Client wowf 1.60.1.70658; last known gameDir is
  `E:\WoWForEver-work\clients\70658\_forever_`. Read current settings when needed.
- Core advocaite/TrinityCore forever at exact
  `b4e7b940593f6402a822d4fbcdf31331d16f73b6`.
- Project `forever-clean`, root `/home/Kayter/WoWForEver-clean`, state phase ready.
- World image `forever-trinitycore:gameplay-70658-54f07b4ce9ca`.
- Ascension 1.13.0/protocol 3, Encyclopedia 0.9.8-v2.1-smartai-abilities,
  Forever Scaling 0.4.0, DungeonFinder 0.2.0 (solo+group enabled). Autolevel means NPC Scaling, not character leveling.
- State DB label `gameplay-1.13@pristine-b4e7b940593f` is not an independently queried
  upstream world-schema revision. Realm 70, content set 137, region group 8.
- Loopback ports 1119/8081/8085, web 8088. MySQL is not host-published.
- General working gameplay confirmed by user; detailed acceptance is incomplete.

## Active files and operations

`~/WoWForEver-clean/server.sh` calls
`/home/Kayter/WoWForEver-dungeon-upgrade-70658/scripts/clean-forever-server.py`.
Keep that worktree AND `/home/Kayter/WoWForEver-clean-tools.ZbyhNF`: the latter
provides active mysql-init.sh and bnet entrypoint bind files. Confirmed mounts
are documented in the handoff and JSON. Certificates: `~/WoWForEver/certs`;
server resources: `~/WoWForEver-clean/data`. The filtered data_directory is unset and
uses that confirmed default. Do not guess dependencies from folder age.

Use `~/WoWForEver-clean/server.sh status|start|stop|restart` for normal lifecycle.
Stop leaves MySQL running. New tool worktrees do not automatically replace the
active controller. Verify references before moving/deleting any worktree.
Worldserver has its entrypoint in the image. Configs are generated under
`/opt/trinitycore/etc`; legacy host overrides are not mounted into this worldserver.
Source extraction and selected launcher client path are independent.

## Backup and validation status

User confirmed BASELINE BACKUP VERIFIED for the fresh snapshot
`/mnt/e/WoWForEver-work/reports/baseline-70658-20261107-003902` created on source 877b877.
Keep the previous verified `baseline-70658-20261106-231543` as an older reference.
This snapshot contains the four-DB SQL, resources/TLS/settings/controller sources and
exact images captured at its creation, not the WoW client. It predates the current
1.13 / Scaling 0.4 / Finder 0.2 upgrade; it is not a fresh snapshot of that generation. Module rollback record:
`~/WoWForEver-clean/advancement/4bae99119c86/install.json`; its databases-before
dump predates installation and is not the fresh databases-current dump.

Offline verification supports classic config IDs, containerd OCI root IDs and
non-runnable OCI-empty artifact configs. Never edit expected hashes to pass.
`test-baseline-restore.py` uses a NEW labelled MySQL and volume, no network/ports/
live binds, 1 CPU/1GiB, and temporary credentials. It compares counts/schema and
ten module tables; cleanup removes only nonce-owned resources. No live Compose
or state is a restore target. `--cleanup-report` validates identity/path/labels.
Real MySQL integration CI 42295336273 passed with generated data, views, module
values, invalid-SQL rejection, cleanup and unchanged-source checks. The actual
user-side four-database trial also PASSED on source 877b877, including count/schema
comparison, ten module tables and removal of its trial container/volume. Report:
`/mnt/e/WoWForEver-work/reports/restore-test-20261107-004340-520b852f5c8f/report.json`.
User ALSO confirmed RESTORED SERVICES VERIFIED on source b282fb2 for that fresh
baseline: restored worldserver, all three module markers, online realm 70/build
70658, login TCP/TLS with the saved CA, web health/status/public CA and cleanup.
Report: `/home/Kayter/WoWForEver-restore-trials/forever-services-check-885b9c3e9bc2/report.json`.
The tool test-baseline-services.py used private extracted files, saved local image
IDs, a fresh SQL clone/internal network and no host ports/live mounts. All trial
containers/volumes/network and private extracted files were removed on success.
Client login into the restored world and image loading on a blank Docker remain
untested; services startup success is not full end-to-end disaster recovery. Synthetic fixture integration
CI 42301993948 PASSED on source 464c9313: real MySQL, internal network, generated
TLS, HTTP, success/failure cleanup and unchanged source; 473 tests, 30 skips.
These fixtures do not emulate TrinityCore; the actual private-baseline service
startup was confirmed separately by the user above. Do not rerun passed backup,
SQL or service trials without a new change or unresolved concern.

## Launcher

Verified Multi 1.9.0 source `16325671a45fd9702d1364db9060e200eac6c920`:
Windows run 42361020986, artifact 13570041961. 81 launcher tests and 224 worker
tests passed, with five-language UI, PS5.1 and NSIS/portable; archive/EXE hashes,
matching GPL worker sources and unchanged CA checked. Chromium verified controls,
save/reopen/cancel and disabled file mutations. User screenshot confirms the AddOns page is in use, but exact EXE version, journal and auto-login runtime checks remain pending;
working baseline launcher remains 1.7.0, with previous verified release 1.7.1.

Authoritative public AddOn list: main/addons/channels.json. Runtime fetches this
catalogue; exact payload commit/size/SHA256 pins define the complete stable/testing
sets. Stable remains Ascension 1.11.0/Encyclopedia 0.9.8; testing now has AddOn Ascension 1.14.0 and Encyclopedia 0.9.23-v2.1-fdf-diagnostics; server candidate is Ascension 1.14.0, active server remains 1.13.0. Read main catalogue fresh before editing; another chat updates Encyclopedia independently. Do not overwrite the independently pinned Encyclopedia payload. Use scripts/update-addon-channel.py
and docs/ADDON-CHANNELS.ru.md for pin/promote; publish the catalogue to MAIN and
synchronize the working branch. Catalogue CI 42399343781 checked the actual pinned
1.14 Git payloads, including all seven loaded files and the preserved stable/Encyclopedia pins. Metadata-only catalogue edits need no launcher rebuild. Old
app/src-tauri/addons/forever-*.json are historical 1.7 snapshots, not runtime inputs.

Defaults: addonChannel=stable, addonUpdatesEnabled=true, clientUpdatesEnabled=true,
addonDevelopmentMode=false, autoGameLogin=true. Pausing AddOn updates skips all
installation/network, including missing folders. Local development preserves existing
folders; missing folders use the selected saved set. For testing the complete release
set, enable AddOn updates and disable local development. All changed folders stage
before any replacement; a journal, per-game lock and backups support rollback/recovery.
Do not manually delete the transaction journal to bypass an interrupted operation.

Client update pause blocks Multi downloads/repairs/resource operations; read-only
verification and launching stay available. Battle.net's own update settings are separate.
Wow.exe now uses ticket login too: refresh after AddOn work, verify returned email
and game account, DPAPI WEB_TOKEN on Windows, no password/ticket in CLI or WTF.
Registry vendor is selected from the chosen EXE; manual-login opt-out remains.
Do not claim actual game login or channel user verification from CI tests.

## Rules and known limits

- Preserve current DBs, accounts/characters/progress, TLS, clients and staged
  70707. Old reset authorization does not authorize deleting this later baseline.
- Do authorized work without unnecessary repeated confirmations. Gather bounded,
  filtered runtime facts only when missing information matters. Do not request
  full private state/Compose/session files, SQL dumps or private backup archives.
- Never publish private keys, passwords/tokens or game client/data. Public CA,
  sources and filtered version/path facts are allowed. Keep source/license notices.
- Do not use down -v, prune, purge-old, legacy install-dev/root Compose, reinstall
  or reset as routine fixes for this ready server. Do not restart first DB import.
- Installer install is not a universal arbitrary-source upgrade. Do not rollback
  just to bypass its active fingerprint check. Prepare separate transitions,
  isolated DB clones, full build before downtime and precise rollback scope.
- A profile/build/.build.info change is not protocol or data migration. Preserve
  pinned 70658 until actual compatible client/core/data are prepared and verified.
- Distinguish user smoke confirmation, CI compilation, trial DB restore and full
  recovery. Previous client ACCESS_VIOLATION root cause is still unproven.
- Barrier 701463 is unimplemented/blocked; Ability Essence economy is incomplete;
  complex procs/pets/full talents are partial. Companion template 1933 is diagnostic;
  flying-book appearance unverified. Scaling guard is per-event; five-player dungeon HP/damage scaling is active,
  with loot scaling and detailed gameplay acceptance incomplete. Mmap pathfinding is disabled.
- After confirmed changes update CURRENT-SERVER.ru.md and current-server.json and
  keep main's entry point current. Release availability is not user installation.

## Checks

Use component-appropriate tests; never use a live install/reset as a test.
`python3 -m unittest discover -s tests -q`; UI:
`node tests/fixtures/launcher-content-ui.js .`. Launcher:
`cargo test --locked --lib` in app/src-tauri with a PUBLIC CA, or Windows CI when
that toolchain is unavailable. Keep all five launcher languages synchronized.
Real restore integration is opt-in FOREVER_RESTORE_INTEGRATION=1 with generated
Docker/MySQL data, as configured in baseline-backup.yml. Native worker license
and matching source must accompany binary delivery. Core changes compile against
the exact pinned headers/CMake flags; syntax checks alone do not prove linking
or gameplay. Follow the current user's authorization over historical guidelines.

## Current native multiclass work

User confirmed active Ascension 1.13, Scaling 0.4, DungeonFinder 0.2; controller
/home/Kayter/WoWForEver-dungeon-upgrade-70658 at a1bc54e3aed2aa2d08e4c0c41213b295cf01d987.
Combined fingerprint 54f07b4ce9cadef8561096e6074d400d2a80a9d983fc5e7815e74c18157a9f52
and advancement 53c704ac9d98823769614008101390981bc9260fa879de87e6f512b285870520
were reproduced before changes. Keep this active checkout. Source includes the
same Scaling 0.4 and DungeonFinder 0.2 modules. Do not use the old 1.11/Scaling0.2
installer as an upgrade or silently downgrade these working modules.

Native tab is now CONFIRMED visible/working. Exact host: inner
PlayerSpellsFrame.TalentsFrame.TabSystem (301x32), NOT outer PlayerSpellsFrame.TabSystem.
ButtonsParent is a clipped node canvas. User rejected brown flat presentation,
mounts in class abilities, duplicate schools, and empty trees. Copied live node
coordinates were GridX 50..53. Candidate 1.14 filters real player schools (pet and
collection skill-lines are also category CLASS), rejects mount/generic quest
spells, uses one native talent source per class, native school IDs and relative
branch coordinates. Startup requires three schools for each classic class.
Artwork uses actual talents-background-<class>-<spec> atlases and native tabs/panels.
TOC has SEVEN files including TalentSchools.lua. Don't substitute pet trees or
invent abilities by matching translated names. Keep native TraitMgr validation.

Candidate source c13cdbff6cc0623e24a8667d42f343b80f8005a8, protocol3.
CI 42398310341/42398310377/42398310367 passed; local 499 tests, 30 skips; UI 31.
Guide docs/MULTICLASS-1.14.ru.md. Active server is still 1.13, NOT 1.14.
Native real-catalogue audit/full linking/user gameplay verification are pending
in prepare; don't claim CI compilation as deployment. New profile check accepts
the confirmed active 13/Scaling04/Finder02 generation. Current world environment
values and other services remain exact; SQL is preferences-only and rollback
never imports old SQL. Use successful prepare's exact record and same checkout
for apply/rollback. Preserve the existing transition 347c815174f8 as historical.
