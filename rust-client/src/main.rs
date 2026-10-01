//! JAWL Companion native client (C1/C2: mic stream + native Live2D avatar).
//!
//! ADR-036: a thin native client owns the audio devices and hosts the Live2D
//! character window / OBS surface. The web panel stays as the control/pult.
//!
//! Modes (pick one):
//!   --mic     own the microphone and stream 16 kHz mono s16le into the
//!             companion's /api/voice/audio (proven in Phase B).
//!   --webview open the OBS presentation window.
//!   --all     launch the whole supervised stack and hold it.
//! (ADR-045: the Live2D --avatar mode and the Mocari runtime are removed;
//! the 3D VRM avatar lives in the Electron desktop shell, desktop/.)

use base64::Engine as _;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Deserialize;
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const COMPANION_URL: &str = "http://127.0.0.1:2367";
const TARGET_RATE: u32 = 16_000;
const CHUNK_SECONDS: f32 = 1.0;
/// Canonical runtime manifest (ADR-041): every machine-specific path, port and
/// profile lives in config/runtime.manifest.json (with a local override). The
/// client falls back to the dev-machine defaults below only when the manifest
/// is missing, so a shipped build never hardcodes another machine's layout.
const MANIFEST_REL: &str = "config/runtime.manifest.json";

#[derive(Debug, Deserialize)]
struct RuntimeManifest {
    #[serde(default)]
    repo_root: Option<String>,
    #[serde(default)]
    profile: Option<String>,
    #[serde(default)]
    ports: ManifestPorts,
    #[serde(default)]
    models: ManifestModels,
    #[serde(default)]
    mic: ManifestMic,
    #[serde(default)]
    brain: ManifestBrain,
    #[serde(default)]
    profile_script: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct ManifestPorts {
    #[serde(default)] control: Option<u16>,
    #[serde(default)] presentation: Option<u16>,
    #[serde(default)] jawl_console: Option<u16>,
    #[serde(default)] opencode_relay: Option<u16>,
    #[serde(default)] qwen3_vl: Option<u16>,
    #[serde(default)] bonsai_coding: Option<u16>,
}

#[derive(Debug, Default, Deserialize)]
struct ManifestModels {
    #[serde(default)] llama_server_exe: Option<String>,
    #[serde(default)] qwen3_vl_model: Option<String>,
    #[serde(default)] qwen3_vl_mmproj: Option<String>,
    #[serde(default)] bonsai_model: Option<String>,
    #[serde(default)] bonsai_mmproj: Option<String>,
}

/// The manifest's avatar.model3_path entry is obsolete (ADR-045); only
/// mic_prefer survives, moved under "mic".
#[derive(Debug, Default, Deserialize)]
struct ManifestMic {
    #[serde(default)] prefer: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct ManifestBrain {
    #[serde(default)] model: Option<String>,
    #[serde(default)] provider: Option<String>,
    #[serde(default)] use_relay: Option<bool>,
}


/// Runtime configuration resolved from the manifest (or dev defaults).
struct RuntimeConfig {
    repo_root: PathBuf,
    profile: String,
    control_port: u16,
    presentation_port: u16,
    jawl_console_port: u16,
    relay_port: u16,
    qwen3_vl_port: u16,
    bonsai_port: u16,
    llama_server_exe: PathBuf,
    qwen3_vl_model: PathBuf,
    qwen3_vl_mmproj: PathBuf,
    bonsai_model: PathBuf,
    bonsai_mmproj: PathBuf,
    mic_prefer: String,
    brain_model: String,
    brain_use_relay: bool,
    profile_script: PathBuf,
}

impl RuntimeConfig {
    fn load() -> Self {
        let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf()));
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        // Manifest lookup: CWD config/runtime.manifest.json, then exe-adjacent.
        let mut manifest_path = cwd.join(MANIFEST_REL);
        let mut repo = cwd.clone();
        if let Some(exe_dir) = &exe_dir {
            let alt = exe_dir.join(MANIFEST_REL);
            if !manifest_path.exists() && alt.exists() { manifest_path = alt; }
        }
        let m: Option<RuntimeManifest> = std::fs::read_to_string(&manifest_path)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok());
        if let Some(m) = &m {
            if let Some(root) = &m.repo_root { repo = PathBuf::from(root); }
        }
        let d = Self::defaults(&repo);
        // Overlay manifest fields.
        let mut out = d;
        if let Some(m) = m {
            if let Some(root) = m.repo_root { out.repo_root = PathBuf::from(root); }
            if let Some(p) = m.profile { out.profile = p; }
            if let Some(v) = m.ports.control { out.control_port = v; }
            if let Some(v) = m.ports.presentation { out.presentation_port = v; }
            if let Some(v) = m.ports.jawl_console { out.jawl_console_port = v; }
            if let Some(v) = m.ports.opencode_relay { out.relay_port = v; }
            if let Some(v) = m.ports.qwen3_vl { out.qwen3_vl_port = v; }
            if let Some(v) = m.ports.bonsai_coding { out.bonsai_port = v; }
            if let Some(v) = m.models.llama_server_exe { out.llama_server_exe = PathBuf::from(v); }
            if let Some(v) = m.models.qwen3_vl_model { out.qwen3_vl_model = PathBuf::from(v); }
            if let Some(v) = m.models.qwen3_vl_mmproj { out.qwen3_vl_mmproj = PathBuf::from(v); }
            if let Some(v) = m.models.bonsai_model { out.bonsai_model = PathBuf::from(v); }
            if let Some(v) = m.models.bonsai_mmproj { out.bonsai_mmproj = PathBuf::from(v); }
            if let Some(v) = m.mic.prefer { out.mic_prefer = v; }
            if let Some(v) = m.brain.model { out.brain_model = v; }
            if let Some(v) = m.brain.use_relay { out.brain_use_relay = v; }
            if let Some(v) = m.profile_script { out.profile_script = out.repo_root.join(v); }
        }
        out
    }

    /// Dev-machine defaults (kept as fallback; the manifest is authoritative).
    fn defaults(repo: &PathBuf) -> Self {
        let root = repo.clone();
        Self {
            repo_root: root.clone(),
            profile: "daily".to_string(),
            control_port: 2367,
            presentation_port: 8766,
            jawl_console_port: 8770,
            relay_port: 8891,
            qwen3_vl_port: 8983,
            bonsai_port: 8986,
            llama_server_exe: PathBuf::from(r"G:\AI\llamacpp-taardis\build\bin\llama-server.exe"),
            qwen3_vl_model: PathBuf::from(r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-Q4_K_M.gguf"),
            qwen3_vl_mmproj: PathBuf::from(r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-mmproj-F16.gguf"),
            bonsai_model: PathBuf::from(r"G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-Q1_0.gguf"),
            bonsai_mmproj: PathBuf::from(r"G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-mmproj-Q8_0.gguf"),
            mic_prefer: "fifine".to_string(),
            // Default brain: the local Hikari stack (owner decision
            // 2026-09-29). The relay profile stays opt-in via the manifest.
            brain_model: "local-bonsai2".to_string(),
            brain_use_relay: false,
            profile_script: root.join(r"scripts\run_integrated_profile.ps1"),
        }
    }
}

#[derive(Debug, Deserialize)]
struct Health { status: String, mode: String }
#[derive(Debug, Deserialize)]
struct Session { csrf_token: String }
struct CompanionSession { cookie: String, csrf: String }

fn check_companion() -> Result<(), String> {
    let resp: Health = ureq::get(&format!("{COMPANION_URL}/api/health"))
        .timeout(Duration::from_secs(5)).call()
        .map_err(|e| format!("companion unreachable: {e}"))?
        .into_json().map_err(|e| format!("bad health json: {e}"))?;
    println!("[companion] status={} mode={}", resp.status, resp.mode);
    Ok(())
}

fn open_session_at(base: &str) -> Result<CompanionSession, String> {
    let resp = ureq::get(&format!("{base}/api/session"))
        .timeout(Duration::from_secs(5)).call()
        .map_err(|e| format!("session handshake failed: {e}"))?;
    let cookie = resp.header("set-cookie")
        .map(|c| c.split(';').next().unwrap_or("").to_string()).unwrap_or_default();
    let body: Session = serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?)
        .map_err(|e| format!("bad session json: {e}"))?;
    Ok(CompanionSession { cookie, csrf: body.csrf_token })
}

fn open_session() -> Result<CompanionSession, String> {
    open_session_at(COMPANION_URL)
}

fn to_s16le_16k(samples: &[f32], src_rate: u32) -> Vec<u8> {
    let ratio = src_rate as f32 / TARGET_RATE as f32;
    let out_len = (samples.len() as f32 / ratio) as usize;
    let mut out = Vec::with_capacity(out_len * 2);
    for i in 0..out_len {
        let src = (i as f32 * ratio) as usize;
        let s = samples.get(src).copied().unwrap_or(0.0).clamp(-1.0, 1.0);
        out.extend_from_slice(&((s * i16::MAX as f32) as i16).to_le_bytes());
    }
    out
}

fn companion_base_url() -> String {
    // The control port is manifest-owned (ADR-041); a profile started with a
    // different port must not leave the mic lane talking to a dead endpoint.
    // --port N (any argument position) overrides it for disposable profiles.
    let arg_port = std::env::args().position(|a| a == "--port")
        .and_then(|pos| std::env::args().nth(pos + 1))
        .and_then(|v| v.parse::<u16>().ok());
    let port = arg_port.unwrap_or_else(|| RuntimeConfig::load().control_port);
    format!("http://127.0.0.1:{port}")
}

fn run_mic(running: Arc<AtomicBool>) {
    println!("[mode] mic -> companion stream");
    let base = companion_base_url();
    println!("[companion] base url: {base}");
    let resp: Result<Health, _> = ureq::get(&format!("{base}/api/health"))
        .timeout(Duration::from_secs(5)).call()
        .map_err(|e| format!("companion unreachable: {e}"))
        .and_then(|r| r.into_json().map_err(|e| format!("bad health json: {e}")));
    match resp { Ok(h) => println!("[companion] status={} mode={}", h.status, h.mode), Err(e) => eprintln!("[companion] {e}") }
    let session = open_session_at(&base).ok();
    if session.is_some() { println!("[companion] session established"); }

    let host = cpal::default_host();
    // Prefer the owner's real microphone (manifest mic_prefer) over a
    // virtual/headset default; fall back to the OS default when absent.
    let mic_prefer = RuntimeConfig::load().mic_prefer.to_lowercase();
    let device = {
        let mut chosen = host.default_input_device();
        if !mic_prefer.is_empty() {
            for d in host.input_devices().into_iter().flatten() {
                if let Ok(name) = d.name() {
                    if name.to_lowercase().contains(&mic_prefer) {
                        println!("[mic] selected device: {name}");
                        chosen = Some(d);
                        break;
                    }
                }
            }
        }
        match chosen { Some(d) => d, None => { eprintln!("[mic] no input device"); return; } }
    };
    let config = match device.default_input_config() { Ok(c) => c, Err(e) => { eprintln!("[mic] no input config: {e}"); return; } };
    let src_rate = config.sample_rate().0;
    let channels = config.channels() as usize;
    println!("[mic] {} Р’В· {} Hz Р’В· {} ch -> {} Hz mono", device.name().unwrap_or_default(), src_rate, channels, TARGET_RATE);

    let buf: Arc<Mutex<VecDeque<f32>>> = Arc::new(Mutex::new(VecDeque::new()));
    let buf2 = buf.clone();
    let stream = device.build_input_stream(&config.into(), move |data: &[f32], _| {
        let mut g = buf2.lock().unwrap();
        for frame in data.chunks(channels.max(1)) {
            g.push_back(frame.iter().sum::<f32>() / frame.len() as f32);
        }
        let cap = (src_rate as f32 * 30.0) as usize;
        while g.len() > cap { g.pop_front(); }
    }, |e| eprintln!("[mic] stream error: {e}"), None).expect("input stream");
    stream.play().expect("play");

    // End-of-utterance: when the mic stays quiet for SILENCE_SECONDS after
    // speech, the utterance is complete. The companion transcribes the buffer
    // (GigaAM) and answers; the native client owns the whole voice turn, which
    // is the ADR-036 audio-owner contract (the browser lane no longer owns
    // the microphone).
    const SILENCE_SECONDS: usize = 2;
    const SPEECH_PEAK: f32 = 0.02;
    let mut saw_speech = false;
    let mut silent_chunks: usize = 0;
    while running.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis((CHUNK_SECONDS * 1000.0) as u64));
        let raw: Vec<f32> = { let mut g = buf.lock().unwrap(); g.drain(..).collect() };
        if raw.len() < (src_rate as f32 * 0.2) as usize { continue; }
        let peak = raw.iter().fold(0.0f32, |a, &b| a.max(b.abs()));
        if peak >= SPEECH_PEAK {
            saw_speech = true;
            silent_chunks = 0;
        } else if saw_speech {
            silent_chunks += 1;
        }
        if saw_speech && silent_chunks >= SILENCE_SECONDS {
            // Finalize the utterance before continuing capture: the server
            // transcribes this session's buffer and returns the reply.
            saw_speech = false;
            silent_chunks = 0;
            println!("[voice] silence after speech -> finishing utterance");
            if let Some(s) = &session {
                let mut req = ureq::post(&format!("{base}/api/voice/end"))
                    .set("Content-Type", "application/json")
                    .set("Cookie", &s.cookie)
                    .set("X-Companion-CSRF", &s.csrf)
                    .timeout(Duration::from_secs(180));
                let payload = serde_json::json!({ "session_id": "rust-client" });
                match req.send_string(&payload.to_string()) {
                    Ok(r) => {
                        let status = r.status();
                        match r.into_string() {
                            Ok(body) => print_voice_final(status, &body),
                            Err(e) => eprintln!("[voice] read reply failed: {e}"),
                        }
                    }
                    Err(e) => eprintln!("[voice] end failed: {e}"),
                }
            } else {
                eprintln!("[voice] no companion session; cannot finish utterance");
            }
            continue;
        }
        let pcm = to_s16le_16k(&raw, src_rate);
        if pcm.is_empty() { continue; }
        let b64 = base64::engine::general_purpose::STANDARD.encode(&pcm);
        let payload = serde_json::json!({ "pcm16_base64": b64, "sample_rate": TARGET_RATE, "channels": 1, "session_id": "rust-client" });
        let mut req = ureq::post(&format!("{base}/api/voice/audio")).set("Content-Type", "application/json").timeout(Duration::from_secs(10));
        if let Some(s) = &session { req = req.set("Cookie", &s.cookie).set("X-Companion-CSRF", &s.csrf); }
        match req.send_string(&payload.to_string()) {
            Ok(r) => println!("[stream] {} B (peak {:.3}) -> {}", pcm.len(), peak, r.status()),
            Err(e) => eprintln!("[stream] send failed: {e}"),
        }
    }
    drop(stream);
    println!("[mic] stopped");
}

/// Print the finalized voice turn: transcript plus the companion's reply.
fn print_voice_final(status: u16, body: &str) {
    let parsed: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => { println!("[voice] final -> {status} (non-json body)"); return; }
    };
    let transcript = parsed.get("transcript").and_then(|t| t.as_str()).unwrap_or("");
    let ok = parsed.get("ok").and_then(|o| o.as_bool());
    println!("[voice] final -> {status} ok={:?} transcript={:?}", ok, transcript);
    if let Some(responses) = parsed.get("responses").and_then(|r| r.as_array()) {
        for response in responses {
            let text = response.get("text").and_then(|t| t.as_str()).unwrap_or("");
            if !text.is_empty() { println!("[companion] {text}"); }
        }
    }
}

/// window alive (so the user sees status and nothing silently closes).
///
/// Order matters: model servers first (they load slowly), then the integrated
/// profile launcher which waits for them. All children stay alive as long as
/// this process runs; closing the window stops them.
fn run_all() {
    use std::process::{Child, Command, Stdio};
    use std::net::TcpStream;

    let cfg = RuntimeConfig::load();
    println!("[launcher] repo={} profile={}", cfg.repo_root.display(), cfg.profile);

    let port_open = |port: u16| TcpStream::connect(("127.0.0.1", port)).is_ok();

    let mut children: Vec<Child> = Vec::new();

    // Qwen3-VL screen-watch describer on the manifest vision port — the only
    // always-on vision model. Bonsai 27B was dropped from the default profile
    // (ADR-040); heavy analysis stays manual via run_coding_server.ps1.
    let vl_port = cfg.qwen3_vl_port;
    let vl_exe = cfg.llama_server_exe.to_string_lossy().to_string();
    let vl_model = cfg.qwen3_vl_model.to_string_lossy().to_string();
    let vl_mmproj = cfg.qwen3_vl_mmproj.to_string_lossy().to_string();
    if !port_open(vl_port) {
        let args = [
            "--model", &vl_model,
            "--alias", "qwen3-vl", "--host", "127.0.0.1", "--port", &vl_port.to_string(),
            "--ctx-size", "8192", "--threads", "4", "-ngl", "99",
            "--no-webui", "--reasoning", "off",
            "--mmproj", &vl_mmproj,
        ];
        let mut cmd = Command::new(&vl_exe);
        cmd.args(args).stdout(Stdio::null()).stderr(Stdio::null());
        // Low priority: periodic screen scans must not micro-freeze the
        // interactive workload (vision encoder + mmproj run on CPU threads).
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x00004000;
            cmd.creation_flags(BELOW_NORMAL_PRIORITY_CLASS);
        }
        if let Ok(c) = cmd.spawn() { children.push(c); println!("[launcher] qwen3-vl starting ({vl_port}, below-normal priority)"); }
    } else { println!("[launcher] qwen3-vl already up ({vl_port})"); }

    // Wait for the vision server to accept connections before the profile.
    {
        let deadline = std::time::Instant::now() + Duration::from_secs(120);
        while !port_open(vl_port) && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(800));
        }
        println!("[launcher] qwen3-vl port {vl_port} {}", if port_open(vl_port) { "up" } else { "TIMEOUT" });
    }

    // Integrated profile (companion + JAWL + voice + brain) from the manifest.
    // With use_relay=false the local brain (Hikari) must be RAISED with the
    // stack: the bare launcher fails closed without a provider key, so the
    // wrapper script is used - it holds the brain worker and sets the env.
    if !port_open(cfg.control_port) {
        let current_dir = cfg.repo_root.clone();
        let brain_model = cfg.brain_model.clone();
        let use_relay = cfg.brain_use_relay;
        let script = if use_relay {
            cfg.profile_script.to_string_lossy().to_string()
        } else {
            // The wrapper: brain holder + provider env + the same profile.
            cfg.repo_root.join(r"scripts\run_local_bonsai_integrated.ps1").to_string_lossy().to_string()
        };
        let prof_script = script.clone();
        let mut args: Vec<String> = vec![
            "-NoProfile".into(), "-ExecutionPolicy".into(), "Bypass".into(),
            "-File".into(), prof_script,
            "-ProfileName".into(), cfg.profile.clone(),
            "-UseVoiceMem".into(),
            "-TtsProvider".into(), "tera".into(),
            "-JawlModelOverride".into(), brain_model,
            "-StartupTimeoutSeconds".into(), "420".into(),
        ];
        if use_relay {
            // Relay profile: the full sensory/vision stack belongs to it.
            args.extend(["-StartLocalAudio".into(), "-EnableProsodyPlanner".into(),
                         "-EnableStreamingAsr".into(), "-EnableScreenWatch".into(),
                         "-EnableSensoryWorker".into(), "-AmbientTriageSeconds".into(), "300".into(),
                         "-UseOpenCodeRelay".into()]);
        } else {
            // Local brain wrapper owns its audio args (-StartLocalAudio).
            args.push("-StartLocalAudio".into());
        }
        let prof = Command::new("powershell")
            .args(&args)
            .current_dir(&current_dir)
            .spawn();
        match prof {
            Ok(c) => { children.push(c); println!("[launcher] integrated profile starting (brain: {})", if use_relay { "relay" } else { "local-hikari" }); }
            Err(e) => eprintln!("[launcher] profile spawn failed: {e}"),
        }
    } else { println!("[launcher] profile already up ({})", cfg.control_port); }

    // Report readiness, then keep the window alive until Ctrl+C.
    let deadline = std::time::Instant::now() + Duration::from_secs(420);
    while !port_open(cfg.control_port) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_secs(2));
    }
    if port_open(cfg.control_port) {
        println!("[launcher] READY — control http://127.0.0.1:{control}  avatar http://127.0.0.1:{pres}/avatar", control = cfg.control_port, pres = cfg.presentation_port);
    } else {
        println!("[launcher] profile did not open {} in time; check logs", cfg.control_port);
    }
    println!("[launcher] hold this window open to keep the stack alive; Ctrl+C to stop");

    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    let _ = ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst));
    while running.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis(500));
    }
    println!("[launcher] stopping stack");
    for mut c in children {
        let _ = c.kill();
    }
}

/// OBS presentation window: WebView2 hosting the presentation origin's
/// placeholder page (ADR-045: the 3D avatar itself lives in the Electron
/// desktop shell; this window remains for OBS workflows that want a
/// frameless, transparent, always-on-top surface).
fn run_webview() {
    use tao::event::{Event, WindowEvent};
    use tao::event_loop::EventLoop;
    use tao::window::WindowBuilder;
    use wry::WebViewBuilder;

    // The presentation origin serves /avatar with no control privileges.
    let pres_port = RuntimeConfig::load().presentation_port;
    let url = std::env::args().nth(2).unwrap_or_else(|| format!("http://127.0.0.1:{pres_port}/"));
    println!("[webview] OBS presentation window -> {url}");

    let event_loop = EventLoop::new();
    let window = WindowBuilder::new()
        .with_title("JAWL Companion")
        .with_transparent(true)
        .with_decorations(false)
        .with_always_on_top(true)
        .with_inner_size(tao::dpi::LogicalSize::new(420.0, 620.0))
        .build(&event_loop)
        .expect("window");

    let _webview = WebViewBuilder::new()
        .with_url(&url)
        .with_transparent(true)
        .build_as_child(&window)
        .expect("webview (is WebView2 Runtime installed?)");

    println!("[webview] window open вЂ” close the window to exit");
    event_loop.run(move |event, _target, control_flow| {
        *control_flow = tao::event_loop::ControlFlow::Poll;
        if let Event::WindowEvent { event: WindowEvent::CloseRequested, .. } = event {
            *control_flow = tao::event_loop::ControlFlow::Exit;
        }
    });
}

fn main() {
    println!("JAWL Companion native client");
    // Default (no args, e.g. double-click) = launch the whole stack.
    let mode = std::env::args().nth(1).unwrap_or_else(|| "--all".to_string());
    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    let _ = ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst));
    match mode.as_str() {
        "--webview" => run_webview(),
        "--all" => run_all(),
        _ => run_mic(running),
    }
}
