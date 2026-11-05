//! Linux: the game runs under Wine/Proton; its memory is reached through /proc/<pid>/mem (allowed because the
//! launcher is an ancestor of the game with the default kernel.yama.ptrace_scope = 1).

use super::Memory;
use std::fs::File;
use std::os::unix::fs::FileExt;
use std::path::Path;

pub struct ProcessMemory {
    pid: u32,
    mem: File,
}

pub fn rss_pages(pid: u32) -> u64 {
    std::fs::read_to_string(format!("/proc/{pid}/statm"))
        .ok()
        .and_then(|s| s.split_whitespace().nth(1).and_then(|v| v.parse().ok()))
        .unwrap_or(0)
}

impl ProcessMemory {
    pub fn open(pid: u32) -> Option<Self> {
        let mem = std::fs::OpenOptions::new().read(true).write(true).open(format!("/proc/{pid}/mem")).ok()?;
        Some(Self { pid, mem })
    }

    pub fn rss(&self) -> u64 {
        rss_pages(self.pid)
    }
}

impl Memory for ProcessMemory {
    fn regions(&self) -> Vec<(u64, u64)> {
        let Ok(maps) = std::fs::read_to_string(format!("/proc/{}/maps", self.pid)) else { return Vec::new() };
        maps.lines()
            .filter_map(|line| {
                let mut f = line.split_whitespace();
                let range = f.next()?;
                let perms = f.next()?;
                let inode = f.nth(2)?;
                let path = f.next().unwrap_or("");
                if perms != "rw-p" || inode != "0" || path.starts_with("[v") || path == "[stack]" {
                    return None;
                }
                let (lo, hi) = range.split_once('-')?;
                Some((u64::from_str_radix(lo, 16).ok()?, u64::from_str_radix(hi, 16).ok()?))
            })
            .collect()
    }

    fn read(&self, addr: u64, len: usize) -> Option<Vec<u8>> {
        let mut buf = vec![0u8; len];
        let n = self.mem.read_at(&mut buf, addr).ok()?;
        if n == 0 {
            return None;
        }
        buf.truncate(n);
        Some(buf)
    }

    fn write(&self, addr: u64, data: &[u8]) -> bool {
        matches!(self.mem.write_at(data, addr), Ok(n) if n == data.len())
    }

    fn alive(&self) -> bool {
        std::path::Path::new(&format!("/proc/{}", self.pid)).exists() && self.rss() > 0
    }

    fn pid(&self) -> u32 {
        self.pid
    }
}

fn is_client(pid: u32, expected: Option<&Path>) -> bool {
    // Wine sets argv[0] to the .exe path; on drives mounted without exec the .exe is not mapped from the file
    let argv0 = std::fs::read(format!("/proc/{pid}/cmdline"))
        .ok()
        .map(|c| String::from_utf8_lossy(c.split(|b| *b == 0).next().unwrap_or(&[])).replace('\\', "/").to_lowercase())
        .unwrap_or_default();
    let exe = std::fs::read_link(format!("/proc/{pid}/exe"))
        .ok()
        .and_then(|p| p.file_name().map(|n| n.to_string_lossy().to_lowercase()))
        .unwrap_or_default();
    let named_client = ["wow.exe", "wowb.exe"].iter().any(|name| argv0.ends_with(&format!("/{name}")) || argv0 == *name);
    if named_client && exe.starts_with("wine") {
        if expected.is_none() { return true; }
        let expected = expected.unwrap().to_string_lossy().replace('\\', "/").to_lowercase();
        if argv0.strip_prefix("z:").unwrap_or(&argv0) == expected { return true; }
        if let Some((_, tail)) = expected.split_once("/drive_c/") {
            if argv0 == format!("c:/{tail}") { return true; }
        }
    }
    std::fs::read_to_string(format!("/proc/{pid}/maps"))
        .map(|m| m.lines().any(|l| {
            let path = l.split_whitespace().skip(5).collect::<Vec<_>>().join(" ");
            let name = path.to_lowercase();
            if !["/wow.exe", "/wowb.exe"].iter().any(|suffix| name.ends_with(suffix)) { return false; }
            expected.map_or(true, |expected| std::fs::canonicalize(&path).ok().zip(std::fs::canonicalize(expected).ok())
                .is_some_and(|(actual, expected)| actual == expected))
        }))
        .unwrap_or(false)
}

/// The game process: the WowB.exe Wine process using the most memory (the launcher stub uses ~30 MB).
pub fn find_client() -> Option<ProcessMemory> { find(None) }

pub fn find_client_for(exe: &Path) -> Option<ProcessMemory> { find(Some(exe)) }

fn find(expected: Option<&Path>) -> Option<ProcessMemory> {
    let me = std::process::id();
    let mut best: Option<(u64, u32)> = None;
    for entry in std::fs::read_dir("/proc").ok()?.flatten() {
        let Some(pid) = entry.file_name().to_str().and_then(|s| s.parse::<u32>().ok()) else { continue };
        if pid == me || !is_client(pid, expected) {
            continue;
        }
        let rss = rss_pages(pid);
        if best.map_or(true, |(r, _)| rss > r) {
            best = Some((rss, pid));
        }
    }
    best.and_then(|(_, pid)| ProcessMemory::open(pid))
}
