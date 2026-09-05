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
1. **Phase 2 — local LLM endpoint for owned JAWL: DONE at the provider level.**
   - Owner provided the LM Studio key for `http://127.0.0.1:1235/v1`; it verifies
     (`/v1/models` + minimal chat completion). Loaded model id is
     `ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d`; `config/jawl/settings.yaml`
     `main_model` now points at it; prepared profile + preflight pass.
   - Provider fix: LM Studio rejects `response_format.type=json_object` (400).
     Patch applied to the owned snapshot and recorded at
     `scripts/patches/llm-openai-compatible-response-format.patch`; run LM Studio
     sessions with `LLM_RESPONSE_FORMAT=text` in the environment. Key travels only
     via `LLM_API_KEY_1` (process env), never printed or committed.
   - REMATCH BLOCKED AT THE TURN: the Ornith model enters a ReAct tool loop and a
     single `--turns 1` run never emits a final answer (18 tool.completed; turns
     timed out at 180–420 s). Evidence: `runtime/daily-live-one-turn.json`,
     `runtime/daily-live-greeting.json`. This is the P0 "bound a single user-turn"
     contract issue and must be fixed BEFORE claiming Phase 3.
2. **Phase 3 — fix the single-turn loop, then complete the connected loop:**
   - Try in order: (a) trim/clamp the daily tool catalog so only terminal
     messaging (and maybe notes) is available; (b) tighten `max_react_steps`;
     (c) fix the launcher cwd so `sandbox/` resolves to
     `runtime/instances/daily/sandbox` (currently it resolves to the pinned-source
     sandbox and repeated `list_directory('sandbox/')` calls fail, feeding the
     loop); then re-run
     `run_native_gateway_profile.py --allow-live-turns --turns 1
     --skip-cancel --skip-reconnect --allow-missing-tool-lifecycle
     --prompt-template '<RU without braces>' --turn-timeout 360
     --report runtime/daily-live-one-turn.json`
     against a briefly started console
     (`runtime\jawl-daily-venv\Scripts\python.exe -m src.web.server
     --host 127.0.0.1 --port 8770 --keep-agent --no-browser` from the pinned
     source dir with all `JAWL_*` instance env + `LLM_API_URL`/`LLM_API_KEY_1`/
     `LLM_RESPONSE_FORMAT=text`).
   - Then the P0-B loop: fact/preference to memory -> native action -> restart
     and recall.
3. **Phase 4 — live acceptance:** `scripts/run_synthetic_cases_live.ps1` (local
   Qwen3-ASR-0.6B); cold/warm latency; `scripts/run_browser_voice_e2e.py --live`.
4. **Phase 5 — P0-C exit criteria (still OPEN):** partial-ASR streaming,
   cancellable native streaming TTS, semantic barge-in, interruption E2E. Update
   `TODO.md`, `docs/STATE.md`, `CHANGELOG.md`, `docs/TECHNICAL_AUDIT.md` after
   each slice, and apply the response-format patch again after any
   `stage_jawl_source.py` re-staging (commit the patch re-record there).

## Blockers / owner follow-ups
- **Remind the owner to revoke/rotate the leaked TokenRouter key (and OpenCode
  auth).** Required, do not skip.
- The owner's LM Studio key is used only via process env `LLM_API_KEY_1`; never
  print it, never commit it.
- Connected daily scenario is blocked on the model's ReAct tool loop (see Phase 3
  fixes above); no live user turn is accepted yet. Ollama `gemma-4-12b-obliterated`
  is the fallback endpoint if LM Studio's model keeps looping.
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