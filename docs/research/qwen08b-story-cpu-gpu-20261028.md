# Qwen3.5-0.8B: short visual timeline trial

Date: 2026-10-28. This follow-up compares direct visual timeline generation against the earlier Florence-tag-to-brain experiments. It does not modify the daily profile.

## Setup

- Model: `unsloth/Qwen3.5-0.8B-GGUF` Q4_K_M (532,517,120 bytes) with F16 projector (204,987,232 bytes), about 0.74 GB total on disk.
- Runtime: local llama.cpp 0.8.0-dev build 290; `llama-server`; CUDA1 = RTX 5080 for GPU tests; CPU test used `-ngl 0`; 8 CPU threads; prompt and RAM caches disabled; temperature 0; one request slot.
- Source: the same local 50-second, five-clip montage used by the manual visual ledger. Images were visual only; audio was not supplied.
- Each prompt carried timestamps and ordered frames, but no scene names or labels. Each case ran three times; all repeats within a case returned the same text.

## Results

| Case | Input and output budget | Warm p50 / max | Completion | Observation |
|---|---|---:|---|---|
| One coherent trailer excerpt | 5 frames at t=0,2,4,6,8; 128 tokens | **366 / 528 ms** | 3/3 stopped normally | Ordered notes: sky; two people in close contact outdoors; similar angle; a woman's dark profile; a man's close-up. It adds “smoking” at t=8, which the manual ledger leaves uncertain from that single frame. |
| Five different clip types | 5 frames at t=8,18,28,38,49; 192 tokens | **665 / 892 ms** | 3/3 stopped normally | Identified woman, anime, RTS, and software UI broadly. At t=49 it reduced the visible performer to an indistinct person and missed the microphone. |
| Full montage sequence | 8 frames at t=8,12,18,22,28,32,38,42; 256 tokens | **985 / 1,216 ms** | 3/3 stopped normally | Produced all eight timestamped observations. It hallucinated a ship deck around the anime cross, described the t=18 lift/hold pose as fighting, called a model-picker UI a chat, and described the keyboard as a generic yellow object. It did correctly identify the RTS battle and the coding warning text. |
| Same eight frames on CPU | 160-token cap | **14,399 / 14,694 ms** | 3/3 hit output cap | Output stopped after t=22 and never reached later frames. Fails the 3-second CPU target. |

## Can the brain turn these observations into a storyline?

Hikari received only the eight Qwen-generated captions, with no images or audio. It returned one complete Russian sentence in **0.70 s p50** with a scene-level prompt, or **0.80 s p50** with a compact summary prompt. The outputs stayed close to the caption list and inherited its unsupported “ship deck” claim; the scene-level version did not identify the anime, game, or software categories explicitly. The summed warm p50 for sequential Qwen vision plus Hikari summary is **about 1.69 s**, but this is a sum of separate runs, not a concurrent end-to-end soak, and its content is not accurate enough to count as a passing story result.

This comparison agrees with the earlier 50-caption Florence test: a brain can compress noisy tags quickly, but it does not reliably reject a bad visual observation. Florence's full-stream failures and Hikari results are documented in [the Florence-to-brain report](florence-tags-to-brain-20261028.md).

## Decision

- **Best small visual candidate so far: Qwen3.5-0.8B Q4 on GPU1.** It is fast and gives substantially more event detail than Florence. On five samples from one trailer, it produced a repeat-stable, chronological visual ledger in under 0.4 seconds warm.
- It is not a CPU real-time candidate on this host: the same eight-image task took about 14.4 seconds and truncated.
- It is not yet a dependable plot narrator: the mixed-clip sequence contains several false interpretations and a microphone miss. Hikari can make its tags concise under the 3-second combined budget, but does not repair those errors.
- Florence-2 remains a possible inexpensive coarse tagger, not a replacement for a grounded describer. Neither Florence→Hikari nor Qwen→Hikari currently meets the full accuracy/story requirement. No single winner is established yet, especially for synchronized audio/video.

## Reproduction artifacts

- Direct Qwen tests and raw outputs: `runtime/d1-omni-test-20261028/realclip-reasoning-bench/results-qwen-timeline-*.json`.
- Reproduction script: `runtime/d1-omni-test-20261028/realclip-reasoning-bench/run_qwen_timeline.py`.
- Qwen→Hikari summary runs: `runtime/d1-omni-test-20261028/realclip-reasoning-bench/results-qwen-hikari-*.json` and `run_qwen_brain_summary.py`.
- The local visual ledger records only directly visible sampled pixels and marks the t=8 bright point as uncertain: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`.

Temporary model servers were stopped. Ports 8997/8998 were free afterward and GPU1 returned to its 467 MiB baseline. No app profile, TTS, or project dependencies changed.
