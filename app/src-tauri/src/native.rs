//! Independent content worker transport. Login server, CA and sessions are never sent.
use serde::{Deserialize,Serialize};
use serde_json::{json,Value};
use std::{path::{Path,PathBuf},sync::{atomic::{AtomicBool,Ordering},mpsc},io::{BufRead,BufReader,Write},process::{Command,Stdio},time::Duration};

#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Request {pub action:String,pub directory:String,pub locale:String,pub high_res:bool}

pub fn worker_path(resource:Option<PathBuf>)->Result<PathBuf,String>{
 let home=std::env::current_exe().map_err(|e|e.to_string())?.parent().unwrap_or(Path::new(".")).to_path_buf();
 let mut candidates=vec![home.join("forever-casc-worker.exe"),home.join("binaries/forever-casc-worker.exe")];
 if let Some(root)=resource{candidates.push(root.join("binaries/forever-casc-worker.exe"));}
 candidates.into_iter().find(|p|p.is_file()).ok_or_else(||"CDN worker is missing; extract the complete Multi archive or reinstall it".into())
}
pub fn run(worker:&Path,request:Request,cancel:&AtomicBool,mut emit:impl FnMut(Value))->Result<Value,String>{
 if !["download","verify","repair"].contains(&request.action.as_str()){return Err("Unsupported download action".into());}
 let mut command=Command::new(worker);command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
 #[cfg(windows)]{use std::os::windows::process::CommandExt;command.creation_flags(0x08000000);}
 let mut child=command.spawn().map_err(|e|e.to_string())?;
 let mut input=child.stdin.take().ok_or("Worker stdin unavailable")?;
 writeln!(input,"{}",serde_json::to_string(&request).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
 let output=child.stdout.take().ok_or("Worker stdout unavailable")?;
 let errors=child.stderr.take().ok_or("Worker stderr unavailable")?;
 let (send,receive)=mpsc::channel();
 let reader=std::thread::spawn(move||{for line in BufReader::new(output).lines(){match line{Ok(s)=>{if s.len()>65536{break;}if send.send(s).is_err(){break;}},Err(_)=>break}}});
 let err_reader=std::thread::spawn(move||{let mut tail=String::new();for s in BufReader::new(errors).lines().map_while(Result::ok){tail.push_str(&s);tail.push('\n');if tail.len()>16000{let at=tail.char_indices().find(|(i,_)|*i>=tail.len()-12000).map_or(0,|(i,_)|i);tail.drain(..at);}}tail});
 let mut report=None;let mut failure=None;let mut sent_cancel=false;
 loop{
  if cancel.load(Ordering::SeqCst)&&!sent_cancel{let _=writeln!(input,"cancel");sent_cancel=true;}
  match receive.recv_timeout(Duration::from_millis(100)){
   Ok(line)=>if let Ok(value)=serde_json::from_str::<Value>(&line){match value.get("kind").and_then(Value::as_str){
    Some("progress")=>emit(value),Some("result")=>report=value.get("report").cloned(),Some("error")=>failure=value.get("detail").and_then(Value::as_str).map(str::to_owned),_=>{}}},
   Err(mpsc::RecvTimeoutError::Timeout)=>{},Err(mpsc::RecvTimeoutError::Disconnected)=>break,
  }
 }
 drop(input);let exit=child.wait().map_err(|e|e.to_string())?;let _=reader.join();let diagnostics=err_reader.join().unwrap_or_default();
 let directory=crate::config::config_dir().join("workshop/reports");std::fs::create_dir_all(&directory).map_err(|e|e.to_string())?;
 let id=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos();
 let path=directory.join(format!("native-{id}.json"));
 let mut value=report.unwrap_or_else(||json!({"complete":false,"detail":failure.clone().unwrap_or_else(||"Worker returned no report".into())}));
 value["reportPath"]=json!(path);value["workerDiagnostics"]=json!(diagnostics);
 std::fs::write(&path,serde_json::to_vec_pretty(&value).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
 if !exit.success(){return Err(format!("{} ({})",failure.unwrap_or_else(||"CDN worker failed".into()),path.display()));}
 Ok(value)
}

#[cfg(test)]mod tests{use super::*;
 #[test]fn content_requests_do_not_accept_server_or_session_configuration(){let value=json!({"action":"download","directory":"E:/new","locale":"ruRU","highRes":true,"server":{"portal":"logon.nvord.com"}});assert!(serde_json::from_value::<Request>(value).is_err());}
 #[test]fn request_serialization_keeps_only_content_inputs(){let value=serde_json::to_value(Request{action:"download".into(),directory:"E:/new".into(),locale:"ruRU".into(),high_res:true}).unwrap();assert_eq!(value.as_object().unwrap().len(),4);assert_eq!(value["locale"],"ruRU");}
}
