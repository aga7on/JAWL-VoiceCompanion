# Qwen-off / Qwen-on comparison — 2026-10-22

## Code changes before the comparison

- `PerceptionFusion.include_eg2_media_in_scene`: in the Qwen profile this is
  **False**, so `compose()` no longer mixes the EG2 dictionary summary into the
  factual scene text. The EG2 observation remains in the media buffer and in
  `state()` for embeddings/memory.
- `web._perception_sink` and `StreamingPerception` write EG2 summaries to
  `eg2_media`, never to `screen`.
- Window capture metadata now states the real semantics:
  `capture_semantics="visible_screen_region_of_target_window"` and
  `content_capture_guaranteed=False`; the Qwen source is
  `screen:target_visible_region:roi=...`.
- For the controlled run: ROI `0.1,0.1,0.8,0.8`, target `QA-Video`,
  `static=2`, `periodic=2`, `active=1`, TTL unchanged at 5 s.
- The QA video window was explicitly topmost/visible before both runs; same
  60 s loop for both: Earth → static YouTube frame → “THANKS FOR WATCHING” card
  → Earth.

## Recorded voice requests

Same three WAV fixtures (`runtime/synthetic-questions/question-01..03.wav`),
same chunking and `/api/voice/end` path. Other services (Hikari, GigaAM, TTS,
VoiceMem, ambient audio, EG2) unchanged.

| Turn | Cold? | Qwen off | Qwen on |
|---|---:|---:|---:|
| 1 | cold | **4.561 s** | **4.220 s** |
| 2 | warm | 13.681 s | 12.933 s |
| 3 | warm | 9.525 s | 11.058 s |
| warm p50 |  | **11.603 s** | **11.995 s** |
| all p50 |  | 9.525 s | 11.058 s |

Cold answer was slightly faster in the Qwen-on run; warm p50 was +0.39 s
(3.4%), within the noise of three turns. No material voice-latency regression
was observed in this sample.

## CPU and memory

| Metric | Qwen off | Qwen on |
|---|---:|---:|
| System CPU avg / max | **45.3% / 93.6%** | **75.9% / 96.7%** |
| Companion RSS | ~1.05–1.09 GB | ~1.07–1.08 GB |
| Qwen RSS | 1.039 GB idle (loaded, not called) | 1.082–1.104 GB |
| Brain RSS | ~10.8 GB | ~10.7 GB |
| System memory avg | 51.8 GB | 58.0 GB |

The Qwen server was left loaded in both runs so the model memory is comparable;
in the off run it received no calls (0.1% CPU). The on run added roughly
**30 percentage points** of system CPU and about **1.1 GB** for the Qwen
process; companion RSS was essentially unchanged.

## Qwen-on visual counters

- **2030** captures, **281** submitted, **238** delivered.
- **37** dropped scene-change results, 0 stale, 0 capture errors.
- **42** scene changes.
- Delivery age: **p50 1392 ms, p95 2631 ms**.
- `compose()` drafts contained the Qwen caption and **no `eg2_media`** text
  (`has_eg2=False`); the static/periodic=2 refresh kept a fresh caption
  available while staying under the 1 req/s active limit.
- Hikari answers on the same content described Earth, continents, city lights
  and space, matching the Qwen caption.

## Captured evidence and limitations

- The earlier covered-window problem was avoided by making `QA-Video` topmost
  before both runs; direct capture showed the video, and the new metadata tells
  consumers that only the visible screen region of the window is captured.
- The sample is three recorded voice turns per condition, so the latency
  difference is directional, not statistical. A longer series would be needed
  for a confidence interval.
- The Qwen-off run had the Qwen model loaded but idle; this is deliberate for
  memory comparability. If “off” must also free model memory, subtract/restart
  the server and expect ~1.1 GB less RSS.
- The next economical step is to store caption time separately from
  “image unchanged” confirmation time; this would keep the true caption age
  while avoiding extra model calls. It is not implemented in this run.

## Verdict

**PASS for the requested comparison.** The EG2 semantic admixture is removed
from the Qwen scene text, TTL and refresh are aligned for the controlled run,
capture semantics are explicit, and the recorded voice comparison shows no
material latency regression. Limitations are sample size and the extra memory
of keeping the Qwen server loaded during the off condition.
