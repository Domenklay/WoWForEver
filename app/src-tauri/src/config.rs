//! Settings (game folder, language, Linux runner...), server definition and the saved login session.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use crate::i18n::{t, tf};

pub const DEFAULT_PORTAL: &str = "trinity.actual.battle.net";

/// Public half of the Ed25519 key built into stock TrinityCore (used by the forever branch too).
pub const STOCK_PUBLIC_KEY: &str = "02596F0D0C061A8B30745988FD72C59E29EC367FB0F341F28E0F08D037BAFC69";
/// Public certificate of the server's private CA (never the key).
pub const CA_PEM: &str = include_str!(concat!(env!("OUT_DIR"), "/forever_root_ca.crt"));

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Server {
    pub name: String,
    /// Host name the client and the certificate use.
    pub portal: String,
    /// Where that host name really is (IP or DNS name of the server).
    pub address: String,
    pub bnet_port: u16,
    pub rest_port: u16,
    pub world_port: u16,
    pub public_key: String,
    pub region_group: u32,
    pub website: String,
    /// Optional public CA file; an embedded CA remains the default.
    pub ca_file: String,
    /// Actual client build configured on the server, not a client conversion.
    pub client_build: u32,
}

/// A build-time setting (FOREVER_SERVER_ADDRESS...), set by GitHub Actions from the repository variables.
fn built_in(value: Option<&'static str>, default: &str) -> String {
    value.filter(|v| !v.trim().is_empty()).unwrap_or(default).trim().to_string()
}

/// Your server, from the FOREVER_SERVER_NAME / FOREVER_SERVER_ADDRESS / FOREVER_WEBSITE variables at build time.
/// Players can still change them in Settings > Server (advanced).
impl Default for Server {
    fn default() -> Self {
        Self {
            name: built_in(option_env!("FOREVER_SERVER_NAME"), "Forever"),
            portal: DEFAULT_PORTAL.into(),
            address: built_in(option_env!("FOREVER_SERVER_ADDRESS"), "127.0.0.1"),
            bnet_port: 1119,
            rest_port: 8081,
            world_port: 8085,
            public_key: STOCK_PUBLIC_KEY.into(),
            region_group: 8,
            website: built_in(option_env!("FOREVER_WEBSITE"), ""),
            ca_file: String::new(),
            client_build: 70658,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct LinuxSettings {
    /// Proton folder (run through umu-run) or "wine".
    pub runner: String,
    pub prefix: String,
    pub gamescope: bool,
    pub gamescope_args: String,
    pub keyboard: String,
}

impl Default for LinuxSettings {
    fn default() -> Self {
        Self {
            runner: String::new(),
            prefix: home().join("Games/forever-wow").to_string_lossy().into_owned(),
            gamescope: false,
            gamescope_args: "-f".into(),
            keyboard: String::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Settings {
    pub server: Server,
    /// The `_classic_beta_` folder (contains WowB.exe, or the game .app on macOS).
    pub game_dir: String,
    /// textLocale / audioLocale, e.g. frFR.
    pub locale: String,
    /// Launcher language: ru, fr, en, es, pt, or empty for the system language.
    pub language: String,
    pub linux: LinuxSettings,
    pub workshop: crate::client::Settings,
    /// Official installations stay under Battle.net's file management.
    pub protect_client_files: bool,
    /// Separate managed CDN installation; never replaces the active/original path.
    pub native_client_dir: String,
    /// Preserve existing project AddOn folders while developing them locally.
    pub addon_development_mode: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self { server: Server::default(), game_dir: String::new(), locale: String::new(),
            language: String::new(), linux: LinuxSettings::default(), workshop: crate::client::Settings::default(),
            protect_client_files: true, native_client_dir: String::new(), addon_development_mode: false }
    }
}

/// Login kept between launches: the 30-day launcher token of the bnetserver, never the password.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Session {
    pub email: String,
    pub token: String,
    pub expires: u64,
}

pub const LOCALES: &[&str] = &["frFR", "enUS", "enGB", "deDE", "esES", "esMX", "itIT", "ptBR", "ruRU", "koKR", "zhCN", "zhTW"];

pub fn home() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("."))
}

pub fn config_dir() -> PathBuf {
    dirs::config_dir().unwrap_or_else(home).join("forever-launcher-app")
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    serde_json::from_slice(&std::fs::read(path).ok()?).ok()
}

fn write_private(path: &Path, data: &[u8]) -> std::io::Result<()> {
    std::fs::create_dir_all(path.parent().unwrap())?;
    let tmp = path.with_extension("tmp");
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        use std::io::Write;
        let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp)?;
        f.write_all(data)?;
    }
    #[cfg(not(unix))]
    std::fs::write(&tmp, data)?;
    std::fs::rename(tmp, path)
}

impl Settings {
    pub fn load() -> Self {
        let mut s: Settings = read_json(&config_dir().join("settings.json")).unwrap_or_default();
        if s.game_dir.is_empty() {
            s.game_dir = detect_game_dir().unwrap_or_default();
        }
        s.game_dir = normalize_game_dir(Path::new(&s.game_dir)).to_string_lossy().into_owned();
        s.server.normalize_legacy_portal();
        if s.locale.is_empty() {
            s.locale = installed_locale(Path::new(&s.game_dir)).unwrap_or_else(|| "enUS".into());
        }
        #[cfg(target_os = "linux")]
        {
            if s.linux.runner.is_empty() {
                s.linux.runner = crate::system::default_runner();
            }
            if s.linux.keyboard.is_empty() {
                s.linux.keyboard = crate::system::keyboard_layout();
            }
        }
        s
    }

    pub fn save(&self) -> std::io::Result<()> {
        write_private(&config_dir().join("settings.json"), &serde_json::to_vec_pretty(self).unwrap())
    }

    /// Wow.exe for wowf, WowB.exe for beta, or the game .app on macOS.
    pub fn exe(&self) -> PathBuf {
        game_binary(Path::new(&self.game_dir))
    }

    pub fn game_found(&self) -> bool {
        if self.game_dir.is_empty() || !self.exe().exists() { return false; }
        let game = normalize_game_dir(Path::new(&self.game_dir));
        let has_info = game.join(".build.info").is_file() || game.parent().is_some_and(|p| p.join(".build.info").is_file());
        !has_info || build_row(&game).is_some()
    }

    /// The wowf launch-options registry contract is not yet verified. Match the successful manual-login probe.
    pub fn automatic_game_login(&self) -> bool {
        cfg!(target_os = "macos") || self.exe().file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("WowB.exe"))
    }
}

#[cfg(all(test, not(target_os = "macos")))]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("forever-multi-client-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
        fn game(&self, name: &str, exe: &str) -> PathBuf {
            let path = self.0.join(name); std::fs::create_dir_all(&path).unwrap();
            std::fs::write(path.join(exe), b"test fixture").unwrap(); path
        }
        fn info(&self, rows: &str) {
            std::fs::write(self.0.join(".build.info"), format!("\u{feff}Product!STRING:0|Active!DEC:1|Version!STRING:0|Tags!STRING:0\n{rows}")).unwrap();
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }

    #[test]
    fn wowf_root_folder_and_exe_resolve_to_the_same_client() {
        let f = Fixture::new(); let game = f.game("_forever_", "Wow.exe");
        f.info("wowf|0|1.60.1.1|enUS text\nwow_classic_beta|1|1.60.1.70532|enUS text\nwowf|1|1.60.1.70658|ruRU text\n");
        for selected in [&f.0, &game, &game.join("Wow.exe")] {
            assert_eq!(normalize_game_dir(selected), game);
            assert_eq!(installed_version(selected).as_deref(), Some("1.60.1.70658"));
            assert_eq!(installed_locale(selected).as_deref(), Some("ruRU"));
        }
        let settings = Settings { game_dir: game.to_string_lossy().into_owned(), ..Default::default() };
        assert!(settings.game_found());
        assert!(!settings.automatic_game_login());
        #[cfg(not(target_os = "macos"))]
        assert_eq!(settings.exe(), game.join("Wow.exe"));
    }

    #[test]
    fn beta_metadata_and_autologin_remain_supported() {
        let f = Fixture::new(); let game = f.game("_classic_beta_", "WowB.exe");
        f.info("wowf|1|1.60.1.70658|ruRU text\nwow_classic_beta|1|1.60.1.70532|frFR text\n");
        assert_eq!(installed_version(&game).as_deref(), Some("1.60.1.70532"));
        assert_eq!(installed_locale(&game).as_deref(), Some("frFR"));
        let settings = Settings { game_dir: game.to_string_lossy().into_owned(), ..Default::default() };
        assert!(settings.game_found());
        assert!(settings.automatic_game_login());
    }

    #[test]
    fn retail_or_ambiguous_metadata_does_not_become_a_forever_client() {
        let f = Fixture::new(); let game = f.game("_forever_", "Wow.exe");
        let settings = Settings { game_dir: game.to_string_lossy().into_owned(), ..Default::default() };
        f.info("wow|1|12.1.0.1|enUS text\n");
        assert!(!settings.game_found());
        f.info("wowf|1|1.60.1.70658|ruRU text\nwowf|1|1.60.1.70659|ruRU text\n");
        assert_eq!(installed_version(&game), None);
        assert!(!settings.game_found());
    }

    #[test]
    fn old_settings_keep_address_ports_and_recover_a_hostname_portal() {
        let mut settings: Settings = serde_json::from_str(r#"{"server":{"portal":"127.0.0.1:1119","address":"old","name":"WoWForEver"},"language":"en"}"#).unwrap();
        settings.server.normalize_legacy_portal();
        assert_eq!(settings.server.portal, DEFAULT_PORTAL);
        assert_eq!(settings.server.address, "127.0.0.1");
        assert_eq!(settings.server.name, "WoWForEver");
        assert_eq!(settings.server.bnet_port, 1119);
        assert!(!settings.addon_development_mode);
        assert!(settings.server.ca_file.is_empty());
        settings.server.portal = "trinity.actual.battle.net:1129".into();
        settings.server.normalize_legacy_portal();
        assert_eq!(settings.server.bnet_port, 1129);
        assert_eq!(settings.server.portal, DEFAULT_PORTAL);
    }

    #[test]
    fn addon_development_is_opt_in_and_survives_settings_roundtrip() {
        let original: Settings = serde_json::from_str(r#"{"gameDir":"E:/client/_forever_","server":{"address":"127.0.0.1"}}"#).unwrap();
        assert!(!original.addon_development_mode);
        let mut enabled = original.clone();
        enabled.addon_development_mode = true;
        let saved = serde_json::to_string(&enabled).unwrap();
        assert!(saved.contains("\"addonDevelopmentMode\":true"));
        let loaded: Settings = serde_json::from_str(&saved).unwrap();
        assert!(loaded.addon_development_mode);
        assert_eq!(loaded.game_dir, original.game_dir);
        assert_eq!(loaded.server.address, original.server.address);
        assert_eq!(loaded.server.public_key, original.server.public_key);
        assert_eq!(loaded.protect_client_files, original.protect_client_files);
    }

    #[test]
    fn portal_validation_rejects_ips_ports_and_invalid_dns_labels() {
        for portal in ["127.0.0.1", "::1", "trinity.actual.battle.net:1119", "https://host", "-bad.host", "host..name", ""] {
            assert!(!valid_portal(portal), "{portal}");
        }
        assert!(valid_portal(DEFAULT_PORTAL));
    }

    #[test]
    fn a_private_key_is_never_accepted_as_a_public_ca_file() {
        let f = Fixture::new(); let path = f.0.join("not-a-ca.pem");
        std::fs::write(&path, "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----").unwrap();
        let server = Server { ca_file: path.to_string_lossy().into_owned(), ..Default::default() };
        assert!(server_ca_pem(&server).is_err());
    }

    #[test]
    fn selected_public_ca_overrides_the_embedded_certificate() {
        let f = Fixture::new(); let path = f.0.join("public-ca.pem");
        let pem = include_str!("../testdata/public-ca.pem");
        std::fs::write(&path, pem).unwrap();
        let server = Server { ca_file: path.to_string_lossy().into_owned(), ..Default::default() };
        assert_eq!(server_ca_pem(&server).unwrap(), pem);
        assert!(server.validate().is_ok());
    }
}

impl Server {
    fn normalize_legacy_portal(&mut self) {
        self.portal = self.portal.trim().to_string();
        if let Ok(socket) = self.portal.parse::<std::net::SocketAddr>() {
            self.address = socket.ip().to_string();
            self.bnet_port = socket.port();
            self.portal = DEFAULT_PORTAL.into();
        } else if self.portal.parse::<std::net::IpAddr>().is_ok() {
            self.address = self.portal.clone();
            self.portal = DEFAULT_PORTAL.into();
        } else if let Some((host, port)) = self.portal.rsplit_once(':') {
            if valid_portal(host) {
                if let Ok(port) = port.parse::<u16>() {
                    if port != 0 { self.bnet_port = port; self.portal = host.into(); }
                }
            }
        }
        if self.portal.is_empty() { self.portal = DEFAULT_PORTAL.into(); }
    }

    pub fn validate(&self) -> Result<(), String> {
        if !valid_portal(&self.portal) { return Err(t("bad_portal").into()); }
        if self.address.trim().is_empty() || self.address.contains([';', '/', '\\', '"', '\'']) ||
            self.bnet_port == 0 || self.rest_port == 0 || self.world_port == 0 || self.client_build == 0 {
            return Err(t("bad_server_address").into());
        }
        if !self.ca_file.is_empty() { server_ca_pem(self)?; }
        Ok(())
    }
}

pub fn valid_portal(portal: &str) -> bool {
    !portal.is_empty() && portal.len() < 254 && portal.parse::<std::net::IpAddr>().is_err() &&
        portal.split('.').all(|label| !label.is_empty() && label.len() <= 63 &&
            !label.starts_with('-') && !label.ends_with('-') &&
            label.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'))
}

/// Only public certificates are accepted. The CA/private server keys never belong in the launcher.
pub fn server_ca_pem(server: &Server) -> Result<String, String> {
    let pem = if !server.ca_file.is_empty() {
        std::fs::read_to_string(&server.ca_file).map_err(|e| tf("ca_read", &[&e]))?
    } else if !CA_PEM.trim().is_empty() {
        CA_PEM.to_string()
    } else {
        let path = std::env::current_exe().ok().and_then(|p| p.parent().map(|p| p.join("forever_root_ca.crt")));
        path.and_then(|p| std::fs::read_to_string(p).ok()).ok_or_else(|| t("ca_missing").to_string())?
    };
    if pem.contains("PRIVATE KEY") || !pem.contains("-----BEGIN CERTIFICATE-----") ||
        reqwest::Certificate::from_pem(pem.as_bytes()).is_err() {
        return Err(t("ca_invalid").into());
    }
    Ok(pem)
}

impl Session {
    pub fn load() -> Option<Self> {
        read_json::<Session>(&config_dir().join("session.json")).filter(|s| !s.token.is_empty())
    }

    pub fn save(&self) -> std::io::Result<()> {
        write_private(&config_dir().join("session.json"), &serde_json::to_vec(self).unwrap())
    }

    pub fn clear() {
        let _ = std::fs::remove_file(config_dir().join("session.json"));
    }
}

/// Language the client was installed with, from the Tags column of .build.info next to the game folder.
pub fn installed_locale(game_dir: &Path) -> Option<String> {
    let (header, row) = build_row(game_dir)?;
    let tags = row.get(header.iter().position(|c| c == "Tags")?)?;
    LOCALES.iter().find(|l| tags.contains(&format!("{l} text"))).map(|l| l.to_string())
}

/// Full client version (e.g. 1.60.1.70450), from the Version column of .build.info next to the game folder.
pub fn installed_version(game_dir: &Path) -> Option<String> {
    let (header, row) = build_row(game_dir)?;
    row.get(header.iter().position(|c| c == "Version")?).filter(|v| !v.is_empty()).cloned()
}

pub fn installed_product(game_dir: &Path) -> Option<String> {
    let (header, row) = build_row(game_dir)?;
    row.get(header.iter().position(|c| c == "Product")?).cloned()
}

fn build_row(game_dir: &Path) -> Option<(Vec<String>, Vec<String>)> {
    let game_dir = normalize_game_dir(game_dir);
    let info_path = if game_dir.join(".build.info").is_file() { game_dir.join(".build.info") }
                    else { game_dir.parent()?.join(".build.info") };
    let info = std::fs::read_to_string(info_path).ok()?;
    let mut lines = info.trim_start_matches('\u{feff}').lines();
    let header: Vec<String> = lines.next()?.split('|').map(|c| c.split('!').next().unwrap_or("").into()).collect();
    let product = header.iter().position(|c| c == "Product")?;
    let active = header.iter().position(|c| c == "Active")?;
    let expected = if game_dir.file_name().is_some_and(|n| n == "_classic_beta_") ||
        (!game_dir.join("Wow.exe").is_file() && game_dir.join("WowB.exe").is_file()) {
        "wow_classic_beta"
    } else { "wowf" };
    let mut rows = lines.map(|l| l.split('|').map(str::to_string).collect::<Vec<_>>())
        .filter(|row| row.len() == header.len() && row[product] == expected && row[active] == "1");
    let row = rows.next()?;
    if rows.next().is_some() { return None; }
    Some((header, row))
}

/// Accept the installation root, selected game directory, or a pasted supported EXE path.
pub fn normalize_game_dir(path: &Path) -> PathBuf {
    if path.as_os_str().is_empty() { return path.to_path_buf(); }
    if path.file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("Wow.exe") ||
        n.to_string_lossy().eq_ignore_ascii_case("WowB.exe")) && path.is_file() {
        return path.parent().unwrap_or(path).to_path_buf();
    }
    if path.join("Wow.exe").is_file() || path.join("WowB.exe").is_file() { return path.to_path_buf(); }
    for name in ["_forever_", "_classic_beta_", "_classic_era_", "_classic_", "_retail_"] {
        let game = path.join(name);
        if game.join("Wow.exe").is_file() || game.join("WowB.exe").is_file() { return game; }
        #[cfg(target_os = "macos")]
        if game.is_dir() && game_binary(&game).exists() { return game; }
    }
    path.to_path_buf()
}

#[cfg(not(target_os = "macos"))]
fn game_binary(dir: &Path) -> PathBuf {
    let dir = normalize_game_dir(dir);
    let names = if dir.file_name().is_some_and(|n| n == "_classic_beta_") { ["WowB.exe", "Wow.exe"] }
                else { ["Wow.exe", "WowB.exe"] };
    names.iter().map(|n| dir.join(n)).find(|p| p.is_file()).unwrap_or_else(|| dir.join(names[0]))
}

/// Re-signed copy of the game app that the launcher starts on macOS (see macos.rs), next to the original.
#[cfg(target_os = "macos")]
pub const MAC_COPY_NAME: &str = "World of Warcraft Forever.app";

/// The first .app in the folder (the Classic beta app name is not fixed), other than the launcher's copy.
#[cfg(target_os = "macos")]
fn game_binary(dir: &Path) -> PathBuf {
    std::fs::read_dir(dir)
        .ok()
        .and_then(|d| {
            let mut apps: Vec<PathBuf> = d
                .flatten()
                .filter(|e| {
                    let name = e.file_name().to_string_lossy().into_owned();
                    !name.starts_with('.') && name != MAC_COPY_NAME
                })
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x == "app"))
                .collect();
            apps.sort();
            apps.into_iter().next()
        })
        .unwrap_or_else(|| dir.join("World of Warcraft.app"))
}

fn detect_game_dir() -> Option<String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    #[cfg(windows)]
    for game in [r"E:\WoWForEver-work\experiments\Forever-client-v4\_forever_",
                 r"E:\WoWForEver-work\experiments\Forever-client-v3\_forever_",
                 r"E:\WoWForEver-work\experiments\Forever-client-v2\_forever_",
                 r"E:\WoW_Forever\_forever_"] {
        candidates.push(game.into());
    }
    #[cfg(windows)]
    for root in ["C:\\Program Files (x86)", "C:\\Program Files", "D:\\", "D:\\Games", "E:\\", "E:\\Games"] {
        for game in ["_forever_", "_classic_beta_"] { candidates.push(Path::new(root).join("World of Warcraft").join(game)); }
    }
    #[cfg(target_os = "macos")]
    for root in ["/Applications/World of Warcraft", &home().join("Applications/World of Warcraft").to_string_lossy()] {
        candidates.push(Path::new(root).join("_classic_beta_"));
    }
    #[cfg(target_os = "linux")]
    {
        // a Lutris entry that already points at WowB.exe
        if let Ok(dir) = std::fs::read_dir(home().join(".local/share/lutris/games")) {
            for entry in dir.flatten() {
                if let Ok(text) = std::fs::read_to_string(entry.path()) {
                    for line in text.lines() {
                        if let Some(exe) = line.trim().strip_prefix("exe:") {
                            let exe = exe.trim().trim_matches(|c| c == '\'' || c == '"');
                            if ["wow.exe", "wowb.exe"].iter().any(|n| exe.to_ascii_lowercase().ends_with(n)) {
                                if let Some(parent) = Path::new(exe).parent() {
                                    candidates.push(parent.to_path_buf());
                                }
                            }
                        }
                    }
                }
            }
        }
        for p in ["Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_forever_",
                  "Games/World of Warcraft/_forever_",
                  "Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_classic_beta_",
                  "Games/World of Warcraft/_classic_beta_"] {
            candidates.push(home().join(p));
        }
    }
    candidates.into_iter().find(|p| game_binary(p).exists()).map(|p| p.to_string_lossy().into_owned())
}
