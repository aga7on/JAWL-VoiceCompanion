# Qwen3-Omni real-clip scorecard (proposed)

This is a diagnostic acceptance protocol for the direct Qwen3-Omni profile. It does not claim that the current model, labels, or live profile has passed. Do not submit model requests while the active eight-hour soak is running.

## Existing material and limits

- Stimuli and source intervals: `runtime/multimodal-realclips-20261024/manifest.json` and `real_sensory_5x10s.mp4` (Russian trailer, anime, RTS gameplay, coding, and Aqua song; 10 seconds per case).
- Visual references: `visual-ground-truth-1fps-20261024.json`, a useful frame-level reference for entities, visible action, readable text, and unknowns. It samples at 1 fps and does not establish exact motion, within-second cuts, or audio linkage.
- Audio references: `audio-ground-truth-provisional-20261024.json/.csv` are explicitly provisional and not human-verified. Do not score transcript, genre, lyrics, or audio/video alignment against them as ground truth.

## Run matrix

For each of the five source clips, run three isolated input modes with the same crop/window and bounded prompt: audio-video, video-only, and audio-only. This gives 15 paired observations for detecting modality leakage. Add one joint 50-second pass to test temporal continuity across all four hard video cuts. Keep cache policy, context, output budget, model revision, server slot count, and prompt wording fixed across comparisons. The current target is the direct Qwen3-Omni model; do not substitute Hikari or another model.

Map each request to a question type: current scene, change/event, temporal order, readable on-screen text, speech, music/sound event, or cross-modal relation. Ask only claims that have references. Include a negative/unknown control when the source actually contains one; do not infer silence or a missing event from an unannotated interval.

## Human audio annotation required before scoring

Two listeners should independently mark half-open intervals to approximately 250 ms, allowing overlapping labels for speech, sung vocals, music, sound effects, quiet ambience, and digital silence. Record language, speech-versus-singing, intelligibility, verbatim words only when clearly audible, and confidence. For the song, mark only independently intelligible lyrics; otherwise label the span unintelligible/unknown. Mark acoustic transitions separately from known video edit times, and label audio/video correspondence only when it can be established. Adjudicate disagreements before calculating metrics. Do not record speaker identity.

For visual references, review the existing one-frame-per-second annotations and selectively add full-resolution HUD/interface text only when independently legible. Label unreadable/partial text as such. Annotate action only when supported by a frame sequence. Do not infer identity.

## Row schema and reporting

Keep one row per clip × input mode × prompt. Suggested fields:

`clip_id`, `mode`, `prompt_id`, `question_type`, `reference_ids`, `capture_time`, `delivery_time`, `source_age_ms`, `queue_delay_ms`, `model_latency_ms`, `source_status`, `expected_supported_claims`, `expected_unknowns`, `claimed_facts`, `supported_claim_precision`, `reference_claim_recall`, `unsupported_claim_count`, `abstention_correct`, `scene_order_correct`, `boundary_error_s`, `text_CER`, `ASR_WER_or_CER`, `audio_event_precision_recall`, `cross_modal_alignment_correct`, `hallucination_severity`, `annotator_agreement`, `RSS`, `VRAM`, `CPU`, `queue_depth`, and `drop_count`.

Score supported and unsupported claims separately. Report clip-macro and per-modality results so dense visual labels do not dominate. Report negative-control behavior, p50/p95 latency, freshness, memory, and queue/drop counts as separate dimensions; do not collapse them into one score. Retain reference transcripts only in the controlled scoring artifact, not routine logs.

## Proposed live gates

These are proposed criteria for a first direct-Qwen acceptance, not existing repository policy: actual full-turn prompt fits in the 12,288-token context with a measured completion reserve; no stale scene is presented as current; at least 95% of observations are fresh with source-age p95 at or below 3 seconds and no stale gap over 5 seconds during the measured run; no capture/processing drops or unbounded queue; no unsupported specific claims on negative controls. Any miss stays a reported failure and drives a targeted change plus a new matched run.

The five clips are suitable for choosing the next experiment, not a representative benchmark or proof of generalized quality. A deterministic event ledger/compressor over existing timestamps, frame changes, OCR/UIA, VAD/ASR, and low-level audio cues is likely simpler to validate for freshness and ordering than training a micro-model. Train a narrow classifier only if this human-reviewed set reveals a repeated failure that existing rules/features cannot cover.
