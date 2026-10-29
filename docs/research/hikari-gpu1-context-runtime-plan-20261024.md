# Hikari GPU1 context/runtime audit — 24 Oct 2026

## Current-state evidence (read-only)

- PID 47336 is `G:\AI\llamacpp-prism\build\bin\llama-server.exe`; its exact command is Hikari PQ2_0, alias `local-bonsai2`, port 8990, `--threads 12 --ctx-size 8192 --parallel 1 --gpu-layers 99 --device CUDA1 --reasoning off --no-webui`.
- `/health` is OK; `/props` reports the Hikari alias and 8,192 context; `/slots` showed one idle slot (not processing, zero decoded tokens). No active generation was interrupted by this audit.
- `config/runtime.manifest.json` and `scripts/hold_supervised_brain.py` default to 65,536 context, 2,048 max output, 12 threads, 99 GPU layers, CUDA1. `run_local_bonsai_integrated.ps1` passes these values through the owned holder. The running PID is therefore an externally launched 8k override, not the current manifest profile.
- Measured JAWL `SYSTEM_CORE_START` prompt has varied from 10,992 to 11,536 tokens. The current 8k server cannot accept that startup envelope. A same-model CPU-only 16,384-context startup reached `ready` with 10,992 prompt tokens, but a real `/api/chat` turn then timed out after 120s because startup ReAct was still active. This is a CPU latency failure, not evidence that a GPU 16k turn fails.
- Current read-only `nvidia-smi`: GPU1 is an RTX 5080 16GB, 8,246 MiB used and 7,732 MiB free; utilization 28%. GPU0 has 5,741 MiB free and is not the configured brain device. The existing Hikari weights are ~7.21 GB on disk; file size is not a KV/cache allocation measurement.
- The model family is documented as Qwen3.6-27B hybrid Gated DeltaNet. Do not estimate 64k KV from a conventional full-attention model: actual KV/cache reservation depends on this GGUF and Prism build, and must be read from the server load log and GPU telemetry.

## Decision

Keep the manifest's 65,536 as the intended daily target, but do not blindly restart into 64k with only 7.7 GiB presently free. The first owner-approved GPU1 experiment should use a disposable owned profile/port if the GPU has enough headroom; otherwise the existing 8990 must be deliberately released/restarted by its owner before testing. Start with 16,384 to clear the measured startup prompt, measure actual KV allocation and the first full JAWL turn, then step to 32,768 and 65,536 only if each passes the same gates and retains at least 2 GiB GPU1 free after model+context allocation. Never use `--fit`/auto-shrink as silent acceptance: record the requested and effective context and fail if they differ. Keep `--parallel 1`; more slots multiply cache reservation and are not needed for this single-conversation profile.

The most likely useful interim point is 32k if it fits: 16k leaves at most ~4.5k tokens after a 11.5k startup envelope and 2k response reserve, before conversation growth. It is a diagnostic/interim profile only; it does not replace proving the configured 64k daily target or an explicit product decision to reduce it.

## Safe read-only preflight

These commands do not stop or launch services, send inference, or mutate app state:

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=47336" |
  Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine
Invoke-RestMethod http://127.0.0.1:8990/health
Invoke-RestMethod http://127.0.0.1:8990/props
Invoke-RestMethod http://127.0.0.1:8990/slots | ConvertTo-Json -Depth 8
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
Get-NetTCPConnection -State Listen -LocalPort 8990 -ErrorAction SilentlyContinue
```

Before any later owned restart, repeat those checks immediately before action, verify the listener PID still exactly matches the expected owner/process, record current GPU1 memory and relevant companion/Omni services, and make a separate restart plan. Do not kill by port alone or touch other GPU processes. The present audit did not launch a model, issue an inference request, or alter runtime processes.

## Acceptance measurements for GPU1 context ramp

For each context 16k → 32k → 64k (single slot, same model/quant/server build, `CUDA1`, `-ngl 99`, 12 threads, no mmproj unless the profile requires it):

1. Capture server startup log: effective `n_ctx`, per-slot context, model offload layers, KV-cache type/bytes, flash-attention/backend selection, load time and any fit/overflow warnings.
2. Capture GPU1 memory at idle after load, during prefill/decode, and after stop; record peak and minimum free MiB. Require ≥2 GiB free at steady peak and no allocation retries/OOM/device fallback. Confirm GPU0 did not gain Hikari allocations.
3. Run actual managed JAWL startup and wait for the `SYSTEM_CORE_START` completion marker before readiness. Record prompt token count; readiness during active startup is FAIL.
4. Run 3 representative RU turns (simple chat, grounded current-screen/audio question, one tool/action envelope) after startup. Record TTFT, completion latency, finish reason, slot idle, valid tool JSON/action execution, and whether history remains in budget. Require the first ordinary turn within the configured 120s ceiling; set a materially lower target from observed user experience before calling it 24/7-ready.
5. Repeat the same turn after a follow-up and after a controlled interruption; ensure no stale answer, queue starvation, malformed action, or context overflow. Test sustained 30–60 min alongside selected sensory workers and a longer soak only after the interactive gate passes.

Reject on early readiness, HTTP 200 containing fallback text, timeout, context truncation, forced context reduction, OOM, or GPU device mismatch. Current CPU 16k chat already demonstrates why health + `ready` alone is insufficient.

## Is a conversation possible on the existing 8k server?

The direct server endpoint can in principle serve a **stateless short prompt** whose fully rendered prompt and output fit in 8,192 tokens; this audit did not send one. `/v1/chat/completions` is not a durable conversation store, so a caller must resend history each turn. It cannot start the measured full JAWL profile because its startup prompt alone exceeds 8k. A reduced/compacted startup would be a product/runtime change requiring explicit compatibility and memory/behavior tests, not a safe transparent bypass. Since the app is currently stopped and the server slot was idle, no live JAWL conversation or server KV state needed preserving during this read-only audit. Keep requests off 8990 until the owner deliberately chooses either a bounded direct diagnostic or the managed GPU1 retest.

## Evidence references

- `docs/research/hikari-context-startup-probe-20261024.md`
- `runtime/context-probe-r2-20261024.json`
- `runtime/context-chat-probe-20261024-chat.json`
- `config/runtime.manifest.json`
- `scripts/hold_supervised_brain.py`
- `scripts/run_local_bonsai_integrated.ps1`

## Fresh read-only preflight (2026-10-24 continuation)

A second current-state check confirms that Hikari PID 47336 still occupies 8990, `/health` is healthy, `/props` and the idle slot both report 8192 context, and the slot is not processing. No other daily companion ports (2367, 8766, 8770, 8994, 9890, 9891) are listening; Qwen Omni remains on 8995. GPU1 currently has 7,732 MiB free; GPU0 has 5,729 MiB free. These are snapshots, not proof that the 16K profile fits under peak load.

The runtime mismatch includes the executable: the live process uses `G:\\AI\\llamacpp-prism\\build\\bin\\llama-server.exe`; the daily manifest resolves `G:\\AI\\llamacpp-prism\\build-fa\\bin\\llama-server.exe`. Both binaries exist and have different SHA-256 hashes (`2A51F8C6…` and `16E24D6A…`, respectively), so record the actual binary/build as part of acceptance. The live process's former parent PID is absent; ownership/manager cannot currently be established from the process tree. No evidence currently shows a kernel/driver fault.

**Go/no-go:** no-go for launch or replacement while the current PID owns 8990 and the maintenance/restart request is unanswered. Do not force-close it or launch a second Hikari server as a substitute. After explicit approval and owner-path resolution, use the managed wrapper with `-BrainContextSize 16384 -NoLocalAudio -NoBrowser`, bounded duration and unique report/log paths. Require the SYSTEM_CORE_START completion marker, effective context 16384 in `/props` and `/slots`, completed chat within 120 seconds, no fallback/truncation/OOM, and at least 1 GiB GPU1 free at peak. This remains a context probe; daily acceptance still requires concurrent sensors, 30–60 minutes live co-watch, and the full unattended soak.

## Executable parity check (read-only)

Follow-up inspection of both executables found that `build\bin\llama-server.exe` and the manifest-selected `build-fa\bin\llama-server.exe` report llama-server `0.2.0-dev`, commit `1a07bfa`; the relevant `--help` flags match, and `--list-devices` exposes `CUDA0`/`CUDA1` in both. Their hashes still differ, so these checks do not establish runtime parity. Acceptance using the managed launcher/build remains open and must record the actual loaded binary, its hash, effective context, and runtime behavior.

Do not treat free-memory figures from llama-server `--list-devices` as GPU headroom evidence. Use a fresh `nvidia-smi` sample; the current GPU1 snapshot is 7,732 MiB free, which is only a preflight snapshot and does not prove 16K peak fit.

## Approved 16k runtime retest (supersedes the pending-restart go/no-go above)

The owner approved one managed restart of 8990. The exact prior PID 47336 was
stopped, then the manifest-selected `build-fa` server was launched by the
managed wrapper in isolated profile `hikari-gpu1-context16k-20261024` at
16,384 context, CUDA1, one slot, and 2,048 output tokens. Effective context
matched in `/props` and `/slots`. JAWL startup completed at 11,543 provider
prompt tokens in 6.66s; one ordinary `/api/chat` turn returned expected `4`
in 0.828s. GPU1 reported 8,767 MiB used and 7,211 MiB free, including two
samples during the short turn; this is ample for the tested context but does
not measure a long sustained peak. The test profile runs bounded for 900s and
has no TTS, microphone, system loopback, or visual capture. Qwen2.5-Omni PID
38564 on 8995 was not touched. Detailed evidence:
`runtime/hikari-gpu1-context16k-live-turn-20261024.json`.

The bounded managed launcher completed at 18:06:31 UTC with exit code 0 and
`brain_leaked_after_run=false`; 8990 and the profile ports 2367/8766/8770 were
closed after cleanup. Machine-readable lifecycle evidence:
`runtime/hikari-gpu1-context16k-acceptance-20261024.json`.

This resolves the 8k startup rejection for the managed 16k probe. It does not
promote the canonical 65,536 context setting and does not pass multi-turn
quality, sensor integration, daily-profile acceptance, or unattended 24/7
operation. The ordinary acceptance next needs representative turns, then a
separate context ramp only if current GPU headroom supports it.
