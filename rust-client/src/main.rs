//! JAWL Companion native client (A5 prototype).
//!
//! ADR-036: a thin native client owns the audio devices and hosts the Live2D
//! character window / OBS surface. The web panel stays as the control/pult.
//! This prototype proves the seams: mic capture (cpal/WASAPI), a companion
//! health/status link, and a window skeleton. Live2D rendering (native Cubism
//! SDK) is the next layer on top of the window.

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Deserialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

const COMPANION_URL: &str = "http://127.0.0.1:2367";

#[derive(Debug, Deserialize)]
struct Health {
    status: String,
    mode: String,
}

fn check_companion() -> Result<(), String> {
    let resp: Health = ureq::get(&format!("{COMPANION_URL}/api/health"))
        .call()
        .map_err(|e| format!("companion unreachable: {e}"))?
        .into_json()
        .map_err(|e| format!("bad health json: {e}"))?;
    println!("[companion] status={} mode={}", resp.status, resp.mode);
    Ok(())
}

/// Own the microphone: prove we can open the default input and read PCM.
fn start_mic_capture(running: Arc<AtomicBool>) -> Result<(), String> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or("no default input device")?;
    let config = device
        .default_input_config()
        .map_err(|e| format!("no default input config: {e}"))?;
    println!(
        "[mic] {} · {} Hz · {} ch",
        device.name().unwrap_or_default(),
        config.sample_rate().0,
        config.channels()
    );
    let peak = Arc::new(std::sync::Mutex::new(0.0f32));
    let peak2 = peak.clone();
    let stream = device
        .build_input_stream(
            &config.into(),
            move |data: &[f32], _| {
                let mut p = peak2.lock().unwrap();
                for &s in data {
                    let a = s.abs();
                    if a > *p {
                        *p = a;
                    }
                }
            },
            |e| eprintln!("[mic] stream error: {e}"),
            None,
        )
        .map_err(|e| format!("build input stream failed: {e}"))?;
    stream.play().map_err(|e| format!("stream play failed: {e}"))?;

    // Report peak level while running (proves live capture).
    while running.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(500));
        let p = {
            let mut g = peak.lock().unwrap();
            let v = *g;
            *g = 0.0;
            v
        };
        if p > 0.001 {
            println!("[mic] peak={:.3}", p);
        }
    }
    drop(stream);
    Ok(())
}

fn main() {
    println!("JAWL Companion native client (A5 prototype)");
    match check_companion() {
        Ok(()) => println!("[companion] link OK"),
        Err(e) => eprintln!("[companion] {e}"),
    }

    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst)).ok();

    match start_mic_capture(running) {
        Ok(()) => println!("[mic] capture stopped cleanly"),
        Err(e) => eprintln!("[mic] {e}"),
    }
}
