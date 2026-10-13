# Selected LLM: CPU cancellation probe — 2026-10-12

## GPU1 update — 2026-10-13 (latest evidence)

Opt-in `--allow-gpu1-model`, mutually exclusive with CPU opt-in, uses exact
canonical CUDA1/layers99/context65536/threads12 and output2048. No fit fallback,
foreign process stop, model/provider/default mutation or device capture.
Requires RAM guard and physical GPU1 free VRAM≥model bytes+2GiB. Minimal child
env needs ProgramFiles for NVML; only that machine path is inherited additionally.

Reports `runtime/llm-model-cancel-gpu1-20261013{,-r2,-r3,-r4}.json` retained:
initial SKIP/NVML; r2 FAIL/tiny12-token follow-up cap; r3 PASS prefill cancellation
62.789ms to idle and same-client answers0.936/0.742s; r4 PASS strict generation
n_decoded2, cancel→idle78.267ms, startup2.899s, followups0.931/0.773s. r3/r4 observed
parent+child0, listener/Job gone. Reasoning-disabled request was made, but the
cause of r2 empty content is not proven. Increasing to canonical output budget
fixed that protocol outcome; this does not prove reasoning absent/needed.

Current GPU1 protocol requires actual generation (CPU still permits observed
prefill). No producer lease release claim for a different provider, concurrent
stream B, long-context quality, time-to-first-audible or complete voice agent.
Latest harness/test/source baseline and final regression receipt are in STATE.
The CPU evidence below remains negative and unchanged; no CPU reload was done.

## Result

**Two actual runs FAIL. Selected-model compute/slot release is NOT accepted.**
The same selected Hikari PQ2_0 GGUF was loaded by the configured prism server,
CPU-only, threads12, one slot/context4096. This is an isolated benchmark override,
not a change to the canonical GPU1/context65536 daily profile. No new downloads,
agent/task/tool execution, audio devices or active-avatar changes.

| Run / report in runtime | Protocol | Observed result |
| --- | --- | --- |
| `llm-model-cancel-cpu-20261012.json` | Wait for active slot with ≥2 generated tokens, then cancel through pinned native SDK | FAIL/observed child+parent1. Load19.416s; required generation was not observed within35s. Native SDK close completed in cleanup; owned Job/server listener gone. |
| `llm-model-cancel-cpu-20261012-r2.json` | Distinct diagnostic repeat: batch16/ubatch1; accept real prefill progress or ≥2 decoded tokens, record phase | FAIL/observed child+parent1. Load21.654s; last slot task2 active, prompt processed0/decoded0 after35s. No cancellation-to-idle measurement or follow-up acceptance obtained. |

These are telemetry observations, not proof of zero CPU work or a root-cause
diagnosis. The local C++ server exports completed prompt/gen statistics; a
long in-flight batch may not yet be reflected. CPU speed, custom quantization
backend and scheduling require separate investigation. Do not infer GPU1 speed
or generic Hikari quality from this result, or call model loading real-time.

Both runs used native OpenAICompatibleProvider, OpenAI SDK3.8.0/httpx0.28.1,
Python3.11, exact owned Win Job/listener proof before inference. Model metadata:
7,206,168,928 bytes; path in reports. No full weights hash was computed.
Server binary SHA256 `16e24d6a6254aaabb7a55be7065ccddd0f761489f7711a9e713ab9654f644e48`.
Initial free RAM~22.3GiB, minimum~15GiB, guard floor8GiB never tripped. Reported
launcher exit1 is expected owned termination during cleanup, not a pass.
Both reports/logs are retained; no third model run was started.

## Harness and next action

`scripts/run_llm_model_cancel_acceptance.py` is opt-in, RAM/deadline guarded,
credential-clean, no proxy, no foreign kill. New reports must not exist already.
It verifies the pinned snapshot and model alias/context, owns the actual server
listener, measures native task cancellation/slot idle and two same-client RU
follow-ups when computation advances. Future reports include source SHA, stage,
own credential-free command and last slot metadata. A private child route also
requires explicit model opt-in. No remote compute completion is inferred from EOF.

9 helper/CLI tests +12 subtests PASS3.14;9 unittest PASS pinned3.11. They are not
real model acceptance. The
last full application gate is still client-post779/66/16/86/6/8: all343 covered
sources remain unchanged. New345-source baseline includes these two diagnostic
files, not a newly claimed full gate. Snapshot348 unchanged.

Do not repeat CPU loads without a new testable hypothesis. Selected GPU1 release
needs sufficient free owned resources; foreign processes must not be stopped.
Meanwhile continue independent B1 ownership/early Popen→Job work, then current
voice/task continuity. No canonical model substitution or reduced daily context.
