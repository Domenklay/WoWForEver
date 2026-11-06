//! Startup metadata is required independently of DOWNLOAD's selected payloads.
use std::{collections::HashSet, path::Path};
use serde::Serialize;
use super::{config::{BuildConfig, CKey, KeyPair}, encoding::Encoding, install::InstallError,
    storage::{EKey, Storage, StorageError}};

#[derive(Debug, Clone)]
pub struct Manifest { pub name: String, pub ckey: CKey, pub ekey: EKey }

pub fn required(build: &BuildConfig, encoding: &Encoding) -> Result<Vec<Manifest>, InstallError> {
    let mut pairs = vec![("encoding".to_owned(), build.encoding),
        ("install".into(), build.install.ok_or(InstallError::MissingManifest("install"))?),
        ("download".into(), build.download.ok_or(InstallError::MissingManifest("download"))?),
        ("root".into(), build.root)];
    if let Some(size) = build.size { pairs.push(("size".into(), size)); }
    pairs.extend(build.vfs.iter().enumerate().map(|(i, pair)| (format!("vfs-object-{i}"), *pair)));
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for (name, KeyPair { ckey, ekey }) in pairs {
        let ekey = ekey.or_else(|| encoding.ekey_for(&ckey))
            .ok_or(InstallError::MissingManifest("startup encoding key"))?;
        if seen.insert((ckey, ekey)) { out.push(Manifest { name, ckey, ekey }); }
    }
    Ok(out)
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all="camelCase")]
pub struct Report { pub checked: usize, pub missing: Vec<String>, pub invalid: Vec<String> }
impl Report { pub fn complete(&self) -> bool { self.missing.is_empty() && self.invalid.is_empty() } }

pub fn check(root: &Path, manifests: &[Manifest]) -> Result<Report, StorageError> {
    let mut store = Storage::open(root)?;
    let mut report = Report::default();
    for manifest in manifests {
        report.checked += 1;
        if !store.contains(&manifest.ekey) { report.missing.push(manifest.name.clone()); }
        else if local_blte(&mut store, manifest).is_none() { report.invalid.push(manifest.name.clone()); }
    }
    Ok(report)
}

/// Preserve the CDN's original encoding, never re-encode data under an old EKey.
pub fn valid_blte(raw: &[u8], manifest: &Manifest) -> Option<Vec<u8>> {
    if raw.get(..4)? != b"BLTE" { return None; }
    let header = u32::from_be_bytes(raw.get(4..8)?.try_into().ok()?) as usize;
    let hashed = if header == 0 { raw } else { raw.get(..header)? };
    if md5::compute(hashed).0 != manifest.ekey { return None; }
    let decoded = super::blte::decode(raw).ok()?;
    (md5::compute(&decoded).0 == manifest.ckey).then_some(decoded)
}

pub fn local_blte(store: &mut Storage, manifest: &Manifest) -> Option<(Vec<u8>, Vec<u8>)> {
    let entry = *store.locate(&manifest.ekey)?;
    let raw = store.read_raw(&entry).ok()?;
    let blte = raw.get(30..)?.to_vec();
    let decoded = valid_blte(&blte, manifest)?;
    Some((blte, decoded))
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::writer::StoreWriter;
    fn object(name: &str, body: &[u8]) -> (Manifest, Vec<u8>) {
        let mut raw = b"BLTE\0\0\0\0N".to_vec(); raw.extend_from_slice(body);
        (Manifest { name: name.into(), ckey: md5::compute(body).0, ekey: md5::compute(&raw).0 }, raw)
    }
    #[test]
    fn healthy_payloads_cannot_hide_the_three_missing_startup_manifests() {
        let root = tempfile::tempdir().unwrap();
        let (asset, raw) = object("asset", b"already downloaded texture");
        let mut writer = StoreWriter::create(root.path().join("Data/data")).unwrap();
        writer.write(&asset.ekey, &raw).unwrap(); writer.finish().unwrap();
        let manifests: Vec<_> = ["install", "download", "size"].map(|n| object(n, n.as_bytes()).0).into();
        let report = check(root.path(), &manifests).unwrap();
        assert!(!report.complete()); assert_eq!(report.missing, ["install", "download", "size"]);
        let before = std::fs::read(root.path().join("Data/data/data.000")).unwrap();
        let mut writer = StoreWriter::create(root.path().join("Data/data")).unwrap();
        for name in ["install", "download", "size"] {
            let (manifest, raw) = object(name, name.as_bytes()); writer.write(&manifest.ekey, &raw).unwrap();
        }
        writer.finish().unwrap();
        assert!(check(root.path(), &manifests).unwrap().complete());
        assert_eq!(before, std::fs::read(root.path().join("Data/data/data.000")).unwrap());
        let mut store = Storage::open(root.path()).unwrap();
        assert_eq!(store.read_verified(&asset.ekey, &asset.ckey).unwrap(), b"already downloaded texture");
    }
    #[test]
    fn both_encoded_and_content_hashes_must_match() {
        let (mut manifest, raw) = object("download", b"manifest");
        assert!(valid_blte(&raw, &manifest).is_some());
        manifest.ekey[15] ^= 1; assert!(valid_blte(&raw, &manifest).is_none());
        manifest.ekey[15] ^= 1; manifest.ckey[15] ^= 1;
        assert!(valid_blte(&raw, &manifest).is_none());
    }
    #[test]
    fn unresolved_root_is_an_error_instead_of_silently_skipping_it() {
        let (manifest, _) = object("root", b"root");
        let pair = KeyPair { ckey: manifest.ckey, ekey: Some(manifest.ekey) };
        let build = BuildConfig { build_name: None, build_uid: None, encoding: pair, root: KeyPair { ekey: None, ..pair },
            install: Some(pair), download: Some(pair), size: Some(pair), vfs: vec![pair, pair] };
        assert!(required(&build, &Encoding::default()).is_err());
        let fixed = BuildConfig { root: pair, ..build };
        assert_eq!(required(&fixed, &Encoding::default()).unwrap().len(), 1);
    }
}
