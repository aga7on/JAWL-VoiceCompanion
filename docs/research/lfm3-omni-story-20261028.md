# LFM3-Omni-2B: real-clip storyline and A/V grounding probe

Date: 2026-10-28. This test evaluates whether LFM3-Omni-2B can produce useful, grounded short descriptions and a chronological account of the same 50-second montage used by the sensory-model benchmarks.

## Setup

- Pinned local checkpoint: `ce2458cbce4ad970f92032ed94e3d18d30b04f9c`; SHA-256 verified against Hugging Face API.
- Runtime: Transformers 5.20.2, PyTorch 2.8.0+cu128, BF16 on GPU1 (RTX 5080), isolated virtual environment. No companion profile or TTS service was changed.
- Input: `runtime/multimodal-realclips-20261024/real_sensory_5x10s.mp4`: Russian live-action trailer, anime, RTS gameplay, coding UI, and Aqua music video, each 10 seconds.
- Visual reference: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`, a manually annotated visual ledger. Audio annotations are explicitly provisional and were not human-listened/verified; exact lyrics and fine-grained audio claims are not scored as ground truth.
- Native video/audio file decoding failed on this Windows environment because TorchCodec's DLL was unavailable. The harness instead extracts frames and mono 16 kHz PCM with FFmpeg, then passes timestamped video frames and audio through the model processor with audio/video interleaving enabled. Segments use 2 fps, 192 max video tokens/frame budget, three identical repetitions. Full montage uses 1 fps and a 96-token video cap.
- Generation settings compared: 128-token detailed output, 96-token compact output, and 64-token coarse output. The 64-token outputs were generated from the same 10-second A/V segments; the full-story task requests five chronological bullets.
- The model used the PyTorch fallback for `causal_conv1d`; optimized kernel was not installed. This affects speed, not input correctness.

## Results

| Task | Coarse 64-token p50 / max | Output quality |
|---|---:|---|
| Five separate 10-second A/V chunks | 0.74–1.64 s / 0.75–1.65 s | Broad scene type usually recognized, but specific actions and sound claims were not dependable. The RTS was described as tanks attacking plants; the coding capture was assigned an unsupported game sound. The first chunk asserted a specific sound and legible trailer copy that the visual ledger does not establish. |
| Full 50-second A/V sequence, five chronological bullets requested | 1.87 / 1.91 s | **Failed storyline test:** response used its 64-token budget after only the opening scene and start of the next item. It did not summarize all five scenes. |
| Song audio only | 2.42 / 2.43 s | Described broad pop-rock/vocal qualities, but generated a lyric-like transcript that is not verified. Treat style and words as unscored hypotheses. |
| Unrelated trailer video + Aqua soundtrack negative control | 1.79 / 1.80 s | **Failed A/V grounding:** all three repeats claimed the unrelated soundtrack matched the trailer and invented a romantic/audio connection. |

The five chunk outputs were deterministic across repeats. That repeat stability did not prevent false claims. Peak allocated/reserved GPU1 memory was about 6.32/6.94 GB. GPU1 returned to its 467 MiB baseline when inference ended.

## Token-budget comparison

- At 128 generated tokens, segment p50 was approximately 2.87–2.90 s, but answers repeatedly ended mid-sentence at the token limit. The 50-second storyline took about 4.97 s, exceeding the 3-second target.
- At 96 tokens, chunk answers were shorter (about 2.25–2.27 s p50) but still truncated; the full-story answer was about 2.51 s and did not cover all five scenes.
- At 64 tokens, all five chunks and the full-story request fit below 3 seconds, but the long summary became incomplete and the independent A/V negative control remained wrong.

Raw attempts and timings: `runtime/lfm3-omni-test-20261028/story-bench/results-lfm3-story.json`, `results-lfm3-story-compact.json`, and `results-lfm3-story-coarse.json`. Reproduction harness: `runtime/lfm3-omni-test-20261028/run_story_bench.py`.

## Decision

LFM3-Omni-2B does **not** meet the target of a correct, detailed storyline response within 3 seconds. Short chunk descriptions are fast enough on this GPU, but their detail is unreliable; whole-sequence output under the latency limit is incomplete; and the audio/video negative control shows severe cross-modal hallucination. It is not a candidate for the always-on narrative layer based on this test. It may remain a research candidate for separately gated modality summaries, provided the downstream system treats its audio/video links and lyric claims as untrusted.

This does not establish CPU performance or real-time stream throughput. It tests prepared clips on one RTX 5080, not a live capture loop.
