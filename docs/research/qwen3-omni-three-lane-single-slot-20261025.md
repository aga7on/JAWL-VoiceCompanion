# Qwen3-Omni shared-slot three-lane probe

Date: 25 Oct 2026. Model: Qwen3-Omni-30B-A3B-Instruct Q4_K_M, the same
dual-RTX-5080 endpoint on port 8990 used by the active Qwen profile. One server
slot, 12,288 context, prompt cache disabled. Three OpenAI-compatible requests
were started together: a short text question, one still frame, and a four-second
mono 16 kHz music excerpt. The text request was deliberately short and does not
contain JAWL's full system/ReAct prompt.

## Measurements

Five rounds used the original prompts. The first round includes cold-start
effects; p50 below is across all five rounds. A sixth round used a concise
one-sentence visual prompt and a 128-token cap after the original visual
response hit its 96-token cap.

| Lane | First visible text p50 | Completion p50 | Outcome |
|---|---:|---:|---|
| Text | 81 ms | 245 ms | Five complete answers; the test question was answered correctly. |
| Still image | 985 ms | 1,527 ms | Original prompt was truncated in all five rounds. The concise sixth-round answer completed in 1,453 ms. |
| Audio | 340 ms | 559 ms | Five complete answers, consistently describing orchestral music. |

Concurrent request-group wall time was 1.45–2.03 seconds in the five rounds;
the concise sixth round completed in 1.45 seconds. The six rounds establish that
these request types can share the live endpoint, not three independent model
workers: the server exposes one inference slot and schedules the requests.

The still-image answer described a top-down biomechanical game field with
plant-like units, tanks, and a base. The music source is catalogued broadly as
Classical, but its exact instruments and mood have not been independently
verified; those details are not accepted as ground truth. The sixth-round visual
prompt change fixed truncation for this one frame, but needs varied-scene replay.
The three-lane latency also does not represent a full JAWL/ReAct brain turn or
continuous audio/video ingestion.

No media was persisted by the probe. Results:

- `runtime/qwen3-omni-direct-20261024/three-lane-results-single-slot-20261025.json`
- `runtime/qwen3-omni-direct-20261024/three-lane-results-single-slot-v2-20261025.json`

CPU and GPU placement probes are recorded in
`runtime/qwen3-omni-direct-20261024/ACCELERATION-RESEARCH-20261025.md`:
the tested dual-GPU short A/V request was fastest at 1.33 seconds; CPU 12 and
24-thread runs took 8.78 and 8.91 seconds; one GPU with CPU MoE offload took
9.51 seconds. These are short probes and do not pass 24/7 or semantic-quality
acceptance.

## Current integrated soak checkpoint

The live eight-hour Qwen profile began at 07:51:35 UTC and is still active. At
09:06:35 UTC, the bounded monitor recorded 20,251 captures, 508 deliveries, no
capture errors, stale drops, or scene-change drops; Qwen health, JAWL
connectivity, and OmniVoice health were OK. The sampled caption was 8.4 seconds
old against a 5-second TTL, so continuity has a repeatable freshness gap under
the active 5/10-second static/periodic configuration. Real brain requests were
rejected twice, at 09:04:44 and 09:14:43 UTC, each at 12,310 prompt tokens
against the 12,288-token window. `/api/doctor` still marks the companion
degraded because the legacy Vision watcher endpoint is unavailable, although
the separate Qwen visual
sensor is capturing and delivering. Keep the soak unchanged; correct context
budgeting, profile/readiness wiring and refresh cadence, then repeat a clean
acceptance after this run.

## Later live checkpoint and acceleration research

At 09:50:35 UTC (sample 238), the monitor, Qwen3-Omni server, companion and
OmniVoice processes were still live. Brain/TTS/ambient audio were healthy;
there were 30,693 captures and 770 deliveries, with zero capture errors or
stale-result drops. The current caption was stale at 9.9 seconds; available
system RAM was 28.37 GiB. Recomputed across 232 samples through 09:47:05 UTC,
only 121/232 (52.2%) were fresh, age p95 was 10.219 seconds, maximum age was
13.75 seconds, and the longest stale run remained 47 samples (about 23 min).
The single recent fresh sample is not evidence of continuity. This run uses
the old 5/10-second cadence and remains an observational baseline, not a
24/7 pass.

The live Qwen endpoint reports `/health=ok`, exposes only `local-qwen3-omni`,
and `/slots` confirms one idle slot at 12,288 context. The active instance
still has `max_dynamic_chars=12000` in its context-budget receipt, while the
corrected source profile uses 9,000. Regenerate and read back the receipt on a
clean post-soak start, then verify the complete JAWL prompt fits with output
reserve before accepting a brain turn. The running instance was left intact.

Updated acceleration research: upstream vLLM-Omni currently documents that
native Windows is unsupported. Its Qwen3-Omni streaming-video WebSocket with
optional audio and incremental prefill is a Linux/WSL migration lead, not a
drop-in speed fix. Keep llama.cpp for the current Windows baseline and after
the soak test default versus `CUDA_SCALE_LAUNCH_QUEUES=4x` as a matched
multi-GPU ablation; no benefit is assumed before measurement. Generic
speculative decoding also remains unverified for this Omni architecture.
References: [vLLM-Omni GPU install](https://docs.vllm.ai/projects/vllm-omni/en/stable/getting_started/installation/gpu/),
[Qwen3-Omni video stream API](https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/video_stream_api/),
[llama.cpp CUDA environment options](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#runtime-cuda-environmental-variables).

An isolated Qwen3-Omni Captioner Q4_K_M download was still in progress at
12:50 Moscow time: the locked GGUF grew from 2.52 GB to 3.77 GB over twenty
minutes, versus the publisher-reported 18.56 GB. It was not hash-verified or
loaded; verify the final file and projector before the post-soak audio-only
comparison.

At 09:51:35 UTC (sample 240), the monitor and Qwen/companion/OmniVoice
processes remained live. Brain/TTS/ambient audio were healthy; 30,930 captures
and 776 deliveries, zero capture errors/stale drops, but caption age was 9.2 s.
The Captioner GGUF continued growing, reaching 3,822,731,264 bytes at
12:51:52 Moscow time; it remains incomplete and locked, so no hash or inference
was attempted.

At 09:52:35 UTC (sample 242), all monitored processes and brain/TTS/ambient
audio remained healthy; captures/deliveries increased to 31,164/782 with no
capture errors. Caption age was 8.3 seconds and still stale. The source cadence
fix and corrected 9,000-character budget remain unloaded until the planned
baseline ends.

At 09:53:05 UTC (sample 243), the same listeners/processes were still alive;
31,280 captures / 785 deliveries, no capture errors/stale drops, and caption
age 7.9 seconds (stale). Recomputing the whole live series through sample 243
(244 rows including sample 0): exactly 50.0% fresh, p95 age 10.484 seconds,
max 13.75 seconds and the same 47-sample/~23-minute stale streak. Available
RAM stayed within the observed 27.96–31.65 GiB range; brain RSS within
24,335–26,974 MiB. This reinforces that a recent fresh point cannot substitute
for continuous freshness.

The live companion process arguments were read with only the Qwen cadence
flags extracted (no full command line or credentials recorded): active
interval 1 s, static interval 5 s, periodic interval 10 s, max age 6 s. The
current launcher/parser defaults are 1/4/4/6 s. This confirms the running
5/10 s settings are an old explicit launch configuration, and the clean
restart must pass/verify 4/4 s rather than merely relying on today's defaults.

At 09:55:05 UTC (sample 247), all monitored processes remained live; 31,747
captures / 797 deliveries, no capture errors/stale drops, and current caption
age 6.6 seconds. Across 248 samples, 122 (49.2%) were fresh, p95 age was
10.484 seconds, max 13.75 seconds, longest stale streak 47 samples, and
available RAM never fell below 27.96 GiB. The monitor records only
`ambient_audio_running`, not Qwen audio-description count/latency/quality, so
this soak can assess loopback service availability but is not an audio-content
acceptance. Add audio-lane counters and labeled loopback cases to the later
30–60-minute integrated acceptance.

At 09:55:35 UTC (sample 248), the same processes remained alive; 31,867
captures / 800 deliveries, no capture errors/stale drops, caption still stale
at 6.6 seconds, and minimum available RAM remained 27.96 GiB. Across 249
samples (n=0–248), freshness was 49.0%, p95 age 10.484 seconds, max 13.75
seconds, with the longest stale run still 47 samples.

At 09:57:35 UTC (sample 252), 253 samples (n=0–252) had accumulated:
122/253 (48.2%) captions were fresh, age p95 was 10.391 seconds, maximum
13.750 seconds, and the longest stale streak remained 47 samples. The latest
caption was stale at 5.594 seconds. The 8h run began at 07:51:35 UTC, so this
was only 2h06m of observation; leave it undisturbed through its planned end.

At 09:57:05 UTC (sample 251), the Qwen server, soak monitor, Companion and
OmniVoice processes were still alive. Brain/TTS/ambient-audio availability
remained true; Qwen visual telemetry reached 32,224 captures and 809
deliveries, with zero capture errors, stale-result drops or scene-change
drops. The latest caption was stale at 5.937 seconds; available RAM was
28.28 GiB and GPU free memory was 1,233 / 3,223 MiB. This still-loaded
process uses the old 5s static / 10s periodic cadence. The JSONL records only
`ambient_audio_running`, so no audio-description success, latency or semantic
quality can be inferred from this soak. The post-soak visual continuity and
audio ground-truth gates are now written into `docs/DAILY_ACCEPTANCE.md`.

At 09:59:05 UTC (sample 255), all four monitored services/processes were
still present. Across 256 samples (n=0–255), 124 captions (48.4%) were fresh;
age p95 was 10.391 seconds, maximum 13.750 seconds, and the longest stale
streak remained 47 samples. The latest point happened to be fresh at 4.375
seconds, but does not alter the full-series failure. Totals: 32,695 captures,
821 deliveries, zero capture errors or stale/scene drops; available RAM was
28.15 GiB. The monitor's audio field remains service availability only.

At 10:00:35 UTC (sample 258), the soak had 259 rows: 127 (49.0%) fresh,
age p95 10.391 seconds, max 13.750 seconds, longest stale streak 47 samples.
The latest caption was fresh at 3.313 seconds; captures/deliveries were
33,044/830, with zero capture errors or drops, and 28.49 GiB RAM available.
The Captioner GGUF download is still growing, at 4,383,408,128 bytes, so it
remains incomplete and must not be inspected or loaded yet.

## New GPU runtime candidate: TensorRT Edge-LLM

The current NVIDIA TensorRT Edge-LLM docs provide a Qwen3-Omni path: quantize
the Thinker/Talker backbone to NVFP4 or INT4 AWQ, export separate text/audio/
vision engines, and run multimodal inputs through the C++ runtime. Its official
support matrix lists x86-64 Linux development and a published-wheel row for
Ubuntu 24.04 + CUDA 13 + SM120, matching RTX 5080's compute capability; it does
not list native Windows. This is a credible post-soak GPU-runtime experiment,
not a proven speedup. The recipe asks for 20–50 GB disk for ONNX/engines in
addition to source checkpoints and quantization artifacts. This host currently
has only the `docker-desktop` WSL distro (no Ubuntu distro), 116.4 GB free on
G:, and two RTX 5080s with 16 GB each. Do not start installation/export during
the live soak. Afterward, first confirm an isolated Ubuntu/WSL environment has
adequate scratch space and an exact TensorRT/CUDA/SM120 wheel or source-build
path; then run the same bounded A/V and audio-only cases against the current
llama.cpp baseline, measuring useful-response latency, quality, peak VRAM/RSS,
and actual full-prompt fit. Model weights must come from the HF safetensors
checkpoint; the current GGUF cannot be used by this export recipe.

References: [TensorRT Edge-LLM Qwen3-Omni recipe](https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/examples/omni.html),
[installation requirements](https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/getting_started/installation.html),
and [official support matrix](https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/getting_started/support-matrix.html).

Important compatibility limit: Edge-LLM's multi-device page currently
documents TP=2 hardware as a pair of DGX Spark systems and its explicit TP
model list does not include Qwen3-Omni. Although the runtime describes a local
two-GPU launch mode, that is not evidence that two consumer RTX 5080s with this
Omni model are qualified. Keep the candidate behind a low-cost feasibility
check: verify exact release/model support and whether a single 5080 has enough
memory for the quantized Thinker plus multimodal encoders/KV before allocating
the substantial download/build space. Source: [multi-device support](https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/features/multi-device.html).

At 10:02:05 UTC (sample 261), all soak processes remained alive. Across 262
samples, 130 (49.6%) were fresh; age p95 was 10.297 seconds, maximum 13.750
seconds, and longest stale streak remained 47 samples. Latest caption was
fresh at 2.500 seconds. Captures/deliveries were 33,392/839 with zero capture
errors or drops; available RAM was 28.55 GiB. The Captioner GGUF continued
growing to 4,471,324,672 bytes, still far short of its expected 18,557,053,312
bytes; do not hash or load it until the download is complete.

At 10:04:05 UTC (sample 265), 266 rows had accumulated: 134 (50.4%) fresh,
age p95 10.297 seconds, maximum 13.750 seconds, with the same 47-sample
longest stale run. The latest caption was fresh at 1.328 seconds. Totals were
33,740 captures and 848 deliveries, with zero capture errors or stale/scene
drops and 28.52 GiB available RAM. This still fails the proposed continuity
gate despite the good latest sample.

At 10:05:05 UTC (sample 267), the four soak processes remained alive. The
latest caption was stale at 10.453 seconds. Across 268 rows, freshness was
exactly 50.0%, age p95 10.453 seconds, maximum 13.750 seconds, and the longest
stale run remained 47 samples. Captures/deliveries reached 34,096/856, with
zero capture errors or stale drops; 28.60 GiB RAM remained available. This
confirms the stale interval recurs even after isolated fresh samples.

At 10:06:05 UTC (sample 269), the monitor advanced after a one-poll delay; all
processes remained alive. Across 270 rows, freshness was 49.6%, age p95
10.453 seconds, maximum 13.750 seconds, and the longest stale run remained 47
samples. The latest caption was stale at 10.343 seconds; captures/deliveries
were 34,336/862. Brain, TTS and ambient-audio service were available; no
capture errors or stale-result drops were recorded.

At 10:06:35 UTC (sample 270), Qwen `/health` returned `ok`; the model process
still exposes one idle slot with `n_ctx=12288`. Across 271 rows, freshness
was 49.4%, age p95 10.453 seconds, max 13.750 seconds, and longest stale run
47 samples. Latest caption age was 10.312 seconds; captures/deliveries were
34,456/865, with zero capture errors or result drops. Companion remained
`degraded`, despite the separate Qwen endpoint and visual worker being live.
Read-only `/api/doctor` confirms the sole warning is Vision (`configured`,
“live capture/model not verified”) and recommends validating the selected
profile; JAWL, VoiceMem, GigaAM, TTS, loopback, resources, and HostOS report
ready/running states. This is the old loaded doctor implementation, not
evidence of a capture failure; verify the corrected doctor after restart.

At 10:07:05 UTC (sample 271), 272 rows had accumulated: 134 (49.3%) fresh,
age p95 10.453 seconds, max 13.750 seconds, and longest stale run 47 samples.
Latest caption age was 9.953 seconds. Captures/deliveries were 34,572/868;
capture errors and result drops remained zero.

At 10:18:35 UTC (sample 294), the same Qwen, Companion, OmniVoice, desktop,
and monitor processes were still running. The latest caption was fresh at
1.062 s, with 37,270 captures / 938 submits / 937 deliveries, zero capture
errors, zero stale drops, and one scene-change drop. Across 294 samples,
freshness was only 48.8%; caption-age p95 remained 10.453 s, max 13.750 s,
and the longest stale stretch 47 samples. Brain, TTS, ambient capture and
JAWL connectivity remained available. Re-reading the active profile receipt
confirms `max_dynamic_chars=12000` despite source budgeting of 9,000 for a
12,288-token window; the current live profile has not loaded the updated
same-scene confirmation or budget. Offline sensor/fusion/context-budget
regressions now pass 43 tests plus 5 subtests. These source tests do not close
the live freshness or full-prompt-fit failures.
