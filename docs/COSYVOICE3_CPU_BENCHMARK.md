# CosyVoice 3 CPU benchmark — 2026-09-08

## Result

CosyVoice 3 loads and synthesizes Russian on CPU after the official `Matcha-TTS`
path is added and its LLM is converted from `bfloat16` to `float32`.

| Test | Result |
|---|---:|
| Model | `Fun-CosyVoice3-0.5B` |
| Device | CPU, CUDA disabled for the process |
| Text | Russian, ~130 characters |
| Audio | 36.2 s |
| Time to first/only chunk | 126.7 s |
| Total wall time | 126.7 s |
| RTF | 3.50 |
| Output | `G:\AI\tts_samples\cosyvoice3_cpu_instruct.wav` |

## Interpretation

- Russian synthesis and zero-shot/instruction API work.
- CPU performance is not real-time: generation takes about 3.5 times the audio
  duration, with a very large first-chunk delay.
- The model is therefore not suitable as the default conversational TTS on CPU.
- Keep it as an experimental voice-cloning/quality backend. TeraTTSv2 remains
  the low-latency default; Qwen3-TTS remains an optional quality/clone backend.

## Reproducibility notes

The normal API call is `inference_instruct2(...)` and the instruction must end
with the literal `<|endofprompt|>` token. CosyVoice3's CPU checkpoint contains
`bfloat16` LLM weights; the CPU probe converts that module to `float32` at
runtime. No CosyVoice source files were changed by this benchmark.

