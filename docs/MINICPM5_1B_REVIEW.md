# MiniCPM5-1B review — 2026-09-06

## Verdict

MiniCPM5-1B is a separate compact text-only model, not a smaller
MiniCPM-o. It cannot see the desktop, transcribe audio, clone a voice or
provide TTS. It is therefore not a Vision/VoiceMem replacement and must not
become a second JAWL personality owner.

It is a credible candidate for a fast auxiliary worker: short classification,
attention/event triage, bounded summarization, or a cheap local fallback. The
primary JAWL brain still needs a Russian-quality and tool-contract acceptance
test before this model can be promoted.

## What is inside

The official model is a dense `LlamaForCausalLM` with 1,080,632,832
parameters, 24 layers, GQA (16 query heads / 2 KV heads), and a 131,072-token
context. It supports one checkpoint with Think and No-Think modes. The
official repository identifies English and Chinese as its languages; there is
no official Russian quality claim in the model card.

The model is Apache-2.0. The user-linked GGUF repository is a third-party
quantization, not the OpenBMB release. It contains Q4_K_M (~688 MB), Q6_K
(~892 MB), IQ4_XS (~639 MB), IQ2_M (~460 MB), and many other variants. The
repository reports imatrix calibration over 500 WikiText rows. That is useful
for quantization quality, but it is not a Russian or tool-use calibration set.

Tool calling is documented as XML-style output, with SGLang's `minicpm5`
parser recommended for conversion to OpenAI `tool_calls`. Our JAWL JSON
envelope would require an explicit adapter and strict negative tests; raw XML
must never reach the native-action dispatcher.

## Decision for our architecture

- Do not replace MiniCPM-o, Qwen ASR, TeraTTS or JAWL with MiniCPM5.
- Add one small Q4_K_M or Q6_K artifact only as an isolated text-worker A/B
  candidate after the current MiniCPM-o baseline download is safe.
- Test Russian dialogue, JSON envelope compliance, tool-call conversion,
  refusal/invalid-action behavior, tok/s, TTFT, resident RAM and VRAM.
- The recommended first candidate is Q4_K_M for speed/quality balance; Q6_K
  is the quality reference. IQ2_M is an experimental low-memory point, not a
  default.
- If Russian semantic quality is weak, retain the model only for cheap
  non-authoritative triage/summarization. It may emit typed observations to
  JAWL but cannot write canonical memory or execute tools.
