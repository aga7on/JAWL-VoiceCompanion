# Qwen daily 15-minute controlled run — 2026-10-22

## Setup

- `run_local_bonsai_integrated.ps1` with Hikari (local-bonsai2), daily profile,
  `-EnableScreenWatch -Eg2Vision -EnableAmbientAudio`, `-RunSeconds 900`.
- Qwen3.5-0.8B CPU server: `127.0.0.1:8994`, `-ngl 0
  --no-mmproj-offload --cache-ram 0 --no-cache-prompt`.
- Visual lane: `--visual-describer qwen`, ROI `0.1,0.1,0.8,0.8`, target window
  `QA-Video`, active interval 1 s, static 5 s, periodic 10 s, max age 6 s.
- Controlled content: local ffplay loop of a 60 s pattern:
  15 s Earth video, 20 s static YouTube frame, 5 s “THANKS FOR WATCHING” card
  (scene change), 20 s Earth video. The window was kept topmost so the ROI
  actually showed the video.
- OmniVoice untouched.

## Results

| Metric | Value |
|---|---|
| Captures | **3501** |
| Requests submitted | **135** |
| Deliveries to PerceptionFusion | **124** |
| Dropped scene-change results | **6** |
| Dropped stale | 0 |
| Capture errors | 0 |
| Scene changes seen | **60** |
| Observation age p50 | **1258 ms** |
| Observation age p95 | **2417 ms** |
| Qwen caption present in 2 s samples | **126 / 299 (42.1%)** |
| Qwen RSS | 1039–1148 MB, avg **1129 MB** |
| Companion main RSS | ~1.0–1.1 GB |
| Hikari brain RSS | up to ~11.7 GB |
| System CPU | avg **54.9%**, max 84.8% |
| System memory | avg ~50.1 GB, 34.1–52.7 GB |

Hikari questions about the current content:

| Question | Wall time | Result |
|---|---:|---|
| «Что сейчас на экране?» | 8.581 s | described dark blue Earth, continents, city lights, glow |
| «Опиши текущую сцену и что на ней происходит.» | 3.440 s | described Earth/space plus dark window/text layers |
| «Какие объекты ты видишь сейчас?» | 2.960 s | named Earth and the dark UI layer |

The answers matched the Qwen caption present at ask time, confirming that Hikari
received the current observation rather than a stale or EG2-only hint.

## Scenario checks

- **Video:** Qwen captions described Earth, oceans, continents, city lights and
  space; Hikari repeated those facts. PASS.
- **Static screen:** the 20 s static segment produced periodic observations with
  no capture errors; no false scene churn beyond the actual cut. PASS.
- **Window switching:** with Notepad focused for 20 s, captures went
  1317→1402, submits 54→58, deliveries 50→52, capture errors 0. PASS.
- **Short scene change inside cooldown:** the video cut to the card while the
  active interval was in effect. The pending/dirty logic retained the change and
  the next allowed request went out; regression test
  `test_scene_change_inside_cooldown_sends_latest_frame_after_interval` passes.
  The exact dirty sample was not caught by the 2 s sampler, but scene_changes=60
  and dropped_scene_change=6 are consistent with the intended behavior. PARTIAL
  evidence in the live log; PASS in unit regression.
- **DND:** with DND enabled for 20 s, captures 1445→1520, submits 59→61,
  deliveries 53→56. Perception did not stop; only attention/speech is gated.
  PASS.
- **Active conversation:** while the three Hikari questions were running,
  captures/submits/deliveries increased (e.g. 2288→2320, 86→87, 80→81).
  Response wall times were 2.7–8.6 s. PASS for perception continuity; no
  baseline without Qwen was measured, so the latency delta is not isolated.
- **Qwen server disconnect:** killed PID 52508. Deliveries stayed **88→88**
  during the 20 s outage; after restart, deliveries rose **88→95** and Qwen
  captions returned. PASS for stop/restart delivery.
- **Old-caption disappearance:** **contaminated** by a bug found during the
  run: the EG2 screen-watcher sink wrote its dictionary summary into the
  `screen` channel, overwriting the Qwen caption. The draft showed
  `code_ide_terminal` from EG2 during the outage, so disappearance of the Qwen
  caption could not be proven cleanly. Fixed after the run:
  `web._perception_sink` now writes to `eg2_media`, not `screen`.
- **Window/ROI validity:** early video/static checks were accidentally made
  while the ffplay window was covered by the terminal. `observe_window` uses a
  screen grab of the window rectangle, so it captured the covering window.
  After making QA-Video topmost, direct capture and Hikari answers confirmed the
  video content. This is a real operational limitation: the target window must
  be visible, not merely existing.

## Verdict

**PARTIAL.**

Reasons for not PASS:

1. The 15-minute run had an EG2/Qwen channel collision in `web._perception_sink`;
   the Qwen caption was not reliably the `screen` caption during the disconnect
   phase. Code is fixed, but a clean re-run is required to prove old-caption
   removal and return.
2. The initial covered-window phase invalidated part of the video/static/window
   evidence; the corrected topmost phase produced valid Earth captions and
   Hikari answers.
3. Qwen caption was present in only 42% of 2 s samples because the 5 s screen TTL
   is shorter than the 10 s periodic refresh. Delivered observations were fresh
   when present, but “now” had gaps on static content.
4. Voice latency was measured with Qwen active only; no Qwen-off baseline.

What did pass: selectable composition/ROI lane, single capture source, bounded
queue, CPU-only Qwen, Hikari receiving current Earth observations, DND and
window switching not stopping perception, stable Qwen RSS (~1.1 GB), zero
capture errors, and delivery stop/restart.

## Cleanup

- Companion, Hikari holder/brain, Qwen server and ffplay were stopped.
- Ports 2367/8766/8770/8990/8994 are free; app returned to stopped state.
- OmniVoice unchanged.
