//! Local, exact-state CASC patch packages. No shell/SQL execution or remote downloads.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

type Result<T> = std::result::Result<T, Error>;
#[derive(Debug)]
pub struct Error {
    pub code: &'static str,
    pub detail: String,
}
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
        err("invalid", e)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Change {
    pub path: String,
    pub before: Option<String>,
    pub after: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub id: String,
    pub name: String,
    pub version: String,
    pub client_version: String,
    pub status: String,
    pub client_render_verified: bool,
    pub server_ready: bool,
    pub base_files: BTreeMap<String, String>,
    pub files: Vec<Change>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Preview {
    pub id: String,
    pub name: String,
    pub version: String,
    pub ready: bool,
    pub reason: String,
    pub files: usize,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub installed: Option<String>,
    pub recovery_needed: bool,
    pub backup: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
struct Journal {
    manifest: Manifest,
    phase: String,
    previous: Option<String>,
}
const STATE: &str = ".forever-content";
const LIMIT: u64 = 8 * 1024 * 1024 * 1024;

fn hash(path: &Path) -> Result<String> {
    let mut f = File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = [0; 65536];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex::encode(h.finalize()))
}
fn digest(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn token(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 80
        && s != "."
        && s != ".."
        && s.bytes().all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
}
fn metadata_name(s: &str) -> bool {
    if !s.is_ascii() {
        return false;
    }
    s == "shmem"
        || [(".idx", 10), (".lru", 16)].iter().any(|(ext, len)| {
            s.len() == len + ext.len() && s.ends_with(ext) && s[..*len].bytes().all(|b| b.is_ascii_hexdigit())
        })
}
fn allowed(s: &str) -> bool {
    if s == ".build.info" {
        return true;
    }
    let p: Vec<_> = s.split('/').collect();
    if p.iter().any(|x| {
        x.is_empty() || *x == "." || *x == ".." || !x.bytes().all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    }) {
        return false;
    }
    if p.len() == 3 && p[0] == "Data" && p[1] == "data" {
        return metadata_name(p[2])
            || (p[2].len() == 8 && p[2].starts_with("data.") && p[2][5..].bytes().all(|b| b.is_ascii_digit()));
    }
    p.len() == 5
        && p[..2] == ["Data", "config"]
        && p[2].len() == 2
        && p[3].len() == 2
        && p[4].len() == 32
        && p[2..].iter().all(|s| s.bytes().all(|b| b.is_ascii_hexdigit()))
        && p[4].starts_with(p[2])
        && &p[4][2..4] == p[3]
}
fn no_links(base: &Path, relative: &str) -> Result<PathBuf> {
    let mut path = base.to_path_buf();
    for part in relative.split('/') {
        path.push(part);
        if let Ok(meta) = fs::symlink_metadata(&path) {
            let linked = meta.file_type().is_symlink();
            #[cfg(windows)]
            let linked = {
                use std::os::windows::fs::MetadataExt;
                linked || meta.file_attributes() & 0x400 != 0
            };
            if linked {
                return Err(err("invalid", "linked path"));
            }
        }
    }
    Ok(path)
}
fn root(game: &Path) -> Result<PathBuf> {
    let game = game.canonicalize()?;
    if game.file_name().and_then(|s| s.to_str()) != Some("_classic_beta_") {
        return Err(err("client", "select _classic_beta_"));
    }
    let root = game
        .parent()
        .ok_or_else(|| err("client", "missing client root"))?
        .to_path_buf();
    if !no_links(&root, ".build.info")?.is_file() || !no_links(&root, "Data/data")?.is_dir() {
        return Err(err("client", "missing CASC storage"));
    }
    Ok(root)
}
fn inventory(root: &Path) -> Result<BTreeMap<String, String>> {
    if root.join("Data/data/RepairMarker.psv").exists() {
        return Err(err("changed", "client repair is pending"));
    }
    let mut out = BTreeMap::new();
    out.insert(".build.info".into(), hash(&root.join(".build.info"))?);
    for entry in fs::read_dir(root.join("Data/data"))? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if metadata_name(&name) {
            let rel = format!("Data/data/{name}");
            out.insert(rel.clone(), hash(&no_links(root, &rel)?)?);
        }
    }
    if !out.contains_key("Data/data/shmem") {
        return Err(err("client", "missing shmem"));
    }
    Ok(out)
}
fn json<T: for<'a> Deserialize<'a>>(path: &Path) -> Result<T> {
    let f = File::open(path)?;
    if f.metadata()?.len() > 1024 * 1024 {
        return Err(err("invalid", "oversized manifest"));
    }
    Ok(serde_json::from_reader(f)?)
}
fn save<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let tmp = path.with_file_name(format!(".state-{:016x}.next", rand::random::<u64>()));
    let result = (|| -> Result<()> {
        let mut f = OpenOptions::new().write(true).create_new(true).open(&tmp)?;
        serde_json::to_writer_pretty(&mut f, value)?;
        f.write_all(b"\n")?;
        f.sync_all()?;
        drop(f);
        fs::rename(&tmp, path)?;
        Ok(())
    })();
    if tmp.exists() {
        let _ = fs::remove_file(tmp);
    }
    result
}

fn optional_hash(path: &Path) -> Result<Option<String>> {
    if path.exists() {
        Ok(Some(hash(path)?))
    } else {
        Ok(None)
    }
}
fn validate(m: &Manifest) -> Result<()> {
    if m.format != "wowforever-zone-package-v1"
        || !token(&m.id)
        || !token(&m.version)
        || m.name.is_empty()
        || m.name.len() > 200
        || !["experimental", "verified"].contains(&m.status.as_str())
        || m.files.len() > 1024
    {
        return Err(err("invalid", "package header"));
    }
    let mut paths = HashSet::new();
    for c in &m.files {
        if !allowed(&c.path)
            || !paths.insert(c.path.to_ascii_lowercase())
            || c.before.as_deref().is_some_and(|s| !digest(s))
            || c.after.as_deref().is_some_and(|s| !digest(s))
            || c.before == c.after
        {
            return Err(err("invalid", "file operation"));
        }
        if c.path.starts_with("Data/config/") || c.path.starts_with("Data/data/data.") {
            if c.before.is_some() || c.after.is_none() {
                return Err(err("invalid", "archives/configs must be new files"));
            }
        }
        if [".build.info", "Data/data/shmem"].contains(&c.path.as_str()) && c.after.is_none() {
            return Err(err("invalid", "required metadata cannot be deleted"));
        }
    }
    for (p, h) in &m.base_files {
        if !(p == ".build.info" || p.starts_with("Data/data/") && metadata_name(&p[10..])) || !digest(h) {
            return Err(err("invalid", "base metadata"));
        }
    }
    Ok(())
}
fn inspect_inner(package: &Path, root: &Path, version: &str) -> Result<(Manifest, Preview)> {
    let package = package.canonicalize()?;
    if package.starts_with(root) || root.starts_with(&package) {
        return Err(err("invalid", "package must be outside the client"));
    }
    let m: Manifest = json(&no_links(&package, "manifest.json")?)?;
    validate(&m)?;
    let mut reason = String::new();
    if m.status != "verified" || !m.client_render_verified {
        reason = "unverified".into();
    } else if !m.server_ready {
        reason = "server".into();
    } else if m.client_version != version {
        reason = "client".into();
    } else {
        if m.files.is_empty()
            || !m
                .files
                .iter()
                .any(|c| c.path == ".build.info" && c.before.as_ref() == m.base_files.get(".build.info"))
        {
            return Err(err("invalid", "missing build switch"));
        }
        if inventory(root)? != m.base_files {
            reason = "changed".into();
        }
        let mut bytes = 0;
        for c in &m.files {
            if optional_hash(&no_links(root, &c.path)?)? != c.before {
                reason = "changed".into();
            }
            if let Some(after) = &c.after {
                let payload = no_links(&package, &format!("payload/{}", c.path))?;
                bytes += payload.metadata()?.len();
                if bytes > LIMIT {
                    return Err(err("invalid", "package exceeds 8 GiB"));
                }
                if hash(&payload)? != *after {
                    return Err(err("invalid", "payload checksum"));
                }
            }
        }
    }
    let preview = Preview {
        id: m.id.clone(),
        name: m.name.clone(),
        version: m.version.clone(),
        ready: reason.is_empty(),
        reason,
        files: m.files.len(),
    };
    Ok((m, preview))
}
pub fn inspect(package: &Path, game: &Path, version: &str) -> Result<Preview> {
    Ok(inspect_inner(package, &root(game)?, version)?.1)
}
fn state_dir(root: &Path) -> Result<PathBuf> {
    no_links(root, STATE)
}
fn current(state: &Path) -> Result<Option<String>> {
    let p = state.join("current.json");
    if !p.exists() {
        return Ok(None);
    }
    let id: String = json(&no_links(state, "current.json")?)?;
    if !token(&id) {
        return Err(err("invalid", "operation pointer"));
    }
    Ok(Some(id))
}
fn read_journal(state: &Path, id: &str) -> Result<Journal> {
    json(&no_links(state, &format!("operations/{id}/journal.json"))?)
}
pub fn status(game: &Path) -> Result<Status> {
    let root = root(game)?;
    let state = state_dir(&root)?;
    let Some(id) = current(&state)? else {
        return Ok(Status {
            installed: None,
            recovery_needed: false,
            backup: None,
        });
    };
    let j = read_journal(&state, &id)?;
    Ok(Status {
        installed: Some(format!("{} {}", j.manifest.name, j.manifest.version)),
        recovery_needed: j.phase != "installed",
        backup: Some(state.join("operations").join(id).to_string_lossy().into()),
    })
}
fn lock(state: &Path) -> Result<File> {
    fs::create_dir_all(state)?;
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .open(no_links(state, "operation.lock")?)?;
    file.try_lock_exclusive()
        .map_err(|_| err("busy", "another package operation is active"))?;
    Ok(file)
}
fn ordered(m: &Manifest) -> Vec<&Change> {
    let mut out: Vec<_> = m.files.iter().collect();
    out.sort_by_key(|c| c.path == ".build.info");
    out
}
fn expected_metadata(m: &Manifest) -> BTreeMap<String, String> {
    let mut out = m.base_files.clone();
    for c in &m.files {
        if c.path == ".build.info" || c.path.starts_with("Data/data/") && metadata_name(&c.path[10..]) {
            if let Some(h) = &c.after {
                out.insert(c.path.clone(), h.clone());
            } else {
                out.remove(&c.path);
            }
        }
    }
    out
}
fn replace_file(source: &Path, target: &Path, expected: &str) -> Result<()> {
    fs::create_dir_all(target.parent().ok_or_else(|| err("invalid", "target parent"))?)?;
    let tmp = target
        .parent()
        .unwrap()
        .join(format!(".forever-copy-{:016x}", rand::random::<u64>()));
    let result = (|| -> Result<()> {
        let mut output = OpenOptions::new().write(true).create_new(true).open(&tmp)?;
        std::io::copy(&mut File::open(source)?, &mut output)?;
        output.sync_all()?;
        drop(output);
        if hash(&tmp)? != expected {
            return Err(err("changed", "copied file checksum"));
        }
        fs::rename(&tmp, target)?;
        Ok(())
    })();
    if tmp.exists() {
        let _ = fs::remove_file(tmp);
    }
    result
}
fn restore(root: &Path, dir: &Path, j: &Journal) -> Result<()> {
    validate(&j.manifest)?;
    for (i, c) in j.manifest.files.iter().enumerate() {
        let now = optional_hash(&no_links(root, &c.path)?)?;
        if now != c.before && now != c.after {
            return Err(err("changed", &c.path));
        }
        if let Some(expected) = &c.before {
            if hash(&no_links(dir, &format!("before/{i}"))?)? != *expected {
                return Err(err("invalid", "backup checksum"));
            }
        }
    }
    for c in ordered(&j.manifest) {
        let i = j.manifest.files.iter().position(|v| v.path == c.path).unwrap();
        let target = no_links(root, &c.path)?;
        if c.before.is_some() {
            replace_file(&dir.join(format!("before/{i}")), &target, c.before.as_ref().unwrap())?;
        } else if target.exists() {
            fs::remove_file(target)?;
        }
    }
    Ok(())
}
pub fn install(package: &Path, game: &Path, version: &str) -> Result<Status> {
    let root = root(game)?;
    let (m, p) = inspect_inner(package, &root, version)?;
    if !p.ready {
        return Err(err("unready", p.reason));
    }
    let state = state_dir(&root)?;
    let _guard = lock(&state)?;
    let previous = current(&state)?;
    if let Some(id) = &previous {
        if read_journal(&state, id)?.phase != "installed" {
            return Err(err("recovery", "rollback the interrupted operation first"));
        }
    }
    let mut required = 64 * 1024 * 1024u64;
    for c in &m.files {
        if c.after.is_some() {
            required = required.saturating_add(
                no_links(&package.canonicalize()?, &format!("payload/{}", c.path))?
                    .metadata()?
                    .len()
                    .saturating_mul(2),
            );
        }
        if c.before.is_some() {
            required = required.saturating_add(no_links(&root, &c.path)?.metadata()?.len());
        }
    }
    if fs2::available_space(&root)? < required {
        return Err(err("io", "not enough free space for staging and backup"));
    }
    let id = format!("{:016x}{:016x}", rand::random::<u64>(), rand::random::<u64>());
    let dir = no_links(&state, &format!("operations/{id}"))?;
    fs::create_dir_all(dir.parent().unwrap())?;
    fs::create_dir(&dir)?;
    fs::create_dir(dir.join("before"))?;
    fs::create_dir(dir.join("staged"))?;
    for (i, c) in m.files.iter().enumerate() {
        if let Some(before) = &c.before {
            fs::copy(no_links(&root, &c.path)?, dir.join(format!("before/{i}")))?;
            if hash(&dir.join(format!("before/{i}")))? != *before {
                return Err(err("changed", "backup mismatch"));
            }
        }
        if let Some(after) = &c.after {
            fs::copy(
                no_links(&package.canonicalize()?, &format!("payload/{}", c.path))?,
                dir.join(format!("staged/{i}")),
            )?;
            if hash(&dir.join(format!("staged/{i}")))? != *after {
                return Err(err("changed", "payload changed while staging"));
            }
        }
    }
    for folder in ["before", "staged"] {
        for entry in fs::read_dir(dir.join(folder))? {
            OpenOptions::new().write(true).open(entry?.path())?.sync_all()?;
        }
    }
    if inventory(&root)? != m.base_files {
        return Err(err("changed", "client changed while staging"));
    }
    let mut j = Journal {
        manifest: m,
        phase: "applying".into(),
        previous,
    };
    save(&dir.join("journal.json"), &j)?;
    save(&state.join("current.json"), &id)?;
    let result = (|| -> Result<()> {
        for c in ordered(&j.manifest) {
            let i = j.manifest.files.iter().position(|v| v.path == c.path).unwrap();
            let target = no_links(&root, &c.path)?;
            if optional_hash(&target)? != c.before {
                return Err(err("changed", &c.path));
            }
            if c.after.is_some() {
                replace_file(&dir.join(format!("staged/{i}")), &target, c.after.as_ref().unwrap())?;
            } else {
                fs::remove_file(&target)?;
            }
            if optional_hash(&target)? != c.after {
                return Err(err("changed", "installed file checksum"));
            }
        }
        j.phase = "installed".into();
        save(&dir.join("journal.json"), &j)?;
        Ok(())
    })();
    if let Err(e) = result {
        if restore(&root, &dir, &j).is_ok() {
            j.phase = "rolled_back".into();
            save(&dir.join("journal.json"), &j)?;
            if let Some(prev) = &j.previous {
                save(&state.join("current.json"), prev)?
            } else {
                fs::remove_file(state.join("current.json"))?
            }
        }
        return Err(e);
    }
    status(game)
}
pub fn rollback(game: &Path) -> Result<Status> {
    let root = root(game)?;
    let state = state_dir(&root)?;
    let _guard = lock(&state)?;
    let id = current(&state)?.ok_or_else(|| err("empty", "no installed package"))?;
    let dir = no_links(&state, &format!("operations/{id}"))?;
    let mut j = read_journal(&state, &id)?;
    if j.phase == "installed" && inventory(&root)? != expected_metadata(&j.manifest) {
        return Err(err("changed", "client metadata changed after installation"));
    }
    j.phase = "rolling_back".into();
    save(&dir.join("journal.json"), &j)?;
    restore(&root, &dir, &j)?;
    j.phase = "rolled_back".into();
    save(&dir.join("journal.json"), &j)?;
    if let Some(prev) = &j.previous {
        save(&state.join("current.json"), prev)?
    } else {
        fs::remove_file(state.join("current.json"))?
    }
    status(game)
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture {
        dir: PathBuf,
        game: PathBuf,
        package: PathBuf,
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }
    fn h(bytes: &[u8]) -> String {
        hex::encode(Sha256::digest(bytes))
    }
    fn fixture() -> Fixture {
        let dir = std::env::temp_dir().join(format!("forever-package-{:016x}", rand::random::<u64>()));
        let root = dir.join("client");
        let game = root.join("_classic_beta_");
        let package = dir.join("package");
        fs::create_dir_all(&game).unwrap();
        fs::create_dir_all(root.join("Data/data")).unwrap();
        fs::write(root.join(".build.info"), b"owned before").unwrap();
        fs::write(root.join("Data/data/shmem"), b"owned shmem").unwrap();
        fs::create_dir_all(package.join("payload/Data/data")).unwrap();
        fs::write(package.join("payload/.build.info"), b"owned after").unwrap();
        fs::write(package.join("payload/Data/data/data.001"), b"owned payload").unwrap();
        let m = Manifest {
            format: "wowforever-zone-package-v1".into(),
            id: "owned-zone".into(),
            name: "Owned zone".into(),
            version: "1".into(),
            client_version: "1.60.1.70532".into(),
            status: "verified".into(),
            client_render_verified: true,
            server_ready: true,
            base_files: inventory(&root).unwrap(),
            files: vec![
                Change {
                    path: ".build.info".into(),
                    before: Some(h(b"owned before")),
                    after: Some(h(b"owned after")),
                },
                Change {
                    path: "Data/data/data.001".into(),
                    before: None,
                    after: Some(h(b"owned payload")),
                },
            ],
        };
        save(&package.join("manifest.json"), &m).unwrap();
        Fixture { dir, game, package }
    }
    fn edit(f: &Fixture, change: impl FnOnce(&mut Manifest)) {
        let mut m: Manifest = json(&f.package.join("manifest.json")).unwrap();
        change(&mut m);
        save(&f.package.join("manifest.json"), &m).unwrap();
    }
    #[test]
    fn install_and_rollback_owned_payload_preserve_unrelated_files() {
        let f = fixture();
        let root = f.game.parent().unwrap();
        fs::write(f.game.join("settings"), b"unchanged").unwrap();
        assert!(inspect(&f.package, &f.game, "1.60.1.70532").unwrap().ready);
        let s = install(&f.package, &f.game, "1.60.1.70532").unwrap();
        assert!(s.installed.is_some());
        assert_eq!(fs::read(root.join(".build.info")).unwrap(), b"owned after");
        assert_eq!(fs::read(root.join("Data/data/data.001")).unwrap(), b"owned payload");
        assert!(rollback(&f.game).unwrap().installed.is_none());
        assert_eq!(fs::read(root.join(".build.info")).unwrap(), b"owned before");
        assert!(!root.join("Data/data/data.001").exists());
        assert_eq!(fs::read(f.game.join("settings")).unwrap(), b"unchanged");
    }
    #[test]
    fn unverified_or_wrong_client_and_tampered_payload_are_blocked() {
        let f = fixture();
        assert_eq!(inspect(&f.package, &f.game, "other").unwrap().reason, "client");
        edit(&f, |m| m.server_ready = false);
        assert_eq!(inspect(&f.package, &f.game, "1.60.1.70532").unwrap().reason, "server");
        edit(&f, |m| m.server_ready = true);
        edit(&f, |m| m.client_render_verified = false);
        assert!(!inspect(&f.package, &f.game, "1.60.1.70532").unwrap().ready);
        assert!(install(&f.package, &f.game, "1.60.1.70532").is_err());
        assert!(!f.game.parent().unwrap().join(STATE).exists());
        edit(&f, |m| m.client_render_verified = true);
        fs::write(f.package.join("payload/Data/data/data.001"), b"bad").unwrap();
        assert_eq!(
            inspect(&f.package, &f.game, "1.60.1.70532").err().unwrap().code,
            "invalid"
        );
    }
    #[test]
    fn rejects_traversal_case_collisions_and_archive_overwrites() {
        assert!(!metadata_name("ééééé.idx"));
        for path in [
            "../escape",
            "Data/data/../escape",
            "WTF/Config.wtf",
            "_classic_beta_/WowB.exe",
            "Data\\data\\shmem",
            "Data/config/aa/bb/cccccccccccccccccccccccccccccccc",
        ] {
            assert!(!allowed(path), "{path}");
        }
        let f = fixture();
        edit(&f, |m| {
            let mut c = m.files[1].clone();
            c.before = Some(h(b"previous"));
            m.files[1] = c;
        });
        assert!(inspect(&f.package, &f.game, "1.60.1.70532").is_err());
    }
    #[test]
    fn new_metadata_or_post_install_changes_refuse_to_overwrite_progress() {
        let f = fixture();
        let root = f.game.parent().unwrap();
        fs::write(root.join("Data/data/0000000001.idx"), b"new generation").unwrap();
        assert_eq!(inspect(&f.package, &f.game, "1.60.1.70532").unwrap().reason, "changed");
        fs::remove_file(root.join("Data/data/0000000001.idx")).unwrap();
        install(&f.package, &f.game, "1.60.1.70532").unwrap();
        fs::write(root.join("Data/data/0000000002.idx"), b"later game update").unwrap();
        assert_eq!(rollback(&f.game).err().unwrap().code, "changed");
        assert_eq!(fs::read(root.join(".build.info")).unwrap(), b"owned after");
    }
    #[test]
    fn partial_copy_failure_automatically_restores_prior_client() {
        let f = fixture();
        let root = f.game.parent().unwrap();
        let rel = "Data/config/aa/bb/aabb0000000000000000000000000000";
        fs::create_dir_all(f.package.join("payload/Data/config/aa/bb")).unwrap();
        fs::write(f.package.join("payload").join(rel), b"owned config").unwrap();
        fs::create_dir_all(root.join("Data/config")).unwrap();
        fs::write(root.join("Data/config/aa"), b"not a directory").unwrap();
        edit(&f, |m| {
            m.files.push(Change {
                path: rel.into(),
                before: None,
                after: Some(h(b"owned config")),
            })
        });
        assert!(install(&f.package, &f.game, "1.60.1.70532").is_err());
        assert!(!root.join("Data/data/data.001").exists());
        assert_eq!(fs::read(root.join(".build.info")).unwrap(), b"owned before");
        assert!(status(&f.game).unwrap().installed.is_none());
    }
    #[test]
    fn package_operations_are_exclusive() {
        let f = fixture();
        let state = state_dir(f.game.parent().unwrap()).unwrap();
        let _guard = lock(&state).unwrap();
        assert_eq!(lock(&state).err().unwrap().code, "busy");
    }
    #[test]
    fn interrupted_switch_can_be_recovered() {
        let f = fixture();
        install(&f.package, &f.game, "1.60.1.70532").unwrap();
        let root = f.game.parent().unwrap();
        let state = state_dir(root).unwrap();
        let id = current(&state).unwrap().unwrap();
        let dir = state.join("operations").join(id);
        let mut j = read_journal(&state, dir.file_name().unwrap().to_str().unwrap()).unwrap();
        j.phase = "applying".into();
        save(&dir.join("journal.json"), &j).unwrap();
        fs::write(root.join(".build.info"), b"owned before").unwrap();
        assert!(status(&f.game).unwrap().recovery_needed);
        rollback(&f.game).unwrap();
        assert!(!root.join("Data/data/data.001").exists());
    }
    #[test]
    fn interrupted_rollback_can_resume_after_metadata_was_restored() {
        let f = fixture();
        install(&f.package, &f.game, "1.60.1.70532").unwrap();
        let root = f.game.parent().unwrap();
        let state = state_dir(root).unwrap();
        let id = current(&state).unwrap().unwrap();
        let dir = state.join("operations").join(&id);
        let mut j = read_journal(&state, &id).unwrap();
        j.phase = "rolling_back".into();
        save(&dir.join("journal.json"), &j).unwrap();
        fs::write(root.join(".build.info"), b"owned before").unwrap();
        assert!(status(&f.game).unwrap().recovery_needed);
        rollback(&f.game).unwrap();
        assert!(!root.join("Data/data/data.001").exists());
        assert!(status(&f.game).unwrap().installed.is_none());
    }
    #[cfg(unix)]
    #[test]
    fn linked_payload_cannot_escape_package() {
        let f = fixture();
        fs::remove_file(f.package.join("payload/Data/data/data.001")).unwrap();
        std::os::unix::fs::symlink(
            f.game.parent().unwrap().join(".build.info"),
            f.package.join("payload/Data/data/data.001"),
        )
        .unwrap();
        assert!(inspect(&f.package, &f.game, "1.60.1.70532").is_err());
    }
}
