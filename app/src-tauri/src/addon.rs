//! Install the pinned project AddOns before the game is spawned.
//! No client archives, settings, SavedVariables or other AddOns are modified.
use std::{fs, path::{Path, PathBuf}, time::Duration};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use crate::i18n::{t, tf};

#[derive(Deserialize)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
struct Manifest {format:String, name:String, version:String, protocol:u32, source_commit:String, files:Vec<Entry>}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {name:String, size:u64, sha256:String}
fn manifest()->Result<Manifest,String>{
 parse_manifest(include_str!("../addons/forever-ascension.json"))
}
fn parse_manifest(text:&str)->Result<Manifest,String>{
 let m:Manifest=serde_json::from_str(text).map_err(|e|e.to_string())?;
 let valid_version=match m.name.as_str(){"ForeverAscension"=>m.version=="1.11.0"&&m.protocol==3,"ForeverEncyclopedia"=>m.version=="0.9.8-v2.1-smartai-abilities"&&m.protocol==1,_=>false};
 if m.format!="forever-addon-v1" || !valid_version || m.source_commit.len()!=40 || !m.source_commit.bytes().all(|c|c.is_ascii_hexdigit()) || m.files.is_empty(){return Err("Invalid bundled AddOn manifest".into());}
 let mut seen=std::collections::HashSet::new();
 for f in &m.files {if f.name.is_empty() || f.name.chars().any(|c|matches!(c, '/'|'\\'|':')) || f.name.starts_with('.') || !seen.insert(&f.name) || f.size>32*1024*1024 || f.sha256.len()!=64 || !f.sha256.bytes().all(|c|c.is_ascii_hexdigit()){return Err("Unsafe AddOn file manifest".into());}}
 Ok(m)
}
fn manifests()->Result<Vec<Manifest>,String>{Ok(vec![manifest()?,parse_manifest(include_str!("../addons/forever-encyclopedia.json"))?])}
fn source_path(m:&Manifest)->Result<&'static str,String>{match m.name.as_str(){
 "ForeverAscension"=>Ok("mods/forever-advancement/addon/ForeverAscension"),
 "ForeverEncyclopedia"=>Ok("mods/living-encyclopedia/addon/ForeverEncyclopedia"),
 _=>Err("Unsupported project AddOn".into()),
}}
fn direct(path:&Path)->Result<(),String>{
 for p in path.ancestors(){match fs::symlink_metadata(p){
  Ok(meta)=>{if meta.file_type().is_symlink(){return Err(t("addon_link").into());}
   #[cfg(windows)] {use std::os::windows::fs::MetadataExt;if meta.file_attributes()&0x400!=0{return Err(t("addon_link").into());}}
  },Err(e)if e.kind()==std::io::ErrorKind::NotFound=>{},Err(e)=>return Err(e.to_string()),
 }}Ok(())
}
fn matches(body:&[u8],f:&Entry)->bool{body.len()as u64==f.size && hex::encode(Sha256::digest(body))==f.sha256}
fn current(folder:&Path,m:&Manifest)->Result<bool,String>{
 direct(folder)?;if !folder.exists(){return Ok(false);}
 if !folder.is_dir(){return Err("AddOn destination is not a directory".into());}
 for f in &m.files {let p=folder.join(&f.name);direct(&p)?;
  match fs::read(&p){Ok(body)if matches(&body,f)=>{},Ok(_)=>return Ok(false),Err(e)if e.kind()==std::io::ErrorKind::NotFound=>return Ok(false),Err(e)=>return Err(e.to_string())}
 }Ok(true)
}
fn commit(game:&Path,stage:&Path,target:&Path,id:&str)->Result<Option<PathBuf>,String>{
 direct(stage)?;direct(target)?;
 let name=target.file_name().ok_or("Invalid AddOn destination")?;
 let backup=game.join(".forever-multi/addon-backups").join(id).join(name);
 let previous=target.exists();
 if previous {direct(&backup)?;fs::create_dir_all(backup.parent().unwrap()).map_err(|e|e.to_string())?;fs::rename(target,&backup).map_err(|e|e.to_string())?;}
 if let Err(e)=fs::rename(stage,target){
  if previous {fs::rename(&backup,target).map_err(|restore|format!("{e}; restore failed: {restore}; backup: {}",backup.display()))?;}
  return Err(e.to_string());
 }Ok(previous.then_some(backup))
}
pub async fn ensure(game:&Path,mut log:impl FnMut(String))->Result<(),String>{
 for m in manifests()? {ensure_one(game,&m,&mut log).await?;}
 Ok(())
}
async fn ensure_one(game:&Path,m:&Manifest,log:&mut impl FnMut(String))->Result<(),String>{
 direct(game)?;
 if !game.join("Wow.exe").is_file()&&!game.join("WowB.exe").is_file(){return Err(t("game_not_found").into());}
 let addons=game.join("Interface/AddOns");let target=addons.join(&m.name);direct(&addons)?;
 log(format!("{} ({})",t("addon_checking"),m.name));
 if current(&target,m)? {log(format!("{} ({})",t("addon_ready"),m.name));return Ok(());}
 // Download and verify the entire new folder before touching an existing one.
 fs::create_dir_all(&addons).map_err(|e|e.to_string())?;
 let id=format!("{:032x}",rand::random::<u128>());
 let stage=addons.join(format!(".{}-install-{id}",m.name));
 fs::create_dir(&stage).map_err(|e|e.to_string())?;
 let result=async {
  let client=reqwest::Client::builder().connect_timeout(Duration::from_secs(10)).timeout(Duration::from_secs(180)).user_agent("WoWForeverMulti-AddOns").build().map_err(|e|e.to_string())?;
  for f in &m.files {
   log(tf("addon_downloading", &[&f.name]));
   let url=format!("https://raw.githubusercontent.com/Domenklay/WoWForEver/{}/{}/{}",m.source_commit,source_path(m)?,f.name);
   let mut response=client.get(url).send().await.map_err(|e|e.to_string())?.error_for_status().map_err(|e|e.to_string())?;
   let mut body=Vec::new();
   while let Some(chunk)=response.chunk().await.map_err(|e|e.to_string())? {if body.len().saturating_add(chunk.len())as u64>f.size{return Err("AddOn response exceeds manifest size".into());}body.extend_from_slice(&chunk);}
   if !matches(&body,f){return Err(format!("AddOn checksum mismatch: {}",f.name));}
   fs::write(stage.join(&f.name),body).map_err(|e|e.to_string())?;
  }
  if !current(&stage,m)? {return Err("Staged AddOn verification failed".into());}
  if let Some(path)=commit(game,&stage,&target,&id)?{log(tf("addon_backup",&[&path.display()]));}
  log(format!("{} ({})",t("addon_ready"),m.name));Ok(())
 }.await;
 if stage.exists(){let _=fs::remove_dir_all(&stage);}
 result.map_err(|e:String|tf("addon_failed",&[&e]))
}

#[cfg(test)]mod tests{
 use super::*;
 #[test]fn both_project_addons_have_independent_pins_and_source_directories(){let values=manifests().unwrap();assert_eq!(values.len(),2);assert_eq!(values[1].name,"ForeverEncyclopedia");assert_eq!(values[1].files.len(),8);assert_ne!(source_path(&values[0]).unwrap(),source_path(&values[1]).unwrap());assert_ne!(values[0].source_commit,values[1].source_commit);}
 #[test]fn encyclopedia_replacement_cannot_overwrite_the_ascension_backup(){let temp=Temp::new();let target=temp.0.join("Interface/AddOns/ForeverEncyclopedia");fs::create_dir_all(&target).unwrap();fs::write(target.join("old.lua"),b"previous book").unwrap();let stage=temp.0.join(".new-book");fs::create_dir(&stage).unwrap();let backup=commit(&temp.0,&stage,&target,"same-run").unwrap().unwrap();assert!(backup.ends_with("ForeverEncyclopedia"));assert_eq!(fs::read(backup.join("old.lua")).unwrap(),b"previous book");assert!(!temp.0.join(".forever-multi/addon-backups/same-run/ForeverAscension").exists());}
 struct Temp(PathBuf);impl Temp{fn new()->Self{let p=std::env::temp_dir().join(format!("forever-addon-test-{:032x}",rand::random::<u128>()));fs::create_dir(&p).unwrap();Self(p)}}impl Drop for Temp{fn drop(&mut self){let _=fs::remove_dir_all(&self.0);}}
 fn entry(body:&[u8])->Entry{Entry{name:"ForeverAscension.toc".into(),size:body.len()as u64,sha256:hex::encode(Sha256::digest(body))}}
 #[test]fn bundled_manifest_is_pinned_and_contains_the_complete_addon(){let m=manifest().unwrap();assert_eq!(m.files.len(),7);assert!(m.files.iter().any(|f|f.name=="Catalog.lua"));assert!(m.files.iter().any(|f|f.name=="ForeverAscension.toc"));}
 #[test]fn a_directory_or_toc_alone_is_not_a_complete_installation(){let temp=Temp::new();let mut m=manifest().unwrap();m.files=vec![entry(b"complete")];assert!(!current(&temp.0,&m).unwrap());fs::write(temp.0.join("ForeverAscension.toc"),b"damaged").unwrap();assert!(!current(&temp.0,&m).unwrap());fs::write(temp.0.join("ForeverAscension.toc"),b"complete").unwrap();assert!(current(&temp.0,&m).unwrap());}
 #[test]fn replacing_an_addon_retains_edits_and_other_addons(){let temp=Temp::new();let addons=temp.0.join("Interface/AddOns");let target=addons.join("ForeverAscension");fs::create_dir_all(&target).unwrap();fs::write(target.join("custom.lua"),b"user edits").unwrap();let other=addons.join("OtherAddon");fs::create_dir(&other).unwrap();fs::write(other.join("file.lua"),b"keep").unwrap();let stage=addons.join(".stage");fs::create_dir(&stage).unwrap();fs::write(stage.join("new.lua"),b"new").unwrap();let backup=commit(&temp.0,&stage,&target,"test").unwrap().unwrap();assert_eq!(fs::read(backup.join("custom.lua")).unwrap(),b"user edits");assert_eq!(fs::read(other.join("file.lua")).unwrap(),b"keep");assert!(target.join("new.lua").is_file());}
 #[test]fn failed_commit_restores_the_original_addon(){let temp=Temp::new();let target=temp.0.join("ForeverAscension");fs::create_dir(&target).unwrap();fs::write(target.join("user.lua"),b"keep").unwrap();assert!(commit(&temp.0,&temp.0.join("missing-stage"),&target,"test").is_err());assert_eq!(fs::read(target.join("user.lua")).unwrap(),b"keep");}
 #[cfg(unix)]#[test]fn linked_addons_cannot_redirect_writes(){let temp=Temp::new();let outside=Temp::new();std::os::unix::fs::symlink(&outside.0,temp.0.join("linked")).unwrap();assert!(current(&temp.0.join("linked"),&manifest().unwrap()).is_err());assert!(fs::read_dir(&outside.0).unwrap().next().is_none());}
}
