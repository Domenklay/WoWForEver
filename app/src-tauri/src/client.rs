//! Client workshop: exact-file baseline verification, local recovery and HTTP manifests.
//! This operates on complete installation files, not individual CASC objects. It never
//! invents a CDN profile, changes build versions or executes a downloaded file.
//! Surplus CASC bookkeeping is quarantined with the replacement transaction;
//! unrelated extras and user settings remain untouched.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const LIMIT: usize = 16 * 1024 * 1024;
const BUFFER: usize = 1024 * 1024;

#[derive(Debug, Serialize)]
pub struct Error {
    pub code: &'static str,
    pub detail: String,
}
type Result<T> = std::result::Result<T, Error>;
fn err(code: &'static str, detail: impl ToString) -> Error {
    Error {
        code,
        detail: detail.to_string(),
    }
}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        err("io", e)
    }
}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        err("manifest", e)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Settings {
    pub reference_dir: String,
    pub manifest_source: String,
}
impl Default for Settings {
    fn default() -> Self {
        let original = Path::new(r"E:\WoW_Forever");
        let reference_dir = if cfg!(windows)
            && original.join(".build.info").is_file()
            && original.join("Data").is_dir()
        {
            original.to_string_lossy().into_owned()
        } else {
            String::new()
        };
        Self {
            reference_dir,
            manifest_source: String::new(),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Request {
    pub action: String,
    pub game_dir: String,
    pub source: Settings,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Profile {
    pub product: String,
    pub version: String,
    pub build_key: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Entry {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
    #[serde(default)]
    pub url: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub profile: Profile,
    pub files: Vec<Entry>,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    pub phase: &'static str,
    pub path: String,
    pub files_done: usize,
    pub files_total: usize,
    pub bytes_done: u64,
    pub bytes_total: u64,
    pub bytes_per_second: u64,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Report {
    pub action: String,
    pub source_kind: &'static str,
    pub profile: Profile,
    pub files: usize,
    pub comparison_only: bool,
    pub target_executable_version: Option<String>,
    pub reference_executable_version: Option<String>,
    pub verified: usize,
    pub different: usize,
    pub resource_different: usize,
    pub storage_different: usize,
    pub remaining: usize,
    pub repaired: usize,
    pub quarantined: usize,
    pub extra_storage_files: Vec<String>,
    pub bytes: u64,
    pub differences: Vec<String>,
    pub report_path: String,
    pub backup: Option<String>,
    pub target_root: String,
    pub reference_root: Option<String>,
    pub scope: &'static str,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Locations {
    pub target_root: String,
    pub target_data: String,
    pub reference_root: Option<String>,
    pub reference_data: Option<String>,
}

fn display_path(path: &Path) -> String {
    let value = path.to_string_lossy();
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else {
        value.trim_start_matches(r"\\?\").into()
    }
}
fn executable_version(root: &Path) -> Option<String> {
    let settings = crate::config::Settings { game_dir: root.to_string_lossy().into_owned(), ..Default::default() };
    crate::official::executable_version(&settings.exe())
}
pub fn locations(game_dir: &str, reference_dir: &str) -> Result<Locations> {
    let target = root(game_dir, false)?;
    let reference = if reference_dir.trim().is_empty() {
        None
    } else {
        Some(root(reference_dir, false)?)
    };
    Ok(Locations {
        target_root: display_path(&target),
        target_data: display_path(&target.join("Data")),
        reference_root: reference.as_deref().map(display_path),
        reference_data: reference.as_ref().map(|p| display_path(&p.join("Data"))),
    })
}
/// These files describe local CASC bookkeeping. A byte difference is not proof
/// of corruption; they remain in strict baseline verification and repair.
fn storage_metadata(path: &str) -> bool {
    let lower = path.to_ascii_lowercase();
    lower.strip_prefix("data/data/").is_some_and(|name| {
        !name.contains('/')
            && (name == "shmem"
                || name == "repairmarker.psv"
                || name.ends_with(".idx")
                || name.ends_with(".lru"))
    })
}
fn index_bucket(name: &str) -> Option<u8> {
    let lower = name.to_ascii_lowercase();
    let hex = lower.strip_suffix(".idx")?;
    if hex.len() != 10 || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        return None;
    }
    let bucket = u8::from_str_radix(&hex[..2], 16).ok()?;
    (bucket < 16).then_some(bucket)
}
fn quarantine_name(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    index_bucket(&lower).is_some()
        || lower == "repairmarker.psv"
        || lower.strip_suffix(".lru").is_some_and(|hex| {
            matches!(hex.len(), 16 | 20) && hex.bytes().all(|b| b.is_ascii_hexdigit())
        })
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct Quarantine {
    path: String,
    sha256: String,
}

/// Only recognized immediate CASC metadata is eligible. Never remove archives,
/// user files or arbitrary extras, and never prune from an incomplete baseline.
fn extra_storage(root: &Path, manifest: &Manifest, cancel: &AtomicBool) -> Result<Vec<Quarantine>> {
    if manifest
        .files
        .iter()
        .any(|e| e.path.eq_ignore_ascii_case("Data/data/RepairMarker.psv"))
    {
        return Err(err(
            "storage_baseline",
            "The selected baseline contains Data/data/RepairMarker.psv",
        ));
    }
    let expected: HashSet<_> = manifest
        .files
        .iter()
        .map(|e| e.path.to_ascii_lowercase())
        .collect();
    let folder = safe(root, "Data/data")?;
    if !folder.exists() {
        return Ok(Vec::new());
    }
    let mut extras = Vec::new();
    for item in fs::read_dir(folder)? {
        check_cancel(cancel)?;
        let item = item?;
        let name = item.file_name().to_string_lossy().into_owned();
        let path = format!("Data/data/{name}");
        if !quarantine_name(&name) || expected.contains(&path.to_ascii_lowercase()) {
            continue;
        }
        let file = safe(root, &path)?;
        if !fs::symlink_metadata(&file)?.is_file() {
            return Err(err("path", path));
        }
        validate_path(&path)?;
        extras.push(Quarantine {
            path,
            sha256: fingerprint(&file, cancel, |_| {})?.1,
        });
    }
    if !extras.is_empty() {
        let buckets: HashSet<_> = manifest
            .files
            .iter()
            .filter_map(|e| e.path.strip_prefix("Data/data/").and_then(index_bucket))
            .collect();
        if buckets.len() != 16 {
            return Err(err(
                "storage_baseline",
                "Surplus CASC metadata requires a baseline with all 16 index buckets",
            ));
        }
    }
    extras.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(extras)
}
type StorageStamp = Vec<(String, u64, SystemTime)>;
fn storage_stamp(root: &Path) -> Result<StorageStamp> {
    let mut stamp = Vec::new();
    for item in fs::read_dir(safe(root, "Data/data")?)? {
        let item = item?;
        let name = item.file_name().to_string_lossy().into_owned();
        let path = safe(root, &format!("Data/data/{name}"))?;
        let meta = fs::symlink_metadata(path)?;
        if !meta.is_file() {
            return Err(err("path", name));
        }
        stamp.push((name, meta.len(), meta.modified()?));
    }
    stamp.sort();
    Ok(stamp)
}
fn unchanged_storage(root: &Path, before: &StorageStamp) -> Result<()> {
    if storage_stamp(root)? != *before {
        return Err(err(
            "changed",
            "Original Data/data changed; close games and downloaders",
        ));
    }
    Ok(())
}
#[derive(Clone, Serialize, Deserialize)]
struct Change {
    entry: Entry,
    old_sha256: Option<String>,
}
#[derive(Serialize, Deserialize)]
struct Journal {
    format: String,
    root: String,
    phase: String,
    changes: Vec<Change>,
    #[serde(default)]
    quarantines: Vec<Quarantine>,
}

fn check_cancel(cancel: &AtomicBool) -> Result<()> {
    if cancel.load(Ordering::Relaxed) {
        Err(err("cancelled", ""))
    } else {
        Ok(())
    }
}
fn sha(data: &[u8]) -> String {
    hex::encode(Sha256::digest(data))
}
fn valid_hash(hash: &str, len: usize) -> bool {
    hash.len() == len && hash.bytes().all(|b| b.is_ascii_hexdigit())
}

fn profile(raw: &str) -> Result<Profile> {
    let mut lines = raw.trim_start_matches('\u{feff}').lines();
    let head: Vec<_> = lines
        .next()
        .ok_or_else(|| err("profile", ".build.info"))?
        .split('|')
        .map(|s| s.split('!').next().unwrap_or(""))
        .collect();
    let col = |name| {
        head.iter()
            .position(|c| *c == name)
            .ok_or_else(|| err("profile", name))
    };
    let (p, a, v, b) = (
        col("Product")?,
        col("Active")?,
        col("Version")?,
        col("Build Key")?,
    );
    let mut found = Vec::new();
    for l in lines {
        let r: Vec<_> = l.split('|').collect();
        if r.len() == head.len() && r[a] == "1" && matches!(r[p], "wowf" | "wow_classic_beta") {
            if !valid_hash(r[b], 32) || r[v].is_empty() {
                return Err(err("profile", "build identity"));
            }
            found.push(Profile {
                product: r[p].into(),
                version: r[v].into(),
                build_key: r[b].to_ascii_lowercase(),
            });
        }
    }
    if found.len() != 1 {
        return Err(err(
            "profile",
            "Select an installation with exactly one active Forever product",
        ));
    }
    Ok(found.remove(0))
}
fn read_profile(root: &Path) -> Result<Profile> {
    profile(&fs::read_to_string(safe(root, ".build.info")?)?)
}
fn game_part(p: &Profile) -> &'static str {
    if p.product == "wowf" {
        "_forever_"
    } else {
        "_classic_beta_"
    }
}

fn linked(meta: &fs::Metadata) -> bool {
    if meta.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & 0x400 != 0 {
            return true;
        }
    }
    false
}
fn validate_path(path: &str) -> Result<()> {
    if path.is_empty() || path.contains('\\') {
        return Err(err("path", path));
    }
    for c in path.split('/') {
        let stem = c.split('.').next().unwrap_or("").to_ascii_uppercase();
        if c.is_empty()
            || c == "."
            || c == ".."
            || c.ends_with(['.', ' '])
            || c.chars().any(|c| c.is_control() || ":*?\"<>|".contains(c))
            || matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
            || (stem.len() == 4
                && (stem.starts_with("COM") || stem.starts_with("LPT"))
                && stem.as_bytes()[3].is_ascii_digit())
        {
            return Err(err("path", path));
        }
    }
    let bits: Vec<_> = path.split('/').collect();
    let protected = bits.iter().skip(1).any(|p| {
        matches!(
            p.to_ascii_lowercase().as_str(),
            "wtf" | "interface" | "cache" | "logs" | "errors" | "screenshots" | ".forever-multi"
        )
    });
    if protected
        || !(path == ".build.info"
            || (bits.len() > 1 && matches!(bits[0], "Data" | "_forever_" | "_classic_beta_")))
    {
        return Err(err("path", path));
    }
    Ok(())
}
fn safe(root: &Path, relative: &str) -> Result<PathBuf> {
    // Also used for our own journal paths, whose names never come from a manifest.
    let mut p = root.to_path_buf();
    for c in relative.split('/') {
        if c.is_empty() || c == "." || c == ".." || c.contains(['\\', ':']) {
            return Err(err("path", relative));
        }
        p.push(c);
        match fs::symlink_metadata(&p) {
            Ok(m) if linked(&m) => return Err(err("path", relative)),
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(p)
}
fn root(input: &str, create: bool) -> Result<PathBuf> {
    if input.trim().is_empty() {
        return Err(err("folder", ""));
    }
    let mut p = PathBuf::from(input);
    if p.extension().is_some_and(|s| s.eq_ignore_ascii_case("exe")) {
        p = p.parent().ok_or_else(|| err("folder", ""))?.into();
    }
    if p.file_name()
        .is_some_and(|s| s == "_forever_" || s == "_classic_beta_")
    {
        p = p.parent().ok_or_else(|| err("folder", ""))?.into();
    }
    if p.parent().is_none() || p.parent().is_some_and(|p| p.as_os_str().is_empty()) {
        return Err(err("folder", "Use an installation directory"));
    }
    if create {
        fs::create_dir_all(&p)?;
    }
    if linked(&fs::symlink_metadata(&p)?) {
        return Err(err("path", "linked installation"));
    }
    Ok(fs::canonicalize(p)?)
}
fn fingerprint(
    path: &Path,
    cancel: &AtomicBool,
    mut progress: impl FnMut(u64),
) -> Result<(u64, String)> {
    let meta = fs::metadata(path)?;
    if !meta.is_file() {
        return Err(err("path", path.display()));
    }
    let mut file = File::open(path)?;
    let mut buf = vec![0; BUFFER];
    let mut hash = Sha256::new();
    let mut size = 0;
    loop {
        check_cancel(cancel)?;
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
        size += n as u64;
        progress(n as u64);
    }
    let after = fs::metadata(path)?;
    if size != meta.len()
        || meta.len() != after.len()
        || meta.modified().ok() != after.modified().ok()
    {
        return Err(err("changed", path.display()));
    }
    Ok((size, hex::encode(hash.finalize())))
}
fn inventory(
    root: &Path,
    p: &Profile,
    cancel: &AtomicBool,
    emit: &impl Fn(Progress),
) -> Result<Vec<Entry>> {
    emit(Progress {
        phase: "scan",
        path: display_path(root),
        files_done: 0,
        files_total: 0,
        bytes_done: 0,
        bytes_total: 0,
        bytes_per_second: 0,
    });
    fn walk(base: &Path, rel: &str, out: &mut Vec<String>, cancel: &AtomicBool) -> Result<()> {
        check_cancel(cancel)?;
        let path = safe(base, rel)?;
        for e in fs::read_dir(path)? {
            let e = e?;
            let child = format!("{rel}/{}", e.file_name().to_string_lossy());
            if validate_path(&child).is_err() {
                continue;
            }
            let m = fs::symlink_metadata(e.path())?;
            if linked(&m) {
                return Err(err("path", child));
            }
            if m.is_dir() {
                walk(base, &child, out, cancel)?;
            } else if m.is_file() {
                out.push(child);
            }
        }
        Ok(())
    }
    let mut paths = vec![".build.info".into()];
    walk(root, "Data", &mut paths, cancel)?;
    walk(root, game_part(p), &mut paths, cancel)?;
    paths.sort();
    let count = paths.len();
    let mut files = Vec::new();
    let total = paths.iter().try_fold(0u64, |sum, path| -> Result<u64> {
        Ok(sum.saturating_add(fs::metadata(safe(root, path)?)?.len()))
    })?;
    let mut done = 0;
    let timer = Instant::now();
    for (i, path) in paths.into_iter().enumerate() {
        emit(Progress {
            phase: "reference",
            path: path.clone(),
            files_done: i,
            files_total: count,
            bytes_done: done,
            bytes_total: total,
            bytes_per_second: 0,
        });
        let (bytes, sha256) = fingerprint(&safe(root, &path)?, cancel, |n| {
            done += n;
            emit(Progress {
                phase: "reference",
                path: path.clone(),
                files_done: i,
                files_total: count,
                bytes_done: done,
                bytes_total: total,
                bytes_per_second: (done as f64 / timer.elapsed().as_secs_f64().max(0.1)) as u64,
            });
        })?;
        files.push(Entry {
            path,
            bytes,
            sha256,
            url: None,
        });
    }
    Ok(files)
}
fn url(input: &str) -> Result<reqwest::Url> {
    let u = reqwest::Url::parse(input).map_err(|_| err("source", "Invalid URL"))?;
    let local = u
        .host_str()
        .is_some_and(|h| matches!(h, "127.0.0.1" | "localhost" | "[::1]"));
    if !(u.scheme() == "https" || (u.scheme() == "http" && local))
        || !u.username().is_empty()
        || u.password().is_some()
        || u.fragment().is_some()
    {
        return Err(err("source", "Use HTTPS or a loopback HTTP server"));
    }
    Ok(u)
}
fn validate(m: &Manifest) -> Result<()> {
    if m.format != "forever-multi-client-v1"
        || !matches!(m.profile.product.as_str(), "wowf" | "wow_classic_beta")
        || !valid_hash(&m.profile.build_key, 32)
        || m.profile.version.is_empty()
        || m.files.is_empty()
        || m.files.len() > 200000
    {
        return Err(err("manifest", "format/profile"));
    }
    let mut seen = HashSet::new();
    for e in &m.files {
        validate_path(&e.path)?;
        if !seen.insert(e.path.to_ascii_lowercase())
            || !valid_hash(&e.sha256, 64)
            || e.bytes > 1 << 40
        {
            return Err(err("manifest", &e.path));
        }
        if let Some(u) = &e.url {
            url(u)?;
        }
        if (e.path.starts_with("_forever_/") && m.profile.product != "wowf")
            || (e.path.starts_with("_classic_beta_/") && m.profile.product != "wow_classic_beta")
        {
            return Err(err("manifest", "mixed product"));
        }
    }
    let exe = format!(
        "{}/{}",
        game_part(&m.profile),
        if m.profile.product == "wowf" {
            "Wow.exe"
        } else {
            "WowB.exe"
        }
    );
    if !seen.contains(".build.info")
        || !seen.contains(&exe.to_ascii_lowercase())
        || !seen.iter().any(|s| s.starts_with("data/config/"))
        || !seen.iter().any(|s| s.starts_with("data/data/"))
    {
        return Err(err("manifest", "incomplete baseline"));
    }
    Ok(())
}
async fn response_bytes(
    response: &mut reqwest::Response,
    cancel: &AtomicBool,
) -> Result<Option<Vec<u8>>> {
    let cancelled = async {
        loop {
            if cancel.load(Ordering::Relaxed) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(75)).await;
        }
    };
    tokio::select! {
        _=cancelled=>Err(err("cancelled","")),
        r=tokio::time::timeout(Duration::from_secs(30),response.chunk())=>r.map_err(|_|err("network","Read timed out"))?.map(|v|v.map(|b|b.to_vec())).map_err(|e|err("network",e.without_url()))
    }
}
fn http_client() -> Result<reqwest::Client> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() > 5 || url(attempt.url().as_str()).is_err() {
                attempt.stop()
            } else {
                attempt.follow()
            }
        }))
        .build()
        .map_err(|e| err("network", e.without_url()))
}
async fn send(request: reqwest::RequestBuilder, cancel: &AtomicBool) -> Result<reqwest::Response> {
    let cancelled = async {
        loop {
            if cancel.load(Ordering::Relaxed) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(75)).await;
        }
    };
    tokio::select! {
        _=cancelled=>Err(err("cancelled","")),
        r=tokio::time::timeout(Duration::from_secs(30),request.send())=>r.map_err(|_|err("network","Response timed out"))?.map_err(|e|err("network",e.without_url()))
    }
}
async fn load_manifest(
    source: &str,
    http: &reqwest::Client,
    cancel: &AtomicBool,
) -> Result<Manifest> {
    let raw = if source.starts_with("https://") || source.starts_with("http://") {
        let mut response = send(
            http.get(url(source)?).header("Accept-Encoding", "identity"),
            cancel,
        )
        .await?
        .error_for_status()
        .map_err(|e| err("network", e.without_url()))?;
        let mut data = Vec::new();
        while let Some(c) = response_bytes(&mut response, cancel).await? {
            if data.len() + c.len() > LIMIT {
                return Err(err("manifest", "too large"));
            }
            data.extend(c);
        }
        data
    } else {
        let f = File::open(source)?;
        let mut data = Vec::new();
        f.take(LIMIT as u64 + 1).read_to_end(&mut data)?;
        data
    };
    if raw.len() > LIMIT {
        return Err(err("manifest", "too large"));
    }
    let mut m: Manifest = serde_json::from_slice(&raw)?;
    validate(&m)?;
    m.profile.build_key.make_ascii_lowercase();
    Ok(m)
}
fn json(path: &Path, value: &impl Serialize) -> Result<()> {
    let tmp = path.with_extension(format!("{}.tmp", rand::random::<u64>()));
    let mut f = OpenOptions::new().write(true).create_new(true).open(&tmp)?;
    f.write_all(&serde_json::to_vec_pretty(value)?)?;
    f.sync_all()?;
    // On Windows rename does not replace. The journal is immutable until commit:
    // journal and completion marker are separate files, never remove-before-write.
    fs::rename(tmp, path)?;
    Ok(())
}
async fn download(
    http: &reqwest::Client,
    e: &Entry,
    part: &Path,
    cancel: &AtomicBool,
    mut progress: impl FnMut(u64),
) -> Result<()> {
    let uri = url(e.url.as_deref().ok_or_else(|| err("source", &e.path))?)?;
    let mut offset = if part.is_file() {
        fs::metadata(part)?.len()
    } else {
        0
    };
    if offset > e.bytes {
        fs::remove_file(part)?;
        offset = 0;
    }
    if offset == e.bytes && part.exists() {
        if fingerprint(part, cancel, |_| {})?.1 == e.sha256.to_ascii_lowercase() {
            return Ok(());
        }
        fs::remove_file(part)?;
        offset = 0;
    }
    check_cancel(cancel)?;
    let mut req = http.get(uri).header("Accept-Encoding", "identity");
    if offset > 0 {
        req = req.header(reqwest::header::RANGE, format!("bytes={offset}-"));
    }
    let mut response = send(req, cancel).await?;
    if response.status() == reqwest::StatusCode::PARTIAL_CONTENT {
        let range = response
            .headers()
            .get(reqwest::header::CONTENT_RANGE)
            .and_then(|s| s.to_str().ok())
            .unwrap_or("");
        let expected = format!("bytes {offset}-{}/{}", e.bytes.saturating_sub(1), e.bytes);
        if range != expected {
            return Err(err("network", "Invalid Content-Range"));
        }
    } else if response.status() == reqwest::StatusCode::OK {
        offset = 0;
    } else {
        return Err(err("network", response.status()));
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(offset == 0)
        .append(offset > 0)
        .open(part)?;
    let mut size = offset;
    while let Some(c) = response_bytes(&mut response, cancel).await? {
        if size + c.len() as u64 > e.bytes {
            return Err(err("integrity", &e.path));
        }
        file.write_all(&c)?;
        size += c.len() as u64;
        progress(c.len() as u64);
    }
    file.sync_all()?;
    drop(file);
    if size != e.bytes {
        return Err(err("network", "Incomplete download; it can be resumed"));
    }
    if fingerprint(part, cancel, |_| {})?.1 != e.sha256.to_ascii_lowercase() {
        fs::remove_file(part)?;
        return Err(err("integrity", &e.path));
    }
    Ok(())
}
fn copy(
    source: &Path,
    part: &Path,
    e: &Entry,
    cancel: &AtomicBool,
    mut progress: impl FnMut(u64),
) -> Result<()> {
    let mut input = File::open(source)?;
    let mut output = File::create(part)?;
    let mut buf = vec![0; BUFFER];
    let mut hash = Sha256::new();
    let mut size = 0;
    loop {
        check_cancel(cancel)?;
        let n = input.read(&mut buf)?;
        if n == 0 {
            break;
        }
        output.write_all(&buf[..n])?;
        hash.update(&buf[..n]);
        size += n as u64;
        progress(n as u64);
    }
    output.sync_all()?;
    if size != e.bytes || hex::encode(hash.finalize()) != e.sha256 {
        return Err(err("changed", &e.path));
    }
    Ok(())
}
fn restore(root: &Path, op: &Path, cancel: &AtomicBool) -> Result<()> {
    let j: Journal = serde_json::from_slice(&fs::read(op.join("journal.json"))?)?;
    if !matches!(
        j.format.as_str(),
        "forever-multi-recovery-v1" | "forever-multi-recovery-v2"
    ) || Path::new(&j.root) != root
        || (j.format == "forever-multi-recovery-v1" && !j.quarantines.is_empty())
    {
        return Err(err("recovery", "Journal identity mismatch"));
    }
    let mut seen = HashSet::new();
    for c in &j.changes {
        if !seen.insert(c.entry.path.to_ascii_lowercase()) {
            return Err(err("recovery", "Duplicate journal path"));
        }
    }
    for q in &j.quarantines {
        validate_path(&q.path)?;
        if !q
            .path
            .strip_prefix("Data/data/")
            .is_some_and(quarantine_name)
            || !seen.insert(q.path.to_ascii_lowercase())
        {
            return Err(err("recovery", "Invalid quarantine path"));
        }
        let dest = safe(root, &q.path)?;
        let backup = safe(op, &format!("backup/{}", q.path))?;
        if backup.is_file() {
            if dest.exists() || fingerprint(&backup, cancel, |_| {})?.1 != q.sha256 {
                return Err(err("recovery", "Quarantined file or destination changed"));
            }
        } else if !dest.is_file() || fingerprint(&dest, cancel, |_| {})?.1 != q.sha256 {
            return Err(err("recovery", "Quarantined original missing or changed"));
        }
    }
    // Validate every recovery file before making any change.
    for c in &j.changes {
        validate_path(&c.entry.path)?;
        let dest = safe(root, &c.entry.path)?;
        let backup = safe(op, &format!("backup/{}", c.entry.path))?;
        if let Some(old) = &c.old_sha256 {
            if backup.exists() {
                if fingerprint(&backup, cancel, |_| {})?.1 != *old {
                    return Err(err("recovery", "Backup changed"));
                }
            } else if !dest.is_file() || fingerprint(&dest, cancel, |_| {})?.1 != *old {
                return Err(err("recovery", "Original missing"));
            }
        } else if dest.exists()
            && fingerprint(&dest, cancel, |_| {})?.1 != c.entry.sha256.to_ascii_lowercase()
        {
            return Err(err("recovery", "New file changed"));
        }
    }
    for c in j.changes.iter().rev() {
        let dest = safe(root, &c.entry.path)?;
        let backup = safe(op, &format!("backup/{}", c.entry.path))?;
        if backup.is_file() {
            if dest.exists() {
                fs::remove_file(&dest)?;
            }
            fs::rename(&backup, &dest)?;
        } else if c.old_sha256.is_none() && dest.exists() {
            fs::remove_file(dest)?;
        }
    }
    for q in j.quarantines.iter().rev() {
        let backup = safe(op, &format!("backup/{}", q.path))?;
        if backup.is_file() {
            fs::rename(backup, safe(root, &q.path)?)?;
        }
    }
    let marker = op.join("restored");
    if !marker.exists() {
        File::create(marker)?.sync_all()?;
    }
    Ok(())
}
fn pending(root: &Path) -> Result<Vec<PathBuf>> {
    let folder = safe(root, ".forever-multi/operations")?;
    if !folder.exists() {
        return Ok(Vec::new());
    }
    let mut ops = Vec::new();
    for e in fs::read_dir(folder)? {
        let p = e?.path();
        if linked(&fs::symlink_metadata(&p)?) {
            return Err(err("path", "linked operation"));
        }
        if p.join("journal.json").exists()
            && !p.join("complete").exists()
            && !p.join("restored").exists()
        {
            ops.push(p);
        }
    }
    Ok(ops)
}

/// Run on a blocking worker with a Tokio handle (hashing and file I/O are synchronous).
pub async fn run(
    req: Request,
    state_dir: PathBuf,
    cancel: &AtomicBool,
    emit: impl Fn(Progress),
) -> Result<Report> {
    if !matches!(
        req.action.as_str(),
        "verify" | "download" | "repair" | "recover"
    ) {
        return Err(err("action", &req.action));
    }
    let modifying = req.action != "verify";
    let target = root(&req.game_dir, modifying)?;
    fs::create_dir_all(state_dir.join("locks"))?;
    let lock = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .open(
            state_dir
                .join("locks")
                .join(sha(target.to_string_lossy().as_bytes())),
        )?;
    lock.try_lock_exclusive().map_err(|_| err("busy", ""))?;
    let recovery = pending(&target)?;
    if !recovery.is_empty() {
        if req.action != "recover" {
            return Err(err("recovery", recovery[0].display()));
        }
        let no_cancel = AtomicBool::new(false);
        for op in &recovery {
            restore(&target, op, &no_cancel)?;
        }
        let report_dir = state_dir.join("reports");
        fs::create_dir_all(&report_dir)?;
        let path = report_dir.join(format!("recovered-{:016x}.json", rand::random::<u64>()));
        let report = Report {
            action: "recover".into(),
            source_kind: "recovery",
            profile: read_profile(&target).unwrap_or(Profile {
                product: String::new(),
                version: String::new(),
                build_key: String::new(),
            }),
            files: 0,
            comparison_only: false,
            target_executable_version: None,
            reference_executable_version: None,
            verified: 0,
            different: 0,
            resource_different: 0,
            storage_different: 0,
            remaining: 0,
            repaired: 0,
            quarantined: 0,
            extra_storage_files: Vec::new(),
            bytes: 0,
            differences: Vec::new(),
            report_path: path.to_string_lossy().into_owned(),
            backup: None,
            target_root: display_path(&target),
            reference_root: None,
            scope: "Interrupted operation rolled back; run Verify to compare the restored baseline",
        };
        json(&path, &report)?;
        return Ok(report);
    } else if req.action == "recover" {
        return Err(err("recovery", "No interrupted operation"));
    }
    let http = http_client()?;
    let mut reference_stamp = None;
    let (m, reference, source_kind) = if !req.source.manifest_source.trim().is_empty() {
        (
            load_manifest(req.source.manifest_source.trim(), &http, cancel).await?,
            None,
            "manifest",
        )
    } else if !req.source.reference_dir.trim().is_empty() {
        let source = root(&req.source.reference_dir, false)?;
        if target.starts_with(&source) || source.starts_with(&target) {
            return Err(err("overlap", ""));
        }
        let p = read_profile(&source)?;
        // Report an incompatible source before spending minutes hashing it.
        if safe(&target, ".build.info")?.is_file() && read_profile(&target)? != p {
            return Err(err("version", p.version));
        }
        let stamp = storage_stamp(&source)?;
        let files = inventory(&source, &p, cancel, &emit)?;
        unchanged_storage(&source, &stamp)?;
        reference_stamp = Some(stamp);
        (
            Manifest {
                format: "forever-multi-client-v1".into(),
                profile: p,
                files,
            },
            Some(source),
            "reference",
        )
    } else {
        return Err(err("source", ""));
    };
    validate(&m)?;
    if safe(&target, ".build.info")?.is_file() && read_profile(&target)? != m.profile {
        return Err(err("version", m.profile.version));
    }
    let quarantines = extra_storage(&target, &m, cancel)?;
    let total = m.files.iter().try_fold(0u64, |s, e| {
        s.checked_add(e.bytes)
            .ok_or_else(|| err("manifest", "size overflow"))
    })?;
    let count = m.files.len();
    let mut done = 0;
    let mut changes = Vec::new();
    let timer = Instant::now();
    for (i, e) in m.files.iter().enumerate() {
        check_cancel(cancel)?;
        let dest = safe(&target, &e.path)?;
        let old = if dest.is_file() {
            Some(fingerprint(&dest, cancel, |n| {
                done += n;
                emit(Progress {
                    phase: "verify",
                    path: e.path.clone(),
                    files_done: i,
                    files_total: count,
                    bytes_done: done,
                    bytes_total: total,
                    bytes_per_second: (done as f64 / timer.elapsed().as_secs_f64().max(0.1)) as u64,
                });
            })?)
        } else if dest.exists() {
            return Err(err("path", &e.path));
        } else {
            None
        };
        if old
            .as_ref()
            .is_none_or(|(bytes, hash)| *bytes != e.bytes || !hash.eq_ignore_ascii_case(&e.sha256))
        {
            changes.push(Change {
                entry: e.clone(),
                old_sha256: old.map(|v| v.1),
            });
        }
        // Missing files have no bytes to hash, but still advance the checked-file counter.
        emit(Progress {
            phase: "verify",
            path: e.path.clone(),
            files_done: i + 1,
            files_total: count,
            bytes_done: done.min(total),
            bytes_total: total,
            bytes_per_second: 0,
        });
    }
    let mut backup = None;
    if let (Some(source), Some(stamp)) = (&reference, &reference_stamp) {
        unchanged_storage(source, stamp)?;
    }
    if modifying && (!changes.is_empty() || !quarantines.is_empty()) {
        let required = changes.iter().map(|c| c.entry.bytes).sum::<u64>();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        // Stable staging paths allow a cancelled HTTP transfer to resume next time.
        let stage = safe(
            &target,
            &format!(".forever-multi/staging/{}", sha(&serde_json::to_vec(&m)?)),
        )?;
        let remaining = changes.iter().try_fold(0u64, |sum, c| -> Result<u64> {
            let partial = safe(&stage, &c.entry.path)?;
            let have = match fs::metadata(partial) {
                Ok(meta) => meta.len().min(c.entry.bytes),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => 0,
                Err(e) => return Err(e.into()),
            };
            Ok(sum.saturating_add(c.entry.bytes - have))
        })?;
        if fs2::available_space(&target)? < remaining.saturating_add(8 * 1024 * 1024) {
            return Err(err("space", remaining));
        }
        fs::create_dir_all(&stage)?;
        done = 0;
        let timer = Instant::now();
        for (i, c) in changes.iter().enumerate() {
            check_cancel(cancel)?;
            let e = &c.entry;
            let part = safe(&stage, &e.path)?;
            fs::create_dir_all(part.parent().unwrap())?;
            let mut cb = |n| {
                done += n;
                emit(Progress {
                    phase: if reference.is_some() {
                        "copy"
                    } else {
                        "download"
                    },
                    path: e.path.clone(),
                    files_done: i,
                    files_total: changes.len(),
                    bytes_done: done,
                    bytes_total: required,
                    bytes_per_second: (done as f64 / timer.elapsed().as_secs_f64().max(0.1)) as u64,
                });
            };
            if let Some(refroot) = &reference {
                copy(&safe(refroot, &e.path)?, &part, e, cancel, &mut cb)?;
            } else {
                download(&http, e, &part, cancel, &mut cb).await?;
            }
        }
        let info = if stage.join(".build.info").is_file() {
            &stage
        } else {
            &target
        };
        if read_profile(info)? != m.profile {
            return Err(err("version", "Downloaded metadata differs from manifest"));
        }
        check_cancel(cancel)?;
        if let (Some(source), Some(stamp)) = (&reference, &reference_stamp) {
            unchanged_storage(source, stamp)?;
        }
        if extra_storage(&target, &m, cancel)? != quarantines {
            return Err(err(
                "changed",
                "Target CASC metadata changed while preparing recovery",
            ));
        }
        // Metadata is published after payloads. Recovery metadata is synced BEFORE any rename.
        changes.sort_by_key(|c| {
            (
                if c.entry.path == ".build.info" {
                    3
                } else if storage_metadata(&c.entry.path) {
                    2
                } else {
                    1
                },
                c.entry.path.clone(),
            )
        });
        let op = safe(
            &target,
            &format!(
                ".forever-multi/operations/{stamp}-{:016x}",
                rand::random::<u64>()
            ),
        )?;
        fs::create_dir_all(&op)?;
        let j = Journal {
            format: "forever-multi-recovery-v2".into(),
            root: target.to_string_lossy().into_owned(),
            phase: "committing".into(),
            changes: changes.clone(),
            quarantines: quarantines.clone(),
        };
        json(&op.join("journal.json"), &j)?;
        let no_cancel = AtomicBool::new(false);
        let commit = (|| -> Result<()> {
            for q in &quarantines {
                let dest = safe(&target, &q.path)?;
                if fingerprint(&dest, &no_cancel, |_| {})?.1 != q.sha256 {
                    return Err(err("changed", &q.path));
                }
                let b = safe(&op, &format!("backup/{}", q.path))?;
                fs::create_dir_all(b.parent().unwrap())?;
                fs::rename(dest, b)?;
                emit(Progress {
                    phase: "commit",
                    path: q.path.clone(),
                    files_done: 0,
                    files_total: changes.len() + quarantines.len(),
                    bytes_done: required,
                    bytes_total: required,
                    bytes_per_second: 0,
                });
            }
            for (i, c) in changes.iter().enumerate() {
                let dest = safe(&target, &c.entry.path)?;
                fs::create_dir_all(dest.parent().unwrap())?;
                if let Some(old) = &c.old_sha256 {
                    if fingerprint(&dest, &no_cancel, |_| {})?.1 != *old {
                        return Err(err("changed", &c.entry.path));
                    }
                    let b = safe(&op, &format!("backup/{}", c.entry.path))?;
                    fs::create_dir_all(b.parent().unwrap())?;
                    fs::rename(&dest, b)?;
                } else if dest.exists() {
                    return Err(err("changed", &c.entry.path));
                }
                fs::rename(safe(&stage, &c.entry.path)?, &dest)?;
                if fingerprint(&dest, &no_cancel, |_| {})?.1 != c.entry.sha256.to_ascii_lowercase()
                {
                    return Err(err("integrity", &c.entry.path));
                }
                emit(Progress {
                    phase: "commit",
                    path: c.entry.path.clone(),
                    files_done: i + 1 + quarantines.len(),
                    files_total: changes.len() + quarantines.len(),
                    bytes_done: required,
                    bytes_total: required,
                    bytes_per_second: 0,
                });
            }
            File::create(op.join("complete"))?.sync_all()?;
            Ok(())
        })();
        if let Err(e) = commit {
            if let Err(recovery) = restore(&target, &op, &no_cancel) {
                return Err(err(
                    "recovery",
                    format!("{}; {}", e.detail, recovery.detail),
                ));
            }
            return Err(e);
        }
        backup = Some(op.to_string_lossy().into_owned());
    }
    let report_folder = state_dir.join("reports");
    fs::create_dir_all(&report_folder)?;
    let report_path = report_folder.join(format!("client-{:016x}.json", rand::random::<u64>()));
    let repaired = if modifying { changes.len() } else { 0 };
    let storage_different = changes
        .iter()
        .filter(|c| storage_metadata(&c.entry.path))
        .count();
    let quarantined = if modifying { quarantines.len() } else { 0 };
    let comparison_only = !modifying;
    let report=Report{action:req.action,source_kind,profile:m.profile,files:count,
        comparison_only,target_executable_version:executable_version(&target),
        reference_executable_version:reference.as_deref().and_then(executable_version),
        verified:count-changes.len()+repaired,different:changes.len()+quarantines.len(),resource_different:changes.len()-storage_different,storage_different:storage_different+quarantines.len(),remaining:changes.len()+quarantines.len()-repaired-quarantined,repaired:repaired+quarantined,quarantined,extra_storage_files:quarantines.iter().map(|q|q.path.clone()).collect(),bytes:total,differences:changes.iter().map(|c|c.entry.path.clone()).chain(quarantines.iter().map(|q|q.path.clone())).take(200).collect(),report_path:report_path.to_string_lossy().into_owned(),backup,target_root:display_path(&target),reference_root:reference.as_deref().map(display_path),
        scope:if comparison_only { "Read-only comparison against a baseline; no game payloads copied or quarantined. Differences do not establish CASC corruption, download completeness or server compatibility." }
        else { "Explicit baseline replacement; recognized surplus CASC metadata quarantined; not CASC object validation or a client/server version upgrade" }};
    json(&report_path, &report)?;
    emit(Progress {
        phase: "done",
        path: String::new(),
        files_done: count,
        files_total: count,
        bytes_done: total,
        bytes_total: total,
        bytes_per_second: 0,
    });
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture {
        dir: PathBuf,
        source: PathBuf,
        target: PathBuf,
        state: PathBuf,
    }
    impl Fixture {
        fn new() -> Self {
            let dir =
                std::env::temp_dir().join(format!("fm-workshop-{:016x}", rand::random::<u64>()));
            let source = dir.join("original");
            let target = dir.join("copy");
            let state = dir.join("state");
            for base in [&source, &target] {
                fs::create_dir_all(base.join("Data/config/aa/bb")).unwrap();
                fs::create_dir_all(base.join("Data/data")).unwrap();
                fs::create_dir_all(base.join("_forever_/WTF")).unwrap();
                fs::create_dir_all(base.join("_forever_/Interface/AddOns")).unwrap();
                fs::write(base.join(".build.info"),"Product!STRING:0|Active!DEC:1|Version!STRING:0|Build Key!HEX:16\nwowf|1|1.60.1.70658|165410aca770316ea0f88100bb4830c2\n").unwrap();
                fs::write(
                    base.join("_forever_/Wow.exe"),
                    b"synthetic owned executable",
                )
                .unwrap();
                fs::write(base.join("Data/data/data.000"), b"correct payload").unwrap();
                fs::write(base.join("Data/config/aa/bb/config"), b"synthetic config").unwrap();
                fs::write(base.join("_forever_/WTF/Config.wtf"), b"user settings").unwrap();
                fs::write(
                    base.join("_forever_/Interface/AddOns/own.lua"),
                    b"user addon",
                )
                .unwrap();
            }
            Self {
                dir,
                source,
                target,
                state,
            }
        }
        fn request(&self, action: &str) -> Request {
            Request {
                action: action.into(),
                game_dir: self.target.join("_forever_").to_string_lossy().into_owned(),
                source: Settings {
                    reference_dir: self.source.to_string_lossy().into_owned(),
                    manifest_source: String::new(),
                },
            }
        }
        async fn run(&self, action: &str) -> Result<Report> {
            run(
                self.request(action),
                self.state.clone(),
                &AtomicBool::new(false),
                |_| {},
            )
            .await
        }
        fn full_index_baseline(&self) {
            for base in [&self.source, &self.target] {
                for bucket in 0..16 {
                    fs::write(
                        base.join(format!("Data/data/{bucket:02x}00000325.idx")),
                        format!("synthetic bucket {bucket}"),
                    )
                    .unwrap();
                }
            }
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }
    #[tokio::test]
    async fn surplus_casc_generations_are_backed_up_with_payload_recovery_and_unrelated_extras_survive(
    ) {
        let f = Fixture::new();
        f.full_index_baseline();
        let extra = ["000000032c.idx", "0000000000000001.lru", "RepairMarker.psv"];
        for name in extra {
            fs::write(f.target.join("Data/data").join(name), name).unwrap();
        }
        fs::write(f.target.join("Data/data/0000000325.idx"), b"broken index").unwrap();
        fs::write(f.target.join("Data/data/data.000"), b"broken archive").unwrap();
        fs::write(
            f.target.join("Data/data/data.999"),
            b"unrelated extra archive",
        )
        .unwrap();
        fs::write(f.target.join("Data/data/notes.txt"), b"user file").unwrap();
        let before = f.run("verify").await.unwrap();
        assert_eq!(
            (
                before.different,
                before.storage_different,
                before.resource_different,
                before.remaining,
                before.quarantined
            ),
            (5, 4, 1, 5, 0)
        );
        for name in extra {
            assert!(f.target.join("Data/data").join(name).exists());
        }
        let repaired = f.run("repair").await.unwrap();
        assert_eq!(
            (
                repaired.different,
                repaired.repaired,
                repaired.quarantined,
                repaired.remaining
            ),
            (5, 5, 3, 0)
        );
        assert_eq!(repaired.verified, repaired.files);
        for name in extra {
            assert!(!f.target.join("Data/data").join(name).exists());
            assert_eq!(
                fs::read(
                    Path::new(repaired.backup.as_ref().unwrap())
                        .join("backup/Data/data")
                        .join(name)
                )
                .unwrap(),
                name.as_bytes()
            );
        }
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"correct payload"
        );
        assert_eq!(
            fs::read(f.target.join("Data/data/data.999")).unwrap(),
            b"unrelated extra archive"
        );
        assert_eq!(
            fs::read(f.target.join("Data/data/notes.txt")).unwrap(),
            b"user file"
        );
        assert_eq!(f.run("verify").await.unwrap().different, 0);
        assert!(!f.source.join("Data/data/RepairMarker.psv").exists());
        assert_eq!(
            fs::read(f.source.join("Data/data/0000000325.idx")).unwrap(),
            b"synthetic bucket 0"
        );
    }
    #[tokio::test]
    async fn quarantine_only_repair_is_not_skipped_when_all_expected_files_match() {
        let f = Fixture::new();
        f.full_index_baseline();
        fs::write(
            f.target.join("Data/data/000000032c.idx"),
            b"stale generation",
        )
        .unwrap();
        let r = f.run("repair").await.unwrap();
        assert_eq!(
            (r.different, r.repaired, r.quarantined, r.remaining),
            (1, 1, 1, 0)
        );
        assert_eq!(r.verified, r.files);
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"correct payload"
        );
    }
    #[tokio::test]
    async fn failed_payload_replacement_restores_both_quarantined_metadata_and_old_archive() {
        let f = Fixture::new();
        f.full_index_baseline();
        let extra = f.target.join("Data/data/000000032c.idx");
        fs::write(&extra, b"previous index").unwrap();
        fs::write(f.target.join("Data/data/data.000"), b"previous archive").unwrap();
        let result = run(
            f.request("repair"),
            f.state.clone(),
            &AtomicBool::new(false),
            |p| {
                if p.phase == "commit" && p.files_done == 0 {
                    // A staged file disappears after quarantine: the transaction must roll back both kinds of changes.
                    for entry in fs::read_dir(f.target.join(".forever-multi/staging")).unwrap() {
                        let file = entry.unwrap().path().join("Data/data/data.000");
                        if file.exists() {
                            fs::remove_file(file).unwrap();
                        }
                    }
                }
            },
        )
        .await;
        assert_eq!(result.err().unwrap().code, "io");
        assert_eq!(fs::read(extra).unwrap(), b"previous index");
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"previous archive"
        );
        assert!(pending(&f.target.canonicalize().unwrap())
            .unwrap()
            .is_empty());
    }
    #[tokio::test]
    async fn refuses_quarantine_from_incomplete_or_repair_marked_original() {
        let f = Fixture::new();
        fs::write(
            f.target.join("Data/data/000000032c.idx"),
            b"keep until proper baseline",
        )
        .unwrap();
        assert_eq!(
            f.run("repair").await.err().unwrap().code,
            "storage_baseline"
        );
        assert!(!f.target.join(".forever-multi").exists());
        f.full_index_baseline();
        fs::write(
            f.source.join("Data/data/RepairMarker.psv"),
            b"source needs repair",
        )
        .unwrap();
        assert_eq!(
            f.run("repair").await.err().unwrap().code,
            "storage_baseline"
        );
        assert!(f.target.join("Data/data/000000032c.idx").exists());
        assert!(!f.target.join(".forever-multi").exists());
    }
    #[tokio::test]
    async fn changing_original_storage_or_late_target_generation_aborts_before_commit() {
        let f = Fixture::new();
        f.full_index_baseline();
        fs::write(f.target.join("Data/data/data.000"), b"previous archive").unwrap();
        let result = run(
            f.request("repair"),
            f.state.clone(),
            &AtomicBool::new(false),
            |p| {
                if p.phase == "verify" && p.files_done == p.files_total {
                    fs::write(
                        f.source.join("Data/data/data.000"),
                        b"original changed while planning",
                    )
                    .unwrap();
                }
            },
        )
        .await;
        assert_eq!(result.err().unwrap().code, "changed");
        assert!(!f.target.join(".forever-multi").exists());
        let result = run(
            f.request("repair"),
            f.state.clone(),
            &AtomicBool::new(false),
            |p| {
                if p.phase == "verify" && p.files_done == p.files_total {
                    fs::write(
                        f.target.join("Data/data/000000032c.idx"),
                        b"new concurrent generation",
                    )
                    .unwrap();
                }
            },
        )
        .await;
        assert_eq!(result.err().unwrap().code, "changed");
        assert!(!f.target.join(".forever-multi/operations").exists());
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"previous archive"
        );
    }
    #[test]
    fn interrupted_v2_quarantine_can_recover_without_source_and_old_journals_remain_readable() {
        let f = Fixture::new();
        let root = f.target.canonicalize().unwrap();
        let path = "Data/data/000000032c.idx";
        fs::write(root.join(path), b"previous generation").unwrap();
        let op = root.join(".forever-multi/operations/interrupted-quarantine");
        fs::create_dir_all(op.join("backup/Data/data")).unwrap();
        let j = Journal {
            format: "forever-multi-recovery-v2".into(),
            root: root.to_string_lossy().into_owned(),
            phase: "committing".into(),
            changes: Vec::new(),
            quarantines: vec![Quarantine {
                path: path.into(),
                sha256: sha(b"previous generation"),
            }],
        };
        json(&op.join("journal.json"), &j).unwrap();
        fs::rename(root.join(path), op.join("backup").join(path)).unwrap();
        restore(&root, &op, &AtomicBool::new(false)).unwrap();
        assert_eq!(fs::read(root.join(path)).unwrap(), b"previous generation");
        let legacy: Journal = serde_json::from_value(serde_json::json!({"format":"forever-multi-recovery-v1","root":root,"phase":"committing","changes":[]})).unwrap();
        assert!(legacy.quarantines.is_empty());
    }
    #[test]
    fn resolves_game_subfolder_to_shared_data_without_hashing_or_changing_files() {
        let f = Fixture::new();
        let root = locations(f.target.to_str().unwrap(), f.source.to_str().unwrap()).unwrap();
        let game = locations(
            f.target.join("_forever_").to_str().unwrap(),
            f.source.join("_forever_").to_str().unwrap(),
        )
        .unwrap();
        assert_eq!(root.target_root, game.target_root);
        assert_eq!(
            root.target_data,
            display_path(&f.target.canonicalize().unwrap().join("Data"))
        );
        assert_eq!(root.reference_root, game.reference_root);
        assert_eq!(root.reference_data, game.reference_data);
        assert!(!f.target.join(".forever-multi").exists());
        assert!(!f.state.exists());
    }
    #[tokio::test]
    async fn storage_differences_remain_strictly_checked_and_repaired_but_reported_separately() {
        let f = Fixture::new();
        for name in ["0000000325.idx", "cache.lru", "shmem"] {
            fs::write(
                f.source.join("Data/data").join(name),
                b"original bookkeeping",
            )
            .unwrap();
            fs::write(
                f.target.join("Data/data").join(name),
                b"updated bookkeeping",
            )
            .unwrap();
        }
        fs::write(f.target.join("Data/data/data.000"), b"broken payload").unwrap();
        let before = f.run("verify").await.unwrap();
        assert_eq!(
            (
                before.different,
                before.resource_different,
                before.storage_different,
                before.remaining
            ),
            (4, 1, 3, 4)
        );
        let repaired = f.run("repair").await.unwrap();
        assert_eq!(
            (repaired.different, repaired.repaired, repaired.remaining),
            (4, 4, 0)
        );
        assert_eq!(
            (repaired.resource_different, repaired.storage_different),
            (1, 3)
        );
        assert_eq!(f.run("verify").await.unwrap().different, 0);
        // An index-like name outside the local bookkeeping directory is still a resource difference.
        assert!(!storage_metadata("Data/config/example.idx"));
        assert!(!storage_metadata("Data/data/nested/example.idx"));
        assert!(!storage_metadata("Data/data/data.000"));
    }
    #[tokio::test]
    async fn hashes_detect_equal_length_corruption_and_verification_leaves_client_untouched() {
        let f = Fixture::new();
        fs::write(f.target.join("Data/data/data.000"), b"corrupt payload").unwrap();
        let r = f.run("verify").await.unwrap();
        assert_eq!(r.files, 4);
        assert_eq!(r.different, 1);
        assert_eq!(r.repaired, 0);
        assert_eq!(r.differences, vec!["Data/data/data.000"]);
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"corrupt payload"
        );
        assert!(!f.target.join(".forever-multi").exists());
        assert!(Path::new(&r.report_path).is_file());
    }
    #[tokio::test]
    async fn local_repair_retains_original_backup_and_preserves_user_files() {
        let f = Fixture::new();
        fs::write(f.target.join("Data/data/data.000"), b"broken").unwrap();
        fs::write(
            f.target.join("_forever_/WTF/Config.wtf"),
            b"keep my settings",
        )
        .unwrap();
        fs::write(
            f.target.join("_forever_/Interface/AddOns/own.lua"),
            b"keep my addon",
        )
        .unwrap();
        fs::write(f.target.join("Data/data/extra"), b"keep extra").unwrap();
        let r = f.run("repair").await.unwrap();
        assert_eq!(r.repaired, 1);
        assert_eq!(r.verified, 4);
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"correct payload"
        );
        assert_eq!(
            fs::read(f.target.join("_forever_/WTF/Config.wtf")).unwrap(),
            b"keep my settings"
        );
        assert_eq!(
            fs::read(f.target.join("_forever_/Interface/AddOns/own.lua")).unwrap(),
            b"keep my addon"
        );
        assert!(f.target.join("Data/data/extra").exists());
        let op = Path::new(r.backup.as_ref().unwrap());
        assert_eq!(
            fs::read(op.join("backup/Data/data/data.000")).unwrap(),
            b"broken"
        );
        assert!(op.join("complete").exists());
        assert!(pending(&f.target.canonicalize().unwrap())
            .unwrap()
            .is_empty());
        assert_eq!(f.run("verify").await.unwrap().different, 0);
    }
    #[tokio::test]
    async fn different_build_is_refused_before_any_repair() {
        let f = Fixture::new();
        let p = f.target.join(".build.info");
        let s = fs::read_to_string(&p).unwrap();
        fs::write(p, s.replace("70658", "70790")).unwrap();
        assert_eq!(f.run("repair").await.err().unwrap().code, "version");
        assert!(!f.target.join(".forever-multi").exists());
    }
    #[tokio::test]
    async fn source_and_target_cannot_overlap() {
        let f = Fixture::new();
        let mut req = f.request("repair");
        req.source.reference_dir = f.target.to_string_lossy().into_owned();
        assert_eq!(
            run(req, f.state.clone(), &AtomicBool::new(false), |_| {})
                .await
                .err()
                .unwrap()
                .code,
            "overlap"
        );
    }
    #[tokio::test]
    async fn cancellation_during_staging_never_changes_live_files() {
        let f = Fixture::new();
        fs::write(f.target.join("Data/data/data.000"), b"broken").unwrap();
        let cancel = AtomicBool::new(false);
        let r = run(f.request("repair"), f.state.clone(), &cancel, |p| {
            if p.phase == "verify" && p.files_done == p.files_total {
                cancel.store(true, Ordering::Relaxed)
            }
        })
        .await;
        assert_eq!(r.err().unwrap().code, "cancelled");
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"broken"
        );
    }
    #[tokio::test]
    async fn interrupted_commit_is_detected_and_can_restore_pre_operation_data() {
        let f = Fixture::new();
        let root = f.target.canonicalize().unwrap();
        let path = "Data/data/data.000";
        let dest = root.join(path);
        let old = fs::read(&dest).unwrap();
        let op = root.join(".forever-multi/operations/synthetic");
        fs::create_dir_all(op.join("backup/Data/data")).unwrap();
        let j = Journal {
            format: "forever-multi-recovery-v1".into(),
            root: root.to_string_lossy().into_owned(),
            phase: "committing".into(),
            quarantines: Vec::new(),
            changes: vec![Change {
                entry: Entry {
                    path: path.into(),
                    bytes: 3,
                    sha256: sha(b"new"),
                    url: None,
                },
                old_sha256: Some(sha(&old)),
            }],
        };
        json(&op.join("journal.json"), &j).unwrap();
        fs::rename(&dest, op.join("backup").join(path)).unwrap();
        fs::write(&dest, b"new").unwrap();
        assert_eq!(f.run("verify").await.err().unwrap().code, "recovery");
        restore(&root, &op, &AtomicBool::new(false)).unwrap();
        assert_eq!(fs::read(dest).unwrap(), old);
        assert!(pending(&root).unwrap().is_empty());
    }
    #[test]
    fn manifest_paths_reject_traversal_user_settings_and_windows_aliases() {
        for p in [
            "../Wow.exe",
            "Data/../../outside",
            "/Data/file",
            "Data/CON",
            "Data/foo:bar",
            "Data/file.",
            "_forever_/WTF/Config.wtf",
            "_forever_/Interface/AddOns/a",
            "Data/a\\b",
            "Data/NUL.txt",
            "Data/.forever-multi/x",
        ] {
            assert!(validate_path(p).is_err(), "{p}");
        }
        assert!(validate_path("Data/data/data.001").is_ok());
        assert!(validate_path("_forever_/Wow.exe").is_ok());
    }
    #[test]
    fn incomplete_or_mixed_product_manifests_are_not_accepted() {
        let f = Fixture::new();
        let p = read_profile(&f.source).unwrap();
        let mut m = Manifest {
            format: "forever-multi-client-v1".into(),
            profile: p,
            files: inventory(
                &f.source,
                &read_profile(&f.source).unwrap(),
                &AtomicBool::new(false),
                &|_| {},
            )
            .unwrap(),
        };
        validate(&m).unwrap();
        m.files.push(m.files[0].clone());
        assert!(validate(&m).is_err());
        m.files.pop();
        m.files.retain(|e| e.path != ".build.info");
        assert!(validate(&m).is_err());
    }
    #[cfg(unix)]
    #[test]
    fn symlink_destination_is_refused() {
        let f = Fixture::new();
        let dest = f.target.join("Data/data/data.000");
        fs::remove_file(&dest).unwrap();
        std::os::unix::fs::symlink(f.source.join("Data/data/data.000"), &dest).unwrap();
        assert!(safe(&f.target, "Data/data/data.000").is_err());
    }
    async fn serve_once(
        payload: Vec<u8>,
        expect_range: bool,
        status: &'static str,
        range: Option<&'static str>,
    ) -> (String, std::thread::JoinHandle<()>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let h = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut buf = [0u8; 4096];
            let n = stream.read(&mut buf).unwrap();
            let s = String::from_utf8_lossy(&buf[..n]);
            if expect_range {
                assert!(s.to_ascii_lowercase().contains("range: bytes=4-"), "{s}");
            }
            let mut headers = format!(
                "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n",
                payload.len()
            );
            if let Some(r) = range {
                headers.push_str(&format!("Content-Range: {r}\r\n"));
            }
            headers.push_str("\r\n");
            stream.write_all(headers.as_bytes()).unwrap();
            stream.write_all(&payload).unwrap();
        });
        (format!("http://{address}/file"), h)
    }
    #[tokio::test]
    async fn http_download_resumes_and_verifies_content() {
        let f = Fixture::new();
        let data = b"a complete download";
        let part = f.dir.join("partial");
        fs::write(&part, &data[..4]).unwrap();
        let (u, h) = serve_once(
            data[4..].to_vec(),
            true,
            "206 Partial Content",
            Some("bytes 4-18/19"),
        )
        .await;
        let e = Entry {
            path: "Data/data/data.000".into(),
            bytes: data.len() as u64,
            sha256: sha(data),
            url: Some(u),
        };
        download(
            &http_client().unwrap(),
            &e,
            &part,
            &AtomicBool::new(false),
            |_| {},
        )
        .await
        .unwrap();
        h.join().unwrap();
        assert_eq!(fs::read(part).unwrap(), data);
    }
    #[tokio::test]
    async fn http_server_ignoring_range_restarts_instead_of_appending() {
        let f = Fixture::new();
        let data = b"a complete download";
        let part = f.dir.join("partial");
        fs::write(&part, &data[..4]).unwrap();
        let (u, h) = serve_once(data.to_vec(), true, "200 OK", None).await;
        let e = Entry {
            path: "Data/data/data.000".into(),
            bytes: data.len() as u64,
            sha256: sha(data),
            url: Some(u),
        };
        download(
            &http_client().unwrap(),
            &e,
            &part,
            &AtomicBool::new(false),
            |_| {},
        )
        .await
        .unwrap();
        h.join().unwrap();
        assert_eq!(fs::read(part).unwrap(), data);
    }
    #[tokio::test]
    async fn corrupt_http_data_is_discarded_and_wrong_range_is_rejected() {
        let f = Fixture::new();
        let part = f.dir.join("partial");
        let (u, h) = serve_once(b"bad".to_vec(), false, "200 OK", None).await;
        let e = Entry {
            path: "Data/data/data.000".into(),
            bytes: 3,
            sha256: sha(b"yes"),
            url: Some(u),
        };
        assert_eq!(
            download(
                &http_client().unwrap(),
                &e,
                &part,
                &AtomicBool::new(false),
                |_| {}
            )
            .await
            .err()
            .unwrap()
            .code,
            "integrity"
        );
        h.join().unwrap();
        assert!(!part.exists());
        fs::write(&part, b"abcd").unwrap();
        let (u, h) = serve_once(
            b"zz".to_vec(),
            true,
            "206 Partial Content",
            Some("bytes 0-1/6"),
        )
        .await;
        let e = Entry {
            bytes: 6,
            url: Some(u),
            ..e
        };
        assert_eq!(
            download(
                &http_client().unwrap(),
                &e,
                &part,
                &AtomicBool::new(false),
                |_| {}
            )
            .await
            .err()
            .unwrap()
            .code,
            "network"
        );
        h.join().unwrap();
        assert_eq!(fs::read(&part).unwrap(), b"abcd");
    }
    #[tokio::test]
    async fn installation_into_new_folder_publishes_metadata_and_keeps_original_unchanged() {
        let f = Fixture::new();
        let mut req = f.request("download");
        let fresh = f.dir.join("fresh");
        req.game_dir = fresh.join("_forever_").to_string_lossy().into_owned();
        let r = run(req, f.state.clone(), &AtomicBool::new(false), |_| {})
            .await
            .unwrap();
        assert_eq!(r.repaired, 4);
        assert_eq!(
            read_profile(&fresh).unwrap(),
            read_profile(&f.source).unwrap()
        );
        assert_eq!(
            fs::read(fresh.join("Data/data/data.000")).unwrap(),
            b"correct payload"
        );
        assert!(!fresh.join("_forever_/WTF").exists());
        assert_eq!(
            fs::read(f.source.join("_forever_/WTF/Config.wtf")).unwrap(),
            b"user settings"
        );
    }
    #[tokio::test]
    async fn failed_manifest_transfer_does_not_replace_any_live_file() {
        let f = Fixture::new();
        fs::write(f.target.join("Data/data/data.000"), b"broken").unwrap();
        let files = inventory(
            &f.source,
            &read_profile(&f.source).unwrap(),
            &AtomicBool::new(false),
            &|_| {},
        )
        .unwrap();
        let (u, h) = serve_once(vec![b'x'; 15], false, "200 OK", None).await;
        let m = Manifest {
            format: "forever-multi-client-v1".into(),
            profile: read_profile(&f.source).unwrap(),
            files: files
                .into_iter()
                .map(|e| Entry {
                    url: Some(u.clone()),
                    ..e
                })
                .collect(),
        };
        let path = f.dir.join("manifest.json");
        json(&path, &m).unwrap();
        let mut req = f.request("download");
        req.source.manifest_source = path.to_string_lossy().into_owned();
        req.source.reference_dir.clear();
        let error = run(req, f.state.clone(), &AtomicBool::new(false), |_| {})
            .await
            .err()
            .unwrap();
        h.join().unwrap();
        assert_eq!(error.code, "integrity");
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"broken"
        );
        assert!(pending(&f.target).unwrap().is_empty());
    }
    #[tokio::test]
    async fn manifest_download_restores_only_the_changed_file_and_retains_backup() {
        let f = Fixture::new();
        fs::write(f.target.join("Data/data/data.000"), b"broken").unwrap();
        let files = inventory(
            &f.source,
            &read_profile(&f.source).unwrap(),
            &AtomicBool::new(false),
            &|_| {},
        )
        .unwrap();
        let (u, h) = serve_once(b"correct payload".to_vec(), false, "200 OK", None).await;
        let m = Manifest {
            format: "forever-multi-client-v1".into(),
            profile: read_profile(&f.source).unwrap(),
            files: files
                .into_iter()
                .map(|e| Entry {
                    url: Some(u.clone()),
                    ..e
                })
                .collect(),
        };
        let path = f.dir.join("manifest.json");
        json(&path, &m).unwrap();
        let mut req = f.request("download");
        req.source.manifest_source = path.to_string_lossy().into_owned();
        req.source.reference_dir.clear();
        let r = run(req, f.state.clone(), &AtomicBool::new(false), |_| {})
            .await
            .unwrap();
        h.join().unwrap();
        assert_eq!(r.source_kind, "manifest");
        assert_eq!(r.repaired, 1);
        assert_eq!(
            fs::read(f.target.join("Data/data/data.000")).unwrap(),
            b"correct payload"
        );
        assert_eq!(
            fs::read(Path::new(r.backup.as_ref().unwrap()).join("backup/Data/data/data.000"))
                .unwrap(),
            b"broken"
        );
    }
    #[tokio::test]
    async fn cancellation_interrupts_a_server_that_never_sends_headers() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel::<()>();
        let server = std::thread::spawn(move || {
            let (_stream, _) = listener.accept().unwrap();
            let _ = rx.recv_timeout(Duration::from_secs(3));
        });
        let cancel = AtomicBool::new(false);
        let client = http_client().unwrap();
        let request = client.get(format!("http://{address}/waiting"));
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            tokio::join!(send(request, &cancel), async {
                tokio::time::sleep(Duration::from_millis(150)).await;
                cancel.store(true, Ordering::Relaxed);
            })
            .0
        })
        .await
        .unwrap();
        tx.send(()).unwrap();
        server.join().unwrap();
        assert_eq!(result.err().unwrap().code, "cancelled");
    }
    #[tokio::test]
    async fn recovery_works_without_the_original_download_source() {
        let f = Fixture::new();
        let root = f.target.canonicalize().unwrap();
        let path = "Data/data/data.000";
        let old = fs::read(root.join(path)).unwrap();
        let op = root.join(".forever-multi/operations/interrupted");
        fs::create_dir_all(op.join("backup/Data/data")).unwrap();
        let j = Journal {
            format: "forever-multi-recovery-v1".into(),
            root: root.to_string_lossy().into_owned(),
            phase: "committing".into(),
            quarantines: Vec::new(),
            changes: vec![Change {
                entry: Entry {
                    path: path.into(),
                    bytes: 3,
                    sha256: sha(b"new"),
                    url: None,
                },
                old_sha256: Some(sha(&old)),
            }],
        };
        json(&op.join("journal.json"), &j).unwrap();
        fs::rename(root.join(path), op.join("backup").join(path)).unwrap();
        fs::write(root.join(path), b"new").unwrap();
        let mut req = f.request("recover");
        req.source = Settings {
            reference_dir: String::new(),
            manifest_source: String::new(),
        };
        let r = run(req, f.state.clone(), &AtomicBool::new(false), |_| {})
            .await
            .unwrap();
        assert_eq!(r.action, "recover");
        assert_eq!(fs::read(root.join(path)).unwrap(), old);
        assert!(pending(&root).unwrap().is_empty());
    }
}
