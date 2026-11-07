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
- World image `forever-trinitycore:gameplay-70658-4530bd4e14a1`.
- Ascension 1.11.0/protocol 3, Encyclopedia 0.9.8-v2.1-smartai-abilities,
  Forever Scaling 0.2.0. Autolevel means NPC Scaling, not character leveling.
- State DB label `gameplay-1@pristine-b4e7b940593f` is not an independently queried
  upstream world-schema revision. Realm 70, content set 137, region group 8.
- Loopback ports 1119/8081/8085, web 8088. MySQL is not host-published.
- General working gameplay confirmed by user; detailed acceptance is incomplete.

## Active files and operations

`~/WoWForEver-clean/server.sh` calls
`/home/Kayter/WoWForEver-gameplay-tools.hReuvj/scripts/clean-forever-server.py`.
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
This contains current four-DB SQL, resources/TLS/settings/controller sources and
exact images, not the WoW client. Module rollback record:
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
sets. Stable remains Ascension 1.11.0/Encyclopedia 0.9.8; testing now has AddOn Ascension 1.13.1 and Encyclopedia 0.9.20-v2.1-archive-layout; server candidate remains Ascension 1.13.0. Read main catalogue fresh before editing; another chat updates Encyclopedia independently. Do not overwrite the independently pinned Encyclopedia payload. Use scripts/update-addon-channel.py
and docs/ADDON-CHANNELS.ru.md for pin/promote; publish the catalogue to MAIN and
synchronize the working branch. Catalogue CI 42359312577 checked the actual pinned
Git payloads. Metadata-only catalogue edits need no launcher rebuild. Old
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
  flying-book appearance unverified. Scaling guard is per-event, without full
  party/loot scaling. Mmap pathfinding is disabled.
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

## Prepared native multiclass candidate

Active user server is still confirmed 1.11.0. Development source 1.13.0:
90/10 XP with per-character opt-out and capped-subclass refunds; native class
spell catalogue; scrolling abilities; IDs 12/13 removed; Hunter native basics;
transient weapon/armor/dual-wield grants from active subclass with ownership tracking.
Native talent branches/grid/edges/ranks use TraitMgr::ValidateConfig for allocation
and refund. Complex unsupported effects/resources remain blocked. Do not bypass
native conditions/choices/currencies. Old purchases/ranks remain stored.

User screenshot confirmed the initial 1.13 AddNamedTab adapter FAILED in-game:
it selected a hidden retail page but created no tab in the visible talent window.
The copied diagnostic report distinguishes TWO TabSystems. The visible loadout
strip is PlayerSpellsFrame.TalentsFrame.TabSystem (301x32). The outer
PlayerSpellsFrame.TabSystem is hidden. ButtonsParent (1212x641) is a clipped,
high-level node canvas, NEVER the tab's parent. AddOn-only 1.13.1 anchors a sibling
tab after the INNER strip, keeps that strip visible, and restores native trees
when selecting Primary/Secondary or closing the page. /fa selects the same native
TalentsFrame page. Do not add a hidden outer tab or revive a separate window.
AddOn source: 9ae2d724fb9451812fc611501fb10a82d9590619. Protocol remains 3.
No server rebuild is needed for this UI fix; server 1.11 still lacks the new trees
and other 1.13 mechanics. Keep Encyclopedia's independent pin unchanged.
Guide: docs/MULTICLASS-1.13.ru.md. Server source ae6a3f8ed5aa2fd43b65cc704ae88377ee25a8f2.
Server CI 42380875759/42380875788/42380875760 passed. Full local suite: 490 tests,
30 skips; final native tab UI suite: 27 tests. New visible tab still needs user
confirmation in-game. User server remains 1.11 until an actual apply result.

Use upgrade-clean-gameplay.py prepare for a full build + isolated restored-baseline
candidate trial, then its exact record and same checkout for apply/rollback. Accepts
prior active 1.11/1.12. SQL is additive preferences only. Rollback restores runtime
without importing old databases; cancelling a merely prepared candidate must never
stop live services. User trial and installation remain pending. Keep controller worktrees.
Multi 1.9 moves channel/update/development controls to the AddOns page and reads
installed TOC versions plus receipt hashes. Journal is a full page with an empty state.
