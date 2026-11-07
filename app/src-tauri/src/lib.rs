mod api;
mod addon;
mod addon_catalog;
mod config;
mod packages;
mod client;
mod native;
// macOS: only the entropy is used (see macos.rs); the rest is kept for its tests
#[cfg_attr(target_os = "macos", allow(dead_code))]
mod dpapi;
mod game;
mod official;
mod i18n;
#[cfg(target_os = "macos")]
mod macos;
// macOS: no external memory patch (see macos.rs); kept for its tests
#[cfg_attr(target_os = "macos", allow(dead_code))]
mod patcher;
mod system;

use config::{Session, Settings};
use i18n::{t, tf};
use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
#[cfg(not(target_os = "macos"))]
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};

#[cfg(not(target_os = "macos"))]
const MIN_CLIENT_PAGES: u64 = 50 * 1024 * 1024 / 4096;

#[cfg(windows)]
pub use system::admin_setup;

struct AppState {
    settings: Mutex<Settings>,
    playing: AtomicBool,
    client_cancel: std::sync::Arc<AtomicBool>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Snapshot {
    settings: Settings,
    email: Option<String>,
    platform: &'static str,
    version: &'static str,
    locales: &'static [&'static str],
    runners: Vec<(String, String)>,
    game_found: bool,
    game_version: Option<String>,
    game_executable: String,
    game_auto_login: bool,
    playing: bool,
    official_client: Option<official::Inspection>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct GameEvent {
    kind: &'static str,
    message: String,
}

fn emit(app: &AppHandle, kind: &'static str, message: impl Into<String>) {
    let _ = app.emit("game", GameEvent { kind, message: message.into() });
}

fn runners() -> Vec<(String, String)> {
    #[cfg(target_os = "linux")]
    {
        let mut r = system::list_protons();
        r.push((t("wine_system").into(), "wine".into()));
        r
    }
    #[cfg(not(target_os = "linux"))]
    Vec::new()
}

#[tauri::command]
fn get_state(state: State<AppState>) -> Snapshot {
    let settings = state.settings.lock().unwrap().clone();
    Snapshot {
        official_client: if cfg!(windows) && !settings.game_dir.is_empty() {
            Some(official::inspect(std::path::Path::new(&settings.game_dir), settings.server.client_build))
        } else { None },
        game_found: settings.game_found(),
        game_version: config::installed_version(std::path::Path::new(&settings.game_dir)),
        game_executable: settings.exe().file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(),
        game_auto_login: settings.automatic_game_login(),
        email: Session::load().map(|s| s.email),
        platform: if cfg!(windows) { "windows" } else if cfg!(target_os = "macos") { "macos" } else { "linux" },
        version: env!("CARGO_PKG_VERSION"),
        locales: config::LOCALES,
        runners: runners(),
        playing: state.playing.load(Ordering::SeqCst),
        settings,
    }
}

#[tauri::command]
fn save_settings(state: State<AppState>, settings: Settings) -> Result<(), String> {
    let mut settings = settings;
    if settings.server.portal.is_empty() {
        settings.server.portal = config::DEFAULT_PORTAL.into();
    }
    settings.game_dir = config::normalize_game_dir(std::path::Path::new(&settings.game_dir)).to_string_lossy().into_owned();
    settings.server.validate()?;
    settings.save().map_err(|e| e.to_string())?;
    *state.settings.lock().unwrap() = settings;
    Ok(())
}

/// Language of the messages sent by the Rust side (the UI resolves "system language" itself).
#[tauri::command]
fn set_language(language: String) {
    i18n::set(&language);
}

/// Language installed with the client in that folder (to preselect it).
#[tauri::command]
fn detect_locale(game_dir: String) -> Option<String> {
    config::installed_locale(std::path::Path::new(&game_dir))
}

#[tauri::command]
async fn inspect_official_client(game_dir: String, server_build: u32) -> Result<official::Inspection, String> {
    tokio::task::spawn_blocking(move || official::inspect(std::path::Path::new(&game_dir), server_build))
        .await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn login(state: State<'_, AppState>, email: String, password: String) -> Result<String, String> {
    let server = state.settings.lock().unwrap().server.clone();
    let api = api::Api::new(&server).await?;
    let ticket = api.login(email.trim(), &password).await?;
    let token = api.remember(&ticket).await?;
    let check = api.launcher_login(&token.token).await?;
    Session { email: check.email.clone(), token: token.token, expires: token.expires }
        .save()
        .map_err(|e| tf("session_save", &[&e]))?;
    Ok(check.email.to_lowercase())
}

#[tauri::command]
async fn logout(state: State<'_, AppState>) -> Result<(), String> {
    if let Some(s) = Session::load() {
        let server = state.settings.lock().unwrap().server.clone();
        if let Ok(api) = api::Api::new(&server).await {
            api.forget(&s.token).await;
        }
    }
    Session::clear();
    Ok(())
}

#[derive(Serialize)]
struct Status {
    online: bool,
    login: bool,
}

#[tauri::command]
async fn server_status(state: State<'_, AppState>) -> Result<Status, String> {
    let s = state.settings.lock().unwrap().server.clone();
    let (world, bnet) = tokio::join!(api::port_open(&s.address, s.world_port), api::port_open(&s.address, s.bnet_port));
    Ok(Status { online: world, login: bnet })
}

#[tauri::command]
async fn news(state: State<'_, AppState>) -> Result<Vec<api::NewsItem>, String> {
    let website = state.settings.lock().unwrap().server.website.clone();
    if website.is_empty() {
        return Ok(Vec::new());
    }
    api::news(&website).await
}

#[tauri::command]
async fn checks(state: State<'_, AppState>) -> Result<system::Checks, String> {
    let settings = state.settings.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || system::check(&settings)).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn repair(state: State<'_, AppState>) -> Result<system::Checks, String> {
    let settings = state.settings.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || {
        system::repair(&settings)?;
        Ok(system::check(&settings))
    })
    .await
    .map_err(|e| e.to_string())?
}

fn package_error(e: packages::Error) -> String {
    let key=match e.code {
        "unready"=>"pkg_unready", "client"=>"pkg_client", "changed"=>"pkg_changed",
        "busy"=>"pkg_busy", "recovery"=>"pkg_recovery", "empty"=>"pkg_empty",
        "io"=>"pkg_io", _=>"pkg_invalid",
    };
    format!("{} ({})",t(key),e.detail)
}
struct PackageGuard<'a>(&'a AtomicBool);
impl Drop for PackageGuard<'_> { fn drop(&mut self) { self.0.store(false,Ordering::SeqCst); } }
fn package_guard(state: &AppState) -> Result<PackageGuard<'_>,String> {
    if state.playing.swap(true,Ordering::SeqCst) { return Err(t("pkg_busy").into()) }
    let guard=PackageGuard(&state.playing);
    #[cfg(not(target_os="macos"))]
    if patcher::find_client().is_some() { return Err(t("pkg_close_game").into()) }
    #[cfg(target_os="macos")]
    { return Err(t("pkg_platform").into()); }
    #[allow(unreachable_code)] Ok(guard)
}
#[tauri::command]
async fn addon_channels(refresh:bool)->Result<serde_json::Value,String>{addon::channel_summary(&config::config_dir().join("addon-cache"),refresh).await}
#[tauri::command]
fn content_catalog() -> serde_json::Value {
    serde_json::from_str(include_str!("../../../content/packages/catalog.json")).expect("embedded content catalog")
}
#[tauri::command]
fn content_status(game_dir: String) -> Result<packages::Status,String> {
    packages::status(std::path::Path::new(&game_dir)).map_err(package_error)
}
#[tauri::command]
async fn inspect_content(game_dir: String,package_dir: String) -> Result<packages::Preview,String> {
    tokio::task::spawn_blocking(move|| {
        let game=std::path::Path::new(&game_dir);
        let version=config::installed_version(game).ok_or_else(||t("pkg_client").to_string())?;
        packages::inspect(std::path::Path::new(&package_dir),game,&version).map_err(package_error)
    }).await.map_err(|e|e.to_string())?
}
#[tauri::command]
async fn install_content(state:State<'_,AppState>,game_dir:String,package_dir:String) -> Result<packages::Status,String> {
    state.settings.lock().unwrap().allow_client_work("install_content")?;
    official::allow_file_operation(state.settings.lock().unwrap().protect_client_files, "install_content")?;
    let _guard=package_guard(&state)?;
    tokio::task::spawn_blocking(move|| {
        let game=std::path::Path::new(&game_dir);
        let version=config::installed_version(game).ok_or_else(||t("pkg_client").to_string())?;
        packages::install(std::path::Path::new(&package_dir),game,&version).map_err(package_error)
    }).await.map_err(|e|e.to_string())?
}
#[tauri::command]
async fn rollback_content(state:State<'_,AppState>,game_dir:String) -> Result<packages::Status,String> {
    state.settings.lock().unwrap().allow_client_work("rollback_content")?;
    official::allow_file_operation(state.settings.lock().unwrap().protect_client_files, "rollback_content")?;
    let _guard=package_guard(&state)?;
    tokio::task::spawn_blocking(move||packages::rollback(std::path::Path::new(&game_dir)).map_err(package_error))
        .await.map_err(|e|e.to_string())?
}

#[tauri::command]
fn cancel_client_work(state: State<AppState>) {
    state.client_cancel.store(true, Ordering::SeqCst);
}

#[tauri::command]
async fn native_client_work(app:AppHandle,state:State<'_,AppState>,request:native::Request)->Result<serde_json::Value,String>{
    state.settings.lock().unwrap().allow_client_work(&request.action)?;
    if state.playing.swap(true,Ordering::SeqCst){return Err(t("already_running").into());}
    let _guard=PackageGuard(&state.playing);
    #[cfg(not(target_os="macos"))]
    if patcher::find_client().is_some(){return Err(t("already_running").into());}
    #[cfg(not(windows))]
    {let _=(app,request);return Err("Native CDN downloads currently require Windows".into());}
    #[cfg(windows)]
    {
        use tauri::Manager;
        let worker=native::worker_path(app.path().resource_dir().ok())?;
        state.client_cancel.store(false,Ordering::SeqCst);let cancel=state.client_cancel.clone();
        tokio::task::spawn_blocking(move||native::run(&worker,request,&cancel,|value|{let _=app.emit("native-progress",value);})).await.map_err(|e|e.to_string())?
    }
}

#[tauri::command]
fn inspect_client_locations(game_dir:String,reference_dir:String)->Result<client::Locations,client::Error> {
    client::locations(&game_dir,&reference_dir)
}

#[tauri::command]
async fn client_work(app: AppHandle, state: State<'_, AppState>, request: client::Request) -> Result<client::Report, client::Error> {
    state.settings.lock().unwrap().allow_client_work(&request.action).map_err(|detail|client::Error{code:"updates_paused",detail})?;
    official::allow_file_operation(state.settings.lock().unwrap().protect_client_files, &request.action)
        .map_err(|detail| client::Error { code:"protected", detail })?;
    if state.playing.swap(true, Ordering::SeqCst) { return Err(client::Error { code:"busy", detail:String::new() }); }
    let _guard=PackageGuard(&state.playing);
    #[cfg(not(target_os="macos"))]
    if patcher::find_client().is_some() { return Err(client::Error { code:"running", detail:String::new() }); }
    state.client_cancel.store(false, Ordering::SeqCst);
    let cancel=state.client_cancel.clone();
    let runtime=tokio::runtime::Handle::current();
    tokio::task::spawn_blocking(move || {
        // Hashing can produce hundreds of chunks per second; keep the webview responsive.
        let throttle=std::sync::Mutex::new((std::time::Instant::now()-std::time::Duration::from_secs(1),""));
        runtime.block_on(client::run(request,config::config_dir().join("workshop"),&cancel,move|p|{
            let mut clock=throttle.lock().unwrap();
            if clock.1!=p.phase || clock.0.elapsed()>=std::time::Duration::from_millis(120) || p.phase=="done" {
                clock.0=std::time::Instant::now();clock.1=p.phase;let _=app.emit("client-progress",p);
            }
        }))
    })
        .await.map_err(|e|client::Error { code:"io", detail:e.to_string() })?
}

#[tauri::command]
async fn play(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    if state.playing.swap(true, Ordering::SeqCst) {
        return Err(t("already_running").into());
    }
    let settings = state.settings.lock().unwrap().clone();
    let result = start(&app, settings).await;
    if result.is_err() {
        state.playing.store(false, Ordering::SeqCst);
    }
    result
}

fn game_account_for_login(email:&str, login:&api::LauncherLogin)->Result<String,String>{
    if !email.eq_ignore_ascii_case(&login.email) || login.login_ticket.is_empty() || login.login_ticket.len()>4096 || login.login_ticket.chars().any(|c|c.is_control()) {
        return Err(t("login_account_mismatch").into());
    }
    let account=login.game_accounts.first().ok_or_else(||t("login_no_game_account").to_string())?.name.clone();
    if account.is_empty()||account.len()>128||account.chars().any(|c|c.is_control()||matches!(c,'"'|'\\')){return Err(t("login_no_game_account").into());}
    Ok(account)
}

async fn start(app: &AppHandle, settings: Settings) -> Result<(), String> {
    if !settings.game_found() {
        return Err(t("game_not_found").into());
    }
    settings.server.validate()?;
    #[cfg(windows)]
    if settings.protect_client_files {
        let inspection = official::inspect(std::path::Path::new(&settings.game_dir), settings.server.client_build);
        official::require_ready(&inspection)?;
        emit(app, "log", inspection.message);
    }
    #[cfg(not(target_os = "macos"))]
    if patcher::find_client_for(&settings.exe()).is_some() { return Err(t("already_running").into()); }
    let game = std::path::Path::new(&settings.game_dir);
    if game.parent().is_some_and(|root| root.join(".forever-content").exists()) {
        let status = packages::status(game).map_err(package_error)?;
        if status.recovery_needed {
            return Err(t("pkg_recovery").into());
        }
    }
    let session = Session::load().ok_or(t("login_first"))?;
    emit(app, "step", t("step_connecting"));
    let api = api::Api::new(&settings.server).await?;

    emit(app, "step", t("step_preparing"));
    addon::ensure(std::path::Path::new(&settings.game_dir), settings.addon_updates_enabled, settings.addon_development_mode, &settings.addon_channel, settings.server.client_build, &config::config_dir().join("addon-cache"), |message| emit(app, "log", message)).await?;
    let login = match api.launcher_login(&session.token).await {
        Err(e) if e == "expired" => {
            Session::clear();
            return Err(t("session_expired").into());
        }
        other => other?,
    };

    let account = game_account_for_login(&session.email, &login)?;
    let s = settings.clone();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        game::write_wtf(&s)?;
        #[cfg(target_os = "linux")]
        system::install_ca_in_prefix(&s)?;
        let portal = format!("{}:{}", s.server.portal, s.server.bnet_port);
        #[cfg(not(target_os = "macos"))]
        if s.automatic_game_login() { game::write_launch_options(&s, &portal, &login.login_ticket, &account)?; }
        #[cfg(target_os = "macos")]
        if s.automatic_game_login() { macos::write_launch_options(&portal, &login.login_ticket, &account)?; }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())??;
    launch(app, settings).await
}

/// macOS: re-signed copy of the game with keypatch.dylib, followed through the library's log.
#[cfg(target_os = "macos")]
async fn launch(app: &AppHandle, settings: Settings) -> Result<(), String> {
    let (a, s) = (app.clone(), settings.clone());
    let copy = tokio::task::spawn_blocking(move || macos::prepare_copy(&s, |m| emit(&a, "step", m)))
        .await
        .map_err(|e| e.to_string())??;
    emit(app, "step", t("step_launching"));
    let (child, log) = macos::spawn(&settings, &copy)?;
    let app = app.clone();
    std::thread::spawn(move || {
        emit(&app, "running", t("running"));
        match macos::watch(child, &log, |kind, m| emit(&app, kind, m)) {
            Ok(()) => emit(&app, "closed", t("closed")),
            Err(e) => emit(&app, "error", e),
        }
        app.state::<AppState>().playing.store(false, Ordering::SeqCst);
    });
    Ok(())
}

/// Windows, Linux: the game is started, then the patcher writes the key into its memory.
#[cfg(not(target_os = "macos"))]
async fn launch(app: &AppHandle, settings: Settings) -> Result<(), String> {
    emit(app, "step", t("step_launching"));
    let patcher = patcher::Patcher::new(&settings.server.public_key, settings.server.region_group)?;
    let selected_exe = settings.exe();
    emit(app, "log", tf("launch_executable", &[&selected_exe.display()]));
    let mut child = game::spawn(&settings)?;
    let app = app.clone();
    std::thread::spawn(move || {
        // reap the started process (on Linux it is umu-run / gamescope, which may exit early)
        let child_pid = child.id();
        std::thread::spawn(move || {
            let _ = child.wait();
        });
        let first = wait_for_client(child_pid, &selected_exe);
        match first {
            Some(mem) => {
                emit(&app, "running", t("running"));
                let ended = patcher.watch(
                    Box::new(mem),
                    |cur| {
                        let other = patcher::find_client_for(&selected_exe)?;
                        let better = !cur.alive() || other.rss() > (current_rss(cur) * 2).max(MIN_CLIENT_PAGES);
                        (other_pid(&other) != cur.pid() && better).then(|| Box::new(other) as Box<dyn patcher::Memory>)
                    },
                    |ev| match ev {
                        patcher::Event::Log(m) => emit(&app, "log", m),
                        patcher::Event::Ready => emit(&app, "ready", t("ready")),
                        patcher::Event::Closed => {}
                    },
                );
                let code = ended.exit_code.map(|c|format!("0x{c:08X} ({c})")).unwrap_or_else(||t("exit_unknown").into());
                emit(&app, "log", tf("client_exit", &[&ended.pid,&code]));
                if !ended.ready { emit(&app, "log", t("closed_before_ready")); }
                emit(&app, "closed", t("closed"));
            }
            None => emit(&app, "error", t("not_started")),
        }
        app.state::<AppState>().playing.store(false, Ordering::SeqCst);
    });
    Ok(())
}

use tauri::Manager;

#[cfg(not(target_os = "macos"))]
fn other_pid(m: &patcher::ProcessMemory) -> u32 {
    use patcher::Memory;
    m.pid()
}

#[cfg(not(target_os = "macos"))]
fn current_rss(m: &dyn patcher::Memory) -> u64 {
    patcher::ProcessMemory::open(m.pid()).map(|p| p.rss()).unwrap_or(0)
}

#[cfg(not(target_os = "macos"))]
fn wait_for_client(child_pid: u32, selected_exe: &std::path::Path) -> Option<patcher::ProcessMemory> {
    #[cfg(windows)]
    if let Some(m) = patcher::ProcessMemory::open(child_pid) {
        if m.matches_exe(selected_exe) && m.rss() >= MIN_CLIENT_PAGES { return Some(m); }
    }
    let _ = child_pid;
    for _ in 0..180 {
        if let Some(m) = patcher::find_client_for(selected_exe) {
            if m.rss() >= MIN_CLIENT_PAGES { return Some(m); }
        }
        std::thread::sleep(Duration::from_secs(1));
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(AppState { settings: Mutex::new(Settings::load()), playing: AtomicBool::new(false), client_cancel: std::sync::Arc::new(AtomicBool::new(false)) })
        .invoke_handler(tauri::generate_handler![
            get_state, save_settings, set_language, detect_locale, inspect_official_client, login, logout, server_status, news, checks, repair, play,
            addon_channels, content_catalog, content_status, inspect_content, install_content, rollback_content
            , client_work, native_client_work, cancel_client_work, inspect_client_locations
        ])
        .run(tauri::generate_context!())
        .expect("error while running Forever Launcher");
}

#[cfg(test)]mod game_login_tests {
 use super::*;
 fn reply(email:&str,accounts:&[&str])->api::LauncherLogin{api::LauncherLogin{email:email.into(),login_ticket:"TC-synthetic-ticket".into(),game_accounts:accounts.iter().map(|n|api::GameAccount{name:(*n).into()}).collect()}}
 #[test]fn automatic_login_uses_the_authenticated_users_game_account(){let r=reply("player@example.test",&["WoW1"]);assert_eq!(game_account_for_login("PLAYER@example.test",&r).unwrap(),"WoW1");}
 #[test]fn stale_or_wrong_account_and_missing_game_account_cannot_fall_back_to_wow1(){assert!(game_account_for_login("other@example.test",&reply("player@example.test",&["WoW1"])).is_err());assert!(game_account_for_login("player@example.test",&reply("player@example.test",&[])).is_err());let mut r=reply("player@example.test",&["WoW1"]);r.login_ticket.clear();assert!(game_account_for_login("player@example.test",&r).is_err());}
 #[test]fn ticket_refresh_happens_after_potentially_long_addon_updates(){let source=include_str!("lib.rs");let start=source.split("async fn start(app:").nth(1).unwrap().split("/// macOS:").next().unwrap();assert!(start.find("addon::ensure(").unwrap()<start.find("api.launcher_login(").unwrap());}
}
