use std::fs;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

fn bounded_status(command: &mut Command) -> std::process::ExitStatus {
    let mut child = command.stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(status) = child.try_wait().unwrap() { return status; }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("read-only config check exceeded its deadline");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

#[test]
fn runtime_manifest_cli_config_errors_exit_nonzero_without_output_capture() {
    let executable = std::env::current_exe()
        .expect("integration test executable path")
        .parent()
        .and_then(std::path::Path::parent)
        .expect("Cargo target debug directory")
        .join(format!(
            "jawl-companion-client{}",
            std::env::consts::EXE_SUFFIX
        ));

    let missing_argument = bounded_status(Command::new(&executable)
        .args(["--check-config", "--repo-root"]));
    assert!(!missing_argument.success());

    let id = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("jawl-cli-config-{}-{id}", std::process::id()));
    let config = root.join("config");
    fs::create_dir_all(&config).unwrap();
    fs::write(config.join("runtime.manifest.json"), "{").unwrap();
    let malformed_manifest = bounded_status(Command::new(&executable)
        .args(["--repo-root", root.to_str().unwrap(), "--check-config"]));
    let _ = fs::remove_dir_all(root);
    assert!(!malformed_manifest.success());
}
