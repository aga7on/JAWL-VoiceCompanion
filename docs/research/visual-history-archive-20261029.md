# Persisting history-only visual observations — 29 October 2026

## Finding

Fresh Qwen captions entered `SensoryHistoryStore` through `PerceptionFusion.note()`. Captions that completed after a scene change, or arrived stale but still inside the short visual-history TTL, were added only to the in-memory visual timeline. They disappeared from the one-hour history and weekly hourly summaries after process exit.

## Change

- `record_visual_event()` can persist a history-only visual event with original capture wall time, source, scene ID, frame ID, and ROI metadata.
- `QwenVisualSensor` enables persistence for stale-but-retainable and scene-mismatched captions. These events stay out of the current-screen channel.
- Ordinary `observe_caption()` explicitly leaves event persistence to its subsequent `note()` call, avoiding duplicate history writes.
- The archive still stores text and provenance only; no raw image/video is persisted by this path.

## Verification

- `test_history_only_visual_event_persists_once_without_current_caption_write` verifies one fresh event is not duplicated and a late event reaches both recent history and its hourly compact summary.
- The Qwen stale-history test verifies a stale caption is preserved in `SensoryHistoryStore` while remaining absent from current-screen.
- Perception fusion + Qwen visual sensor + sensory history + current-screen TTL suites: **41 passed**.
- `py_compile` and scoped `git diff --check` passed.

Live process-restart recall and week-long retention remain operational acceptance checks; this change verifies storage, serialization, and re-open behavior through the existing history-store suite.
