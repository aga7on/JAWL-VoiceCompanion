# Qwen 640×360 full-sequence replay

Date: 2026-10-24
Scope: 50 sequential 1-fps frames across the same five 10-second clips, replayed through the existing `QwenVisualSensor → QwenEventDescriber → PerceptionFusion` harness. Qwen3.5-0.8B Q4_K_M, CPU-only, four threads, reasoning off, 1-frame/s capture, 50s capture plus bounded drain. The 640×360 images were resized from the saved 1280×720 R2 frames into this run's isolated `frames` directory. No production profile, Hikari, or OmniVoice was touched.

## Result

The 640 run accepted 42 submissions, completed 34 unique-frame inferences, and delivered 14 captions. Eight pending frames were replaced by newer frames; 20 completed results were invalidated after scene changes. There were zero stale-result drops, capture errors, or inference errors. Source-to-completion age was p50 **1.369 s** / p95 **1.664 s**. At end of drain the latest caption was 6.70 s old against a 5 s TTL, so `caption_fresh=false`.

## Comparison with existing same-sequence replays

| Input size | Accepted submissions | Completed inferences | Queue replacements | Scene-change drops | Stale drops | Delivered | Age p50/p95 | End-of-drain caption |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1280×720 R2 | 43 | 10 | 33 | 5 | 3 | 2 | 4.828 / 4.828 s | 10.14 s, stale |
| 480×270 R3 | 41 | 36 | 5 | 18 | 0 | 18 | 0.843 / 2.968 s | 5.88 s, stale |
| **640×360 R6** | **42** | **34** | **8** | **20** | **0** | **14** | **1.369 / 1.664 s** | **6.70 s, stale** |

R6 improves greatly over full resolution in inference throughput and freshness. Compared with R3 it completes two fewer captions and delivers four fewer, with three more queue replacements and two more scene-change drops. Its delivery-age distribution is tighter than R3's (higher p50, lower p95). All three runs end with the latest caption expired after drain; none proves persistent fresh presence after a 50-second sequence.

Delivered counts by manifest interval:

| Clip / montage seconds | R2 full | R3 480 | R6 640 |
|---|---:|---:|---:|
| Russian trailer, 0–9 | 0 | 3 | 1 |
| Anime, 10–19 | 0 | 1 | 0 |
| Gameplay, 20–29 | 0 | 6 | 5 |
| Coding UI, 30–39 | 1 | 6 | 7 |
| Aqua, 40–49 | 1 | 2 | 1 |

These are delivered observations, not completed captions. In R2, 8–10 outputs from one clip may be absent due to queue coalescing; in R6, scene-change invalidation is the main delivery loss. The exact temporal sample set and harness cadence are the same; the 640 inputs were generated directly from the full-resolution R2 JPEGs. R3 used the saved 480×270 frame set.

## Interpretation

640×360 is a viable balanced resolution for continued full-sequence testing: it keeps much higher throughput and lower age than full resolution, and its age p95 is better than the 480 run here. It is not a perfect quality/performance midpoint in the pipeline: 480 completed/delivered more captions in this run, while 640 retained better detail in matched-frame checks. The high scene-change drop count indicates that improved per-caption speed alone does not solve live continuity. Acceptance should score both `inference completed` and `delivered to current context`, with age at delivery, per hard cut and within each clip.

The replay harness reports delivered observations only during callbacks, while the final state after drain can be expired; `delivered` must not be confused with `currently fresh`. These are fixture-frame replays, not physical screen capture or full JAWL conversation acceptance.

## Cleanup and artifacts

The temporary CPU server ran only on `127.0.0.1:48996`. It was stopped after the replay; its owned PID exited and the listener was verified absent. Ports 8990 and 8995 remained owned by their pre-existing services.

- R6 replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-640x360-20261024-r6/qwen-visual-replay.json`
- R6 server logs: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-640x360-20261024-r6/server.stderr.log`
- R2 full-resolution replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-20261024-r2/qwen-visual-replay.json`
- R3 low-resolution replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-480x270-20261024-r3/qwen-visual-replay.json`
- Reference ledger and mapping: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`, `runtime/multimodal-realclips-20261024/manifest.json`
