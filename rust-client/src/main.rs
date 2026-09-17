//! JAWL Companion native client (B3 prototype).
//!
//! ADR-036: a thin native client owns the audio devices and hosts the Live2D
//! character window / OBS surface. The web panel stays as the control/pult.
//!
//! This prototype owns the real microphone (cpal/WASAPI), streams bounded PCM
//! chunks into the companion's `/api/voice/audio`, and reports the companion's
//! live health. Live2D rendering (native Cubism SDK) is the next layer.

use base64::Engine as _;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Deserialize;
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const COMPANION_URL: &str = "http://127.0.0.1:2367";
/// Companion ASR expects 16 kHz mono s16le PCM.
const TARGET_RATE: u32 = 16_000;
/// Send ~1 second of audio per POST.
const CHUNK_SECONDS: f32 = 1.0;

#[derive(Debug, Deserialize)]
struct Health {
    status: String,
    mode: String,
}

#[derive(Debug, Deserialize)]
struct Session {
    csrf_token: String,
}

/// A live companion session: cookie + CSRF token for the gated endpoints.
struct CompanionSession {
    cookie: String,
    csrf: String,
}

fn open_session() -> Result<CompanionSession, String> {
    let resp = ureq::get(&format!("{COMPANION_URL}/api/session"))
        .timeout(Duration::from_secs(5))
        .call()
        .map_err(|e| format!("session handshake failed: {e}"))?;
    let cookie = resp
        .header("set-cookie")
        .map(|c| c.split(';').next().unwrap_or("").to_string())
        .unwrap_or_default();
    let body: Session = serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?)
        .map_err(|e| format!("bad session json: {e}"))?;
    Ok(CompanionSession { cookie, csrf: body.csrf_token })
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

/// Linear-resample f32 mono to 16 kHz and convert to s16le bytes.
fn to_s16le_16k(samples: &[f32], src_rate: u32) -> Vec<u8> {
    let ratio = src_rate as f32 / TARGET_RATE as f32;
    let out_len = (samples.len() as f32 / ratio) as usize;
    let mut out = Vec::with_capacity(out_len * 2);
    for i in 0..out_len {
        let src = (i as f32 * ratio) as usize;
        let s = samples.get(src).copied().unwrap_or(0.0).clamp(-1.0, 1.0);
        let v = (s * i16::MAX as f32) as i16;
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

fn main() {
    println!("JAWL Companion native client (B3: mic -> companion stream)");
    if let Err(e) = check_companion() {
        eprintln!("[companion] {e}");
    }
    let session = match open_session() {
        Ok(s) => {
            println!("[companion] session established");
            Some(s)
        }
        Err(e) => {
            eprintln!("[companion] {e}");
            None
        }
    };

    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    let _ = ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst));

    let host = cpal::default_host();
    let device = match host.default_input_device() {
        Some(d) => d,
        None => {
            eprintln!("[mic] no default input device");
            return;
        }
    };
    let config = match device.default_input_config() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[mic] no default input config: {e}");
            return;
        }
    };
    let src_rate = config.sample_rate().0;
    let channels = config.channels() as usize;
    println!(
        "[mic] {} · {} Hz · {} ch -> {} Hz mono to companion",
        device.name().unwrap_or_default(),
        src_rate,
        channels,
        TARGET_RATE
    );

    // Bounded buffer: capture callback downsamples to mono f32 and pushes.
    let buf: Arc<Mutex<VecDeque<f32>>> = Arc::new(Mutex::new(VecDeque::new()));
    let buf2 = buf.clone();
    let stream = device
        .build_input_stream(
            &config.into(),
            move |data: &[f32], _| {
                let mut g = buf2.lock().unwrap();
                for frame in data.chunks(channels.max(1)) {
                    // average channels -> mono
                    let m = frame.iter().sum::<f32>() / frame.len() as f32;
                    g.push_back(m);
                }
                // cap at ~30 s of buffered audio to stay bounded
                let cap = (src_rate as f32 * 30.0) as usize;
                while g.len() > cap {
                    g.pop_front();
                }
            },
            |e| eprintln!("[mic] stream error: {e}"),
            None,
        );
    let stream = match stream {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[mic] build input stream failed: {e}");
            return;
        }
    };
    if let Err(e) = stream.play() {
        eprintln!("[mic] play failed: {e}");
        return;
    }

    let chunk_samples = (TARGET_RATE as f32 * CHUNK_SECONDS) as usize;
    while running.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis((CHUNK_SECONDS * 1000.0) as u64));
        // Drain the buffer and resample to 16k s16le.
        let raw: Vec<f32> = {
            let mut g = buf.lock().unwrap();
            g.drain(..).collect()
        };
        if raw.len() < (src_rate as f32 * 0.2) as usize {
            continue; // too little audio this tick
        }
        // peak level for the log
        let peak = raw.iter().fold(0.0f32, |a, &b| a.max(b.abs()));
        let pcm = to_s16le_16k(&raw, src_rate);
        if pcm.len() < chunk_samples * 2 / 4 {
            continue;
        }
        let b64 = base64::engine::general_purpose::STANDARD.encode(&pcm);
        let payload = serde_json::json!({
            "pcm16_base64": b64,
            "sample_rate": TARGET_RATE,
            "channels": 1,
            "session_id": "rust-client",
        });
        let mut req = ureq::post(&format!("{COMPANION_URL}/api/voice/audio"))
            .set("Content-Type", "application/json")
            .timeout(Duration::from_secs(10));
        if let Some(s) = &session {
            req = req
                .set("Cookie", &s.cookie)
                .set("X-Companion-CSRF", &s.csrf);
        }
        let res = req.send_string(&payload.to_string());
        match res {
            Ok(r) => {
                let code = r.status();
                println!("[stream] sent {} B pcm (peak {:.3}) -> HTTP {}", pcm.len(), peak, code);
            }
            Err(e) => eprintln!("[stream] send failed: {e}"),
        }
    }
    drop(stream);
    println!("[mic] capture stopped cleanly");
}
