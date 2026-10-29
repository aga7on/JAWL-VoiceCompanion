# Capture-time provenance for ambient audio - 29 October 2026

## Finding

`AmbientAudioASRBridge.consume()` queued PCM without its capture timestamp. `AmbientSegmenter` assigned segment boundaries from the time its worker dequeued/processed each chunk. Under worker backlog, transcription and soundscape observations could therefore be timestamped later than the audio was captured. Freshness checks would understate observation age and could keep delayed audio in the current-context lane.

## Change

- Each submitted ambient chunk now carries a monotonic capture-end timestamp through the bounded segment queue. Split chunks retain their relative location in the incoming PCM interval.
- Segment `started_at` / `ended_at` now describe the captured audio interval; worker delay no longer rewrites observation time.
- Segment size is bounded by actual buffered audio duration/bytes, independent of how long the worker waited in the queue. Idle flush remains bounded using processing time.
- Both ASR and YAMNet/soundscape segmenters receive the same capture-time provenance.

## Verification

- `test_segment_timestamps_keep_capture_time_across_worker_backlog`: queued a captured segment, blocked the worker, advanced processing time by 2 seconds, then verified the emitted segment retained the original capture boundary.
- Ambient segmenter suite: 6/6 passed. Ambient audio integration suite: 31/31 passed.
- `py_compile` and scoped `git diff --check` passed.

This verifies timestamp propagation and regression behavior in-process. It does not prove live capture/ASR freshness under sustained CPU load; the profile and endpoint are stopped, so live acceptance remains open.
