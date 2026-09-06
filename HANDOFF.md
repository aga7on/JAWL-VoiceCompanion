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
1. **Phase 2 complete — first live user turn is ACCEPTED.**
   - Root blocker was NOT the model looping: LM Studio's loaded model was capped at
     `n_ctx 15872`, and JAWL requests inflate to 16–35k tokens → HTTP 400
     `exceed_context_size_error` (then empty answers). Fixed by reloading the
     model with a big context: `lms load ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d
     --context-length 65536 --yes` (CLI at `C:\Users\ARTEM\.lmstudio\bin\lms.exe`).
     After reload the API identifier became `ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d:2`;
     `config/jawl/settings.yaml` now targets the `:2` id. Re-run the same load
     command after any LM Studio restart/reload (and keep `LLM_API_KEY_1` in env).
   - Companion hardening to stop tool-driven stalls: adaptive context budget
     (`system.context_depth.budget: enabled, skill_policy: adaptive`), `max_react_steps`
     lowered to 8, `goal_mode` off, owned directive `config/jawl/prompts/custom/
     RESPOND_DIRECTLY.md` (seeded by `prepare_daily_profile.py`), and a snapshot
     patch `scripts/patches/jawl-context-budget-companion.patch` (no omitted
     namespace index; `SkillCatalog` removed from adaptive base prefixes — a
     companion profile must not self-discover host/coding tools for social turns).
   - Acceptance evidence: `runtime/daily-live-64k.json` — `pass:true`,
     `completed_turns:1`, `assistant.final:1`, full turn in ~48 s, agent made a
     terminal answer, saved a `SQLNotes.update_note`, then requested early cycle
     termination. Tool-loop/400 evidence in `daily-live-one-turn.json`,
     `daily-live-greeting.json`, `daily-live-bounded.json`, `runtime/daily-live-budget*.json`.
2. **Phase 3 — first connected live loop (P0-B):** fact/preference to memory → a
   native action → restart-and-recall. The `SQLNotes.update_note` already fired
   during the accepted turn; use it to seed a real memory fact, then ask the same
   question via gateway after a console restart.
3. **Phase 4 — live acceptance:** run `scripts/run_synthetic_cases_live.ps1`
   (local Qwen3-ASR-0.6B on CPU) to accept the synthetic matrix; measure
   cold/warm latencies; browser voice E2E via `scripts/run_browser_voice_e2e.py --live`
   once the provider is live (it is now).
4. **Phase 5 — finish P0-C exit criteria (still OPEN):** partial-ASR streaming,
   cancellable native streaming TTS, semantic barge-in, browser/device
   interruption E2E. Update `TODO.md`, `docs/STATE.md`, `CHANGELOG.md`,
   `docs/TECHNICAL_AUDIT.md` after each slice. Re-apply both snapshot patches
   (`scripts/patches/`) after any `stage_jawl_source.py` re-staging.

## Blockers / owner follow-ups
- **Remind the owner to revoke/rotate the leaked TokenRouter key (and OpenCode
  auth).** Required, do not skip.
- The owner's LM Studio key is used only via process env `LLM_API_KEY_1`; never
  print it, never commit it.
- LM Studio served context is set by the model load command (`--context-length
  65536`); a plain reload in LM Studio reverts to ~16k and re-introduces the
  400 `exceed_context_size_error`. `scripts/prepare_daily_profile.py` and the
  launcher do not touch LM Studio — re-run the `lms load ... --context-length
  65536` command on any reload. Model is CPU 9B (qwen35) at ~10.45 GB; ~1.5 s
  per LLM round trip after the load (much faster than the pre-fix behaviour).
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