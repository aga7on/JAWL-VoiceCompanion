# Qwen visual context continuity audit: saved 640?360 full-50 trace

Date: 2026-10-24
Scope: read-only audit of `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-640x360-20261024-r6/qwen-visual-replay.json` against the 50-frame visual ledger and manifest. No model, service, or production code was run or changed. Audio observations are out of scope.

## Method and provenance

Each accepted request in `submission_trace` was joined by `frame_id` to its source JPEG, `clip_local_t_s`, `observed_at`, and `scene_id`; each final caption was joined by `source_frame`. A 64?128 retry was grouped with the same source frame and only the final 128-token caption counted. The 50 ledger entries supply the manual scene/UI-state labels. The report only calls a claim supported when the static visual evidence is sufficient; action and OCR claims that a still or ledger cannot verify remain uncertain.

The captured source-to-request mapping is present for all 42 submitted requests, and the 14 delivered observations map to those same request IDs and scene IDs (no provenance mismatch among delivered captions). `transport_trace` contains 37 transport attempts but represents 34 unique completed source frames: frames 005, 014, and 040 each have a truncated 64-token attempt followed by a final 128-token answer. The artifact reports 512 capture-adapter calls over the 50-second replay, 42 submits, 8 queue/describer drops before completion, 34 completed captions, 20 completed results discarded on scene change, 14 delivered to current context, and 0 capture/inference errors.

Delivered-caption age was 953.6?1872.0 ms (p50 1379.3 ms, p95 1736.6 ms). At the final snapshot the latest caption had aged to 6700 ms, beyond the 5000-ms TTL, and `caption_fresh=false`. Thus the trace shows timely delivery at individual completions but also a stale/empty current caption after the run drains; freshness must be judged at the moment of the user's question, not from a historical successful delivery.

| Clip | Completed unique captions / 10 frames | Delivered to current context / 10 | Notes |
|---|---:|---:|---|
| Russian trailer | 6/10 | 1/10 | Only the final sampled close-up (`t=8`) survived scene invalidation into current context. |
| Anime | 8/10 | 0/10 | Inference ran, but no caption was delivered as current context. |
| RTS gameplay | 6/10 | 5/10 | Several frames in one sensor scene were delivered. |
| Coding UI | 9/10 | 7/10 | Captions cover through `t=37`; the `t=38` input and `t=39` settings states were not delivered. |
| Aqua video | 5/10 | 1/10 | Only final microphone close-up (`t=49`) was delivered. |

## Temporal and content observations

**Gameplay (`t=21,23,24,26,27`; one sensor `scene_id`).** The captions evolve from circular structures and a vehicle to a ?cactus-like plant,? a ?dinosaur-like creature,? a tank, then a military base ?being attacked by alien creatures.? The ledger supports a top-down RTS battlefield with units and structures but does not label a cactus, dinosaur, or attack action. The shifting object names may partly track different visible units, but the exact identities and attack narrative are not established by the labeled evidence. The captions omit the stable high-level context that would make a useful co-watcher summary: this is a top-down RTS game with HUD panels/minimap-like UI. This is a continuity/abstraction gap, not proof that each object noun is false.

**Coding UI (`t=30?37`; one sensor `scene_id`).** Captions call the model-menu screen a list of uploaded video files and later a list of game accounts; those interpretations conflict with the ledger's model/list menu. The cursor and changing interface contents are sometimes grounded, but one caption invents ?a person ? in front of a dark screen? where the ledger describes a coding-assistant window and text pane. At the known UI transition at `t=35`, the model describes a task/sidebar entry, which is broadly compatible with the ledger's coding-chat panel but contains exact text details the ledger only marks partial. The next known input/settings changes (`t=38,39`) have no delivered caption. For UI-state recognition, this is at best a partial hit at `t=35`; the run does not demonstrate reliable recognition of all four labeled UI updates.

**Trailer and performance close-up.** The sole delivered trailer caption says the man is smoking; the ledger only establishes a man in profile and a small bright point near his face, so smoking is an uncertain action inference. The final Aqua caption says the woman is singing; the visual ledger only establishes a woman close to a microphone. Because this audit excludes audio, ?singing? is not a visually verified claim.

**Text.** Some generated captions make precise claims about Russian or English text, but the ledger marks the relevant excerpts unreadable or only partial and provides no exact transcription. These are unverified OCR-like claims here; this audit cannot score text correctness. The repeated ?list? interpretations on the model menu and the unsupported person claim are sufficient to show why text and UI semantics need their own labeled checks.

## Decision and next discriminator

This saved trace is enough to establish exact frame provenance, queue outcomes, completion latency, delivery freshness, and several qualitative continuity/UI failure modes. It does **not** establish a fair temporal-stability score: most clips have too few current-context captions, the sensor's internal scene IDs do not align one-to-one with ledger UI states, and the ledger intentionally avoids inferring motion between 1-fps samples.

The next smallest informative offline test is a **frame-aligned delivery/grounding replay audit** over this same artifact, keeping the immutable source mapping and adding one independent annotator pass for only the 34 final captions. For every caption, record supported/contradicted/uncertain claims; salient omitted ledger facts; exact visible text vs unverified text; and whether a within-scene caption preserves stable scene identity while allowing local object changes. Separately report:

1. Per-clip completed-caption coverage and current-context delivery coverage, with per-caption age at delivery and at end/TTL expiry.
2. UI-state detection for the four labeled coding changes (`t=32,35,38,39`): delivery within ?1 s, whether the new state is named correctly, and whether stale prior UI text survives after each transition.
3. Scene continuity across gameplay and coding: supported-claim precision, contradiction rate, salient-fact coverage, unsupported action/plot claims, and caption-to-caption identity drift. Keep this separate from detector hard-cut metrics.

A useful follow-up should not rerun Qwen first. It should score saved output independently and identify whether the main failure is (a) inference content, (b) scene-change invalidation dropping useful results, or (c) insufficient caption delivery cadence. If the same source-disjoint test shows that captions are grounded but transitions are dropped, adjust deterministic delivery/history policy before considering another model. If object/action claims still fail with fresh delivered frames, compare a higher-resolution or targeted-ROI description only on those frozen frames. Training a small model is premature until an independent annotated set demonstrates a repeatable failure that deterministic routing/ROI/OCR cannot address.

## References

- Exact trace: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-640x360-20261024-r6/qwen-visual-replay.json`
- Visual-only ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip/source manifest: `runtime/multimodal-realclips-20261024/manifest.json`
- Related detector diagnostic: `docs/research/qwen-visual-change-detector-sweep-20261024.md`
