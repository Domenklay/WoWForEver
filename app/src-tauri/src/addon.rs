//! Whole-set AddOn updates with verified staging, backups and interrupted-run recovery.
use std::{fs,fs::OpenOptions,io::Write,path::{Path,PathBuf},time::Duration,future::Future};
use serde::{Deserialize,Serialize};
use sha2::{Digest,Sha256};
use fs2::FileExt;
use crate::{i18n::{t,tf},addon_catalog::{self as catalog,Channel,Catalog,Manifest,Entry,Release}};
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
 if backup.exists(){return Err("AddOn backup destination already exists".into());}
 let previous=target.exists();
 if previous {direct(&backup)?;fs::create_dir_all(backup.parent().unwrap()).map_err(|e|e.to_string())?;fs::rename(target,&backup).map_err(|e|e.to_string())?;}
 if let Err(e)=fs::rename(stage,target){
  if previous {fs::rename(&backup,target).map_err(|restore|format!("{e}; restore failed: {restore}; backup: {}",backup.display()))?;}
  return Err(e.to_string());
 }Ok(previous.then_some(backup))
}
fn preserve_development_folder(target:&Path,development_mode:bool)->Result<bool,String>{
 if !development_mode {return Ok(false);}
 direct(target)?;
 if !target.exists(){return Ok(false);}
 if !target.is_dir(){return Err("AddOn destination is not a directory".into());}
 Ok(true)
}
fn write_json(path:&Path,value:&impl Serialize)->Result<(),String>{
 direct(path)?;fs::create_dir_all(path.parent().ok_or("Invalid metadata path")?).map_err(|e|e.to_string())?;
 let temp=path.with_extension(format!("{:032x}.tmp",rand::random::<u128>()));direct(&temp)?;
 let mut options=OpenOptions::new();options.write(true).create_new(true);
 #[cfg(unix)]{use std::os::unix::fs::OpenOptionsExt;options.mode(0o600);}
 let result=(||{let mut f=options.open(&temp).map_err(|e|e.to_string())?;f.write_all(&serde_json::to_vec_pretty(value).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;f.sync_all().map_err(|e|e.to_string())?;fs::rename(&temp,path).map_err(|e|e.to_string())})();
 if temp.exists(){let _=fs::remove_file(&temp);}result
}
async fn download(client:&reqwest::Client,url:&str,limit:u64)->Result<Vec<u8>,String>{
 let mut response=client.get(url).send().await.map_err(|e|e.to_string())?.error_for_status().map_err(|e|e.to_string())?;
 let mut body=Vec::new();while let Some(chunk)=response.chunk().await.map_err(|e|e.to_string())?{if body.len().saturating_add(chunk.len())as u64>limit{return Err("AddOn response exceeds size limit".into());}body.extend_from_slice(&chunk);}Ok(body)
}
fn cached(path:&Path)->Result<Option<Catalog>,String>{direct(path)?;if !path.exists(){return Ok(None);}let size=fs::metadata(path).map_err(|e|e.to_string())?.len();if size>catalog::LIMIT{return Err("Cached catalogue exceeds size limit".into());}catalog::parse(&fs::read_to_string(path).map_err(|e|e.to_string())?).map(Some)}
async fn resolve_catalog(cache:&Path,client:&reqwest::Client,development:bool,log:&mut impl FnMut(String))->Result<Catalog,String>{
 let path=cache.join("channels.json");
 if !development {
  match download(client,catalog::URL,catalog::LIMIT).await {
   Ok(body)=>{let text=std::str::from_utf8(&body).map_err(|e|e.to_string())?;let c=catalog::parse(text)?;write_json(&path,&c)?;return Ok(c);},
   Err(_)=>{log(t("addon_catalog_offline").into());}
  }
 }
 if let Some(c)=cached(&path)?{log(tf("addon_catalog_cached",&[&c.revision]));return Ok(c);}
 log(t("addon_catalog_bundled").into());catalog::parse(catalog::BUNDLED)
}
#[derive(Clone,Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Receipt {format:String,revision:String,channel:Channel,release:Release,preserved:Vec<String>}
#[derive(Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Change {name:String,had_previous:bool}
#[derive(Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Journal {format:String,id:String,installed:bool,changes:Vec<Change>,receipt:Receipt}
fn stage(game:&Path,id:&str,name:&str)->PathBuf{game.join("Interface/AddOns").join(format!(".{name}-install-{id}"))}
fn journal_path(game:&Path)->PathBuf{game.join(".forever-multi/addon-transaction.json")}
fn validate_journal(j:&Journal)->Result<(),String>{
 if j.format!="forever-addon-transaction-v1"||j.id.len()!=32||!j.id.bytes().all(|c|c.is_ascii_hexdigit())||j.changes.is_empty()||j.changes.len()>2{return Err("Invalid AddOn recovery journal".into());}
 let mut seen=std::collections::HashSet::new();for c in &j.changes{catalog::source_path(&c.name)?;if !seen.insert(&c.name){return Err("Duplicate recovery target".into());}}
 if j.receipt.format!="forever-addon-installed-v1"||j.receipt.release.addons.len()!=2||j.receipt.release.client_build!=70658{return Err("Invalid AddOn recovery receipt".into());}
 let mut names=std::collections::HashSet::new();for m in &j.receipt.release.addons{catalog::validate_manifest(m)?;if !names.insert(&m.name){return Err("Duplicate receipt AddOn".into());}}
 if j.receipt.preserved.iter().any(|n|!names.contains(n)){return Err("Unknown preserved AddOn".into());}
 Ok(())
}
fn recover(game:&Path)->Result<(),String>{
 let path=journal_path(game);direct(&path)?;if !path.exists(){return Ok(());}
 if fs::metadata(&path).map_err(|e|e.to_string())?.len()>catalog::LIMIT{return Err("AddOn recovery journal is too large".into());}
 let j:Journal=serde_json::from_slice(&fs::read(&path).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;validate_journal(&j)?;
 if j.installed {
  for m in &j.receipt.release.addons{if !j.receipt.preserved.contains(&m.name)&&!current(&game.join("Interface/AddOns").join(&m.name),m)?{return Err("Completed AddOn set differs; recovery retained".into());}}
  write_json(&game.join(".forever-multi/addon-installed.json"),&j.receipt)?;
 }else{
  for c in j.changes.iter().rev(){
   let target=game.join("Interface/AddOns").join(&c.name);let staged=stage(game,&j.id,&c.name);
   let backup=game.join(".forever-multi/addon-backups").join(&j.id).join(&c.name);
   direct(&target)?;direct(&staged)?;direct(&backup)?;
   if c.had_previous&&backup.exists(){
    // Preserve an interrupted new folder as well, rather than discard possible edits.
    if target.exists(){let failed=game.join(".forever-multi/addon-failed").join(&j.id).join(&c.name);direct(&failed)?;if failed.exists(){return Err("AddOn recovery destination already exists".into());}fs::create_dir_all(failed.parent().unwrap()).map_err(|e|e.to_string())?;fs::rename(&target,failed).map_err(|e|e.to_string())?;}
    fs::rename(backup,&target).map_err(|e|e.to_string())?;
   }else if c.had_previous&&!target.exists(){return Err("Previous AddOn folder is missing; recovery retained".into());}
   else if !c.had_previous&&!staged.exists()&&target.exists(){let failed=game.join(".forever-multi/addon-failed").join(&j.id).join(&c.name);direct(&failed)?;fs::create_dir_all(failed.parent().unwrap()).map_err(|e|e.to_string())?;if failed.exists(){return Err("AddOn recovery destination already exists".into());}fs::rename(&target,failed).map_err(|e|e.to_string())?;}
  }
 }
 for c in &j.changes{let p=stage(game,&j.id,&c.name);direct(&p)?;if p.exists(){fs::remove_dir_all(p).map_err(|e|e.to_string())?;}}
 fs::remove_file(path).map_err(|e|e.to_string())
}
fn apply(game:&Path,j:&mut Journal,mut replace:impl FnMut(&Path,&Path,&Path,&str)->Result<Option<PathBuf>,String>)->Result<(),String>{
 write_json(&journal_path(game),j)?;
 for c in &j.changes {
  let target=game.join("Interface/AddOns").join(&c.name);let s=stage(game,&j.id,&c.name);
  if let Err(error)=replace(game,&s,&target,&j.id){recover(game).map_err(|e|format!("{error}; recovery: {e}"))?;return Err(error);}
 }
 j.installed=true;write_json(&journal_path(game),j)?;recover(game)
}
async fn ensure_set<F,Fut>(game:&Path,c:&Catalog,channel:&Channel,development:bool,log:&mut impl FnMut(String),mut fetch:F)->Result<(),String>
where F:FnMut(String,u64)->Fut,Fut:Future<Output=Result<Vec<u8>,String>>{
 let release=c.channels.get(channel.key()).ok_or("AddOn channel is missing")?;
 log(tf("addon_channel",&[&channel.key(),&release.release]));
 let addons=game.join("Interface/AddOns");direct(&addons)?;
 let mut changed=Vec::new();let mut preserved=Vec::new();
 for m in &release.addons{let target=addons.join(&m.name);
  if preserve_development_folder(&target,development)?{log(tf("addon_dev_preserved",&[&m.name]));preserved.push(m.name.clone());continue;}
  if !current(&target,m)?{changed.push(m);}
 }
 let receipt=Receipt{format:"forever-addon-installed-v1".into(),revision:c.revision.clone(),channel:channel.clone(),release:release.clone(),preserved};
 if changed.is_empty(){if !development{write_json(&game.join(".forever-multi/addon-installed.json"),&receipt)?;}return Ok(());}
 fs::create_dir_all(&addons).map_err(|e|e.to_string())?;
 let id=format!("{:032x}",rand::random::<u128>());
 let mut changes=Vec::new();
 let result=async {
  for m in &changed {
   let folder=stage(game,&id,&m.name);direct(&folder)?;fs::create_dir(&folder).map_err(|e|e.to_string())?;
   for f in &m.files{log(tf("addon_downloading",&[&format!("{}/{}",m.name,f.name)]));let body=fetch(catalog::url(m,f),f.size).await?;if !matches(&body,f){return Err(format!("AddOn checksum mismatch: {}/{}",m.name,f.name));}let p=folder.join(&f.name);direct(&p)?;fs::create_dir_all(p.parent().unwrap()).map_err(|e|e.to_string())?;fs::write(p,body).map_err(|e|e.to_string())?;}
   if !current(&folder,m)?{return Err("Staged AddOn verification failed".into());}
   changes.push(Change{name:m.name.clone(),had_previous:addons.join(&m.name).exists()});
  }
  // No live folder is renamed until every changed AddOn is staged and verified.
  let mut j=Journal{format:"forever-addon-transaction-v1".into(),id:id.clone(),installed:false,changes,receipt};
  validate_journal(&j)?;
  apply(game,&mut j,commit)?;
  log(tf("addon_ready_set",&[&release.release]));
  log(tf("addon_backup",&[&game.join(".forever-multi/addon-backups").join(&id).display()]));Ok(())
 }.await;
 // A retained recovery journal owns its staging folders until recovery succeeds.
 if !journal_path(game).exists(){for m in &changed{let p=stage(game,&id,&m.name);if p.exists(){let _=fs::remove_dir_all(p);}}}
 result
}
pub async fn ensure(game:&Path,updates:bool,development:bool,channel:&Channel,client_build:u32,cache:&Path,mut log:impl FnMut(String))->Result<(),String>{
 direct(game)?;
 if !game.join("Wow.exe").is_file()&&!game.join("WowB.exe").is_file(){return Err(t("game_not_found").into());}
 direct(&journal_path(game))?;
 if !updates{if journal_path(game).exists(){return Err("Interrupted AddOn update: enable updates to recover the set".into());}log(t("addon_paused").into());return Ok(());}
 if client_build!=70658{return Err("AddOn channels require server build 70658".into());}
 if development {log(t("addon_dev_mode").into());
  let bundled=catalog::parse(catalog::BUNDLED)?;
  if !journal_path(game).exists()&&bundled.channels[channel.key()].addons.iter().all(|m|preserve_development_folder(&game.join("Interface/AddOns").join(&m.name),true).unwrap_or(false)){
   for m in &bundled.channels[channel.key()].addons{log(tf("addon_dev_preserved",&[&m.name]));}return Ok(());
  }
 }
 let root=game.join(".forever-multi");direct(&root)?;fs::create_dir_all(&root).map_err(|e|e.to_string())?;
 let lock_path=root.join("addon.lock");direct(&lock_path)?;
 let lock=OpenOptions::new().create(true).truncate(false).read(true).write(true).open(lock_path).map_err(|e|e.to_string())?;
 lock.try_lock_exclusive().map_err(|_|t("addon_busy").to_string())?;
 if journal_path(game).exists(){log(t("addon_recover").into());recover(game)?;}
 let client=reqwest::Client::builder().connect_timeout(Duration::from_secs(10)).timeout(Duration::from_secs(180)).redirect(reqwest::redirect::Policy::none()).user_agent("WoWForeverMulti-AddOns/1.8").build().map_err(|e|e.to_string())?;
 let c=resolve_catalog(cache,&client,development,&mut log).await?;
 ensure_set(game,&c,channel,development,&mut log,|url,size|{let client=client.clone();async move{download(&client,&url,size).await}}).await.map_err(|e|tf("addon_failed",&[&e]))
}
#[cfg(test)]fn manifests()->Result<Vec<Manifest>,String>{Ok(catalog::parse(catalog::BUNDLED)?.channels["stable"].addons.clone())}
#[cfg(test)]fn manifest()->Result<Manifest,String>{Ok(manifests()?.remove(0))}
#[cfg(test)]fn source_path(m:&Manifest)->Result<&'static str,String>{catalog::source_path(&m.name)}
#[cfg(test)]mod tests{
 use super::*;
 #[tokio::test]
 async fn development_preserves_changed_and_incomplete_addons_without_network_or_backups(){
  let temp=Temp::new();fs::write(temp.0.join("Wow.exe"),b"fixture").unwrap();
  let ascension=temp.0.join("Interface/AddOns/ForeverAscension");
  let book=temp.0.join("Interface/AddOns/ForeverEncyclopedia");
  fs::create_dir_all(&ascension).unwrap();fs::create_dir_all(&book).unwrap();
  fs::write(ascension.join("Catalog.lua"),b"local development edits").unwrap();
  fs::write(book.join("unfinished.lua"),b"work in progress without a TOC").unwrap();
  let mut logs=Vec::new();ensure(&temp.0,true,true,&Channel::Stable,70658,&temp.0.join("cache"),|line|logs.push(line)).await.unwrap();
  assert_eq!(fs::read(ascension.join("Catalog.lua")).unwrap(),b"local development edits");
  assert_eq!(fs::read(book.join("unfinished.lua")).unwrap(),b"work in progress without a TOC");
  assert_eq!(fs::read_dir(&ascension).unwrap().count(),1);assert_eq!(fs::read_dir(&book).unwrap().count(),1);
  assert!(!temp.0.join(".forever-multi").exists());
  assert_eq!(logs.len(),3);assert!(logs[1].contains("ForeverAscension"));assert!(logs[2].contains("ForeverEncyclopedia"));
 }
 #[test]
 fn absent_addons_and_normal_mode_still_use_the_verified_installer(){
  let temp=Temp::new();let target=temp.0.join("ForeverEncyclopedia");
  assert!(!preserve_development_folder(&target,true).unwrap());
  fs::create_dir(&target).unwrap();fs::write(target.join("local.lua"),b"edited").unwrap();
  assert!(preserve_development_folder(&target,true).unwrap());
  assert!(!preserve_development_folder(&target,false).unwrap());
  assert!(!current(&target,&manifests().unwrap()[1]).unwrap());
 }
 #[cfg(unix)]#[test]
 fn development_does_not_follow_a_linked_addon_folder(){
  let temp=Temp::new();let outside=Temp::new();let linked=temp.0.join("ForeverAscension");
  std::os::unix::fs::symlink(&outside.0,&linked).unwrap();
  assert!(preserve_development_folder(&linked,true).is_err());
 }
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

pub async fn channel_summary(cache:&Path,refresh:bool)->Result<serde_json::Value,String>{
 let client=reqwest::Client::builder().connect_timeout(Duration::from_secs(5)).timeout(Duration::from_secs(15)).redirect(reqwest::redirect::Policy::none()).build().map_err(|e|e.to_string())?;
 let mut messages=Vec::new();let c=resolve_catalog(cache,&client,!refresh,&mut |m|messages.push(m)).await?;
 let mut sets=serde_json::Map::new();for(key,r)in &c.channels{sets.insert(key.clone(),serde_json::json!({"release":r.release,"clientBuild":r.client_build,"addons":r.addons.iter().map(|m|serde_json::json!({"name":m.name,"version":m.version})).collect::<Vec<_>>()}));}
 Ok(serde_json::json!({"revision":c.revision,"channels":sets,"messages":messages}))
}

#[cfg(test)]mod channel_install_tests {
 use super::*;
 struct Temp(PathBuf);impl Temp{fn new()->Self{let p=std::env::temp_dir().join(format!("forever-channel-{:032x}",rand::random::<u128>()));fs::create_dir(&p).unwrap();fs::write(p.join("Wow.exe"),b"fixture").unwrap();Self(p)}}impl Drop for Temp{fn drop(&mut self){let _=fs::remove_dir_all(&self.0);}}
 fn fixture()->Catalog{let mut c=catalog::parse(catalog::BUNDLED).unwrap();for(key,r)in c.channels.iter_mut(){let body=if key=="stable"{b"approved".as_slice()}else{b"testing".as_slice()};for m in &mut r.addons{m.files=vec![Entry{name:format!("{}.toc",m.name),size:body.len()as u64,sha256:hex::encode(Sha256::digest(body))}];}}c}
 fn folder(game:&Path,name:&str)->PathBuf{game.join("Interface/AddOns").join(name)}
 fn fill(game:&Path,body:&[u8]){for name in ["ForeverAscension","ForeverEncyclopedia"]{let p=folder(game,name);fs::create_dir_all(&p).unwrap();fs::write(p.join(format!("{name}.toc")),body).unwrap();}}
 fn unchanged(game:&Path,body:&[u8]){for name in ["ForeverAscension","ForeverEncyclopedia"]{assert_eq!(fs::read(folder(game,name).join(format!("{name}.toc"))).unwrap(),body);}}
 fn journal(c:&Catalog,id:&str)->Journal{Journal{format:"forever-addon-transaction-v1".into(),id:id.into(),installed:false,changes:c.channels["testing"].addons.iter().map(|m|Change{name:m.name.clone(),had_previous:true}).collect(),receipt:Receipt{format:"forever-addon-installed-v1".into(),revision:c.revision.clone(),channel:Channel::Testing,release:c.channels["testing"].clone(),preserved:vec![]}}}
 #[tokio::test]async fn switching_both_directions_installs_the_whole_set_and_keeps_previous_folders(){
  let temp=Temp::new();fill(&temp.0,b"local edits");let c=fixture();
  for(channel,body)in [(Channel::Testing,b"testing".as_slice()),(Channel::Stable,b"approved".as_slice())]{
   ensure_set(&temp.0,&c,&channel,false,&mut |_|{},|_,_|async move{Ok(body.to_vec())}).await.unwrap();unchanged(&temp.0,body);
   let receipt:Receipt=serde_json::from_slice(&fs::read(temp.0.join(".forever-multi/addon-installed.json")).unwrap()).unwrap();assert_eq!(receipt.channel,channel);assert!(!journal_path(&temp.0).exists());
  }
  assert_eq!(fs::read_dir(temp.0.join(".forever-multi/addon-backups")).unwrap().count(),2);
 }
 #[tokio::test]async fn failure_in_second_download_cannot_mix_old_and_new_addons(){
  let temp=Temp::new();fill(&temp.0,b"previous");let c=fixture();let mut count=0;
  let result=ensure_set(&temp.0,&c,&Channel::Testing,false,&mut |_|{},|_,_|{count+=1;let body=if count==1{b"testing".to_vec()}else{b"corrupted".to_vec()};async move{Ok(body)}}).await;
  assert!(result.is_err());unchanged(&temp.0,b"previous");assert!(!temp.0.join(".forever-multi/addon-backups").exists());assert!(!journal_path(&temp.0).exists());assert_eq!(fs::read_dir(temp.0.join("Interface/AddOns")).unwrap().count(),2);
 }
 #[test]fn failure_during_second_folder_commit_restores_both_originals(){
  let temp=Temp::new();fill(&temp.0,b"previous");let c=fixture();let mut j=journal(&c,&"a".repeat(32));
  for m in &j.receipt.release.addons{let s=stage(&temp.0,&j.id,&m.name);fs::create_dir(&s).unwrap();fs::write(s.join(&m.files[0].name),b"testing").unwrap();}
  let mut count=0;let result=apply(&temp.0,&mut j,|g,s,t,id|{count+=1;if count==2{Err("disk full".into())}else{commit(g,s,t,id)}});
  assert!(result.is_err());unchanged(&temp.0,b"previous");assert!(!journal_path(&temp.0).exists());
  assert!(temp.0.join(".forever-multi/addon-failed").join(&j.id).join("ForeverAscension").is_dir());
 }
 #[test]fn interrupted_between_backup_and_install_is_recoverable_and_repeatable(){
  let temp=Temp::new();fill(&temp.0,b"previous");let c=fixture();let j=journal(&c,&"b".repeat(32));write_json(&journal_path(&temp.0),&j).unwrap();
  let m=&j.receipt.release.addons[0];let backup=temp.0.join(".forever-multi/addon-backups").join(&j.id).join(&m.name);fs::create_dir_all(backup.parent().unwrap()).unwrap();fs::rename(folder(&temp.0,&m.name),backup).unwrap();
  recover(&temp.0).unwrap();recover(&temp.0).unwrap();unchanged(&temp.0,b"previous");assert!(!journal_path(&temp.0).exists());
 }
 #[test]fn interruption_after_whole_set_install_finishes_receipt_instead_of_rolling_back(){
  let temp=Temp::new();fill(&temp.0,b"testing");let c=fixture();let mut j=journal(&c,&"c".repeat(32));j.installed=true;write_json(&journal_path(&temp.0),&j).unwrap();recover(&temp.0).unwrap();unchanged(&temp.0,b"testing");assert!(!journal_path(&temp.0).exists());assert!(temp.0.join(".forever-multi/addon-installed.json").is_file());
 }
 #[tokio::test]async fn paused_addons_do_not_access_catalogue_or_install_even_missing_folders(){
  let temp=Temp::new();ensure(&temp.0,false,false,&Channel::Testing,70658,&temp.0.join("no-cache"),|_|{}).await.unwrap();assert!(!temp.0.join("Interface").exists());assert!(!temp.0.join(".forever-multi").exists());
 }
 #[tokio::test]async fn local_development_can_install_a_missing_addon_without_overwriting_edits(){
  let temp=Temp::new();let p=folder(&temp.0,"ForeverAscension");fs::create_dir_all(&p).unwrap();fs::write(p.join("my.lua"),b"local").unwrap();let c=fixture();
  ensure_set(&temp.0,&c,&Channel::Testing,true,&mut |_|{},|_,_|async{Ok(b"testing".to_vec())}).await.unwrap();assert_eq!(fs::read(p.join("my.lua")).unwrap(),b"local");assert_eq!(fs::read(folder(&temp.0,"ForeverEncyclopedia").join("ForeverEncyclopedia.toc")).unwrap(),b"testing");assert!(!journal_path(&temp.0).exists());
 }
 #[test]fn corrupted_cache_cannot_be_used_as_a_release_set(){let temp=Temp::new();let p=temp.0.join("channels.json");fs::write(&p,b"not json").unwrap();assert!(cached(&p).is_err());}
 #[test]fn recovery_rejects_a_path_injected_target(){let c=fixture();let mut j=journal(&c,&"d".repeat(32));j.changes[0].name="../../WTF".into();assert!(validate_journal(&j).is_err());}
}

/// Read the selected client only. No catalogue fetch, install, recovery or settings writes.
pub fn installed(game:&Path)->Result<serde_json::Value,String>{
 if game.as_os_str().is_empty(){return Ok(serde_json::json!({"addons":[],"recoveryNeeded":false}));}
 let folder=game.join("Interface/AddOns");direct(&folder)?;
 let receipt_path=game.join(".forever-multi/addon-installed.json");direct(&receipt_path)?;
 let receipt=if receipt_path.exists(){
  if fs::metadata(&receipt_path).map_err(|e|e.to_string())?.len()>catalog::LIMIT as u64{return Err("Oversized AddOn receipt".into());}
  let r:Receipt=serde_json::from_slice(&fs::read(&receipt_path).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
  if r.format!="forever-addon-installed-v1"{return Err("Unknown AddOn receipt".into());}
  for m in &r.release.addons{catalog::validate_manifest(m)?;}
  Some(r)
 }else{None};
 let mut addons=Vec::new();
 if folder.exists(){for entry in fs::read_dir(&folder).map_err(|e|e.to_string())?{
  let entry=entry.map_err(|e|e.to_string())?;let path=entry.path();
  let name=entry.file_name().to_string_lossy().into_owned();
  if name.starts_with('.')||!entry.file_type().map_err(|e|e.to_string())?.is_dir(){continue;}
  direct(&path)?;
  if addons.len()>=2048{return Err("Too many AddOn folders".into());}
  let mut version=None;
  // Prefer the generic TOC, then this client flavour. Never execute Lua or follow links.
  for suffix in ["", "_Mainline", "_Forever"]{
   let toc=path.join(format!("{name}{suffix}.toc"));direct(&toc)?;
   if !toc.exists(){continue;}
   if fs::metadata(&toc).map_err(|e|e.to_string())?.len()>65536{return Err("Oversized AddOn TOC".into());}
   let body=fs::read_to_string(&toc).map_err(|e|e.to_string())?;
   version=body.lines().find_map(|line|line.trim_start_matches('\u{feff}').trim().strip_prefix("## Version:").map(|v|v.trim().to_owned()));
   break;
  }
  let managed=receipt.as_ref().and_then(|r|r.release.addons.iter().find(|m|m.name==name));
  let status=if let Some(m)=managed{if current(&path,m)?{"verified"}else{"changed"}}else{"unmanaged"};
  addons.push(serde_json::json!({"name":name,"version":version,"status":status}));
 }}
 addons.sort_by_key(|a|a["name"].as_str().unwrap_or("").to_lowercase());
 Ok(serde_json::json!({"addons":addons,"recoveryNeeded":journal_path(game).exists()}))
}

#[cfg(test)]
mod inventory_tests{
 use super::*;
 #[test]fn installed_versions_are_read_from_disk_without_writing(){
  let temp=std::env::temp_dir().join(format!("forever-inventory-{}",std::process::id()));
  fs::create_dir_all(temp.join("Interface/AddOns/ThirdParty")).unwrap();
  let toc=temp.join("Interface/AddOns/ThirdParty/ThirdParty.toc");fs::write(&toc,b"## Title: Other\n## Version: 7.2\n").unwrap();
  let v=installed(&temp).unwrap();assert_eq!(v["addons"][0]["name"],"ThirdParty");assert_eq!(v["addons"][0]["version"],"7.2");assert_eq!(v["addons"][0]["status"],"unmanaged");
  assert!(!temp.join(".forever-multi").exists());assert_eq!(fs::read(&toc).unwrap(),b"## Title: Other\n## Version: 7.2\n");fs::remove_dir_all(temp).unwrap();
 }
}
