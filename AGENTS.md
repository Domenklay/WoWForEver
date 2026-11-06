# Instructions for AI coding assistants

The user's revision-2 report establishes the actual ambiguity: the 70707
INSTALL has two Windows x86_64 root Wow.exe entries, CN-only CKey
606df11c09fe22c9456b951a89848329 (109949136 bytes) and EU/KR/TW/US CKey
753e09cce90875e466bbf55c3d3ce169 (85829840 bytes). The common loader is
bff1efe594682fd926c51bacf701bf40 (41311952 bytes). The numeric Windows=1
and x86_64=2 categories were correct for this actual manifest. Revision 3
adds explicit named region-mask selection, default EU, before bootstrap
uniqueness checks. It still does not activate, extract or prove payload
availability/version; await the regional local-read audit output.

The user's first local preload audit read INSTALL successfully but failed to
select a root Windows x64 Wow.exe (bootstrap empty). This is not proof that
the payload is absent. Audit revision 2 selects named masks without assuming
numeric tag categories and retains bounded executable/tag diagnostics on
selection failure. Obtain this output before guessing a filename, product
directory, architecture or activation procedure. No local 70707 EXE or
protocol has yet been verified.

Latest 2026-11-06 evidence: Multi settings still point to the v4 copy, with
127.0.0.1/trinity.actual.battle.net:1119 and build 70658. The earlier requested
original-install logs showed a Nvord login and cannot diagnose the latest v4
failure. Request fresh logs from the saved gameDir, not an assumed folder.
Both actual EXEs are 70658. Source preload config 7feb61f3c994bcb168526b8db521514a
is WOW-70707patch1.60.1_Retail, with verified public metadata fields. Multi 1.4
does not implement client preload activation. The new audit is read-only;
see docs/PRELOAD-AUDIT.ru.md. Do not present a manifest check as a working
updater or relabel an EXE/protocol based only on the package version.

On 2026-11-06 the user authorized moving to 70707 and requested future client
and database upgrades. They then confirmed the ORIGINAL E:\WoW_Forever EXE
and active metadata are still 70658, downloaded with Nvord ForeverLauncher
2.0.5. Do not switch the server or relabel metadata until a real 70707 EXE
is activated. Follow docs/SERVER-UPGRADES.ru.md: new extracted resources,
private four-DB snapshot, isolated DB clone, reviewed versioned migrations,
verified cutover and retained old generation. Never reset existing progress
or reuse its DB volume for staging. The launcher comparison is read-only and
does not establish corruption or completeness from whole-CASC-file differences.

On 2026-11-06 the user selected a 70707 preload. See docs/CLIENT-70707.ru.md.
Preload metadata is not an activated EXE. The 70707/70755 upstream PR 271
was open, not merged when inspected. Do not apply its whole SQL (it switches
realms to 70755), change launcher profile numbers as a server migration,
or reset the existing 70658 clean installation. Keep client files protected.

On 2026-11-06 the user explicitly requested preparing Multi for a fresh owned
Battle.net installation and confirmed Forever branch 1.60. Multi 1.3 adds
read-only native EXE version inspection and protected connection preparation;
see docs/OFFICIAL-CLIENT.ru.md. Keep CASC/EXE/indices managed by Battle.net.
Protect old settings by default, block mismatched client/server profile builds,
and keep source downloads, official conversion and server protocol support distinct.
Do not redeploy the current clean server just to build this launcher.

On 2026-11-06 the user reported that launcher recovery again preceded an
"installation files are corrupted" error and explicitly requested a plain copy
without our transformations. Follow docs/CLIENT-PRISTINE-COPY.ru.md: use the
entire owned E:\WoW_Forever root, including Data and .build.info, and a new empty
destination. Compare every file by SHA-256 before first launch. Do not apply
our repair/quarantine, metadata restoration, CASC experiments, add-on transfer
or clean-client settings reset to that baseline unless the user explicitly
requests them again. Preserve the running clean server. Exact file copying is
not a claim that the character-screen hang has been fixed. Launcher network
configuration and runtime public-key replacement must be described separately
from changes to client archives; obtain fresh evidence before proposing fixes.

The user requested a clean server reset on 2026-11-05 after confirming that the
actual test Wow.exe FileVersion is 1.60.1.70658. Follow docs/CLEAN-FOREVER-SERVER.ru.md.
The clean setup pins pristine upstream forever b4e7b940593f6402a822d4fbcdf31331d16f73b6,
uses fresh databases/extracted data and realm build 70658, and excludes our gameplay
patches, overrides and advancement injection. The new upstream's 70790 opcode
translations must not be enabled for this confirmed 70658 EXE. The user authorized
removing the old server/databases; clean-forever-server.py purge-old scopes removal to the
old Compose projects only after the new server is ready. Client sources, TLS
identity and add-on source code remain preserved. Never claim cloud tests deployed
the clean server to the user's Windows/WSL machine.

This repository runs a private server for the **World of Warcraft Forever** beta, client build **1.60.1.70450**,
based on the [`forever` branch of TrinityCore](https://github.com/advocaite/TrinityCore/tree/forever). Read
`README.md` first; this file adds what an assistant needs to help someone set it up.
The user intentionally runs **1.60.1.70532** in this fork; see the compatibility
limits in README.md. This is not a claim of full compatibility with that client.
On 2026-11-05 the user requested migration to a newer owned installation at
`E:\WoW_Forever\_forever_`, preferring ForeverLauncher.exe 2.0.5 and allowing
the Beta launcher if client selection is needed. The verified independent test copy is
`E:\WoWForEver-work\experiments\Forever-client-v2\_forever_\Wow.exe`: build
1.60.1.70658, product wowf. The server refresh pins the forever core at
b6ae12c227ef00bfe24fdaf16fba28acc61a5b7f; see docs/SERVER-REFRESH.ru.md. Follow `docs/zones/NEW-CLIENT-MIGRATION.ru.md`; preserve the
old experiment and rebuild CASC changes against the new baseline instead of
copying old indexes/configuration. Do not describe the cloud-prepared migration
tool as a completed Windows deployment or assume the old audited build key.

## Layout

| Path | What it is |
|---|---|
| `Dockerfile`, `docker/` | Builds TrinityCore from the forever branch, applies `docker/patches/*.patch`, writes the configs at start (`docker/entrypoint.sh`). |
| `docker-compose.yml` | mysql, worldserver, bnetserver, web (website), extractor (profile `tools`). `docker-compose.traefik.yml` publishes the website through Traefik. |
| `web/` | Website (FastAPI + Jinja): account sign-up through worldserver SOAP, status, launcher downloads, 4 languages (`web/app/i18n.py`). |
| `app/` | Launcher (Tauri 2: Rust in `app/src-tauri/src`, UI in `app/ui`), 5 languages (`i18n.rs`, `ui/i18n.js`). |
| `scripts/` | `gen-certs.sh` (CA + server certificate), `upload-dokploy.sh`, `pkt-dump.py` (packet log reader). |
| `docs/` | `DOKPLOY.md` (deployment), `MACOS.md` (how the macOS launcher works). |
| `mods/forever-advancement/` | Server adapter and ForeverAscension AddOn using the supplied Ascension Content catalogue. Setup/rollback: `README.ru.md`. The obsolete subclass engine is no longer compiled; its old progress is retained for rollback. |

## Helping someone run their server

1. Linux server with Docker. `cp .env.example .env`: set the three passwords, `PUBLIC_ADDRESS` (public IP or DNS
   name), `WOW_DIR` (the "World of Warcraft" folder of a 1.60.1.70450 client, for the data extraction).
2. `./scripts/gen-certs.sh`, `docker compose build`, `docker compose run --rm extractor`, `docker compose up -d`.
3. Ports: TCP 1119, 8081, 8085 forwarded to the server; 80/443 for the website through Traefik or Dokploy.
4. Dokploy: follow `docs/DOKPLOY.md` (data and certificates go to `/etc/dokploy/compose/<app>/files/`).

## Publishing their launcher (GitHub Actions)

Explain the steps of "Publish the launcher for your server" in `README.md`: fork (and enable Actions in it), repository **variables**
`FOREVER_CA_CERT` (text of `certs/ca/forever_root_ca.crt`) and `FOREVER_SERVER_ADDRESS` (optional
`FOREVER_WEBSITE`, `FOREVER_SERVER_NAME`), then Actions > Launcher > Run workflow with a version. With the GitHub CLI:

```sh
gh variable set FOREVER_CA_CERT < certs/ca/forever_root_ca.crt
gh variable set FOREVER_SERVER_ADDRESS --body "play.example.com"
gh variable set FOREVER_WEBSITE --body "https://play.example.com"
gh workflow run launcher.yml -f version=1.0.0
```

Then `LAUNCHER_REPO=<owner>/<repo>` in the server's `.env` so the website offers the downloads.

## Rules

- **Never** commit, upload or paste `certs/ca/forever_root_ca.key`, `certs/forever.key.pem`, `.env` or passwords.
  `forever_root_ca.crt` is public and is what the launcher needs.
- Do not add Blizzard files: no game client, game data, artwork, logos or download links to the client.
- The upstream documented client is 1.60.1.70450; the user's explicit 70532 experiment is described above. Do not suggest ways to get the beta without access.
- Do not redeploy or restart the worldserver during its first database import (an interrupted import leaves a
  half-filled `world` database).
- If the build stops at "applying /patches/...", the forever branch probably merged that fix: check upstream and
  delete the patch rather than forcing it.
- Keep the 5 launcher languages in sync when changing texts (RU, FR, EN, ES, PT); the website retains its 4 languages; `cargo test --lib` checks the Rust messages.

## Checks

For the content/CASC/subclass tools, run `python3 -m unittest discover -s tests -q`.
The advancement checks exercise catalogue import, replacement/rollback, server resource rules,
and the AddOn against a Lua API double when liblua5.4 is available. They
do not launch the actual game client. Do not claim a deployment to the user's
Windows/WSL machine from cloud-only tests.

```sh
docker compose config -q                                    # compose files
cd app/src-tauri && FOREVER_CA_CERT="$(cat ../../certs/ca/forever_root_ca.crt)" cargo test --lib
```
