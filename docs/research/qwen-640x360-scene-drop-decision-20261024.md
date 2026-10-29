# Decision memo: 640×360 scene-change drops

Date: 2026-10-24
Evidence: full 50-frame R6 replay, current `QwenVisualSensor` / `QwenEventDescriber` behavior, existing frame ledger and manifest. No server or production code was changed for this analysis.

## Diagnosis

R6 accepted 42 frame submissions and completed 34 unique-frame inferences. The describer replaced 8 pending frames; after inference, the sensor discarded 20 results from the **current-screen channel** because the scene ID had moved on. It delivered 14 current observations. Source-to-completion age was p50 1.369 s / p95 1.664 s; the final caption expired during drain. This is not chiefly an inference-error problem: there were zero errors and zero stale-result drops.

The code explains the split. `_tick()` computes a global 32×32 grayscale signature difference and increments `scene_id` whenever it exceeds `scene_threshold` (0.08), then invalidates the prior screen caption immediately. `_deliver()` only treats a result from the newest scene as current. A result tagged with an older scene is sent to `record_visual_event` when that API exists and counted as `dropped_scene_change`; it is not delivered as current, and only recent events within PerceptionFusion's bounded horizon remain in its history. Thus the 20 count is “not current-screen deliveries,” not necessarily 20 erased captions.

The 1-fps content has many legitimate cuts: the ledger has 10 coarse anime scene states, while the sensor assigned one scene to each sampled anime frame. Conversely, the sensor retained one scene across all coding UI samples where the ledger labels four UI states, and assigned nine states to Aqua where the ledger labels five. The current pixel score is therefore a useful change trigger, not a reliable distinction between hard cut, motion, and semantic/UI state change. Rapid cuts plus roughly 1.4 s source-to-completion age naturally make captions late for the current screen.

## Competing implementation hypotheses

| Branch | Hypothesis and approach | Pros | Costs / risks | Falsifier |
|---|---|---|---|---|
| **A — Cadence/trigger is the main bottleneck** | Make visual cadence load-aware (e.g. cap requests near measured service capacity), reduce redundant submissions during a busy request, and prioritize the newest frame at hard cuts. | Small deterministic change; reduces the 8 queue replacements and avoids work on frames that cannot finish before the next capture. | Slower polling can miss one-second cuts; it does not correct current scene IDs or preserve useful transient descriptions. Lowering the active rate may make the stream feel less alive. | Replay the same 50 frames at a 1.5–2 s target cadence. Reject this as the primary fix if queue replacements fall but useful hard-cut coverage/current-delivery rate also falls or caption age remains above TTL. |
| **B — Current/history semantics and cut-vs-motion are the main bottleneck** | Separate “large hard cut” from ordinary motion/UI change; only a confirmed cut invalidates current context. Preserve superseded captions as short, timestamped, scene-scoped history, and allow them to inform “what just happened?” without presenting them as current. Keep a new scene pending until its caption arrives. | Aligns with a living co-watcher: never labels an old frame as now, while retaining transient scenes and their order. Addresses the 20 scene-change rejections directly and keeps provenance. | A bad cut classifier can either leak stale captions into “now” or over-segment motion. Existing event history has a short TTL and can crowd out fast changes; this still cannot describe a shot shorter than inference latency in time to the viewer. | First score cut labels offline on the existing 50 frames. Then compare baseline vs. hard-cut/history policy on the same sequence. Reject if it reduces scene-change rejection but increases stale-current errors, loses event order, or fails to raise correctly attributed current-or-recent scene coverage. |
| **C — Coarse plus targeted detail is the main bottleneck** | Keep 640×360 as a coarse lane, then request a high-resolution ROI/OCR only for text-heavy UI, explicit game-state questions, or a detected salient change. | Preserves the throughput advantage while giving the brain verified UI text or details only when useful. Matched A/B showed 640 can read model names better than 480, while full res is much slower. | Extra scheduling and CPU use; extra ROI calls can worsen queue pressure. OCR can verify text but will not resolve motion, hostility, or game-event semantics. | Replay the same frames with escalation only on labeled text/UI frames and explicit gameplay queries. Reject if verified detail does not improve enough to justify extra latency/CPU, or if it crowds out current scene captions. |

## Build vs. train

A small **deterministic** cut/change detector and delivery policy is the simpler next step than training or searching for another VLM. The current failure is mainly attribution and scheduling around scene IDs, while Qwen is already producing plausible broad captions. Use a transparent combination of frame difference, color histogram, edge/UI-region change, and short hysteresis; score against the ledger's labeled scene/UI states before wiring anything into production. A tiny trained hard-cut classifier becomes worth considering only if the deterministic detector fails on held-out motion/cut cases and a source-disjoint dataset shows a clear gain. The present five clips are too small and correlated to justify training a model for this gate.

## Next discriminating experiment

Run a no-inference detector sweep on the immutable 50 existing frames, using ledger `scene_id`/`change_before` labels: compare the current 32×32 grayscale threshold with a two-frame hysteresis plus a simple color/edge change signal. Report hard-cut precision/recall with ±1-second tolerance, false scene changes inside gameplay, missed coding UI state changes, and per-clip segment counts. This is cheap and isolates whether the detector is the problem before spending another 50-second Qwen replay.

If it passes, the next replay should keep the same 640 frames and cadence but separate current caption from a 15-second provenance-bearing event history. Acceptance should report current deliveries, recent-event retention, stale-current violations, cut-to-caption age, and queue replacement separately. Baseline for that A/B is R6: 34 completions, 8 queue replacements, 20 scene-change rejections, 14 current deliveries, age p50/p95 1.369/1.664 s, expired caption after drain.

## Sources

- R6 exact replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-640x360-20261024-r6/qwen-visual-replay.json`
- Sensor and describer logic: `src/jawl_voicecompanion/qwen_visual_sensor.py`, `src/jawl_voicecompanion/qwen_event_describer.py`
- Reference scenes and changes: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Time/clip mapping: `runtime/multimodal-realclips-20261024/manifest.json`
