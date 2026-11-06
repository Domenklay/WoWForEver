//! Pinned 70658 package; CDN data never supplies Multi's login/realm configuration.
use crate::{ProductCode,tact::{install::{Options,InstallError},version::{Cdn,Version}}};
pub const BUILD:u32=70658;
pub const BUILD_KEY:&str="165410aca770316ea0f88100bb4830c2";
pub const CDN_KEY:&str="f0fcf03baf658e38f2f6c96a77798a2c";
pub const SOURCES:&[&str]=&[
 "http://cdn.nvord.com","http://dl.nvord.com","http://mirror.nvord.com",
 "http://62.109.28.250","http://62.109.6.21","http://62.109.22.162",
 "http://141.94.102.199","http://198.244.202.75","http://135.125.223.199",
 "http://135.125.223.200","http://135.125.223.201","http://135.125.223.202",
 "http://198.27.80.36","http://144.217.76.139",
 "https://us.cdn.blizzard.com","https://level3.ssl.blizzard.com",
 "http://eu.cdn.blizzard.com","http://us.cdn.blizzard.com","http://cdn.blizzard.com","http://level3.blizzard.com"
];
pub fn resolve(code:&ProductCode,options:&Options)->Result<(Version,Cdn),InstallError>{
 if code.as_str()!="wowf" || options.stage {return Err(InstallError::MissingManifest("pinned wowf 70658 profile"));}
 Ok((Version{region:"eu".into(),build_config:BUILD_KEY.into(),cdn_config:CDN_KEY.into(),key_ring:None,
 build_id:BUILD,versions_name:format!("1.60.1.{BUILD}"),product_config:String::new()},
 Cdn{name:"eu".into(),path:"tpr/wow".into(),hosts:vec!["mirror.nvord.com".into(),"cdn.nvord.com".into(),"dl.nvord.com".into()],
 servers:SOURCES.iter().map(|s|(*s).into()).collect(),config_path:"tpr/configs/data".into()}))
}
#[cfg(test)]mod tests{use super::*;
 #[test]fn package_pin_cannot_follow_the_live_version_service(){let(v,_)=resolve(&ProductCode::Forever,&Options::default()).unwrap();assert_eq!(v.build_id,70658);assert_eq!(v.build_config,BUILD_KEY);assert_eq!(v.cdn_config,CDN_KEY);}
 #[test]fn login_routes_and_launcher_updater_feed_are_not_content_sources(){assert!(SOURCES.iter().all(|s|!s.contains("logon")&&!s.contains("chat")&&!s.contains("launcher.json")&&!s.contains("127.0.0.1")));}
}
