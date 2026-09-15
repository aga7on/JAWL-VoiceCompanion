# Sensory stack design — streaming perception for the companion (2026-09-10)

Adopted principle (matches the full-duplex research pattern): **fast
specialized models run constantly, heavy VLM runs periodically, the LLM never
sees raw media** — it reads compact `MusicState` / `VisualState` /
`SpeechState` JSON. Realtime budget is reserved for conversation; sensory
context may lag seconds.

## Audio stack (desktop loopback → MusicState)

| Tier | Cadence | Component | Produces | Measured |
|---|---|---|---|---|
| T0 | continuous | WASAPI loopback (pyaudiowpatch) | 48 kHz stream, ring buffer | proven smoke: 93 chunks/0 drops |
| T1 | 250–500 ms | librosa features | BPM, beat phase, RMS energy+trend, spectral centroid, onset rate | 60 s audio → 2.3 s total |
| T1 | 500 ms | chroma + Krumhansl | key + confidence | C#-major detected near actual Ab (±5th) |
| T2 | 1–3 s | Basic Pitch (ICASSP'22, TF) | top notes + confidence | 15 s → 2.8 s (5.4× realtime); notes matched the Ab-major scale; polyphonic master lowers confidence (known limit) |
| T3 | 3–10 s | CLAP (laion/larger_clap_general, GPU) | zero-shot tags: genre, vocals, mood, events | 30–32 ms per 10 s chunk (GPU1), load 6.5 s; Rick Astley bench: "energetic dance music" 0.57–0.99 + "upbeat male pop vocals singing" — correct |
| Speech lane | on VAD | Silero VAD → whisper-turbo | speech text | RTF 0.385 (CPU); music → hallucinated text → filter drops it (by design whisper serves speech only) |
| Speech lane | on VAD | DUSHA wav2vec2 SER (RU) | emotion: angry/sad/positive/neutral | pending install |
| Optional | 250–500 ms | Essentia (if Windows wheels) | tighter BPM/key, tonal/spectral descriptors | Tier1 librosa is the fallback; same JSON schema |

`MusicState` example (real bench output, 60 s of YouTube playback):

```json
{"schema": "MusicState/1", "music": true, "bpm": 156.2,
 "beat_phase": 0.208, "key": "C# major", "key_confidence": 0.542,
 "energy_rms": 0.1588, "brightness_hz": 2624.5, "onset_rate_per_s": 9.6,
 "notes_top": [{"note": "D#4", "confidence": 0.59}, ...]}
```

## Screen stack (desktop capture → VisualState)

| Tier | Cadence | Component | Produces | Measured/notes |
|---|---|---|---|---|
| T0 | continuous | mss/dxcam capture + pHash diff | scene-change events | 1 FPS capture, 57 frames/60 s (bench) |
| T0 | continuous | Win32 active-window API | app/window title, foreground process | free, no model |
| T1 | 2–5 Hz | MobileCLIP2-S0/S2 (image↔text) | scene/style/theme tags ("code editor", "dark theme", "video player", "game") | analog of CLAP for vision; to install |
| T2 | on change | PP-OCRv6-tiny (or existing PaddleOCR worker) | visible text/UI strings | OCR-on-demand gate: only on scene change / user ask |
| T3 | 2–10 s | Qwen3-VL-2B Q4 (llama-server, GPU1) | short RU caption, reasoning | warm 2.5 s per caption (17.9 s cold first), 48 kHz… GPU VRAM ~2.5 GB; video content described |
| Camera lane | deferred | YOLO26n + ByteTrack, RTMPose-t, X3D/MoViNet, Video Depth | people/objects/poses/actions | for a webcam/user-presence scenario later; desktop screen needs none of these |

`VisualState` shape: active app/window + scene tags + changed regions +
optional caption + optional OCR strings, all with timestamps.

## Fusion

`sensory_worker` merges screen+audio events in a sliding window into typed
sensory observations (L0 ring buffer 60–120 s) → VoiceMem/ambient path →
JAWL. The composer layer (Gemma/JAWL) turns `MusicState`+`VisualState`+
`SpeechState` into natural RU context understanding; structured facts stay
the interface (per the duplex research: discrete structured transfer between
lanes).

## Bench verdict (Rick Astley scenario, 2026-09-10)

60 s of YouTube playback captured (loopback 48 kHz + 57 screen frames):
- MusicState built in 5.1 s for 60 s audio (streaming cadence cheaper);
- CLAP tags correct and nearly free (30 ms/chunk);
- Qwen3-VL-2B captions: "чат в мессенджере…", "визуальный редактор кода…" —
  accurate for non-video desktop frames; 2.5 s warm latency fits the 2–10 s
  tier;
- whisper on music → hallucinated «Редактор субтитров А.Семкин» — confirms
  ASR must be gated by VAD/speech detection (already the design);
- heavy audio-LMs (Qwen-Omni, Audio Flamingo) stay rejected: RU-gate risk +
  weight cost; richer descriptions come from more cheap extractors + LLM
  composition, not a bigger audio model.

Composer proof (Gemma, Ollama 11434, temp 0.2): fed only MusicState + CLAP
tags + screen caption →
«Ты смотришь видео на YouTube под энергичную танцевальную поп-музыку с
мужским вокалом. Темп трека довольно быстрый.» — natural RU context from
structured facts, no hallucination. This validates the full chain:
loopback → MusicState/CLAP → composer → sensory observation.

## Visual T1 bench — MobileCLIP2-S0 (2026-09-10)

- Loaded via open_clip 3.3.0 (`MobileCLIP2-S0`, checkpoint
  `mobileclip2_s0.pt` from HF `apple/MobileCLIP2-S0`); the pip `mobileclip`
  package is v1-only, MobileCLIP2 lives in the repo's `mobileclip2/`
  subpackage and open_clip model list.
- Image encode: **35–37 ms per 1120 px frame on CPU** (S0, 256 px input) —
  2–5 Hz cadence trivially cheap; text prompts cached once.
- Desktop tags on captured frames: "a photograph of a person" 0.48–0.58 on
  frames showing the music video subject; correct semantic pick.

## Speech emotion bench — DUSHA wav2vec2 (2026-09-10)

- Model: `xbgoose/wavlm-base-speech-emotion-recognition-russian-dusha-finetuned`
  (WavLM-base, 95 M, CPU). The repo ships no preprocessor config — build
  `Wav2Vec2FeatureExtractor` manually (16 kHz, normalize, attention mask).
- Labels: neutral/angry/positive/sad/other.
- Sanity: neutral RU TTS clip → `neutral 0.869`; 10 s music → `other 0.982`
  (correctly refuses speech-emotion on music). Load 0.5 s, inference
  0.24–0.53 s per ≤20 s clip.

## EmotionEngine v0 (DSP prosody) — 2026-09-10

Implemented in `scripts/voxcpm_server.py` (additive, backward compatible):
`pitch` (semitones, ±6) and `energy` (0.5–1.5) join existing `speed`; each
step is skipped when neutral so the default contract is unchanged. The
prosody planner maps agent emotion → envelope (happy: pitch+2/energy 1.15/
speed 1.08; angry: +1/1.3/1.1; sad: −1.5/0.8/0.88; calm/whisper as config).

Bench on GPU1 (9895): all four envelopes generated; whisper roundtrip shows
the transcript is byte-identical across neutral/angry/sad — DSP shaping
preserves Russian phonetics. DSP overhead is milliseconds on 2 s audio.
StyleStream remains deferred (licence + RU production test needed); CosyVoice3
CUDA stays an optional replacement lane; RVC/Seed-VC rejected for emotion
(voice conversion, not prosody control).

## Sensory worker soak (2026-09-10)

`scripts/sensory_worker.py` — prototype: loopback ring buffer (120 s) +
screen pHash/window-title stream + music-state thread + Silero-gated speech
thread, NDJSON output. Soak 240 s: 479 screen events, 43 music_state, 1
speech event, worker_stop recorded `captured_seconds=120.0` (ring cap).
Music analysis costs **0.158 s per 60 s window** — the adaptive-rate design
is effectively free. First soak exposed a missing `stream_callback` in the
audio capture thread (fixed; screen-only evidence retained as
`runtime/sensory-soak-20260910.ndjson`, fixed run as `...-r2.ndjson`).

Known refinement: the single speech event during the soak was a music
hallucination (whisper «Редактор субтитров…» on instrumental audio) — the
speech lane must additionally gate through the existing ASR-noise filter
and/or reject when SER says `other`; not yet wired.

## Adoption order

1. MusicState T1/T2 (librosa + Basic Pitch) — done, benches recorded.
2. CLAP T3 worker (GPU1, rare cadence) — bench done; wrap into worker.
3. Screen T0/T1: pHash + win32 window + MobileCLIP2 install/bench.
4. OCR-on-change (PP-OCRv6-tiny vs existing PaddleOCR worker — decide by bench).
5. DUSHA SER for speech intonation.
6. sensory_worker.py prototype (L0 ring + NDJSON events) + 15 min soak
   (RAM/VRAM stability).
7. Integration acceptance per docs/MULTIMODAL_MODEL_GATE.md (A–E on the
   bundle), then ambient/VoiceMem wiring.
