//! JAWL Companion native client (C1/C2: mic stream + native Live2D avatar).
//!
//! ADR-036 records native capture as an alternative. Electron is the current
//! default voice lane; --mic uses this client's /api/voice/capture lease.
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
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
mod runtime_manifest;

const COMPANION_URL: &str = "http://127.0.0.1:2367";
const TARGET_RATE: u32 = 16_000;
const CAPTURE_LEASE_TTL_MS: u64 = 15_000;
// Covers a 10 s upload stall regardless of the device's callback block size.
const MIC_QUEUE_SECONDS: usize = 12;
const FINAL_POLL_MS: u64 = 100;
const FINAL_TIMEOUT_SECONDS: u64 = 180;
const UPLOAD_TIMEOUT_SECONDS: u64 = 10;
const MAX_UPLOAD_PCM: usize = 48 * 1024;
const MAX_FINAL_HEADERS: usize = 8 * 1024;
const MAX_FINAL_BODY: usize = 1024 * 1024;
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
    fn load(explicit_root: Option<&std::path::Path>) -> Result<Self, String> {
        let cwd = std::env::current_dir().map_err(|_| "cannot resolve current directory")?;
        let executable = std::env::current_exe().ok();
        let manifest = runtime_manifest::load(explicit_root, &cwd, executable.as_deref())?;
        // Missing manifest is the intentional development fallback retained
        // from the original Rust client; any present malformed file is fatal.
        let discovered_root = manifest
            .as_ref()
            .map(|m| m.discovered_root.clone())
            .unwrap_or(cwd);
        let effective_root = manifest
            .as_ref()
            .and_then(|m| m.repo_root.as_ref())
            .map(|root| resolve_repo_path(&discovered_root, root))
            .unwrap_or(discovered_root);
        let mut out = Self::defaults(&effective_root);
        if let Some(m) = manifest {
            out.repo_root = effective_root;
            if let Some(v) = m.profile {
                out.profile = v;
            }
            if let Some(v) = m.control_port {
                out.control_port = v;
            }
            if let Some(v) = m.presentation_port {
                out.presentation_port = v;
            }
            if let Some(v) = m.jawl_console_port {
                out.jawl_console_port = v;
            }
            if let Some(v) = m.relay_port {
                out.relay_port = v;
            }
            if let Some(v) = m.qwen3_vl_port {
                out.qwen3_vl_port = v;
            }
            if let Some(v) = m.bonsai_port {
                out.bonsai_port = v;
            }
            if let Some(v) = m.llama_server_exe {
                out.llama_server_exe = resolve_repo_path(&out.repo_root, &v);
            }
            if let Some(v) = m.qwen3_vl_model {
                out.qwen3_vl_model = resolve_repo_path(&out.repo_root, &v);
            }
            if let Some(v) = m.qwen3_vl_mmproj {
                out.qwen3_vl_mmproj = resolve_repo_path(&out.repo_root, &v);
            }
            if let Some(v) = m.bonsai_model {
                out.bonsai_model = resolve_repo_path(&out.repo_root, &v);
            }
            if let Some(v) = m.bonsai_mmproj {
                out.bonsai_mmproj = resolve_repo_path(&out.repo_root, &v);
            }
            if let Some(v) = m.mic_prefer {
                out.mic_prefer = v;
            }
            if let Some(v) = m.brain_model {
                out.brain_model = v;
            }
            if let Some(v) = m.brain_use_relay {
                out.brain_use_relay = v;
            }
            if let Some(v) = m.profile_script {
                out.profile_script = resolve_repo_path(&out.repo_root, &v);
            }
        }
        Ok(out)
    }

    /// Dev-machine defaults (kept as fallback; the manifest is authoritative).
    fn defaults(repo: &std::path::Path) -> Self {
        let root = repo;
        Self {
            repo_root: root.to_path_buf(),
            profile: "daily".to_string(),
            control_port: 2367,
            presentation_port: 8766,
            jawl_console_port: 8770,
            relay_port: 8891,
            qwen3_vl_port: 8983,
            bonsai_port: 8986,
            llama_server_exe: PathBuf::from(r"G:\AI\llamacpp-taardis\build\bin\llama-server.exe"),
            qwen3_vl_model: PathBuf::from(
                r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-Q4_K_M.gguf",
            ),
            qwen3_vl_mmproj: PathBuf::from(
                r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-mmproj-F16.gguf",
            ),
            bonsai_model: PathBuf::from(
                r"G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-Q1_0.gguf",
            ),
            bonsai_mmproj: PathBuf::from(
                r"G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-mmproj-Q8_0.gguf",
            ),
            mic_prefer: "fifine".to_string(),
            // Default brain: the local Hikari stack (owner decision
            // 2026-09-29). The relay profile stays opt-in via the manifest.
            brain_model: "local-bonsai2".to_string(),
            brain_use_relay: false,
            profile_script: root.join(r"scripts\run_integrated_profile.ps1"),
        }
    }
}

fn resolve_repo_path(repo_root: &std::path::Path, path: &std::path::Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        repo_root.join(path)
    }
}

#[derive(Debug, Deserialize)]
struct Health {
    status: String,
    mode: String,
}
#[derive(Debug, Deserialize)]
struct Session {
    csrf_token: String,
}
struct CompanionSession {
    cookie: String,
    csrf: String,
}

#[derive(Debug, Deserialize)]
struct CaptureConfig {
    ok: bool,
    owner: Option<String>,
    capture_id: Option<String>,
    expires_in_ms: u64,
    gate_open: f32,
    gate_close: f32,
    silence_ms: u64,
    pre_roll_ms: u64,
    lease_ttl_ms: u64,
}

impl CaptureConfig {
    fn validate(self, action: &str, capture_id: &str) -> Result<Self, String> {
        if !self.ok {
            return Err("capture lease response was not successful".into());
        }
        match action {
            "acquire" | "renew" => {
                if self.owner.as_deref() != Some("native")
                    || self.capture_id.as_deref() != Some(capture_id)
                {
                    return Err("capture lease identity mismatch".into());
                }
                if self.expires_in_ms == 0 || self.expires_in_ms > CAPTURE_LEASE_TTL_MS {
                    return Err("capture lease expiry is invalid".into());
                }
            }
            "release" => {
                if self.owner.is_some() || self.capture_id.is_some() || self.expires_in_ms != 0 {
                    return Err("capture lease release was not confirmed".into());
                }
            }
            _ => return Err("unsupported capture lease action".into()),
        }
        if !self.gate_open.is_finite()
            || !self.gate_close.is_finite()
            || !(0.001..=0.25).contains(&self.gate_open)
            || !(0.0005..self.gate_open).contains(&self.gate_close)
            || !(300..=5_000).contains(&self.silence_ms)
            || self.pre_roll_ms > 500
            || self.lease_ttl_ms != CAPTURE_LEASE_TTL_MS
        {
            return Err("capture settings are outside the supported range".into());
        }
        Ok(self)
    }
}

struct CaptureLeaseGuard<'a> {
    base: &'a str,
    session: &'a CompanionSession,
    capture_id: String,
}

impl CaptureLeaseGuard<'_> {
    fn renew(&self) -> Result<CaptureConfig, String> {
        capture_control(self.base, self.session, "renew", &self.capture_id)
    }
}

impl Drop for CaptureLeaseGuard<'_> {
    fn drop(&mut self) {
        let _ = capture_control(self.base, self.session, "release", &self.capture_id);
    }
}

fn capture_control(
    base: &str,
    session: &CompanionSession,
    action: &str,
    capture_id: &str,
) -> Result<CaptureConfig, String> {
    if capture_id.is_empty() || capture_id.len() > 128 {
        return Err("capture_id must be a non-empty string of at most 128 characters".into());
    }
    let payload = serde_json::json!({
        "action": action,
        "owner": "native",
        "capture_id": capture_id,
    });
    let response = ureq::post(&format!("{base}/api/voice/capture"))
        .set("Content-Type", "application/json")
        .set("Cookie", &session.cookie)
        .set("X-Companion-CSRF", &session.csrf)
        .timeout(match action {
            "renew" => Duration::from_millis(500),
            "release" => Duration::from_millis(250),
            _ => Duration::from_secs(5),
        })
        .send_string(&payload.to_string());
    let response = match response {
        Ok(response) => response,
        Err(ureq::Error::Status(status, _response)) => {
            return Err(format!("capture lease rejected (HTTP {status})"));
        }
        Err(error) => return Err(format!("capture lease request failed: {error}")),
    };
    let config: CaptureConfig = response
        .into_json()
        .map_err(|error| format!("bad capture config: {error}"))?;
    config.validate(action, capture_id)
}

struct MicQueueState {
    samples: VecDeque<f32>,
    paused: bool,
}

struct MicQueue {
    state: Mutex<MicQueueState>,
    generation: AtomicU64,
    failed: AtomicBool,
    max_samples: usize,
}

impl MicQueue {
    fn new(max_samples: usize) -> Self {
        Self {
            state: Mutex::new(MicQueueState {
                samples: VecDeque::new(),
                paused: false,
            }),
            generation: AtomicU64::new(0),
            failed: AtomicBool::new(false),
            max_samples,
        }
    }

    fn feed(&self, data: &[f32], channels: usize) {
        let generation = self.generation.load(Ordering::SeqCst);
        let mut state = match self.state.lock() {
            Ok(state) => state,
            Err(_) => {
                self.failed.store(true, Ordering::SeqCst);
                return;
            }
        };
        // Fence callbacks already in flight across pause/resume as well.
        if state.paused || generation != self.generation.load(Ordering::SeqCst) {
            return;
        }
        if self.failed.load(Ordering::SeqCst) {
            return;
        }
        if channels == 0
            || data.len() % channels != 0
            || data.len() / channels > self.max_samples.saturating_sub(state.samples.len())
            || data.iter().any(|sample| !sample.is_finite())
        {
            self.failed.store(true, Ordering::SeqCst);
            return;
        }
        state.samples.extend(
            data.chunks(channels)
                .map(|frame| frame.iter().sum::<f32>() / channels as f32),
        );
    }

    fn set_paused(&self, paused: bool) {
        match self.state.lock() {
            Ok(mut state) => {
                self.generation.fetch_add(1, Ordering::SeqCst);
                state.paused = paused;
                state.samples.clear();
            }
            Err(_) => {
                self.failed.store(true, Ordering::SeqCst);
            }
        }
    }

    fn take(&self, max_samples: usize) -> Vec<f32> {
        match self.state.lock() {
            Ok(mut state) => {
                let count = state.samples.len().min(max_samples);
                state.samples.drain(..count).collect()
            }
            Err(_) => {
                self.failed.store(true, Ordering::SeqCst);
                Vec::new()
            }
        }
    }
}

type VoiceFinal = Result<(u16, String), String>;

fn new_native_capture_id() -> String {
    static CAPTURE_SEQUENCE: AtomicU64 = AtomicU64::new(0);
    format!(
        "native-{}-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
        CAPTURE_SEQUENCE.fetch_add(1, Ordering::SeqCst)
    )
}

struct NativeUtteranceId {
    capture_id: String,
    sequence: u64,
    session_id: String,
}

impl NativeUtteranceId {
    fn new(capture_id: &str) -> Self {
        Self {
            capture_id: capture_id.to_owned(),
            sequence: 0,
            session_id: format!("{capture_id}:0"),
        }
    }

    fn advance_after_final(&mut self) -> Result<(), String> {
        let next = self
            .sequence
            .checked_add(1)
            .ok_or("utterance sequence exhausted")?;
        self.sequence = next;
        self.session_id = format!("{}:{next}", self.capture_id);
        Ok(())
    }
}

struct PendingVoiceRequest {
    cancel: Arc<AtomicBool>,
    result: mpsc::Receiver<VoiceFinal>,
    worker: Option<std::thread::JoinHandle<()>>,
    generation: u64,
    operation: &'static str,
}

impl PendingVoiceRequest {
    fn start_final(
        base: &str,
        session: &CompanionSession,
        capture_id: &str,
        utterance_id: &str,
        generation: u64,
    ) -> Result<Self, String> {
        let base = base.to_owned();
        let session = CompanionSession {
            cookie: session.cookie.clone(),
            csrf: session.csrf.clone(),
        };
        let capture_id = capture_id.to_owned();
        let utterance_id = utterance_id.to_owned();
        Self::spawn(generation, "final", move |cancel| {
            request_voice_final(&base, &session, &capture_id, &utterance_id, cancel)
        })
    }

    fn spawn(
        generation: u64,
        operation: &'static str,
        request: impl FnOnce(&AtomicBool) -> VoiceFinal + Send + 'static,
    ) -> Result<Self, String> {
        let cancel = Arc::new(AtomicBool::new(false));
        let worker_cancel = cancel.clone();
        let (sender, result) = mpsc::sync_channel(1);
        let worker = std::thread::Builder::new()
            .name(format!("native-voice-{operation}"))
            .spawn(move || {
                let response = request(&worker_cancel);
                let _ = sender.try_send(response);
            })
            .map_err(|error| format!("cannot start {operation} wait: {error}"))?;
        Ok(Self {
            cancel,
            result,
            worker: Some(worker),
            generation,
            operation,
        })
    }

    fn is_current(&self, running: &AtomicBool, mic: &MicQueue) -> Result<bool, String> {
        if !running.load(Ordering::SeqCst) {
            return Ok(false);
        }
        if mic.failed.load(Ordering::SeqCst) {
            return Err("mic callback/queue failed".into());
        }
        if mic.generation.load(Ordering::SeqCst) != self.generation {
            return Err("capture generation changed".into());
        }
        Ok(true)
    }
}

impl Drop for PendingVoiceRequest {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::SeqCst);
        // The worker polls cancellation on a short socket timeout; never detach
        // a live 180 s HTTP request when capture stops.
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn request_voice_final(
    base: &str,
    session: &CompanionSession,
    capture_id: &str,
    utterance_id: &str,
    cancel: &AtomicBool,
) -> VoiceFinal {
    let payload = serde_json::json!({
        "session_id": utterance_id, "owner": "native", "capture_id": capture_id,
    })
    .to_string();
    request_voice_json(
        base,
        session,
        "/api/voice/end",
        &payload,
        "final",
        Duration::from_secs(FINAL_TIMEOUT_SECONDS),
        cancel,
    )
}

fn request_voice_json(
    base: &str,
    session: &CompanionSession,
    path: &str,
    payload: &str,
    operation: &str,
    timeout: Duration,
    cancel: &AtomicBool,
) -> VoiceFinal {
    // This lane uses only the numeric loopback HTTP origin from companion_base_url.
    // A cancellable socket is needed because ureq 2 cannot cancel a blocking call.
    let deadline = Instant::now() + timeout;
    if cancel.load(Ordering::SeqCst) {
        return Err(format!("{operation} wait stopped"));
    }
    let address: SocketAddr = base
        .strip_prefix("http://")
        .ok_or("voice wait requires loopback HTTP")?
        .parse()
        .map_err(|_| "invalid voice wait address")?;
    if !address.ip().is_loopback() {
        return Err("voice wait requires loopback HTTP".into());
    }
    if [&session.cookie, &session.csrf]
        .iter()
        .any(|value| value.contains(['\r', '\n']))
    {
        return Err("invalid voice request headers".into());
    }
    let mut socket = TcpStream::connect_timeout(&address, Duration::from_millis(250))
        .map_err(|error| format!("{operation} connect failed: {error}"))?;
    socket
        .set_read_timeout(Some(Duration::from_millis(FINAL_POLL_MS)))
        .map_err(|error| error.to_string())?;
    socket
        .set_write_timeout(Some(Duration::from_millis(FINAL_POLL_MS)))
        .map_err(|error| error.to_string())?;
    let headers = format!("POST {path} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\nContent-Type: application/json\r\nCookie: {}\r\nX-Companion-CSRF: {}\r\nContent-Length: {}\r\n\r\n",
        session.cookie, session.csrf, payload.len());
    if headers.len() > MAX_FINAL_HEADERS || payload.len() > MAX_UPLOAD_PCM * 2 {
        return Err("voice request is too large".into());
    }
    let request = headers + payload;
    let mut sent = 0;
    while sent < request.len() && !cancel.load(Ordering::SeqCst) && Instant::now() < deadline {
        match socket.write(&request.as_bytes()[sent..]) {
            Ok(0) => return Err(format!("{operation} send ended prematurely")),
            Ok(count) => sent += count,
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut
                        | std::io::ErrorKind::WouldBlock
                        | std::io::ErrorKind::Interrupted
                ) => {}
            Err(error) => return Err(format!("{operation} send failed: {error}")),
        }
    }
    let mut bytes = Vec::new();
    let mut expected_length = None;
    let mut block = [0u8; 8192];
    while !cancel.load(Ordering::SeqCst) && Instant::now() < deadline {
        match socket.read(&mut block) {
            Ok(0) => return Err(format!("{operation} response ended prematurely")),
            Ok(count) => bytes.extend_from_slice(&block[..count]),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut
                        | std::io::ErrorKind::WouldBlock
                        | std::io::ErrorKind::Interrupted
                ) =>
            {
                continue
            }
            Err(error) => return Err(format!("{operation} read failed: {error}")),
        }
        if bytes.len() > MAX_FINAL_HEADERS + MAX_FINAL_BODY {
            return Err(format!("{operation} response is too large"));
        }
        if expected_length.is_none() {
            if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                let header_end = end + 4;
                if header_end > MAX_FINAL_HEADERS {
                    return Err(format!("{operation} headers are too large"));
                }
                let headers: ureq::Response = std::str::from_utf8(&bytes[..header_end])
                    .map_err(|_| format!("invalid {operation} headers"))?
                    .parse()
                    .map_err(|_| format!("invalid {operation} HTTP response"))?;
                if !(200..300).contains(&headers.status()) {
                    return Err(format!("{operation} rejected (HTTP {})", headers.status()));
                }
                // Companion's _json sends one Content-Length. Reject unknown
                // framing rather than waiting for an unbounded EOF/body.
                if headers.has("Transfer-Encoding") || headers.all("Content-Length").len() != 1 {
                    return Err(format!("unsupported {operation} response framing"));
                }
                let length: usize = headers
                    .header("Content-Length")
                    .unwrap_or("")
                    .parse()
                    .map_err(|_| format!("invalid {operation} response length"))?;
                if length > MAX_FINAL_BODY {
                    return Err(format!("{operation} response is too large"));
                }
                expected_length = Some(header_end + length);
            } else if bytes.len() > MAX_FINAL_HEADERS {
                return Err(format!("{operation} headers are too large"));
            }
        }
        if let Some(length) = expected_length {
            if bytes.len() >= length {
                let response: ureq::Response = std::str::from_utf8(&bytes[..length])
                    .map_err(|_| format!("{operation} response is not UTF-8"))?
                    .parse()
                    .map_err(|_| format!("invalid {operation} HTTP response"))?;
                let status = response.status();
                let body = response
                    .into_string()
                    .map_err(|_| format!("invalid {operation} body"))?;
                let value: serde_json::Value = serde_json::from_str(&body)
                    .map_err(|_| format!("{operation} response is not JSON"))?;
                if value.get("ok").and_then(serde_json::Value::as_bool) != Some(true) {
                    return Err(if operation == "final" {
                        "voice finalization failed"
                    } else {
                        "audio upload was rejected"
                    }
                    .into());
                }
                return Ok((status, body));
            }
        }
    }
    Err(format!(
        "{operation} wait {}",
        if cancel.load(Ordering::SeqCst) {
            "stopped"
        } else {
            "timed out"
        }
    ))
}

fn wait_voice_request(
    pending: PendingVoiceRequest,
    running: &AtomicBool,
    mic: &MicQueue,
    renew_interval: Duration,
    last_renew: &mut Instant,
    mut renew: impl FnMut() -> Result<(), String>,
) -> Result<Option<(u16, String)>, String> {
    let outcome = (|| loop {
        if !pending.is_current(running, mic)? {
            return Ok(None);
        }
        if last_renew.elapsed() >= renew_interval {
            let renewed = renew(); // Validate identity/config but keep the acquired settings snapshot.
            if !pending.is_current(running, mic)? {
                return Ok(None);
            }
            renewed?;
            *last_renew = Instant::now();
        }
        match pending
            .result
            .recv_timeout(Duration::from_millis(FINAL_POLL_MS))
        {
            Ok(result) => {
                if !pending.is_current(running, mic)? {
                    return Ok(None);
                }
                return result.map(Some);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err(format!("{} worker exited", pending.operation))
            }
        }
    })();
    if !matches!(outcome, Ok(Some(_))) {
        mic.set_paused(true);
    }
    // Dropping pending cancels and joins before this function returns.
    outcome
}

fn send_audio_chunk(
    base: &str,
    session: &CompanionSession,
    capture_id: &str,
    utterance_id: &str,
    pcm: &[u8],
    generation: u64,
) -> Result<PendingVoiceRequest, String> {
    if pcm.is_empty() || pcm.len() % 2 != 0 || pcm.len() > MAX_UPLOAD_PCM {
        return Err("audio upload must be bounded non-empty PCM16".into());
    }
    let encoded = base64::engine::general_purpose::STANDARD.encode(pcm);
    let payload = serde_json::json!({
        "pcm16_base64": encoded,
        "sample_rate": TARGET_RATE,
        "channels": 1,
        "session_id": utterance_id,
        "owner": "native",
        "capture_id": capture_id,
    })
    .to_string();
    let base = base.to_owned();
    let session = CompanionSession {
        cookie: session.cookie.clone(),
        csrf: session.csrf.clone(),
    };
    PendingVoiceRequest::spawn(generation, "upload", move |cancel| {
        request_voice_json(
            &base,
            &session,
            "/api/voice/audio",
            &payload,
            "upload",
            Duration::from_secs(UPLOAD_TIMEOUT_SECONDS),
            cancel,
        )
    })
}

fn check_companion() -> Result<(), String> {
    let resp: Health = ureq::get(&format!("{COMPANION_URL}/api/health"))
        .timeout(Duration::from_secs(5))
        .call()
        .map_err(|e| format!("companion unreachable: {e}"))?
        .into_json()
        .map_err(|e| format!("bad health json: {e}"))?;
    println!("[companion] status={} mode={}", resp.status, resp.mode);
    Ok(())
}

fn open_session_at(base: &str) -> Result<CompanionSession, String> {
    let resp = ureq::get(&format!("{base}/api/session"))
        .timeout(Duration::from_secs(5))
        .call()
        .map_err(|e| format!("session handshake failed: {e}"))?;
    let cookie = resp
        .header("set-cookie")
        .map(|c| c.split(';').next().unwrap_or("").to_string())
        .unwrap_or_default();
    let body: Session = serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?)
        .map_err(|e| format!("bad session json: {e}"))?;
    Ok(CompanionSession {
        cookie,
        csrf: body.csrf_token,
    })
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

fn companion_base_url(cfg: &RuntimeConfig) -> String {
    // The control port is manifest-owned (ADR-041); a profile started with a
    // different port must not leave the mic lane talking to a dead endpoint.
    // --port N (any argument position) overrides it for disposable profiles.
    let arg_port = std::env::args()
        .position(|a| a == "--port")
        .and_then(|pos| std::env::args().nth(pos + 1))
        .and_then(|v| v.parse::<u16>().ok());
    let port = arg_port.unwrap_or(cfg.control_port);
    format!("http://127.0.0.1:{port}")
}

fn run_mic(running: Arc<AtomicBool>, cfg: &RuntimeConfig) {
    println!("[mode] mic -> companion stream");
    let base = companion_base_url(cfg);
    println!("[companion] base url: {base}");
    let resp: Result<Health, _> = ureq::get(&format!("{base}/api/health"))
        .timeout(Duration::from_secs(5))
        .call()
        .map_err(|e| format!("companion unreachable: {e}"))
        .and_then(|r| r.into_json().map_err(|e| format!("bad health json: {e}")));
    match resp {
        Ok(h) => println!("[companion] status={} mode={}", h.status, h.mode),
        Err(e) => eprintln!("[companion] {e}"),
    }
    let session = open_session_at(&base).ok();
    if session.is_some() {
        println!("[companion] session established");
    }
    let session = match session {
        Some(session) => session,
        None => {
            eprintln!("[mic] capture requires an authenticated companion session");
            return;
        }
    };

    let host = cpal::default_host();
    // Prefer the owner's real microphone (manifest mic_prefer) over a
    // virtual/headset default; fall back to the OS default when absent.
    let mic_prefer = cfg.mic_prefer.to_lowercase();
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
        match chosen {
            Some(d) => d,
            None => {
                eprintln!("[mic] no input device");
                return;
            }
        }
    };
    let config = match device.default_input_config() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[mic] no input config: {e}");
            return;
        }
    };
    let src_rate = config.sample_rate().0;
    let channels = config.channels() as usize;
    println!(
        "[mic] {} Р’В· {} Hz Р’В· {} ch -> {} Hz mono",
        device.name().unwrap_or_default(),
        src_rate,
        channels,
        TARGET_RATE
    );

    let capture_id = new_native_capture_id();
    let mut utterance = NativeUtteranceId::new(&capture_id);
    let mut last_renew = Instant::now();
    let capture_config = match capture_control(&base, &session, "acquire", &capture_id) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("[mic] capture lease unavailable: {error}");
            return;
        }
    };
    let _lease = CaptureLeaseGuard {
        base: &base,
        session: &session,
        capture_id: capture_id.clone(),
    };

    let mic_queue = Arc::new(MicQueue::new(src_rate as usize * MIC_QUEUE_SECONDS));
    let queue_cb = mic_queue.clone();
    let queue_error = mic_queue.clone();
    let stream = match device.build_input_stream(
        &config.into(),
        move |data: &[f32], _| {
            queue_cb.feed(data, channels);
        },
        move |error| {
            // Both DeviceNotAvailable and backend-specific callback errors invalidate capture.
            queue_error.failed.store(true, Ordering::SeqCst);
            eprintln!("[mic] stream error; capture will stop: {error}");
        },
        None,
    ) {
        Ok(stream) => stream,
        Err(error) => {
            eprintln!("[mic] input stream unavailable: {error}");
            return;
        }
    };
    if let Err(error) = stream.play() {
        eprintln!("[mic] input stream could not start: {error}");
        return;
    }

    // Explicit half-duplex alternative: capture pauses during ASR/JAWL finalization.
    // Electron remains the current default capture owner.
    let mut saw_speech = false;
    let mut silence_ms: u64 = 0;
    let pre_roll_samples = ((src_rate as u64 * capture_config.pre_roll_ms) / 1000) as usize;
    let mut pre_roll: VecDeque<f32> = VecDeque::with_capacity(pre_roll_samples.max(1));
    let mut buf: Vec<f32> = Vec::new();
    // Upload/final waits poll this same renewal schedule independently of HTTP progress.
    let renew_interval = Duration::from_millis((capture_config.lease_ttl_ms / 4).max(1));
    while running.load(Ordering::SeqCst) {
        if mic_queue.failed.load(Ordering::SeqCst) {
            eprintln!("[mic] input queue/device failure; stopping capture fail-closed");
            break;
        }
        std::thread::sleep(Duration::from_millis(FINAL_POLL_MS));
        if !running.load(Ordering::SeqCst) {
            break;
        }
        if last_renew.elapsed() >= renew_interval {
            match _lease.renew() {
                Ok(_updated) => last_renew = Instant::now(),
                Err(error) => {
                    eprintln!("[mic] capture lease lost: {error}");
                    break;
                }
            }
        }
        buf.extend(mic_queue.take(src_rate as usize / 5));
        if mic_queue.failed.load(Ordering::SeqCst) {
            break;
        }
        if buf.len() < (src_rate as usize / 5) {
            continue;
        }
        let raw: Vec<f32> = std::mem::take(&mut buf);
        let rms = (raw.iter().map(|sample| sample * sample).sum::<f32>() / raw.len() as f32).sqrt();
        let peak = raw.iter().fold(0.0f32, |a, &b| a.max(b.abs()));
        let chunk_ms = (raw.len() as u64 * 1000 / src_rate.max(1) as u64).max(1);
        if !saw_speech {
            if rms < capture_config.gate_open {
                for sample in raw {
                    pre_roll.push_back(sample);
                    while pre_roll.len() > pre_roll_samples {
                        pre_roll.pop_front();
                    }
                }
                continue;
            }
            saw_speech = true;
            silence_ms = 0;
            let mut with_preroll = pre_roll.drain(..).collect::<Vec<f32>>();
            with_preroll.extend(raw);
            let raw = with_preroll;
            let pcm = to_s16le_16k(&raw, src_rate);
            if pcm.is_empty() {
                continue;
            }
            let pending = match send_audio_chunk(
                &base,
                &session,
                &capture_id,
                &utterance.session_id,
                &pcm,
                mic_queue.generation.load(Ordering::SeqCst),
            ) {
                Ok(pending) => pending,
                Err(error) => {
                    eprintln!("[mic] {error}");
                    break;
                }
            };
            match wait_voice_request(
                pending,
                &running,
                &mic_queue,
                renew_interval,
                &mut last_renew,
                || _lease.renew().map(|_| ()),
            ) {
                Ok(Some(_)) => println!("[stream] {} B (peak {:.3}) uploaded", pcm.len(), peak),
                Ok(None) => break,
                Err(error) => {
                    eprintln!("[mic] {error}; stopping capture fail-closed");
                    break;
                }
            }
            continue;
        }
        if rms < capture_config.gate_close {
            silence_ms = silence_ms.saturating_add(chunk_ms);
        } else {
            silence_ms = 0;
        }
        if silence_ms >= capture_config.silence_ms {
            saw_speech = false;
            silence_ms = 0;
            mic_queue.set_paused(true);
            pre_roll.clear();
            buf.clear();
            if let Err(error) = stream.pause() {
                eprintln!("[mic] could not pause capture: {error}");
                break;
            }
            println!("[voice] finishing utterance; microphone paused (half-duplex)");
            let pending = match PendingVoiceRequest::start_final(
                &base,
                &session,
                &capture_id,
                &utterance.session_id,
                mic_queue.generation.load(Ordering::SeqCst),
            ) {
                Ok(pending) => pending,
                Err(error) => {
                    eprintln!("[voice] {error}");
                    break;
                }
            };
            match wait_voice_request(
                pending,
                &running,
                &mic_queue,
                renew_interval,
                &mut last_renew,
                || _lease.renew().map(|_| ()),
            ) {
                Ok(Some((status, body))) => {
                    print_voice_final(status, &body);
                    if let Err(error) = utterance.advance_after_final() {
                        eprintln!("[voice] {error}; stopping capture fail-closed");
                        break;
                    }
                }
                Ok(None) => break,
                Err(error) => {
                    eprintln!("[voice] {error}; stopping capture fail-closed");
                    break;
                }
            }
            if !running.load(Ordering::SeqCst) || mic_queue.failed.load(Ordering::SeqCst) {
                break;
            }
            if let Err(error) = stream.play() {
                eprintln!("[mic] could not resume capture: {error}");
                break;
            }
            // Clear once more before accepting fresh callbacks. Paused PCM is never replayed.
            mic_queue.set_paused(false);
            continue;
        }
        let pcm = to_s16le_16k(&raw, src_rate);
        if pcm.is_empty() {
            continue;
        }
        let pending = match send_audio_chunk(
            &base,
            &session,
            &capture_id,
            &utterance.session_id,
            &pcm,
            mic_queue.generation.load(Ordering::SeqCst),
        ) {
            Ok(pending) => pending,
            Err(error) => {
                eprintln!("[mic] {error}");
                break;
            }
        };
        match wait_voice_request(
            pending,
            &running,
            &mic_queue,
            renew_interval,
            &mut last_renew,
            || _lease.renew().map(|_| ()),
        ) {
            Ok(Some(_)) => println!("[stream] {} B (peak {:.3}) uploaded", pcm.len(), peak),
            Ok(None) => break,
            Err(error) => {
                eprintln!("[mic] {error}; stopping capture fail-closed");
                break;
            }
        }
    }
    mic_queue.set_paused(true);
    drop(stream);
    println!("[mic] stopped");
}

/// Print the finalized voice turn: transcript plus the companion's reply.
fn print_voice_final(status: u16, body: &str) {
    let parsed: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => {
            println!("[voice] final -> {status} (non-json body)");
            return;
        }
    };
    let transcript = parsed
        .get("transcript")
        .and_then(|t| t.as_str())
        .unwrap_or("");
    let ok = parsed.get("ok").and_then(|o| o.as_bool());
    println!(
        "[voice] final -> {status} ok={:?} transcript={:?}",
        ok, transcript
    );
    if let Some(responses) = parsed.get("responses").and_then(|r| r.as_array()) {
        for response in responses {
            let text = response.get("text").and_then(|t| t.as_str()).unwrap_or("");
            if !text.is_empty() {
                println!("[companion] {text}");
            }
        }
    }
}

/// window alive (so the user sees status and nothing silently closes).
///
/// Order matters: model servers first (they load slowly), then the integrated
/// profile launcher which waits for them. All children stay alive as long as
/// this process runs; closing the window stops them.
fn run_all(cfg: &RuntimeConfig) {
    use std::net::TcpStream;
    use std::process::{Child, Command, Stdio};

    println!(
        "[launcher] repo={} profile={}",
        cfg.repo_root.display(),
        cfg.profile
    );

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
            "--model",
            &vl_model,
            "--alias",
            "qwen3-vl",
            "--host",
            "127.0.0.1",
            "--port",
            &vl_port.to_string(),
            "--ctx-size",
            "8192",
            "--threads",
            "4",
            "-ngl",
            "99",
            "--no-webui",
            "--reasoning",
            "off",
            "--mmproj",
            &vl_mmproj,
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
        if let Ok(c) = cmd.spawn() {
            children.push(c);
            println!("[launcher] qwen3-vl starting ({vl_port}, below-normal priority)");
        }
    } else {
        println!("[launcher] qwen3-vl already up ({vl_port})");
    }

    // Wait for the vision server to accept connections before the profile.
    {
        let deadline = std::time::Instant::now() + Duration::from_secs(120);
        while !port_open(vl_port) && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(800));
        }
        println!(
            "[launcher] qwen3-vl port {vl_port} {}",
            if port_open(vl_port) { "up" } else { "TIMEOUT" }
        );
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
            cfg.repo_root
                .join(r"scripts\run_local_bonsai_integrated.ps1")
                .to_string_lossy()
                .to_string()
        };
        let prof_script = script.clone();
        let mut args: Vec<String> = vec![
            "-NoProfile".into(),
            "-ExecutionPolicy".into(),
            "Bypass".into(),
            "-File".into(),
            prof_script,
            "-ProfileName".into(),
            cfg.profile.clone(),
            "-UseVoiceMem".into(),
            "-TtsProvider".into(),
            "tera".into(),
            "-JawlModelOverride".into(),
            brain_model,
            "-StartupTimeoutSeconds".into(),
            "420".into(),
        ];
        if use_relay {
            // Relay profile: the full sensory/vision stack belongs to it.
            args.extend([
                "-StartLocalAudio".into(),
                "-EnableProsodyPlanner".into(),
                "-EnableStreamingAsr".into(),
                "-EnableScreenWatch".into(),
                "-EnableSensoryWorker".into(),
                "-AmbientTriageSeconds".into(),
                "300".into(),
                "-UseOpenCodeRelay".into(),
            ]);
        } else {
            // Local brain wrapper owns its audio args (-StartLocalAudio).
            args.push("-StartLocalAudio".into());
        }
        let prof = Command::new("powershell")
            .args(&args)
            .current_dir(&current_dir)
            .spawn();
        match prof {
            Ok(c) => {
                children.push(c);
                println!(
                    "[launcher] integrated profile starting (brain: {})",
                    if use_relay { "relay" } else { "local-hikari" }
                );
            }
            Err(e) => eprintln!("[launcher] profile spawn failed: {e}"),
        }
    } else {
        println!("[launcher] profile already up ({})", cfg.control_port);
    }

    // Report readiness, then keep the window alive until Ctrl+C.
    let deadline = std::time::Instant::now() + Duration::from_secs(420);
    while !port_open(cfg.control_port) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_secs(2));
    }
    if port_open(cfg.control_port) {
        println!("[launcher] READY — control http://127.0.0.1:{control}  avatar http://127.0.0.1:{pres}/avatar", control = cfg.control_port, pres = cfg.presentation_port);
    } else {
        println!(
            "[launcher] profile did not open {} in time; check logs",
            cfg.control_port
        );
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
fn run_webview(cfg: &RuntimeConfig) {
    use tao::event::{Event, WindowEvent};
    use tao::event_loop::EventLoop;
    use tao::window::WindowBuilder;
    use wry::WebViewBuilder;

    // The presentation origin serves /avatar with no control privileges.
    let pres_port = cfg.presentation_port;
    let url = std::env::args()
        .nth(2)
        .unwrap_or_else(|| format!("http://127.0.0.1:{pres_port}/"));
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
        if let Event::WindowEvent {
            event: WindowEvent::CloseRequested,
            ..
        } = event
        {
            *control_flow = tao::event_loop::ControlFlow::Exit;
        }
    });
}

fn main() {
    println!("JAWL Companion native client");
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = args
        .iter()
        .find(|arg| ["--all", "--webview", "--mic"].contains(&arg.as_str()))
        .map(String::as_str)
        .unwrap_or("--all");
    let explicit_root = match args.iter().position(|arg| arg == "--repo-root") {
        Some(index) => match args.get(index + 1) {
            Some(path) => Some(PathBuf::from(path)),
            None => {
                eprintln!("[config] --repo-root requires a path");
                std::process::exit(2);
            }
        },
        None => None,
    };
    let cfg = match RuntimeConfig::load(explicit_root.as_deref()) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("[config] {error}");
            std::process::exit(2);
        }
    };
    if args.iter().any(|arg| arg == "--check-config") {
        println!("Runtime configuration is valid (no devices or workers started).");
        return;
    }
    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    let _ = ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst));
    match mode {
        "--webview" => run_webview(&cfg),
        "--all" => run_all(&cfg),
        _ => run_mic(running, &cfg),
    }
}

#[cfg(test)]
mod runtime_config_tests {
    use super::*;

    #[test]
    fn relative_repo_and_resource_paths_resolve_from_discovered_repo() {
        let id = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("jawl-runtime-config-{}-{id}", std::process::id()));
        let config = root.join("config");
        std::fs::create_dir_all(&config).unwrap();
        std::fs::write(
            config.join("runtime.manifest.json"),
            r#"{
            "schema_version":1,
            "repo_root":"runtime-root",
            "ports":{"brain_port":8990},
            "models":{"llama_server_exe":"bin/llama.exe","qwen3_vl_model":"models/vision.gguf"},
            "brain":{"model":"fixture","llm_url":"http://127.0.0.1:8990/v1"},
            "profile_script":"scripts/profile.ps1"
        }"#,
        )
        .unwrap();

        let loaded = RuntimeConfig::load(Some(&root)).unwrap();
        let effective = root.canonicalize().unwrap().join("runtime-root");
        assert_eq!(loaded.repo_root, effective);
        assert_eq!(loaded.profile_script, effective.join("scripts/profile.ps1"));
        assert_eq!(loaded.llama_server_exe, effective.join("bin/llama.exe"));
        assert_eq!(loaded.qwen3_vl_model, effective.join("models/vision.gguf"));
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[cfg(test)]
mod capture_contract_tests {
    use super::*;

    fn valid_config() -> CaptureConfig {
        CaptureConfig {
            ok: true,
            owner: Some("native".into()),
            capture_id: Some("native-test".into()),
            expires_in_ms: CAPTURE_LEASE_TTL_MS,
            gate_open: 0.02,
            gate_close: 0.012,
            silence_ms: 1_200,
            pre_roll_ms: 120,
            lease_ttl_ms: CAPTURE_LEASE_TTL_MS,
        }
    }

    #[test]
    fn lease_accepts_only_matching_native_identity_and_expected_ttl() {
        assert!(valid_config().validate("acquire", "native-test").is_ok());
        assert!(valid_config().validate("renew", "native-test").is_ok());

        let mut wrong_owner = valid_config();
        wrong_owner.owner = Some("desktop".into());
        assert!(wrong_owner.validate("acquire", "native-test").is_err());

        let mut wrong_id = valid_config();
        wrong_id.capture_id = Some("other".into());
        assert!(wrong_id.validate("renew", "native-test").is_err());

        let mut wrong_ttl = valid_config();
        wrong_ttl.lease_ttl_ms -= 1;
        assert!(wrong_ttl.validate("acquire", "native-test").is_err());
    }

    #[test]
    fn capture_settings_match_python_finite_and_range_contract() {
        assert!(valid_config().validate("acquire", "native-test").is_ok());
        let mut invalid = valid_config();
        invalid.gate_open = f32::NAN;
        assert!(invalid.validate("acquire", "native-test").is_err());
        let mut invalid = valid_config();
        invalid.gate_close = invalid.gate_open;
        assert!(invalid.validate("acquire", "native-test").is_err());
        let mut invalid = valid_config();
        invalid.silence_ms = 299;
        assert!(invalid.validate("acquire", "native-test").is_err());
        let mut invalid = valid_config();
        invalid.pre_roll_ms = 501;
        assert!(invalid.validate("acquire", "native-test").is_err());
    }

    #[test]
    fn release_requires_server_confirmation() {
        let mut released = valid_config();
        released.owner = None;
        released.capture_id = None;
        released.expires_in_ms = 0;
        assert!(released.validate("release", "native-test").is_ok());
        assert!(valid_config().validate("release", "native-test").is_err());
    }

    #[test]
    fn queue_is_sample_bounded_and_pause_discards_pcm() {
        let queue = MicQueue::new(TARGET_RATE as usize * MIC_QUEUE_SECONDS);
        // 1000 typical 10 ms callbacks fit: capacity is time, not callback count.
        for _ in 0..1000 {
            queue.feed(&[0.25; 160], 1);
        }
        assert!(!queue.failed.load(Ordering::SeqCst));
        queue.set_paused(true);
        queue.feed(&[0.5; 160], 1);
        queue.set_paused(false);
        assert!(queue.take(usize::MAX).is_empty());
        queue.feed(&[0.75; 160], 1);
        assert_eq!(queue.take(usize::MAX), vec![0.75; 160]);

        let bounded = MicQueue::new(4);
        bounded.feed(&[0.0; 4], 1);
        bounded.feed(&[0.0], 1);
        assert!(bounded.failed.load(Ordering::SeqCst));
        assert_eq!(bounded.take(usize::MAX).len(), 4);
    }

    struct MockVoiceHttp {
        base: String,
        stopped: Arc<AtomicBool>,
        requests: Arc<Mutex<Vec<(String, serde_json::Value)>>>,
        final_started: mpsc::Receiver<()>,
        final_disconnected: Arc<AtomicBool>,
        upload_started: mpsc::Receiver<()>,
        upload_disconnected: Arc<AtomicBool>,
        worker: Option<std::thread::JoinHandle<()>>,
    }

    impl MockVoiceHttp {
        fn start(final_delay: Duration) -> Self {
            Self::start_with_delays(final_delay, Duration::ZERO)
        }

        fn start_with_delays(final_delay: Duration, upload_delay: Duration) -> Self {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            listener.set_nonblocking(true).unwrap();
            let stopped = Arc::new(AtomicBool::new(false));
            let server_stopped = stopped.clone();
            let requests = Arc::new(Mutex::new(Vec::new()));
            let server_requests = requests.clone();
            let final_disconnected = Arc::new(AtomicBool::new(false));
            let server_disconnected = final_disconnected.clone();
            let (started_sender, final_started) = mpsc::sync_channel(1);
            let upload_disconnected = Arc::new(AtomicBool::new(false));
            let server_upload_disconnected = upload_disconnected.clone();
            let (upload_sender, upload_started) = mpsc::sync_channel(1);
            let worker = std::thread::spawn(move || {
                let mut handlers = Vec::new();
                while !server_stopped.load(Ordering::SeqCst) {
                    match listener.accept() {
                        Ok((socket, _)) => {
                            let stopped = server_stopped.clone();
                            let requests = server_requests.clone();
                            let disconnected = server_disconnected.clone();
                            let started = started_sender.clone();
                            let upload_disconnected = server_upload_disconnected.clone();
                            let upload_started = upload_sender.clone();
                            handlers.push(std::thread::spawn(move || {
                                Self::serve(
                                    socket,
                                    final_delay,
                                    upload_delay,
                                    stopped,
                                    requests,
                                    disconnected,
                                    started,
                                    upload_disconnected,
                                    upload_started,
                                );
                            }));
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(5));
                        }
                        Err(error) => panic!("mock HTTP accept: {error}"),
                    }
                }
                for handler in handlers {
                    handler.join().unwrap();
                }
            });
            Self {
                base,
                stopped,
                requests,
                final_started,
                final_disconnected,
                upload_started,
                upload_disconnected,
                worker: Some(worker),
            }
        }

        fn serve(
            mut socket: TcpStream,
            final_delay: Duration,
            upload_delay: Duration,
            stopped: Arc<AtomicBool>,
            requests: Arc<Mutex<Vec<(String, serde_json::Value)>>>,
            disconnected: Arc<AtomicBool>,
            started: mpsc::SyncSender<()>,
            upload_disconnected: Arc<AtomicBool>,
            upload_started: mpsc::SyncSender<()>,
        ) {
            socket
                .set_read_timeout(Some(Duration::from_millis(100)))
                .unwrap();
            socket
                .set_write_timeout(Some(Duration::from_millis(100)))
                .unwrap();
            let deadline = Instant::now() + Duration::from_secs(3);
            let mut bytes = Vec::new();
            let mut block = [0; 4096];
            let (path, payload) = loop {
                if stopped.load(Ordering::SeqCst) || Instant::now() >= deadline {
                    return;
                }
                match socket.read(&mut block) {
                    Ok(0) => return,
                    Ok(count) => bytes.extend_from_slice(&block[..count]),
                    Err(error)
                        if matches!(
                            error.kind(),
                            std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                        ) =>
                    {
                        continue
                    }
                    Err(_) => return,
                }
                assert!(bytes.len() <= MAX_UPLOAD_PCM * 2 + MAX_FINAL_HEADERS);
                if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                    let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                    assert!(headers.contains("Cookie: fixture-session"));
                    assert!(headers.contains("X-Companion-CSRF: fixture-csrf"));
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            let (name, value) = line.split_once(':')?;
                            name.eq_ignore_ascii_case("content-length")
                                .then(|| value.trim().parse::<usize>().unwrap())
                        })
                        .unwrap();
                    if bytes.len() >= end + 4 + length {
                        let path = headers.split_whitespace().nth(1).unwrap().to_owned();
                        let payload: serde_json::Value =
                            serde_json::from_slice(&bytes[end + 4..end + 4 + length]).unwrap();
                        break (path, payload);
                    }
                }
            };
            requests
                .lock()
                .unwrap()
                .push((path.clone(), payload.clone()));
            assert_eq!(payload["owner"], "native");
            let capture_id = payload["capture_id"].as_str().unwrap();
            assert!(capture_id.starts_with("native-"));
            if path == "/api/voice/audio" || path == "/api/voice/end" {
                assert!(payload["session_id"]
                    .as_str()
                    .unwrap()
                    .starts_with(&format!("{capture_id}:")));
            }
            if path == "/api/voice/end" || path == "/api/voice/audio" {
                let (delay, started, disconnected) = if path == "/api/voice/end" {
                    (final_delay, started, disconnected)
                } else {
                    (upload_delay, upload_started, upload_disconnected)
                };
                let _ = started.try_send(());
                let until = Instant::now() + delay;
                while Instant::now() < until && !stopped.load(Ordering::SeqCst) {
                    match socket.read(&mut block) {
                        Ok(0) => {
                            disconnected.store(true, Ordering::SeqCst);
                            return;
                        }
                        Err(error)
                            if matches!(
                                error.kind(),
                                std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                            ) => {}
                        Err(_) => {
                            disconnected.store(true, Ordering::SeqCst);
                            return;
                        }
                        Ok(_) => panic!("unexpected extra voice request"),
                    }
                }
            }
            let body = if path == "/api/voice/end" {
                serde_json::json!({"ok": true, "transcript": "fixture"})
            } else if path == "/api/voice/audio" {
                assert_eq!(payload["sample_rate"], TARGET_RATE);
                assert_eq!(payload["channels"], 1);
                let pcm = base64::engine::general_purpose::STANDARD
                    .decode(payload["pcm16_base64"].as_str().unwrap())
                    .unwrap();
                assert!(!pcm.is_empty() && pcm.len() <= MAX_UPLOAD_PCM);
                serde_json::json!({"ok": true})
            } else {
                assert_eq!(path, "/api/voice/capture");
                assert_eq!(payload["action"], "renew");
                serde_json::json!({
                    "ok": true, "owner": "native", "capture_id": capture_id,
                    "expires_in_ms": CAPTURE_LEASE_TTL_MS, "lease_ttl_ms": CAPTURE_LEASE_TTL_MS,
                    "gate_open": 0.03, "gate_close": 0.015, "silence_ms": 1500, "pre_roll_ms": 100,
                })
            }
            .to_string();
            let reply = format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
            let _ = socket.write_all(reply.as_bytes());
        }
    }

    impl Drop for MockVoiceHttp {
        fn drop(&mut self) {
            self.stopped.store(true, Ordering::SeqCst);
            if let Some(worker) = self.worker.take() {
                worker.join().unwrap();
            }
        }
    }

    fn fixture_session() -> CompanionSession {
        CompanionSession {
            cookie: "fixture-session".into(),
            csrf: "fixture-csrf".into(),
        }
    }

    fn assert_disconnected(disconnected: &AtomicBool) {
        let until = Instant::now() + Duration::from_secs(1);
        while !disconnected.load(Ordering::SeqCst) && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(disconnected.load(Ordering::SeqCst));
    }

    #[test]
    fn stalled_upload_stop_clears_pcm_and_joins_worker_under_one_second() {
        let server = MockVoiceHttp::start_with_delays(
            Duration::ZERO,
            Duration::from_secs(UPLOAD_TIMEOUT_SECONDS),
        );
        let mic = MicQueue::new(TARGET_RATE as usize * MIC_QUEUE_SECONDS);
        mic.feed(&[0.25; 160], 1);
        let pending = send_audio_chunk(
            &server.base,
            &fixture_session(),
            "native-test",
            "native-test:0",
            &[0, 0],
            mic.generation.load(Ordering::SeqCst),
        )
        .unwrap();
        let cancelled = pending.cancel.clone();
        server
            .upload_started
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let running = Arc::new(AtomicBool::new(true));
        let stop_running = running.clone();
        let stopper = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(30));
            stop_running.store(false, Ordering::SeqCst);
        });
        let started = Instant::now();
        let result = wait_voice_request(
            pending,
            &running,
            &mic,
            Duration::from_secs(5),
            &mut Instant::now(),
            || panic!("renew not due"),
        )
        .unwrap();
        stopper.join().unwrap();
        assert!(result.is_none());
        assert!(started.elapsed() < Duration::from_secs(1)); // Includes worker Drop/join.
        assert!(cancelled.load(Ordering::SeqCst));
        assert!(mic.state.lock().unwrap().paused);
        assert!(mic.take(usize::MAX).is_empty());
        assert_disconnected(&server.upload_disconnected);
        let requests = server.requests.lock().unwrap();
        assert_eq!(requests.len(), 1); // No retry, final, or TTS/goal cancellation.
        assert_eq!(requests[0].0, "/api/voice/audio");
    }

    #[test]
    fn delayed_upload_renews_over_mock_http_while_callbacks_remain_bounded() {
        let server = MockVoiceHttp::start_with_delays(Duration::ZERO, Duration::from_millis(600));
        let session = fixture_session();
        let mic = MicQueue::new(TARGET_RATE as usize * MIC_QUEUE_SECONDS);
        let generation = mic.generation.load(Ordering::SeqCst);
        let pcm = vec![0; MAX_UPLOAD_PCM];
        let pending = send_audio_chunk(
            &server.base,
            &session,
            "native-test",
            "native-test:0",
            &pcm,
            generation,
        )
        .unwrap();
        let mut renewals = 0;
        let result = wait_voice_request(
            pending,
            &AtomicBool::new(true),
            &mic,
            Duration::from_millis(100),
            &mut Instant::now(),
            || {
                // Synthetic 10 ms callbacks, not hardware evidence.
                mic.feed(&[0.25; 160], 1);
                let updated = capture_control(&server.base, &session, "renew", "native-test")?;
                assert_eq!(updated.owner.as_deref(), Some("native"));
                renewals += 1;
                Ok(())
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(result.0, 200);
        assert!(renewals >= 2);
        assert!(!mic.failed.load(Ordering::SeqCst));
        assert_eq!(mic.generation.load(Ordering::SeqCst), generation);
        assert!(!mic.state.lock().unwrap().paused);
        assert_eq!(mic.take(usize::MAX).len(), renewals * 160);
        let requests = server.requests.lock().unwrap();
        assert_eq!(
            requests
                .iter()
                .filter(|(path, _)| path == "/api/voice/audio")
                .count(),
            1
        );
        assert_eq!(
            requests
                .iter()
                .filter(|(path, _)| path == "/api/voice/capture")
                .count(),
            renewals
        );
        assert!(requests
            .iter()
            .all(|(path, _)| path == "/api/voice/audio" || path == "/api/voice/capture"));
    }

    #[test]
    fn queued_upload_ack_from_old_generation_is_rejected_and_pcm_cleared() {
        let server = MockVoiceHttp::start(Duration::ZERO);
        let mic = MicQueue::new(1600);
        let pending = send_audio_chunk(
            &server.base,
            &fixture_session(),
            "native-test",
            "native-test:0",
            &[0, 0],
            mic.generation.load(Ordering::SeqCst),
        )
        .unwrap();
        server
            .upload_started
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let until = Instant::now() + Duration::from_secs(1);
        while !pending.worker.as_ref().unwrap().is_finished() && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(pending.worker.as_ref().unwrap().is_finished()); // Actual HTTP ack is queued.
        mic.set_paused(true);
        mic.set_paused(false);
        mic.feed(&[0.5; 160], 1);
        let cancelled = pending.cancel.clone();
        let error = wait_voice_request(
            pending,
            &AtomicBool::new(true),
            &mic,
            Duration::from_secs(5),
            &mut Instant::now(),
            || panic!("renew not due"),
        )
        .unwrap_err();
        assert!(error.contains("generation changed"));
        assert!(cancelled.load(Ordering::SeqCst));
        assert!(mic.state.lock().unwrap().paused);
        assert!(mic.take(usize::MAX).is_empty());
        assert_eq!(server.requests.lock().unwrap().len(), 1);
    }

    #[test]
    fn upload_queue_device_and_renew_failures_cancel_join_and_clear_pcm() {
        for failure in ["queue", "device", "renew"] {
            let server = MockVoiceHttp::start_with_delays(
                Duration::ZERO,
                Duration::from_secs(UPLOAD_TIMEOUT_SECONDS),
            );
            let mic = MicQueue::new(160);
            mic.feed(&[0.25; 160], 1);
            let pending = send_audio_chunk(
                &server.base,
                &fixture_session(),
                "native-test",
                "native-test:0",
                &[0, 0],
                mic.generation.load(Ordering::SeqCst),
            )
            .unwrap();
            let cancelled = pending.cancel.clone();
            server
                .upload_started
                .recv_timeout(Duration::from_secs(2))
                .unwrap();
            let started = Instant::now();
            let error = wait_voice_request(
                pending,
                &AtomicBool::new(true),
                &mic,
                Duration::ZERO,
                &mut Instant::now(),
                || {
                    match failure {
                        "queue" => mic.feed(&[0.25], 1), // Real sample capacity overflow.
                        "device" => mic.failed.store(true, Ordering::SeqCst), // CPAL callback's flag, no device run.
                        _ => return Err("fixture lease renewal failed".into()),
                    }
                    Ok(())
                },
            )
            .unwrap_err();
            assert!(error.contains(if failure == "renew" {
                "renewal failed"
            } else {
                "callback/queue failed"
            }));
            assert!(started.elapsed() < Duration::from_secs(1));
            assert!(cancelled.load(Ordering::SeqCst));
            assert!(mic.state.lock().unwrap().paused);
            assert!(mic.take(usize::MAX).is_empty());
            assert_disconnected(&server.upload_disconnected);
            assert_eq!(server.requests.lock().unwrap().len(), 1);
        }
    }

    #[test]
    fn upload_http_errors_clear_pcm_and_join_without_replay() {
        let replies = [
            (
                "HTTP/1.1 409 Conflict\r\nContent-Length: 0\r\n\r\n".to_owned(),
                "HTTP 409",
            ),
            (
                format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n",
                    MAX_FINAL_BODY + 1
                ),
                "too large",
            ),
            (
                "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n".to_owned(),
                "unsupported upload response framing",
            ),
            (
                "HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n{\"ok\":false}".to_owned(),
                "audio upload was rejected",
            ),
            (
                "HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}".to_owned(),
                "ended prematurely",
            ),
        ];
        for (reply, expected_error) in replies {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let server = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                socket
                    .set_write_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut request = [0; 4096];
                socket.read(&mut request).unwrap();
                socket.write_all(reply.as_bytes()).unwrap();
            });
            let mic = MicQueue::new(1600);
            mic.feed(&[0.25; 160], 1);
            let pending = send_audio_chunk(
                &base,
                &fixture_session(),
                "native-test",
                "native-test:0",
                &[0, 0],
                mic.generation.load(Ordering::SeqCst),
            )
            .unwrap();
            let cancelled = pending.cancel.clone();
            let error = wait_voice_request(
                pending,
                &AtomicBool::new(true),
                &mic,
                Duration::from_secs(5),
                &mut Instant::now(),
                || panic!("renew not due"),
            )
            .unwrap_err();
            server.join().unwrap();
            assert!(error.contains(expected_error), "{error}");
            assert!(cancelled.load(Ordering::SeqCst));
            assert!(mic.state.lock().unwrap().paused);
            assert!(mic.take(usize::MAX).is_empty());
        }
    }

    #[test]
    fn upload_rejects_empty_odd_and_oversize_pcm_before_starting_transport() {
        for pcm in [Vec::new(), vec![0], vec![0; MAX_UPLOAD_PCM + 2]] {
            let result = send_audio_chunk(
                "invalid-address",
                &fixture_session(),
                "native-test",
                "native-test:0",
                &pcm,
                0,
            );
            assert!(matches!(result, Err(error) if error.contains("bounded non-empty PCM16")));
        }
    }

    #[test]
    fn new_capture_and_completed_utterance_have_distinct_bounded_ids() {
        let capture_id = new_native_capture_id();
        let next_capture_id = new_native_capture_id();
        assert_ne!(capture_id, next_capture_id);
        assert!(capture_id.len() <= 128);
        let mut utterance = NativeUtteranceId::new(&capture_id);
        let first = utterance.session_id.clone();
        assert_ne!(first, NativeUtteranceId::new(&next_capture_id).session_id);
        utterance.advance_after_final().unwrap();
        assert_ne!(first, utterance.session_id);
        assert_eq!(utterance.session_id, format!("{capture_id}:1"));
        assert!(utterance.session_id.len() <= 200);

        utterance.sequence = u64::MAX;
        let before_exhaustion = utterance.session_id.clone();
        assert!(utterance.advance_after_final().is_err());
        assert_eq!(utterance.session_id, before_exhaustion);
    }

    #[test]
    fn mock_http_audio_and_final_share_each_utterance_id_and_rotate_after_completion() {
        let server = MockVoiceHttp::start(Duration::ZERO);
        let session = fixture_session();
        let capture_id = new_native_capture_id();
        let mut utterance = NativeUtteranceId::new(&capture_id);
        let mic = MicQueue::new(1600);
        mic.set_paused(true);
        let mut ids = Vec::new();
        for _ in 0..2 {
            ids.push(utterance.session_id.clone());
            // These are the same HTTP helpers and ID state used by run_mic.
            for _ in 0..2 {
                let pending = send_audio_chunk(
                    &server.base,
                    &session,
                    &capture_id,
                    &utterance.session_id,
                    &[0, 0, 1, 0],
                    mic.generation.load(Ordering::SeqCst),
                )
                .unwrap();
                assert_eq!(
                    wait_voice_request(
                        pending,
                        &AtomicBool::new(true),
                        &mic,
                        Duration::from_secs(5),
                        &mut Instant::now(),
                        || panic!("renew not due")
                    )
                    .unwrap()
                    .unwrap()
                    .0,
                    200
                );
            }
            let pending = PendingVoiceRequest::start_final(
                &server.base,
                &session,
                &capture_id,
                &utterance.session_id,
                mic.generation.load(Ordering::SeqCst),
            )
            .unwrap();
            let completed = wait_voice_request(
                pending,
                &AtomicBool::new(true),
                &mic,
                Duration::from_secs(5),
                &mut Instant::now(),
                || panic!("renew not due"),
            )
            .unwrap();
            assert_eq!(completed.unwrap().0, 200);
            utterance.advance_after_final().unwrap();
        }
        assert_ne!(ids[0], ids[1]);
        let requests = server.requests.lock().unwrap();
        assert_eq!(requests.len(), 6);
        for (index, id) in ids.iter().enumerate() {
            let group = &requests[index * 3..index * 3 + 3];
            assert_eq!(group[0].0, "/api/voice/audio");
            assert_eq!(group[1].0, "/api/voice/audio");
            assert_eq!(group[2].0, "/api/voice/end");
            for (_, payload) in group {
                assert_eq!(payload["session_id"].as_str(), Some(id.as_str()));
                assert_eq!(payload["capture_id"].as_str(), Some(capture_id.as_str()));
                assert_eq!(payload["owner"], "native");
            }
        }
    }

    #[test]
    fn delayed_final_renews_over_mock_http_and_keeps_paused_pcm_empty() {
        let server = MockVoiceHttp::start(Duration::from_millis(600));
        let session = fixture_session();
        let mic = MicQueue::new(1600);
        mic.set_paused(true);
        let pending = PendingVoiceRequest::start_final(
            &server.base,
            &session,
            "native-test",
            "native-test:0",
            mic.generation.load(Ordering::SeqCst),
        )
        .unwrap();
        let mut last_renew = Instant::now();
        let result = wait_voice_request(
            pending,
            &AtomicBool::new(true),
            &mic,
            Duration::from_millis(100),
            &mut last_renew,
            || {
                mic.feed(&[0.5; 160], 1); // Synthetic callbacks during the pause are dropped.
                capture_control(&server.base, &session, "renew", "native-test").map(|_| ())
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(result.0, 200);
        mic.set_paused(false);
        assert!(mic.take(usize::MAX).is_empty());
        let requests = server.requests.lock().unwrap();
        assert_eq!(
            requests
                .iter()
                .filter(|(path, _)| path == "/api/voice/end")
                .count(),
            1
        );
        assert!(
            requests
                .iter()
                .filter(|(path, _)| path == "/api/voice/capture")
                .count()
                >= 2
        );
        assert!(requests
            .iter()
            .all(|(path, _)| path == "/api/voice/end" || path == "/api/voice/capture"));
    }

    #[test]
    fn stop_during_delayed_final_joins_worker_promptly_without_a_tts_cancel() {
        let server = MockVoiceHttp::start(Duration::from_secs(FINAL_TIMEOUT_SECONDS));
        let mic = MicQueue::new(1600);
        mic.set_paused(true);
        let pending = PendingVoiceRequest::start_final(
            &server.base,
            &fixture_session(),
            "native-test",
            "native-test:0",
            mic.generation.load(Ordering::SeqCst),
        )
        .unwrap();
        server
            .final_started
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let running = Arc::new(AtomicBool::new(true));
        let stop_running = running.clone();
        let stopper = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(30));
            stop_running.store(false, Ordering::SeqCst);
        });
        let started = Instant::now();
        let result = wait_voice_request(
            pending,
            &running,
            &mic,
            Duration::from_secs(5),
            &mut Instant::now(),
            || panic!("renew not due"),
        )
        .unwrap();
        stopper.join().unwrap();
        assert!(result.is_none());
        assert!(started.elapsed() < Duration::from_secs(1)); // Includes cancelling and joining the worker.
        let requests = server.requests.lock().unwrap();
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].0, "/api/voice/end");
        drop(requests);
        let until = Instant::now() + Duration::from_secs(1);
        while !server.final_disconnected.load(Ordering::SeqCst) && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(server.final_disconnected.load(Ordering::SeqCst));
    }

    #[test]
    fn final_transport_fails_closed_on_http_body_and_framing_errors() {
        let replies = [
            (
                "HTTP/1.1 409 Conflict\r\nContent-Length: 0\r\n\r\n".to_owned(),
                "HTTP 409",
            ),
            (
                format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n",
                    MAX_FINAL_BODY + 1
                ),
                "too large",
            ),
            (
                "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n".to_owned(),
                "unsupported final response framing",
            ),
            (
                "HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n{\"ok\":false}".to_owned(),
                "voice finalization failed",
            ),
            (
                "HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}".to_owned(),
                "ended prematurely",
            ),
        ];
        for (reply, expected_error) in replies {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let server = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                socket
                    .set_write_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut request = [0; 4096];
                socket.read(&mut request).unwrap();
                socket.write_all(reply.as_bytes()).unwrap();
            });
            let result = request_voice_final(
                &base,
                &fixture_session(),
                "native-test",
                "native-test:0",
                &AtomicBool::new(false),
            );
            server.join().unwrap();
            assert!(result.unwrap_err().contains(expected_error));
        }
    }

    #[test]
    fn callback_failure_ends_a_paused_final_wait_and_joins_worker() {
        let server = MockVoiceHttp::start(Duration::from_secs(FINAL_TIMEOUT_SECONDS));
        let mic = MicQueue::new(1600);
        mic.set_paused(true);
        let pending = PendingVoiceRequest::start_final(
            &server.base,
            &fixture_session(),
            "native-test",
            "native-test:0",
            mic.generation.load(Ordering::SeqCst),
        )
        .unwrap();
        server
            .final_started
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        // The production CPAL error callback sets this same fail-closed flag.
        mic.failed.store(true, Ordering::SeqCst);
        let started = Instant::now();
        assert!(wait_voice_request(
            pending,
            &AtomicBool::new(true),
            &mic,
            Duration::from_secs(5),
            &mut Instant::now(),
            || panic!("renew not due")
        )
        .is_err());
        assert!(started.elapsed() < Duration::from_secs(1));
    }
}
