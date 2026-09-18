//! JAWL Companion native client (C1/C2: mic stream + native Live2D avatar).
//!
//! ADR-036: a thin native client owns the audio devices and hosts the Live2D
//! character window / OBS surface. The web panel stays as the control/pult.
//!
//! Modes (pick one):
//!   --mic     own the microphone and stream 16 kHz mono s16le into the
//!             companion's /api/voice/audio (proven in Phase B).
//!   --avatar  open a winit window and render the Live2D model (moc3) with the
//!             pure-Rust Mocari runtime (no proprietary Cubism SDK).

use base64::Engine as _;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Deserialize;
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const COMPANION_URL: &str = "http://127.0.0.1:2367";
const TARGET_RATE: u32 = 16_000;
const CHUNK_SECONDS: f32 = 1.0;
const MODEL_PATH: &str = r"G:\AI\JAWL-VoiceCompanion\runtime\live2d\mao_pro\mao_pro.model3.json";

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

fn open_session() -> Result<CompanionSession, String> {
    let resp = ureq::get(&format!("{COMPANION_URL}/api/session"))
        .timeout(Duration::from_secs(5)).call()
        .map_err(|e| format!("session handshake failed: {e}"))?;
    let cookie = resp.header("set-cookie")
        .map(|c| c.split(';').next().unwrap_or("").to_string()).unwrap_or_default();
    let body: Session = serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?)
        .map_err(|e| format!("bad session json: {e}"))?;
    Ok(CompanionSession { cookie, csrf: body.csrf_token })
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

fn run_mic(running: Arc<AtomicBool>) {
    println!("[mode] mic -> companion stream");
    if let Err(e) = check_companion() { eprintln!("[companion] {e}"); }
    let session = open_session().ok();
    if session.is_some() { println!("[companion] session established"); }

    let host = cpal::default_host();
    let device = match host.default_input_device() { Some(d) => d, None => { eprintln!("[mic] no input device"); return; } };
    let config = match device.default_input_config() { Ok(c) => c, Err(e) => { eprintln!("[mic] no input config: {e}"); return; } };
    let src_rate = config.sample_rate().0;
    let channels = config.channels() as usize;
    println!("[mic] {} В· {} Hz В· {} ch -> {} Hz mono", device.name().unwrap_or_default(), src_rate, channels, TARGET_RATE);

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

    while running.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis((CHUNK_SECONDS * 1000.0) as u64));
        let raw: Vec<f32> = { let mut g = buf.lock().unwrap(); g.drain(..).collect() };
        if raw.len() < (src_rate as f32 * 0.2) as usize { continue; }
        let peak = raw.iter().fold(0.0f32, |a, &b| a.max(b.abs()));
        let pcm = to_s16le_16k(&raw, src_rate);
        if pcm.is_empty() { continue; }
        let b64 = base64::engine::general_purpose::STANDARD.encode(&pcm);
        let payload = serde_json::json!({ "pcm16_base64": b64, "sample_rate": TARGET_RATE, "channels": 1, "session_id": "rust-client" });
        let mut req = ureq::post(&format!("{COMPANION_URL}/api/voice/audio")).set("Content-Type", "application/json").timeout(Duration::from_secs(10));
        if let Some(s) = &session { req = req.set("Cookie", &s.cookie).set("X-Companion-CSRF", &s.csrf); }
        match req.send_string(&payload.to_string()) {
            Ok(r) => println!("[stream] {} B (peak {:.3}) -> {}", pcm.len(), peak, r.status()),
            Err(e) => eprintln!("[stream] send failed: {e}"),
        }
    }
    drop(stream);
    println!("[mic] stopped");
}

/// Software texture-mapped triangle rasterizer for the Live2D mesh.
/// Draws each drawable mesh's triangles with its texture, honoring opacity.
fn rasterize(
    model: &mocari::assets::RuntimeModel,
    frame: &mut [u32],
    width: usize,
    height: usize,
) {
    // Mint-tinted background to match the panel's Windows Aero palette.
    for px in frame.iter_mut() {
        *px = 0x00_1a2b26; // dark teal
    }
    let canvas = model.runtime().canvas();
    let _ = canvas; // canvas units are pixels; vertices are normalized model units.
    // Vertices are in normalized model space (roughly xв€€[-0.6,0.6],
    // yв€€[-2.0,1.0] for this model). Fit that bbox into the window.
    let (mut minx, mut miny, mut maxx, mut maxy) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for m in model.runtime().meshes() {
        for v in m.vertices() {
            let p = v.position();
            minx = minx.min(p[0]); miny = miny.min(p[1]);
            maxx = maxx.max(p[0]); maxy = maxy.max(p[1]);
        }
    }
    let span_x = (maxx - minx).max(1e-3);
    let span_y = (maxy - miny).max(1e-3);
    let scale = (width as f32 * 0.8 / span_x).min(height as f32 * 0.8 / span_y);
    let cx = (minx + maxx) / 2.0;
    let cy = (miny + maxy) / 2.0;
    let ox = width as f32 / 2.0;
    let oy = height as f32 / 2.0;
    let to_px = |p: [f32; 2]| -> (f32, f32) { (ox + (p[0] - cx) * scale, oy - (p[1] - cy) * scale) };

    let mut meshes: Vec<&mocari::moc3::Moc3DrawableMesh> = model.runtime().meshes().iter().collect();
    meshes.sort_by_key(|m| m.render_order());
    for mesh in meshes {
        let opacity = mesh.opacity();
        if opacity <= 0.0 {
            continue;
        }
        let tex = model.textures().get(mesh.texture_index().max(0) as usize);
        let verts = mesh.vertices();
        let idx = mesh.indices();
        for tri in idx.chunks_exact(3) {
            let (a, b, c) = (verts[tri[0] as usize], verts[tri[1] as usize], verts[tri[2] as usize]);
            let (pa, pb, pc) = (to_px(a.position()), to_px(b.position()), to_px(c.position()));
            raster_tri(frame, width, height, pa, pb, pc, a.uv(), b.uv(), c.uv(), tex, opacity);
        }
    }
}

fn raster_tri(
    frame: &mut [u32],
    width: usize,
    height: usize,
    pa: (f32, f32),
    pb: (f32, f32),
    pc: (f32, f32),
    ua: [f32; 2],
    ub: [f32; 2],
    uc: [f32; 2],
    tex: Option<&mocari::assets::DecodedTexture>,
    opacity: f32,
) {
    let min_x = pa.0.min(pb.0).min(pc.0).floor().max(0.0) as i32;
    let max_x = pa.0.max(pb.0).max(pc.0).ceil().min(width as f32) as i32;
    let min_y = pa.1.min(pb.1).min(pc.1).floor().max(0.0) as i32;
    let max_y = pa.1.max(pb.1).max(pc.1).ceil().min(height as f32) as i32;
    let area = (pb.0 - pa.0) * (pc.1 - pa.1) - (pc.0 - pa.0) * (pb.1 - pa.1);
    if area.abs() < 1e-6 {
        return;
    }
    for y in min_y..max_y {
        for x in min_x..max_x {
            let px = x as f32 + 0.5;
            let py = y as f32 + 0.5;
            let w0 = ((pb.0 - pa.0) * (py - pa.1) - (pb.1 - pa.1) * (px - pa.0)) / area;
            let w1 = ((pc.0 - pb.0) * (py - pb.1) - (pc.1 - pb.1) * (px - pb.0)) / area;
            let w2 = 1.0 - w0 - w1;
            if w0 < 0.0 || w1 < 0.0 || w2 < 0.0 {
                continue;
            }
            // barycentric uv
            let u = w0 * uc[0] + w1 * ua[0] + w2 * ub[0];
            let v = w0 * uc[1] + w1 * ua[1] + w2 * ub[1];
            let (mut r, mut g, mut b, mut a) = (200u32, 220u32, 210u32, 255u32);
            if let Some(t) = tex {
                let (tw, th) = (t.width().max(1) as usize, t.height().max(1) as usize);
                let tx = (u.clamp(0.0, 1.0) * (tw - 1) as f32) as usize;
                let ty = (v.clamp(0.0, 1.0) * (th - 1) as f32) as usize;
                let rgba = t.rgba();
                let i = (ty * tw + tx) * 4;
                if i + 3 < rgba.len() {
                    r = rgba[i] as u32;
                    g = rgba[i + 1] as u32;
                    b = rgba[i + 2] as u32;
                    a = rgba[i + 3] as u32;
                }
            }
            let alpha = (a as f32 / 255.0) * opacity;
            if alpha <= 0.01 {
                continue;
            }
            let di = y as usize * width + x as usize;
            let dst = frame[di];
            let (dr, dg, db) = ((dst >> 16) & 0xff, (dst >> 8) & 0xff, dst & 0xff);
            let (or_, og, ob) = (
                (r as f32 * alpha + dr as f32 * (1.0 - alpha)) as u32,
                (g as f32 * alpha + dg as f32 * (1.0 - alpha)) as u32,
                (b as f32 * alpha + db as f32 * (1.0 - alpha)) as u32,
            );
            frame[di] = (or_ << 16) | (og << 8) | ob;
        }
    }
}

fn run_avatar() {
    println!("[mode] avatar window (Mocari Live2D, software raster)");
    let mut model = match mocari::assets::load_model_runtime(MODEL_PATH) {
        Ok(m) => m,
        Err(e) => { eprintln!("[avatar] failed to load {MODEL_PATH}: {e}"); return; }
    };
    println!("[avatar] model loaded: {} drawables, {} textures",
        model.runtime().meshes().len(), model.textures().len());

    // Headless render proof: rasterize one frame and save a PNG so we can
    // verify the character actually draws (not a blank window) without a GUI.
    if std::env::args().any(|a| a == "--headless") {
        let (w, h) = (480usize, 640usize);
        model.runtime_mut().set_parameter_normalized("ParamMouthOpenY", 0.6);
        model.runtime_mut().update_meshes();
        let mut frame = vec![0u32; w * h];
        rasterize(&model, &mut frame, w, h);
        let bg = 0x00_1a2b26u32;
        let drawn = frame.iter().filter(|&&p| p != bg).count();
        let out = std::path::Path::new(r"G:\AI\JAWL-VoiceCompanion\runtime\avatar-render.png");
        let mut rgba = Vec::with_capacity(w * h * 4);
        for &p in &frame {
            rgba.push(((p >> 16) & 0xff) as u8);
            rgba.push(((p >> 8) & 0xff) as u8);
            rgba.push((p & 0xff) as u8);
            rgba.push(255u8);
        }
        match image::save_buffer(out, &rgba, w as u32, h as u32, image::ColorType::Rgba8) {
            Ok(()) => println!("[avatar] headless frame saved: {} ({} px drawn of {})", out.display(), drawn, w * h),
            Err(e) => eprintln!("[avatar] save failed: {e}"),
        }
        return;
    }

    let event_loop = winit::event_loop::EventLoop::new().expect("event loop");
    let attrs = winit::window::Window::default_attributes()
        .with_title("JAWL Companion")
        .with_inner_size(winit::dpi::LogicalSize::new(480u32, 640u32));
    let window = std::sync::Arc::new(event_loop.create_window(attrs).expect("window"));
    let context = softbuffer::Context::new(window.clone()).expect("softbuffer context");
    let mut surface = softbuffer::Surface::new(&context, window.clone()).expect("softbuffer surface");
    println!("[avatar] window open (close to exit)");

    let start = std::time::Instant::now();
    // Load the model's expression files (exp_01..08) once; an ExpressionManager
    // blends the active one each frame.
    let model_dir = std::path::Path::new(MODEL_PATH).parent().unwrap().to_path_buf();
    let mut expressions: Vec<mocari::json::Expression3> = Vec::new();
    for i in 1..=8 {
        let p = model_dir.join("expressions").join(format!("exp_{i:02}.exp3.json"));
        if let Ok(e) = mocari::expression::load_expression(&p) { expressions.push(e); }
    }
    println!("[avatar] {} expressions loaded", expressions.len());
    let mut expr_manager = mocari::expression::ExpressionManager::new();
    let mut current_expr: usize = 0;
    let mut last_frame = std::time::Instant::now();
    // Poll the companion's live state for lip-sync (avatar_audio: speaking +
    // amplitude) and the last turn's emotion (to drive the expression later).
    // Runs in a background thread so the render loop never blocks on I/O.
    // The companion exposes this on GET /api/state (session-gated).
    let lip = Arc::new(Mutex::new((false, 0.0f32))); // (speaking, amplitude)
    let emotion = Arc::new(Mutex::new(String::new())); // last turn emotion id
    {
        let lip = lip.clone();
        let emotion = emotion.clone();
        std::thread::spawn(move || {
            // Establish a session once; the state endpoint needs it.
            let session = open_session().ok();
            loop {
                let mut req = ureq::get(&format!("{COMPANION_URL}/api/state"));
                if let Some(s) = &session {
                    req = req.set("Cookie", &s.cookie).set("X-Companion-CSRF", &s.csrf);
                }
                if let Ok(resp) = req.call() {
                    if let Ok(v) = resp.into_json::<serde_json::Value>() {
                        let aa = v.get("avatar_audio");
                        let speaking = aa.and_then(|a| a.get("speaking")).and_then(|x| x.as_bool()).unwrap_or(false);
                        let amp = aa.and_then(|a| a.get("amplitude")).and_then(|x| x.as_f64()).unwrap_or(0.0) as f32;
                        if let Ok(mut g) = lip.lock() { *g = (speaking, amp); }
                        if let Some(e) = v.pointer("/last_turn/response/emotion/id").and_then(|x| x.as_str()) {
                            if let Ok(mut g) = emotion.lock() { *g = e.to_string(); }
                        }
                    }
                }
                std::thread::sleep(Duration::from_millis(120));
            }
        });
    }
    let _ = event_loop.run(move |event, elwt| {
        use winit::event::{Event, WindowEvent};
        match event {
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => elwt.exit(),
            Event::WindowEvent { event: WindowEvent::RedrawRequested, .. } => {
                let size = window.inner_size();
                let (w, h) = (size.width.max(1) as usize, size.height.max(1) as usize);
                let t = start.elapsed().as_secs_f32();
                // Idle sway/breathing.
                model.runtime_mut().set_parameter_normalized("ParamAngleX", 0.5 + 0.15 * (t * 0.6).sin());
                model.runtime_mut().set_parameter_normalized("ParamAngleY", 0.5 + 0.1 * (t * 0.4).cos());
                // Lip-sync: the model's LipSync group targets `ParamA`
                // (see mao_pro.model3.json Groups), not ParamMouthOpenY.
                let (speaking, amp) = lip.lock().map(|g| *g).unwrap_or((false, 0.0));
                let mouth = if speaking { amp.clamp(0.0, 1.0) } else { 0.2 * (t * 1.4).sin().abs() };
                model.runtime_mut().set_parameter_normalized("ParamA", mouth);
                // Expression from the companion's last-turn emotion. The mao_pro
                // bundle ships 8 expression slots (exp_01..08); map the agent's
                // emotion id onto them. Switch only on change (mocari fades).
                let emo = emotion.lock().map(|g| g.clone()).unwrap_or_default();
                let expr_idx = match emo.as_str() {
                    "happy" | "joy" => 1,
                    "sad" => 3,
                    "angry" => 4,
                    "surprised" => 5,
                    "concerned" => 6,
                    "confused" => 7,
                    "attentive" => 2,
                    _ => 0, // neutral
                };
                if expr_idx != current_expr && expr_idx < expressions.len() {
                    expr_manager.play(expressions[expr_idx].clone());
                    current_expr = expr_idx;
                }
                let dt = last_frame.elapsed().as_secs_f32();
                last_frame = std::time::Instant::now();
                expr_manager.tick(dt);
                expr_manager.apply(model.runtime_mut());
                model.runtime_mut().update_meshes();
                surface.resize(std::num::NonZeroU32::new(w as u32).unwrap(), std::num::NonZeroU32::new(h as u32).unwrap()).unwrap();
                let mut buf = surface.buffer_mut().unwrap();
                rasterize(&model, &mut buf, w, h);
                buf.present().unwrap();
                window.request_redraw();
            }
            _ => {}
        }
        // Drive a continuous redraw for the idle animation.
        window.request_redraw();
    });
}

/// Launch the whole companion stack as owned child processes and keep this
/// window alive (so the user sees status and nothing silently closes).
///
/// Order matters: model servers first (they load slowly), then the integrated
/// profile launcher which waits for them. All children stay alive as long as
/// this process runs; closing the window stops them.
fn run_all() {
    use std::process::{Child, Command, Stdio};
    use std::net::TcpStream;

    println!("[launcher] starting full stack");

    let port_open = |port: u16| TcpStream::connect(("127.0.0.1", port)).is_ok();
    let spawn_hidden = |exe: &str, args: &[&str]| -> Option<Child> {
        Command::new(exe).args(args).stdout(Stdio::null()).stderr(Stdio::null()).spawn().ok()
    };

    let mut children: Vec<Child> = Vec::new();

    // Qwen3-VL screen-watch describer (GPU1) on 8983 вЂ” the only always-on
    // vision model. Bonsai 27B was dropped from the default profile (ADR-040):
    // it held 13 GB VRAM + 17 GB RAM for ~100 s/screenshot. Heavy analysis is
    // manual via scripts\run_coding_server.ps1, not part of the stack.
    if !port_open(8983) {
        if let Some(c) = spawn_hidden(r"G:\AI\llamacpp-taardis\build\bin\llama-server.exe", &[
            "--model", r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-Q4_K_M.gguf",
            "--alias", "qwen3-vl", "--host", "127.0.0.1", "--port", "8983",
            "--ctx-size", "8192", "--threads", "8", "-ngl", "99",
            "--no-webui", "--reasoning", "off",
            "--mmproj", r"G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-mmproj-F16.gguf",
        ]) { children.push(c); println!("[launcher] qwen3-vl starting (8983)"); }
    } else { println!("[launcher] qwen3-vl already up (8983)"); }

    // Wait for the vision server to accept connections before the profile.
    for (name, port) in [("qwen3-vl", 8983u16)] {
        let deadline = std::time::Instant::now() + Duration::from_secs(120);
        while !port_open(port) && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(800));
        }
        println!("[launcher] {} port {} {}", name, port, if port_open(port) { "up" } else { "TIMEOUT" });
    }

    // 3) Integrated profile (companion + JAWL + voice + relay)
    if !port_open(2367) {
        let prof = Command::new("powershell")
            .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                r"G:\AI\JAWL-VoiceCompanion\scripts\run_integrated_profile.ps1",
                "-ProfileName", "daily", "-StartLocalAudio", "-UseVoiceMem",
                "-AsrBackend", "gigaam", "-TtsProvider", "tera", "-EnableProsodyPlanner",
                "-EnableStreamingAsr", "-UseOpenCodeRelay", "-EnableScreenWatch",
                "-EnableSensoryWorker", "-AmbientTriageSeconds", "300",
                "-JawlModelOverride", "deepseek-v4-flash", "-StartupTimeoutSeconds", "420"])
            .current_dir(r"G:\AI\JAWL-VoiceCompanion")
            .spawn();
        match prof {
            Ok(c) => { children.push(c); println!("[launcher] integrated profile starting"); }
            Err(e) => eprintln!("[launcher] profile spawn failed: {e}"),
        }
    } else { println!("[launcher] profile already up (2367)"); }

    // Report readiness, then keep the window alive until Ctrl+C.
    let deadline = std::time::Instant::now() + Duration::from_secs(420);
    while !port_open(2367) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_secs(2));
    }
    if port_open(2367) {
        println!("[launcher] READY вЂ” control http://127.0.0.1:2367  avatar http://127.0.0.1:8766/avatar");
    } else {
        println!("[launcher] profile did not open 2367 in time; check logs in runtime\\instances\\daily\\logs");
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

fn main() {
    println!("JAWL Companion native client");
    // Default (no args, e.g. double-click) = launch the whole stack.
    let mode = std::env::args().nth(1).unwrap_or_else(|| "--all".to_string());
    let running = Arc::new(AtomicBool::new(true));
    let r2 = running.clone();
    let _ = ctrlc::set_handler(move || r2.store(false, Ordering::SeqCst));
    match mode.as_str() {
        "--avatar" => run_avatar(),
        "--all" => run_all(),
        _ => run_mic(running),
    }
}
