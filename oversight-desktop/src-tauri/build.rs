fn main() {
    // The Clans address is built in (main.rs, CLANS_URL).
    println!("cargo:rerun-if-env-changed=OVERSIGHT_CLANS_URL");
    // Listing the app's commands makes each one need a permission, so a window can call
    // only what its capability file allows (capabilities/main.json).
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["core"])),
    )
    .expect("failed to run tauri-build");
}
