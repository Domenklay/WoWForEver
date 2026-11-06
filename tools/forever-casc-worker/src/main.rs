//! GPL-3.0-or-later standalone content worker. JSON request, progress and result.
use std::{fs,path::{Path,PathBuf},io::{self,BufRead,Write},sync::{Arc,Mutex},time::Instant};
use anyhow::{bail,Context,Result};
use serde::{Deserialize,Serialize};
use serde_json::{json,Value};
use forever_casc_worker::{profile,ProductCode,net::Http,tact::{install::{self,Event,Options},download::Cancel,verify}};

const MARKER:&str=".forever-multi-managed.json";
#[derive(Debug,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Request { action:String, directory:PathBuf, #[serde(default="default_locale")] locale:String, #[serde(default)] high_res:bool }
fn default_locale()->String{"ruRU".into()}
#[derive(Serialize,Deserialize)]
struct Owned { format:String, build:u32, build_key:String, cdn_key:String, complete:bool }
fn ownership()->Owned{Owned{format:"forever-multi-cdn-v1".into(),build:profile::BUILD,build_key:profile::BUILD_KEY.into(),cdn_key:profile::CDN_KEY.into(),complete:false}}
fn direct(path:&Path)->Result<()> {
 for part in path.ancestors().filter(|p|p.exists()) {
  let meta=fs::symlink_metadata(part)?;if meta.file_type().is_symlink(){bail!("Linked client paths are unsupported");}
  #[cfg(windows)]{use std::os::windows::fs::MetadataExt;if meta.file_attributes() & 0x400 != 0{bail!("Reparse points are unsupported");}}
 }Ok(())
}
fn claim(root:&Path,write:bool)->Result<()> {
 if !root.is_absolute(){bail!("Choose an absolute installation directory");}direct(root)?;
 for parent in root.ancestors().skip(1) {
  if parent.join(".build.info").is_file() || parent.join("Wow.exe").is_file() || parent.join("WowB.exe").is_file() {
   bail!("Choose a separate installation root outside the original game and staging folders");
  }
 }
 if root.exists(){
  if !root.is_dir(){bail!("Installation destination is not a directory");}
  let marker=root.join(MARKER);direct(&marker)?;
  if marker.exists(){let old:Owned=serde_json::from_slice(&fs::read(marker)?)?;
   if old.format!="forever-multi-cdn-v1" || old.build!=profile::BUILD || old.build_key!=profile::BUILD_KEY || old.cdn_key!=profile::CDN_KEY{bail!("Managed installation belongs to another profile");}
  } else if fs::read_dir(root)?.next().is_some() || !write {bail!("Choose a NEW empty directory; original and experimental installations are protected");}
 }else if write {fs::create_dir_all(root)?;}else{bail!("Installation directory is missing");}
 if write && !root.join(MARKER).exists(){write_owned(root,&ownership())?;}Ok(())
}
fn write_owned(root:&Path,state:&Owned)->Result<()>{let path=root.join(MARKER);direct(&path)?;forever_casc_worker::fsutil::write_atomic(&path,&serde_json::to_vec_pretty(state)?)?;Ok(())}
fn emit(value:Value){let mut out=io::stdout().lock();let _=writeln!(out,"{value}");let _=out.flush();}
fn progress(phase:&str,done:u64,total:u64,bytes:u64,bytes_total:u64,detail:impl AsRef<str>){emit(json!({"kind":"progress","phase":phase,"done":done,"total":total,"bytes":bytes,"bytesTotal":bytes_total,"detail":detail.as_ref()}));}
fn game_closed()->Result<()> {
 #[cfg(windows)] for exe in ["Wow.exe","WowB.exe"] {
  let out=std::process::Command::new("tasklist.exe").args(["/FI",&format!("IMAGENAME eq {exe}"),"/FO","CSV","/NH"]).output()?;
  if !out.status.success(){bail!("Cannot check running game processes");}
  if String::from_utf8_lossy(&out.stdout).to_lowercase().contains(&format!("\"{}\"",exe.to_lowercase())){bail!("Close the game before checking or downloading");}
 }Ok(())
}
fn loose_damage(prepared:&install::Prepared,root:&Path)->Result<Vec<String>> {
 let mut bad=Vec::new();
 for entry in prepared.install.select(&prepared.tags) {
  let relative=entry.relative_path().context("Unsafe INSTALL path")?;
  let path=root.join(&prepared.flavor).join(relative);direct(&path)?;
  let okay=fs::read(&path).is_ok_and(|body|body.len() as u64==u64::from(entry.size) && md5::compute(&body).0==entry.ckey);
  if !okay{bad.push(entry.path.clone());}
 }Ok(bad)
}
fn backup_indices(root:&Path)->Result<PathBuf>{
 let folder=root.join(".forever-multi-backups").join(format!("indices-{}",std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos()));
 direct(&folder)?;fs::create_dir_all(&folder)?;
 for entry in fs::read_dir(root.join("Data/data"))?{let entry=entry?;if entry.path().extension().is_some_and(|e|e=="idx"){direct(&entry.path())?;fs::copy(entry.path(),folder.join(entry.file_name()))?;}}
 Ok(folder)
}
async fn run(request:Request,cancel:Cancel)->Result<Value>{
 if !["download","verify","repair"].contains(&request.action.as_str()){bail!("Unsupported content action");}
 if !install::LOCALES.iter().any(|(code,_)|*code==request.locale){bail!("Unsupported game locale");}
 game_closed()?;let root=&request.directory;let write=request.action!="verify";claim(root,write)?;
 // This process-level lock is distinct from the short checkpoint/store lock.
 let operation=fs::OpenOptions::new().read(true).write(true).create(true).truncate(false).open(root.join(".forever-multi-operation.lock"))?;
 operation.try_lock().context("Another content operation is already running")?;
 let mut options=Options::default();options.region=forever_casc_worker::tact::version::Region::Eu;options.locale=request.locale.clone();options.flavor="_forever_".into();options.windows_path=None;options.concurrency=12;
 if request.high_res{options.optional_tags.push("HighRes".into());}
 let mut backup=None;
 if request.action=="verify" || request.action=="repair" {
  let report=verify::deep_scan(root,&cancel,|p|progress("verify",p.checked,p.total,p.bytes,p.bytes_total,""))?;
  if request.action=="repair" && !report.damaged.is_empty(){
   game_closed()?;backup=Some(backup_indices(root)?);
   verify::repair_unchanged(&root.join("Data/data"),&report)?;
  } else if request.action=="verify" {
   // Full payload scan is read-only; manifest planning uses an isolated cache.
   let cache=tempfile::tempdir()?;
   let http=Http::new()?;let mut quiet=|_:Event|{};
   let prepared=install::prepare(&http,cache.path(),&ProductCode::Forever,&options,&mut quiet).await?;
   let bad=loose_damage(&prepared,root)?;
   let store=forever_casc_worker::tact::storage::Storage::open(root)?;
   let present:std::collections::HashSet<[u8;9]>=store.files().map(|e|e.key).collect();
   let missing=prepared.wanted.iter().filter(|e|!present.contains::<[u8]>(&e.ekey[..9])).count();
   return Ok(json!({"complete":report.is_healthy()&&bad.is_empty()&&missing==0,"build":profile::BUILD,"checked":report.checked,"damaged":report.damaged.len(),"unverifiable":report.unverifiable,"missing":missing,"installFilesDamaged":bad,"directory":root,"gameDir":root.join("_forever_"),"readOnly":true,"runtimeTested":false}));
  }
 }
 let mut own=ownership();write_owned(root,&own)?;
 let http=Http::new()?;
 let clock=Arc::new(Mutex::new(Instant::now()-std::time::Duration::from_secs(1)));let last=clock.clone();
 let mut on_event=move|event:Event|{
  match event {
   Event::Build{..}=>progress("metadata",0,0,0,0,""),
   Event::Indices(p)=>progress("indices",p.done as u64,p.total as u64,0,0,p.hash),
   Event::Planned{files,bytes,..}=>progress("plan",0,files as u64,0,bytes,""),
   Event::Progress(p)=>{let mut time=last.lock().unwrap();if time.elapsed().as_millis()>150 || p.files_stored==p.files_total{*time=Instant::now();progress("download",p.files_stored as u64,p.files_total as u64,p.bytes_stored,p.bytes_total,"");}},
   Event::InstallFile{path,bytes}=>progress("install",0,0,bytes,0,path.to_string_lossy()),
   _=>{}
  }
 };
 let mut prepared=install::prepare(&http,root,&ProductCode::Forever,&options,&mut on_event).await?;
 // Refuse a locale fallback: Russian selection must not silently fetch English.
 if !prepared.tag_column.split_whitespace().any(|word|word==request.locale.as_str()){bail!("The pinned manifest does not ship the requested locale");}
 if prepared.wanted.is_empty(){bail!("Full selection is empty");}
 if fs2::available_space(root)? < prepared.plan.bytes().saturating_add(512*1024*1024){bail!("Insufficient disk space for the complete selected client");}
 if request.high_res {prepared.tag_column=prepared.tag_column.replace("Windows ","Windows HighRes ");}
 let selected=prepared.wanted.len();game_closed()?;
 let result=install::execute(&http,root,&ProductCode::Forever,&options,prepared,&cancel,&mut on_event).await?;
 if !result.complete{return Ok(json!({"complete":false,"paused":cancel.is_cancelled(),"build":profile::BUILD,"selected":selected,"reasons":result.reasons,"missing":result.missing,"directory":root}));}
 let checked=verify::deep_scan(root,&cancel,|p|progress("verify",p.checked,p.total,p.bytes,p.bytes_total,""))?;
 if !checked.is_healthy(){bail!("Post-download verification found {} damaged objects; use Repair",checked.damaged.len());}
 own.complete=true;write_owned(root,&own)?;
 Ok(json!({"complete":true,"build":profile::BUILD,"selected":selected,"checked":checked.checked,"unverifiable":checked.unverifiable,"directory":root,"gameDir":root.join("_forever_"),"backup":backup,"runtimeTested":false}))
}
#[tokio::main]
async fn main(){
 tracing_subscriber::fmt().with_writer(io::stderr).with_max_level(tracing::Level::WARN).init();
 let mut first=String::new();if io::stdin().read_line(&mut first).is_err()||first.len()>65536{emit(json!({"kind":"error","detail":"Invalid request"}));std::process::exit(1);}
 let request:Request=match serde_json::from_str(&first){Ok(v)=>v,Err(e)=>{emit(json!({"kind":"error","detail":e.to_string()}));std::process::exit(1);}};
 let cancel=Cancel::new();let stop=cancel.clone();
 std::thread::spawn(move||{for line in io::stdin().lock().lines(){match line{Ok(s)if s.trim()=="cancel"=>{stop.cancel();break;},Err(_)=>{stop.cancel();break;},_=>{}}}stop.cancel();});
 match run(request,cancel).await{Ok(report)=>emit(json!({"kind":"result","report":report})),Err(error)=>{emit(json!({"kind":"error","detail":format!("{error:#}")}));std::process::exit(1);}}
}

#[cfg(test)]mod tests{
 use super::*;
 #[test]fn a_new_client_must_not_be_nested_inside_the_original(){let parent=tempfile::tempdir().unwrap();let source=parent.path().join("original");fs::create_dir(&source).unwrap();fs::write(source.join(".build.info"),b"owned original").unwrap();let nested=source.join("new-empty-client");assert!(claim(&nested,true).is_err());assert!(!nested.exists());assert_eq!(fs::read(source.join(".build.info")).unwrap(),b"owned original");}
 #[test]fn an_original_installation_can_never_be_adopted_or_changed(){let parent=tempfile::tempdir().unwrap();let root=parent.path().join("original");fs::create_dir(&root).unwrap();fs::write(root.join(".build.info"),b"owned original").unwrap();assert!(claim(&root,true).is_err());assert_eq!(fs::read(root.join(".build.info")).unwrap(),b"owned original");assert!(!root.join(MARKER).exists());}
 #[test]fn a_new_directory_is_pinned_and_can_resume_only_the_same_build(){let parent=tempfile::tempdir().unwrap();let root=parent.path().join("managed");claim(&root,true).unwrap();claim(&root,true).unwrap();let mut wrong=ownership();wrong.build=70707;write_owned(&root,&wrong).unwrap();assert!(claim(&root,true).is_err());}
 #[test]fn transport_rejects_login_and_certificate_fields(){let value=json!({"action":"download","directory":"C:/new","portal":"logon.nvord.com","caFile":"other.crt"});assert!(serde_json::from_value::<Request>(value).is_err());}
}
