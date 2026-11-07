//! Game preparation and start: wowf Wow.exe and the legacy beta WowB.exe.
//! macOS starts a copy of the game app instead: see macos.rs.

use crate::config::Settings;
use crate::i18n::tf;
use std::path::Path;
#[cfg(not(target_os = "macos"))]
use std::process::{Child, Command};

pub const WTF_NAME: &str = "ForeverLauncher.wtf";
#[cfg(not(target_os = "macos"))]
const LEGACY_LAUNCH_OPTIONS: &str = r"Software\Blizzard Entertainment\Battle.net\Launch Options\WoW";

#[cfg(not(target_os = "macos"))]
const FOREVER_LAUNCH_OPTIONS:&str=r"Software\Custom Game Server Dev\Battle.net\Launch Options\WoW";

/// Read the selected executable, never credentials or process memory. New clients
/// can use the upstream custom vendor registry key; beta clients use the legacy one.
#[cfg(not(target_os = "macos"))]
fn launch_options_key(exe:&Path)->Result<&'static str,String>{
    use std::io::Read;
    let mut file=std::fs::File::open(exe).map_err(|e|e.to_string())?;
    let ascii=b"custom game server dev";
    let wide:Vec<u8>="custom game server dev".encode_utf16().flat_map(u16::to_le_bytes).collect();
    let mut tail=Vec::new();let mut block=vec![0u8;1024*1024];
    loop {let count=file.read(&mut block).map_err(|e|e.to_string())?;if count==0{break;}
        tail.extend(block[..count].iter().map(u8::to_ascii_lowercase));
        if memchr::memmem::find(&tail,ascii).is_some()||memchr::memmem::find(&tail,&wide).is_some(){return Ok(FOREVER_LAUNCH_OPTIONS);}
        if tail.len()>128{tail.drain(..tail.len()-128);}
    }
    Ok(LEGACY_LAUNCH_OPTIONS)
}

/// WTF/ForeverLauncher.wtf: a copy of Config.wtf with the portal and the language set.
pub fn write_wtf(settings: &Settings) -> Result<(), String> {
    let dir = Path::new(&settings.game_dir).join("WTF");
    std::fs::create_dir_all(&dir).map_err(|e| tf("wtf_folder", &[&e]))?;
    let path = dir.join(WTF_NAME);
    let base = dir.join("Config.wtf");
    let text = std::fs::read_to_string(&path).or_else(|_| std::fs::read_to_string(&base)).unwrap_or_default();
    let wanted = [
        ("portal", format!("{}:{}", settings.server.portal, settings.server.bnet_port)),
        ("textLocale", settings.locale.clone()),
        ("audioLocale", settings.locale.clone()),
    ];
    let mut lines: Vec<String> = text
        .lines()
        .filter(|l| !wanted.iter().any(|(k, _)| {
            let mut words = l.split_whitespace();
            words.next().is_some_and(|w| w.eq_ignore_ascii_case("SET")) &&
                words.next().is_some_and(|w| w.eq_ignore_ascii_case(k))
        }))
        .map(str::to_string)
        .collect();
    for (k, v) in wanted {
        lines.push(format!("SET {k} \"{v}\""));
    }
    std::fs::write(&path, lines.join("\r\n") + "\r\n").map_err(|e| format!("{} : {e}", path.display()))
}

fn launch_args(settings: &Settings) -> Vec<&'static str> {
    let mut args = Vec::new();
    if settings.automatic_game_login() { args.push("-launcherlogin"); }
    args.extend(["-config", WTF_NAME]);
    args
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preparing_connection_preserves_exe_casc_and_original_settings() {
        let root = std::env::temp_dir().join(format!("multi-official-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let game = root.join("_forever_");
        std::fs::create_dir_all(game.join("WTF")).unwrap();
        std::fs::create_dir_all(root.join("Data/data")).unwrap();
        let originals = [
            (game.join("Wow.exe"), b"owned synthetic EXE fixture".to_vec()),
            (root.join(".build.info"), b"owned metadata fixture".to_vec()),
            (root.join("Data/data/shmem"), b"owned local-state fixture".to_vec()),
            (root.join("Data/data/0000000001.idx"), b"owned index fixture".to_vec()),
            (root.join("Data/data/data.000"), b"owned archive fixture".to_vec()),
            (game.join("WTF/Config.wtf"), b"SET portal \"EU\"\nSET gxApi \"D3D12\"\n".to_vec()),
        ];
        for (path, bytes) in &originals { std::fs::write(path, bytes).unwrap(); }
        let settings = Settings { game_dir: game.to_string_lossy().into_owned(), locale: "ruRU".into(), ..Default::default() };
        write_wtf(&settings).unwrap();
        for (path, bytes) in &originals { assert_eq!(std::fs::read(path).unwrap(), *bytes); }
        assert!(std::fs::read_to_string(game.join("WTF").join(WTF_NAME)).unwrap().contains("trinity.actual.battle.net:1119"));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    #[cfg(not(target_os = "macos"))]
    fn wowf_uses_ticket_login_with_an_explicit_config_and_can_opt_out() {
        let settings = Settings { game_dir: "missing-client/_forever_".into(), ..Default::default() };
        assert_eq!(launch_args(&settings), vec!["-launcherlogin", "-config", WTF_NAME]);
        let manual = Settings { auto_game_login:false, ..settings };
        assert_eq!(launch_args(&manual), vec!["-config", WTF_NAME]);
    }

    #[test]
    fn launch_config_uses_hostname_and_port_and_keeps_original_settings() {
        let dir = std::env::temp_dir().join(format!("multi-launch-config-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        std::fs::create_dir_all(dir.join("WTF")).unwrap();
        let original = "SET portal \"127.0.0.1:1119\"\n  SET Portal \"EU.actual.battle.net\"\nSET gxApi \"D3D11\"\n";
        let base = dir.join("WTF/Config.wtf");
        std::fs::write(&base, original).unwrap();
        let mut settings = Settings { game_dir: dir.to_string_lossy().into_owned(), locale: "ruRU".into(), ..Default::default() };
        settings.server.portal = "trinity.actual.battle.net".into();
        settings.server.bnet_port = 1129;
        write_wtf(&settings).unwrap();
        let launch = std::fs::read_to_string(dir.join("WTF").join(WTF_NAME)).unwrap();
        assert_eq!(launch.matches("SET portal ").count(), 1);
        assert!(launch.contains("SET portal \"trinity.actual.battle.net:1129\""));
        assert!(launch.contains("SET gxApi \"D3D11\""));
        assert!(launch.contains("SET textLocale \"ruRU\""));
        assert!(!launch.contains("EU.actual.battle.net"));
        assert_eq!(std::fs::read_to_string(&base).unwrap(), original);
        std::fs::remove_dir_all(dir).unwrap();
    }
}

/// Stores the login ticket where the client reads it with -launcherlogin.
#[cfg(windows)]
pub fn write_launch_options(settings: &Settings, portal: &str, ticket: &str, game_account: &str) -> Result<(), String> {
    use windows::core::HSTRING;
    use windows::Win32::System::Registry::*;
    let key_path=launch_options_key(&settings.exe())?;
    let blob = crate::dpapi::protect(ticket.as_bytes())?;
    unsafe {
        let mut key = HKEY::default();
        RegCreateKeyExW(HKEY_CURRENT_USER, &HSTRING::from(key_path), 0, None, REG_OPTION_NON_VOLATILE, KEY_WRITE, None, &mut key, None)
            .ok()
            .map_err(|e| tf("registry", &[&e]))?;
        let set_str = |name: &str, value: &str| {
            let wide: Vec<u16> = value.encode_utf16().chain(std::iter::once(0)).collect();
            let bytes = std::slice::from_raw_parts(wide.as_ptr() as *const u8, wide.len() * 2);
            RegSetValueExW(key, &HSTRING::from(name), 0, REG_SZ, Some(bytes)).ok()
        };
        let r = set_str("CONNECTION_STRING", portal)
            .and_then(|_| set_str("GAME_ACCOUNT", game_account))
            .and_then(|_| RegSetValueExW(key, &HSTRING::from("WEB_TOKEN"), 0, REG_BINARY, Some(&blob)).ok());
        let _ = RegCloseKey(key);
        r.map_err(|e| tf("registry", &[&e]))
    }
}

/// Linux: the same values in the prefix registry, through `reg import` (the Wine DPAPI blob is built here).
#[cfg(target_os = "linux")]
pub fn write_launch_options(settings: &Settings, portal: &str, ticket: &str, game_account: &str) -> Result<(), String> {
    use crate::dpapi::{wine, WEB_TOKEN_ENTROPY};
    let launch_options=launch_options_key(&settings.exe())?;
    let blob = wine::protect(ticket.as_bytes(), wine::PROTON_USER, &WEB_TOKEN_ENTROPY);
    let hexdata: Vec<String> = blob.iter().map(|b| format!("{b:02x}")).collect();
    let content = format!(
        "Windows Registry Editor Version 5.00\r\n\r\n[HKEY_CURRENT_USER\\{launch_options}]\r\n\"WEB_TOKEN\"=hex:{}\r\n\"GAME_ACCOUNT\"=\"{game_account}\"\r\n\"CONNECTION_STRING\"=\"{portal}\"\r\n",
        hexdata.join(",")
    );
    // regedit files are UTF-16 LE with a BOM; Wine sees the Linux file system as Z:
    let mut bytes = vec![0xFF, 0xFE];
    for u in content.encode_utf16() {
        bytes.extend(u.to_le_bytes());
    }
    let dir = crate::config::config_dir();
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let file = dir.join("launch-options.reg");
    std::fs::write(&file, bytes).map_err(|e| e.to_string())?;
    let wine_path = format!("Z:{}", file.to_string_lossy().replace('/', "\\"));
    let res = crate::system::run_in_prefix(settings, &["reg", "import", &wine_path]);
    let _ = std::fs::remove_file(&file);
    res
}

#[cfg(windows)]
pub fn spawn(settings: &Settings) -> Result<Child, String> {
    Command::new(settings.exe())
        .args(launch_args(settings))
        .current_dir(&settings.game_dir)
        .spawn()
        .map_err(|e| tf("launch_failed", &[&settings.exe().display(), &e]))
}

#[cfg(target_os = "linux")]
pub fn spawn(settings: &Settings) -> Result<Child, String> {
    let (runner, mut env) = crate::system::runner(settings)?;
    let mut cmd: Vec<String> = runner;
    cmd.push(settings.exe().to_string_lossy().into_owned());
    cmd.extend(launch_args(settings).into_iter().map(String::from));
    let l = &settings.linux;
    if l.gamescope && crate::system::which("gamescope") {
        // gamescope starts its own Xwayland with a US keyboard unless told otherwise
        let (layout, variant) = l.keyboard.split_once('+').unwrap_or((l.keyboard.as_str(), ""));
        if !layout.is_empty() {
            env.push(("XKB_DEFAULT_LAYOUT".into(), layout.into()));
        }
        if !variant.is_empty() {
            env.push(("XKB_DEFAULT_VARIANT".into(), variant.into()));
        }
        let mut wrapped = vec!["gamescope".to_string()];
        wrapped.extend(l.gamescope_args.split_whitespace().map(String::from));
        wrapped.push("--".into());
        wrapped.extend(cmd);
        cmd = wrapped;
    }
    crate::system::clean_env(&mut Command::new(&cmd[0]))
        .args(&cmd[1..])
        .envs(env)
        .current_dir(&settings.game_dir)
        .spawn()
        .map_err(|e| tf("launch_failed", &[&cmd[0], &e]))
}

#[cfg(all(test,not(target_os="macos")))]mod registry_key_tests {
 use super::*;
 #[test]fn registry_vendor_is_selected_from_the_actual_client_including_a_chunk_boundary(){
  let root=std::env::temp_dir().join(format!("forever-login-vendor-{:032x}",rand::random::<u128>()));std::fs::create_dir(&root).unwrap();let exe=root.join("Wow.exe");
  std::fs::write(&exe,b"legacy client fixture").unwrap();assert_eq!(launch_options_key(&exe).unwrap(),LEGACY_LAUNCH_OPTIONS);
  let mut bytes=vec![b'x';1024*1024-10];bytes.extend("Software\\Custom Game Server Dev\\Battle.net\\Launch Options\\WoW".encode_utf16().flat_map(u16::to_le_bytes));std::fs::write(&exe,bytes).unwrap();assert_eq!(launch_options_key(&exe).unwrap(),FOREVER_LAUNCH_OPTIONS);
  std::fs::remove_dir_all(root).unwrap();
 }
}
