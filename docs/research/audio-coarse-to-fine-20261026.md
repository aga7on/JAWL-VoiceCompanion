# Audio scene classification and coarse-to-fine follow-up — 2026-10-26

## What changed

- The EG2 audio descriptor now ranks four positive scene classes: music, speech-dominant, environmental sound, and speech with music. It does not use a single `music_absent` text prompt as the opposing class.
- Music detail is split into independent vocal, percussion, bass, and electronic-timbre candidate banks. These heads are evaluated independently of the broad scene result.
- L2 analyzes bounded overlapping windows, carries the top L1 concepts forward, adds DSP features, and records changes between windows separately from each window's characteristics. L3 aggregates candidate support over time.
- Similarity values remain uncalibrated candidates. The existing safe-claim path was not loosened. Model weights and production thresholds were not changed.
- The CLAP prompt-bank probe now uses positive scene and specialist prompts and writes a separate dated artifact.

## Evidence and limits

- Targeted synthetic tests: `tests.test_audio_coarse_to_fine` 3/3 passed; selected EG2 runtime tests 2/2 passed. `py_compile` passed for the edited Python files.
- The seven available CLAP control fixtures produced the same broad top-scene mapping as the previous prompt bank. Russian speech is still ranked as speech plus music, so this probe shows no increase in correct confirmations and retains a false overlap. Some specialist heads also produce candidates on speech/silence controls; those candidates must remain unverified.
- The current fixtures are not manually verified intervals. The repository has no human-labeled audio interval set that can establish the requested no-increase-in-false-positives criterion. P0 quality acceptance therefore remains open.
- The descriptor exposes separate embedding, L1, L2, and L3 stage timings. Window embedding time is subtracted from L2 so it is not counted twice. Capture is `null` because capture occurs upstream and the current descriptor call receives only WAV bytes.
- No live run was started for this change. The reported 503 prefetch drops and 41.8 s captured out of 60 s have not been remeasured, and stable long-run cursor behavior is not established. P2 remains open for the next controlled single-thread live run.

Probe artifact: `runtime/audio-path-replay/out/clap-prompt-bank-probe-20261026-positive.json`.
