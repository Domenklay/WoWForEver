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
Full worldserver/bnetserver/web startup and client login from restored archives
remain untested; a successful SQL trial does not prove full server recovery.
The next tool is test-baseline-services.py (guide BASELINE-SERVICES-RESTORE.ru.md):
private extracted files, saved local image IDs, fresh SQL clone/internal network,
no host ports/live mounts, current world module evidence and TLS/HTTP probes,
label-checked cleanup. It does not test client login or archive image loading on
a blank Docker. Its user-side result is pending. Synthetic fixture integration
CI 42301993948 PASSED on source 464c9313: real MySQL, internal network, generated
TLS, HTTP, success/failure cleanup and unchanged source; 473 tests, 30 skips.
These fixtures do not emulate TrinityCore or prove user-side service startup.

## Launcher

Verified Multi 1.7.1 source `87edd5aa6bdf0168dd25714c17b5815df82f6c68`:
Windows run 42291254078, artifact 13540302260. 61 launcher and 224 worker tests,
five-language UI, PS5.1, NSIS/portable passed; archive/EXE hashes, GPL worker
source and unchanged CA checked. Download/hash are in the handoff. User test of
1.7.1 has not been reported; working baseline launcher is 1.7.0.

Opt-in addonDevelopmentMode preserves existing Ascension/Encyclopedia folders,
even incomplete ones. Missing folders still get pinned verified installation.
Default false; turning off restores normal checks/backups at next launch. UI
checkbox/home notice are translated in RU/FR/EN/ES/PT. Junctions/symlinks remain
unsupported. SavedVariables, other AddOns and CASC are outside AddOn replacement.

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
