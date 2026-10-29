# Hikari context and live-turn probe — 24 Oct 2026

## Findings

The active Hikari process on port 8990 was started with `--ctx-size 8192`; the repository manifest and owned launcher default to 65,536. The previous live startup needed 11,536 prompt tokens and was rejected by that 8k server.

An isolated owned profile on port 8996 used the same Bonsai/Hikari weights, CPU-only (`--device none`, eight threads), and 16,384 context. JAWL reached `ready`; its actual `SYSTEM_CORE_START` prompt was 10,992 tokens, so 16k clears the context-size startup rejection. Owned launcher report: `runtime/context-probe-r2-20261024.json` (PASS; 84.6s startup+shutdown; brain process reaped).

The saved run log now makes the size cause explicit: JAWL logged a 13,212-character dynamic context compacted to 12,000 characters (`skills` was trimmed), followed by **10,995 input tokens** at the provider. The saved assembled prompt dump is 50,236 Unicode characters. The startup event itself is only a short trigger; almost all of the budget is the current core instruction/skill context. Therefore the live 8,192-token endpoint cannot accept this prompt even before reserving output. Blindly removing roughly 2,803 prompt tokens would mean dropping core skills or behavior, not merely shortening a greeting.

A second isolated 16k CPU profile attempted one text turn through Companion `/api/chat`. JAWL's startup ReAct remained active and deferred the incoming `HOST_TERMINAL_MESSAGE`; the request hit its 120s deadline and returned the Companion fallback “JAWL недоступен: текущий turn завершён с ошибкой.” Shutdown then cancelled the unfinished startup cycle. The API returned HTTP 200, but the turn acceptance is correctly recorded as FAIL in `runtime/context-chat-probe-20261024-chat.json`. The owned profile's general launcher report says PASS only for startup/readiness/cleanup; it does not represent a chat PASS. CPU-only 27B Hikari is too slow for this integrated turn path on the tested configuration (peak working set about 8.55 GB).

Temporary CPU model and Companion processes were reaped; only pre-existing Hikari `8990` and Omni `8995` remain. No TTS, mic, loopback capture, or GPU was used by these probes.

## Managed GPU1 16k retest — 24 Oct 2026

After explicit owner approval, the exact pre-existing 8990 listener (PID 47336,
8,192 context) was stopped and replaced by the managed launcher using an
isolated profile, CUDA1, 16,384 context, one slot, and 2,048 output tokens.
`/props` and `/slots` both reported 16,384. The full `SYSTEM_CORE_START`
completed: JAWL logged 10,998 local input tokens, provider usage reported
11,543 prompt tokens, and the empty-actions startup cycle concluded in 6.66s.
The managed Companion health endpoint reached `ready` with JAWL connected.

One ordinary Russian text request through Companion `/api/chat` returned the
expected answer `4` with HTTP 200 in 0.828s. GPU1 remained at 8,767 MiB used /
7,211 MiB free in the short-turn monitor; there were no monitor errors or
allocation failures. This comfortably clears the 1 GiB acceptance floor for
this one-slot 16k probe, but does not establish headroom at 32k/65k or during
concurrent sensors. The accepted control used Unicode escapes after an initial
PowerShell-pipeline encoding error; that malformed first request was excluded.

Three post-turn observation windows (150 seconds, fifteen samples) kept Companion
health `ready`, Hikari RSS at 8,592 MiB, and GPU1 at 8,767 MiB used / 7,211 MiB
free. This is a short stability sample, not a soak.

The bounded managed launcher then exited cleanly at 18:06:31 UTC with exit code
0 and `brain_leaked_after_run=false`; its machine report is
`runtime/hikari-gpu1-context16k-acceptance-20261024.json`. Ports 8990, 2367,
8766, and 8770 were no longer listening after cleanup. The launcher report's
`passed` status covers startup, model identity, and shutdown only; the single
chat turn is evidenced separately above and does not extend this to a soak.

This was deliberately a text-only profile with `tts=not_configured`, no
microphone, loopback, or visual capture; OmniVoice on 8995 was left untouched.
It establishes GPU1 16k startup and one short JAWL turn, not voice quality,
sensor grounding, the daily profile, or 24/7 acceptance. Machine-readable
evidence: `runtime/hikari-gpu1-context16k-live-turn-20261024.json`.

## Next required validation

The GPU1 16k startup/turn blocker is cleared for this narrow probe. Continue
with representative multi-turn latency and semantic checks, then evaluate
larger context only with current VRAM telemetry. Full daily-profile acceptance
still requires TTS and sensor integration, real A/V co-watch, 30–60-minute
continuity, and the full-stack unattended soak. Do not promote 16k or change the
65,536 manifest target from this single short turn alone.

### Readiness correction

The live probe showed that `run_local_bonsai_integrated.ps1` always passed `-AllowBusyStartup`, which let the Companion report ready while `SYSTEM_CORE_START` was still running. The ordinary local-bonsai launcher no longer passes that flag; it now waits for the existing cycle-completion marker and fails closed on timeout. The explicit recovery and acceptance flows may still opt in. `tests/test_launcher_manifest.py`: 17 passed; PowerShell parse and CodeSee feature validation passed. The launcher was later exercised by the managed GPU1 16k retest below; that validates startup and one short chat turn only, not the full daily profile.

Operational implication: keep the managed profile's larger context configuration and validate it with the existing GPU1 model; do not lower the daily prompt budget to make an 8k manually started server appear compatible. The one approved managed retest has since replaced the previous 8990 process and shut down cleanly; no Hikari endpoint is currently listening on 8990.
