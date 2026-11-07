# Candidate benchmarks: StreamVibe, Spark-X2.6, and SLEEP

Date: 2026-11-01. Research-only; no daily-profile or kernel changes.

## Scope and evidence boundaries

- **Spark-X2.6-1.7B** is a runnable text model candidate. The local run uses the [official Q4_K_M GGUF](https://huggingface.co/XHToken/Spark-X2.6-1.7B-GGUF) with the repository's existing llama.cpp build, CPU-only, and a temporary local endpoint. This tests model behavior and latency on this machine, not the vendor's RTX 4090 claims. The [official serving guide](https://github.com/XHToken/Spark-X2.6/blob/X2.6/README.md#client) says thinking is on by default and can be disabled per request.
- **StreamVibe** is a [paper/benchmark](https://arxiv.org/abs/2610.34662) and a proposed streaming proactive model, not a released local checkpoint or runnable source tree at benchmark time. Its [project page](https://stream-vibe.github.io/) says code and Hugging Face release are pending approval. The included cases are a small **StreamVibe-inspired controller probe**, not StreamVibe-Bench and not a test of StreamVibe-VL. Captions are textual inputs, so this does not test visual perception.
- **SLEEP** is a [continual-learning method](https://research.google/blog/the-sleep-framework-a-new-way-for-llms-to-retain-knowledge-in-continual-learning/) that consolidates memories into expanded model parameters during an offline training phase. There is no downloadable SLEEP checkpoint or ready-to-run repository integration in this test. The included **external-memory analogue** checks compacting, correction, uncertainty, recall, and forgetting behavior; it does not claim to reproduce SLEEP training or weight updates.

## Test suites

The versioned cases live in `benchmarks/candidate-benchmarks/`. The standard-library runner is `scripts/run_candidate_bench.py`; it speaks to an OpenAI-compatible local endpoint and records raw responses, latency, and mechanical pass criteria. Run reports go under ignored `runtime/candidate-benchmark-results/`. No product dependencies are added.

1. `spark_agent.json`: Russian response quality, arithmetic, grounded abstention, JSON adherence, tool choice, and continuation after a tool result.
2. `streamvibe_controller.json`: explicit triggers, implicit help, evolving task state, request revision, interruption, useful silence, and false-positive suppression. The score is decision accuracy plus timing/message rubric.
3. `sleep_external_memory.json`: compact durable preference, latest correction, uncertain observation, and explicit forgetting, followed by recall questions from the generated compact memory.

The first run is a screening probe. A model is a candidate for a role only after repeated runs, manual review of all outputs, and comparison against the same cases on the current JAWL path. A mechanical pass is not a full quality acceptance.

## Acceptance signals

- Spark: no malformed output in constrained JSON tasks; correct tool selection/continuation; factual answers; clear Russian; useful latency at the tested generation budget.
- Proactive controller: no alerts before a stated trigger; alerts at an actionable point; updates behavior when the request changes; low false-positive rate.
- External-memory analogue: retains stable preferences and decisions, uses the latest correction, preserves uncertainty/provenance, recalls required facts after compaction, and does not reproduce explicitly forgotten content.

## Run record: 2026-11-01

Spark-X2.6-1.7B official Q4_K_M GGUF (1,768,720,512 bytes), existing llama.cpp build b11962, local loopback endpoint, 4K context, 8 CPU threads, zero GPU layers and no op offload. Generation used temperature 0, 160-token cap (220 for compaction), and `enable_thinking=false`; the official serving instructions say thinking is enabled by default and can be disabled per request. A first probe without that switch spent the short output budget on reasoning, so it is excluded from the results below.

| Probe | Mechanical result | Request p50 / max | What failed |
|---|---:|---:|---|
| Spark agent tasks | **6/8** | **466 ms / 1,137 ms** | It answered Bishkek as “Кыргызстана — столица” without naming the city; it answered “Нет” instead of explicitly abstaining when the profile was absent. JSON, arithmetic, simple code, tool selection, ReAct continuation, and latest TTS preference passed. |
| StreamVibe-inspired controller | **5/8** | **1,027 ms / 2,131 ms** | Three false proactive interventions: before the kettle trigger, during normal install progress, and on a transient spinner despite no error. It handled explicit events, a stuck task, revised intent, and interruption. Text captions only; no video was passed to Spark. |
| SLEEP-inspired external memory | **2/4** | **2,733 ms / 3,774 ms** per compact+recall pair | It preserved the latest correction and uncertainty. It contradicted a stable TTS preference on recall and retained/revealed a value explicitly marked to forget. |

Raw request/response artifacts are in `benchmarks/results/`. Timing is warm model inference at the local endpoint; it excludes download and model startup. These are small screening suites with one measured pass each, not acceptance-quality statistical samples. StreamVibe's own code/checkpoint is still unavailable, so its model was not run. The SLEEP result is an external-memory analogue using Spark, not an experiment that updates model weights. No daily model role was changed.

## Interpretation

- Spark is **not accepted as the main brain** from this probe. Its tool-routing/continuation behavior is promising, but basic factual grounding and abstention failed. A larger follow-up should compare it against the current JAWL brain on identical multi-turn tool tasks, then repeat with the official low-thinking setting.
- The StreamVibe paper is useful as a benchmark design: score silence, intervention timing, task progress, revised intent, and trajectory consistency. The current probe is not enough to replace JAWL Attention or to claim visual understanding.
- The SLEEP paper is not a plug-in memory layer. The external compact-memory probe exposed two important failures, especially deletion. Do not route durable JAWL memory through model summarization alone; keep provenance, correction order, and forget-cascade under deterministic policy.

StreamVibe's original code/data release and a runnable SLEEP implementation remain prerequisites for full reproduction.
