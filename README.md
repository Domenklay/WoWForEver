# Forever

A ready-to-run private server for the **World of Warcraft Forever** beta, client build **1.60.1.70450**, with an
account sign-up website and a launcher for Windows, Linux and macOS.

I made it to play the free beta with my friends. It is built on the
[`forever` branch of TrinityCore](https://github.com/advocaite/TrinityCore/tree/forever), packaged with Docker, plus
a few fixes of my own found with packet logs.

![In game](docs/screenshots/game.jpg)

| Launcher | Website |
|---|---|
| ![Launcher](docs/screenshots/launcher.png) | ![Website](docs/screenshots/website.png) |
| ![Launcher login](docs/screenshots/launcher-login.png) | ![Character selection](docs/screenshots/game-characters.jpg) |

## How it works

1. **The server** runs in Docker: MySQL, `worldserver`, `bnetserver` (Battle.net login over TLS) and the website.
2. **Players create their account on the website** (open sign-up, rate limited per IP). The website asks the
   worldserver to create it, exactly like the `bnetaccount create` console command.
3. **Players download the launcher** from the website, which offers the right file for their system. On first use
   the launcher prepares the PC: it adds the server to the hosts file and trusts the server's certificate.
4. **They log in once in the launcher and click Play**. The launcher remembers them for 30 days, logs them into
   the game automatically and puts the server's key in the game client (in memory, the game files are not changed).

The launcher and the website are in English, French, Spanish and Portuguese (Latin America), following the system
or browser language.

**Requirements on the player side**: the game client in exactly build **1.60.1.70450** (World of Warcraft Forever
beta, installed with Battle.net). Another build will not connect.

**No Blizzard assets**: this repository contains no game client, game data, artwork or logo (only screenshots of the
game running on this server). The launcher and the website use neutral visuals drawn in CSS. The game data the
server needs is extracted from your own client.

## Run the server

You need a Linux server with **Docker** and Docker Compose, 8 GB of RAM to build (4 GB to run), about 20 GB of disk,
and the game client (to extract its data).

```sh
git clone <this repository> forever && cd forever
cp .env.example .env               # passwords, PUBLIC_ADDRESS (public IP or DNS name), WOW_DIR
./scripts/gen-certs.sh             # your own CA + server certificate (never share certs/ca/forever_root_ca.key)
docker compose build               # compiles TrinityCore, takes a while
docker compose run --rm extractor  # extracts the game data from your client into ./data
docker compose up -d
docker compose logs -f worldserver # the first start imports the database (a few minutes)
```

### Ports

Forward these ports to the server on your router / firewall (**TCP only**, no UDP needed):

| Port | Service | What for |
|---|---|---|
| 1119 | bnetserver | Battle.net login (TLS) |
| 8081 | bnetserver | login REST API (launcher login, game login ticket) |
| 8085 | worldserver | the game itself, once in the realm |
| 80, 443 | Traefik / Dokploy | the website (HTTP for Let's Encrypt, HTTPS), only if you publish it |

Never expose MySQL (3306) or SOAP (7878): they stay on the internal Docker network.

### The website

It listens on `127.0.0.1:8088`. To publish it on a domain with HTTPS:

- **Traefik**: set `SITE_DOMAIN` in `.env` (and the Traefik network/entrypoint/resolver names if yours differ), then
  ```sh
  docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d
  ```
- **Dokploy** (what I use, it is simpler): Dokploy builds and runs the compose file from your repository and handles
  the domain with its own Traefik. Step by step: [docs/DOKPLOY.md](docs/DOKPLOY.md).

### Accounts from the console

```sh
docker compose attach worldserver   # leave with Ctrl+P, Ctrl+Q
bnetaccount create mail@example.com Password
```

## Build the launcher for your server

The launcher is a [Tauri](https://tauri.app) app in `app/` (Rust + HTML/CSS/JS). It is tied to your server:

1. Copy your CA certificate: `cp certs/ca/forever_root_ca.crt app/src-tauri/resources/` (the public `.crt`, never the
   `.key`). The build stops if it is missing.
2. Set your server in `app/src-tauri/src/config.rs` (`Server::default`): `address` (public IP or DNS name) and
   `website`. Players can also change them in Settings > Server (advanced).
3. Build:
   - **GitHub Actions** (`.github/workflows/launcher.yml`, in your fork with your certificate committed): run it from
     the Actions tab, or push a tag like `v1.0.0` to publish a release with the Windows installer, the Linux
     AppImage and the macOS dmg.
   - **By hand**: `cd app && npx @tauri-apps/cli@2 build` (Linux needs `libwebkit2gtk-4.1-dev`).

To offer the launchers on the website, see the download settings in `.env.example` (direct links, a `downloads`
folder, or your latest GitHub release).

The macOS launcher works differently because of Apple's protections: [docs/MACOS.md](docs/MACOS.md). It is not
signed by Apple, so players run `xattr -cr "/Applications/Forever Launcher.app"` once.

## Good to know

- **Fixes on top of the forever branch**: `docker/patches/` (friend list, party invites and names with surnames,
  360 action bar slots for the gamepad bars), each described in [its README](docker/patches/README.md).
- **Config overrides**: `Key = Value` lines in `overrides/worldserver.conf` or `overrides/bnetserver.conf`.
- **Update**: `docker compose build --no-cache && docker compose up -d`; new SQL updates are applied on start.
  If the branch merges one of the patches, the build stops at that patch: delete it.
- **Newer game client**: set `CLIENT_BUILD` in `.env` to the new build number (experimental until the branch
  supports it).

## License

GNU GPL v2.0 or later, like TrinityCore. See [LICENSE](LICENSE).

Not affiliated with or endorsed by Blizzard Entertainment. World of Warcraft is a trademark of Blizzard
Entertainment, Inc. You need your own access to the game.
