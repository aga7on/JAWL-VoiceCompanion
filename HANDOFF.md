# Nightly Handoff — 2026-09-06 (UTC)

Project: `JAWL-VoiceCompanion` at `G:\AI\JAWL-VoiceCompanion` — goal is the first
connected daily scenario (P0-A startup/shutdown, P0-B connected loop, P0-C voice
robustness). Everything up to this moment is committed at `82c0112`; working tree
is clean; full suite green (345 pytest + 28 subtests, Node mic gate, diff check).

## Done (committed)
- Synthetic voice robustness slice (P0-C foundation):
  - `src/jawl_voicecompanion/asr.py`: `ASRNoSpeech` outcome, `no_speech` finish
    status, injectable `clock` (offline TTL/disconnect tests).
  - `src/jawl_voicecompanion/web.py`: `/api/voice/end` maps `no_speech` to a
    neutral empty transcript.
  - `scripts/make_synthetic_audio_cases.py` + `tests/test_synthetic_audio_cases.py`:
    deterministic 12-case acoustic generator with `cases.json` expectations.
  - `scripts/run_asr_profile.py --expects` (+ `tests/test_asr_profile.py`):
    fails only when required speech is missing; tolerated no-speech still counts.
  - `scripts/check_mic_gate.mjs`: browser backpressure at `MAX_PENDING_AUDIO_CHUNKS`.
  - `scripts/run_synthetic_cases_live.ps1`: TeraTTSv2 -> case matrix -> local
    Qwen3-ASR llama-server, end to end.
- Committed the whole accumulated working tree (docs, `config/jawl/`, native
  catalog/gateway/policy and target-release profiles, LAN/HTTPS docs+tests).

## Next steps (ordered)
1. **Phase 2 — real local LLM endpoint for owned JAWL.**
   - Option A (recommended, no credential): Ollama `http://127.0.0.1:11434`
     (already verified reachable without auth). Models:
     `gemma-4-12b-obliterated:latest`, `gemma-4-12b-coder-fable5-composer2.5-v1:latest`.
     Configure owned profile with `LLM_API_URL=http://127.0.0.1:11434/v1` and
     `main_model=gemma-4-12b-obliterated:latest` (no key needed for loopback),
     then `scripts/prepare_daily_profile.py` and first live user turn via
     `run_daily_profile.ps1`.
   - Option B: LM Studio `127.0.0.1:1235` — ASK THE OWNER for the API key; the
     server returns 401 without it and you must not guess or print secrets.
2. **Phase 3 — first connected live loop (P0-B):** real LLM through owned JAWL,
   one Russian question -> fact/preference to memory -> a native action ->
   restart-and-recall check.
3. **Phase 4 — live acceptance:** run `scripts/run_synthetic_cases_live.ps1`
   (local Qwen3-ASR-0.6B on CPU) to accept the synthetic matrix; measure
   cold/warm latencies; browser voice E2E via `scripts/run_browser_voice_e2e.py --live`
   once a provider is live.
4. **Phase 5 — finish P0-C exit criteria (still OPEN):** partial-ASR streaming,
   cancellable native streaming TTS, semantic barge-in, browser/device
   interruption E2E. Update `TODO.md`, `docs/STATE.md`, `CHANGELOG.md`,
   `docs/TECHNICAL_AUDIT.md` after each slice.

## Blockers / owner follow-ups
- **Remind the owner to revoke/rotate the leaked TokenRouter key (and OpenCode
  auth).** Required, do not skip.
- No `LLM_API_KEY_1` in process/user/machine env; never store credentials in the
  repo; inject through the process environment only.
- LM Studio needs the owner's key or local auth must be disabled.
- `voicemem_memoryspace/demo/` contains biometric voiceprints + vector stores —
  it is gitignored; do not add it back.
- 100 live-turns, microphone/VoiceMem, OBS/Live2D soak and supervised recovery
  require owner presence.

## Verification commands
- `python -m pytest -q`
- `node scripts/check_mic_gate.mjs`
- `git diff --check`
- `python scripts/preflight_jawl_runtime.py --allow-missing-model`
- Full gate: `scripts/run_full_gate_capture.ps1` (report lands in `runtime/`)