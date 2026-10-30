# InternVL3.5-1B storyboard benchmark

Date: 2026-10-28

## Purpose

Test a new small VLM for chronological scene summarization. This is a different model from the earlier Qwen and d1 runs. The same local five-scene, 50-second video and the same 15-frame storyboard used in the Qwen3.5-2B comparison were used. The input is visual only; this does not test audio or native video decoding.

## Setup

- Model: `OpenGVLab/InternVL3_5-1B-HF`, pinned revision `9191dbccf312b537016f041b25d61c72e7c5c9f3`.
- Transformers: existing isolated test environment, PyTorch 2.14.1+cu130, BF16.
- Device: one RTX 5080 (GPU1; exposed as `cuda:0` inside the isolated process).
- Input: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-storyboard-15frames.png`; five successive 10-second sections, three frames sampled per section.
- Prompt: five lines, one per section, maximum 12 words per line, preserve chronology, omit uncertain details.
- Four deterministic runs; first run excluded as warmup for the latency summary.

## Results

- Warm request p50: **2.417 s end-to-end**, max **2.423 s**. Generation p50 **2.371 s**; image preparation p50 **46 ms**.
- Model load: 1.26 s (not included in request latency).
- Peak GPU allocation: 2.58 GB; reserved: 2.64 GB.
- All repeats produced the same five-line answer in the correct section order.
- Against the manual frame ledger: section 1 correctly mentions sky but invents/transcribes unreadable text; section 2 misses that this is anime; section 3 recognizes gameplay but names unverified objects; section 4 calls the coding assistant UI a chat; section 5 broadly matches the woman in a red dress and the man on stage.
- No reliable action progression or plot was recovered. A correct five-line structure alone does not count as a correct storyline.

## Comparison with Qwen3.5-2B

The identical storyboard and prompt on Qwen3.5-2B BF16 took **2.435 s p50** (max 2.450 s). Qwen produced more specific details, particularly for the game and coding UI, but also asserted unsupported actions and objects. InternVL is no faster in a meaningful way and gives less useful detail, with clear scene-category errors. Neither passes as a reliable storyline model.

## Decision

Do not select InternVL3.5-1B as the project’s story describer. It meets the nominal 3-second warm-latency target on this GPU but fails the factual-grounding requirement. The existing Florence-2 evaluation still shows it is too generic and inaccurate to replace the VLM describer, and the Florence-tags-to-brain test did not produce a reliable story. The larger objective remains open: no tested candidate has yet achieved both reliable, grounded scene progression and the desired live latency.

## Artifacts

- Raw measurements: `runtime/internvl35-1b-story-20261028/internvl35-1b-storyboard-results.json`
- Input storyboard: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-storyboard-15frames.png`
- Manual reference ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Official model card: https://huggingface.co/OpenGVLab/InternVL3_5-1B-HF
