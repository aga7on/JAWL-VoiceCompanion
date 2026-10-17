# Текущее состояние — 16 октября 2026

Ветка `dev/daily-companion-20261014`; dirty changes владельца сохранены.
Очередь: [TODO](../TODO.md). План: [DAILY_PLAN](DAILY_PLAN.md).
Приёмка: [DAILY_ACCEPTANCE](DAILY_ACCEPTANCE.md). Запуск: [DAILY_RUNBOOK](DAILY_RUNBOOK.md).

Сессия OpenCode `ses_ec36a8f41ffe6wjzIAbHN7DnXG` прочитана и продолжена в Codex.
OpenCode остановился на недельной квоте. Новый Codex tool goal зарегистрирован,
status=active: автономно выполнить доступную часть D1–D6. TODO ещё не завершён.

## Живой сенсорный прогон 17 октября 2026 (goal live-tests)

`scripts/live_sensory_run.py` захватил 2 дисплея + 6с системного аудио
(открытый YouTube), EG2-теги, детальное VLM-описание обоих экранов, точную
транскрипцию GigaAM/crispasr («...крашеными волосами зовёт капитана Кан...»),
спектрограммное описание звука и финальный RU-ответ 27B. Артефакты в
`runtime/live-sensory-run/` (report.json + txt + jpg + wav). Озвучка не
приложена: companion не поднят (heartbeat); TTS-часть остаётся открытой.

## Проверено

16Oct owned supervisor_status больше не вызывает native/cmdline fallback.
Atomic identity receipt живёт внутри native exclusive lock; PID marker и
process creation time должны совпадать.25 focused tests/38 subtests PASS.
[Новая supervised серия](../runtime/supervisor-identity-series-20261016.json):
Hikari20/20, cancel/reconnect, receipt actual PID/create_time/exact Job,
stopped registry и полный port/marker/identity receipt cleanup PASS.

17Oct Chameleon UI H1/D3: добавлены кнопки DND (`🔕`) и Click-through (`👻`)
в HUD-dock, hover-логика для временного разрешения кликов при click-through,
IPC `jawl-window-mode` расширен параметром `clickThrough` с
`setIgnoreMouseEvents`. Восстановлен `desktop/panel-preload.js` (был удалён
при H1, но необходим для Electron preload). Все 47 Node.js desktop-тестов
и 1040 Python-тестов проходят. 17Oct: `test_web.py` обновлён для нового
`app.html` (проверки `/app.js` вместо старого `frontend/index.html`).
18Oct Ambient pause/resume D4-01: pause/resume в SensoryIngestor; ResourceGovernor
в composition.py; DND button pauses ambient capture; paused status в сенсорах;
тесты sensory/web/e2e зелёные.
18Oct Screen observation D4-02: VisionLookService dedup/cooldown, ScreenDeltaWatcher
backoff, /api/vision/look, UIA context, perception fusion; тесты vision/presence/
screen_adapter/e2e зелёные.
18Oct System speech separation D4-03: ambient audio ingests system_audio; own TTS
filtered via playback suppression; TTS endpoints activate suppression with TTL;
source_app=system_audio; tests ambient_audio/web зелёные.
18Oct EmbeddingGemma 2 H4: audio-visual vibe fusion, latent VRM reflex, semantic
scene-change trigger, compact episodic vector memory, Russian eg2 linear reader
(`project`/`read`), PerceptionFusion.observe_eg2, optional composition
integration and bounded RollingMediaBuffer; tests eg2/perception fusion 16
passed. Live multimodal validation remains.
18Oct EmbeddingGemma 2 H4: audio-visual vibe fusion, latent VRM reflex, semantic
scene-change trigger, compact episodic vector memory, Russian eg2 reader,
PerceptionFusion.observe_eg2, optional composition integration and bounded
5-minute RollingMediaBuffer; tests eg2/perception fusion 16 passed. Live
multimodal validation remains.
18Oct H5 baseline expanded: game_embodied.py adds motor controller, voice combat
coordinator, strategy/mod planner, GameObservation, SimulatedGameInputBridge,
ModScaffold/ModScaffoldWriter, GameEmbodiedLayer orchestration; tests 17 passed.
Live game input, mod execution and auto-modding remain open.
18Oct Remaining TODO engineering pass: D4-04 attention/proactive tests 13 passed;
D4-05 streaming capture/voice capture tests 31 passed; D5-03 hostos policy/web
tests 19 passed; D6-03 main pytest 1028 passed + 281 subtests, desktop node 95
passed, e2e 18 passed in batches/single runs. H1-H4 have implementation and tests;
H5 has no implementation. Live physical/mic/8h acceptance remains open.

18Oct Chameleon UI D3: добавлено сохранение/восстановление позиции окна и
режима `compact` в Electron userData (`jawl-window-state.json`). Multi-monitor
валидация позиции при восстановлении. Глобальный хоткей `Ctrl+Shift+G` для
выхода из click-through. Все 47 Node.js desktop-тестов проходят.

18Oct D3-01/D3-02/D3-03 все помечены как выполненные: единое окно
«Хамелеон» с compact/studio режимами, HUD-dock с DND/Click-through/Ghost,
VRM позы idle/listen/think/speak/working, липсинк aa/oh/ee,
сохранение позиции окна. Все 47 Node.js + 1040 Python тестов PASS.

D5 agent-work [r5](../runtime/owned-agent-work-20261016-r5.json) подтвердил
шесть сценариев: file/read/SHA, browser open, form save с одним POST и свежим
native read, remember → revise → restart → содержательный recall. Последний
sandbox отказ вызвал15 повторов. Owned hook теперь наблюдает исключение
самой native authority, завершает correlated request и блокирует последующие
batch calls. [Живой policy сценарий](../runtime/native-policy-refusal-20261016-r1.json)
PASS: одна попытка, один явный error, вне sandbox файла нет, cleanup PASS.
Полный D5 остаётся OPEN: r6 исчерпал output budget на внутреннем поле,
r7 пропустил запрошенное повторное чтение. Все FAIL сохранены в history.
Local wrapper согласует native context budget с actual64k server (dynamic48000
chars); memory_key разрешён как штатный optional аргумент. Для обычных
Companion turns внутренние поля ограничены320 chars каждое; active native
Goals сохраняют reasoning budget. Discovery/tools/Goal v2 не урезаны.

Новый exact Job/creation-time resource sampler не читает cmdline/cwd.

## 17 октября 2026 — eg2-транскрибер: словарь EN, перевод мозгом (решение владельца)

- Владелец решил: EG2-транскрипт может быть английским; 27B-мозг переводит в
  RU перед озвучкой (reasoning тоже может быть EN). Стартовый словарь
  `Eg2Transcriber` переключён на EN (плотность EG2-пространства выше), RU-слой
  остаётся опцией через `vocab`/`vocab_path`. Тесты 6 PASS.

## 17 октября 2026 — eg2-транскрибер (аудио→слова по методу eg2.haku.sh)

- Новый `src/jawl_voicecompanion/eg2_transcribe.py`: `Eg2Transcriber` —
  слайсовый zero-decoder ASR поверх EG2 cortex (линейный reader + словарь RU,
  ridge-fit на выровненных парах, кэш эмбеддингов словаря, эвристическая
  пунктуация). `tests/test_eg2_transcribe.py` — 6 PASS (без ONNX, FakeCortex).

## Проверка 17 октября 2026 (продолжение сессии) — EG2 полная сенсорика: зрение + звук

- Добавлено описание звуков/музыки/настроения/этикета co-watching через EG2
  (`classify_audio_wav`, `vibe_fusion`) в `describe_displays` и
  `PerceptionFusion.observe_displays`.
- Endpoint `/api/vision/describe-displays` и hostos-инструмент принимают
  `audio_wav_base64` и возвращают объединённое описание.
- Тесты web/perception/eg2/screen/hostos — 118 PASS.

## Проверка 17 октября 2026 (продолжение сессии) — EG2 двухэкранная сенсорика + агентный инструмент

- Добавлен hostos-инструмент `screen.describe_displays` и wiring через
  `hostos_executor.display_describer` (composition), чтобы JAWL мог описывать
  оба дисплея через EG2.
- Endpoint `/api/vision/describe-displays` возвращает описание и сохраняет его
  в `perception_fusion`.
- Тесты: web/perception/eg2/screen/hostos — 118 PASS.

## Проверка 17 октября 2026 (продолжение сессии) — EG2 двухэкранная сенсорика + API

- Добавлен `VisionLookService.describe_displays(...)` и endpoint
  `/api/vision/describe-displays`: захватывает все дисплеи, описывает через EG2,
  сохраняет результат в `perception_fusion`.
- `VisionLookService` теперь получает `perception_fusion` в composition.
- Кодовые ворота зелёные.

## Проверка 17 октября 2026 (продолжение сессии) — EG2 двухэкранная сенсорика

- Добавлен `ScreenCaptureAdapter.capture_displays(max_displays=...)`: bounded
  захват до 4 мониторов через `EnumDisplayMonitors`, без raw-архива.
- Добавлены `EmbeddingGemmaSensoryCortex.classify_displays` и
  `describe_displays`: zero-decoder описание каждого дисплея.
- Добавлен `PerceptionFusion.observe_displays(...)` для слияния двух (и более)
  дисплеев + системного аудио в единое наблюдение.
- Тесты: `test_eg2_sensory`, `test_perception_fusion`, `test_screen_adapter`
  — 29 PASS. CodeSee validator PASS.

## Проверка 17 октября 2026 (продолжение сессии)

- Прочитана сессия OpenCode `ses_ec36a8f41ffe6wjzIAbHN7DnXG` (563 сообщения) и
  зафиксированы решения/идеи в `docs/HARMONIZED_ARCHITECTURE_AND_ROADMAP.md`.
- Python-тесты: perception/sensory/ambient/screen/attention/vision/web — 137 + 75 PASS;
  desktop Node-тесты: 100 PASS; CodeSee validator: PASS (только предупреждения
  о длине имён шагов).
- `python -m compileall src` — без ошибок.
- База стабильна, следующий автономный срез — live acceptance D4/D5/D6 и
  (при необходимости) дальнейшая дефрагментация UI (H1).
[Native soak smoke](../runtime/native-owned-soak-smoke-20261016-r1.json):180с
PASS, Goal write/read, controlled provider loss → один error → recovery,
lease revoked и полный cleanup. Новый journal proof включает свежий read
другого plan только внутри того же native ReAct trace.
[Первый8h soak остановлен с FAIL](../runtime/native-owned-soak-8h-20261016-r1.json):
63.6мин,12 Goal cycles PASS;13-й объявил done без действий. Native guard
отверг ложное completion и перевёл Goal в blocked. Controlled provider
fault/recovery ранее PASS; lease revoked, sampler stopped, Jobs/ports cleanup
PASS.8h не пройден. Разбирается bounded protocol repair для этого случая;
сам completion guard/полномочия остаются native. [Исходный code baseline](../runtime/gateway-series-5eaa9d15dfe9/owned-code-baseline.json)
и [завершённый checkpoint](../runtime/gateway-series-5eaa9d15dfe9/soak-checkpoint.json)
сохранены, код не менялся во время прогона.
Major gate текущего runtime PASS:932 unittest/66 pytest/16 HTTP/109 Node
и оба browser harnesses. [Connected voice20](../runtime/owned-voice-series-20261016-r2.json)
PASS: real GigaAM/Hikari/OmniVoice, /app,20 streaming drafts, full non-silent
playback и body EOF, exact browser Job/stack cleanup. Три WAV по кругу;

## Новые модули OpenCode (15–16Oct)

- **`src/jawl_voicecompanion/duplex_cascade.py`**: VAD-free микро-ходовый контроллер
  очерёдности речи (6 спецтокенов `DuplexCascade`: `<|user is talking|>`,
  `<|user is thinking|>`, `<|user backchannel|>`, `<|user interruption|>`,
  `<|user finish talking|>`, `<|no voice|>`) с RU словарями backchannel/interruption/
  thinking trailers и опциональным `EmbeddingGemmaTurnScorer` (ONNX CPU, ~13 мс).
- **`src/jawl_voicecompanion/eg2_sensory.py`**: `EmbeddingGemmaSensoryCortex` —
  Zero-Decoder классификация экрана (vision_encoder_q4) и аудио (audio_encoder_q4)
  через предвычисленные RAM-банки концептов; детектор смены сцены `cos_sim`
  (threshold 0.88) и рефлекс-эмоции VRM.
- **Live-замеры (15Oct)**: `runtime/eg2-text-probe.json` (13.4–15.7 мс на RU-текст);
  `runtime/live-eg2-multimodal-test6.json` (70.1 мс audio-эмбеддер, 155.8 мс vision,
  13.4 мс text-классификация по предвычисленной матрице, top-1 intent casual_chat 0.86,
  top-1 audio human_speech_ru 0.69, top-1 vision 3d_anime_avatar_ui 0.71).
- **Live-замеры voice (15–16Oct)**: `runtime/live-fifine-turn-e2e.json` (endpoint→
  first sound 240.5 мс, GigaAM 207.8 мс); `runtime/live-fifine-bargein-eg2.json`
  (ASR 156.9 мс, first sound 169.6 мс, EG2 intent ranking 106.6 мс на 6 текстов).

## Новые модули OpenCode (15–16Oct)

- **`src/jawl_voicecompanion/duplex_cascade.py`**: VAD-free микро-ходовый контроллер
  очерёдности речи (6 спецтокенов `DuplexCascade`: `<|user is talking|>`,
  `<|user is thinking|>`, `<|user backchannel|>`, `<|user interruption|>`,
  `<|user finish talking|>`, `<|no voice|>`) с RU словарями backchannel/interruption/
  thinking trailers и опциональным `EmbeddingGemmaTurnScorer` (ONNX CPU, ~13 мс).
- **`src/jawl_voicecompanion/eg2_sensory.py`**: `EmbeddingGemmaSensoryCortex` —
  Zero-Decoder классификация экрана (vision_encoder_q4) и аудио (audio_encoder_q4)
  через предвычисленные RAM-банки концептов; детектор смены сцены `cos_sim`
  (threshold 0.88) и рефлекс-эмоции VRM.
- **Live-замеры (15Oct)**: `runtime/eg2-text-probe.json` (13.4–15.7 мс на RU-текст);
  `runtime/live-eg2-multimodal-test6.json` (70.1 мс audio-эмбеддер, 155.8 мс vision,
  13.4 мс text-классификация по предвычисленной матрице, top-1 intent casual_chat 0.86,
  top-1 audio human_speech_ru 0.69, top-1 vision 3d_anime_avatar_ui 0.71).
- **Live-замеры voice (15–16Oct)**: `runtime/live-fifine-turn-e2e.json` (endpoint→
  first sound 240.5 мс, GigaAM 207.8 мс); `runtime/live-fifine-bargein-eg2.json`
  (ASR 156.9 мс, first sound 169.6 мс, EG2 intent ranking 106.6 мс на 6 текстов).
physical mic/audibility не проверялись. Первый запуск остановился до ASR
из-за Edge discovery: стандартные Windows discovery variables восстановлены.
[Метрики sample20](../runtime/owned-voice-latency-20261016.json): dispatch→first
WebAudio p50=8.338с,p95=11.964с,min=6.377с,max=13.286с. Это browser proxy,
не physical speech-end; first turn отдельно, остальные19 не20 warm sample.

- Последний major full gate PASS после native work/policy исправлений:
  [receipt](../runtime/full-gate-native-work-soak-20261016.json),
  [log](../runtime/full-gate-native-work-soak-20261016.log).
  932 unittest/66 pytest/16 HTTP/109 Node и оба browser harnesses PASS.
  Последующее добавление queue projections в harness:12 focused PASS.
  Supervisor identity gate912 сохранён отдельно.
  Pinned snapshot348 файлов, SHA256 `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.
  Предыдущий voice/process gate сохранён в `runtime/full-gate-resume-final-20261015.json`.
- [Owned console/bootstrap](../runtime/resume-owned-console-20261015.json) PASS:
  actual owned launcher, exact Windows Job proof, auth401, cancel-before-turn200,
  tombstone409, listener gone; отдельный brain bootstrap exit0/hook init marker.
- [Ordinary real-model voice после новых hooks](../runtime/brain-gateway-voice-e2e-20261015.json)
  PASS:3/3 synthetic WAV → actual `/app` → GigaAM → Hikari JAWL → OmniVoice.
  Streaming draft3/3, EOF и полный non-silent WebAudio playback. Physical mic
  и аппаратная слышимость не проверялись. [Wrapper](../runtime/brain-gateway-voice-wrapper-20261015.json)
  и [cleanup](../runtime/brain-gateway-voice-cleanup-20261015.json) PASS; стек остановлен.
- [Supervised Hikari startup](../runtime/resume-supervised-local-20261015.json)
  PASS: production readiness без heartbeat timeout, тестовые порты/registry/
  profile очищены. Более новая identity/turn серия приведена ниже.
- [Native text checkpoint](../runtime/owned-gateway-checkpoint-20261015.json)
  PASS: ordinary20/20 и supervised20/20 на Hikari через native HTTP/SSE;
  cancel/reconnect без пропусков, ровно один terminal event на каждый ход.
  Ordinary provider loss → один turn.error → provider restart → успешный ответ.
  Actual brain PID/create_time/core hooks/pinned SHA проверены в exact Job в
  обоих integrated путях. Порты модели/консоли/Companion и supervisor markers
  очищены; supervised desired_state=stopped. Это не mic/TTS20-turn приёмка.
- [Native recovery](../runtime/resume-native-recovery-20261015-attempt2.json)
  PASS на cheap child: ROOT lease разрешает restart, revoke запрещает следующий,
  третьего child нет, cleanup PASS. Это lifecycle, не8h soak модели.
- [Synthetic desktop browser](../runtime/resume-desktop-voice-e2e-20261015.json)
  PASS: actual WebAudio/NDJSON, scoped cancel, stale-drop, без cross-turn overlap;
  brain/ASR/TTS в этом отдельном harness — fixtures.

## Исправлено

- Desktop smart-barge-in был выключен незаданным флагом; RU word boundaries
  не работали. Теперь onset начинает observation; explicit interruption или
  содержательный draft отменяет только наблюдавшийся playback owner.
  Fallback считает550ms voiced PCM, не время после короткого шума.
- Поддакивание подтверждается canonical ASR после обычного flush/смены session
  и reset scoped partials. `suppress_backchannel=true` подавляет только явный
  короткий ack, без нового brain turn/memory event. Старые буферы не продолжаются.
  Незавершённый RU хвост удерживает endpoint>=2200ms; явная пунктуация допускает380ms.
  Это bounded heuristic, не trained DuplexCascade и не acoustic full duplex.
- Job active=0 мог опережать signaled descendant handles:
  [50/50 ранних возвратов до фикса](../runtime/resume-job-drain-probe-20261015-before.json).
  Теперь handles сохраняются после exact Job membership check до terminate;
  reap ждёт signals плюс active=0, fault сохраняет identities для retry.
  [После фикса0/50](../runtime/resume-job-drain-probe-20261015.json),39 focused
  process tests PASS. WAV cleanup/replacement worker происходят после reap.
- Исправлены import order test-helper supervisor и generation-marker readiness
  recovery harness. Voice launcher передаёт `--ui app`; URL guard сохранён.

## Скорость и следующий срез

Brain отказывает без изолированных paths до native import и пишет bounded
atomic startup receipt. Local wire grammar ограничивает внешний JSON object
без второго SDK wrapper; native parser/discovery/аргументы/Goal v2 полные.
Delivery guard подавляет повтор terminal до history/SSE; failed emit допускает
retry. Harness отличает replay history от submitted turns и отклоняет два
terminal event одного turn_id. Native lock marker удаляется только после
exact Job drain и совпадения captured dead PID; foreign/live marker сохраняется.

Native HTTP dispatch→terminal, sample20 на режим: ordinary p50=3.596с,
p95=4.608с/max=7.037с; supervised p50=3.584с,p95=6.939с/max=7.459с.
Это без ASR/TTS. В каждом retained profile был один protocol-error tick;
native repair завершился ответом. Ordinary real batch содержал несколько
terminal actions, но журнал/история получили одну доставку.
Источники: [ordinary r5](../runtime/owned-gateway-series-20261015-r5.json),
[supervised r6](../runtime/owned-gateway-series-20261015-r6.json).
Неудачные r1–r4 и r5 cleanup FAIL сохранены; r4 PASS старого harness не является
приёмкой отсутствия duplicate finals. Подробности в checkpoint history.

[Новые метрики без thoughts](../runtime/brain-gateway-voice-latency-20261015.json):
voice/end HTTP dispatch→первый WebAudio start≈10.272/9.466/11.373с.
Это endpoint proxy из rounded browser timings, не физический конец речи.
Обычные LLM steps2.8–4.8с; две фразы потребовали memory/reader tool и второго
шага. После voice/end response до звука ещё1.25–2.54с. Sample3 не даёт p50/p95.
Цель обычного тёплого разговора1–3с не достигнута.

Native terminal skill уже выставляет terminate_loop для correlated companion
turn. В новых трёх traces нет лишнего completion LLM после terminal.
Две voice фразы вызвали native memory/reader tools; plain-chat20 принят отдельно.
Нужна оптимизация стадий, а не дублирующий
fast-exit. Далее:20 connected voice ходов, stage timings, снижение p95.

Прежние169–240ms из OpenCode получены с заданным/эхо-ответом, не полным JAWL.
EG2 timings не доказывают распознавание музыки или замену VLM/ASR; в test6 vision
разрыв top2 всего0.0021. H3/H4 остаются research.

[Разбор стадий Voice20](research/VOICE_LATENCY_CHECKPOINTS_20261016.md):
22 LLM calls на20 ходов; per-turn LLM total p50=6.226с, native other0.189с,
HTTP residual0.384с, response→audio1.088с. Prefill/decode отдельно не измерены.
Cached tokens8017 на всех22 calls при median prompt14641. Actual server
checkpoint spacing8192 подтверждён help;1024 — гипотеза для benchmark после
soak, не включённое исправление. Native context/discovery остаётся полным. В изолированном worktree готов
[opt-in cache CLI candidate](../runtime/d2-cache-candidate-20261016.json):
13 focused/4 subtests и CodeSee validator PASS. Main runtime не изменён;
перенос зависит от реального latency/RSS benchmark после текущего soak.
[Расширенный A/B/B/A измеритель](../runtime/d2-cache-benchmark-preparation-20261016.json)
готов в этом worktree:30 focused/54 subtests, actual native bootstrap и
CodeSee validator PASS. Server numeric timings прошли actual native SDK/
provider/executor fixture probe без модели. Первый benchmark attempt
остановился до warm20: в worktree отсутствовал public embedding asset;
asset скопирован с SHA check, следующий запуск подготовлен. Latency result
пока отсутствует; main performance config остаётся прежним.

## Открытая приёмка

- D1:20 connected voice ходов приняты на synthetic WAV; connected voice
  provider-error/recovery ещё OPEN, native text20 обоих режимов принят отдельно.
  D2:latency1–3с, physical Fifine/echo,
  тихая речь/паузы, сохранение задач при Stop/provider failure.
- D3:owner/multi-monitor/click-through. Compact/studio и VRM foundation есть;
  synthetic window toggle не заменяет эти проверки.
- D4:явно выбранные screen/system-audio sources, свежий bounded context,
  provenance/TTL/pause и уместная инициатива через общий JAWL Heartbeat.
- D5:полная стабильная серия поручений/отказ/Stop. Memory correction → restart
  → recall и три поручения прошли в r5, но поздние серии выявили planning/JSON
  failures; tasks через Stop/provider fault ещё не приняты.
- D6:разговор30–60мин;8h native soak FAIL после63.6мин, Goal13 false done
  был отвергнут. Cleanup PASS, требуется исправление и новый полный прогон.
  Новый owned suite использует exact Job/creation identity sampler; старый
  standalone sampler по cwd/cmdline не используется для приёмки.180с smoke
  не заменяет8h и не проверяет физический разговор. Прямые API memory/file writes в старых daily harnesses
  не принимаются за три LLM поручения и содержательный recall после restart.
  H1–H5 сохранены в [roadmap](HARMONIZED_ARCHITECTURE_AND_ROADMAP.md).

## Решения и история

Effective manifest: Hikari Bonsai-2 GPU1, GigaAM/crispasr CPU, OmniVoice9890
по умолчанию; Tera9889 выбираемый. Модели/аватар/owner config не менялись.
GPU0 не занимать скрытно; pinned/native upstream read-only. Capture после
выбора источников/разрешений; постоянного raw audio/video архива нет.

Прежний STATE сохранён byte-for-byte:
[STATE-before-resume](history/2026-10-15-opencode-resume/STATE-before-resume.md).
Промежуточные записи:
[STATE-checkpoints](history/2026-10-15-opencode-resume/STATE-checkpoints.md).
История14Oct: [архив](history/2026-10-14-daily-reset/INDEX.md).
Исторический R6 terminal FAIL не отменяется успешными новыми прогонами.
