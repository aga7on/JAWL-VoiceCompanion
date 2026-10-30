# Parallel sensory lane engineering probe

Date: 2026-10-24

## Decision

Keep the modular direction requested for JAWL: an independently scheduled audio/music lane and a separate visual lane publish timestamped evidence; Hikari remains the conversational brain/fuser. The tested Hikari prompt demonstrates that a compact evidence packet can be fused, but the live runtime still needs an integrated capture-to-brain acceptance run.

## Implemented this iteration

- The existing Qwen visual sensor remains independent, with its own capture/inference workers and latest-pending frame queue. A timed-out stop followed by restart now resumes safely, including the race where the old worker is exiting. Observation age uses monotonic capture time; capture timestamps are taken immediately after the capture adapter returns.
- YAMNet now receives segments through a separate bounded worker and queue, independent of the sequential ASR/optional EG2 description worker. On overload, the oldest waiting soundscape segment is replaced with the newest and counted. Stop/cancel drains or clears both paths appropriately; results from an invalidated generation are rejected. Music results retain segment identity and are not merged with an unrelated ASR result.
- TTS and model services were not modified or started.

## Verification

Targeted suite covering ambient audio, segmenting, system loopback, YAMNet, audio understanding, fusion, ambient memory, streaming perception, and Qwen video sensor/describer: **107 passed**. The new tests explicitly cover YAMNet output while ASR is blocked, bounded latest-wins soundscape queue behavior, stale-generation rejection/restart, Qwen worker recovery after a timed-out stop, and monotonic freshness despite a wall-clock jump. Python compilation and scoped `git diff --check` passed.

## Remaining evidence gaps

- No current live capture-to-brain run yet verifies both sensor lanes publishing concurrently during real video/music playback.
- EG2 audio description remains sequential with the ASR processing worker; only YAMNet was split because the immediate requirement was independent music detection.
- CPU/RSS/queue behavior under hours of concurrent real workloads is unmeasured. Prior 8-hour native soak was not full-stack companion acceptance.
- YAMNet scores remain uncalibrated: they may indicate broad sound classes, not reliable genre or mood. Music style needs separately validated labels/model.
- Current visual short history is insufficient for long-form movie/game narrative recall; a longer, evidence-linked event memory remains open.

Next acceptance should use a replay with independently labeled speech, music and scene transitions; verify source/segment/frame IDs and monotonic time alignment through fusion into the live brain; then proceed to a 30–60 minute real playback soak before treating these lanes as always-on ready.
## Brain-bound temporal provenance follow-up

The production turn enrichment path now attaches one compact provenance line built from the same atomic `PerceptionFusion.compose_snapshot()` that supplied the context text. Fresh screen, speech, music, and sound channels carry their current age relative to that turn; screen entries include scene/frame/source IDs, while audio entries include segment/source/detector, interval duration, and an explicit uncalibrated marker for raw scores. ASR segments now pass their start/end monotonic stamps and duration into fusion metadata. This allows the brain to compare channel freshness and interval overlap instead of interpreting asynchronous arrival order as event order.

Verification after this change: combined relevant suite **188 passed, 29 subtests passed**. The earlier run without `ruamel.yaml` had 8 unrelated settings-hub setup failures; after installing that missing package into the local ignored test venv, the full web suite passed. No dependency files changed.

Remaining limitation: channel latest-values carry segment/frame identity and age, but no current live paired-media run has yet proven that Hikari correctly uses this contract under real concurrent capture; do not call the temporal fusion gate closed.

## Current-frame versus history and direct brain probe

The live Hikari probe exposed a real context-selection weakness: on a combined A/V question it could cite the older Sun frame (with its age) instead of the current classroom frame. The request still correctly separated temporal overlap from speaker attribution and semantic causality after the A/V caution was added, but current-vs-history selection was only partial.

The turn builder now labels the present channel explicitly as `Текущий экран`. For simple current-screen questions that do not ask about earlier events or a relation, it omits the bounded old-scene timeline while retaining fresh audio channels. History and A/V timestamp comparison remain available when requested. A direct local Hikari check using the production enrichment path then answered the current-screen query with the classroom observation in 0.58s; the older Sun event was absent from the brain-bound text. This is one constructed probe, not broad accuracy evidence.

After these latest changes, the combined audio, fusion, Qwen visual, and web suite passed: **189 passed, 29 subtests passed**. Full live concurrent capture and 24/7 acceptance remain open.

## 24 Oct continuation: 640x360 sequence and reproducibility check

The video lane replayed the identical 50-frame, five-clip sequence at 640x360. It accepted 42 submissions, completed 34 unique-frame requests, and delivered 14 current-scene captions; 8 pending frames were replaced, and 20 completed results were invalidated on scene changes. There were zero stale drops during capture, capture errors, or inference errors. Source-to-completion age was p50/p95 1.369/1.664s, but the final observation expired after drain (6.70s old against a 5s TTL). This supports 640x360 for further live testing, not production acceptance: delivery continuity remains poor and the final caption is stale. See `qwen-fiveclip-640x360-50frame-replay-20261024.md`.

The audio lane ran a third CPU-only five-clip replay with a new output path. All YAMNet window arrays and music-presence counts matched both earlier runs; GigaAM nonempty decisions and normalized character counts also matched. The saved artifact contains no PCM or transcript text. This verifies deterministic replay only; human-verified event boundaries, WER/CER, and style quality remain open. See `audio-music-coverage-audit-20261024.md`.

Focused verification of the current independent sensor/fusion code passed: 86 tests covering Qwen visual sensor/describer, MusicFrame, YAMNet soundscape, ambient audio, audio understanding, fusion freshness, and streaming perception. Neither live Hikari nor TTS was touched. The next acceptance still needs full capture-to-brain co-watch and then a long full-profile soak.

## 24 Oct continuation: detector sweep correction and model-path decision

A diagnostic visual-change sweep initially used Lanczos downsampling for its claimed production baseline. That differed from `QwenVisualSensor._crop`, which relies on Pillow's default BICUBIC resampler. The baseline has now been corrected on the exact R2 source JPEGs. Production-equivalent baseline: 28 predictions, 22/23 hard changes matched (6 FP, 1 miss; precision 78.6%, recall 95.7%); coding UI changes 0/4. The exploratory color/edge detector remains separate, has lower hard-change recall (78.3%), and does not classify UI changes semantically. No production threshold change is justified. See `qwen-visual-change-detector-sweep-20261024.md`.

The separate audio decision memo compares stable YAMNet/MusicFrame temporal logic, a small supervised task head, and conditional CLAP. The memo recommends the current low-cost presence/uncertainty lane now; model selection or training is premature without listener-verified labels. A tiny head could be cheaper at inference, but is not simpler overall until an adequate source-disjoint dataset exists. See `music-style-path-decision-20261024.md`.
