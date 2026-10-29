# Manual visual reference ledger for the five local clips — 24 Oct 2026

This is a hand-authored visual reference set for the existing 50-second local montage. It was prepared by inspecting the 1-fps contact sheet and the source/time manifest; it uses no model labels, new downloads, or inference. The ledger has one row per sampled second (0–9 of each 10-second clip), with montage time, clip-local time, a coarse visual state, whether a sampled change is apparent, visible entities, an action only when the still supports one, screen-text readability, and unresolved points.

## Artifacts and source mapping

- Structured ledger: [`visual-ground-truth-1fps-20261024.json`](../../runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json)
- Existing 1-fps image reviewed: [`all-frames-1fps.jpg`](../../runtime/multimodal-realclips-20261024/probes/all-frames-1fps.jpg)
- Source/time manifest: [`manifest.json`](../../runtime/multimodal-realclips-20261024/manifest.json)
- Local clips: `runtime/multimodal-realclips-20261024/probes/01_ru_trailer.mp4` through `05_aqua_song.mp4`

The montage starts are 0, 10, 20, 30, and 40 seconds. Clip-local samples are integer seconds 0–9, with the first sample at local t=0. Source windows are in the ledger's `clips` array. The five inter-clip boundaries at montage 10/20/30/40 are known from the manifest; within-clip boundaries are only marked when a clear visual change is apparent between sampled images. A change between two samples is not an exact cut timestamp.

## Annotation rules

- `scene_id` is a manual coarse visual-state ID, not an assertion that every change is a film edit. Coding UI state changes are distinguished from scene cuts.
- `entities` describe visible categories only. People are not named, relationships/intent are not inferred, and game title/unit identity is left unknown.
- `action` is null unless a single sampled pose visibly supports a restrained description. A still does not establish motion, cause, result, or what happened between samples.
- `screen_text.readable_excerpt` is populated only for two short anime title fragments judged legible in the contact sheet. Other visible overlays and UI text are marked unreadable or partial; use OCR/UIA and a higher-resolution human check for text scoring.
- `unknown_notes` records the most salient ambiguity. The ledger intentionally contains no audio labels, ASR transcript, speaker, or audiovisual correspondence.

## Limits and use

This is a small, source-correlated reference ledger for offline evaluation, not a benchmark or statistically independent ground truth. The 1-fps sheet misses brief actions, intermediate cuts, fine HUD values, and precise text. It can support a first pass at frame-level object/action grounding, visible-text abstention, coarse scene ordering, and error analysis against saved captions. It cannot by itself validate continuous video understanding, audio-video synchronization, exact cut timing, OCR accuracy, or live capture freshness.

Recommended use: score a later, separately authorized current Qwen visual-path replay against this ledger with scene-boundary tolerance of one sample, supported/unsupported claims, action-role correctness, text CER only for independently verified readable strings, scene/frame provenance, queue replacements, and capture-to-delivery age. Ask current-scene and recent-change questions separately. A pass on this offline packet is not integrated 30–60-minute or 24/7 acceptance.
