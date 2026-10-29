# Marlin-2B temporal video caption probe — 2026-10-28

## Question

Can a small model built for dense temporal captioning turn the project's real 50-second montage into a grounded, ordered storyline quickly enough for a live visual lane?

## Setup

- Checkpoint: `prasannaJagadesh/marlin-2B-GPTQ-4BITS`, revision `40eb7e8e1e8d345ed4faefbeeec2c3d446b82335`.
- Model file SHA-256: `3593bc7d6eee8d30cefade8ba50a2c2ba5f606ec9ad68d0bcabc70bff34ebbbe`.
- Runtime: isolated Python 3.11.15 environment, Transformers 5.20.2, PyTorch 2.14.1+cu130, GPTQModel 7.1.0; RTX 5080 GPU1.
- Input: `runtime/multimodal-realclips-20261024/real_sensory_5x10s.mp4`, sampled at 2 fps (20 frames for 10 s, 100 for 50 s). The montage contains a Russian trailer, anime, RTS gameplay, coding UI, and Aqua music video, in that order.
- Prompt requests a spatial description and timestamped events. Warm-up used a separate 2-second excerpt and was excluded.
- Outputs and raw timing: `runtime/marlin-2b-test-20261028/results/marlin-gptq-results.json`.

## Results

| Probe | Input frames / prompt tokens | Latency | Output | Outcome |
|---|---:|---:|---:|---|
| 10-second opening trailer, 3 repeats | 20 / 8,928 | p50 7.57 s | 128/128 tokens each run | Repeats are identical, but answer is cut off. It invents a piggyback action and smoking, and describes two characters not in the reference ledger. |
| Full 50-second montage, 2 repeats | 100 / 11,488 | p50 11.13 s (max 11.20 s) | 192/192 tokens each run | Repeats are identical, but answer cuts off at its second event. It recognizes anime, gameplay, coding, and a performance/music-video segment at coarse level, but inserts scenes from the opening trailer into later material and invents actions. It does not provide a useful complete timeline. |

Peak GPU1 allocation was 4.27 GiB (4.53 GiB reserved). Model load took 6.1 s. The tested runtime did not use Triton: Windows lacked it, so GPTQModel's Torch backend was patched in the isolated harness to use eager dequantization. The Transformers video processor also warned that it did not apply the reference per-frame pixel cap. This is a compatibility-path timing result, not an optimized-kernel ceiling.

## Decision

**Do not use Marlin-2B as the live describer on this setup.** It misses a 3-second target by a wide margin for both tested clips, and its full-montage response is incomplete and poorly grounded despite the model's temporal-captioning focus. Its broad recognition of the different montage sections is insufficient to support reliable event memory or storyline discussion.

The model is video-only; it cannot replace the audio description lane. The full clip is 50 seconds, but its answer does not preserve the five-section order accurately enough for an audio/video fusion experiment.

## Reproduction

The isolated harness is `runtime/marlin-2b-test-20261028/run_marlin_bench.py`. It changes no project profile or dependency. It forces GPTQModel's portable Torch backend and bypasses `torch.compile` in the quantized linear helper because the latter attempted to invoke unavailable Triton on Windows.
