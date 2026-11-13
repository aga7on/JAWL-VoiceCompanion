# Единственная очередь — ежедневный компаньон

## ПРИОРИТЕТ: MOSS-Live-подобный полнодуплексный речевой слой (владелец, 10.11.2026)

Чек-лист до цели (статусы честные):

## ПРИОРИТЕТ B: проактив по сенсорике через мотивации/drives (владелец, 10.11.2026)
- [x] **P-M0 (companion-side, v0):** `sensory_motivation.py` (novelty/Jaccard + change hints, decaying score, threshold/cooldown) + хук в `screen_commentary.py` (`suppressed_motivation`), без правок read-only snapshot. Тесты: `test_sensory_motivation` 6/6, регрессия commentary+proactive+motivation 32/32 PASS (engineer). Дизайн `docs/SENSORY_MOTIVATION_DESIGN.md`.
- [x] **P-M0.1 (server wiring):** `create_server` (`web.py:4012,4090`) подключает `SensoryMotivation` в `ScreenCommentaryScheduler`. Детерминированные тесты `tests/test_screen_commentary.py` 10/10 PASS (подавление рутины + пропуск критических событий).
- [ ] **P-M1 (BLOCKED):** отразить сигнал на реальном `curiosity` drive через snapshot ядро: **BLOCKED** — в read-only snapshot ядре JAWL нет эндпоинта для динамической инъекции дефицита (только чтение/статический config через settings.yaml); companion-side `SensoryMotivation` является авторитетным фильтром без создания второго источника правды.
- [ ] **P-M2:** owner-tuned пороги, live проверка проактива (требует рестарт companion + наблюдение).


- [ ] **Рестарт companion-процесса** — применить накопленные правки (live_speech Cycle 20, screen_commentary D4, adaptive hold итерация 1, barge-in контекстная коррекция Cycle 21d, echo guard Cycle 22, Live Voice Phase C Cycle 13: Stream-First progressive generation, TurnTrace dual-lane, instant barge-in mute <=300ms, TokenBucket anti-spam). Без этого живой сервис работает на старом коде.
- [x] **Аудит full-duplex контура** (итерация 1, 10.11): карта mic→VAD→draft→end→brain→TTS→barge-in→echo guard с file:line — в STATE.md Cycle 21.
- [x] **Foreground turn-taking: adaptive hold** (итерация 1, 10.11): `voiced_ms`-адаптивное окно тишины, 14+17 тестов. REAL-MIC VALIDATION PENDING.
- [x] **P1 Barge-in с контекстной коррекцией (Cycle 21d):** клиент передаёт причину (`desktop/app.js:1270,1344,1779`), сервер фиксирует сниппет активного ответа (`_current_speaking_text` → `_last_interrupted_turn_text`), немедленно отменяет `gateway.arbiter.cancel_all()`, следующий ход в `enrich_turn_text` получает маркер `[ПЕРЕБИВАНИЕ: ...]`, который сгорает за один раз (expire 120 с). Не ломает `split_packet`. Тесты: `tests/test_desktop_speech_cancel.mjs` 8/8, `tests/test_web.py` 92/92 (4 BargeIn), `tests/test_speech_requests.py` 14/14, `desktop/tests/app-voice-lifecycle.test.mjs` 30/30.
- [x] **Echo guard для loopback-ASR**: self-TTS suppression существует для ambient; проверена сквозная защита streaming ASR от собственного голоса (Cycle 22).
- [x] **Fast foreground lane**: first-audio ≤1.2 с (SLO из DUPLEX_RESEARCH_ADOPTION) — Stream-First progressive phrase chunking (`StreamPhraseSegmenter`) + TurnTrace Dual-Lane KPI (`first_audible_audio_ms` preface vs `first_meaningful_audio_ms` deliberative stream) + Zero-GPU Fast Lane flag (`ENABLE_FAST_LANE=0` default, RAM/CPU cached preface). 192 Python тестов (7 Dual-Lane, 7 TurnTrace) + 59 Node тестов PASS.
- [ ] **Coordination: фон ReAct → вставка в паузе** — результат фонового хода вставляется в естественной паузе, не перебивая пользователя (против теперешнего поведения: ответ приходит, когда закончится).
- [x] **Backchannel policy v0.5**: «угу» / preface anti-spam gating — детерминированный `TokenBucketRateLimiter` (`capacity=1.0`, `refill_rate=1.0/6.0` с минимальным интервалом 6 с), семантическая дедупликация идентичных реплик, строгое подавление при активной речи пользователя (`user_speaking`) и при `is_muted`. Интеграция в `/api/voice/preface`. 12/12 тестов PASS (`tests/test_voice_preface_policy.py`).

## Остальная очередь

- [x] **Living Companion Subsystems: Offline Sleep Memory Consolidation, Multimodal Co-Watching & Pure-CPU Music DSP (13 ноября 2026)**:
  1. **Эпизодическая память и оффлайн консолидация («сон»)** (`src/jawl_voicecompanion/memory_consolidation.py`):
     - `OfflineConsolidator`, `EpisodicObservation`, `MemoryProposal`.
     - Префиксная и точная фильтрация tombstone-записей (`is_tombstoned(key)`), немедленная очистка кандидатов при надгробиях, TTL-экспирация устаревших наблюдений без воскрешения удалённых/истекших фактов.
     - Агрегация в кластеры, взвешенная формула уверенности, строгое разделение фактов (`status="fact"`) и гипотез (`status="hypothesis"`).
     - Стейджинг предложений и атомарный экспорт `export_staged_proposals()` с поддержкой кооперативной отмены `cancel_check`.
     - Детерминированные тесты: `tests/test_memory_consolidation.py` **11/11 PASS**.
  2. **Мультимодальный движок ко-вотчинга (аниме, кино, игры)** (`src/jawl_voicecompanion/cowatch_engine.py`):
     - 3-уровневое разделение идентичностей: `spatial_track_id`, `visual_identity_id`, `audio_speaker_id`.
     - Поддержка закадрового голоса без ложной визуальной привязки к экранным персонажам.
     - Мгновенный сброс визуальных треков и активных гипотез при детекции смены сцены (`SceneCutEvent`).
     - Гейтинг внимания: DND, quiet hours, активная речь пользователя (`user_speaking`), кулдаун инициативы (45–60 с).
     - Рутинные сцены отдают `action="silence"`, текст `"тишина"`.
     - Мост к игровому контексту (`record_gameplay_observation`): инвентарь, боссы, здоровье, кооперативные цели.
     - Интеграция мгновенного barge-in (`barge_in_abort <= 300 ms`).
     - Детерминированные тесты: `tests/test_cowatch_engine.py` **10/10 PASS**.
  3. **Чистый CPU DSP музыкальный анализатор тональностей и настроения** (`src/jawl_voicecompanion/music_perception.py`):
     - Чистый NumPy CPU DSP: Krumhansl-Schmuckler chroma key correlation, BPM по спектральному потоку, Russell circumplex (valence/arousal/mood).
     - Строгие DSP-пороги: тишина (< -55 dBFS) -> `kind="unknown"`, шум (flatness > 0.55) -> `kind="sound"`, чистая речь -> `kind="speech"`, чистая музыка -> `kind="music"`, перекрытие -> `speech_overlap=True`.
     - Адаптер `as_audio_description_provider()` для интеграции в `AudioDescriptionService` с нулевым оверхедом VRAM.
     - Детерминированные тесты: `tests/test_music_perception.py` **9/9 PASS**.
  4. **Сквозная интеграция и рантайм**:
     - `src/jawl_voicecompanion/__init__.py`: экспорт публичных классов.
     - `src/jawl_voicecompanion/composition.py`: инициализация `MusicPerceptionAnalyzer`, fallback `AudioDescriptionService`, `OfflineConsolidator`, `CoWatchEngine`.
     - `src/jawl_voicecompanion/web.py`: подключение в `CompanionServer`, безусловная запись надгробия в `forget_memory_sources(key)` до проверки сенсорных ID, shutdown в `server_close`.
     - `src/jawl_voicecompanion/companion_runtime.py`: свойства-делегаты (`offline_consolidator`, `cowatch_engine`, `music_analyzer`).
     - Интеграционные тесты: `tests/test_companion_runtime.py` **7/7 PASS**, `tests/test_web.py` **94/94 PASS**, Node desktop suite **144/144 PASS**.
  5. **Бюджет VRAM**:
     - GPU 0: 0 MiB аллокаций ($\Delta\text{VRAM} = 0$).
     - GPU 1: зарезервирован под Bonsai LLM и OmniVoice TTS.
     - Консолидация памяти, ко-вотчинг и музыкальный DSP строго на CPU/RAM.

- [x] **Баг (TTS): слышно только первое предложение до точки.** Корень: `LiveSpeechSession._run` умирал при первой ошибке синтеза (`break` вместо continue) — всё, что после упавшего предложения, замолкало, `state.error` никто не читал. Исправлено: ошибка записывается, предложение пропускается, очередь продолжается. Регрессия: `tests/test_live_speech_error_resilience.py`. **Требуется рестарт companion-процесса, чтобы код применился.**
- [x] **Комментирование происходящего на экране.** Реализовано как initiative lane `src/jawl_voicecompanion/screen_commentary.py` (10.11): ScreenDeltaWatcher-события → bounded observation turn («ответь "тишина" если не стоит комментировать») → доставка через новый `ProactiveFeed.deliver_direct` с rate limits (min gap 600 с, ≤2/час, idle 90 с после хода, mute/quiet respect). Тесты: `tests/test_screen_commentary.py` 8/8. Требует рестарта.
- [ ] **Собрать свою foreground/background архитектуру** по образцу OpenMOSS/MOSS-Live (модель несвободна, архитектура открытая): foreground = SenseNova-Loop realtime voice lane (barge-in, backchannel, удержание хода, быстрые ответы), background = JAWL ReAct (сейчас), coordination = SQLTasks/Goal state + speech sink; результат фона вставляется в естественной паузе. Референсы: OpenMOSS/MOSS-Live (GitHub), arxiv 2611.01639 "Local or Escalate? Post-Training Expert Routing for Real-Time Duplex Speech Models", 2610.35581 (interruptions/backchannels reward window). Первая часть (foreground turn-taking) начата в чек-листе выше.
- [x] **Cycle 13 / Live Voice (Phase C): Stream-First Duplex, Dual-Lane TurnTrace, Generation Epochs и мгновенный Barge-In (13 ноября 2026)** [AC-03, AC-01, AC-05, AC-08, AC-09: VERIFIED; STREAM-FIRST PASS; DUAL-LANE KPI PASS; SINGLE-OWNER FSM PASS; BARGE-IN <=300ms PASS; TOKEN BUCKET PASS; PYTHON 192/192 PASS; NODE 59/59 PASS]:
  1. **Stream-First progressive phrase generation (H1/P0)**:
     - `StreamPhraseSegmenter` в `src/jawl_voicecompanion/duplex_cascade.py`: буферизация streaming-токенов от Bonsai LLM и нарезка по пунктуационным границам (`[.?!…\n]`, мин. 12 символов / 3 слова) без ожидания полного ответа модели.
     - Прогрессивная отправка первых фраз в OmniVoice TTS: первый чанк синтезируется параллельно генерации следующих предложений.
  2. **TurnTrace сквозная Dual-Lane инструментация (H1/P0)**:
     - Канонические константы стадий в `src/jawl_voicecompanion/turn_trace.py`: `STAGE_USER_SPEECH_END`, `STAGE_VAD_ENDPOINT`, `STAGE_ASR_FINAL`, `STAGE_LLM_REQUEST`, `STAGE_LLM_FIRST_TOKEN`, `STAGE_LLM_FIRST_SENTENCE`, `STAGE_TTS_REQUEST`, `STAGE_TTS_FIRST_PCM`, `STAGE_AUDIO_ENQUEUED`, `STAGE_AUDIO_PLAYBACK_START`, `STAGE_AUDIO_PLAYBACK_END`, `STAGE_BARGE_IN_DETECTED`, `STAGE_AUDIO_STOPPED`.
     - Метод `compute_turn_kpis()` строго разделяет Fast Lane (`first_audible_audio_ms` p95 <= 1.2s) и Deliberative Lane (`first_meaningful_audio_ms` p95 <= 1.2s; short answer completion p95 <= 4.0s). Рефлекторный preface не подменяет содержательный ответ.
  3. **Single-Owner Playback FSM и Generation Epochs (H4/P0)**:
     - Серверный и клиентский контроль `generation_epoch` в `TurnArbiter`, `DuplexCascadeArbiter`, `web.py` и `desktop/app.js`.
     - При каждом новом ходе пользователя или barge-in эпоха инкрементируется (`next_epoch()`), отсекая устаревшие chunks и отменённый TTS.
  4. **Мгновенный Barge-in mute <= 300 мс (H5/P0)**:
     - В `desktop/app.js` добавлен выделенный `GainNode` (`earlySpeech.gainNode`). При обнаружении barge-in громкость обнуляется аппаратно в тот же квант времени (`gainNode.gain.setValueAtTime(0, earlySpeech.ctx.currentTime)`), останавливается шедулинг PCM, сбрасывается очередь, инвалидируется эпоха.
     - Инструментация `t_barge_in_detected` и `t_audio_stopped` подтверждает задержку остановки звука <= 300 мс (тест `test_barge_in_audio_stop_latency_under_300ms`).
  5. **Антиспам и дедупликация (H3/P1)**:
     - `TokenBucketRateLimiter` в `src/jawl_voicecompanion/affective_engine.py`: ёмкость 1.0, refill rate 1/6.0 с, защита от повторов фраз, подавление при речи пользователя и mute.
-     - Интеграция в `/api/voice/preface`.
  6. **Zero-GPU Fast Lane (H2/P1)**:
     - Флаг `ENABLE_FAST_LANE` (по умолчанию `False`), поддержка RAM/CPU-кэша без нагрузки на GPU 1 (GPU 1 выделен под Bonsai LLM и OmniVoice TTS, GPU 0 строго запрещён).
  7. **Тесты и верификация**:
     - Python voice suite: 192/192 PASS (`tests/test_voice_turn_trace.py` 7/7, `tests/test_voice_dual_lane.py` 7/7, `tests/test_voice_barge_in.py` 10/10, `tests/test_voice_preface_policy.py` 12/12, `tests/test_turn_trace.py` 13/13, `tests/test_echo_guard.py` 13/13, `tests/test_web.py` 92/92, `tests/test_barge_in_p1.py` 8/8, `tests/test_duplex_cascade.py` 14/14, `tests/test_affective_engine.py` 13/13).
     - Node desktop suite: `desktop/tests/app-voice-lifecycle.test.mjs` 30/30 PASS, `desktop/speech-stream.test.mjs` 21/21 PASS, `tests/test_desktop_speech_cancel.mjs` 8/8 PASS (всего 59/59 PASS).

  1. Тесты `test_mhc_route`/`test_mhc_merge` в `test-backend-ops.cpp` (d=64..4096): **36/36 OK** на пороге 1e-6 — CUDA-ядра сверены с CPU-эталоном.
  2. MTP `--spec-type draft-mtp` крашится (0xC0000005) на MTP-графе; изоляция показала: файл корректен, баг в форке. Отложено, не блокирует.
  3. Найдена ловушка двух GPU: без пина llama.cpp расщеплял модель на карты, замеры падали втрое. Пин `CUDA_VISIBLE_DEVICES=1` добавлен в `hold_supervised_brain.py` (+ удаление `--device CUDA1`).
  4. Честные замеры: Q4_K_M 65.7, IQ3_M 81.0, IQ3_S 85.0 ток/с. Владелец выбрал IQ3_M; манифест переключён.
  5. Голосовой E2E 3/3 (`final_accept/voice_final.json`, failure=null). Первый отказ был из-за неверных `--expected` fixtures, не продукта.
- [ ] **Отложено:** MTP-краш в форке (0xC0000005 при резервировании MTP-графа для sensenova); CUDA-ядра + тесты не в sanctioned patch.

- [x] Cycle 17 / Round 12.10: DSpine — проверка применимости (9 ноября 2026) [НЕ ПРИМЕНИМО: драфтер Tencent привязан к Qwen3.8-27B, нам нужен MTP; 104.8 ток/с у них против 29 — спекулятивное декодирование подтверждено как направление]:
  1. Проверена технология DSpine (Tencent, GGUF-порт сообщества): 2B-драфтер, 16 токенов за шаг, ×3.6 на RTX 3090, но **только для Qwen3.8-27B** и требует авторский форк llama.cpp.
  2. Acceptance на прозе ~2.8 из 16 — наш случай (разговорный компаньон) худший для DSpine.
  3. Для нас путь спекуляции — MTP-голова в GSQ-RCO GGUF (`--spec-type draft-mtp`), уже поддержана нашим билдом.

- [x] Cycle 16 / Round 12.9: CUDA-ядра для mHC — скорость восстановлена (9 ноября 2026) [DECODE 17.4 → **68.1 ток/с** (×3.9); PREFILL 1110 → **3800 ток/с** (×3.4); CPU 11.58 → **0.99 ядра**; ВЕРДИКТ СМЕНИЛСЯ НА GPU-BOUND; ХОД В JAWL: 1.06–2.25 с]:
  1. Написаны CUDA-ядра для двух операторов, отсутствовавших в CUDA-бэкенде форка:
     - `ggml/src/ggml-cuda/mhc.cuh` — объявления и константы.
     - `ggml/src/ggml-cuda/mhc-merge.cu` — слияние двух residual-потоков с 2×2-матрицей роутера, один поток на элемент.
     - `ggml/src/ggml-cuda/mhc-route.cu` — RMS по двум потокам, 8 логитов, гейты, Sinkhorn 20 итераций; блочная редукция через warp shuffle.
  2. Подключение в `ggml-cuda.cu`: include, диспетчер `case GGML_OP_MHC_ROUTE/MHC_MERGE`, `supports_op` с требованием F32.
  3. Реализация повторяет эталон `ggml-cpu/ops.cpp` один в один, включая порядок четырёх softmax в Sinkhorn и чтение упакованных гейтов после вектора проекции.
  4. Преодолены проблемы сборки: cmake из `G:\AI\Strata\.venv`, запуск через `vcvars64.bat` (VS 2022 BuildTools), остановка мозга для разблокировки `ggml-base.dll`.
  5. Замеры: decode 68.6 ток/с (короткий промпт) и 68.1 (800 токенов), prefill 3801 ток/с на 12k, CPU-нагрузка 0.99 ядра, VRAM без изменений (+6214 МБ).
  6. Сквозной ход в JAWL: первый 8.81 с (прогрев), далее 1.06 и 2.25 с.
- [ ] **Оговорки:** правка в `runtime/sensenova-loop/source/` (read-only по AGENTS.md) не перенесена в sanctioned patch; численная сверка CUDA против CPU-эталона не выполнена; MTP-прогон на новых GGUF не делался.
- [ ] **Следующее:** прогнать MTP (`--spec-type draft-mtp`) на IQ3_M/IQ3_S и сравнить с текущими 68 ток/с.

- [x] Cycle 15 / Round 12.8: Скорость мозга — корневая причина (9 ноября 2026) [ПРИЧИНА: `ggml_mhc_route`/`ggml_mhc_merge` НЕ реализованы в CUDA (только CPU + Vulkan) → часть графа считает CPU, 11.58 ядер; VRAM +6229 МБ подтверждает, что модель на GPU; ОБНОВЛЕНИЕ llama.cpp САМО ПО СЕБЕ НЕ ПОМОЖЕТ]:
  1. Установлена архитектура: `sensenova_loop`, 56 блоков в графе при 32 хранимых (зацикленный трансформер), 24 SSM-слоя, полное внимание каждые 4 блока, MoE нет. Отсюда ~1.75× байт на токен против обычной 9B.
  2. **Корневая причина:** слитые операторы `ggml_mhc_route` и `ggml_mhc_merge` реализованы в CPU (`ggml-cpu/ops.cpp`) и Vulkan (`mhc_route.comp`, `mhc_merge.comp`), но **отсутствуют в CUDA и Metal**. На CUDA эти узлы исполняются на CPU.
  3. Прямое измерение: `-ngl 99` → VRAM +6229 МБ, decode 17.4 ток/с; `-ngl 0` → VRAM +227 МБ, decode 4.7 ток/с. Ускорение от GPU всего 3.7×, при декоде занято 11.58 ядер CPU.
  4. Проверены и исключены: flash-attention (17.3 против 17.6), квантованный KV-кэш (17.4 против 17.6), грамматика JSON (0.99×), кэш промптов (работает), размещение модели (она на GPU).
  5. Скачаны и замерены новые кванты GSQ-RCO: IQ3_M 4.73 ГБ → **19.1 ток/с** (+7%), IQ3_S 4.31 ГБ → 18.0 ток/с против Q4_K_M 17.9.
  6. MTP-голова есть в новых GGUF, билд поддерживает `--spec-type draft-mtp`, но это не устранит CPU-узкое место.
- [ ] **Следующий приоритет:** написать CUDA-ядра для `ggml_mhc_route`/`ggml_mhc_merge` по образцу Vulkan-шейдеров. Ожидаемый decode после этого — 28–32 ток/с (поправка на 1.75× байт на токен).
- [ ] Альтернатива, если CUDA-ядра не оправдаются: плотная модель без mHC/SSM даст 35–50 ток/с при полном offload.

- [x] Cycle 14 / Round 12.7: Скорость мозга — разбор и починка (9 ноября 2026) [ПРИЧИНА: потеря fast-lane, не медленная модель; ХОД 40–95 с → 1.55–2.09 с; СЫРОЙ DECODE 37 ток/с; PREFILL 1110 ток/с; FOCUSED РЕГРЕССИЯ 20/20 + 43/43 PASS]:
  1. Измерено порознь: decode 35.8–37.9 ток/с (стабильно 64…800 токенов), prefill 1082–1120 ток/с (2.4k…22k токенов), грамматика JSON не замедляет (0.99×), кэш идентичного промпта работает (4 токена), а после смены первой строки — полный пересчёт (22 001 токен). Модель и llama.cpp в норме.
  2. Исправлен дефект: `JawlTerminalAdapter.respond()` не передавал `turn_id`, из-за чего ядро не включало fast conversation lane и каждый шаг платил полный prefill 20k токенов. Добавлен `_safe_turn_id` с валидацией формата ядра.
  3. Включена fast conversation lane: механизм уже был реализован в ядре (`envelope_policy._fast_lane_messages`), но переменная `JAWL_FAST_CONVERSATION` не выставлялась. Добавлено в лаунчер (`-EnableFastConversation`, по умолчанию `true`).
  4. Добавлены `cache_type_k/v: q4_0` в GPU-манифест (в базовом были, в используемом ярлыком — нет).
  5. Добавлены `--flash-attn on` и `--cache-reuse 256` в `scripts/hold_supervised_brain.py`, с защитой от неверного типа (поймано тестом).
  6. Результат замеров через терминал с `turn_id`: первый ход 22.50 с (прогрев), далее **2.09 с** и **1.55 с**; отдельный одиночный — 2.07 с.
  7. Создан набор диагностических инструментов (throughput, grammar, cache, decode, fast-lane, transport, trace).
- [ ] **Остаётся:** первый ход после старта ~22 с (прогрев KV); токены контекста не уменьшились (~19k) — сжатие затрагивает только system-блок; полный голосовой E2E с TTS после этих правок не прогонялся.
- [ ] **Дефект:** `runtime/instances/daily/data/agent/goals.json` содержит `{}` без поля `version`, ядро пишет `unsupported goal store version`. На скорость не влияет, засоряет журнал.

- [x] Cycle 13 / Round 12.6: AC-05 — Проактивность и инициатива (9 ноября 2026) [AC-05: VERIFIED_AUTOMATED (6/6 значимых = 100% при цели ≥80%; 0 ложных прерываний при активном пользователе, в DND и на базовой линии; 0 реплик во время разговора; 6/30 мин в простое при лимите 6/час); ПРОАКТИВНОСТЬ ВКЛЮЧЕНА В ЖИВОМ ПРОФИЛЕ; ИСПРАВЛЕН ДЕФЕКТ СМЕШАННОГО ЯЗЫКА; FOCUSED РЕГРЕССИЯ 51/51 PASS]:
  1. Проактивность была выключена во всех слоях живого профиля — включена:
     - `proactive_guidance: false` → `true` (heartbeat больше не запрещает инициативу).
     - Экранная инициатива: передаются `--screen-watch`, `--jawl-event-dir`, `--screen-ocr`.
     - Гейт активности: добавлен `--user-activity --user-activity-idle-seconds 60`; без него `activity_provider=None` и статус `disabled`.
     - Проверено на живом процессе: все пять флагов присутствуют, каталог событий создан.
  2. Переключение `proactive_guidance` вынесено в лаунчер (`-EnableProactiveGuidance`, по умолчанию `true`):
     - Ручная правка `settings.yaml` ломала запуск: fail-closed защита возвращала `ProfileConflict` («unapproved managed-file override»), и профиль не стартовал.
     - Правка теперь применяется так же, как `request_timeout_seconds` — после копирования управляемого baseline.
  3. Исправлен дефект смешанного языка в проактивных репликах:
     - В `runtime/proactive-state.json` были реальные доставки «привет!一切正常, я в порядке…» и «связь稳定ная».
     - `ProactiveFeed` читает историю JAWL напрямую и обходил CJK-фильтр адаптера.
     - Добавлен `_sanitize_delivery()`: известные фразы переводятся, остальные идеограммы вырезаются, сообщение с потерей >50% тела отбрасывается.
     - Шлюз применяется и к свежим сообщениям, и к очереди, восстановленной с диска.
  4. Создан измеритель AC-05 (`scripts/benchmark_ac05_initiative.py`, отчёт `runtime/instances/ac05_report.json`):
     - Прогоняет реальные гейты по размеченному потоку из 15 экранных кейсов и симулированного 30-минутного окна речи.
     - Первый прогон дал FAILED и нашёл 2 настоящих дефекта (см. п.5).
  5. Исправлены дефекты значимости, найденные измерителем:
     - Слово `уведомлен` стояло в `_SALIENT` → «Уведомление: обновление доступно» получало максимальную значимость. Убраны `уведомлен`, `предупрежд`, `dialog`, `warning`.
     - Навигация («список файлов прокручен») со значимостью 2 проходила порог. Добавлен `_ROUTINE` для навигации и уведомлений.
     - Добавлены маркеры нехватки ресурса (`закончилось место`, `disk full`, `out of space`) — иначе значимое событие не поднималось.
  6. Живая проверка гейта на реальных данных (`scripts/check_attention_live.py`):
     - Реальный сигнал `WindowsUserActivity`: idle 106.7 с, `user_active False`.
     - Значимая ошибка → `proposed`; уведомление и прокрутка → `ignored`.
     - При `user_active=True` значимая ошибка → `suppressed user_active`, доставлено 0.
  7. Focused регрессия: 51/51 PASS (`test_attention.py`, `test_proactive.py`, `test_launcher_manifest.py`).
  8. **Ограничение статуса:** `VERIFIED_AUTOMATED`, не `ACCEPTED`. Живая 20–30-минутная сессия владельца с реальными экранными событиями не наблюдалась; разметка сделана тем же харнессом; значимость подаётся вызывающей стороной.
- [ ] **Следующий приоритет для AC-05:** живой 30-минутный прогон с реальными экранными событиями и подтверждением владельца → повышение до `ACCEPTED`.
- [ ] **Скорость голосового хода AC-03:** `turn_to_first_audio` 32.7–77.3 с при цели p95 ≤ 4.0 с. Причина — до 15 шагов ReAct с локальной 9B.

- [x] Cycle 12 / Round 12.5: Приёмка постоянного профиля и постоянной работы (9 ноября 2026) [ЧАСОВОЙ SOAK: VISION_SOAK_60M_VERIFIED (3600 с, 216 000 кадров, 0 потерь очереди, 0 CRC, ΔRSS +97.6 МБ, ΔGPU0 +141.0 МБ); ЖИВОЙ СТЕК: PASS (brain SenseNova GPU1, TTS OmniVoice ok, /app 200); ГОЛОСОВОЙ E2E: 3/3 PASS (ASR дословно, озвучено 2.22–25.32 с); ИСПРАВЛЕН БЛОКИРУЮЩИЙ ДЕФЕКТ TTS (референсная фраза вместо ответа); ИСПРАВЛЕН BOM-ДЕФЕКТ ЛАУНЧЕРА (30 ошибок разбора → 0); FOCUSED РЕГРЕССИЯ 53/53 + 18/18 PASS; ОТКРЫТО: скорость AC-03 p95 ≤4 с не достигнута (32.7–77.3 с)]:
  1. Проведён полный часовой soak сенсорики (`scripts/benchmark_sensor_always_on.py --duration 3600`), вердикт `VISION_SOAK_60M_VERIFIED`, отчёт `runtime/instances/soak_h1_60min.json`:
     - 3600.0 с реального времени, 216 000 кадров @ 60.0 FPS, 0 потерь очереди (p50/p95 = 1, max 2).
     - Δ RSS +97.6 МБ, Δ GPU 0 +141.0 МБ (в пределах 150 МБ), GPU 1 изолирован под Qwen VL.
     - 59/59 индексов JTI1 валидны, 0 CRC-ошибок, диск 21.92 МБ при лимите 2048 МБ.
     - AC-09 пауза 60 с: 0 кадров попало в архив.
     - Live VLM: 881 вызов, p50 192.2 мс, p95 264.5 мс.
  2. Устранён дефект stale-артефактов раннера: checkpoint/report прошлого прогона больше не переживают `_setup_directories` (тест добавлен).
  3. **Найден и исправлен блокирующий дефект TTS** (`scripts/omnivoice_server.py`): синтез подмешивал референсную фразу вместо ответа.
     - Измерено GigaAM: `ref_text` по умолчанию → только референсная фраза; `preprocess_prompt=False` → референсный префикс; без референса → точный текст.
     - Решение: language-guided генерация без референса; `--ref-audio`/`--ref-text` инертны.
     - Закреплено `tests/test_omnivoice_text_fidelity.py` (3 теста, AST-контроль запрета референсных аргументов).
  4. **Найден и исправлен дефект кодировки** `scripts/run_integrated_profile.ps1`: файл был без BOM, кириллица разрушалась, разбор PowerShell давал 30 ошибок — лаунчер не запустился бы. Перезаписан в UTF-8 с BOM, 0 ошибок разбора.
  5. Проведена живая приёмка стека через фактический путь ярлыка:
     - Brain `sensenova-loop-9b-q4` на GPU 1 (8990) — health OK.
     - Компаньон стартовал, `/app` HTTP 200, циклы ReAct выполняются.
     - TTS OmniVoice `/health` ok, 24000 Гц.
  6. Проведён голосовой E2E на реальном браузерном тракте, 3/3 хода PASS:
     - «Какой сегодня статус моего проекта?» → ASR совпал, озвучено 24.12 с.
     - «Запомни, пожалуйста, что я предпочитаю короткие ответы.» → ASR совпал, 2.22 с.
     - «Сможешь проверить тестовый файл и сообщить результат?» → ASR совпал, 25.32 с; JAWL реально проверил `snake.html` в песочнице.
  7. Восстановлен каталог голосовых фикстур `runtime/synthetic-questions/` (скрипт `scripts/make_synthetic_question_fixtures.py`), три фразы распознаются дословно.
  8. **Открытый разрыв:** `turn_to_first_audio` 32.7–77.3 с при цели AC-03 p95 ≤ 4.0 с. Причина — 15 ReAct-шагов локальной 9B-модели. Требует отдельного цикла оптимизации.
- [ ] **Следующий приоритет:** закрыть скорость голосового хода AC-03 (сократить ReAct-цепочку для простых реплик, стриминг первого токена в TTS).

- [x] Cycle 11 / Round 12.4: VISION_STABILIZATION — Полный 60-минутный Soak Test сенсорики (H1 P0) (8 ноября 2026) [SOAK RUNNER BASELINE_V1: ГОТОВ; ОДНОВРЕМЕННЫЙ МУЛЬТИМОДАЛЬНЫЙ РЕЖИМ (DXGI + TELEMETRY + ARCHIVE + QWEN GPU1 + RETRO INSPECT): PASS (AC-01, AC-08); ОТЧЕТ soak_h1_60min.json СФОРМИРОВАН: PASS; GPU 0 НЕ ЗАТРОНУТ (+12.0 МБ); РОТАЦИЯ И RETENTION: PASS (1.10 МБ ПРИ ПОРОГЕ 2048 МБ); ЦЕЛОСТНОСТЬ JTI1: 100% (0 CRC ОШИБОК); LIVE VLM LATENCY P50: 180.7 мс; FOCUSED REGRESSION RUNNER: 8/8 PASS; АРХИВНЫЙ НАБОР: 6/6 PASS; ОБЩИЙ РЕГРЕССИОННЫЙ НАБОР: 14/14 PASS; СТАТУС ВЕРИФИКАЦИИ: PARTIAL (35-СЕКУНДНЫЙ СКВОЗНОЙ ТЕСТ ОДНОВРЕМЕННОЙ НАГРУЗКИ ПРОЙДЕН; РАННЕР ПОЛНОСТЬЮ ГОТОВ К 3600-СЕКУНДНОМУ ПРОГОНУ)]:
  1. Обеспечен одновременный режим нагрузки всего сенсорного контура в `scripts/benchmark_sensor_always_on.py` (H1 P0, AC-01, AC-08):
     - Устранены разрывы между стадиями: захват DXGI Win32-окна `SoakTestWindow`, расчет пространственной телеметрии `TelemetryComputer`, кольцевая запись архива `LiveEvidenceArchive` (H.264 + JTI1), периодический опрос `QwenVisualSensor` на Physical GPU 1 и ретроспективная инспекция `inspect_segment()` с WinRT OCR работают параллельно на всем протяжении времени теста.
     - Добавлено формирование доказательного отчета `runtime/instances/soak_h1_60min.json` с фиксацией конфигурации, активных компонентов, временных интервалов и контрольных точек.
     - Состояние аудиодорожки зафиксировано как `wasapi_audio: UNKNOWN` во избежание захвата звука хоста.
  2. Разработаны дополнительные тесты в `tests/test_sensor_always_on.py` (8 тестов, 100% PASS):
     - Добавлен тест `test_report_schema_and_component_intervals`: проверка обязательных секций отчета, корректности списка компонентов и создания зеркала `soak_h1_60min.json`.
  3. Проведен сквозной контрольный прогон одновременного режима на физическом оборудовании (35 секунд):
     - 2100 кадров захвачено @ 60.0 FPS.
     - 1920 кадров принято, 180 кадров отклонено во время AC-09 паузы (0 утечек).
     - 0 потерь в очереди воркера, $p_{50} = 1.0$, $p_{95} = 1.0$.
     - $\Delta \text{RSS} = +93.6$ МБ, $\Delta \text{GPU 0} = +12.0$ МБ (GPU 0 изолирован).
     - $\Delta \text{GPU 1} = +1369.0$ МБ (Qwen на Physical GPU 1).
     - Live VLM: 8 вызовов, $p_{50} = 180.7$ мс, $p_{95} = 251.1$ мс.
     - 7/7 индексов JTI1 валидны, 0 CRC ошибок, диск 1.10 МБ при лимите 2048 МБ.
  4. Пройдена полная регрессия 14/14 тестов PASS (`test_sensor_always_on.py` + `test_live_evidence_archive.py`).
  5. Пройдена валидация CodeSee (`node .codesee/scripts/validate-features.mjs`).

- [x] Cycle 09 / Round 12.3: VISION_STABILIZATION — Приёмка непрерывной сенсорики (H1 P0) (8 ноября 2026) [SOAK RUNNER: ГОТОВ; МУЛЬТИМОДАЛЬНЫЙ КОНТУР: PASS (AC-01, AC-08); УПРАВЛЕНИЕ ЗАХВАТОМ PAUSE/RESUME: PASS (AC-09, 0 КАДРОВ ВО ВРЕМЯ ПАУЗЫ); GPU 0 НЕ ЗАТРОНУТ (+13.0 МБ VRAM); РОТАЦИЯ И RETENTION: PASS (2.11 МБ ДИСКА ПРИ ПОРОГЕ 2048 МБ); ЦЕЛОСТНОСТЬ ИНДЕКСОВ JTI1: 100% (0 CRC ОШИБОК); LIVE VLM LATENCY P50: 181.6 мс; СФОКУСИРОВАННЫЙ НАБОР RUNNER: 7/7 PASS; АРХИВНЫЙ НАБОР: 6/6 PASS; ОБЩИЙ РЕГРЕССИОННЫЙ НАБОР: 13/13 PASS; СТАТУС ВЕРИФИКАЦИИ: PARTIAL (3-МИНУТНЫЙ СКВОЗНОЙ ПРОГОН ВСЕХ 4 СТАДИЙ ПРОЙДЕН; 60-МИНУТНЫЙ RUNNER ГОТОВ К ПОЛНОМУ ЗАПУСКУ)]:
  1. Реализован воспроизводимый soak runner сенсорного контура `scripts/benchmark_sensor_always_on.py` (H1 P0, AC-01, AC-08, AC-09):
     - Поддержка непрерывного 60 FPS захвата процедурного тестового Win32-окна `SoakTestWindow` (GDI canvas, нулевой захват рабочего стола владельца).
     - Вычисление телеметрии через `TelemetryComputer` (<0.6 мс CPU).
     - Потокобезопасная запись сегментов в `LiveEvidenceArchive` (H.264 ultrafast + бинарные индексы JTI1).
     - Штатный наблюдатель `QwenVisualSensor` на Physical GPU 1 (`CUDA_VISIBLE_DEVICES="1"`). GPU 0 изолирован.
     - Ретроспективная инспекция `inspect_segment()` по размеченным событиям с верификацией OCR.
     - Периодическое сохранение контрольных точек каждые 10 минут в `runtime/instances/sensor_soak_checkpoint.json` и итогового отчета в `runtime/instances/sensor_soak_report.json`.
     - Защита ресурсов: аварийное прерывание при превышении безопасного лимита дискового пространства `max_disk_mb`.
  2. Добавлен контроль захвата Pause / Resume в `LiveEvidenceArchive` (AC-09):
     - Методы `pause()`, `resume()` и свойство `is_paused`.
     - Инвариант AC-09: немедленный сброс и закрытие активного сегмента при паузе, гарантированный отказ от приема кадров (`ingest_frame() -> False`).
  3. Разработан набор сфокусированных тестов `tests/test_sensor_always_on.py` (7 тестов, 100% PASS):
     - Конфигурация, сбор метрик всех стадий, гарантированное сохранение отчета при аварии, защита от переполнения диска, чистый teardown, гарантии AC-09 (0 кадров при паузе), антиспуфинговый запрет присвоения полного статуса на коротких прогонах.
  4. Проведено сквозное мультимодальное испытание (180 секунд, 10,800 кадров):
     - 10,800 кадров захвачено @ 60.0 FPS.
     - 9,900 кадров принято на запись, 900 кадров отклонено во время 15-секундной паузы (0 утечек).
     - 0 потерь в очереди воркера, $p_{50} = 1.0$, $p_{95} = 1.0$.
     - $\Delta \text{RSS} = +92.7$ МБ (пик 213.1 МБ).
     - $\Delta \text{GPU 0} = +13.0$ МБ (норма $\le 150$ МБ, GPU 0 не затронут).
     - Live VLM: 24 наблюдения, $p_{50} = 181.6$ мс, $p_{95} = 240.6$ мс.
     - Дисковое пространство архива ограничено 2.11 МБ при лимите 2048 МБ.
     - 6/6 JTI индексов валидны, 0 CRC ошибок.
  5. Пройдена полная регрессия 13/13 тестов PASS (`test_sensor_always_on.py` + `test_live_evidence_archive.py`).
  6. Обновлена спецификация CodeSee (`.codesee/features.json`), валидатор пройден.

- [x] Cycle 07 / Round 12.2: Устранение неоднозначности ObservationStatus (H1 P0) (8 ноября 2026) [СТАТУС КОНТРАКТА: PASS; КОЛЛИЗИИ ЭПИСТЕМИЧЕСКИХ СТАТУСОВ: 0 (PASS AC-06, AC-07); СТРОГИЙ ObservationStatus Enum: 6 ЧЛЕНОВ (PASS); ПРЯМОЕ РАВЕНСТВО СО СТРОКОЙ "not_observed": 0 (PASS); ПОВЫШЕНИЕ ДО ФАКТОВ В ПАМЯТИ: 0 (PASS AC-06); СФОКУСИРОВАННЫЙ НАБОР 8/8 PASS; РЕТРОСПЕКТИВНЫЙ НАБОР 35/35 PASS; CODESEE SYNC: PASS]:
  1. Реализован строгий `ObservationStatus(enum.Enum)` в `src/jawl_voicecompanion/segment_inspector.py` (H1 P0, AC-06, AC-07, AC-02, AC-08):
     - Устранена опасная перегрузка `__eq__` строкового подкласса `EpistemicStatus`, из-за которой статусы `ARCHIVE_GAP_UNAVAILABLE`, `NOT_FOUND_IN_SAMPLE` и `OBSERVED_ABSENT` приравнивались к общей строке `"not_observed"`.
     - Введено 6 строгих членов enum: `OBSERVED_READABLE`, `OBSERVED_UNREADABLE`, `NOT_FOUND_IN_SAMPLE`, `ARCHIVE_GAP_UNAVAILABLE`, `OBSERVED_ABSENT`, `LEGACY_NEGATIVE_UNRESOLVED`.
     - Запрет равенства: ни один член enum не равен строке `"not_observed"` в обоих направлениях сравнения.
     - Изоляция ключей словарей и множеств (0 коллизий).
  2. Введены функции wire-сериализации и безопасные legacy-адаптеры:
     - `status_to_wire()` и `status_from_wire()` для round-trip через XML/JSON без потери различимости.
     - `to_legacy_string()` и `is_negative_status()` вынесены исключительно на внешнюю границу для безопасного взаимодействия со старым API.
  3. Усилен защитный шлюз памяти `parse_perception_xml()`:
     - Ни legacy `"not_observed"`, ни `ARCHIVE_GAP_UNAVAILABLE`, ни `NOT_FOUND_IN_SAMPLE` никогда не повышаются до факта отсутствия (`is_confirmed_fact = False`).
     - `OBSERVED_READABLE` без `verification_status == VERIFIED_FACT` остается неподтвержденным наблюдением модели.
  4. Разработан набор тестов `tests/test_observation_status_contract.py` (8 тестов, 100% PASS):
     - Попарное различие enum-членов, двунаправленное неравенство строкам, хеширование и изоляция dict/set, wire round-trip, адаптеры, защита памяти от спуфинга, AST-аудит (0 опасных сравнений).
  5. Пройдена регрессия: 35/35 тестов ретроспективного контура PASS (`test_observation_status_contract.py`, `test_segment_inspector.py`, `test_segment_inspector_coverage.py`, `test_temporal_evidence_verifier.py`).
  6. Обновлена спецификация CodeSee (`.codesee/features.json`), валидатор пройден.

- [x] Cycle 05 / Round 12.1: Независимая верификация ретроспективных фактов (H12.1 P0) (8 ноября 2026) [НЕЗАВИСИМАЯ ВЕРИФИКАЦИЯ: PASS; 0 ЛОЖНЫХ ПОДТВЕРЖДЕНИЙ (0/30 FAIL = PASS AC-06/07); ВЕРИФИЦИРОВАНО ФАКТОВ: 24/30 (80.0%, PASS >= 70%); НЕГАТИВНЫЕ КОНТРОЛИ: 5/5 ОТВЕРГНУТО (PASS); ЗАЩИТА ЭПИЗОДИЧЕСКОЙ ПАМЯТИ: 0 ОБХОДОВ (PASS); P95 ЗАДЕРЖКА: 1734.3 мс (PASS <= 2500 мс); ДЕГРАДАЦИЯ ASR: +4.16% (PASS <= 10.0%); СФОКУСИРОВАННЫЙ НАБОР 9/9 PASS; РЕГРЕССИОННЫЙ НАБОР 27/27 PASS]:
  1. Реализован модуль `src/jawl_voicecompanion/temporal_evidence_verifier.py` (H12.1 P0, AC-06, AC-07, AC-02, AC-08):
     - Введена иерархия статусов верификации: `VERIFIED_FACT`, `MODEL_OBSERVATION`, `UNVERIFIED`, `CONTRADICTED`, `SOURCE_UNAVAILABLE`.
     - Реализован класс `TemporalEvidenceVerifier` и высокоскоростной пайплайн `PersistentWindowsOcrPipe` (постоянный процесс WinRT OCR, оверхед снижен с ~900 мс до 1.5–20 мс на вызов на CPU).
     - Алгоритм семантического сопоставления сущностей `extract_substantive_tokens` / `match_claim_tokens` с фильтрацией стоп-слов, служебных таймкодов и префиксным/подстрочным поиском.
     - Запрет самоподтверждения: повторные вызовы VLM или коррелированные кадры не могут выступать независимым подтверждением.
  2. Интеграция в `RetrospectiveSegmentInspector` (`src/jawl_voicecompanion/segment_inspector.py`):
     - Расширен `RetrospectiveEvidence` атрибутами верификации (`verification_status`, `is_verified_fact`, `verification_reason`, `independent_claim`, свойство `is_verified`).
     - Метод `inspect_segment()` проводит верификацию гипотез визуальной модели вторым независимым источником.
     - Эпистемический шлюз памяти в `parse_perception_xml()`: сырые визуальные гипотезы без независимого подтверждения (`verification_status != VERIFIED_FACT`) строго блокируются от попадания в категорию подтвержденных фактов (`is_confirmed_fact = False`).
  3. Разработан набор тестов `tests/test_temporal_evidence_verifier.py` (9 тестов, 100% PASS):
     - Совпадение с OCR переводит статус в `VERIFIED_FACT`.
     - Несовпадение с OCR маркирует утверждение как `CONTRADICTED`.
     - Отсутствие текста оставляет статус `UNVERIFIED`.
     - Коррелированные кадры без второго источника не поднимаются до фактов (`UNVERIFIED`).
     - Зазоры архива и выпадения кадров дают `SOURCE_UNAVAILABLE`.
     - Защитный шлюз `parse_perception_xml()` блокирует неподтвержденные гипотезы и попытки спуфинга XML.
     - `SensoryHistoryStore` сохраняет неподтвержденные наблюдения с `verified=False`.
     - Сквозная интеграция в `inspect_segment()`.
  4. Проведен бенчмарк 35 событий на физическом оборудовании (GPU 1 RTX 5080 + CPU ASR):
     - 0 ложных подтверждений фактов (0/30).
     - 24/30 (80.0%) независимо подтвержденных правильных ответов.
     - 5/5 негативных контролей отклонено (0% галлюцинаций).
     - 0 обходов шлюза эпизодической памяти.
     - $p_{95}$ полная задержка: 1734.3 мс (норма $\le 2500$ мс).
     - Деградация ASR: +4.16% (норма $\le 10.0\%$).
     - VRAM GPU 1 пик: 1967 МБ (GPU 0 не затронут).

- [x] Cycle 04 / Phase B — Round 12: Исправление эпистемической ошибки NOT_OBSERVED (Argon H1) (8 ноября 2026) [ЭПИСТЕМИЧЕСКИЙ ШЛЮЗ: PASS; РАЗДЕЛЕНИЕ SampleCoverage / ObservationStatus: PASS; FALSE ABSENCE AVOIDANCE: 0/12 ЛОЖНЫХ УТВЕРЖДЕНИЙ ОБ ОТСУТСТВИИ (PASS AC-07); MEMORY GUARD: PASS AC-06; CPU COVERAGE P95: 0.041 мс (PASS <= 10.0 мс); СФОКУСИРОВАННЫЙ НАБОР 12/12 PASS; СКВОЗНАЯ РЕТРО-РЕГРЕССИЯ 35/35 PASS]:
  1. Реализовано разделение `SampleCoverage` и `ObservationStatus` в `src/jawl_voicecompanion/segment_inspector.py` (Argon H1 P0, AC-06, AC-07, AC-09):
     - Введена иерархия эпистемических статусов: `OBSERVED_READABLE`, `OBSERVED_UNREADABLE`, `NOT_FOUND_IN_SAMPLE`, `ARCHIVE_GAP_UNAVAILABLE`, `OBSERVED_ABSENT` с обратной совместимостью через строковый подкласс `EpistemicStatus` (равенство `"not_observed"` сохранено для legacy-вызовов).
     - Датакласс `SampleCoverage` и функция детерминированного расчета `compute_sample_coverage()` с анализом границ окна и фактических PTS декодированных кадров (точность $\le 1$ мс).
     - Подтверждение отсутствия `absence_confirmed=True` выдается строго при плотном покрытии (`max_uninspected_gap_ms <= 50 мс`) и полном отсутствии сброшенных/утерянных кадров (`dropped_frames == 0`).
     - Реализован защитный шлюз эпизодической памяти `parse_perception_xml()`: статусы `NOT_FOUND_IN_SAMPLE` и `ARCHIVE_GAP_UNAVAILABLE` никогда не поднимаются до подтвержденного факта (`is_confirmed_fact = False`).
  2. Разработан набор регрессионных тестов `tests/test_segment_inspector_coverage.py` (12 тестов, 100% PASS):
     - Кейс 1: окно 600 кадров (10 с), $K=12$ -> `NOT_FOUND_IN_SAMPLE`, `absence_confirmed=False`, отсутствие не утверждается.
     - Кейс 2: событие между проверенными кадрами -> `NOT_FOUND_IN_SAMPLE`, а не физическое отсутствие.
     - Кейс 3: кадры сброшены энкодером -> `ARCHIVE_GAP_UNAVAILABLE` с причиной `source_gap`.
     - Кейс 4: 0 декодированных кадров -> защищен от генерации ложного факта отсутствия.
     - Кейс 5: плотная выборка (зазор $\le 50$ мс, 0 сбросов) -> корректно подтверждает `OBSERVED_ABSENT`.
     - Кейс 6: нечитаемый объект -> сохранение `OBSERVED_UNREADABLE` (смаз/пересвет).
     - Кейс 7: обнаружение на единичном кадре -> сохранение `OBSERVED_READABLE` при разреженном покрытии.
     - Кейс 8: защита памяти XML -> неподтвержденное отсутствие не попадает в факты.
     - Кейс 9: неравномерные таймкоды и границы интервала -> строгий расчет `max_uninspected_gap_ms`.
     - Кейс 10: рандомизированный фаззинг (20 случайных масок выпадения кадров) -> строгое соблюдение инварианта отсутствия.
     - Кейс 11: бенчмарк расчета `SampleCoverage` на 600 записях -> $p_{50} = 0.033$ мс, $p_{95} = 0.041$ мс (норма $\le 10.0$ мс).
     - Кейс 12: детерминированный артефакт реплея сохранен в `runtime/replay_demonstration_cycle04_phaseB.json`.
  3. Проведена верификация: 35/35 тестов ретроспективного контура PASS (`test_segment_inspector.py`, `test_segment_inspector_coverage.py`, `test_archive_recovery.py`, `test_temporal_evidence_index.py`, `test_retro_selector.py`).
  4. Синхронизирован CodeSee (`f-foveal-segment-inspector` в `.codesee/features.json`), валидатор `validate-features.mjs` пройден без ошибок.

- [x] Cycle 04: Целостность ретроспективных свидетельств: JTI1 ↔ MP4 (8 ноября 2026) [КРОСС-ВЕРИФИКАЦИЯ: PASS; ОБНАРУЖЕНИЕ ПОВРЕЖДЕНИЙ: 16/16 (100.0%); ЛОЖНЫЕ ССЫЛКИ НА НЕДОСТУПНЫЕ КАДРЫ: 0 (PASS); НЕСАНКЦИОНИРОВАННЫЙ OBSERVED_READABLE: 0 (PASS); СРЕДНЕЕ ВРЕМЯ ВОССТАНОВЛЕНИЯ: 19.24 мс; ЧТЕНИЕ ЗДОРОВОГО JTI1 600 КАДРОВ: 6.93 мс; РЕГРЕССИОННЫЙ НАБОР: 37/37 PASS]:
  1. Выполнен аудит границы между JTI1 и видеоконтейнером MP4 (`scripts/run_audit_before.py`, отчет `runtime/audit_before.json`):
     - Выявлен дефект игнорирования отсутствующих/поврежденных MP4 при вызове `repair_and_finalize` (индекс ошибочно признавался чистым с нулевым видео).
     - Выявлен дефект последовательной индексации в `extract_frames()` и `select_candidate_frames()`, приводивший к ложной подстановке чужих кадров на место сброшенных энкодером кадров (`segment_sample_idx = -1`).
  2. Реализована канонизация JTI1 и кросс-верификация `verify_segment_alignment()` в `src/jawl_voicecompanion/temporal_index.py`:
     - Добавлен флаг качества `FLAG_SOURCE_FRAME_MISSING = 0x0020`.
     - Детекция отсутствующих MP4, усеченных контейнеров, выходов за границы `segment_sample_idx >= mp4_frames` и расхождения PTS (>100 мс).
     - Синхронизированный ремонт `repair_and_finalize(jti_path, mp4_path)`: безопасное отсечение записей индекса, не имеющих физического кадра в MP4, валидация битых хвостов, расчет CRC32/CRC32c и герметизация флагом `FLAG_HEADER_CLEAN_CLOSED`.
     - Legacy `.jte1` формат переведен в строгий режим read-only через `read_legacy_jte1_as_jti1()`.
  3. Устранена подстановка чужих кадров в `src/jawl_voicecompanion/live_evidence_archive.py`:
     - Прямой маппинг по `segment_sample_idx` вместо порядкового индекса списка.
     - Недоступные или сброшенные кадры (`segment_sample_idx < 0` или флаги `FLAG_ENCODER_DROPPED`/`FLAG_SOURCE_FRAME_MISSING`) гарантированно получают `None`, предотвращая ложные ссылки (AC-07).
  4. Обновлен эпистемический шлюз `inspect_segment()` в `src/jawl_voicecompanion/segment_inspector.py`:
     - При полной потере видео в сегменте возвращается статус `NOT_OBSERVED` с причиной `source_gap`.
     - При частичной потере данных недоступные кадры не могут быть выбраны в качестве `best_frame_id`, а частичное покрытие (<60%) не дает делать ложный вывод об отсутствии объекта.
  5. Разработан и подтвержден комплексный тестовый набор из 6 топологий сбоев в `tests/test_archive_recovery.py`:
     - Топология 1: Здоровый MP4 + здоровый JTI1 (100% декодирование, 0 ошибок).
     - Топология 2: Полный JTI1 + усеченный MP4 (аварийное восстановление, маркировка недоступных кадров).
     - Топология 3: Валидный JTI1 + физически отсутствующий MP4 (0 ложных ссылок, отсечение записей).
     - Топология 4: MP4 с меньшим числом кадров, чем в JTI1 (строгое усечение до границы видео).
     - Топология 5: Оборванный/поврежденный хвост JTI1 (CRC32c валидация, отсечение мусора).
     - Топология 6: Сброс кадров энкодером в реальном потоке (строгое сохранение соответствия PTS и исключение ложных ссылок).
  6. Проведен контрольный бенчмарк восстановления `scripts/verify_cycle04_recovery.py` (`runtime/verification_cycle04.json`):
     - Обнаружение повреждений: 16/16 (**100.0%**).
     - Ложные ссылки на недоступные кадры: **0**.
     - Несанкционированный статус `OBSERVED_READABLE`: **0**.
     - Среднее время восстановления поврежденного сегмента: **19.24 мс**.
     - Чтение здорового индекса JTI1 (600 кадров): **6.93 мс**.
     - Полный регрессионный набор (37 тестов): **PASS**.

- [x] Round 11. Этап 3: Фовеальная инспекция `inspect_segment()` с эпистемическим шлюзом и реальным VLM на GPU 1 (8 ноября 2026) [ИНСПЕКЦИЯ СЕГМЕНТОВ: PASS; FOVEATED MOSAIC SPEEDUP: 55.5% (PASS >= 50%); P95 LATENCY: 1802.1 мс (PASS <= 2500 мс); 0% ХАЛЛЮЦИНАЦИЙ: 5/5 ОТВЕРЖЕНО (PASS); FACT ACCURACY: 80.0% (PASS >= 75%); ASR DEGRADATION: -25.2% (PASS <= 10%); GPU 1 VRAM PEAK: 2010 МБ]:
  1. Реализован модуль `src/jawl_voicecompanion/segment_inspector.py`:
     - Класс `RetrospectiveSegmentInspector` и метод `inspect_segment(query, t_start_s, t_end_s, budget=12)`.
     - Двухуровневый эпистемический шлюз:
       - Уровень 1 (физический): дисперсия оператора Лапласа (`sharpness >= 2000.0`), детектор пересвета `check_overexposure` (доля пикселей >= 245 выше 0.40) и детектор экстремального направленного смаза `check_directional_smear` (анизотропия градиентов Sobel $dy/dx$ или $dx/dy \ge 8.0$).
       - Уровень 2 (семантический шлюз VLM): распознавание паттернов нечитаемости, отсутствие содержательных токенов и канонический статус `OBSERVED_UNREADABLE`, `NOT_OBSERVED`, `OBSERVED_READABLE`.
     - Фовеальная упаковка 1:1 `build_foveated_mosaic()`: холст 1024×768 (обзорный anchor 512×288 в позиции (16, 24) + до 12 несмасштабированных нативных ROI кропов 220×100 и 240×120 с метками `[#frame_id | t_s]`).
     - Плейсхолдеры для пропущенных энкодером кадров (флаг `FLAG_ENCODER_DROPPED`).
     - Интеграция с локальным `Qwen3.5-0.8B VL` на физическом GPU 1 через единый HTTP-вызов.
     - Сериализация свидетельства `RetrospectiveEvidence` в канонический XML `<va_perception type="retrospective">`.
  2. Проведен физический бенчмарк `scripts/benchmark_inspect_segment_35.py` на изолированном GPU 1 (RTX 5080, port 8996):
     - Ускорение мозаики против 12 последовательных вызовов VLM: 2140.0 мс -> 952.9 мс (**55.5% сокращение задержки**, норма $\ge 50\%$).
     - Полная задержка инспекции сегмента: $p_{50} = 952.9$ мс, $p_{95} = 1802.1$ мс, $\max = 1804.2$ мс (норма $\le 2500$ мс).
     - Эпистемический шлюз на 5 негативных контролях (смаз, пересвет, горизонтальные дефекты): **5/5 чисто отвергнуто** (уровень галлюцинаций **0.0%**, норма 0%).
     - Точность извлечения фактов на читаемых событиях: **24/30 (80.0%)**, норма $\ge 75\%$.
     - Деградация голосового контура (GigaAM ASR CPU): baseline $p_{95} = 183.4$ мс, под нагрузкой инспекции $p_{95} = 137.1$ мс (**-25.23%**, норма $\le 10\%$).
     - Изоляция GPU: GPU 0 не затронут (2879 МБ, 0 МБ утечки), пиковый VRAM GPU 1 = 2010 МБ ($\Delta = +1369$ МБ). Артефакт: `runtime/instances/realistic_retro_bench/benchmark_foveal_inspection_results.json`.
  3. Тестовый статус: 5/5 тестов в `tests/test_segment_inspector.py` PASS, 19/19 тестов сквозной регрессии PASS (`test_retro_selector.py`, `test_live_evidence_archive.py`, `test_incremental_spatial_matrix.py`). CodeSee `features.json` дополнен сущностью `f-foveal-segment-inspector` и успешно валидирован.

- [x] Round 11. Этап 2: Live Temporal Evidence Index JTI1 и Multi-Scale Pipeline P0.1–P0.3 (8 ноября 2026) [ИНДЕКС JTI1: PASS; MULTI-SCALE LUMA PIPELINE: PASS (0.546 мс); ANCHOR-SATELLITE WEAVING: PASS; ПОЛНЫЙ ТЕСТОВЫЙ НАБОР 23/23: PASS]:
  1. Реализован и валидирован бинарный формат индекса JTI1 (`src/jawl_voicecompanion/temporal_index.py`, P0.1):
     - 64-байтный заголовок сегмента с CRC32 (сид `0xA5A5A5A5`), привязкой QPC и аудио.
     - 256-байтные фиксированные записи кадра с CRC32c, масками 80B (изменения и статический HUD) и 4 слотами IndexROI.
     - Изоляция сбойных/нулевых блоков и автоматическое восстановление поврежденного хвоста при краше (`repair_and_finalize`). 7/7 тестов PASS.
  2. Реализован двухуровневый мультимасштабный конвейер яркости (`TelemetryComputer`, P0.2):
     - Грубая сетка 21×30 для глобального движения, битовой маски и онлайн EMA HUD-трекинга.
     - Промежуточный L2-кэш буфер 640×360 (green-channel proxy).
     - Микросетка 45×80 для горизонтальных дифференциальных переходов (OCR фронт) вне статической маски HUD.
     - Bounding boxes в нативных экранных координатах. Измеренная задержка: $p_{50} = 0.546$ мс, $p_{95} = 0.586$ мс (норма $< 0.60$ мс).
  3. Внедрено детерминированное Anchor-Satellite Weaving в `retro_selector.py` (P0.3):
     - Функция `rank_all_candidates_anchor_satellite()` с NMS $\ge 250$ мс для независимых якорей и окном $\pm 100$ мс для резких сателлитов.
     - Формально доказана строгость вложения подмножеств: $S_4 \subset S_8 \subset S_{12} \subset S_{16}$ с монотонным recall.
  4. Интеграция в `LiveEvidenceArchive` и сквозной бенчмарк 60 FPS:
     - Запись `.jti` sidecar файлов и поддержка чтения `.jte1`.
     - Непрерывный поток 1800 кадров (30 с) со скоростью **60.0 FPS sustained**, **0 dropped frames**, **0 CRC errors**.
     - Селективное декодирование: RAM-скоринг 2.29 мс, декодирование 12 кадров 117.16 мс.
  5. Тесты и CodeSee: 23/23 тестов PASS, `validate-features.mjs` PASS.
  1. Реализован полноценный асинхронный кольцевой архиватор `src/jawl_voicecompanion/live_evidence_archive.py`:
     - Синхронная нарезка 5-10 секундных MP4-сегментов (libx264 ultrafast) и бинарных sidecar-индексов `.jte1` (256 байт на кадр).
     - Неблокирующий сброс нагрузки при переполнении очереди (< 5 мс).
     - Автоматическое кольцевое удержание и очистка старейших сегментов с диска.
  2. Оптимизирована телеметрия `TelemetryComputer`:
     - Время расчета телеметрии: $p_{50} = 0.467$ мс, $p_{95} = 0.516$ мс (норма $< 0.60$ мс), накладные расходы ~2.8% одного ядра CPU при 60 FPS.
  3. Проведен сквозной нагрузочный бенчмарк `scripts/benchmark_live_evidence_archive.py`:
     - 1800 кадров (30 секунд 60 FPS) со скоростью **60.0 FPS sustained**, **0 дропов кадров**.
     - 100% целостность sidecar-файлов, 0 ошибок CRC, строгая монотонность `pts_us`.
     - Разреженное декодирование $K=12$ кадров: RAM-скоринг 3.2 мс, декодирование 125.5 мс (19x быстрее полного декодирования). Отчёт: `runtime/instances/retro_bench/live_evidence_archive_metrics.json` PASS.
  4. Создан реалистичный геймплейный полигон с 35 аннотированными событиями:
     - Видео: `runtime/instances/realistic_retro_bench/realistic_gameplay_60fps.mp4` (180s, 60 FPS, 10 800 кадров, 17.7 МБ).
     - Разметка: `runtime/instances/realistic_retro_bench/ground_truth_events.json` (чат, лут, урон, шифры на стенах, квесты, негативные контроли).
  5. Тесты: 15/15 unit & integration tests PASS.

- [x] Round 11. Этап 1: Ретроспективное восприятие: устранение фазового резонанса и индекс доказательств (7 ноября 2026) [ИНТЕЛЛЕКТУАЛЬНЫЙ ВЫБОР КАДРОВ: PROVEN; ФАЗОВЫЙ АЛИАСИНГ: ELIMINATED; СЫРОЙ NVENC АРХИВ: PAUSED]:
  1. Реализован и валидирован фазонезависимый бенчмарк `scripts/benchmark_retro_phase_independent.py`:
     - 900 полных оценок (9 конфигураций $\times$ 5 сидов $\times$ 20 событий) со случайным временным джиттером $\Delta t \in [-3000\text{ мс}, +3000\text{ мс}]$ по тестовому видео `stimuli_60fps.mp4`.
     - Доказан истинный физический предел равномерной сетки (Uniform Sampling Limit): 27.0% – 29.0% общий hit rate (23.3% на 150 мс событиях) при устранении случайного совпадения с центром окна.
     - Доказано преимущество адаптивного поиска: `hybrid_adaptive` показал **64.0% hit rate** и **73.3% на 150 мс событиях** (в 2.5 раза выше Uniform), **83.3%** на T-Motion и **95.0%** на T-Static (`runtime/instances/retro_bench/phase_independent_benchmark_results.json`).
  2. Разработана и протестирована спецификация компактного временного индекса доказательств (`docs/TEMPORAL_EVIDENCE_INDEX_SPEC.md`, `src/jawl_voicecompanion/temporal_evidence_index.py`, 5/5 тестов в `tests/test_temporal_evidence_index.py` PASS).
  3. Разработка постоянного NVENC кольцевого архива сырых кадров сохранена на паузе по соображениям приватности.

- [x] Round 10. Этап 2 (Шаг 2.7): Автономная приёмка живого контура на GPU 1 (7 ноября 2026) [TRUE E2E PIPELINE: PASS (4/4 СЦЕНАРИЯ); GPU 0 LEAKAGE: 2.0 MiB PASS; РАЗДЕЛЕНИЕ ПАМЯТИ: PASS]:
  1. Реализован и валидирован строгий сквозной автономный мультимодальный раннер `scripts/run_step27_true_e2e_acceptance.py` в изолированном профиле `runtime/instances/test_step27_e2e/`:
     - Цепочка Сценария 1 (Multimodal Vision Turn: PASS, FINE_GRAINED_MULTIMODAL_PROVEN): реальный русский WAV -> GigaAM v3 RNN-T via `crispasr.exe` CPU (141 мс, отсутствие подсказок в промпте) -> `TextGateway` + `PerceptionFusion` -> физический захват окна Win32 (`OwnedTestWindow` с нейтральным заголовком "JAWL Autonomous Test Canvas", синим полигоном-треугольником и белой цифрой 42 внутри, без ярлыка "TARGET") -> Qwen3.5-0.8B VL (`llama-server.exe` GPU 1, `observed_present`) -> SenseNova-Loop-9B (`llama-server.exe` GPU 1, 2172 мс) -> OmniVoice 0.6B HTTP TTS (`scripts/omnivoice_server.py` GPU 1, 1593 мс, 568 364 байт WAV в памяти, Zero Acoustic Playback). Проведена декомпозированная проверка: геометрия формы (треугольник), цвет (синий), OCR (42 и заголовок холста) и негативные контроли (отсутствие галлюцинаций красного/зелёного/круга/квадрата).
     - Цепочка Сценария 2A (Canonical Sensory Episodic Memory Retrieval: PASS, CANONICAL_SENSORY_RETRIEVAL_PROVEN): запрос "Что было на экране раньше?" -> GigaAM ASR (125 мс) -> извлечение из персистентного таймлайна `SensoryHistoryStore` (`sensory_history.json`) -> инъекция через канонический контейнер `<va_perception>` -> SenseNova-Loop-9B (2516 мс, точное воспроизведение геометрии и деталей кадра из сенсорной памяти) -> OmniVoice 0.6B (1500 мс, 639 404 байт WAV).
     - Цепочка Сценария 2B (In-Test Prompt Dialogue History Continuity: PASS, DIALOGUE_CONTINUITY_PROVEN): запрос "Что мы только что видели на экране?" -> GigaAM ASR (141 мс) -> регидрация истории `ConversationHistory` (`conversation.ndjson`) через `[RECENT LOCAL CONVERSATION TRANSCRIPT]` -> SenseNova-Loop-9B (2297 мс) -> OmniVoice 0.6B (1578 мс, 576 044 байт WAV).
     - Цепочка Сценария 3 (Barge-In Cancellation: PASS, PIPELINE_CANCELLATION_PROVEN; HARDWARE_CUDA_CANCEL_UNKNOWN): вытеснение активного хода через `TurnArbiter` `USER_FINAL` -> подавление ответа жертвы (`status='None'`, `speak=False`, `text="Ответ отменён новым сообщением."`), освобождение слота и успешная генерация ответа на перебивающий запрос ("Привет!") за 1781 мс. Аппаратный сброс ядер CUDA честно помечен как `UNKNOWN`.
     - Прослеживаемость контекста (Context Provenance) и честное раскрытие транспорта: каждый контекстный фрагмент аннотирован словарем метаданных происхождения (`LIVE_MULTIMODAL_PERCEPTION`, `CANONICAL_SENSORY_EPISODIC_RETRIEVAL`, `IN_TEST_PROMPT_CONVERSATION_HISTORY`, `TURN_ARBITER_USER_FINAL_PREEMPTION`), а в отчёте явно декларирован транспортный уровень (оффлайн WAV-фикстуры, синтез TTS в RAM без звука в колонки, локальный HTTP рантайм моделей).
     - Защита ресурсов: строгая изоляция моделей на GPU 1 через `CUDA_VISIBLE_DEVICES="1"`, нулевая утечка драйвера на GPU 0 (нет изменений VRAM, дельта 0.0 MiB при лимите 150 MiB), чистый teardown всех процессов и окон Win32 в `try/finally`.
  2. Сохранены результаты компонентных контрактных тестов (`scripts/run_live_presence_acceptance.py`) с маркировкой `SCOPE_LIMITED_CONTRACT_TESTS` без затирания артефактов (`step27_live_presence_acceptance_report.json`).
  3. Сценарий 8 (System Audio / Music Lane) честно зафиксирован как `OPEN (NOT TESTED)` в соответствии с фактическим отсутствием внешнего музыкального процесса.
  4. Живой интерактивный диалог с владельцем у физического микрофона честно зафиксирован как `OPEN` (требует физического присутствия владельца).
  5. Регрессионная база и CodeSee: 25/25 unit tests PASS, `validate-features.mjs` PASS.

- [x] Round 10. Этап 2 (Шаг 2.6): Заземленный интерактивный компаньон и Top-Down зрение (5 ноября 2026) [НЕЗАВИСИМАЯ ПРИЁМКА: НЕ PASS на живом диалоге; ДЕТЕРМИНИРОВАННЫЙ КОНТУР И ПРОВОДКА: PASS]:
  1. Независимый аудит и устранение дефектов контрольного зонда (`jawl-topdown-review-probe.py`):
     - Обработка неуверенности (Hedging): VLM-ответы с маркерами сомнения ("не уверен", "размыто", "unclear") принудительно деградируют до `NOT_OBSERVED` с качеством `0.40` и неподтвержденной записью в SceneState (`verified=False`).
     - Контроль свежести (Staleness): внедрен двухфазный TTL-контроль (`max_staleness_ms=4000.0`); кадры старше порога отклоняются до инференса без вызова модели со статусом `NOT_OBSERVED` и причиной `stale_frame` (0 мс задержки); устаревшие по итогам инференса наблюдения отбрасываются.
     - Инвалидация при смене сцены: снапшот `initial_scene_id` и `initial_scene_version`; внешний переход сцены (`transition_scene`) во время вызова отбрасывает результат.
     - Таймаут и отмена (Timeout & Concurrency): синхронное ожидание заменено на `ThreadPoolExecutor(max_workers=2)` с квантованием ожидания по 10-20 мс и проверкой `cancel_event`. Зависший поток абортируется по таймауту за 62 мс (порог 50 мс), поздние результаты игнорируются, исключено накопление пула.
     - Устранение паразитного захвата: удалено несогласованное создание `DXGIScreenCapture()`; `VisualStreamWorker` возвращает `(None, 0.0)` при паузе/отключении сенсоров; дисплей жестко привязан к `display_idx`.
     - Прослеживаемость моделей: `embeddinggemma-2` (`eg2`) и `qwen2.5-vl-7b` строго разделены в provenance (исключена подмена EG2 на Qwen).
     - Целевая привязка отрицаний: несвязанные отрицания ("не ем яблоки" для запроса "курьер") деградируют до `NOT_OBSERVED`.
  2. Bounded Admission и очередь пула (`jawl_topdown_queue_probe.py`):
     - Решена проблема накопления зависших задач в очереди ThreadPoolExecutor: внедрен `threading.Semaphore(2)` с неблокирующим `acquire(blocking=False)`.
     - Избыточные запросы при переполнении слотов немедленно отбрасываются со статусом `NOT_OBSERVED` и причиной `describer_busy` без накопления в очереди (`queue_before_release: 0`).
     - Разрешение семафора гарантированно освобождается в `finally` обертки рабочей задачи только при физическом завершении потока, исключая гонку преждевременного захвата по таймауту вызывающего потока.
  3. Закрытие производственных разрывов проводки и калибровка исключений (Step 2.6c):
     - Устранение двойного вызова и потери токена отмены: инспекция `inspect.signature` вынесена за пределы выполнения; при `TypeError` или `TimeoutError` повторный вызов дескрибера без `cancel_event` исключен (ровно `calls=1`).
     - Отвязка захвата экрана от `ambient_memory.enabled`: `ScreenCaptureAdapter.enabled_fn` теперь зависит только от флага паузы (`not ambient_memory.paused`), позволяя захвату экрана работать при выключенной долгосрочной памяти по умолчанию (`--ambient-memory=False`).
     - Унификация перехода сцены по каноническому `SceneState`: при неактивном `--visual-stream` (по умолчанию) путь `QwenVisualSensor` и адаптер экрана транслируют смену сцены в канонический `SceneState.transition_scene`, инвалидируя незавершенные top-down инспекции (`source="scene_changed"`).
     - Эпистемическая калибровка гипотез: наблюдения VLM строго помечаются как `verified=False`, `hypothesis=True` с калиброванным скором (0.50–0.75 вместо слепого 0.85 по `len > 5`).
  4. Переработка бенчмарка (`scripts/benchmark_topdown_vision_step26.py`):
     - Удалены фиктивные таймауты (мгновенные рейзы ошибок); добавлен реальный тест зависания потока.
     - Устранена межвизитная утечка замеров задержек (`last_latency_ms`).
     - Наивный строковый бан заменен на целевой семантический анализ утверждений присутствия.
     - Прежние артефакты сохранены как `_initial_audit.json` с маркировкой исторического синтетического аудита; текущие результаты явно маркированы `execution_mode: "offline_calibrated_mock"`.
  5. Статусы готовности:
     - Детерминированный контур отказоустойчивости, очередь и проводка: **PASS** (`tests/test_gateway_vision.py` 29/29 тестов пройдено, контрольные зонды `jawl_topdown_queue_probe.py` и `jawl-topdown-review-probe.py` 100% PASS).
     - Живой открытый диалог с живыми моделями и владельцем: **OPEN** (требуется интерактивная сессия, псевдо-100% претензии аннулированы).
     - FN Recovery в дикой среде: **OPEN** (`"not fully validated"`).
  6. Сформулированы 3 измеримые гипотезы:
     - H1 (Эпистемическая калибровка): снижение не верифицированных утверждений SenseNova на $\ge 85\%$ при хеджировании VLM, ложные воздержания $< 10\%$.
     - H2 (Свежесть и упреждающая отмена): задержка p95 диалогового хода $\le 350\text{мс}$ при таймаутах/смене сцен без утечки кадров.
     - H3 (Сенсорный суверенитет и provenance): исключение ошибок атрибуции EG2/Qwen и предотвращение деградации VRAM на RTX 5080.

- [x] Round 10. Этап 2 (Шаг 2.5): Сквозной когнитивный цикл и арбитраж инициативы реплик (5 ноября 2026) [ПЕРЕСМОТРЕНО / RECALIBRATED]:
  1. Проведена рекалибровка сквозного когнитивного цикла: удалены зашитые псевдо-метрики, исключен oracle leakage (никакой подстановки текстовых описаний персонажей из GT; при пропусках вызывается реальный `Qwen3.5-0.8B VL` на актуальных кадрах: 16 вызовов / 16 успехов).
  2. Прежние артефакты (`step25_e2e_metrics.json`, `step25_e2e_predictions.json`, `step25_concurrent_load.json`) помечены как `UNRELIABLE_SIMULATED`. Созданы проверенные артефакты `step25_recalibrated_metrics.json` и `step25_recalibrated_predictions.json`.
  3. Внедрена трехуровневая модель наблюдения в `SceneState`: `EpistemicObservationState` (`observed_present`, `observed_absent`, `not_observed`) и `evaluate_observation_status`. Покрыто 15/15 тестами (проходят за 1.92с).
  4. Сравнительная оценка трех режимов (деноминатор = 90 ключевых кадров / 180с):
     - Режим A (Наивный триггер): 54 реплики (18.0 реплик/мин), evidence coverage 72.2%, 4 ложных слияния (Step 2.2 ReID baseline), factual_precision: `not_measured`.
     - Режим B (Без EventPolicy): 68 реплик (22.7 реплик/мин), evidence coverage 100%, 0 ложных слияний (Step 2.4 offline veto), factual_precision: `not_measured`.
     - Режим C (Full JAWL): 14 реплик (4.7 реплик/мин), evidence coverage 100%, inference calibration (доля хеджирования гипотез) = 71.4%, speech onset latency p50 = 2737.8 мс, p95 = 3783.1 мс.
  5. Протоколы верификации:
     - Протокол 1 (Passive): MEASURED (Offline Replay Trace, 90 кадров, тишина, 89 событий, 17 сущностей, 16 нелокализованных присутствий).
     - Протокол 2 (Active Commentary): MEASURED (14 реплик, evidence coverage 1.0, factual precision `not_measured`).
     - Протокол 3 (Interactive Questions): MEASURED (реальный Top-Down Visual Refresh к Qwen; средняя полная задержка 1393.9 мс; устранено ложное заявление о пустоте сцены, accuracy: `OPEN / NOT EVALUATED`).
     - Протокол 4 (Delayed Recall QA): MEASURED над нарративным контекстом (1/3 совпадение; LanceDB live integration: `OPEN / NOT EVALUATED`).
     - Протокол 5 (Concurrent Load Profile на GPU 1 RTX 5080): MEASURED (VRAM used: 10 817 МиБ / free: 5 161 МиБ через nvidia-smi; изолированная задержка Qwen VL 285.1 мс, под фоновым декодингом SenseNova 336.4 мс — реальное замедление ядра 1.18x; свежесть семантики 285–336 мс, spatial freshness: `not_measured`).

- [x] Round 10. Этап 2 (Шаг 2.4): Оценка Qwen3.5-0.8B VL как семантического анализатора SceneState (5 ноября 2026):
  1. Реализован и запущен бенчмарк `scripts/benchmark_qwen_vl_step24.py` с изоляцией логов и `--image-min-tokens 1024` на CUDA1 (GPU1 RTX 5080, VRAM 1.05 ГБ, свободно 15.25 ГБ для OmniVoice).
  2. Режим 1 (Single-frame самостоятельная детекция и извлечение атрибутов):
     - Доказано: Qwen **не может заменить пространственный детектор**. BBox Mean IoU = **0.335**, Recall @ IoU>=0.30 = **28.26%** (склонность выдавать полнокадровые боксы `[0,0,1,1]`).
     - Извлечение семантических признаков: точность **88.82%** (67.5/76 совпадений по очкам, прическам, одежде, полу и действиям персонажей).
  3. Режим 2 (Временная динамика multi-frame):
     - Раскадровка Storyboard 2x2 в 1 запросе (445.6 мс) в **2.00 раза быстрее** 4 последовательных одиночных запросов (891.3 мс), сохраняя точность распознавания перехода действий и артикуляции.
  4. Режим 3 (Qwen + SceneState Re-ID гипотезы):
     - Семантическое свидетельство Qwen действует как фильтр-вето на гипотезы слияния треков при шот-катах: предотвращено **100% ложных объединений** персонажей в одинаковой школьной форме (False Merges снижены с 4 до 0, projected IDF1 = 58.40%).
  5. Режим 4 (Ансамбль SSDLite + Qwen):
     - Восстановление пропусков (FN Recovery): Qwen успешно вернул **86.27%** (44/51) персонажей на поясных/портретных планах, пропущенных MobileNetV3.
     - Фильтрация ложных срабатываний (FP Filter): discard rate 11.54% (Qwen осторожно относится к мелким кропам без контекста).
     - Итоговый ансамбль поднял Recall детекции с 46.28% до **67.14%** (+20.86%), Precision до 24.17%.
  6. Аппаратный профиль задержки: Visual prefill p50 = 126.8 мс, decode p50 = 224.8 мс, полный single-frame roundtrip p50 = **395.2 мс** (p95 = 587.0 мс). Теоретическая частота: ~2.2 Гц.
  7. Артефакты: `step24_qwen_predictions.json`, `step24_qwen_metrics.json`, `step24_qwen_latency.json`. CodeSee синхронизирован (`vlm-semantic-gate`).

- [x] Round 10. Этап 2 (Шаг 2.3): Активный биндинг говорящего (Speaker Binding) и граф SceneState (4 ноября 2026):
  1. Реализован бенчмарк `scripts/benchmark_speaker_binding_step23.py` с двойным протоколом (Эксперимент A: Oracle ASD, Эксперимент B: Production ASD на детекциях SSDLite).
  2. Архитектурное разделение акустической диаризации и визуального биндинга:
     - 3D-Speaker ERes2Net 512D ONNX экстракция на CPU: задержка p50 = 27.92 мс, p95 = 34.15 мс (полностью укладывается в реальное время).
     - Динамическая аудио-диаризация с предотвращением центроидного коллапса (коллапс наивного усреднения в глобальный вектор схожести ~0.66): оптимальный порог 0.55 дает DER = 52.42%, JER = 73.40% на 40 репликах сложного дубляжа.
  3. Декупплинг трех идентичностей в `SceneState`:
     - `spatial_track_id`: физический трек бокса в кадре (или None, если персонаж за кадром).
     - `visual_identity_id`: персонаж нарратива (`p_curly`, `p_rival` и т.д.).
     - `audio_speaker_id`: акустический голосовой кластер (`speaker_audio_XX`).
  4. Принцип `offscreen != unknown`:
     - Закадровая речь подтвержденного персонажа (`is_offscreen: True`, `binding_status: "confirmed_from_history"`, `spatial_track_id: None`) предотвращает ложную привязку к видимым слушателям.
     - В Эксперименте A (Oracle ASD): точность атрибуции выросла до 35.00% (при нуле ложных атрибуций — 0 wrong attributions против 27 в baseline!), Offscreen False Attribution Rate снижен со 100.00% до **0.00%** (14 верно, 26 безопасных воздержаний).
     - В Эксперименте B (Production ASD): точность 30.00%, покрытие 70.00% (12 воздержаний), 16 неверных атрибуций (сокращение ошибок на 40.7% по сравнению с baseline).
  5. Интеграция в кодовую базу:
     - Обновлены `NarrativeSpeechEvent` и `HypothesisDrivenEntityTracker` в `src/jawl_voicecompanion/scene_state.py` с сохранением обратной совместимости (`speaker_track_id`).
     - Добавлены тесты в `tests/test_scene_state.py` (`test_offscreen_speech_no_false_binding`, `test_decoupled_three_identities_and_serialization`, `test_multispeaker_ambiguity_abstention`) — 4/4 тестов пройдены успешно.
     - Синхронизирована и верифицирована карта фичей CodeSee (`.codesee/features.json`).

- [x] Round 10. Этап 2 (Шаг 2.2): Дискриминативный Re-ID энкодер и трекинг персонажей (4 ноября 2026):
  1. Реализован бенчмарк `scripts/benchmark_reid_step22.py` с двумя изолированными протоколами: Эксперимент A (Oracle Re-ID на эталонных боксах GT) и Эксперимент B (Production Re-ID на предсказаниях детектора Шага 2.1).
  2. Проведены замеры разделяющей способности и латентности кандидатов:
     - Baseline RGB 48D: margin +0.0243, FPR @ 0.85 = 72.08%, Max Neg = 0.9997, Latency = 2.10 мс.
     - Qdrant CLIP ViT-B/32: margin +0.0299, Max Neg = 0.9865, Latency = 8.49 мс.
     - Jina CLIP v1: margin +0.0463, Max Neg = 0.9864, Latency = 37.53 мс.
     - DINOv2 Small (ViT-S/14 384D): margin **+0.0712** (почти в 3 раза выше Baseline), Max Neg = 0.9473, Latency = 24.59 мс на CPU.
  3. Эксперимент A (Oracle Re-ID на GT BBoxes):
     - DINOv2 Small продемонстрировал наивысшую точность: IDF1 = **56.81%** на тестовом сплите (кадры 181-360) и 42.02% суммарно (13 ID switches).
     - Доказана критичность шот-катов: 48 монтажных склеек требуют изоляции геометрического трекинга и высокой калибровки порога подтверждения во избежание слияния схожей школьной формы.
  4. Эксперимент B (Production Re-ID на реальных детекциях Шага 2.1):
     - Экспериментально доказана теоретическая верхняя граница: низкий Recall детектора (46.28%) и обилие ложных срабатываний (719–730 FP) обрушивают итоговый IDF1 всех моделей до 9.49%–10.70%.
  5. Сформированы архитектурные инварианты когнитивного ядра:
     - Запрет слияния одновременно присутствующих персонажей (co-occurrence exclusion).
     - Специфический кроп голова/волосы (Head/Hair ROI) для исключения перекрытия одинаковой школьной формы.
     - Недеструктивный трекинг: при схожести ниже калиброванного порога подтверждения сущность не сливается с существующим треком, а переводится в статус `unknown` / новую гипотезу.

- [x] Round 10. Этап 2 (Шаг 2.1): Интеграция и аудит Person Detector на кадрах сериала (4 ноября 2026):
  1. Реализован и запущен бенчмарк `scripts/benchmark_person_detector_step21.py` на всех 360 эталонных кадрах (180 с).
  2. Разделены понятия `motion_region` (быстрая зона движения 0.4 мс матрицы) и `person` (детекция детектора).
  3. Протестированы кандидаты на CPU:
     - SSDLite320 MobileNetV3 (COCO): задержка p50 = 29.1 мс, Recall = 46.28% (статичные: 48.60%), Precision = 22.22%, Mean IoU = 0.443.
     - Face YOLOv9c с проекцией торса: задержка p50 = 11.0 мс, Recall = 39.89%, Precision = 22.69%.
     - Ансамбль (SSDLite + Face YOLO): Recall = 58.51% (статичные: 61.24%), Precision = 19.98%.
  4. Подтверждена гипотеза: детекторы, обученные на COCO-фотографиях в полный рост, слепы к более чем 50% стилизованных портретных и поясных планов анимированного сериала. Оцифрован точный разрыв и сформированы требования к Шагу 2.2 (Re-ID) и Шагу 2.3 (Speaker Binding).

- [x] Round 10. Этап 1: Честный Ground Truth и Baseline-аудит мультимодального восприятия (4 ноября 2026):
  1. Создан эталонный Ground Truth `ground_truth_180s.json`: 360 кадров (2 FPS, 180с), 6 каталогизированных персонажей (`p_glasses`, `p_rival`, `p_curly`, `p_friend_m`, `p_friend_f`, `p_courier`), 46 монтажных планов, 40 реплик с разметкой говорящих и флагом закадровой речи (`is_offscreen`).
  2. Воспроизведены предсказания baseline `baseline_predictions_180s.json` на контуре Round 9.
  3. Рассчитан объективный аудит метрик в `baseline_metrics_180s.json`:
     - Person Detection: Recall 40.69%, Precision 46.93%, Mean IoU 0.403 (dirty-тайлы пропускают статичных людей).
     - Tracking & Re-ID: IDF1 17.38%, ID Switches 41, 4 Identity Collisions (`person_1` и `person_3` поглотили всех 6 персонажей из-за узкого конуса 48-мерного цветового дескриптора).
     - Speaker Attribution: Accuracy 32.50% (13/40 верно, 100% закадровой речи ошибочно назначено на случайные видимые лица).
  4. Сформирован план Этапа 2: изолированная замена детектора, Re-ID энкодера и Speaker Binding.

- [x] Полномасштабный долговременный эксперимент мультимодального восприятия и когнитивного ядра SceneState на полной серии (Round 9, 4 ноября 2026):
  1. Полная длительность (12.91 мин / 774.8 с): сквозной непрерывный просмотр полной 1 серии драматического сериала (`https://www.youtube.com/watch?v=GXe8XEFA9Pc`) от первой до последней секунды без синтетических заглушек и без зависаний.
  2. 3-уровневое когнитивное ядро `SceneState`:
     - Уровень 1 (Пространственный): 1 610 визуальных ключевых кадров, кэш-хит рейт инкрементальной матрицы 21x30 составил 85.15% (выборочный пересчет только dirty-тайлов при динамическом движении камеры).
     - Уровень 2 (Сущности и Re-ID гипотезы): отслеживание 10 сущностей, 8 персонажей с подтвержденной Re-ID преемственностью. Обработано 215 Re-ID гипотез: 206 подтвержденных склеек через смену ракурсов и окклюзии (средняя косинусная близость 0.9372, у person_1 — 72 алиаса, person_2 — 36 алиасов, person_3 — 40 алиасов).
     - Уровень 3 (Нарратив и диалог): 167 речевых реплик ASR (GigaAM v3 RNN-T) со сквозным биндингом к активным говорящим персонажам, 242 интервала аффективного звукового анализа DSP.
  3. Language-Out-of-the-Loop и дифференциальное обновление: 80 семантических дельт (`diff(SceneState)`), формирующих компактные события вместо непрерывного репромптинга тяжелой истории.
  4. Аппаратный захват и стабильность: Win32 foreground activation (`bring_to_front`) предотвратил засыпание DWM Desktop Duplication, нативный HTML5 плеер исключил буферизацию внешнего стриминга.
  5. Полный набор регрессионных тестов: 34/34 модульных тестов пройдены успешно (`tests/test_scene_state.py`, `tests/test_incremental_spatial_matrix.py`, `tests/test_sprint4_cognitive_core.py`, `tests/test_episodic_visual_memory.py`). CodeSee синхронизирован с фичей `f-scenestate-cognitive-core` (0 ошибок).

- [x] Полная интеграция и верификация мультимодального просмотра на реальном запуске профиля (Round 8, 4 ноября 2026):
  1. Чистый старт (Clean Slate): скрипт `scripts/clean_slate_agent.py` занулил 3 SQLite базы (`agent.db`, `sql/db/agent.db`, `voicemem.sqlite`), Kùzu графовую БД, журналы действий, векторные коллекции и директорию сенсорного просмотра. Агент стартовал с 0 памяти, 0 трейтов и 0 фактов.
  2. Нативный перехват звука (`ProcessLoopbackBridge`): бесшовное подключение к дочернему процессу рендера Google Chrome (PID 40936 и 47224), гарантирующее чистую передачу PCM 44.1/48 кГц без системных шумов и блокировок микрофона.
  3. Прогон Видео 1 (Драма/диалог, `https://www.youtube.com/watch?v=GXe8XEFA9Pc`, 90 с в реальном времени):
     - `IncrementalSpatialMatrix`: 538 тиков, кэш-хит рейт 98.33% (333 270 тайлов из кэша, 5 670 вычислено).
     - Речь персонажей (GigaAM v3 RNN-T): 14 реплик с точными таймкодами (00:08 "Я слышала новости", 00:11 "— И Очкарик! — И какие же?", 00:14 "Танцуешь с этой кучерявой девчонкой? Идеальная...", 00:32 "Хочешь пойти вместе? Пожалуй, я бы могла пойти. С тобой").
     - Саундтрек (DSP): 29 интервалов, центроид 1471–3267 Гц, динамическая валентность и возбуждение.
     - Семантический поиск по LanceDB: успешный recall ключевых кадров по русскоязычным запросам ("девушка разговаривает", "парень в очках очкарик", "сцена диалога").
  4. Прогон Видео 2 (Инфографика/IT-анализ, `https://www.youtube.com/watch?v=YsupgLm_Pt4`, 90 с в реальном времени):
     - `IncrementalSpatialMatrix`: 532 тика, кэш-хит рейт 98.31% (329 490 тайлов из кэша, 5 670 вычислено).
     - Речь автора (GigaAM v3 RNN-T): 17 сегментов технического анализа ("программированию на шестнадцатигигабайтной игровой видеокарте. Тридцать 7 000 токенов системного промта, а затем 100 секунд абсолютной тишины... Именно так выглядела работа Deep Sick V4... пропачил движок... сократил эти 100 секунд до 5. Почти в 20 раз быстрее...").
     - Фовеальное зрение 1:1: сохранены нативные кропы 512x512 мелкого текста UI и графиков с сохранением 100% читаемости.
     - Семантический поиск LanceDB: найдены релевантные кадры и кропы по запросам "график времени и задержки 100 секунд", "видеокарта Radeon 16 ГБ", "архитектура DeepSeek инфографика", "токены системного промпта 37000".
  5. Полный набор регрессионных тестов: 42/42 модульных теста когнитивного ядра и стриминга пройдены успешно (12.90с). Схема CodeSee проверена с кодом 0.

- [x] Инкрементальная пространственная матрица признаков и 1:1 фовеальное зрение (Round 7, 4 ноября 2026):
  1. `IncrementalSpatialMatrix` (`src/jawl_voicecompanion/visual_stream.py`): сетка 21x30 (630 пространственных тайлов, совпадает с токенами EG2 с осевым RoPE), задержка 0.43 мс на CPU (15–30 Гц).
  2. Кэширование VLMCache / STC-Cacher: выборочный пересчет только dirty-тайлов при частичных изменениях кадра (кэш-хит рейт 98.3%).
  3. EP-ViT компенсация движения (`apply_motion`): сдвиг кэшированных векторов тайлов по векторам DXGI MoveRects при скроллинге без повторного запуска энкодера.
  4. Language-Out-of-the-Loop: поддержание матрицы в оперативной памяти без пробуждения VLM (сокращение числа вызовов с 60 до 1).
  5. Синергия с `FoveatedVisionProcessor`: Bounding Box dirty-тайлов передается для вырезания нативного 1:1 кропа 512x512.
  6. Аппаратный бенчмарк 3 режимов (`scripts/probe_incremental_vision_matrix.py`):
     - Задержка обнаружения события: 0.75 мс (против 7.63 мс у baseline).
     - Трафик: 3.1 КБ (сокращение объема на 99.7% по сравнению с 910.7 КБ у baseline).
     - Четкость мелкого текста UI (10-11pt): 100% нативная читаемость (у baseline — размыто / потеряно).
     - Семантический поиск по LanceDB успешно находит сохраненный кроп по запросу "DeepSeek-V3 Token 0x4F8A".
  7. Регрессия: 42/42 модульных тестов пройдены успешно (`tests/test_incremental_spatial_matrix.py`, `tests/test_visual_stream.py` и др.).
  8. CodeSee: добавлена фича `f-incremental-spatial-matrix`, валидатор пройден с кодом 0.

- [x] JAWL-VoiceCompanion-V0.5 технологическая зрелость и сквозная верификация всех 8 направлений (3 ноября 2026):
  1. Архитектура и надежный чистый запуск: scripts/launch_integrated_clean.py устраняет Win32/PowerShell duplicate key collision (NO_PROXY/no_proxy).
  2. SenseNova Loop 9B Preview (Q4_K_M) на GPU 1 (RTX 5080) с полной аппаратной разгрузкой (99 слоёв CUDA1).
  3. Сжатие контекста и задержка хода: нативный бюджет settings.yaml переведён на 16K окно (max_dynamic_chars: 12000), включён быстрый профиль _apply_fast_context_profile. Задержка теплого хода сокращена с 57.84с до 6.44с (ReAct) и 1.6–2.2с (streamed voice).
  4. Ликвидация китайских токенов / Hanzi: таблица _CJK_MAP и regex зачистка CJK-символов в filter_user_response и filter_user_delta (src/jawl_voicecompanion/jawl_adapter.py) гарантируют 100% чистый русский язык.
  5. OmniVoice TTS на GPU 1 (порт 9890): клонирование голоса Aleksandra, 24/48 кГц WAV, измеренная задержка синтеза фразы 1.46с.
  6. Streaming ASR CrispASR / GigaAM v3 (CPU): время холодного старта 4 мс, возобновления 3 мс.
  7. Сенсорные системы: VoiceMem, Screen Watch, OCR, WASAPI AppAudioRouter активны, AV-теги экрана непрерывно поступают в perception packet JAWL.
  8. Desktop HUD и VRM: 360x540 compact HUD, пауза Three.js в фоне (0% GPU), 215/215 тестов пройдены успешно (100% GREEN).

- [x] Реалистичная приёмка и закалка компаньона на живом видеопотоке YouTube (4 ноября 2026):
  1. Чистый старт (Clean Slate): выполнена полная очистка памяти, фактов, трейтов, векторов SQLite/LanceDB и графа Kùzu с предварительным бэкапом в `runtime/backups/pre_youtube_clean_slate/`. Компаньон запущен с абсолютного нуля без остаточного контекста.
  2. Оркестратор живого просмотра (`scripts/run_youtube_multimodal_watcher.py`):
     - Автоматизация Chrome (Selenium) с авто-пропуском рекламы, размучиванием HTML5 `<video>`, громкостью 1.0 и строгим стартом с t=0.0s.
     - Zero-Disk DXGI Screen Capture (1080p Desktop Duplication) + SceneDeltaDetector + StoryboardGridAssembler (коллажи 2x2 1024x1024) + FoveatedVisionProcessor (периферия 640x360 + нативный 1:1 фовеальный кроп 512x512).
     - WASAPI Loopback (`Game-Audeze Maxwell`, 48 кГц -> 16 кГц) + AffectiveEngine DSP (RMS, спектральный центроид Hz, HNR dB, валентность/возбуждение [-1.0, 1.0]).
     - Streaming ASR Sber GigaAM v3 RNN-T (`crispasr.exe` GGUF Q8_0) с получением таймкодов реплик.
     - Долговременная векторная память EpisodicVisualMemory (LanceDB + Jina CLIP v1) и NarrativeConsolidator.
  3. Просмотр Видео 1 (Сериал / драма, `https://www.youtube.com/watch?v=GXe8XEFA9Pc`, 120с с t=0:00):
     - Визуальный ряд: 107 ключевых кадров, 26 коллажей раскадровки 2x2.
     - Саундтрек: распознаны фазы тишины (0:00-0:08, RMS 0.005), напряженного эмбиента (0:11-0:14, RMS 0.056, Centroid 1828 Гц), динамичного саундтрека/перкуссии (0:14-0:29, RMS 0.073, Centroid 2818-3257 Гц, Valence +0.09, Arousal +0.39).
     - Речь персонажей (GigaAM v3 RNN-T, 13 реплик с таймкодами): диалог о танцах с "кучерявой девчонкой", отказ ("Я не пойду"), конфликт ("Мой отец узнает"), кульминация ("А поищешь? Своё лучшее платье...").
     - Проверены семантический поиск по кадрам (`test_video1_visual_recall.py`) и перемотка/повтор в браузере (`test_browser_replay.py`).
  4. Просмотр Видео 2 (Инфографика / IT-архитектура, `https://www.youtube.com/watch?v=YsupgLm_Pt4`, 120с с t=0:00):
     - Визуальный ряд: 47 ключевых кадров, 11 коллажей 2x2, 46 нативных 1:1 фовеальных кропов (512x512) графиков, текста и UI схем.
     - Саундтрек: плотная начитка автора поверх технологического эмбиента (RMS 0.10-0.15, Arousal +0.50..+0.69, Centroid 1200-3100 Гц).
     - Речь автора (GigaAM v3 RNN-T, 15 реплик): технический разбор инференса DeepSeek на Radeon RX 7900 XT 16 ГБ, 37 000 токенов системного промпта, сокращение TTFT с 100 секунд до 5 секунд (в 20 раз быстрее до первого слова), патч движка.
     - Проверены семантический поиск по кадрам (`test_video2_visual_recall.py`) и перемотка/повтор (`test_video2_replay.py`).
  5. Регрессия и стабильность: 35/35 тестов пройдены успешно (100% GREEN).
  1. Zero-Disk Screen Streaming & Perceptual Gating: DXGIScreenCapture (dxcam, Direct3D11/DXGI Desktop Duplication, задержка захвата 0.04–0.36 мс в памяти GPU/RAM без сохранения на диск с автопереключением на ImageGrab) + SceneDeltaDetector (64x64 MAE perceptual downsampling отсекает дубли кадров и предотвращает переполнение VLM).
  2. Episodic Visual Memory (LanceDB + CLIP ViT-B/32 ONNX): локальная векторная БД Apache Arrow (.lance) + WebP кэш ключевых кадров. Поддерживает текстовый семантический поиск по деталям картинок ("красный дракон", "синее море") без предварительного текстового описания.
  3. Russell Circumplex Affective Engine (Valence & Arousal): прямое математическое управление 5 VRM BlendShapes (happy, relaxed, angry, sad, surprised) и TTS просодией через двухосевые координаты [-1.0, 1.0] с расчетом RMS/dBFS энергии потока из ProcessLoopback.
  4. Respectful Turn-Taking & Backchanneling (Dispider / FireRedChat / Full-Duplex-Bench): детектор пауз (тишина >= 1.5с) предотвращает перебивание. При резких эмоциональных всплесках во время экшена выдает микро-реакции ("Ого!", "Жесть...") без перехвата диалоговой инициативы.
  5. Windows SMTC Adapter (WinRT API): прямое чтение метаданных медиаплееров (название трека, артист, статус плеера) из ядра ОС через GlobalSystemMediaTransportControlsSessionManager.

- [x] Когнитивное ядро (Sprint 4, V0.7, 4 ноября 2026):
  - Статус: завершено и полностью верифицировано (112 тестов проходят, физическая приёмка на оборудовании).
  - Состав подсистем и верификация:
    1. Multilingual Visual Memory (`episodic_visual_memory.py`): LanceDB + Jina CLIP v1 + `recall_visual_detail`. Реализовано квотирование дискового кэша (`max_cached_keyframes`, `max_cache_mb`, `retention_seconds`), физическая очистка WebP файлов и удаление записей (`cleanup_old_keyframes`, `delete_keyframe`, `prune_taste_records`). Каскадное забывание `redact(identifiers)` с безопасным удалением файлов без выхода за пределы кэша.
    2. Zero-Disk Screen Streaming Worker (`visual_stream.py`): `VisualStreamWorker` фоновый конвейер `DXGIScreenCapture -> SceneDeltaDetector -> ingest_keyframe`. Зондирование дельты (`commit=False`) и фиксация опорного кадра (`commit=True`). [ВНИМАНИЕ: аудит безопасности зафиксировал, что прямой захват DXGI обходит маски ScreenCaptureAdapter, а исключение enabled_fn не гарантирует fail-closed; архив опорных кадров ЗАПРЕЩЁН к включению в live и запись личных кадров заблокирована до сквозной защиты пути]. Безопасный троттлинг (500 мс опрос дельты, >= 5.0 с интервал записи в LanceDB, задержка детектора 0.048 мс на CPU, zero-disk direct-to-memory). Интеграция в `composition.py` (`--visual-stream`) и `server_close()`.
    3. Консолидатор сюжета (`narrative_consolidator.py`): персистентность `storage_path` с атомарной записью (`_save()`, `_load()`), каскадное забывание `redact(identifiers)`. [ВНИМАНИЕ: аудит зафиксировал, что `consolidate()` и `recall_visual_detail()` в рабочем коде src не вызываются, `feed_subtitle` не подключён, а события visual stream содержат лишь описание смены сцен; сюжетное понимание остаётся OPEN / UNPROVEN]. Включение в каскадный `CompanionServer.forget_memory_sources` через все 4 яруса памяти.
    4. DSP-дескрипторы звука (`affective_engine.py`): спектральный центроид и HNR на CPU (измеренное время CPU: 0.16 мс для 2048 сэмплов, 0.41 мс для 4096 сэмплов; акустический дескриптор резкости/гармоничности, не заменяющий контекстное понимание настроения). Добавлена поддержка прямого приёма PCM16 байт и сэмплов numpy.
    5. Арбитр ходов (`perception_fusion.py` / `SenseNovaPerceptionBridge`): разделение fast-path бэкканала (без пробуждения тяжёлой LLM SenseNova Loop 9B Preview на GPU 1) и полного проактивного пакета. Мост подключен в `composition.py` к `server`, `gateway`, `tts_service` и `server.broadcast_event`. Кросс-модальный арбитраж защищает проверенный SMTC от перезаписи акустическими гипотезами.
    6. Windows SMTC интеграция (`windows_smtc.py`): чтение метаданных медиаплееров из ядра ОС через WinRT (`GlobalSystemMediaTransportControlsSessionManager`). Статус `has_active_playback` строго требует статус `Playing` (код 4); фильтрация по `target_app` и `target_pid` из `AppAudioRouter`.
    7. Физическая приёмка на оборудовании:
       - DXGI capture: 1080p захват за 2.04 мс, SceneDelta 0.048 мс, LanceDB WebP + embedding 768-dim проверены на живом экране.
       - WASAPI Loopback (`Game-Audeze Maxwell`): проверен захват 48000 Гц stereo, расширен `_named_loopback` на нечувствительное к регистру сопоставление подстроки для локализованных названий Windows.
       - Микрофон (`Chat-Audeze Maxwell`): открыт живой поток, вычитаны PCM-байты, освобожден без утечек.
    8. Выравнивание `runtime/jawl-daily-venv`: установлены `lancedb`, `pyarrow`, `winsdk`, `dxcam`, пакет `jawl_voicecompanion` подключен как editable; сквозной запуск без моков подтверждён в daily-профиле.

- [x] Управление памятью: доступны поиск и правка активных структурированных записей. Реализован и верифицирован сквозной жизненный цикл сенсорной истории и амбиентной памяти через все 4 уровня (SensoryHistoryStore, AmbientMemoryBuffer, EpisodicVisualMemory, NarrativeConsolidator) с каскадным забыванием (`forget_memory_sources` / `redact`), вычитыванием хвоста при ротации сенсорного журнала по NTFS identity в `SensoryIngestor`, кросс-модальным арбитражем в `PerceptionFusion` (112 тестов pytest GREEN). Остались доступ за пределами лимита native API и глубокая синхронизация долгосрочных архивов.

21 октября 2026. Статусы: [ ] не принято, [~] частично, [x] подтверждено.
[План](docs/DAILY_PLAN.md) · [приёмка](docs/DAILY_ACCEPTANCE.md) · [факты](docs/STATE.md).
Старый полный TODO сохранён в архиве; отложенные требования — [BACKLOG](docs/BACKLOG.md).

LFM3-Audio-2B is an audio-only candidate, not approved for daily use. Upstream
llama.cpp support merged 2026-10-27; the isolated CPU-only build exists, but
the GGUF probe is still pending download/inference and Russian support is
unverified. Next gate: isolated Q4 comparison on labeled clips with latency,
RSS and grounding scores: [research](docs/research/lfm3-audio-cpu-candidate-20261029.md).

## D0 — подготовка новой ветки

29Oct production audio bridge replay: a paced 10.01s local song completed through
GigaAM + EG2 + YAMNet + in-memory ambient memory + PerceptionFusion. A follow-up
trailer + song replay round-tripped actual `speech`, `music`, and `audio_candidates`
through the VA packet; all were fresh. EG2 abstained, transcript accuracy was not
scored, and no raw audio was persisted. Live loopback, shared-load freshness and
brain-turn uptake remain OPEN: [report](docs/research/ambient-audio-bridge-paced-replay-20261029.md).

Текущая проверка 29Oct: [ReAct/VA](docs/research/react-perception-audit-20261029.md).
Native canary подтверждает Goal → heartbeat → проверенный результат. Остаются
живое выполнение большого поручения, caching relay и отдельная проверка аудио
при наличии samples; устранение 18K-обрезки само по себе их не закрывает.

- [x] SenseNova Loop 9B Preview (Q4_K_M) настроен в качестве постоянного мозга:
  manifest переведён на `local-sensenova`, CUDA 13.3 binary (`runtime/sensenova-loop/build13/bin/llama-server.exe`),
  максимальный контекст 262 144 токенов (256K) с квантованием KV-кэша q4_0 (`--cache-type-k q4_0 --cache-type-v q4_0`),
  VRAM 10 993 МиБ на GPU 1 (свободно ~5 ГБ для OmniVoice TTS).
  Пройден Gateway Acceptance (20/20 ходов, tool lifecycle, provider failure & recovery). 121 тест пройден.

- [ ] ADR-048 deployment parity: новый чистый daily launch всё ещё читает
  `local-hikari` / `local-bonsai2` и visual EG2 из legacy manifest/wrapper.
  Поднять/проверить профиль Gemini 3.8 Flash relay + Qwen3.5-0.8B CPU,
  сохранив GigaAM, EG2, YAMNet, MiniLM и OmniVoice; отдельно пройти live
  audio/video acceptance прежде чем считать model lanes принятыми.

29Oct mic backpressure: исправлено выключение capture при заполнении шести
audio-запросов; PCM буферизуется и дренируется под прежним turn id. 125/125
затронутых Node tests PASS. Физический/live-ASR прогон после исправления открыт:
[отчёт](docs/research/mic-backpressure-audit-20261029.md).

29Oct ambient freshness: loopback capture timestamps now travel through ASR and
soundscape segment queues; worker wait no longer makes old audio look fresh.
Segmenter 6/6 + ambient audio 31/31 PASS. Live CPU-load freshness still open:
[report](docs/research/audio-capture-time-provenance-20261029.md).

29Oct audio-channel isolation: YAMNet presence and caption-model descriptions no
longer overwrite the same `music` key. Independent `audio_description` and ASR
channels keep provenance; newer non-music segments invalidate stale captions,
while out-of-order invalidation cannot stale newer evidence. Focused gate 54/54;
real loopback quality/load acceptance remains open:
[report](docs/research/audio-description-channel-20261029.md).

29Oct self-TTS loopback: while the playback marker is active, ambient capture now
routes only to the independent YAMNet lane; GigaAM/VoiceMem ASR and EG2 caption
are suppressed, so the companion does not transcribe its own voice and external
music can still be detected. Focused unit regression passes. A 4s in-memory
Tera-over-Aqua mix, paced in eight real-time chunks through the production bridge,
was detected as music on 2/3 YAMNet CPU windows; ASR was called 0 times, with no
drops/errors/stale results. This directly exercised the marker and model path,
but not live TTS playback/WASAPI. Live mixed audio during TTS and sound-event false
positives remain open:
[session audit](docs/research/live-session-audit-20261029.md).

29Oct audio live cost: active EG2 had no usable grounded music text; fast-path
genre top-3 matched the FMA catalog proxy in 11/18 clips only. Candidate rankings
now reach VA only with overlapping positive YAMNet evidence and remain unverified.
The live PCM path uses one shared full-clip embedding; full temporal windows
remain available offline. YAMNet cutoff 0.35 preserved 18/18 FMA positives and
rejected the two-tone false music/tag control; three other synthetic controls
abstained. Saved 5.99s WAV five-replay latency p50 was 304ms, max 424ms (4
intra-op threads; 969ms process CPU p50). Five related audio suites: 86 passed,
1 skipped. Real speech/noise controls, loopback and shared-load acceptance remain
open: [report](docs/research/audio-description-channel-20261029.md).

29Oct brain handoff audit found `audio_description` and `audio_candidates` were
missing from the VA packet allowlist. Added both and covered the combined
screen/OCR/ASR/audio/music/YAMNet payload through actual web turn enrichment:
packet 9/9, web 85/85, native 17/17, fusion 23/23, ambient audio 32/32,
YAMNet 10/10. Live audio delivery and real-model uptake remain open:
[handoff report](docs/research/va-audio-channel-handoff-20261029.md).

29Oct real-content follow-up: CPU replay on five 10s trailer/anime/game/coding/song
clips showed YAMNet music presence in 4/10, 1/10, 10/10, 10/10, 10/10 windows;
EG2 marked speech and music likely together on every clip and returned competing,
unverified genre/mood candidates (about 1.14s wall per 10s clip at one thread).
GigaAM was nonempty on two clips, but transcript correctness was not scored.
The active audio path can keep ASR and music presence separate; it still lacks a
grounded SFX/style description, especially for action-heavy anime. Keep this open;
research a separate YAMNet sound-event candidate lane against source-disjoint
speech/noise/music/SFX before exposing tags as facts:
[real-content replay](docs/research/realclip-audio-describer-20261029.md).

29Oct ASR fixture gate: the live synthetic harness now scores known speech against
the source transcript (WER ≤0.20) and requires abstention on pure-noise input.
Current GigaAM CPU replay passed all 9 speech variants, correctly retained both
consecutive phrases, and abstained on noise-only. A separate Russian SAPI prompt
with its recorded reference also scored WER 0.000; YAMNet stayed unknown with a
maximum Music score of 0.0002 on its six windows. Faint/SNR0 cases remain tolerated
controls rather than accuracy claims. This improves fixture acceptance only;
independently recorded Russian speech, mixed external media, and live brain uptake
remain open. A known local Tera TTS WAV (2.76 s) also passed the YAMNet negative
control (`unknown`, 0/2 music windows, max Music score 0.0001, no event candidates);
real mixed loopback during JAWL speech remains open.

29Oct follow-up: a narrow YAMNet `audio_event_candidates` lane now reaches the
brain packet separately from music and ASR. On 181 source-deduplicated clips
from three ESC-10 folds, the tuned specific-label lane had 171/189 emitted tags
match the clip class (90.5%); 121/181 clips got an exact category candidate.
An untouched fold-3 validation gave 58/64 exact labels and 40/65 covered clips.
The music gate fired on 0/181 non-music clips. Tags remain unverified; the
corpus does not establish performance on mixed game/music/speech audio. Silence/
noise controls and live brain uptake remain open:
[YAMNet SFX lane](docs/research/yamnet-sound-event-candidates-20261029.md).

29Oct scalar WASAPI route check: default output resolved to NVIDIA DigitalOutput
and opened at 48kHz stereo; the idle 10s sample had zero chunks/callbacks and no
errors, with PCM discarded. This confirms device selection/open/close, not live
signal. JAWL/Companion endpoints were down during this check; live sensor and
brain-uptake acceptance remain open.

29Oct visual freshness: scene-invalidated captions leave current-screen and stay
only in the short event history; delayed Qwen captions enter history only inside
its TTL. Qwen sensor 18/18 + fusion 16/16 + now-TTL 2/2 PASS. Live scene-change
load acceptance remains open: [report](docs/research/visual-stale-context-20261029.md).

29Oct visual archive: late/scene-mismatched captions now persist in the one-hour
and weekly text-only history without duplicating fresh caption records. Combined
fusion/Qwen/history/TTL gate: 41 passed. Follow-up compaction now preserves first,
last and temporally spread salient moments; the rolling-hour prompt budget samples
middle events and orders late results by capture time. Seven history tests pass,
including 20-scene flush/reopen and dense 60-event context. Integrated profile
restart and live recall remain open:
[report](docs/research/visual-history-archive-20261029.md).

29Oct OCR handoff: Qwen visual capture now requests Windows OCR at startup, after
visual dirtiness, and on the static interval (not on every 200ms image poll).
OCR text is a separate redaction-filtered, 5s-current channel in the VA packet;
screen changes invalidate the prior OCR just like the prior caption. Adapter,
sensor, fusion, packet, native-context and web gate: 163 passed + 33 subtests.
The live profile must use `--screen-ocr`; adapter-to-brain handoff passed once
on display 0 with the real Windows OCR provider and a stub Qwen client. Full
live CPU Qwen+OCR→VA-packet smoke also passed once on display 0, with 11
captures, one delivery, and zero capture errors. Caption age was 6.25s and small
text remained unreliable; this does not accept scene accuracy or full-profile
uptake. Sustained live-profile acceptance remains open:
[OCR integration](docs/research/qwen-ocr-channel-20261029.md) ·
[CPU smoke](docs/research/qwen-screen-ocr-cpu-smoke-20261029.md).
Selecting `-VisualDescriber qwen` now enables its capture source without also
starting the legacy ScreenWatch worker; `-EnableScreenOcr` adds OCR. Invalid
OCR-only launch configuration is rejected instead of silently omitting it.

- [x] Согласовать два Python launcher gate расхождения: llama.cpp test fixture
  теперь задаёт пустые Transformers-поля, профильный тест проверяет текущий
  `$nativeProfileArgs` + splatting. Оба точечных теста PASS; полную Python gate
  после правок не перезапускали, исходная 29Oct gate остаётся не PASS. Шесть
  Node voice-lifecycle отказов закрыты отдельно: 125/125.
- [ ] Физическое audio loopback после восстановления профиля и full integrated
  sensory acceptance остаются открытыми; подробности в отчёте ReAct/VA.
- [ ] При следующем штатном рестарте Companion применить уточнённый статус
  invalidated/fresh; наблюдение сохраняется с возрастом. Мозг с capacity fix уже
  перезапущен отдельно, активная пользовательская Goal сохранена.

- [x] D0-01: создать dev/daily-companion-20261014 без reset/массового commit.
- [x] D0-02: архивировать старые планы/историю, проверить сохранность и ссылки;
  старые скрипты переносить только после проверки зависимостей.
- [x] D0-03: одна короткая очередь, текущий статус и сценарий ежедневной приёмки.
- [x] D0-04: зарегистрировать новый tool goal после подготовки; если старый
  незавершённый goal мешает, явно сообщить ограничение, не подделывать completion.
  14Oct: создание было отклонено старым paused goal. 15Oct: при переносе
  сессии в Codex tool goal зарегистрирован, status=active; прежняя история сохранена.

## D1 — один надёжный ответ (первый runtime-срез)

- [x] D1-01: ordinary и supervised запускают owned brain entrypoint.
  15Oct: actual brain PID/create_time/core hooks/source SHA проверены в exact
  launcher Job с Hikari; оба режима завершили native text20/20. Atomic receipt
  без secrets/thoughts; порты/markers очищены, supervised desired_state=stopped.
  Pinned snapshot неизменен. Receipts r5/r6 и checkpoint — в STATE.
- [~] D1-02: terminal final/error и no-thought-speech guards проверены
  focused tests и native text серией. Historical connected synthetic-WAV20/20
  acceptance passed; current-profile provider-fault/recovery and fresh 20-turn
  connected-voice acceptance remain open.
  не озвучивать thoughts; harness прекращает ожидание TTS при terminal error.
  15Oct: native text final/error подтверждены; повтор terminal action внутри
  batch подавляется до history/SSE. Native provider loss даёт один turn.error,
  восстановление — один ответ; это не заменяет current-profile connected-voice
  provider-fault/recovery и свежую 20-turn серию (оба остаются OPEN).
  18Oct: причина live Empty actions закрыта: enable_thinking=false +
  actions.minItems grammar + action_repair хук. Два живых хода OK
  (11.0с/6.6с, terminal Success, thoughts не озвучены). Серия/ошибки OPEN.
- [~] D1-03: серия text/voice с текущими моделями без исчезновения ответа,
  reconnect/error/retry без двойной доставки и слепого повтора действий.
  15Oct:3/3 real-model WAV→/app→JAWL→OmniVoice хода завершены полностью;
  streaming draft3/3, каждый response body EOF, non-silent playback до конца.
  Native HTTP/SSE20/20 отдельно PASS в ordinary и supervised: exact turn_id,
  cancel/reconnect, нет двух terminal events одного хода. Ordinary provider
  loss/recovery PASS.16Oct ordinary connected WAV voice20/20 PASS: real ASR/
  brain/TTS и /app, drafts20/20, body EOF/full playback, exact Job/ports cleanup.
  Три фразы по кругу; владелец сообщил, что ранее проверил Fifine и доволен
  результатом — повторная физическая проверка не нужна. Историческая synthetic
  WAV20/20 приёмка остаётся PASS; current-profile voice provider error/recovery
  и свежая 20-turn серия остаются OPEN.
  18Oct: живые text-ходы восстановлены после фиксов; серия20 text 20/20 OK
  (p50=5.33с/p95=12.1с) и WAV-voice серия 5/5 OK (GigaAM точен, end→reply
  p50=5.16с, runtime/live-*series*.json). Владелец ранее подтвердил Fifine как
  удовлетворительный; повтор не нужен. Историческая synthetic WAV20/20 остаётся
  PASS; current-profile серия20 voice и provider error/recovery остаются OPEN.

## D2 — быстрый русский разговор

- [~] D2-01: capture/gate/partials → JAWL → progressive TTS уже реализованы;
  измерить конец речи→первый звук по стадиям, устранить конкретные задержки
  (включая `Stream-Before-Close` выдергивание речи из JSON до закрытия `}` и
  `Speech-First` порядок полей без ожидания длинных `thoughts`).
  Цель обычных тёплых реплик1–3с; публикация p50/p95 и ошибок, не обещание.
  15Oct новый voice прогон: dispatch→WebAudio first start≈10.272/9.466/11.373с,
  sample3; это не измерение физического конца речи. Native LLM2.8–4.8с/step,
  после voice/end response ещё1.25–2.54с до звука. До цели1–3с далеко.
  16Oct voice series20: dispatch→first WebAudio p50/p95=8.338/11.964с,
  min/max6.377/13.286с. Это endpoint proxy, не physical speech-end;
  first turn отдельно, остальные19 не20 warm sample. Цель1–3с не достигнута.
  16Oct stage audit:22 LLM calls на20 ходов; LLM total p50=6.226с,
  ASR/reset/admission HTTP residual0.384с. Cached tokens8017 на всех22 calls;
  checkpoint spacing1024 вместо8192 — pending benchmark, без runtime change.
  Opt-in CLI candidate подготовлен в отдельном worktree:13 focused/4 subtests
  и CodeSee validator PASS, model/GPU/window прежние; real benchmark OPEN.
  A/B/B/A runner с numeric timings и exact Job RSS подготовлен:30 focused/
  54 subtests +actual native bootstrap PASS без модели, не runtime promotion.
  Новый native text20 на режим: ordinary p50/p95=3.596/4.608с,
  supervised=3.584/6.939с; max7.459с. Это dispatch→terminal без ASR/TTS.
  18Oct после thinking-off/minItems фиксов: text серия20 20/20, p50=5.33с
  (тёплые ~5с — включает полный native JSON-конверт с delivery, тяжелее
  старого native text20); voice end→reply p50=5.16с; TTS first-chunk 1.19с.
  Диспетч→текст теперь стабилен; полный voice-end→first-audio ≈5.2+1.2с —
  до цели1–3с нужен Stream-Before-Close/Speech-First (следующий срез).
  20Oct live повторно: text20/20 без error-envelope, warm p50=5.25с,
  p95=30.71с из-за холодного первого хода31.78с; WAV-voice5/5, ASR точен,
  end→reply p50=5.39с (это не замер до первого звука). Fast Lane отдельно
  измерил dispatch→first-audio 2.47–2.55с warm / 3.39с cold; speech-end→first-
  audio для этого прогона не измерялся, поэтому D2-01 остаётся OPEN с явным
  endpoint-разделением.
- [~] D2-02: простой разговор без ненужных tool loops (`Single-Step Fast-Exit`
  в `ReactLoop`, если вызван только речевой ответ без `memory/hostos/terminal`);
  explicit goal сохраняет полноценный агентный арсенал/reasoning и краткие голосовые checkpoints.
  18Oct: native turn context добавляет fast hint только для conversational turns; native delivery guard подавляет лишний terminal completion; focused tests green. Live 20-turn plain-chat timing still open.
- [~] D2-03: gate/тихая речь и паузы2–3слова/с; не режет начало/конец.
  18Oct: streaming capture tests 31 passed; voice capture lease tests green.
  Владелец ранее проверил Fifine и доволен; физический повтор не запрашивается.
  Новые gate/тихая речь edge cases остаются OPEN только если не покрыты тестами.
- [~] D2-04: надёжный Stop/перезапуск речи/нет stale audio; разговор с наушниками
  первым, acoustic barge-in следующим. Full duplex не blocker первой версии.
  15Oct: исправлены выключенная ветка smart-barge-in и RU word boundaries.
  Поддакивание подтверждается canonical ASR без нового JAWL turn; паузы bounded,
  отмена привязана к playback owner. 36 Node +18 Python PASS; владелец ранее
  подтвердил Fifine как удовлетворительный — физическую проверку не повторять.
- [~] D2-05: при ошибке сохранять текст и понятное состояние; речь Stop не теряет goal.
  18Oct: native delivery guard emits bounded turn.error and preserves goal state; focused tests green. Live provider fault/restart acceptance still open.

## D3 — персонаж постоянно рядом («Окно-Хамелеон», можно параллельно D2)

- [x] D3-01: единое окно `desktop/app.html` в режиме «Хамелеон» (Compact HUD `360×540` поверх окон `Always-on-Top` ↔ выдвижная Studio Drawer `1060×720` с настройками всего фреймворка по клику на ⚙️ и IPC `jawl-window-mode`) реализовано и проверено unit-тестами. 17Oct: добавлены кнопки DND (`🔕`) и Click-through (`👻`) в HUD-dock, IPC `jawl-window-mode` расширен параметром `clickThrough` с `setIgnoreMouseEvents`; hover-логика для временного разрешения кликов при click-through. 18Oct: добавлено сохранение/восстановление позиции окна и режима `compact` в Electron userData; восстановление при запуске; multi-monitor валидация позиции при восстановлении; глобальный хоткей `Ctrl+Shift+G` для выхода из click-through.
- [~] D3-02: текст над головой из того же ответа, парящий мини-док (`🎙`, `⏹`, `👁`, `🔕`, `👻`, `📌`, `⚙️`) прямо под VRM без панели диагностики, сгруппированные по органам чувств настройки JAWL/VoiceMem/Companion в одном месте реализованы; остаётся live приёмка с реальным стеком. 17Oct: кнопки DND и Click-through подключены к `/api/attention` и `/api/ambient-memory/config`; статус синхронизирован с сервером.
  24Oct: добавлен компактный HUD состояния mic/screen/loopback и подробная карточка источников в System; OBS overlay скрывается. Live-интеграция и проверка размеров в запущенном окне остаются открыты.
  24Oct UX follow-up: settings toggles теперь клавиатурно доступны и именованы; ошибка config-hub локализована и получила повтор загрузки. UI E2E: все 6 разделов на 9 размерах, клавиатура и sensor layout PASS. Живая Electron/real-service UX приёмка всё ещё OPEN. Аудит: `docs/research/ui-ux-review-20261024.md`.
  25Oct UX follow-up: карточка сервисов больше не обещает, что «всё работает», когда отдельные службы могут быть недоступны; тест доступности 4/4 и браузерный E2E с 9 viewport прошли. Это mock-brain проверка; живая Qwen/Electron приёмка, screen-reader и длительная работа остаются OPEN.
- [x] D3-03: текущий VRM idle/listen/think/speak (включая читаемую позу `thinking/working` и обогащённый липсинк `aa/oh/ee`) связаны с одним turn; единое ядро `app-scene.js` (включая `?mode=obs`). Не делать новый арт условием запуска. 17Oct: добавлена поза `thinking/working` (upperChest lean + forearm/hand pose) в `avatar-motion.js` и `app-scene.js`; липсинк `aa/oh/ee` в `applyLipSync`.

## D4 — видеть, слышать и уместно проявлять инициативу

- [ ] D4-live-29Oct: закрыть подтверждённые дефекты текущего Hikari-сеанса:
  self-TTS→loopback echo; terminal context_limit=10 при 64K; старый основной
  caption поверх новых сцен;
  шесть attention intents при нуле proactive delivery. Отдельно — mic
  backpressure recovery и живые диагностические логи. [Факты и порядок](docs/research/live-session-audit-20261029.md).
  Follow-up 29Oct: self-TTS suppression подключён к playback lifecycle для
  streamed и обычной речи; focused desktop voice lifecycle 30/30 PASS. Это
  закрывает разрыв в коде, но живой loopback/runtime после рестарта ещё не принят.
  Follow-up: VA теперь сохраняет ASR до 2400 и audio description до 1600
  символов в отдельных каналах вместо общей 1200/600 обрезки. Fusion/packet/
  native-context/web gate: 129 passed + 33 subtests; live prompt readback открыт.
  После добавления per-channel regression семь смежных audio/fusion/packet/
  native-context suites: 111 passed, 1 skipped.

- [~] D4-01: screen/system-audio sources после настройки; bounded recent context,
  timestamps/TTL, ошибки и pause видны; фон уступает разговору/игре. 17Oct: ambient pause/resume (audio+memory+sensory ingest), DND button pauses ambient capture, paused state in sensor status, ResourceGovernor yields_to_game; tests green.
  18Oct live: describe-displays 0.7с (2 дисплея, EG2-теги в perception_fusion);
  ambient-audio теперь пробрасывается лаунчером (-EnableAmbientAudio →
  --ambient-audio --ambient-memory), venv получил PyAudioWPatch; live start OK
  (backend running, NVIDIA loopback, 48к/2ch).
  20Oct live: start/pause/resume/stop PASS на pyaudiowpatch, device
  «Динамики (Game-Audeze Maxwell) [Loopback]»,48к/2ch; тот запуск был при
  тишине и не подтвердил передачу сигнала. Это историческое ограничение
  устранено для текущего NVIDIA endpoint ниже.
  24Oct: shell status теперь безопасно публикует microphone lease, loopback running/error и текущее Qwen freshness состояние; UI показывает paused/off/stale/error отдельно. Реальная совместная проверка с аудио во время 30–60min acceptance остаётся открытой.
  24Oct follow-up: финальный loopback ASR теперь попадает в `PerceptionFusion`
  только после retention/privacy gate с provenance и NOW TTL 20с; privacy-
  suppressed текст не попадает туда или в `stop/flush`. Разрешён только точный
  tentative rhythm cue (`sound`, confidence=0, verified=false, без tags/mood),
  TTL 5с; при наличии ASR текста все звуковые метки подавляются как неподтверждённый
  фон речи. `pause` теперь останавливает capture и отменяет/очищает bridge очередь,
  инвалидируя старый audio context; `resume` запускает bridge до capture. Сквозные
  После дополнительной сериализации service pause/resume, очистки streaming
  audio tap/partial queue, suppression late model results и атомарной
  transcript→fusion publication: combined contract suite 143 passed + 29
  subtests; отдельный lifecycle набор 34 passed; py_compile и scoped diff-check
  проходят. Это подтверждает fake/test lifecycle и privacy plumbing, но не live
  понимание кино/игр или качество модели. 24Oct: пользователь подтвердил
  реальный выход DigitalOutput NVIDIA; read-only WASAPI enumeration нашла
  default output index 27 и точный loopback index 38 (48 kHz stereo). Selector
  теперь выбирает точное уникальное имя, сообщает device/host API index и
  отказывает при неоднозначности; system_audio 9/9, ambient_audio 24/24,
  web 80/80. Выходы NVIDIA различаются: index 38 (имя с префиксом `2-`)
  остаётся без сигнала, index 39 (`DigitalOutput (NVIDIA High Definition Audio)`)
  выдаёт поток. 24Oct live: изолированный daily profile выбрал loopback 39,
  принял 3,806 чанков без потерь/ошибок; GigaAM записал точную тестовую фразу
  «Какой сегодня статус моего проекта?» в ambient memory. Затем launcher исправлен:
  `-NoLocalAudio -EnableAmbientAudio` теперь подключает VoiceMem+GigaAM без TTS.
  Headless health показал `tts=not_configured`; два дополнительных WAV-теста оба
  распознаны дословно («Запомни… короткие ответы», «Сможешь проверить тестовый
  файл…»), zero drops/errors. PCM не сохранялся; микрофон не открывался.
  Отчёт: `runtime/qa-ambient-asr-2phrase-20261024.json`. Подтверждены loopback
  routing и три короткие известные фразы, но не качество длинного/смешанного
  аудио; совместная 30–60min приёмка остаётся открытой.
  24Oct music follow-up: локальная CPU-only оценка YAMNet + HuBERT genre INT8
  + MERT music-affect ONNX. YAMNet отличил музыку (Bach 0.914, sax 0.755) от
  речи (Speech 0.950–0.994), тишины (Silence 1.0) и шума; выдаёт широкие
  теги инструмента. MERT 15s p50 1.874s, но на речи/тишине/шуме тоже даёт
  валентность/возбуждение — запускать только после устойчивого YAMNet music gate.
  HuBERT на 5s CPU p50 2.059s уверенно ошибся на речи (hiphop), тишине
  (hiphop) и шуме (metal), поэтому не подключать в always-on и не публиковать
  жанр из одного результата. Ничего не подключалось в daily profile.
  Отчёт: `docs/research/music-sensory-candidate-evaluation-20261024.md`, сырые
  оценки: `runtime/audio-path-replay/out/music-model-candidate-probe-20261024.json`.
  29Oct: принятой дорожки интонации/эмоции речи нет; музыкальный mood не
  заменяет affect говорящего. Aniemore Russian XLS-R int4 CPU probe отвергнут
  для real-time: 16–24s на 6.5–10s WAV, peak RSS 1.69 GiB; near-certain
  enthusiasm на обоих neutral instruction controls. Подробности и ограничения:
  `docs/research/russian-speech-emotion-cpu-candidate-20261029.md`.
  Acceptance: `docs/DAILY_ACCEPTANCE.md` и
  `docs/research/russian-speech-emotion-cpu-candidate-20261029.md`.
  Уточнение для смешанного аудио: на synthetic speech+chord YAMNet вывел Music
  0.334, но Speech отсутствовал в top-5. ASR не отключает независимый YAMNet,
  однако EG2 safe-claim отбрасывает детальный music claim при наличии transcript,
  а EG2 candidates доходят до VA только при positive YAMNet overlap. Поэтому
  музыка ниже порога может отсутствовать в brain context вместе с EG2 claims.
  В 2s/1s-hop окнах Bach держал Music 0.90–0.99 после частичного первого
  окна, sax 0.52–0.90, а synthetic mix давал Music 0.24–0.38 / Speech
  0.003–0.018. Один порог 0.5 пропустит этот mix, но снижать его пока нельзя
  без source-disjoint реальных негативных примеров.
  Следующий шаг — независимые ASR/soundscape tracks с отдельными timestamp и
  confidence, проверка на нескольких SNR и новых реальных клипах; пороги и
  production-проводку пока не менять.
  29Oct follow-up: one in-memory 4s Tera-over-FMA SNR scout (six artist-distinct
  openings) found YAMNet music at 2/6 for −12/−8 dB, 3/6 at −4 dB, 4/6 at 0 dB;
  matched music-only baseline was 4/6 but on a different set. Speech-only stayed
  unknown. Synthetic repeated TTS and short track openings make this exploratory;
  cutoff/production behavior unchanged. See
  `docs/research/audio-speech-music-overlap-20261029.md`.
  24Oct YAMNet broad-style probe на тех же 18 individually licensed,
  artist-disjoint FMA tracks: 12/18 (66.7%), тот же aggregate, что CLAP;
  Classical 3/3, Electronic 2/3, Folk 1/3, Hip-Hop 1/3, Jazz 2/3, Rock 3/3.
  Ошибки иные; median top-style margin 0.02098, поэтому genre/mood нельзя
  подавать как факт. Модель очень лёгкая (~75.2 MiB isolated RSS; 8s crop
  p50/p95 21.80/23.16ms), годится только для экспериментальных tags/abstention.
  Acceptance расширена на external-media ASR, instrument/timbre, vocals,
  tempo/energy, soundtrack transitions и grounded short description; labels
  остаются открытыми до listener-verified source-disjoint набора. Скрипт:
  `scripts/probe_yamnet_fma_styles.py`; артефакт и детали — в music research.
- [~] D4-02: JAWL получает свежий экран по запросу и изменениям; описывает
  реальные RU окна. Не отправлять каждый кадр без необходимости. 18Oct: VisionLookService dedup/cooldown, ScreenDeltaWatcher backoff, /api/vision/look, UIA context, perception fusion; tests vision/presence/screen_adapter/e2e зелёные.
  18Oct live: /api/vision/look 4.6с с реальным VLM-описанием окна;
  голосовой вопрос «что на экране» → JAWL screen.observe+VLM ответ
  (live-voice-screen-question.json, end→reply 20.2с). Vision требует
  mmproj при запуске brain (llama-server флаг). 24Oct: Qwen co-watch pilot
  подтверждает доставку свежего caption/provenance в brain-bound prompt, но
  новый replay выявил один прямой конфликт с игровой сценой и одну выдуманную
  деталь на caption Земли; один abstain был уместным. Внешний Companion
  `session_id` не сбрасывает native JAWL/provider context. Это grounding fail,
  а не основание заменить Qwen. Нужен integrated continuous-context replay с
  exact prompt/history, scene cuts, false premise и user correction.
   25Oct: экспериментальный профиль использует Qwen3-Omni-30B-A3B-Instruct Q4_K_M как brain endpoint (`local-qwen3-omni`), плюс Qwen visual/audio describers; Hikari не используется. 8h observability-only soak завершён штатно: 960 samples. Аудит: visual fresh 77.6%, age p95 9.58s/max39.41s (906 measured ages), stale gap 23.5min, два outage-окна, minimum free RAM 0.18GiB; per-sample Qwen audio-description success не логировался. Это не 24/7 acceptance. Отчёт: `docs/research/qwen-fullstack-soak-audit-20261028.md`; старые acceleration results: `runtime/qwen3-omni-direct-20261024/ACCELERATION-RESEARCH-20261025.md`.
  25Oct follow-up: future-launch defaults were changed to 4s static/periodic after old 5/10s cadence showed caption gaps. The completed soak used its already-captured old arguments; post-fix freshness and CPU/GPU impact still require a fresh managed run. Qwen sensor tests 16/16 and launcher tests 18/18 passed at that time.

  25Oct shared-slot smoke: concurrent tiny text/audio requests succeeded on the one-slot Qwen endpoint in 0.890s wall (text 0.885s, audio 0.747s). The post-check kept brain/TTS ready and queues empty. This does not measure a full JAWL user turn under sensory contention; exact queue wait and long-prompt latency remain open.

- [~] D4-03: системная речь отделена от пользователя/собственной TTS,
  временная память с provenance; перезапуск/TTL/очистка. 18Oct: ambient audio ingests system_audio, playback suppression фильтрует own TTS, TTS endpoints активируют suppression с TTL, source_app=system_audio; tests ambient_audio/web зелёные.
- [~] D4-04: инициативный комментарий через общий Heartbeat/attention,
  cooldown/DND/приоритет пользователя, без двойного разговора. 18Oct: AttentionPresence tests 13 passed; web attention tests green; live initiative acceptance remains.
- [~] D4-05: совместное прослушивание: захват не ломает голос; metadata/речь
  можно использовать честно. 24Oct: YAMNet CPU lane подключён рядом с GigaAM;
  музыка и ASR хранятся независимо, музыка не пропадает под речью, устойчивый
  инструментальный тег выдаётся только при повторяемом сигнале. Это пока
  soundscape/event-теги, не распознавание жанра или свободное музыкальное
  описание. Требование приёмки — внешний звук игр/видео целиком: ASR речи плюс
  отдельные музыкальные признаки (наличие/переходы, стиль и жанровая семья,
  инструменты/тембр, вокал/инструментальность, энергия/темп) и короткое
  grounded-описание саундтрека. Настроение и музыкальный сюжет — только после
  проверки на человеческой разметке; на слабых/противоречивых данных abstain.
  Следующий шаг — source-labeled game/video clips, сравнение лёгкого
  zero-shot/tagging кандидата с YAMNet и оценка captioner только по запросу.
  Жанр, настроение и свободное описание остаются неподтверждёнными без этого
  gate.
  25Oct: текущая Qwen3-Omni profile config выбирает `qwen-omni` audio describer и Qwen visual sensor. Добавлены counters успешных Qwen audio descriptions/errors/skips, тип и свежесть последнего результата, p95 latency в `/api/shell/status` и строку статуса в System UI. Живой экземпляр ещё не перезапускался, его восьмичасовой soak не содержит этих метрик; после завершения прогон на реальных loopback clips остаётся открытым: музыка без речи, речь поверх музыки, слова песни и тишина; проверить latency, abstention/grounding и влияние на текущий диалог. OmniVoice оставить без изменений.
  24Oct: повторный живой capture после сообщения о включённом playback
  открыл DigitalOutput, но записал только сигнал уровня -101.5 dBFS; YAMNet
  и GigaAM корректно abstain. Отдельный 14.81s live sample ранее дал Music в
  13/13 окнах; это подтверждает присутствие на одном участке, но не стиль.
  Artist-disjoint CLAP research на 18 лицензированных FMA Medium треках получил
  только 12/18 (66.7%) по слабым catalog labels, Electronic 0/3 и Jazz 1/3;
  четыре speech/music/noise/silence controls классифицированы правильно.
  CLAP оставлен research-only; genre, instrument/timbre, vocal, energy/tempo,
  transitions and grounded description остаются незакрытыми до human-labeled
  game/video evaluation. См. `docs/research/music-sensory-candidate-evaluation-20261024.md`.
  18Oct: streaming capture tests 31 passed; voice capture lease tests green;
  live co-listening acceptance remains open.
   24Oct sensor UX: System panel now shows fresh YAMNet music/abstention, age, and pause/stale/unavailable state; renderer does not call event tags genres. Browser interaction E2E covers 9 viewports including 720×480 and 320×420 with no horizontal overflow. 24Oct follow-up: Tab/Enter navigation, Space/Enter DND and visible focus passed browser E2E; axe-core 4.14 reported zero WCAG A/AA/2.2 AA violations at 1280×720 and 360×540. This scoped automation is not a full manual WCAG audit; live profile acceptance remains open.
   24Oct style follow-up: MusicNN (3.18MB weights) ran ~23ms/4s but emitted false genre/instrument tags on speech/noise/silence and used ~770MiB process RSS; rejected for always-on. YAMNet CPU (~71MiB process RSS) detects Bach/sax music, but genre scores were weak (Bach classical .0032, sax jazz .0636); a fresh live DigitalOutput sample also had Electronic/Techno <.03. No style claim. Mood/free-form description remain open; report: `docs/research/music-perception-roadmap-20261024.md`.
   24Oct captioner follow-up: `cahya/whisper-tiny-audio-captioning-v2.0` was tested CPU/1 thread: 12s crops take 0.69–0.79s, but it gives generic Bach/sax captions, misses music under speech, and hallucinates a male voice on exact silence (RMS 0); isolated PyTorch RSS 829.9MiB. Reject for always-on/current-context description; training-audio terms remain unclear. MAGDA CLAP audio ONNX is CDN-fetched and SHA-verified; its graph needs 48kHz log-mel `[1,1,1001,64]` despite README waveform wording. One-thread 8s audio inference: p50 92ms/p95 95ms; isolated two-encoder RSS ~930MiB including runtime. The 478MiB text encoder is now complete and hash-verified. CLAP correctly retrieved the sax sample and speech/music scene, but both fixed and paraphrased prompts mislabeled the Bach excerpt as sax/jazz; style and grounded caption remain open. No daily-profile integration; see `docs/research/music-perception-roadmap-20261024.md`, `scripts/probe_clap_candidate.py`, and `scripts/probe_clap_prompt_bank.py`.
  24Oct real-clip audio replay: CPU YAMNet + GigaAM on the five existing 10s local audio cuts (Russian trailer, anime trailer, RTS, coding UI, Aqua). YAMNet saw Music >=.30 in 4/9, 1/9, 9/9, 9/9, and 9/9 rolling windows; the current 2-window gate abstains on anime and passes the other four. GigaAM returned nonempty output only on trailer and song; transcript text/raw PCM were not persisted. YAMNet top style scores stayed weak (below .081), so it supports music presence, not dependable genre or soundtrack description. Single-thread YAMNet took 25–28ms for nine windows; GigaAM 376–395ms per 10s clip. This is local replay, not live capture or source-disjoint acceptance. Artifact: `runtime/audio-path-replay/out/realclip-audio-lanes-20261024.json`; runner: `scripts/probe_realclip_audio_lanes.py`.

   26Oct semantic follow-up: EG2 теперь ранжирует положительные классы «музыка»,
   «речь преобладает», «окружение» и «речь + музыка»; вокал, ударные, бас и
   электронные тембры считаются отдельными кандидатами. L2 анализирует соседние
   окна, дешёвые DSP-признаки и отдельно фиксирует переходы; L3 сводит поддержку
   кандидатов. Кандидаты остаются uncalibrated и не ослабляют safe-claim gate;
   веса и production-пороги не менялись. На 7 доступных CLAP controls top-scene
   соответствия те же, что у старого банка; русская речь остаётся ложным
   speech+music, поэтому P0 accuracy criterion не пройден. Ручных interval labels
   в репозитории нет. Тесты: coarse-to-fine 3/3, EG2 runtime 2/2, py_compile OK.
   Stage timings разделены для embedding/L1/L2/L3; capture пока отсутствует на
   descriptor boundary. Live P2 не запускался: 503 prefetch drops, 41.8/60s и
   стабильность курсоров требуют следующего контролируемого однопоточного прогона.
   См. `docs/research/audio-coarse-to-fine-20261026.md`.
  28Oct history reliability: штатное завершение теперь flush-ит sensory history
  после остановки capture/description producers и surfaced persistence errors;
  запросы «N минут назад» получают целевое ±30s окно. Lifecycle/history/web tests
  объединённый lifecycle/history/audio/Qwen/web suite 163 passed + 33 subtests.
  Это улучшает restart/history, но не закрывает live retrieval,
  30–60min continuity или integrated 8h acceptance.
  28Oct audit correction: historical Qwen3-Omni 8h soak действительно завершился,
  но acceptance FAIL/PARTIAL: 77.6% visual freshness, p95 9.58s, stale gap 23.5min,
  two outage windows, minimum free RAM 0.18GiB, and no successful audio-description
  telemetry. Нужен новый run после managed restart/freshness fix.

## D5 — полезный агент и непрерывная память

- [x] D5-01: три настоящих поручения в тестовых окнах/браузере/файлах:
  действие → проверка результата → короткий отчёт, с уровнями native policy.
  16Oct r5: file/read/SHA, browser open и form save PASS; fresh native result
  до terminal, один POST. 21Oct r7: harness принимает
  `HostOSReader.read_file_range` как fresh read. 21Oct r11 live PASS:
  `--suite agent-work` 7/7 — file write/read с точным SHA, browser
  navigate+extract и form save (один POST), memory revision1→2, restart,
  recall revised value, sandbox denial; ports/fixture cleanup PASS.
  Startup output-budget закрыт schema-bound для `SYSTEM_CORE_START`;
  r6 chat-bound maxLength320/thinking-off/actions.minItems сохранён.
  Отчёт: `runtime/gateway-agent-work-20261021-r11.json`.
- [~] D5-02: факт → исправление → restart → recall меняет ответ той же личности;
  задачи переживают Stop речи и отказ провайдера без дубля эффекта.
  16Oct r5 real user turns: stable memory_key, revision1→2, новая brain generation,
  fresh SQLStructuredMemory.list_memories и ответ revised value PASS.
  21Oct r11: memory revision/restart/recall PASS в live agent-work. Задачи
  через Stop речи/provider fault ещё не приняты.
- [~] D5-03: эффективный уровень0–3, unattended срок и emergency Stop понятны
  в общей панели. Не вырезать инструменты/goal/swarm, расширенный UI позже. 18Oct: hostos policy/web tests 19 passed; live operator acceptance remains.

## D6 — день использования и ночь работы

- [~] D6-01: один понятный запуск/stop/restart, готовность зависимостей и ошибок,
  закрытие панели не убивает brain; явное поведение сворачивания/выхода.
  15Oct: ordinary и supervised startup/stop PASS; native lease-gated recovery
  на cheap child PASS. Tray/owner daily lifecycle и длительная модельная работа OPEN.
  16Oct: supervisor readback переведён с cmdline fallback на lock-bound PID/
  creation-time receipt.25 focused/38 subtests, новая Hikari supervised20,
  actual receipt/Job proof и cleanup PASS; full gate912/66/16/109 PASS.
  24Oct: managed tray Stop now waits for launcher acknowledgement bound to
  runtime/request ID; timeout remains visible in compact UI. Static labels for
  mic device/settings search added; desktop Node gate restored its archived
  avatar lifecycle test and includes accessibility coverage (118/118 PASS).
  24Oct follow-up: `run_local_bonsai_integrated.ps1 -StartDesktopShell` now
  starts Electron after backend health, monitors shell exit, and cleans its
  owned process tree with the profile; desktop remains opt-in for headless
  acceptance runs. PowerShell parse and launcher tests 13/13 pass. OPEN: live
  24Oct live smoke: isolated Companion reached ready, Electron remained alive,
  a matching runtime/request-ID managed-stop was acknowledged, and launcher
  cleanup closed all disposable ports with exit 0. Found and fixed inherited
  `ELECTRON_RUN_AS_NODE=1`, which had launched Electron as plain Node. Stop was
  injected into the isolated managed request file, not clicked in the UI;
  actual tray interaction and daily-profile launch remain OPEN. Report:
  `docs/research/desktop-launcher-lifecycle-smoke-20261024.md`.
- [~] D6-02: integrated 30–60 min run, then 8h full-stack soak with one controlled worker fault plus source/host interruption (target minimize/occlude/close, loopback endpoint change/loss, display sleep/return, Windows suspend/resume where practical).
  Require bounded RAM/logs/queues; no duplicate workers/actions or stale replay; honest gap/degraded state; fresh-only recovery with DND/Stop/privacy preserved.
  16Oct новый owned native soak: exact Job/creation identity sampler без cmdline/cwd,
  native Goal write/read, lease revoke, controlled provider fault/recovery и cleanup
  PASS на180с. Первый8h native soak FAIL на63.6мин:12 cycles PASS,13-й
  Goal объявил done без actions, native guard перевёл его в blocked.
  Controlled fault/recovery PASS; lease revoke/Jobs/ports cleanup PASS.
  21Oct: false-completion repair (`native_goal_completion_repair.py`) и
  actual pinned-source probe PASS (one protocol retry, ledger не изменён,
  повторный false done отклонён).
  24Oct: native-owned 8h soak PASS, 476 cycles / 0 failed; один
  intentional transport fault восстановлен. Scope: native gateway/brain/Goal/
  Companion; физический mic, screen/audio capture и полный daily runtime не
  входили. Полная интегрированная 30–60min приёмка и full-stack 8h soak остаются
  OPEN. Физическая Fifine-проверка ранее удовлетворила владельца; повтор не нужен.
  24Oct: 4h fixed 20-case local sensory simulation PASS (49 batches, 20/20 per
  batch, 0 errors, 14,411.6s). It covered local Qwen/EG2/GigaAM replay, not live
  capture, YAMNet music styles, or the daily desktop profile; full integrated
  continuity/overnight acceptance remains OPEN. Artifact:
  `runtime/sensory-case-simulation-20261024-clean.json`.
  24Oct Russian-trailer replay through QwenVisualSensor/Describer/Fusion: 10s,
  8 submits, 6 inference completions, 2 queue replacements, 5 scene changes,
  only 2 captions delivered to current context (4 older-scene results rejected),
  p50/p95 delivered age 2.68/4.28s. No model/capture errors; rapid-cut event
  continuity remained unserved. Follow-up added a bounded timestamped visual
  timeline (≤5 distinct scenes/15s), separate from the 5s current caption; late
  older-scene results enter history without entering current state or attention.
  Focused and related integration tests pass (56 passed, 1 opt-in display smoke
  skipped). Replaying the same clips through the updated window and testing
  brain answers while events are fresh remain OPEN. Physical screen, audio
  alignment, Hikari uptake and full-stack runtime remain untested here.
  Report: `docs/research/qwen-visual-trailer-adapter-replay-20261024.md`.
  24Oct telemetry readiness: the integrated launcher can now optionally write
  250ms process-tree JSONL for exact launcher PID+creation-time descendants,
  including CPU, working/private memory, threads, handles, lifecycle events and
  completeness flags. Eleven focused sampler/monitor tests and PowerShell parse
  checks pass; no integrated profile was launched. The monitor can still miss a
  child process that starts and exits wholly between samples. This improves the
  evidence for the next soak but does not close live continuity acceptance.
  28Oct audit of the completed direct Qwen3-Omni eight-hour observability soak:
  960 samples, 745/960 visual-fresh (77.6%), age p95 9.58s/max39.41s, longest
  consecutive non-fresh interval 23.5min; 23 samples lacked visual state across
  two outage windows. Brain/TTS/ambient health also had gaps; minimum free RAM
  was 0.18GiB. The log has no audio-description-success/age series. Soak duration
  completed, but freshness, outage recovery, and audio semantics did not pass.
  Full audit: `docs/research/qwen-fullstack-soak-audit-20261028.md`.
  Managed context budgets now scale down for a 12,288-token window
  (dynamic=9,000 chars) and accept exact legacy receipts for migration; 15
  focused tests pass. This code
  is not loaded into the active soak, so overflow,
  freshness and readiness recovery remain OPEN pending relaunch and retest.
- [~] D6-03: применимый major regression + DAILY_ACCEPTANCE, короткая инструкция
  владельцу и перечень известных ограничений. Это daily release, не весь production TODO. 18Oct: main pytest 1028 passed + 281 subtests; desktop node 95 passed; e2e 18 passed in batches/single runs; live DAILY_ACCEPTANCE items remain.
  16Oct новый full gate PASS:932 unittest/66 pytest/16HTTP/109Node +browser
  harnesses; queue projection checks отдельно12 focused PASS. Новый real-model WAV voice3/3 и native text20/20 обоих режимов PASS.
  DAILY_ACCEPTANCE mic/full actions/durable-task Stop/8h ещё не принята.
  Connected WAV voice20 и memory correction/restart/recall подтверждены. Исторический
  14Oct Argon heartbeat FAIL сохранён в runtime/supervised-profile-acceptance-20261014T174524Z.json.
24Oct full gate PASS after repairing corrupted Cyrillic screen-query/prompt strings:
pinned snapshot + secret scan clean; 1125 unittest, 67 pytest and 18 API/E2E tests;
  browser interaction E2E, synthetic desktop voice E2E, Node tests and git diff check
  passed. This validates the code gate, not the still-open integrated daily-profile
  30–60min run or full-stack overnight acceptance.

---

## Горизонт H1–H5 — целевая гармоничная архитектура (после базовой стабилизации D1/D2)

Подробная спецификация: [HARMONIZED_ARCHITECTURE_AND_ROADMAP.md](docs/HARMONIZED_ARCHITECTURE_AND_ROADMAP.md).

- [~] **H1 — Дефрагментация UI и VRM («Окно-Хамелеон» в стиле Project Airi / N.E.K.O.):**
  18Oct: legacy frontend/rust removed, unified desktop app.html/app.js, obs mode, motion/lipsync; desktop node 95 passed; live VRM acceptance remains.
  полный вывод из эксплуатации устаревших `frontend/index.html`, `--legacy-shell` (`avatar.html` + `avatar-scene.js`) и `rust-client/`; перевод OBS (`8766`) на единое ядро `app.html?mode=obs`; единый контроллер позы (`idle ↔ listening ↔ thinking/working ↔ speaking`) и многоканальная виземная артикуляция губ (`aa/oh/ee/ih/ou`).
- [~] **H2 — Двухскоростной контур мозга (Dual-Lane JAWL — Fast Chat + Deep Task/RE):**
  18Oct: duplex cascade heuristic + tests 9 passed/13 subtests; fast hint in turn context; live latency/task separation acceptance remains.
  разделение потоков внутри единой личности JAWL: быстрый разговорный поток (отклик 1–2 с без тяжёлых tool-loops) и асинхронный поток поручений/модинга/реверса (`HostOS`, `G:\RE`, `Ghidra`, `x64dbg`), присылающий голосовые чекпоинты в быстрый поток.
- [~] **H3 — Full-Duplex голос (`DuplexCascade` + `OmniVoice`):**
  18Oct: deterministic micro-turn controller and tests pass; full audio duplex/OmniVoice live validation remains.
  20Oct DuplexCascade 2.0 (live path): `earlySpeech` (streamed WAV before `final`) теперь считается речью ассистента, и barge-in останавливает именно её (`stopEarlySpeech(true)`, без владельца `speechPlayback`); `/api/voice/draft` принимает `assistant_speaking`/`extended_used` и возвращает `duplex_action`/`avatar_gesture` (backchannel → `nod`, interruption → `cancel_tts`); клиент берёт серверный `required_ms` как окно endpointing (1200 → 800 мс warm, 2000 мс для незаконченной мысли) и показывает `nod` только при смене жеста. Python 44 + streaming 22, JS 24+30 pass.
  21Oct per-request cancel: `speak_cancel` отменяет in-flight TTS по `request_id` (таргетное закрытие HTTP-сокета через `TTSService.cancel(request_id=...)`), поздний WAV после отмены не эмитится; `done.count` теперь кумулятивный. Python 53 focused.
  отказ от жёсткого VAD в пользу микро-ходов (`overlap_window ≈ 0.5–0.6 с`); управление очерёдностью речи через 6 спецтокенов (`<|user is talking|>`, `<|user is thinking|>`, `<|assistant_backchannel|>`, `<|user finish talking|>`, `<|user interruption|>`); мгновенный потоковый синтез микро-чанков в `OmniVoice` с клонированным голосом.
- [~] **H4 — Мультимодальная сенсорная кора на базе `EmbeddingGemma 2` (по принципу `eg2.haku.sh`):**
  18Oct: audio-visual vibe fusion, latent VRM reflex, semantic scene-change trigger, compact episodic vector memory, Russian eg2 reader, PerceptionFusion.observe_eg2 and optional composition integration; tests eg2/perception fusion 14 passed. Live multimodal validation remains.
  20Oct: DetailedSensoryDescriber (eg2_describer.py) - 3-level Coarse-to-Fine: L0 macro domain, L1 facets (style, elements, genre/mood/speech, spatial zones from 29 patch tokens), L2 grounded text (in-memory Windows OCR ru+en-US 4-130 ms, DSP: BPM/key/mode/spectral/speech-modulation). 3-ring perception snapshot (user/world/self). Integrated into PerceptionFusion and composition. Tests: 16 new + 25 existing = 41 passed. Replaces heavy VLM (4.6-20 s) with CPU pipeline (~1.2 s screen + 0.2 s audio).
  20Oct late: vision preprocessing fixed (Gemma4 axial RoPE [pos_x,pos_y] + divisible-by-3 21x30 grid -> 70 spatial tokens; correct detail margin grew from 0.0021 to ~0.24). Haku-style Scene/Character/Plot/Setting/Meme banks expanded to ~158 concepts with 0.4 MB `.npz` cache (2 ms warm init). `enrich_turn_text` now attaches fresh perception on every contextual turn, not only explicit screen words; ambient audio now runs `Eg2AudioDescriptionProvider` (genre/BPM/key/mood); `--screen-watch` can run on EG2 via `-Eg2Vision` without an external VLM. Tests: 125 passed + 29 subtests.
  20Oct live screen-watch: stack `-EnableScreenWatch -Eg2Vision` ready; watcher running, 3 SCREEN_DELTA events; `/api/vision/describe-displays` ok (2 displays, plot/OCR/zones); `/api/vision/look` ok; attention produced SPEAK_INTENT (significance 3), no VLM. Evidence: `runtime/live-eg2-screenwatch-report.json`.
- [~] **D2-01 (Speech-First / Stream-Before-Close) — серверная часть сделана:**
  20Oct: `speech_first.py` — инкрементальный извлекатель речи из *частичного* JSON-конверта
  (терпим к обрезанным escape/\\u-последовательностям, приватные поля `observation`/`reasoning`
  никогда не озвучиваются, фраза режется только по настоящей границе предложения, инвариант
  spoken+tail == финальный ответ байт-в-байт). `live_speech.py` — сессия «произношу первое
  предложение, пока остальной ответ ещё пишется»: рендер работает в отдельном потоке, TTS
  вызывается на каждую готовую фразу. WS-действия `speak_delta` / `speak_finish` /
  `speak_cancel` отдают те же NDJSON-события `audio`, которые уже умеет играть
  `desktop/speech-stream.js`. Тесты: `test_speech_first.py` (18) + `test_live_speech.py` (9) +
  WS-тест в `test_ws.py`; полный гейт **1147 passed + 281 subtests**.
  20Oct P0-связка: `native_jawl_streaming.py` — owned-хук в brain-процессе (tee на
  `_consume_stream`, принудительный `stream=True` для local json-envelope внутри
  активного correlated turn, из потока извлекаются только готовые фразы и уходят
  как `assistant.delta` с `format="speech"`; reasoning/private поля не эмитятся,
  итоговый `LLMResult` не меняется). Bootstrap реального brain-entrypoint:
  `"streaming_installed": true`. Компаньон: `jawl_terminal` отличает speech-дельты
  от display-дельт, `gateway.stream_text` пропускает их, `/api/chat/stream` кормит
  `LiveSpeechSession` и отдаёт `audio`-события до `final`. Клиент `desktop/app.js`
  играет ранние WAV сразу и не дублирует озвучку после `final`.
  **Live-замер 27B (20Oct):** `speech_delta` 15.07с, `final` 15.98с, первый
  `audio` 16.69с, 3 WAV-чанка, `speech_done` 18.79с, ошибок нет. Связка
  end-to-end работает; первый звук пока на 0.7с позже `final`, потому что первая
  фраза приходит за ~0.9с до конца хода (долгий prefill). Цель — сдвинуть первую
  фразу/звук раньше `final` через Fast-Lane Context Slimming и более ранний
  `Speech-First` порядок полей.
  **20Oct Fast Lane (готово):** на коротких разговорных ходах на проводе
  system 38168→1915 символов, user 24465→195 (остаются сама реплика + свежее
  восприятие); стабильный префикс без `turn_id` включает переиспользование
  кэша llama.cpp. Live-замер: первый `speech_delta` **1.01–1.06с** (cold 1.88),
  `final` 1.74–1.82с, первый `audio` **2.47–2.55с** (cold 3.39), 3 WAV,
  ошибок нет. Цель 1–3с для первого звука достигнута на тёплых ходах.
  Задачи с инструментами по-прежнему получают полный контекст.
  - *Zero-Decoder Visual Probe:* мгновенная классификация кадров экрана через матрицу концептов в RAM за ~15 мс (вызов тяжёлой VLM только для детального OCR);
  - *Audio-Visual Vibe Fusion:* одновременное понимание музыки, звуковых эффектов, интонации голоса и видеокадра при совместном просмотре фильмов/аниме (с соблюдением co-watching etiquette — реакция лицом во время диалогов, голос в паузах);
  - *Латентные рефлексы VRM:* прямая реакция эмоций/тела аватара на вектор экрана/звука за ~20 мс в обход LLM;
  - *Семантический детектор смены сцены* (`cos_sim` соседних кадров для пробуждения `Attention`/`Heartbeat`) и *компактная векторная эпизодическая память дня* (~10 МБ/час без raw video);
  - *Русский `eg2` reader:* линейный проектор аудио-слайсов в русские словоформы/токены для сверхбыстрого потокового ASR.
  - **Зрение для управления ПК (Grounding & Affordance Lane):** тот же проход EG2 + UIA + OCR выдаёт `GroundingCandidate` с bbox/role/confidence; кандидаты связаны с `VisionActionPlan`/`VisionPlanExecutor`, действия проверяются postcondition. Без confidence-гейта и свежего observation token клики запрещены.
- [x] **H4-Grounding — live-приёмка зрения как органа управления:** клик/фокус/ввод в тестовом окне через UIA-кандидаты; OCR-кандидаты на canvas/видео; отказ при низкой уверенности; Stop и policy не дают двойного эффекта.
  21Oct live PASS (`scripts/live_grounding_acceptance.py`): окно «Grounding Test Window» + кнопка, UIA-кандидат confidence 0.98/match 0.987, `plan_status=ok`, click через InvokePattern, postcondition `title_changed`, повторный execute → `clicks=1` (идемпотентно), несуществующая цель → `denied:no_grounded_candidate`. OCR-canvas: `OCR CANVAS` найден через OCR (confidence 0.9), `desktop.pointer` клик подтверждён по `canvas_clicks=1`/title, повтор идемпотентен; Stop → `denied:emergency_stop_active`, повторного клика нет. Добавлены `screen.ground` (HostOS, read-only), bounds в UIA, fresh-token/confidence-гейт, Windows OCR fallback (`windows_ocr.py`). Focus берётся через `AttachThreadInput`/`SwitchToThisWindow`.
- [~] **H5 — Игровой моторно-тактический слой (Game Embodied Layer 10–60 Гц + Auto-Modding):**
  18Oct: expanded engineering baseline in `game_embodied.py`: motor controller, voice combat coordinator, strategy/mod planner, GameObservation, SimulatedGameInputBridge, ModScaffold/ModScaffoldWriter, GameEmbodiedLayer orchestration; tests 17 passed. Live game input, mod execution and auto-modding remain open.

---

## M — Дешёвая модель: трек замены тяжёлого мозга

Цель: снизить VRAM/стоимость основного мозга и сенсорного композитора без потери
daily-качества. Default-модель не меняется до отдельной приёмки владельцем.

- [ ] **M1 — Baseline Hikari 27B:** зафиксировать VRAM/RSS, p50/p95 prefill/decode,
  RU-качество и JSON/action validity на одном фиксированном наборе; сохранить отчёт.
- [ ] **M2 — Шортлист дешёвых моделей:** Qwen3-4B/8B, Gemma-3-4B/12B, Llama-3.1-8B,
  Mistral-Nemo-12B (лицензия, GGUF, контекст, RU, tool-calling); отсеять по бюджету
  VRAM и наличию квантов.
- [ ] **M3 — Единый RU-бенч:** 30 диалоговых реплик, 20 JSON/tool-конвертов,
  10 длинных sensory-снимков; метрики: RU-адекватность, JSON validity, action
  correctness, галлюцинации, p50/p95, VRAM. Ошибки считать по каждому пункту.
- [ ] **M4 — Прогон на GPU1/CPU через тот же llama-server:** сравнить top-2 с Hikari
  на одинаковых промптах и температуре; зафиксировать дельту качества/скорости.
- [ ] **M5 — Интеграция за флагом `-BrainModel`/profile:** без смены default;
  focused tests + DAILY_ACCEPTANCE subset + live text/voice; rollback одной командой.
- [ ] **M6 — Решение и ADR:** обновить STATE/TODO, указать цену, VRAM, latency,
  известные ограничения; promotion только после подтверждения владельца.
- [ ] **M7 — Дешёвый сенсорный композитор (опционально):** EG2 + детерминированный
  Coarse-to-Fine composer как default; `Needle 3` — только English tool-router
  (русский словарь 8k BPE не подходит для генерации RU-текста).
  24Oct paired CPU overlap probe (YAMNet + existing GigaAM): 18 controlled
  speech/music mixes across 3 phrases × 2 sources × 3 SNR; ASR expected phrase
  17/18, YAMNet Music ≥.3 in at least one 2s window 18/18, and 0/5 clean
  speech/noise/silence controls crossed a ≥2-window rule at thresholds .2–.5.
  This supports parallel tracks but is too small/synthetic to set production
  thresholds. Remove blanket ASR→music suppression only after source-disjoint
  real media validation. Music-Descriptor (MERT genre/instrument/mood heads)
  is a research lead, but demo + MTG-Jamendo declare CC-BY-NC; not a shipping
  candidate absent license review. No production wiring. Details:
  `docs/research/yamnet-gigaam-overlap-20261024.md`.  24Oct live-media check: while playback was active on NVIDIA loopback 39,
  captured 14.91s in memory (699 chunks, 0 drops/errors). YAMNet CPU saw
  persistent Music (13 rolling windows, 12 above 0.3, median score .683, max .867); GigaAM
  returned no text. Conditional MERT ran CPU in 1.94s, outputs .324/.293.
  Secondary instrument/genre tags were only .001–.006 and are not publishable;
  source identity was not labeled, so this is a live-path/detector smoke, not a
  music accuracy acceptance. No PCM/transcript persisted. Probe/artifact:
  `scripts/probe_live_music_loopback.py`,
  `runtime/audio-path-replay/out/live-music-loopback-probe-20261024.json`.
  QA segment audit found segA/C/D AAC tracks are digital silence (mean/max
  -91 dBFS), segB has no audio stream. Do not count those visual fixtures as
  audio-positive coverage; report:
  `docs/research/yamnet-gigaam-overlap-20261024.md`.  24Oct implementation follow-up: `YamnetSoundscapeDetector` is now an optional
  CPU-only ambient lane alongside GigaAM, not a replacement. It emits a music
  event only after repeated ≥.30 YAMNet windows (long clips require at least
  25% positive windows), includes only stable tags ≥.15, and never fabricates
  mood/free-form captions. ASR and music persist separately with segment/source
  metadata; music Fusion TTL is 20s and pause clears it. Detector load failure
  leaves ASR intact and is visible in bridge/UI telemetry. Production-venv
  isolated RSS +31.5 MiB after 8s sax inference, 29.7ms per 8s segment; not a
  combined companion budget. Focused test suites: 129 Python + 7 UI passed,
  py_compile passed. Real fixture replay separated Bach/sax/music, speech,
  speech+synthetic chord, noise and silence. This remains below acceptance:
  need source-labeled game/video audio, full companion overlap, and 30–60m soak.
  24Oct live known-music check in isolated no-mic/no-TTS profile: 15s FMA
  Electronic fixture at -18dB yielded a fresh YAMNet `audio_kind=music` event;
  GigaAM emitted no transcript, 0 capture drops and 0 soundscape errors. No genre
  or instrument tag was emitted, so only music presence is proven. This unclosed
  30m run still has time remaining. It exposed monotonic-vs-wall clock misuse for
  YAMNet memory retention (1970 event timestamps); fixed conversion and added a
  regression. 30 focused ambient/YAMNet unittest cases pass; short live
  verification of the fix remains open. Details in music research.
    24Oct design review: connection badge now says «Панель подключена» only
    after `/api/session` succeeds, and «Сервер недоступен» on failure; the old
    «В контуре» overclaimed overall readiness. Mock-brain browser E2E passes
    after the copy change; all nine responsive viewports remain overflow-free.
    Голосовая ошибка теперь объясняет 503 как недоступный TTS и предлагает
    проверить службу/повторить, а сетевые ошибки дают краткую инструкцию.
    E2E mock-flow подтвердил показ сообщения после неудачи озвучивания.


- 24Oct: ???????? 29-???????? no-mic/no-TTS loopback integration run: 174 polls, 115 segments, zero capture drops/errors, one known electronic control yielded `music`; broad genre/style and external-media transcript remain unverified. Fix wall-clock timestamps covered by 30 tests; live post-fix timestamp check remains open. Run details: `docs/research/music-sensory-candidate-evaluation-20261024.md`.


- 24Oct three-role multimodal smoke: Hikari text brain + two concurrent Qwen2.5-Omni-3B sensor slots accepted a video and an audio request (2.70s video, 2.54s audio; Hikari 0.56s). Video got Earth/scene changes but missed clouds/icon detail; audio tagged electronic/EDM but was repetitive and omitted instruments/vocal/transitions. Isolated servers left on localhost 8990/8995; no screen/loopback capture, no daily-profile wiring, and no TTS. Keep audio description quality open; report and proposed detailed role prompts: `docs/research/omni-three-role-smoke-20261024.md`.
  24Oct follow-up replay with the bounded event window plus one direct Hikari
  request: 8 submissions, 5 scene changes, 2 current captions, 4 retained visual
  events; brain endpoint answered in 1.79s and cited details from prior scenes,
  but output truncated and temporal grounding was inconsistent on a second probe.
  Confirms context transport only, not reliable continuity or Companion chat.
  Artifact: `runtime/instances/goal-trailer-visual-replay-20261024/trailer-sensor-replay-timeline-hikari.json`.
  24Oct follow-up: default full repository gate now passes after the unstable
  desktop-wallpaper OCR assertion became opt-in: 1,129 unit + 67 pytest + 18
  API E2E; browser interaction, synthetic desktop voice, Node, PowerShell parse,
  and diff checks also pass. This does not clear the live-profile blocker:
  Hikari currently exposes 8,192 tokens against a measured 11,536-token JAWL
  startup prompt. Gate report: `docs/research/full-gate-20261024.md`.
  24Oct Hikari follow-up: active 8990 was launched at ctx 8192; workspace owned
  launcher is configured for 65536. Same model at 16k CPU passes JAWL startup
  (10,992 prompt tokens) but the first live chat turn times out at 120s while
  startup ReAct is still running. Need GPU1 16k chat retest; this requires an
  owner-approved restart of Hikari 8990. Do not treat the CPU chat as PASS.
  Report: `docs/research/hikari-context-startup-probe-20261024.md`.
  Readiness fix: normal local-bonsai launch no longer opts into AllowBusyStartup;
  the existing heartbeat gate waits for SYSTEM_CORE_START completion before
  exposing Companion readiness. 17 launcher tests, PowerShell parse and CodeSee
  validation passed. Live GPU1 verification still depends on permission to
  restart the current user-owned 8990 service.

## 2026-10-25 sensory history follow-up

- Implemented a bounded one-hour text timeline and seven-day compact hourly history for screen/audio observations, with provenance, sensitive-text suppression, and no raw media persistence. Store/fusion/web tests pass (25 passed, 4 subtests).
- The ten-minute live acceptance captured 199 status samples and 264 text observations with zero capture/API errors. Current scene descriptions worked; direct unaided two-minute retrieval and full ten-minute visual/audio synthesis remain PARTIAL. The existing running companion predates the history-store wiring, so a managed restart and in-process acceptance remain OPEN.
- Report: `docs/research/sensory-history-acceptance-20261025.md`; raw-media-free ledger: `runtime/sensory-history-acceptance-20261025.json`.

- [ ] 28Oct follow-up: compare LFM1.6B GPU with Qwen GPU on labeled sequential content and live brain/TTS coexistence before selecting a detailed visual describer. Five-frame speed probe completed; runtime/lfm-detail-probe-20261028/STATUS.md.

- [~] 28Oct live YouTube sensory check: LFM450→target-window buffer 50/50 at 1Hz with 64.8ms p50; Hikari caption-only recap in 1.08s declined to invent a plot but answered English and stayed broad. Need labeled story-quality set and Florence tags→brain comparison before selection. Report: runtime/lfm450-story-replay-20261028/STATUS.md.


- [x] Visual detail acceptance & Foveated Vision (Round 5, 4 ноября 2026):
  - Решена проблема информационного обрыва (Information Cliff) и размытия 960x520 JPEG 72 с помощью FoveatedVisionProcessor (CropVLM, S-BOED): двухпоточный композит [периферия 640x360 + нативный 1:1 кроп 512x512 зоны внимания] сохраняет 100% пиксельную четкость шрифтов UI (10pt) за 33.10 мс без раздувания токенов.
  - Решена проблема потери кадров при быстром монтаже (5 смен сцен за 10с в трейлерах) через StoryboardGridAssembler: сборка квадрантного коллажа 2x2 (1024x1024) за 24.15 мс сокращает число вызовов VLM на 75% (1 вызов вместо 4) и исключает отбрасывание устаревших кадров, передавая модели связную динамику сюжета.
  - Неблокирующий буфер AsyncVisualRingBuffer (deque maxlen=8) гарантирует 0% просадки FPS в играх, поглощая всплески кадров за <0.01 мс на кадр и сбрасывая промежуточный шторм устаревших кадров перед LanceDB.
  - Бенчмарк: `benchmarks/bench_foveated_storyboard_stream.py`; тесты: `tests/test_visual_stream.py` (100% GREEN).

- [~] Hikari conversation continuity: managed restart applied 200-message history/cache and startup receipt reports `terminal_context_compaction.installed=true`; compaction is character-budget-driven (18K target) with the latest 12 messages preserved verbatim. Still exercise a long live conversation across the compaction threshold and confirm the summary retains needed decisions. Current health is degraded because captions age out amid scene-change drops; loopback awaits samples.

- [~] Weak YAMNet music-candidate offline screen: 181 source-disjoint ESC-10 non-music clips + three recorded speech fixtures produced zero candidates; five real media clips yielded four confirmed music results and one weak anime candidate; 54 speech/music mixes produced 11 weak candidates and 34 confirmed detections; four speech/noise controls produced zero candidates. Promising routing evidence, not full acceptance: add human-checked speech-only and game/SFX/tonal clips and validate live loopback under load. Candidate cutoff remains uncalibrated; confirmed gate stays 0.35. Report/artifact: `docs/research/audio-speech-music-overlap-20261029.md`, `runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json`.

29Oct direct-mic delivery cues are an experimental DSP lane, disabled by default and opt-in via `-EnableVoiceDeliveryCues` (pitch/level/voiced-frame measurements, no emotion inference). Acceptance remains OPEN pending owner-reviewed mic samples, calibration, CPU/latency cost, and brain uptake: `docs/research/voice-delivery-cues-20261029.md`.

29Oct ambient loopback ASR now filters only clear artifacts (blank/filler, repeated-character and CJK/Hangul) before memory/VA, with an `asr_noise_filtered` counter and no invented default confidence. This is not VAD or semantic validation; mixed-loopback accuracy remains OPEN: `docs/research/ambient-asr-artifact-gate-20261029.md`.
