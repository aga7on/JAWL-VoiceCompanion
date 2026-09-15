# VoxCPM2 integration gate — 2026-09-09

## Status

VoxCPM2 is an optional streaming TTS backend. It is not the default voice
provider: TeraTTSv2 remains the default CPU profile. The existing JSON voice
contract and browser playback owner are preserved.

## Runtime layout

- Model/runtime: `G:\AI\VoxCPM` (separate repository and `.venv`).
- Worker: `scripts/voxcpm_server.py`.
- Launcher: `scripts/run_voxcpm_server.ps1`.
- Default worker port: `127.0.0.1:9891`.
- GPU profile: the launcher maps physical GPU1 to the worker's `cuda:0`.
- Companion selection: `--tts-provider voxcpm`.
- Default application selection remains `--tts-provider tera`.

The worker is loopback-only. It exposes `/health`, `/tts`, native
`/tts/stream` (NDJSON audio events), and `/cancel`.

## Voice modes

The default worker configuration is zero-shot VoxCPM2 without a reference
clip. This is the measured low-latency profile and is selected as
`voxcpm-zero-shot`. A reference clip can be passed explicitly to the worker
for cloning; this is opt-in because the tested clone quality was not accepted
as the primary companion voice and its first-audio latency is materially worse.

The worker truthfully advertises `emotion_control=false`. Speed is implemented
as bounded post-processing. The companion must not represent these controls as
native emotional control.

## Cancellation and streaming contract

The flow is:

1. `TTSService.stream()` owns the current speech generation and yields WAV
   chunks in source order.
2. `VoxCPMHttpClient` consumes the worker's NDJSON audio events.
3. Browser playback may abort its HTTP stream and explicitly POST
   `/api/tts/cancel`.
4. The Companion closes the active response and forwards `/cancel` to the
   worker. The worker stops between native generator chunks and releases its
   active generation in `finally`.
5. `web.py` closes the service generator when the browser disconnects, so the
   speech slot is released instead of remaining occupied by a stale request.

Cancellation cannot interrupt a torch kernel already executing inside a
native chunk. The accepted guarantee is bounded interruption between chunks,
not token-level cancellation inside the model.

## Evidence

Live profile: `runtime/voxcpm-native-stream-20260909.json`.

- worker health: `status=ok`, native streaming and barge-in capability true;
- 29 audio chunks, first chunk `0.342 s`;
- 4.64 s generated audio in 4.054 s, RTF `0.874`;
- cancellation test passed, followed by a successful recovery request;
- all current TTS, web, and local E2E unit suites pass after the integration.

The existing strict browser barge-in evidence remains
`runtime/browser-barge-in-20260907-strict-retry3-gap9.json`. It validates the
browser microphone/VAD/playback path and explicit TTS cancellation against the
Companion contract; it does not by itself prove subjective VoxCPM voice
quality.

## Connected browser evidence — 2026-09-10

The integrated launcher now supports `-TtsProvider voxcpm` (starts the
worker on GPU1 with `CUDA_VISIBLE_DEVICES=1` and passes
`--tts-provider voxcpm --tts-url http://127.0.0.1:<port>`; ASR path
unchanged, `-AsrBackend whisper` verified in the same profile). Live
disposable profile `voxcpm-whisper-20260909` (Gemma via Ollama 11434):

- Real-browser voice E2E passed 3/3 turns through capture, whisper-turbo
  ASR, JAWL, VoxCPM `/api/tts/stream` and WebAudio playback. Evidence:
  `runtime/browser-voice-e2e-20260909-voxcpm-whisper.json`. Timings:
  `voice_end → tts_headers` 14–34 ms; `turn_to_first_audio` 15.4–26.9 s,
  dominated by the JAWL/LLM route (`turn_to_voice_end` 12–27 s), not TTS.
- Real-browser barge-in PASSED at `gap_seconds=20`:
  `runtime/browser-barge-in-voxcpm-whisper-gap20-20260909.json` — two voice
  turns, TTS cancel during first speech, two TTS streams, 21 audio buffers,
  both transcripts matched. `gap=9` failed with whisper-turbo because the
  serial voice pipeline pauses audio uploads while `/api/voice/end`
  processes (~16 s: whisper ~3.4 s + JAWL ~12 s), so the second phrase must
  start after end-processing returns; gap must exceed that. The qwen-ASR
  gap=9 evidence remains the tighter interrupt slice for the default ASR.
- The barge-in harness now records `failure_phase`,
  `browser_state_on_failure` and a failure screenshot before the driver
  quits, so a timeout is debuggable instead of a bare TimeoutException.

## Voice consistency fix — 2026-09-10 (live session finding)

Live companion speech changed voice at sentence boundaries. Cause: the
Companion splits an answer into per-sentence parts, and zero-shot VoxCPM
(without a reference clip) samples a new speaker per generation — same seed
only makes the same text deterministic (verified: identical bytes), it does
not pin the speaker across different sentences.

Fix: run the worker with a fixed reference clip (`--reference-wav`, voice
clone mode = one speaker for all parts). Measured cost on GPU1
(inference_timesteps=10, 24 threads): first-audio 0.217–0.226 s (vs
0.157–0.175 s zero-shot), RTF 0.94 (vs 0.87) — materially cheaper than the
earlier card note suggested. The reference used is the companion's own
synthesized RU clip (`runtime/crane/logs/tts_cv_out.wav`); for production a
dedicated recorded reference (with consent) can replace it via
`-VoxCPMReferenceWav` in the launcher.

## Prosody planner — per-sentence emotion (2026-09-10 evening)

Operator request: the model feeding text to TTS must emote per sentence.
Implemented (default off, `-EnableProsodyPlanner` in the launcher):

- `src/jawl_voicecompanion/prosody_planner.py` — `ProsodyPlanner` calls the
  local OpenAI-compatible provider with a bounded prompt and returns one
  clamped envelope per sentence (`pitch`, `f0_range`, `energy`, `speed`);
  tolerant alignment pads/truncates to the sentence count; any failure
  degrades to neutral (fail-soft).
- Planner brain: **gemma-3-1b-it Q4_K_M** via llama-server on GPU1 (8987) —
  warm plan latency **0.96–1.04 s** (the 27B/12B defaults were too slow:
  10 s cold / broken 4-item JSON on Gemma-12B).
- `TTSService.stream` (Tera path): sentence 1 is submitted neutral
  immediately (first-audio latency untouched); the planner annotates the
  tail while it plays. Without a planner the legacy all-parallel path is
  byte-identical. `TeraTTSHttpClient._request_sentence` passes
  `pitch`/`f0_range`/`energy` to the worker (older workers ignore them).
- Tera worker prosody upgraded to **WORLD2** (`pyworld`): F0 rescale +
  dynamic-range shaping (formant-preserving, no phase-vocoder metal) +
  punctuation pauses (320/180 ms). Listening verdict on `world2` clips:
  «уже сильно лучше, хотя есть уловимое роботизированное» — accepted as the
  base; `librosa` pitch-shift variant rejected by the operator (metalliferous).
- E2E proof: planner 1.04 s → 5 sentences with distinct envelopes, files in
  `runtime/tts_samples/planner-e2e/` (`merged.wav` + per-sentence).
- Unit coverage: `tests/test_tts.py` — planner tail annotation + order
  preservation, and planner-failure neutral degradation (13/13 pass).

## Voice provider decision — 2026-09-10 live session

Live A/B with the operator settled the default back to **TeraTTSv2**:

- Tera's voice is a baked voice pack (`ru_f1`): the same speaker on every
  phrase by construction — the per-sentence voice-drift seen with VoxCPM
  zero-shot cannot occur. Tera worker accepts `seed` (default 42,
  deterministic) and serves complete-WAV `/tts`; the Companion streams
  phrases client-side.
- VoxCPM2 remains the opt-in expressive/clone lane. Clone mode with a fixed
  reference (Mita Kepochka clip, `runtime/models/voxcpm/ref_mita_kepochka.wav`,
  10 s, 48 kHz mono, loudness-normalized) is live-tested: operator judged
  the clone quality insufficient; levers queued — reference segment choice,
  `inference_timesteps` 10→20–30, input denoiser, and the cheap-clone
  roadmap from the duplex research (zero-shot timbre conversion e.g.
  Seed-VC real-time on top of Tera's phonetics, keeping prosody control in
  the DSP prosody layer).
- ASR for the live lane switched to Qwen3-ASR (`-AsrBackend qwen`,
  RTF ≈ 0.14, 6.2 s audio in 0.86 s) after whisper-turbo (RTF 0.385)
  proved too slow for realtime draft transcription.

## Worker-level streaming re-bench — 2026-09-09 evening

Direct `/tts/stream` re-bench (RU text, 8.8 s audio, zero-shot, 48 kHz,
`inference_timesteps=10`, GPU1 `cuda:0`, seed 42):

- first-audio cold: `1.502 s`; warm: `0.152–0.175 s` across 6 runs (p50 ≈ 0.166 s);
- RTF: `0.869–0.880` (faster than realtime on GPU1);
- 55 chunks per 8.8 s utterance; `done` event present;
- `/cancel` after the 2nd chunk stopped the stream at `0.502 s` total and the
  next request recovered normally (`first_audio 0.152 s`).

The worker holds roughly 6–7 GiB of GPU1 VRAM; it was stopped before the
`qwen-ollama-unattended-8h-v4-20260909` soak to avoid VRAM contention and can
be relaunched with `scripts/run_voxcpm_server.ps1`.

## Remaining production gate

Before making VoxCPM2 the default, run the real browser barge-in profile with
the VoxCPM worker active and record first-audio p50/p95, interruption delay,
recovery, GPU/RAM peaks, and a human voice-quality decision. Until then use
TeraTTSv2 as the stable default and VoxCPM2 as an explicit opt-in backend.
