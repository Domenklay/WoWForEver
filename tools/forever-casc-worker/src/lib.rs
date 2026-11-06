//! Separate GPL-3.0-or-later worker. No launcher sessions, login routes or CA settings.
pub mod buildinfo;
pub mod net;
pub mod profile;
pub mod tact;
pub use product::ProductCode;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActionState { Install, Play, Update { local_build: String, remote_build: String } }

pub mod product {
    use std::{borrow::Cow, fmt, str::FromStr};
    use serde::{Serialize, Deserialize};
    #[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
    #[serde(from="String", into="String")]
    pub enum ProductCode { Retail, Classic, ClassicEra, Ptr, ClassicBeta, Forever, Custom(String) }
    impl ProductCode {
        pub fn as_str(&self) -> &str { match self { Self::Retail=>"wow",Self::Classic=>"wow_classic",Self::ClassicEra=>"wow_classic_era",Self::Ptr=>"wowt",Self::ClassicBeta=>"wow_classic_beta",Self::Forever=>"wowf",Self::Custom(s)=>s } }
        pub fn install_dir(&self) -> Cow<'_,str> { Cow::Borrowed(match self { Self::Retail=>"_retail_",Self::Classic=>"_classic_",Self::ClassicEra=>"_classic_era_",Self::Ptr=>"_ptr_",Self::ClassicBeta=>"_classic_beta_",Self::Forever=>"_forever_",Self::Custom(_)=>"_custom_" }) }
    }
    impl FromStr for ProductCode { type Err=std::convert::Infallible; fn from_str(s:&str)->Result<Self,Self::Err>{Ok(match s { "wow"=>Self::Retail,"wow_classic"=>Self::Classic,"wow_classic_era"=>Self::ClassicEra,"wowt"=>Self::Ptr,"wow_classic_beta"=>Self::ClassicBeta,"wowf"=>Self::Forever,_=>Self::Custom(s.into()) })} }
    impl From<String> for ProductCode {fn from(s:String)->Self{s.parse().unwrap()}}
    impl From<ProductCode> for String {fn from(p:ProductCode)->Self{p.as_str().into()}}
    impl fmt::Display for ProductCode {fn fmt(&self,f:&mut fmt::Formatter<'_>)->fmt::Result{f.write_str(self.as_str())}}
}

pub mod text { pub fn hex(bytes:&[u8])->String{hex::encode(bytes)} }
pub mod error {
    pub fn chain(error:&dyn std::error::Error)->String {
        let mut text=error.to_string();let mut source=error.source();
        while let Some(cause)=source {let message=cause.to_string();if !text.ends_with(&message){text.push_str(": ");text.push_str(&message);}source=cause.source();}text
    }
}
pub mod logging {
    pub struct Throttle(std::sync::atomic::AtomicU64);
    impl Throttle {
        pub const fn new()->Self{Self(std::sync::atomic::AtomicU64::new(0))}
        pub fn pass(&self,every:u64)->Option<u64>{use std::sync::atomic::Ordering::Relaxed;let now=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs();let old=self.0.load(Relaxed);if now.saturating_sub(old)<every{return None;}self.0.store(now,Relaxed);Some(0)}
    }
}
pub mod preflight {
    #[derive(Debug,thiserror::Error)] #[error("download guard failed")] pub struct PreflightError;
    pub trait DownloadGuard {
        fn pause(&mut self,code:&crate::ProductCode)->Result<bool,PreflightError>;
        fn resume(&mut self,code:&crate::ProductCode)->Result<bool,PreflightError>;
    }
}
pub mod paths {
    pub enum Repaired { Yes, No }
    pub fn ensure_writable(dir:&std::path::Path)->std::io::Result<Repaired>{std::fs::create_dir_all(dir)?;let probe=tempfile::NamedTempFile::new_in(dir)?;drop(probe);Ok(Repaired::No)}
}
pub mod fsutil {
    use std::{io::{self,Write},path::Path};
    pub fn write_atomic(path:&Path,bytes:&[u8])->io::Result<()>{write_atomic_with_mode(path,bytes,0o644)}
    pub fn write_atomic_with_mode(path:&Path,bytes:&[u8],mode:u32)->io::Result<()>{
        let parent=path.parent().unwrap_or(Path::new("."));std::fs::create_dir_all(parent)?;
        let mut file=tempfile::NamedTempFile::new_in(parent)?;file.write_all(bytes)?;
        #[cfg(unix)] {use std::os::unix::fs::PermissionsExt;file.as_file().set_permissions(std::fs::Permissions::from_mode(mode))?;}
        #[cfg(not(unix))] let _=mode;
        file.as_file().sync_all()?;file.persist(path).map_err(|e|e.error)?;Ok(())
    }
    pub fn dir_size(dir:&Path)->u64{std::fs::read_dir(dir).ok().into_iter().flatten().flatten().map(|e|if e.file_type().is_ok_and(|t|t.is_dir()){dir_size(&e.path())}else{e.metadata().map_or(0,|m|m.len())}).sum()}
}
