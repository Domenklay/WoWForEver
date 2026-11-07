//! Public release-set metadata. Payloads always come from exact commits in our repository.
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap,HashSet};

pub const URL:&str="https://raw.githubusercontent.com/Domenklay/WoWForEver/main/addons/channels.json";
pub const BUNDLED:&str=include_str!("../../../addons/channels.json");
pub const LIMIT:u64=512*1024;
#[derive(Clone,Debug,Default,Serialize,Deserialize,PartialEq,Eq)]
#[serde(rename_all="lowercase")]
pub enum Channel { #[default] Stable, Testing }
impl Channel {pub fn key(&self)->&'static str {match self {Self::Stable=>"stable",Self::Testing=>"testing"}}}
#[derive(Clone,Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Catalog {pub format:String,pub revision:String,pub channels:BTreeMap<String,Release>}
#[derive(Clone,Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Release {pub release:String,pub client_build:u32,pub addons:Vec<Manifest>}
#[derive(Clone,Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Manifest {pub name:String,pub version:String,pub protocol:u32,pub source_commit:String,pub source_path:String,pub files:Vec<Entry>}
#[derive(Clone,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Entry {pub name:String,pub size:u64,pub sha256:String}
pub fn source_path(name:&str)->Result<&'static str,String>{match name {
 "ForeverAscension"=>Ok("mods/forever-advancement/addon/ForeverAscension"),
 "ForeverEncyclopedia"=>Ok("mods/living-encyclopedia/addon/ForeverEncyclopedia"),
 _=>Err("Unsupported project AddOn".into())}}
fn token(s:&str,max:usize)->bool{!s.is_empty()&&s.len()<=max&&s.bytes().all(|c|c.is_ascii_alphanumeric()||b"._+-".contains(&c))}
pub fn file_path(s:&str)->bool{
 if s.is_empty()||s.len()>220 {return false;}
 s.split('/').all(|p|!p.is_empty()&&!p.starts_with('.')&&!p.ends_with('.')&&p.bytes().all(|c|c.is_ascii_alphanumeric()||b"._-".contains(&c))&& !matches!(p.split('.').next().unwrap_or("").to_ascii_uppercase().as_str(),"CON"|"PRN"|"AUX"|"NUL"|"COM1"|"COM2"|"COM3"|"COM4"|"COM5"|"COM6"|"COM7"|"COM8"|"COM9"|"LPT1"|"LPT2"|"LPT3"|"LPT4"|"LPT5"|"LPT6"|"LPT7"|"LPT8"|"LPT9"))
 && matches!(s.rsplit('.').next().unwrap_or("").to_ascii_lowercase().as_str(),"lua"|"toc"|"xml"|"blp"|"tga"|"png"|"jpg"|"jpeg"|"ttf"|"ogg"|"mp3"|"wav"|"txt"|"csv")
}
pub fn validate_manifest(m:&Manifest)->Result<(),String>{
 let protocol=match m.name.as_str(){"ForeverAscension"=>3,"ForeverEncyclopedia"=>1,_=>return Err("Unsupported project AddOn".into())};
 if m.source_path!=source_path(&m.name)?||!token(&m.version,100)||m.protocol!=protocol||m.source_commit.len()!=40||!m.source_commit.bytes().all(|c|c.is_ascii_digit()||b"abcdef".contains(&c))||m.files.is_empty()||m.files.len()>2048{return Err("Incompatible AddOn release".into());}
 let mut seen=HashSet::new();let mut total=0u64;
 for f in &m.files {if !file_path(&f.name)||!seen.insert(f.name.to_ascii_lowercase())||f.size>32*1024*1024||f.sha256.len()!=64||!f.sha256.bytes().all(|c|c.is_ascii_digit()||b"abcdef".contains(&c)){return Err("Unsafe AddOn file manifest".into());}total=total.saturating_add(f.size);}
 if total>128*1024*1024||!m.files.iter().any(|f|f.name==format!("{}.toc",m.name)){return Err("Incomplete AddOn manifest".into());}Ok(())
}
pub fn parse(text:&str)->Result<Catalog,String>{
 if text.len()as u64>LIMIT{return Err("AddOn catalogue exceeds size limit".into());}
 let c:Catalog=serde_json::from_str(text).map_err(|e|e.to_string())?;
 if c.format!="forever-addon-channels-v1"||!token(&c.revision,100)||c.channels.len()!=2||!c.channels.contains_key("stable")||!c.channels.contains_key("testing"){return Err("Invalid AddOn channel catalogue".into());}
 for r in c.channels.values(){
  if r.client_build!=70658||!token(&r.release,100)||r.addons.len()!=2{return Err("Incompatible AddOn set".into());}
  let mut seen=HashSet::new();for m in &r.addons{validate_manifest(m)?;if !seen.insert(&m.name){return Err("Duplicate AddOn in release set".into());}}
 }Ok(c)
}
pub fn url(m:&Manifest,f:&Entry)->String{format!("https://raw.githubusercontent.com/Domenklay/WoWForEver/{}/{}/{}",m.source_commit,m.source_path,f.name)}
#[cfg(test)]mod tests{
 use super::*;
 #[test]fn initial_testing_set_uses_real_approved_payloads_and_protocols(){let c=parse(BUNDLED).unwrap();let a=&c.channels["stable"];let b=&c.channels["testing"];assert_eq!(a.addons.len(),2);assert_eq!(serde_json::to_value(&a.addons).unwrap(),serde_json::to_value(&b.addons).unwrap());}
 #[test]fn invalid_channel_paths_versions_and_protocols_are_rejected(){
  let base:serde_json::Value=serde_json::from_str(BUNDLED).unwrap();
  for (key,value) in [("sourceCommit","main"),("sourcePath","../../outside"),("version","bad/version")]{let mut c=base.clone();c["channels"]["testing"]["addons"][0][key]=value.into();assert!(parse(&c.to_string()).is_err());}
  let mut c=base.clone();c["channels"]["testing"]["clientBuild"]=70707.into();assert!(parse(&c.to_string()).is_err());
  let mut c=base;c["channels"]["testing"]["addons"][0]["protocol"]=4.into();assert!(parse(&c.to_string()).is_err());
  for path in ["../x.lua","foo/../../x.lua","/x.lua","x\\x.lua","CON.lua","x.exe","a/X.lua/../x.lua","a//x.lua"]{assert!(!file_path(path),"{path}");}
  assert!(file_path("Textures/book.tga"));
 }
 #[test]fn unknown_channel_cannot_silently_become_stable(){assert!(serde_json::from_str::<Channel>("\"nightly\"").is_err());}
}
