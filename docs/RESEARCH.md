# Repository Research

## 2026-09-19 — R2T2 (Confucius4-R2T2): true-streaming ASR кандидат

Запрос владельца: r2t2.ai — тестировать. Модель от NetEase Youdao.

**Что это:** open-source **true streaming ASR** (Real Real-Time Transcription) на
базе **Qwen3-ASR-1.7B**. Append-only вывод: текст коммитится по мере речи и
**никогда не перезаписывается** (Longest Stable Prefix) — 200–600 мс latency,
chunk 80 мс–2 с настраивается. Это ровно закрывает две известные проблемы
нашего ASR-контура: «фраза отправляется до того, как я её договорил» и «слов
в транскрипте меньше, чем я сказал» — за счёт инкрементальности и стабильности.

**Code:** Apache 2.0. **Weights:** NetEase Model Use License Agreement
(ограничения: >100M MAU / >1 млрд ¥ — нужен отдельный license §2.2; §3.4(c) —
нельзя использовать для улучшения AI-моделей кроме R2T2/non-commercial;
юрисдикция КНР, zh-версия преобладает §6/§9). Для локального личного
использования приемлемо; для закрытого коммерческого продукта — юридическая
зона внимания.

**Backends:** vLLM (рекомендован, требует CUDA+PyTorch матрицу) или
transformers; есть готовый WebSocket-сервер (`ws_server.py`, порт 8272,
`/asr_stream_api_v1`: PCM 16k mono int16 → incremental JSON text). Python 3.12.

**Языки:** оптимизирован под Chinese/English; русский — в списке
«cross-lingual» (retains useful capability) БЕЗ опубликованной оценки.
Это ключевой риск: наш контур русский, канонический ASR — GigaAM v3
(crispasr, batch-final), Qwen3-ASR-0.6B — опциональный фолбэк.

**Бенчи** (по их таблицам): R2T2 160 мс ≈ Qwen3-ASR offline 2 с с небольшим
проигрышем (AMI 9.25→11.37, LS-clean 1.67→2.13, SPGI 2.90→3.00) — отличный
trade-off за 20× меньшую латентность, но цифр по-русски нет.

**План проверки (gate, без зряшного скачивания 4–8 ГБ):**
1. RU-фикстура: маленький русский WAV → hosted demo r2t2.youdao.com/demo
   с русским промптом (бесплатно). Если качество по-русски слабое → REJECT
   по RU_NATURAL_SPEECH_ASR, как с Qwen3-ASR-0.6B было.
2. Если RU приемлемо → целевая связка, повторяющая текущий путь:
   **R2T2 = streaming partials** (инкрементальные коммиты в `/api/ws`),
   **GigaAM = final** (batch over buffered utterance). Та же архитектура, что
   уже есть (streaming_asr + giga_final), но streaming-слой с append-only
   стабильностью вместо rollback-партиалов.
3. License + RU вывод зафиксировать здесь же.

## 2026-09-19 — R2T2 RU-smoke: заблокирован перегруженным демо

Hosted demo (`r2t2.youdao.com/demo` и HF Space `netease-youdao/confucius4-r2t2-demo`)
стабильно отдаёт `event: error, {"error": null}` **даже на собственном английском
семпле** (`librispeech_sample.wav`) — GPU-слот ZeroGPU не выделяется («heavy loads»
на странице демо). Это не про наш русский WAV, а про недоступность инференса.
RU-качество R2T2 **НЕ проверено**. Локальная проверка требует vLLM/transformers
env + 4 ГБ весов (Python 3.12) — по гейту не ставится до RU-smoke. Статус:
**pending — повторить демо позже / локальный RU-smoke после решения по env.**

## 2026-09-19 — Laya: System-1 decision engine (routing перед LLM)

Запрос владельца: laya.convaiinnovations.com — изучить.

**Что это:** не-авторегрессионная **System-1 decision model** Family от ConvAI
Innovations (открытая альтернатива закрытому Jev от TypeSafe AI). Один forward
pass, **никакой text generation** — только вероятности по структурированным
схемам (нечему галлюцинировать, malformed JSON невозможны). Три примитива:
`choice` (выбор из критериев, распределение по всем опциям + калиброванная
уверенность), `score` (ординальная шкала), `noul` (P(true)/P(false)).
Латентность **32.8 мс/вопрос** на GPU (7.2 мс batched) — 6–8× быстрее Jev,
0$ inference, Apache-2.0, commercial-use.

**Чекпойнты (HF `convaiinnovations/`):**
- `laya` — ModernBERT-large 421M, ctx 512, English (triage/guardrails/email);
- `laya-multilingual` — mmBERT-base 322M, ctx 1024, **100+ языков, русский в
  списке**, 2.2× быстрее — «use this for anything that is not English»;
- `laya-typed-decisions` — ModernBERT-large 421M, ctx 1024, agent workflows.

**Router:** авто-выбор чекпойнта по скрипту ввода (ru → multilingual),
`preload` нескольких — потом только forward passes.

**Кейс для нас:** System-1 слой ДО глубокого LLM — routing темы сообщения
(задача/вопрос/поручение), фильтр спама/jailbreak, эмоция — за ~30 мс локально,
с калиброванной уверенностью, без токенов и без жёсткого ожидания LLM.
Загрузка: `runtime/models/laya-multilingual` (snapshot скачан). Требует
`pip install laya` + transformers; RU-смок на наших фикстурах — следующий шаг.

### Вердикт RU-smoke (2026-09-21, локально, ПРОВЕРЕНО)

Веса `laya-multilingual/model.safetensors` (643.8 MB, dl_parallel ✓) + `laya`
0.3.4 в vision-venv (transformers 4.57.6). Прогон `scripts/laya_ru_latency.py`,
CPU, mmBERT-base, 5 русских обращений, вопрос-схема `department` (choice).

**Результаты:**
- accuracy **4/5**: technical 0.979/0.988, billing 0.998 ✓; граничный кейс
  «Сколько стоит годовая подписка?» → billing 0.896 (ожидалось sales —
  «подписка» перевесила «цены»; семантическая граница критериев, не отказ).
- **warm p50 = 54 ms / max 65 ms** на CPU (без GPU, без батча) — укладывается
  в голосовой цикл; на GPU по паспорту ещё быстрее.
- Первичный смок (браузер-завис → technical 0.99, возврат денег → billing
  0.97) — то же качество.

**Вердикт: PASS как локальный System-1 слой.** То, что Needle3 не может на
русском (см. ниже), Laya делает корректно за ~54 мс и без генерации. Кандидат
для routing темы сообщения (задача/вопрос/поручение/эмоция) до глубокого LLM,
с калиброванной уверенностью: conf < порога → эскалация на LLM. Пограничные
критерии надо писать раздельно (явления при покупке ≠ вопросы о цене), при
нужде — 2-вопросная схема.

## 2026-09-19 — Needle 3: крошечный tool-calling субагент

Запрос владельца: найти и скачать needle 3 — кандидат субагента для связей.

**Cactus-Compute/needle3** (Apache-2.0, 36k downloads): **микро-модель
function-calling** для on-device/edge (мобилки, роботы, edge). Не генеративный
чат: выбирает инструменты и заполняет аргументы из фразы, один JSON
`function_calls` + `reasoning` + калиброванная `confidence`; запрос вне
покрытия → пустой список (не догадка). Есть structured extraction и embedding.
Arch: Laddered Simple Attention Network (GQA + Monarch MLP + engram n-gram),
121M params; `needle3.cact` (2-бит, 33.7 MB) + движок на платформу
(`windows-x86_64/needle.exe` 1.2 MB) + safetensors 230.8 MB для fine-tune.

**CLI (в README):** `needle --model needle3.cact --tools tools.json --prompt "..."`;
`--serve` — режим сервера. Confidence позволяет act/confirm/refuse. Fine-tune:
LoRA + `needle build --layers N` (субсеть 2–20 слоёв, от 29M параметров).

**Кейс для нас:** локальный tool-caller в swarm — выбор native-инструмента IAWL
по фразе (связка с hostos/native policy), экономия LLM-токенов, офлайн.
Скачано в `runtime/models/needle3/` (exe, .cact 33.7 MB, header, config,
tokenizer, LICENSE, README). **RU-качество не заявлено/не проверено** — нужен
RU-смок; если русский слаб → только английский tool-path или REJECT для
RU-контура (как с другими EN-only кандидатами).

### Вердикт RU-smoke (2026-09-21, локально, ПРОВЕРЕНО)

Инфраструктура: веса `needle3.cact` + `windows-x86_64/needle.exe` + Python
`cactus-needle` (vision-venv). Тест: 4 инструмента (timer_set, remember_fact,
send_message, open_app), свежий агент на каждый запрос (никакого state bleed).

**Результаты (изолированные прогоны):**
- EN "Set a timer for five minutes" → `timer_set{minutes:5}` conf 1.0 — **PASS**
- RU "Поставь таймер на пять минут" → `send_message` («оставь таймер...») — **FAIL**
- RU "Запомни, что я люблю кофе" → **UnicodeDecodeError** (движок падает на
  кириллице в decode-шаге) — **ERROR**
- RU "Отправь Пете сообщение: привет" → `send_message` — **PASS по имени тула**,
  но аргументы искажены (contact/text = "привет")
- RU "Запусти браузер" → `send_message` («апусти браузер») — **FAIL**

Дополнительно проверено: CLI-передача `--prompt` с кириллицей через консоль
Windows ломается на cp866 → мусор-токены; `--serve` на этом билде вообще не
применяет `--tools` (все фразы дают «No tool available...» — даже EN).

**Вердикт: REJECT для RU-контура.** Needle3 — отличный EN tool-caller (121M,
80 MB RAM, ~1.1k tps on CPU, confidence честная), но русский не поддержан на
уровне декодера: кириллица может вызвать UnicodeDecodeError движка, а
близкие RU-фразы маршрутизируются неверно (всё соскальзывает на первый
популярный тул). Для задач «связей» в русском потоке не годится без
EN-моста/транслита, который добавляет хрупкость и теряет смысл русских
интонаций. Кандидат остаётся только как возможный EN-only tool-path для
латинских команд/структурированных имён — без приоритета.

## 2026-09-17 — LFM2.5-Audio-1.5B: пригодность для русского голосового дуплекса

Запрос владельца: проверить поддержку русского, наличие русских файнтюнов,
возможность дообучения.

**Факты (по карточке HF LiquidAI/LFM2.5-Audio-1.5B и API поиска):**
- Поддерживаемые языки: **только English** (явно в карточке: «Supported
  languages: English»). Аудио-энкодер — NVIDIA FastConformer (canary-180m-flash,
  тоже англоязычный). Детокенизатор — Mimi-совместимый (Kyutai), 8 codebooks.
- Существует официальный файнтюн **LFM2.5-Audio-1.5B-JP** (японский) — значит
  мультиязычное дообучение технически возможно и LiquidAI его делают сами.
  Русского файнтюна в поиске HF не нашлось (проверены все ~30 моделей по
  запросу LFM2.5-Audio: EN, JP, tool-aware форки — RU нет).
- Community-форки: GGUF (официальный и Mungert), ONNX (официальный),
  MLX (Apple), tool-aware файнтюны (matbee), IFEval SFT+GRPO. Все EN.
- Дообучение: технически возможно (есть JP-прецедент; есть peft/LoRA адаптер
  Omni-Post-Train; код обучения у LiquidAI частично открыт через liquid-audio
  пакет). Но для русского speech-to-speech потребуется: русский аудио-датасет
  разговорной речи (тысячи часов для качественного дуплекса), переобучение
  аудио-энкодера (FastConformer — английский), и отдельный гейт на качество
  русского ASR+TTS. Оценка: недели работы и GPU-время, результат не гарантирован
  — наша текущая связка GigaAM (RU ASR) + TeraTTS (RU TTS) уже даёт русский
  голос с доказанным качеством и low-latency.

**Вердикт:** LFM2.5-Audio сейчас для нас REJECT по gate (RU_NATURAL_SPEECH_ASR
не поддержан). Дообучение под русский — возможная, но тяжёлая R&D-задача;
возвращаемся к ней только если текущая связка ASR→LLM→TTS упрётся в задержку,
которую нельзя решить иначе. LFM2-VL-3B (зрение) — REJECT без прогона: в списке
языков нет русского, а Qwen3-VL-2B уже доказан на RU-фикстурах.

Historical research snapshot, not a current runtime instruction. Native gateway
findings and provider/model choices below may have been superseded; consult
[PRODUCT.md](PRODUCT.md), [STATE.md](STATE.md), and [DECISIONS.md](DECISIONS.md).
Do not execute old probes against the protected JAWL-Coding reference or assume
its dirty additions exist in a clean upstream checkout.


Research snapshot: 2026-09-01. Reference repositories were downloaded as
shallow clones for inspection under `G:\AI\_tmp\companion-repos`.

## JAWL

Upstream/reference: [JAWL](https://github.com/th0r3nt/JAWL)

Relevant strengths:

- event-driven ReAct;
- Heartbeat with wake-up and idle backoff;
- SQL/vector/graph memory;
- traits, mental states and drives;
- subconscious consolidation and reflection;
- Windows UI Automation and guarded desktop actions;
- multimodal hooks and MCP.

Conclusion: use as the cognitive core.

Runtime validation finding: an isolated JAWL instance was started with the
local Ollama endpoint and its real Vector DB embedding cache. The LLM request
completed, but the native cycle returned a thought with no terminal broadcast.
The existing `HostTerminalClient` is therefore an event input plus broadcast
output channel, not a request/response RPC. The companion must preserve a
degraded fallback until a correlated streaming contract is implemented.

The correlated web contract was inspected and exercised as well: JAWL's web
`POST /api/chat` acknowledges the user sequence while
`GET /api/chat/stream` carries later terminal broadcasts. The companion's
adapter correlates only a later non-user sequence. In the isolated production
probe the terminal input reached JAWL and Ollama completed, but the selected
model emitted no user-facing broadcast, so `no_broadcast` was the correct
result. JAWL's web helper also resolves its port/history files from the code
root instead of `JAWL_DATA_DIR`, which matters for multi-instance isolation.

## VoiceMem

Upstream/reference: [VoiceMem](https://github.com/xzf-thu/VoiceMem)

Relevant strengths:

- streaming dual-brain design;
- left/right memory separation;
- speculative retrieval while the user is speaking;
- external ASR partial-text integration;
- audio and affect context;
- voice/session memory.

Conclusion: use as a voice and sensory sidecar. Do not allow its right-brain
profile to become a second canonical personality.

Current integration finding: VoiceMem `0.2.3` exposes the useful lightweight
boundary `VoiceMem.stream().feed_partial(text, ended=...)`; partial text does
not require its audio models, and `ended=True` returns a completed `Turn` with
retrieved memory. Its bundled `web/run.py` is a demo WebSocket application,
not a stable sidecar protocol with request correlation. The companion should
therefore put a small loopback adapter/runner around this boundary and keep
VoiceMem in its own environment.

## Open-LLM-VTuber

Repository: [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)

Relevant code patterns:

- provider factories for ASR, TTS, VAD and LLM;
- FastAPI/WebSocket transport;
- sentence-level streaming;
- ordered parallel TTS queue;
- Live2D actions and expressions;
- pluggable Agent interface;
- interruption and audio lifecycle handling.

Important limitation: it is mainly an avatar/voice runtime, not the desired
long-lived cognitive core. Its current long-term memory story is not a reason
to replace JAWL.

## Warashi

Repository: [Warashi](https://github.com/inni918/warashi)

Relevant ideas:

- hard-capped core memory;
- FTS5 deep recall;
- per-character data separation;
- proactive topic pool;
- sleep/quiet mode;
- performance presets;
- first-run setup and character management;
- natural barge-in UX.

Conclusion: borrow product UX and bounded-memory behavior. JAWL's Vector +
Graph remains the richer archival layer.

## Miru

Repository: [Miru](https://github.com/kiyotakali/Miru)

Relevant ideas:

- separate AttentionEngine that creates `speak_intent`;
- salience, deduplication and cooldown;
- screen sensor with change detection;
- VLM significance scoring;
- focused presence instead of constant interruption;
- screenshot disposal after analysis;
- auditable Markdown memory;
- slot-based domains for people, projects, topics and self;
- SleepAgent and daily journal.

Conclusion: add an Attention/Presence layer next to JAWL Heartbeat, but keep
personality and durable state in JAWL.

## Mana

Repository: [Mana](https://github.com/Yuuzulight/Mana)

Relevant ideas:

- Windows local-first voice loop;
- model profiles and health/doctor checks;
- continuous listening with Silero VAD;
- gaming/resource backoff;
- Turn Arbiter with priority lanes and TTL;
- interruption categories: backchannel, correction, amend and new question;
- bounded memory tiers;
- explicit memory tool with patch/remove/archive;
- fact provenance, epistemic kind and valid-time history;
- one tool policy and audit log;
- secret redaction;
- explicit vision tool bridge;
- stale-file checks for edit proposals.

Conclusion: this is the strongest source for implementation safeguards and
Windows product behavior.

## AniCompanion

Repository: [AniCompanion](https://github.com/catsmice/AniCompanion)

The implementation targets macOS and Swift, so its code is not directly
portable to this Windows/Python project. Its useful patterns are:

- frontend as a face in front of a pluggable agent;
- streaming sentence parser;
- emotion tags separated from spoken text;
- ordered TTS playback;
- full-duplex acoustic echo cancellation;
- focused-window screen capture;
- explicit screen consent;
- amplitude-driven lip-sync;
- 3D expression fallback mapping.

Conclusion: borrow the frontend contracts and audio UX, not the platform
runtime. We use Live2D rather than its VRM renderer.

## Soul of Waifu

Repository: [Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu)

Relevant ideas previously inspected:

- psychology and relationship layers;
- episodic topic archive and diary;
- emotional decay;
- neurohormone-like state variables;
- desktop-agent tools and approvals;
- avatar HUD and state presentation.

Conclusion: design reference only for the current project. The repository is
GPL-3.0 and its character/avatar assets have separate terms.

The local `G:\AI\OmniVoice` checkout was also inspected: it contains only a
Python virtual environment, without source, checkpoints, inference entrypoint
or service API. No OmniVoice adapter is claimed until the actual project/model
location is supplied.

## Combined findings

## RAM-first multimodal proposal review — 2026-09-06

The pasted proposal is useful as a model-placement study, but it must not
change ownership boundaries. MiniCPM-o 4.5 is a credible future sensory/live
candidate: its official GGUF repository labels it any-to-any/full-duplex and
lists a Q4_K_M file of about 5.03 GB under Apache-2.0. The official project
also documents a llama.cpp-omni/WebRTC path. This is evidence to benchmark,
not evidence that our RTX 5080 build, Russian quality, interruption behavior,
or JAWL tool calling is already production-ready.

Keep the following decisions:

- JAWL remains the only personality, memory, task, heartbeat, and native-tool
  owner. MiniCPM-o, if adopted, is a sensory/interaction worker and cannot
  become a second agent or write canonical memory directly.
- Qwen3-ASR-0.6B remains the current selected ASR baseline. It already passed
  the real three-turn browser capture path on this machine. Whisper Turbo is a
  later A/B candidate, not an automatic replacement.
- Silero VAD is a good small CPU gate and streaming boundary. It complements
  the user's hardware/noise gate; it does not replace level calibration,
  echo cancellation, or barge-in tests.
- YAMNet is optional P2 audio-event classification. It is not required for
  speech conversation and should only run on a decimated audio branch when an
  event is salient. A 30-second bounded metadata clip and dedup/cooldown are
  preferable to continuous LLM calls.
- Whisper timestamps, ForcedAligner, diarization, and PySceneDetect are
  archive/enrichment tools. None belongs in the critical voice response path.
- Gemma E2B/E4B or another small summarizer may consolidate a bounded sensory
  ring buffer later, but consolidation must emit a typed observation to JAWL;
  it must not decide what becomes a fact or trait.

RAM-first placement is therefore: CPU RAM for VAD, ASR, ring buffers, queues,
and delayed enrichment; GPU1 only for an explicitly benchmarked optional
  vision/omni worker; GPU0 and the main LLM remain reserved by the host setup.
  Models can be memory-mapped or cold-loaded, but the acceptance budget must
  include page faults, warm-up, and VRAM/RAM pressure rather than counting file
  size as inference memory. Vision remains deferred as requested.

The proposal's "MiniCPM-o instead of Gemma" conclusion is not accepted as a
replacement for the current text brain. The useful next experiment is a
separate opt-in MiniCPM-o sensory benchmark against the existing typed
VoiceMem/audio boundaries, with no changes to the canonical JAWL profile until
latency, Russian audio, full-duplex interruption, and resource isolation pass.

The most important additions to the original plan are:

1. Attention must be a lightweight timing layer separate from deep JAWL
   reasoning.
2. Voice interruption needs semantic classification, not only VAD.
3. Memory needs lifecycle and provenance, not just append-only recall.
4. Every tool needs one policy, approval path and audit record.
5. Screen vision needs passive-sensor and explicit-tool paths.
6. Model health, fallbacks and resource profiles are product features.
7. The first avatar should remain 2D Live2D.

## License and asset notes

### MiniCPM-o 4.5 benchmark decision — 2026-09-06

The attached proposal is correct that the official repository does not publish
IQ1/IQ2 MiniCPM-o 4.5 files. The official GGUF set currently starts at Q4_0
and includes Q4_K_S, Q4_K_M, Q5_K_M, Q6_K and Q8_0. A locally produced IQ1/IQ2
file is an experiment, not a supported release artifact; it cannot replace the
runtime until it passes multimodal quality and startup tests.

The first controlled download is the official Q4_K_M language GGUF plus the
official vision, audio, TTS and token2wav sidecars. Q4_0 and Q5_K_M are the
comparison points; F16 is a conversion/calibration source only if disk and
RAM headroom remain sufficient. We do not download every quantization.

The intended memory topology is hybrid, not arbitrary per-layer paging:

- GPU1 is the isolated optional MiniCPM worker; GPU0 and the JAWL text path
  remain reserved. Device assignment is accepted only when `nvidia-smi`
  confirms it.
- Vision/projector and KV cache are candidates for GPU1. Audio, TTS and
  token2wav are candidates for CPU RAM unless measurements prove otherwise.
  GGUF weights may be memory-mapped; file size is not resident VRAM/RAM.
- `--gpu-layers`, split/offload settings and context size are benchmark
  parameters. Arbitrary dynamic layer swapping is excluded from real time:
  page faults can create stalls and destroy latency.
- The bundled llama.cpp executable is CPU-only. It can validate loading and
  vision behavior, but a CUDA-enabled llama.cpp-omni or supported PyTorch
  runtime is required for a 5080 VRAM result.

Acceptance compares identical prompts/assets across Q4_0, Q4_K_M and Q5_K_M:
load success, resident RAM, peak VRAM, image TTFT, generation rate, Russian
UI-grounding/OCR, audio/video startup, interruption behavior and repeatability.
MiniCPM remains an opt-in sensory worker; JAWL still owns persona, memory,
policy, tools and final action decisions. A benchmark result never changes the
production profile automatically.

JAWL and Open-LLM-VTuber use permissive code licenses in their repositories;
VoiceMem is Apache-2.0. Miru and Mana use Apache-2.0 code, with Mana's
artwork separately restricted. AniCompanion is MIT with third-party assets.
Warashi includes upstream and bundled terms. Soul of Waifu is GPL-3.0.

Do not copy avatar models, voices, backgrounds or sample characters merely
because they are present in a reference repository. Every asset needs its own
license check.
