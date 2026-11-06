//! Read-only inspection and connection policy for a Battle.net installation.
//! Never repairs, renames, converts, downloads or writes game payloads.

use crate::{config, i18n::{t, tf}};
use serde::Serialize;
use std::path::Path;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Inspection {
    pub game_dir: String,
    pub executable: String,
    pub product: Option<String>,
    pub version: Option<String>,
    pub metadata_version: Option<String>,
    pub server_build: u32,
    pub ready: bool,
    pub status: &'static str,
    pub message: String,
}

pub fn numeric_version(text: &str) -> Option<[u32; 4]> {
    let start = text.find(|c: char| c.is_ascii_digit())?;
    let prefix: String = text[start..].chars().take_while(|c| c.is_ascii_digit() || matches!(c, '.' | ',' | ' ' | '\t')).collect();
    let values: Vec<u32> = prefix.split(|c: char| !c.is_ascii_digit()).filter(|s| !s.is_empty())
        .map(str::parse).collect::<Result<_, _>>().ok()?;
    values.try_into().ok()
}

pub fn classify(product: Option<&str>, version: Option<&str>, storage: bool, expected: u32) -> &'static str {
    let Some(v) = version.and_then(numeric_version) else { return "official_unknown_version" };
    if v[..3] != [1, 60, 1] || !matches!(product, Some("wowf" | "wow_classic_beta")) {
        return "official_unsupported";
    }
    if !storage { return "official_missing_storage"; }
    if v[3] != expected { return "official_mismatch"; }
    "official_ready"
}

fn managed_ready(root:&Path,expected:u32)->bool {
    let path=root.join(".forever-multi-managed.json");
    if !path.exists() && !path.is_symlink(){return true;}
    if path.is_symlink(){return false;}
    std::fs::read(path).ok().and_then(|bytes|serde_json::from_slice::<serde_json::Value>(&bytes).ok())
        .is_some_and(|v|v["format"]=="forever-multi-cdn-v1" && v["complete"]==true && v["build"].as_u64()==Some(expected as u64))
}

pub fn inspect(selected: &Path, server_build: u32) -> Inspection {
    let game = config::normalize_game_dir(selected);
    let settings = config::Settings { game_dir: game.to_string_lossy().into_owned(), ..Default::default() };
    let executable = settings.exe();
    let version = executable_version(&executable);
    let product = config::installed_product(&game);
    let root = if game.join(".build.info").is_file() { game.clone() }
        else { game.parent().unwrap_or(&game).to_path_buf() };
    let mut status = if !executable.is_file() { "official_no_exe" }
        else { classify(product.as_deref(), version.as_deref(), root.join("Data/data").is_dir(), server_build) };
    if status=="official_ready" && !managed_ready(&root,server_build){status="official_managed_incomplete";}
    let message = if status == "official_mismatch" {
        tf(status, &[&version.as_deref().unwrap_or("?"), &server_build])
    } else { t(status).to_string() };
    Inspection { game_dir: game.to_string_lossy().into_owned(), executable: executable.to_string_lossy().into_owned(),
        metadata_version: config::installed_version(&game), product, version,
        server_build, ready: status == "official_ready", status, message }
}

pub fn require_ready(report: &Inspection) -> Result<(), String> {
    if report.ready { Ok(()) } else { Err(report.message.clone()) }
}

pub fn allow_file_operation(protected: bool, action: &str) -> Result<(), String> {
    if protected && action != "verify" { Err(t("official_protected").into()) } else { Ok(()) }
}

// FileVersion strings retain build numbers above 65535; the four 16-bit fields
// of VS_FIXEDFILEINFO alone would truncate WoW build 70658.
#[cfg(windows)]
pub fn executable_version(path: &Path) -> Option<String> {
    use std::{ffi::c_void, os::windows::ffi::OsStrExt};
    use windows::{core::PCWSTR, Win32::Storage::FileSystem::{
        GetFileVersionInfoSizeW, GetFileVersionInfoW, VerQueryValueW}};
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    unsafe {
        let size = GetFileVersionInfoSizeW(PCWSTR(name.as_ptr()), None);
        if size == 0 || size > 4 * 1024 * 1024 { return None; }
        let mut data = vec![0u8; size as usize];
        GetFileVersionInfoW(PCWSTR(name.as_ptr()), 0, size, data.as_mut_ptr().cast()).ok()?;
        let query = |key: &str| -> Option<(*mut c_void, u32)> {
            let key: Vec<u16> = key.encode_utf16().chain(Some(0)).collect();
            let mut pointer = std::ptr::null_mut(); let mut length = 0;
            if VerQueryValueW(data.as_ptr().cast(), PCWSTR(key.as_ptr()), &mut pointer, &mut length).as_bool()
                && !pointer.is_null() && length != 0 { Some((pointer, length)) } else { None }
        };
        let mut languages = Vec::new();
        if let Some((pointer, bytes)) = query("\\VarFileInfo\\Translation") {
            let start = pointer as usize; let begin = data.as_ptr() as usize;
            if bytes <= size && bytes % 4 == 0 && start >= begin
                && start.checked_add(bytes as usize).is_some_and(|end| end <= begin + data.len()) {
                for pair in std::slice::from_raw_parts(pointer.cast::<u16>(), bytes as usize / 2).chunks_exact(2) {
                    languages.push(format!("{:04x}{:04x}", pair[0], pair[1]));
                }
            }
        }
        languages.extend(["040904b0".into(), "040904e4".into()]);
        for field in ["FileVersion", "ProductVersion"] {
            for language in &languages {
                if let Some((pointer, chars)) = query(&format!("\\StringFileInfo\\{language}\\{field}")) {
                    let lo = pointer as usize; let begin = data.as_ptr() as usize;
                    let end = lo.checked_add((chars as usize).checked_mul(2)?)?;
                    if lo < begin || end > begin + data.len() { continue; }
                    let text = String::from_utf16_lossy(std::slice::from_raw_parts(pointer.cast::<u16>(), chars as usize));
                    let text = text.trim_end_matches('\0').trim();
                    if numeric_version(text).is_some() { return Some(text.to_string()); }
                }
            }
        }
    }
    None
}

#[cfg(not(windows))]
pub fn executable_version(_path: &Path) -> Option<String> { None }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interrupted_managed_downloads_cannot_be_connected_as_complete_clients(){
        let parent=std::env::temp_dir().join(format!("multi-managed-ready-{}-{}",std::process::id(),std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        std::fs::create_dir_all(&parent).unwrap();
        assert!(managed_ready(&parent,70658));
        let path=parent.join(".forever-multi-managed.json");
        for (build,complete,ready) in [(70658,false,false),(70707,true,false),(70658,true,true)]{
            std::fs::write(&path,serde_json::to_vec(&serde_json::json!({"format":"forever-multi-cdn-v1","build":build,"complete":complete})).unwrap()).unwrap();
            assert_eq!(managed_ready(&parent,70658),ready);
        }
        std::fs::write(&path,b"interrupted marker").unwrap();assert!(!managed_ready(&parent,70658));
        std::fs::remove_dir_all(parent).unwrap();
    }
    #[test]
    fn actual_exe_build_not_metadata_selects_compatibility() {
        assert_eq!(numeric_version("Version 1.60.1.70658"), Some([1,60,1,70658]));
        assert_eq!(numeric_version("10.0.26100.8410 (WinBuild.160101.0800)"), Some([10,0,26100,8410]));
        assert_eq!(classify(Some("wowf"), Some("1.60.1.70658"), true, 70658), "official_ready");
        assert_eq!(classify(Some("wowf"), Some("1.60.1.70707"), true, 70658), "official_mismatch");
        assert_eq!(classify(Some("wowf"), Some("1.60.1.70707"), true, 70707), "official_ready");
        assert_eq!(classify(Some("wow_classic_beta"), Some("1.60.1.70707"), true, 70707), "official_ready");
        assert_eq!(classify(Some("wowf"), Some("1.60.1.70790"), true, 70658), "official_mismatch");
        assert_eq!(classify(Some("wowf"), None, true, 70658), "official_unknown_version");
        assert_eq!(classify(Some("wow"), Some("12.0.1.70658"), true, 70658), "official_unsupported");
        assert_eq!(classify(Some("wow_classic_era"), Some("1.15.8.70658"), true, 70658), "official_unsupported");
        assert_eq!(classify(Some("wowf"), Some("1.60.1.70658"), false, 70658), "official_missing_storage");
    }
    #[test]
    fn protected_policy_blocks_all_mutations_including_recovery() {
        assert!(allow_file_operation(true, "verify").is_ok());
        for action in ["repair", "download", "recover", "install_content", "rollback_content"] {
            assert!(allow_file_operation(true, action).is_err());
            assert!(allow_file_operation(false, action).is_ok());
        }
        let settings: config::Settings = serde_json::from_str("{}").unwrap();
        assert!(settings.protect_client_files);
    }
    #[test]
    #[cfg(windows)]
    fn reads_real_windows_version_resources_without_executing_target() {
        let system = std::env::var_os("WINDIR").unwrap();
        let binary = std::path::PathBuf::from(system).join("System32/kernel32.dll");
        assert!(executable_version(&binary).and_then(|s| numeric_version(&s)).is_some());
    }
    #[test]
    #[cfg(windows)]
    fn inspection_cannot_trust_forged_metadata_and_preserves_the_installation() {
        let root = std::env::temp_dir().join(format!("multi-inspect-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let game = root.join("_forever_");
        std::fs::create_dir_all(&game).unwrap();
        std::fs::create_dir_all(root.join("Data/data")).unwrap();
        let kernel = std::path::PathBuf::from(std::env::var_os("WINDIR").unwrap()).join("System32/kernel32.dll");
        // A real native resource, with a deliberately false 1.60 metadata row.
        // This temporary fixture is never executed or committed as game data.
        std::fs::copy(&kernel, game.join("Wow.exe")).unwrap();
        let info = root.join(".build.info");
        std::fs::write(&info, "Product!STRING:0|Active!DEC:1|Version!STRING:0|Tags!STRING:0\nwowf|1|1.60.1.70658|ruRU text\n").unwrap();
        let index = root.join("Data/data/0000000001.idx");
        std::fs::write(&index, b"owned index fixture").unwrap();
        let paths = [game.join("Wow.exe"), info, index];
        let before: Vec<_> = paths.iter().map(|p| std::fs::read(p).unwrap()).collect();
        for selected in [&root, &game, &game.join("Wow.exe")] {
            let report = inspect(selected, 70658);
            assert_eq!(report.metadata_version.as_deref(), Some("1.60.1.70658"));
            assert!(report.version.is_some());
            assert_eq!(report.status, "official_unsupported");
            assert!(!report.ready);
        }
        for (path, bytes) in paths.iter().zip(before) { assert_eq!(std::fs::read(path).unwrap(), bytes); }
        assert!(!game.join("WTF").exists());
        std::fs::remove_dir_all(root).unwrap();
    }
}
