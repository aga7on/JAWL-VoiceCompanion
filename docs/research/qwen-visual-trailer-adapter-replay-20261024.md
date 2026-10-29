# Qwen visual sensor replay on the Russian trailer — 24 Oct 2026

## Scope

Replayed the ten-second Russian live-action trailer through the current
`QwenVisualSensor -> QwenEventDescriber -> PerceptionFusion` path. Ten frames
were extracted at 1 fps and 640x360. An in-memory fixture adapter supplied the
frames at one-second intervals; this deliberately tests the sensor/queue/model/
fusion code without claiming to test physical desktop capture. The model was
Qwen3.5-0.8B Q4_K_M on a temporary llama.cpp CPU server with four threads,
prompt cache disabled, and a one-slot queue. No audio or Hikari brain request
was part of this replay. Existing servers on ports 8990 and 8995 were left
untouched; temporary port 48994 was closed afterwards.

## Result

In the final isolated run the fixture was polled 144 times over 10 seconds;
the sensor submitted 8 frames and detected 5 scene changes. The model completed
6 requests without inference errors; the one-item pending queue replaced 2
frames. Four completed captions belonged to scenes that had already changed and
were rejected from the current-screen channel. Two captions reached fusion.
No result was rejected for exceeding the six-second age limit. Delivered age
was p50 2.68 s and p95 4.28 s. During each callback, `PerceptionFusion.compose()`
contained the newly delivered caption. By the end of the drain period the last
caption had aged past the five-second screen TTL, so the final `compose()` was
empty, as intended.

The accepted captions were limited to two shots: a seated group in a dim scene
and a man smoking. One attempted Russian title-card transcription contained
replacement characters and was not usable. Several intermediate shots never
reached the brain-facing current channel. The source marker was truncated by
the existing 64-character source envelope; the recorded run ID and fixture
scope remain in the JSON artifact.

## Decision

The Russian trailer is a suitable real-content case, but this result does not
support narrative continuity for rapid cuts. The sensor correctly keeps stale
scene captions out of “now,” yet the measured path had no separate bounded
timeline through which the brain could inspect completed events from the last
few seconds. The latest-frame queue also coalesces fast scene changes when CPU
inference falls behind.

After this measurement, `PerceptionFusion` gained a bounded visual-event window:
up to five distinct scenes for 15 seconds, carrying capture time, source, frame
and scene IDs. Historical entries are explicitly labeled as history and the
current caption keeps its separate five-second TTL. Late prior-scene results
may enter this short history but cannot replace the current screen or trigger
the attention callback. Focused fusion/sensor tests pass. This implementation
closes the missing mechanism, not the acceptance gap: rerun the trailer through
the changed path, ask what just happened while the event window is fresh, then
score the whole five-clip set. A faster model or training is not justified
until that replay shows which residual errors remain.

This replay does not verify physical screen capture, audio alignment, the
Hikari brain's use of the delivered captions, actual text recognition, or
continuous daily-profile operation.

Artifacts: [`replay_sensor.py`](../../runtime/instances/goal-trailer-visual-replay-20261024/replay_sensor.py),
[`trailer-sensor-replay-final.json`](../../runtime/instances/goal-trailer-visual-replay-20261024/trailer-sensor-replay-final.json).
### Russian trailer: short visual event history + Hikari uptake — 24 Oct 2026

Replayed the same 10 extracted 640x360 trailer frames through the updated Qwen sensor and 15-second bounded fusion timeline, then submitted one direct Hikari completion with a fresh timeline snapshot. Qwen submitted 8 frames, detected 5 scene changes, delivered 2 current captions; the event window held 4 distinct scenes. Seven inference requests completed, one pending frame was replaced, with zero inference errors. The Hikari request completed in 1.79s and named specific visual details from earlier scenes, showing that the timeline text reaches the brain endpoint. The response was cut off at the 120-token cap and did not reliably distinguish a current frame from prior scenes; a second narrowly prompted direct probe produced generic dramatic-story interpretation. Treat this as evidence of context transport, not reliable narrative understanding or Companion chat acceptance. Audio/transcript was not evaluated in this visual replay. Artifact: `runtime/instances/goal-trailer-visual-replay-20261024/trailer-sensor-replay-timeline-hikari.json`.


### Matched-production replay after adding bounded scene history - 24 Oct 2026

The immediately preceding ad hoc attempt is not a valid production result: its temporary llama.cpp server omitted the daily profile's cache, slot, context, and reasoning flags. Its empty-caption outcome should not be used to characterize the configured sensor.

A fresh owned CPU server was then launched with the exact managed Visual Qwen arguments in `scripts/run_integrated_profile.ps1`: Qwen3.5-0.8B Q4_K_M, 4 threads, 4,096 context, one slot, CPU-only, reasoning off, prompt/RAM/idle-slot caches disabled, and the same multimodal projector. A direct streaming request on trailer frame 8 returned a non-empty, non-truncated caption in 1.75 s. The 10-second sensor replay submitted 8 frames across 5 scene changes; 7 descriptions completed without inference errors, 1 pending frame was replaced, 3 captions were delivered as current, and 4 late-scene captions were retained in the bounded event window. Delivered age p50/p95 was 3.42/3.83 s. The window contained four events (scenes 3-6) with frame, scene, source and capture-time metadata. The current caption correctly expired after the replay drain; it was available during the delivery callbacks. The artifact records `brain_result: null`: no Hikari request was made.

The timeline now transports a short scene history through the actual sensor/describer/fusion code, but content grounding remains mixed. Qwen reversed who carries whom in one outdoor shot and misread the visible Russian title while the prompt asks it not to transcribe text. Other sampled descriptions matched broad visible content. Treat visual-event history as useful context with fallible claims; OCR/UIA should own readable text and uncertain actions need abstention. This fixture replay still does not prove physical capture, brain uptake, audio/video alignment, or integrated Companion acceptance.

Raw result: `runtime/instances/goal-trailer-visual-replay-20261024/trailer-sensor-replay-event-window-production-20261024.json`. The temporary server was stopped through its owned command session and port 48994 was verified free.
