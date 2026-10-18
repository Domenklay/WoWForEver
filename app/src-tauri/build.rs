use std::path::PathBuf;
use std::process::Command;

/// macOS: the key patch library loaded into the game copy (app/macos/keypatch.c), universal so that it fits the
/// game whether it runs native or under Rosetta. Embedded in the launcher with include_bytes!.
fn build_keypatch() {
    let src = "../macos/keypatch.c";
    println!("cargo:rerun-if-changed={src}");
    let out = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("libforever_keypatch.dylib");
    let status = Command::new("clang")
        .args(["-dynamiclib", "-O2", "-Wall", "-arch", "arm64", "-arch", "x86_64", "-mmacosx-version-min=11.0", "-o"])
        .arg(&out)
        .arg(src)
        .status()
        .expect("clang not found (xcode-select --install)");
    assert!(status.success(), "building {src} failed");
}

fn main() {
    // the public certificate of your server's CA (scripts/gen-certs.sh writes it to certs/ca/forever_root_ca.crt)
    let ca = "resources/forever_root_ca.crt";
    println!("cargo:rerun-if-changed={ca}");
    if !std::path::Path::new(ca).is_file() {
        panic!("{ca} is missing: copy certs/ca/forever_root_ca.crt (never the .key) to app/src-tauri/{ca}");
    }
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        build_keypatch();
    }
    // FOREVER_CHECK_ONLY=1: lets `cargo check --target x86_64-pc-windows-gnu` run on Linux without the Windows
    // resource compiler (real builds never set it)
    if std::env::var_os("FOREVER_CHECK_ONLY").is_some() {
        println!("cargo:rustc-cfg=desktop");
        println!("cargo:rustc-check-cfg=cfg(desktop, mobile)");
        return;
    }
    tauri_build::build()
}
