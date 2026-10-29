# LFM3-Audio-2B as a possible audio-description lane (2026-10-29)

## Finding

The official [LFM3-Audio-2B card](https://huggingface.co/LiquidAI/LFM3-Audio-2B)
describes an audio-only 2B model for multilingual speech, audio understanding,
events, and text responses. It is a more directly matched candidate for an
isolated audio lane than LFM3-Omni, whose A/V story probe showed cross-modal
hallucinations ([existing report](lfm3-omni-story-20261028.md)).

The official [GGUF card](https://huggingface.co/LiquidAI/LFM3-Audio-2B-GGUF)
lists Q4_K_M weights at about 1.10 GB and an audio `mmproj` at about 338 MB.
Support landed in upstream llama.cpp PR [#31257](https://github.com/ggml-org/llama.cpp/pull/31257),
merged on 2026-10-27. The project's existing `G:\AI\llamacpp-prism` source
(commit `1a07bfa`, 2026-09-17) predates that merge and has no LFM3-Audio runtime
symbols, so the candidate is not available in the current production runtime.

An isolated upstream checkout was made under
`runtime/lfm3-audio-cpu-probe` at commit `0ac1a7f` and built successfully with
MSVC Release, `GGML_CUDA=OFF`. The resulting `llama-mtmd-cli.exe` is CPU-only.
Its optional HF downloader was built without HTTPS support. The official files
are public, but `huggingface_hub` stalled during transfer; a separate 16 MiB
parallel Range probe took 26s (about 0.6 MiB/s), implying roughly 40 minutes for
the 1.44 GB model+projector pair at the observed rate. No inference was started
and no model download is left running. Public HF metadata lists English and
several other languages, but not Russian, which makes Russian ASR a separate
acceptance risk.

The official [ONNX card](https://huggingface.co/LiquidAI/LFM3-Audio-2B-ONNX)
lists a Q4 CPU bundle at 2.71 GB and documents separate encoder/decoder/cache
inputs; it is not a drop-in encoder or classifier for the existing ONNX lane.
The local `runtime/vision-venv` also does not have `onnxruntime_genai` installed.

## Decision and next experiment

Do not add this model to the daily profile yet. The next gate is an isolated
CPU-only Q4_K_M comparison on the existing source-labeled trailer and song, then
the wider gameplay, coding, speech/noise/silence set if the first probes are
promising. Record CPU-only provider/build, cold and warm latency, peak RSS,
transcript presence without persisting transcript text, and groundedness for
audible events, style, vocals, and unsupported claims. Keep GigaAM ASR and
YAMNet presence as independent controls. Promote only if the model improves
grounded descriptions and handles the project's Russian audio within acceptable
latency and memory.
