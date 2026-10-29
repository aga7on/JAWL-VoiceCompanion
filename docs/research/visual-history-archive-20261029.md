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

## Hourly compaction follow-up

The first compactor ranked moments by importance and then kept the first ten;
equal-scored scene changes therefore retained only the newest part of a busy
hour. It now keeps the earliest and latest observation and fills the remaining
slots by salience plus temporal distance from the already selected moments,
returning them in chronological order. A regression writes 20 scene changes over
57 minutes, flushes and reopens the store, then verifies ten moments still span the
hour, including its first and last scenes. `tests/test_sensory_history.py`: **5
passed**. The rolling-hour prompt budget also samples by salience and time instead
of retaining only the head and tail; late results render by original capture time.
Tests cover dense 60-event context and out-of-order completion. The expanded
`tests/test_sensory_history.py` suite is **7 passed**. This verifies store-level
compaction/reopen, not a live Companion restart or brain-generated narrative quality.

Live process-restart recall and week-long retention remain operational acceptance checks; this change verifies storage, serialization, and re-open behavior through the existing history-store suite.
