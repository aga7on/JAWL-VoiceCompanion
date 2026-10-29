# Visual stale-context handling — 29 October 2026

## Finding

Scene invalidation set `possibly_outdated`, but the composer still rendered that caption in the current-screen section. The recent visual timeline also treated an invalidated scene as current and hid its historical event. Separately, `QwenVisualSensor._deliver()` did not use the describer's `stale` flag or update the existing stale-result counter, so delayed output could refresh the screen channel.

## Change

- Invalidated screen observations are omitted from the current-screen text and no longer suppress their own event from the short visual timeline.
- A stale Qwen result is archived with its original capture timestamp only when it fits the configured visual-history TTL. It never updates the current screen or triggers the fresh-observation callback.
- A stale result outside the history window is dropped and increments `dropped_stale`; accepted historical results increment `stale_history_recorded`.
- Scene-mismatched results continue to be archived or rejected by the same short history horizon.

## Verification

- Qwen visual sensor: 18/18 passed, including stale result kept as history, stale result beyond history TTL dropped, and scene change removing the old caption from current-screen while preserving it in history.
- Perception fusion: 16/16 passed. Current-screen TTL: 2/2 passed.
- `py_compile` and scoped `git diff --check` passed.

This validates current/history separation in-process. Live scene changes and Qwen latency under load still require the profile to be running.
