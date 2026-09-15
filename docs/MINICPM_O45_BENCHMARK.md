# MiniCPM-o 4.5 benchmark and gate result

Universal protocol: `docs/MULTIMODAL_MODEL_GATE.md`.

Status: base + sidecars downloaded and SHA-256 validated 2026-09-06.
This is an opt-in sensory worker, not a replacement for the JAWL
text/persona/memory owner.

## Official language files

| Variant | Bytes | Official SHA-256 | Role |
|---|---:|---|---|
| Q4_0 | 4,773,679,904 | `0df3f51f5d6f2342d302f69f0e5426fe6fa3507368c6a847e3163d75d1440947` | low-size reference |
| Q4_K_M | 5,026,714,400 | `1237a97ee081b8abebc47aa7dad565701e8f5f904cdc92f6723ac4281bbc0932` | primary baseline |
| Q5_K_M | 5,849,946,912 | `5d32e7569f2ef9c61de81a4fba3890a225240a5cf753e0348f5889dbf44ea434` | quality reference |

Download state (owned area `runtime/models/minicpm-o-4.5/`):

- `MiniCPM-o-4_5-Q4_K_M.gguf` — downloaded, size 5,026,714,400 B matches,
  SHA-256 verified against official.
- `audio/MiniCPM-o-4_5-audio-F16.gguf` — 660,167,904 B, SHA-256
  `d5b188ac7feaf98e17175c3f9bd14bf269301bfd187439fdaa3e3a494fc32ef7` verified.
- `vision/MiniCPM-o-4_5-vision-F16.gguf` — 1,095,113,184 B, SHA-256
  `1453678cc4e4fe18de241952962e234f265cb8dda780773526103ab8ba82f421` verified.
- `tts/MiniCPM-o-4_5-projector-F16.gguf` (14,948,640 B) and
  `tts/MiniCPM-o-4_5-tts-F16.gguf` (1,157,244,416 B) — SHA-256 verified.
- `token2wav-gguf/{encoder,flow_extra,flow_matching,hifigan2,prompt_cache}.gguf` —
  all five files downloaded, reduced/baseline SHA-256 verified.
- Q4_0 / Q5_K_M comparison points are not yet downloaded.

## Runbook / runtime state (2026-09-06)

- CUDA toolkit 12.8 on this host was runtime-only (CUBLAS missing); the
  full CUDA toolkit 13.3.73 was installed alongside (winget) on 2026-09-06
  and the CUDA backend now builds and runs (see GPU smoke results below).
  MSVC 14.44 (VS2022 BuildTools) and Ninja are available.
- CPU-only `llama.cpp-omni` built from `tc-mb/llama.cpp-omni` (master,
  `64d092c`) into `G:\AI\llama-omni\build-cpu\bin`:
  `llama-omni-cli.exe`, `llama-omni-single-test-audio.exe`,
  `llama-omni-single-test-omni.exe`.
  Note: `llama-cli-impl` fails to compile in this fork because
  `tools/cli/CMakeLists.txt` does not add the `tools/mtmd` include dir;
  omni/mtmd targets are unaffected.
- Models live in `runtime/models/minicpm-o-4.5/` with the exact layout the
  CLI auto-discovers: `MiniCPM-o-4_5-Q4_K_M.gguf`, `vision/`, `audio/`,
  `tts/`, `token2wav-gguf/`.
- Command used for the smoke:
  `llama-omni-cli -m <base>\MiniCPM-o-4_5-Q4_K_M.gguf -ngl 0 -c 2048 --no-tts
  --omni --test <fixtures>\omni_test_case\omni_test_case_ 1`

## CPU smoke results (Q4_K_M, -ngl 0, -c 2048, no TTS)

- Load: all four component models found in the owned area. Audio model
  loaded as APM; vision and audio encoders ran on CPU.
- Fixture: omni_test_case_0000 (1 image + 1 audio), media_type=2.
- prefill (audio+vision): ~1.86 s.
- LLM decode to EOS: ~4.3 s (tokens 62 → 114).
- Exit code 0; no LLM warnings fatal; per-round boundaries recorded.
## GPU smoke results (Q4_K_M, GGML_CUDA=ON, CUDA 13.3)

- Full CUDA toolkit 13.3.73 installed via winget (`Nvidia.CUDA`); note
  upstream CDN no longer serves the 12.8.0/.1 local installers (all
  variants returned 404), and CUDA 13.3 is backward-compatible with the
  host's 12.8 runtime and the RTX 5080 (arch `120a`).
- Built into `G:\AI\llama-omni\build-cuda\bin` with:
  `-G Ninja -DGGML_CUDA=ON [-G exit 0]`; `cmake --build --target
  llama-omni-cli llama-omni-single-test-audio llama-omni-single-test-omni
  llama-tokenize -j16`. A clean dir was needed for the cublas/NCCL
  detection. NVCC from the new toolkit automatically detected `arch 120a`.
- Runtime needs CUDA `bin` + `bin\x64` on PATH or the process exits
  `0xC0000135` (DLL not found).
- GPU selection: `GGML_CUDA_DEVICE=1` alone is not enough because the
  mtmd/vision backend hardcodes CUDA0 (`vision using CUDA0 backend`); the
  host's other backend would still use GPU0. Use
  `CUDA_VISIBLE_DEVICES=1` so the physical GPU1 is the only device the
  process sees (`ggml`/`CUDA0` label then refers to the physical GPU1).
- End-to-end omni test (`--omni --test omni_test_case_ 1`, n_ctx 4096,
  no explicit `-ngl`): GPU1 peak 10995/16303 MiB, GPU0 untouched
  (2603 MiB host baseline). LLM+vision+audio+TTS all offloaded; TTS
  simulator RTF 0.05..0.11; exit code 0. Full LLM+audio+vision path
  recorded (see stdout logs in temp area).
- Vision-only bench on CPU did not finish in 10 min; on GPU1 it is
  expected to be fast with the CUDA backend.
- Screen/image OCR (bench + grounded prompt):
  - EN fixture (Booking System screenshot + EN spoken prompt):
    baseline 2465 MiB, peak 2651 MiB; serial encode ~129-143 ms,
    batched ~99-107 ms (1.24-1.42x); LLM recognized all 5 UI lines
    including "Status: ONLINE". Reproducible on repeat runs.
  - RU fixture (same layout, Cyrillic strings + RU SAPI prompt): not
    recognized. With RU prompt the model replies in Chinese; with an EN
    prompt against the Cyrillic image it answers an unrelated greeting.
    The built-in system prompt is Chinese and the model does not parse
    Cyrillic screen text or Russian SAPI audio. RU OCR/UI grounding is
    NOT supported by this model/config.
- Audio-only pipeline (en fixture, TTS on): prefill init (system) 0.047 s,
  user prefill 0.051-0.070 s; LLM decode 82 tokens in ~0.18 s to EOS
  (~455 tok/s offload); first audible response 495-527 ms (2 runs);
  TTS audio tokens 74-141 per chunk; Token2Wav vocoder on GPU (CUDA
  detected); repeatability stable (wall e2e 6.1 s and 7.1 s incl. cold
  model load on run 1); exit 0.

## RU acceptance tests (2026-09-06) - FAIL

Purpose: verify that the model can act as a JAWL UI-grounding worker for
the Russian scenario (Cyrillic screen + spoken Russian prompt). Result:
negative in both channels. Full protocol:

1. Fixture `runtime/bench/rumbench_ru/ru_test_case/`:
   - `ru_test_case_0001.jpg` - synthetic Russian UI ("Система бронирования",
     "Логин: operator01", "Пароль: ********", "Забронировано мест: 12",
     "Статус: ОНЛАЙН", "Ошибок за сутки: 0").
   - `ru_test_case_0001.wav` - Russian prompt via SAPI "Microsoft Irina
     Desktop" (ru-RU): "Прочитай, что написано на экране. Перечисли строки
     и статус."
   - `ru_test_case_0000.wav` / `ref_ru.wav` - Russian ref voice sample for
     voice cloning.
2. Run A (RU prompt + Cyrillic image, `--test ... 1>`, RU wav used only as
   ref audio): decode ran, but output `llm_debug/chunk_*` was an unrelated
   Chinese folk tale ("从前有座山..."), i.e. no RU speech recognition, no
   grounding.
3. Run B (`--test ... 2`, ref = `ru_test_case_0000.wav`, user = 
   `ru_test_case_0001.wav` + image): same Chinese story output. Confirmed
   the RU wav never became an actionable user prompt.
4. Run C (EN prompt + Cyrillic image, `mix_test_case`): model responded in
   Chinese with a greeting ("啊，你好。今天过得怎么样呀？") - Cyrillic
   screen text is not read at all.
5. Control (EN prompt + EN image, `en_test_case`): perfect OCR, listed all
   5 UI lines and status. Proves the pipeline itself works and RU is the
   failure channel, not the runtime.

Conclusion: the model is English/Chinese-only in both modalities. A JAWL
Russian UI-grounding worker cannot be built on this model/config without an
external RU OCR/ASR wrapper. The model stays an opt-in EN screen/voice
coprocessor on GPU1; all Russian sensory work stays on the JAWL stack
(Whisper RU + RU TTS + main LLM).

The official repository also contains separate F16 vision, audio, TTS and
token2wav assets. There are no official IQ1/IQ2 files for this model. Any
locally converted low-bit file must be clearly marked experimental and must
use an importance matrix before quality comparison.

## Placement policy

- GPU1 is the only allowed device for this optional worker; GPU0 remains
  reserved for the host/JAWL workload.
- Keep VAD, ASR, audio event buffering, TTS and token2wav in CPU RAM unless
  measurements show a clear benefit from GPU1.
- Use memory mapping and explicit partial GPU offload where supported.
  Do not implement per-layer demand paging in the realtime path.
- A file-size estimate is not a VRAM estimate. Record peak VRAM, resident RAM,
  page faults, cold start and warm start.

## Acceptance matrix

Run the same Russian prompts, UI screenshots and short audio/video fixtures
for every variant. Record load success, image TTFT, generation throughput,
Russian OCR/UI grounding, audio/video startup, interruption response,
repeatability, peak VRAM and resident RAM. A variant is not production-ready
unless it also preserves the JAWL boundary: it may emit typed observations,
but cannot write canonical memory, select native tools or change policy.

The current bundled `llama.cpp` executable is CPU-only. CPU loading is useful
for compatibility smoke tests; GPU claims require a CUDA-enabled runtime and
an `nvidia-smi`-verified GPU1 assignment.

## Next decision
- DECIDED (2026-09-06): RU scenario is closed. The model cannot read
  Cyrillic screens or hear Russian speech in either direction. It is kept
  only as an opt-in EN screen/voice coprocessor on GPU1; all Russian
  sensory work remains on the JAWL stack.
- Proved: CUDA build + GPU1 isolation via `CUDA_VISIBLE_DEVICES=1`; TTS
  and omni path work end-to-end on GPU1; EN image TTFT/bench and audio
  smoke done (figures above). Remaining optional metrics (interruption,
  token/sec) are informational, not gating, for an EN-only coprocessor.
- The duplicate download cache has been removed; the validated runtime bundle
  remains in `runtime/models/minicpm-o-4.5/` as an opt-in asset. The main next
  step is the RU JAWL production gate: restore/verify the canonical discovery
  and tool-transport path, then run the real voice, memory, native-action and
  interruption checks. MiniCPM-o is not part of that gate.
