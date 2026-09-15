# Универсальный gate мультимодальных моделей

Статус: обязательный прединтеграционный протокол, 2026-09-06.

## Правило отбора

Не скачивать полный вес модели размером 10–30 GB до минимального RU-прогона.
Сначала использовать самый маленький доступный вариант, API или короткие
fixture-файлы. Большой вес разрешён только после прохождения всех обязательных
capability:

| Capability | Что должно быть доказано |
|---|---|
| `RU_SCREEN_OCR` | модель читает кириллический экран и возвращает проверяемые строки |
| `RU_NATURAL_SPEECH_ASR` | понимает естественную русскую речь без передачи текста в prompt |
| `RU_AUDIO_VISION_BINDING` | связывает русский вопрос, звук и изображение в одном ответе |
| `RU_REALTIME_LATENCY` | первый полезный результат укладывается в заранее заданный realtime-бюджет |

Провал любой обязательной capability означает `REJECT` для русского
сенсорного контура. Модель может остаться opt-in worker для другого языка, но
не получает доступ к канонической памяти, личности, native tools или policy
JAWL.

## Минимальный протокол A–E

Каждый кандидат прогоняется на одинаковых fixture с JSON-отчётом. Ответ
проверяется по ожидаемым строкам и фактам, а не визуально по впечатлению.

1. **Run A — RU screen OCR.** Кириллический UI-скрин и запрос на русском;
   проверить минимум пять строк, статус и отсутствие нерелевантного ответа.
2. **Run B — RU natural speech.** WAV с естественной русской фразой без её
   текста в prompt; проверить транскрипт по смысловым ключам.
3. **Run C — audio + vision binding.** Одновременно изображение и русский
   аудиозапрос; ответ должен ссылаться на объект/строки именно на изображении.
4. **Run D — realtime.** Холодный и тёплый запуск; измерить load, encode,
   first useful token/audio, полный ответ, RAM/VRAM и ошибки.
5. **Run E — negative/control.** Английский контрольный fixture и нерелевантный
   или шумовой ввод; проверить отсутствие галлюцинаций и различение медиа.

## Решение и граница JAWL

В отчёте обязательны модель, quant, runtime, fixture/version, хэши, устройство,
`CUDA_VISIBLE_DEVICES`, cold/warm timings, peak RAM/VRAM, транскрипт, ответ и
причина решения.

- `PASS`: все четыре capability подтверждены двумя повторяемыми прогонами.
- `CONDITIONAL`: smoke успешен, но capability не доказана; только исследовательский worker.
- `REJECT`: провалена обязательная RU capability или нарушена изоляция.

Модель может выдавать только типизированное sensory observation с
`correlation_id`, временем и provenance. Она не может записывать каноническую
память, выбирать native tool, менять policy или обходить JAWL delivery-контракт.
`mmap` и частичный offload допустимы; per-layer paging в realtime-пути не
реализуется без отдельного доказательства стабильности.

Первый конкретный прогон описан в `docs/MINICPM_O45_BENCHMARK.md`: MiniCPM-o
4.5 прошла EN-контроль, но не прошла RU OCR и русский audio path.

## Важное уточнение для нашей модульной архитектуры

Этот gate является обязательным для единой Omni/VLM-модели, которой мы хотим
отдать одновременно русский экран, речь и binding audio+vision. Он не должен
блокировать наш основной модульный путь: Qwen3-ASR принимает речь, отдельная
VLM принимает кадр, а JAWL получает нормализованный sensory-контекст. Для
модульного пути проверяются те же четыре результата на уровне всей связки,
но capability `RU_AUDIO_VISION_BINDING` оценивается интеграционным тестом, а
не требованием к одной модели.

До скачивания тяжёлых весов обязательны также metadata/config/API smoke и
малый RU fixture. `mmap`, CPU/RAM offload и частичный GPU offload разрешены,
но только если отдельный cold/warm прогон фиксирует peak RAM/VRAM, latency и
отсутствие деградации. Это оптимизация размещения, а не замена capability
gate. Ни один кандидат не получает доступа к persona, памяти, native tools или
policy JAWL до прохождения соответствующего интеграционного acceptance.

## 2026-09-07 — Sidecar ASR + CPU-VLM smoke (modular path)

Hardware: CPU-only, AMD Ryzen 9 9900X3D (12C/24T), ~94 GB RAM, no GPU.

### ASR (capability RU_NATURAL_SPEECH_ASR) — PASS
- faster-whisper large-v3-turbo (CTranslate2 int8, 12 threads) in a stdlib sidecar
  (`scripts/asr_whisper_server.py`, OpenAI-compatible `/v1/audio/transcriptions`
  + `/health`) on 127.0.0.1:8984; models in `runtime/models/whisper-turbo`.
- Artifacts: Systran repo is gated; used mobiuslabsgmbh mirror (same CT2 bin,
  sha256 e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da,
  1617884929 B). Repo ships no vocab.json; ctranslate2 4.8.2 requires
  `vocabulary.json` (fetched from deepdml mirror).
- RU WAV (21.1 s TTS): latency 3.44 s (~6.1x realtime), full Russian sentences
  with punctuation, no tail loss. Companion live /api/doctor → asr: online.
- Run B.ean, and draft/finish client mechanics confirmed non-destructive.

### CPU-VLM candidate smoke (RU_SCREEN_OCR) — CONDITIONAL for SmolVLM2; others blocked
Common: transformers 5.16.1 + CPU + bfloat16 + sdpa; fixtures
`runtime/vision-smoke/fixtures/{ru_form.png,desktop_live.png}`; prompt RU;
results.json in `runtime/vision-smoke`.
- SmolVLM2-500M-Instruct: RUNS end-to-end. Processor quirk of this build:
  `processor.image_seq_len` must equal the pooler token count per subimage (64),
  not the default 169; size longest 2048 → 9–13 subimages → 576–832 image tokens.
  Latency ~8 s/frame (2 frames in ~16 s), RAM ~6–8 GB. Output: layout-level
  description only; no reliable Cyrillic OCR at 500M (garbles strings, rephrases
  the request). Verdict: CONDITIONAL – usable as near-real-time ambient/layout
  descriptor, NOT for text extraction.
- Namo-500M-V1: weights in place; BLOCKED in this env (transformers 5.16.1 has no
  `namo` model_type; PyPI pkg `namo` fails to build; GitHub repo not pip-installable,
  needs manual import + CUDA-oriented deps).
- moondream2: BLOCKED in this env (transformers 5.16.1 lacks moondream classes;
  current `moondream` pip is a cloud API client; legacy vikhyat/moondream package
  would be required). Weights historically 3.85 GB.

### Decision
- Full Omni-gate stays future work. For the modular path: ASR milestone closed
  (whisper sidecar = accepted RU ASR). Vision: adopt SmolVLM2 as interim
  near-real-time CPU layout/ambient descriptor; RU text extraction requires a
  stronger model or an OCR hybrid (e.g., Tesseract RU) — despite this, OCR-only
  framing remains rejected; the VLM adds spatial/context grounding.

### 2026-09-07 — Round 2: moondream2 and Namo now RUN on CPU (bench-recorded)
- moondream2 (2B, siglip+phi-1.5, vikhyatk/moondream2): repo ships full remote code
  (hf_moondream.py + config + modules). transformers 5.16.1 auto-load path broken
  (`all_tied_weights_keys` on remote PreTrainedModel) -> load manually:
  `HfMoondream(HfConfig())` + `model.load_state_dict(safetensors, strict=False)`
  (0 missing keys). API: `encode_image(im)->EncodedImage`, `query(emb, ru)`.
  Result: partial Cyrillic read - "Прибыль 1 240 500 рублей" (garbled but meaning
  intact) on ru_form; desktop -> echoes instruction. ~11 s/frame compute,
  ~6-8 GB RAM, load ~8 s. Verdict CONDITIONAL (reads some text, weak layout).
- Namo-500M-V1 (Qwen2.5-0.5B + AIMv2-L-native + pixelshuffle_2x, omni w/ whisper-AE):
  not pip-installable; repo `lucasjinreal/Namo-R1` cloned, `namo` package copied to
  `runtime\vlm-namo\namo` with 3 in-place patches for this env: (1) vision/__init__
  AutoConfig.register("aimv2") wrapped in try/except (builtin in 5.16.1); (2)
  ve_aim builds tower from repo AIMv2Config (builtin lacks patch_size/hidden_size);
  (3) configuration_namo sets vision_config.hidden_size=1024 (checkpoint arch;
  builtin Aimv2Config has no hidden_size attr -> connector would build 2816*4).
  Deps added to vision-venv: einops, loguru, termcolor, timm, peft, requests.
  Manual preproc (CLIP norm, dynamic div-28 resize, shortest 448 / longest 700).
  Result: reads real digits/dates of the form ("...14.02..06..13.40..1240.."),
  garbles longer labels; correct aspect-ratio resize matters (700x364 vs 700x448).
  ~4.4 s/frame compute, LOAD ~1 s. Verdict CONDITIONAL.
- Final RU_SCREEN_OCR for all three = REJECT for text extraction; CONDITIONAL for
  ambient/layout description. SmolVLM2 (layout) vs moondream (partial text) vs
  namo (fast, partial digits). No candidate gives reliable Cyrillic OCR on CPU at
  these sizes; a dedicated OCR step (e.g., Tesseract RU) remains the fit for text.

### 2026-09-10 — TAARDIS-27B RU gate: REJECT (built, benched, failed RU)

Built the TAARDIS llama.cpp fork from source (q1_0_g128-port branch, CUDA
12.8, sm_120a, Ninja) after solving three Windows build obstacles: the VS
generator bakes the newest-registered nvcc (13.3) into its CUDA
customization regardless of CMAKE_CUDA_COMPILER — Ninja avoids it; the
installed CUDA 12.8 toolkit lacks the CUBLAS component (headers and libs) —
a synthetic toolkit on G:\ was assembled (real 12.8 include copy + cu12
cublas headers from the nvidia-cublas-cu12 wheel + cublas import libs
generated from Ollama's cublas64_12.dll) and forced via
`-DCUDAToolkit_ROOT`; runtime DLLs (cudart/cublas from Ollama) were placed
next to the exe.

Bench on GPU0 (`TAARDIS-27B-Full-Ternary-V2-1.75bit` + Doctors-V3 lora,
q4_0 KV, fa on, recommended sampling temp 1.0/top-p 0.95/top-k 20/
repeat-penalty 1.3, thinking off):

- Generation ~31–38 tok/s (GPU0 shared with a resident Ollama model, so
  ceiling unclear), prompt ~98 tok/s.
- **RU: FAIL.** Even with an explicit Russian system prompt the model
  answers in English; thinking mode reasons about Russian correctly but the
  direct generation does not hold the language. 1.75-bit ternary conversion
  destroyed Russian language steering.
- Factual quality degraded (garbled Rayleigh-scattering explanation);
  repetition loops appear without repeat-penalty (Doctors fix stop
  discipline, not content).

Verdict: **REJECT for the RU realtime brain.** The 2-bit/ternary post-training
conversion hits Russian far harder than English. The confirmed brain
candidate is **ISTA-DASLab GSQ-RCO Qwen3.8-27B IQ2_S** (2.75 bpw, dynamic
per-tensor quant, 9.3 GB, vision mmproj included, published recovery
101.8% vs BF16, MTP speculative variants) — download and GPU0 test in
progress. Bonsai-27B Q1 remains the interim brain+eyes.

Prism ML `Bonsai-27B-gguf`: Qwen3.6-27B hybrid (Gated DeltaNet), ternary/1-bit
GGUF line. Tested locally on GPU1 with mainline llama.cpp CUDA b10883 (the
linked AMD Strix-Halo release is not applicable to our NVIDIA hardware):

- Weights: `Bonsai-27B-Q1_0.gguf` 3.80 GB + `Bonsai-27B-mmproj-Q8_0.gguf`
  0.63 GB (vision encoder). Ternary `Ternary-Bonsai-27B-Q2_0` is 7.17 GB;
  the operator judged 7 GB too large for the VRAM budget and chose Q1.
- Server load 0.16 s; VRAM 5.4 GB total with 8k ctx (10.6 GB still free on
  GPU1); system RAM 6.8 GB.
- RU text: coherent and grammatical («...рассеянием Рэлея...»); generation
  **102 tok/s** short / 57 tok/s at 4k context; prompt prefill **2164 tok/s**
  (a 4k prompt in ~1.9 s — the JAWL 11k route projects to ~5 s vs 12–27 s
  now). Reasoning must be disabled per request
  (`chat_template_kwargs.enable_thinking=false`) or content comes empty.
- Vision (mmproj): RU screen OCR PASS — the ru_form read exactly (заголовок,
  «Прибыль 1 240 500 рублей», статус УСТАНОВЛЕНО) in 7 s; desktop caption
  more detailed than Qwen3-VL-2B (read the on-screen file name), 15 s
  (on-demand tier).
- Known weakness: counting task missed (15 vs 250 repetitions) — 1-bit
  precision limit; JAWL tool-call/Goal-envelope compliance is untested yet.

Interim verdict: a single 4.4 GB resident model covers the conversation lane
(speed ~3–10× the current Gemma route) and on-demand vision, which supports
dropping the dedicated background VLM; background sensory stays with the
cheap extractor stack. Next: download the ternary Q2_0 target + DSpark
drafter if quality/VRAM trade-off allows, build the Prism CUDA fork for
speculative decoding, and run the JAWL tool-call RU gate before any
provider swap.

### 2026-09-10 — Round 5 candidate: Bonsai-27B Q1_0 with vision (one model for brain+eyes)

### 2026-09-10 — Round 4: modular sensory bundle on GPU (Qwen3-VL-2B Q4 + whisper + MusicState/CLAP)

Bundle: Qwen3-VL-2B Q4_K_M via llama.cpp CUDA b10883 on GPU1 (port 8983,
server load 0.18 s), whisper-turbo ASR (8984, CPU), MusicState (librosa +
Basic Pitch) and CLAP (laion/larger_clap_general, GPU) — see
SENSORY_STACK_DESIGN.md for the full sensory architecture.

- Run A — RU_SCREEN_OCR: PASS ×2. ru_form fixture read exactly (заголовок
  «Загрузка отчёта - Сводка по продажам», прибыль «1 240 500 рублей»,
  статус «Установлено»); 1.7 s first, 0.2 s warm. Versus 83.8 s CPU
  (Round 3 crane) this closes the RU screen-reading capability on GPU.
- Run B — RU_NATURAL_SPEECH_ASR: PASS (whisper-turbo, prior evidence plus
  gate question transcription in this round; browser E2E 3/3 earlier).
- Run C — RU_AUDIO_VISION_BINDING: PASS ×2 (integration, modular). RU
  question synthesized by VoxCPM → whisper → text+image → VLM: "Какой
  отчёт...?" → «отчёт по продажам, 1 240 500 рублей» (0.4 s); repeat with
  "Какой статус?" → «УСТАНОВЛЕНО» (ASR homophone форма/форум tolerated).
- Run D — realtime: server cold load 0.18 s; first image request 17.9 s
  (cold prefill), warm captions 2.5 s, warm OCR 0.2–1.7 s; CLAP 30 ms per
  10 s chunk; MobileCLIP2-S0 35–37 ms/frame CPU; SER 0.24–0.53 s/clip;
  Basic Pitch 15 s → 2.8 s. Sensory cadences all fit their tiers; realtime
  conversation budget untouched.
- Run E — negative/control: 1×1 px image → honest «пустое поле… без
  деталей» (no hallucination); music into speech-ASR hallucinated and is
  VAD-gated by design; SER correctly assigns music to `other` (0.982).

Verdict: modular sensory bundle = **PASS** at the integration level (all
four capabilities, Run C repeated). Voice emotion: DSP prosody engine
(pitch/energy/speed envelopes) verified in scripts/voxcpm_server.py —
whisper roundtrip text-identical across neutral/angry/sad envelopes.
StyleStream deferred (licence/RU-test); CosyVoice3 CUDA optional lane.

Known costs: VoxCPM2 worker ≈ 11 GB system RAM + ~4–5 GB VRAM (GPU1) while
resident; memory-light scheduling (load-on-idle/lazy) is future work.

### 2026-09-07/08 - Round 3: Crane VLM + OCR + TTS (CPU) - phases 2/4/5/6
- Engine: lucasjinreal/Crane -> crane-serve (Rust, CPU F32). Bina/weights under runtime\crane-repo / runtime\models\crane.
- Qwen3.5-2B VLM (--model-type qwen3_5_vl, /v1/chat/completions, image_url base64):
  ru_form -> PASS. ������ ��������� ������������� ������: ��������� ������ - ������ ��
  ��������, ���� ���� �������������/��������, ���������� �������: ������� 14:02 � ����������
  ���������� / 13:40 � ��������� ����� ������� / 06 �������� � ������� ��������, �������
  �����������: �������˨�λ, �������� 1 240 500 ������, ������ �������� ��רһ � ��� ��������
  ������ ����� + ������ ���������. desktop_live -> PARTIAL: ������ ������� ������ ���������
  (Telegram Desktop 1.2.100.1, Windows 11, ������ ����� ������), �� �� ����-�������� ������ �
  ������-����� (���� ����������� x10+). �����������: ru_form 83.8s, desktop 151.2s (F32 CPU, 22).
- PaddleOCR-VL-1.5 OCR (--model-type paddleocr_vl, 8081): ru_form 31s -> ������ ���������� RU
  ������ (label:��������, ����, ����� � �����); desktop_live -> ���������� �����
  (\( \text{CaCO}_3 \)...) = ������ ��������� formula-������������� �� ��������� ����. ���������
  (2 �������). OCR ��� ���� = PASS, ���-�������� desktop = REJECT.
- ��������� VLM (smol/moondream/namo) ��� ���������� RU-������ �����������: Qwen3.5-2B �
  PaddleOCR-VL ������ ��������� ������; Qwen3.5-2B ��� + ��������� ����������.
- Qwen3-TTS (Qwen/Qwen3-TTS-12Hz-0.6B): CustomVoice = ������ text->speech �� /v1/audio/speech
  (wav, 24kHz 1ch), Base ������� voice-clone reference audio � � Rust-���� �� ����������.
  RTF (F32 CPU, 24 ����) = ~2.4x realtime (25.8s �� 10.88s �����). --dtype f16 �� CPU ������
  (NaN-���). Whisper-�����������: ������������ ������� ~100% ������� � �������� �������.
  �������: WORKING (intonation/����� ������), ������� ��������� ������� �� CPU ���.
- Silero VAD (vision-venv, silero-vad + torchaudio): ����������� RU-speech working
  (10.88s wav -> 3 ��������, 9.40s ����; ������ 0.5/180ms/150ms). �������: PASS (endpointing).
- ���� �� ����� 2,4,5,6 �� CRANE_VLM_GATE.md � ��. ���� ������ c ����������������� ������������.
