//! Windows: ReadProcessMemory / WriteProcessMemory on the WowB.exe process started by the launcher.

use super::Memory;
use std::ffi::c_void;
use std::path::Path;
use windows::Win32::Foundation::{CloseHandle, HANDLE, STILL_ACTIVE};
use windows::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Memory::{VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, MEM_PRIVATE, PAGE_READWRITE};
use windows::Win32::System::ProcessStatus::{GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS};
use windows::Win32::System::Threading::{
    GetExitCodeProcess, OpenProcess, PROCESS_QUERY_INFORMATION, PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE,
    QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
};

pub struct ProcessMemory {
    pid: u32,
    handle: HANDLE,
}

unsafe impl Send for ProcessMemory {}

impl Drop for ProcessMemory {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.handle);
        }
    }
}

impl ProcessMemory {
    pub fn open(pid: u32) -> Option<Self> {
        let access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION;
        let handle = unsafe { OpenProcess(access, false, pid) }.ok()?;
        Some(Self { pid, handle })
    }

    pub fn rss(&self) -> u64 {
        let mut c = PROCESS_MEMORY_COUNTERS::default();
        unsafe {
            if GetProcessMemoryInfo(self.handle, &mut c, std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32).is_ok() {
                return c.WorkingSetSize as u64 / 4096;
            }
        }
        0
    }

    pub fn matches_exe(&self, expected: &Path) -> bool {
        let mut buffer = vec![0u16; 32768];
        let mut length = buffer.len() as u32;
        if unsafe { QueryFullProcessImageNameW(self.handle, PROCESS_NAME_WIN32,
            windows::core::PWSTR(buffer.as_mut_ptr()), &mut length) }.is_err() { return false; }
        let actual = String::from_utf16_lossy(&buffer[..length as usize]);
        let expected = std::fs::canonicalize(expected).unwrap_or_else(|_| expected.to_path_buf());
        fn normalize(path: &str) -> String { path.trim_start_matches(r"\\?\").replace('/', "\\").to_lowercase() }
        normalize(&actual) == normalize(&expected.to_string_lossy())
    }
}

impl Memory for ProcessMemory {
    fn regions(&self) -> Vec<(u64, u64)> {
        let mut out = Vec::new();
        let mut addr: usize = 0;
        loop {
            let mut info = MEMORY_BASIC_INFORMATION::default();
            let n = unsafe {
                VirtualQueryEx(self.handle, Some(addr as *const c_void), &mut info, std::mem::size_of::<MEMORY_BASIC_INFORMATION>())
            };
            if n == 0 {
                break;
            }
            let base = info.BaseAddress as usize;
            if info.State == MEM_COMMIT && info.Type == MEM_PRIVATE && info.Protect == PAGE_READWRITE {
                out.push((base as u64, (base + info.RegionSize) as u64));
            }
            let next = base.saturating_add(info.RegionSize);
            if next <= addr {
                break;
            }
            addr = next;
        }
        out
    }

    fn read(&self, addr: u64, len: usize) -> Option<Vec<u8>> {
        let mut buf = vec![0u8; len];
        let mut got = 0usize;
        unsafe {
            let _ = ReadProcessMemory(self.handle, addr as *const c_void, buf.as_mut_ptr() as *mut c_void, len, Some(&mut got));
        }
        if got == 0 {
            return None;
        }
        buf.truncate(got);
        Some(buf)
    }

    fn write(&self, addr: u64, data: &[u8]) -> bool {
        let mut written = 0usize;
        unsafe {
            WriteProcessMemory(self.handle, addr as *const c_void, data.as_ptr() as *const c_void, data.len(), Some(&mut written)).is_ok()
                && written == data.len()
        }
    }

    fn alive(&self) -> bool {
        let mut code = 0u32;
        unsafe { GetExitCodeProcess(self.handle, &mut code).is_ok() && code == STILL_ACTIVE.0 as u32 }
    }

    fn pid(&self) -> u32 {
        self.pid
    }
}

/// The running WowB.exe using the most memory.
pub fn find_client() -> Option<ProcessMemory> { find(None) }

pub fn find_client_for(exe: &Path) -> Option<ProcessMemory> { find(Some(exe)) }

fn find(expected: Option<&Path>) -> Option<ProcessMemory> {
    let mut best: Option<(u64, ProcessMemory)> = None;
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
        let mut entry = PROCESSENTRY32W { dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32, ..Default::default() };
        let mut ok = Process32FirstW(snap, &mut entry).is_ok();
        while ok {
            let len = entry.szExeFile.iter().position(|c| *c == 0).unwrap_or(entry.szExeFile.len());
            let name = String::from_utf16_lossy(&entry.szExeFile[..len]);
            if name.eq_ignore_ascii_case("WowB.exe") || name.eq_ignore_ascii_case("Wow.exe") {
                if let Some(p) = ProcessMemory::open(entry.th32ProcessID) {
                    if expected.is_some_and(|exe| !p.matches_exe(exe)) {
                        ok = Process32NextW(snap, &mut entry).is_ok();
                        continue;
                    }
                    let rss = p.rss();
                    if best.as_ref().map_or(true, |(r, _)| rss > *r) {
                        best = Some((rss, p));
                    }
                }
            }
            ok = Process32NextW(snap, &mut entry).is_ok();
        }
        let _ = CloseHandle(snap);
    }
    best.map(|(_, p)| p)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn process_path_is_checked_against_the_open_handle() {
        let process = ProcessMemory::open(std::process::id()).unwrap();
        let exe = std::env::current_exe().unwrap();
        assert!(process.matches_exe(&exe));
        assert!(!process.matches_exe(&exe.parent().unwrap().join("other-copy").join(exe.file_name().unwrap())));
    }
}
