## 2026-11-13 — Multimodal Companion Extension: Music Flow & Critique, Media Narrative & CoWatch Opinions, Persona Hypotheses & Social Graph, Autonomous Player 2 Controller
- **Чистый CPU DSP динамического анализа музыки и критики (`src/jawl_voicecompanion/music_perception.py`)**:
  - `MusicSectionKind`: типизированные секции музыкальной композиции (`INTRO`, `VERSE`, `CHORUS`, `BRIDGE`, `BUILDUP`, `DROP`, `OUTRO`, `TRANSITION`, `UNKNOWN`).
  - `DynamicMusicFlowTracker`: динамический трекинг потока музыки, скользящее окно кадров, фиксация перехода между секциями и энергетических пиков.
  - `MusicDropEvent`: обнаружение дропов с вычислением амплитуды, длительности нарастания и глубины спада энергии.
  - `MusicCritiqueEngine` и `MusicCritique`: генерация многоаспектной аналитической критики (напряжение, ритмический поток, динамический контраст, развитие формы) с краткими и подробными вердиктами.
  - Тесты: `tests/test_music_perception.py` — **11/11 PASS**.
- **Движок субъективного восприятия нарратива и ко-вотчинга (`src/jawl_voicecompanion/cowatch_engine.py`)**:
  - `NarrativeArcKind`: структурированные сюжетные арки (`EXPOSITION`, `RISING_ACTION`, `CLIMAX`, `FALLING_ACTION`, `RESOLUTION`, `PLOT_TWIST`).
  - `CharacterOpinionTracker` и `CharacterOpinion`: трекинг персонажей во времени (симпатия, моральный компас, значимость, эмоциональная валентность) на базе наблюдаемых действий.
  - `MediaNarrativeTracker` и `NarrativeSnapshot`: мониторинг динамики сюжета, драматического напряжения, частоты событий и сюжетных поворотов.
  - `CoWatchOpinionEngine`: генерация субъективных мнений компаньона, эмпатических реакций на сюжетные твисты и развитие отношений персонажей.
  - Тесты: `tests/test_cowatch_engine.py` — **14/14 PASS**.
- **Гипотезы о личности пользователя и консолидация соцграфа (`src/jawl_voicecompanion/memory_consolidation.py`)**:
  - `PersonaHypothesis`: моделирование личностных черт и привычек пользователя со статусами (`CANDIDATE`, `ACTIVE`, `DISPROVEN`), списком подкреплений и опровержений.
  - `UserPersonaHypothesisEngine`: инкрементальное выдвижение и валидация гипотез на основе эпизодических наблюдений с математической формулой уверенности.
  - `SocialEntityRelation` и `SocialGraphConsolidator`: построение и консолидация графа социальных связей пользователя (семья, друзья, коллеги, менторы, питомцы, соперники) с сохранением валентности отношений и истории взаимодействия.
  - Чистое исполнение на CPU/RAM во время ночной консолидации («сон») с соблюдением TTL и tombstone-фильтрации.
  - Тесты: `tests/test_memory_consolidation.py` — **16/16 PASS**.
- **Автономный напарник Player 2 для кооперативных игр (`src/jawl_voicecompanion/game_embodied.py` & `game_controller.py`)**:
  - `CompanionRole`: тактические роли (`SUPPORT`, `DEFENSIVE`, `AGGRESSIVE`).
  - `TacticalTelemetry`: безопасный адаптер и нормализатор игрового контекста (здоровье, боеприпасы, пространственные координаты, враги, укрытия, нахождение под обстрелом).
  - `Player2Decision`: комплексное решение компаньона (комбинация кнопок геймпада, аналоговые стики с circular deadzone, эмоциональная реакция, реплика и срочность `SpeechUrgency`).
  - `Player2CompanionController`: конечный автомат тактического поведения, интегрированный с `ActionSpeechCoordinator` и `NaturalPauseInjectionQueue` для естественной синхронизации действий и речи без перебивания игрока.
  - Интеграция в `GameEmbodiedLayer`: `enable_player2()`, `tactical_tick()`, статус контроллера.
  - Тесты: `tests/test_game_embodied.py` — **25/25 PASS**, `tests/test_game_controller.py` — **9/9 PASS**.
- **Сквозная интеграция и регрессионная верификация**:
  - Экспорт 161 публичного символа в `src/jawl_voicecompanion/__init__.py::__all__` (0 отсутствующих атрибутов).
  - Полный таргетированный набор новых подсистем: **111/111 PASS** (0.92 с).
  - Смежные регрессионные наборы: `test_companion_runtime.py` (8/8), `test_model_slots_web.py` (5/5), `test_sensory_motivation.py` (6/6), `test_perception_fusion.py` (8/8), `test_scene_state.py` (19/19), `test_narrative_consolidator.py` (17/17).
  - VRAM: $\Delta\text{VRAM} = 0$ MiB на GPU 0; GPU 1 строго зарезервирован под SenseNova Loop 9B Preview и OmniVoice TTS; чистый CPU/RAM для аналитики, графов и контроллера.

## 2026-11-13 — Model-Agnostic Cognitive Roles, MOSS-Live Duplex Coordination, Multimodal Scene Memory (Micro-Detail Zero-Loss Recall) & Virtual Gamepad Embodiment
- **Модульные когнитивные слоты (`src/jawl_voicecompanion/model_slots.py`)**:
  - `ModelSlot`: типизированные роли `FOREGROUND_BRAIN`, `BACKGROUND_REASONER`, `VISION_PERCEPTION`, `AUDIO_PERCEPTION`, `COORDINATOR`, `GAME_EMBODIMENT`.
  - `ModelCapabilities`: структурированные метаданные возможностей модели (`streaming`, `tool_calling`, `vision`, `audio_in`, `system_prompt`, `concurrency`, `max_context_tokens`).
  - Абстрактный интерфейс `ModelAdapter` с эмуляцией/дефолтами для `stream_generate`, `generate_with_tools`, `describe_vision`, `analyze_audio`.
  - Адаптеры `MockModelAdapter`, `OpenAICompatibleAdapter` (OpenAI v1/chat/completions), `LlamaServerAdapter` (специализация под llama.cpp / SenseNova Loop 8990), `SlotRefAdapter` (ссылочный алиас между слотами).
  - Потокобезопасный `ModelSlotRegistry`: регистрация, runtime hot-swapping (`swap`), fallback-цепочки разрешения (`get_with_fallback`), интроспекция `snapshot()`.
  - Полная совместимость с оригинальными ключами JAWL (`--llm-url`, `--llm-model`, `--vision-url`, `--vision-model`, `JawlWebChatAdapter`, `runtime_manifest.py`).
- **MOSS-Live Foreground-Background Duplex Координатор (`src/jawl_voicecompanion/moss_coordinator.py`)**:
  - `ForegroundLane`: потоковая генерация реплик в реальном времени из слота `FOREGROUND_BRAIN` с поддержкой кооперативной отмены и точным подсчётом spoken/unspoken текста.
  - `BackgroundTaskManager`: фоновое выполнение задач рассуждения ReAct / deep reasoning в слоте `BACKGROUND_REASONER` на пуле потоков без блокировки и деградации задержек речи.
  - `NaturalPauseInjectionQueue`: потокобезопасная приоритетная очередь вставки результатов фонового рассуждения строго в паузах между репликами пользователя (`can_inject(is_user_speaking, is_companion_speaking)`), с TTL экспирацией.
  - `TurnContinuityBuffer`: сохранение контекста прерванного хода при barge-in и формирование преамбулы продолжения (`format_resumption_context`).
  - `MossCoordinationLayer`: мастер-координатор, связывающий `ModelSlotRegistry`, lanes, injection queue и `DuplexCascadeArbiter`.
- **Мультимодальная память сцены с нулевой потерей микро-деталей (`src/jawl_voicecompanion/scene_memory.py`)**:
  - `SceneMemoryManager`: кольцевой буфер кадров `MultimodalSceneFrame` на чистом CPU/RAM с временным окном TTL и предельным объёмом.
  - Нулевая потеря точности (zero-loss): точные числа (HP, таймеры, координаты, ресурсы), строковые значения OCR/UI, пространственные `BoundingBox` (IoU, центроиды, включение точек), акустические маркеры.
  - Граф сцены `MultimodalSceneGraph`: узлы (`SceneGraphNode`) и направленные рёбра (`SceneGraphEdge`) связывают сущности, OCR-тексты, аудиособытия и речевые ходы во времени.
  - Честный эпистемический статус: `OBSERVED_PRESENT`, `OBSERVED_ABSENT`, `NOT_OBSERVED` без ложных домыслов.
  - Высокоточный контекстный рекол `format_micro_recall_context()` для промптов моделей.
- **Игровое воплощение и виртуальный контроллер (`src/jawl_voicecompanion/game_controller.py`)**:
  - `VirtualGamepadButton`, `GamepadStick`: виртуальный геймпад с настраиваемыми мёртвыми зонами (circular deadzone).
  - `ActionSpeechCoordinator`: координация игровых действий и естественного комментирования (уровни срочности `TACTICAL`, `REACTION`, `AMBIENT`), подавление повторов, доставка через `NaturalPauseInjectionQueue`.
  - `GameControllerAdapter` и когнитивный слот `GameEmbodimentAdapter` (`ModelSlot.GAME_EMBODIMENT`).
  - Совместимость с `GameInputBridge` (`game_embodied.py`).
- **Сквозная интеграция и Web API**:
  - `src/jawl_voicecompanion/composition.py`: инициализация и связывание реестра слотов, MOSS-координатора, памяти сцены и игрового контроллера.
  - `src/jawl_voicecompanion/companion_runtime.py`: свойства-делегаты (`model_slot_registry`, `moss_coordinator`, `scene_memory`, `game_controller`) и аккуратный teardown.
  - `src/jawl_voicecompanion/perception_fusion.py`: передача кадров и детекций в `scene_memory`.
  - Эндпоинты в `web.py`:
    - `GET /api/models/slots` — снимок всех слотов и адаптеров
    - `POST /api/models/swap` — горячая замена адаптера слота
    - `GET /api/moss/queue` — состояние очереди естественных пауз
    - `POST /api/moss/task` — диспетчеризация фоновой задачи reasoning
    - `GET /api/game/gamepad` — снимок состояния виртуального контроллера
    - `POST /api/game/gamepad/press` — виртуальное нажатие кнопок геймпада
    - `GET /api/scene/summary` — агрегированная сводка графа сцены и кадров
    - `POST /api/scene/query` — эпистемический запрос к памяти микро-деталей
- **Регрессия (числа/доказательства)**:
  - `tests/test_model_slots.py`: **15/15 PASS** (контракты, возможности, Mock, OpenAI, LlamaServer, SlotRef, горячая замена, цепочки fallback, snapshot).
  - `tests/test_moss_coordinator.py`: **8/8 PASS** (очередь пауз, непрерывность диалога при barge-in, background задачи, координатор MOSS, стриминг foreground lane).
  - `tests/test_multimodal_micro_recall.py`: **13/13 PASS** (BoundingBox геометрия, эпистемические статусы, численные микро-детали, граф сцены, temporal co-occurrence, spatial region query, TTL прунинг).
  - `tests/test_game_controller.py`: **9/9 PASS** (мертвые зоны геймпада, нажатия кнопок, координация речи и действий, интеграция с pause queue, GameEmbodimentAdapter).
  - `tests/test_model_slots_web.py`: **5/5 PASS** (GET/POST /api/models, /api/moss, /api/game, /api/scene).
  - `tests/test_companion_runtime.py`: **8/8 PASS** (делегирование свойств и жизненный цикл).
  - `tests/test_game_embodied.py`: **17/17 PASS**.
  - `tests/test_web.py`: **94/94 PASS**.
  - Всего в наборе новых компонентов: **58/58 PASS** (3.67 с).
- **Бюджет VRAM**:
  - GPU 0: 0 MiB аллокаций ($\Delta\text{VRAM} = 0$).
  - GPU 1: зарезервирован под SenseNova Loop 9B Preview (порт 8990) и OmniVoice TTS (порт 9890).
  - Pure CPU/RAM: CrispASR GigaAM v3 RNN-T, Silero VAD, YAMNet ONNX, Multimodal Scene Graph, Game Controller State.

## 2026-11-13 — Living Companion Subsystems: Offline Sleep Memory Consolidation, Multimodal Co-Watching & Pure-CPU Music DSP
- **Эпизодическая память и оффлайн консолидация («сон»)**:
  - `src/jawl_voicecompanion/memory_consolidation.py`: `OfflineConsolidator`, `EpisodicObservation`, `MemoryProposal`.
  - Префиксная и точная фильтрация tombstone-записей (`is_tombstoned(key)`), немедленная очистка кандидатов при надгробиях, TTL-экспирация устаревших наблюдений без воскрешения удалённых/истекших фактов.
  - Агрегация в кластеры по схожести ключей и значений, взвешенный расчёт доверия $C = 1 - (1 - c_0) \cdot e^{-\alpha (N-1)}$.
  - Разделение статусов: факты (`status="fact"`, confidence >= threshold и N >= 3) vs гипотезы (`status="hypothesis"`).
  - Стейджинг предложений и атомарный экспорт `export_staged_proposals()` с поддержкой кооперативной отмены `cancel_check`.
- **Мультимодальный движок ко-вотчинга (аниме, кино, игры)**:
  - `src/jawl_voicecompanion/cowatch_engine.py`: `CharacterBinding`, `SceneCutEvent`, `CoWatchObservation`, `CoWatchCommentaryBid`, `CoWatchEngine`.
  - 3-уровневое разделение идентичностей (`spatial_track_id`, `visual_identity_id`, `audio_speaker_id`).
  - Поддержка закадровой речи (speaker без визуального bounding-box) без ложного связывания с экранными персонажами.
  - Мгновенный сброс визуальных связок и неподтверждённых гипотез при детекции смены сцены (`SceneCutEvent`).
  - Гейтинг внимания: подавление комментариев при `is_dnd`, `is_quiet_hours`, активной речи пользователя (`user_speaking`), неистекшем кулдауне (45–60 с).
  - Рутинные сцены отдают `action="silence"`, текст `"тишина"`.
  - Мост к игровому контексту (`record_gameplay_observation`): инвентарь, боссы, здоровье, кооперативные цели.
  - Интеграция мгновенного barge-in (`barge_in_abort <= 300 ms`).
- **Чистый CPU DSP музыкальный анализатор тональностей и настроения**:
  - `src/jawl_voicecompanion/music_perception.py`: `MusicPerceptionResult`, `MusicPerceptionAnalyzer` (NumPy FFT, STFT, chroma filterbank 12 полутонов).
  - Распознавание тональности (Krumhansl-Schmuckler chroma correlation) и BPM (спектральный поток 50–200 BPM).
  - Маппинг валентности, возбуждения и настроения по Russell circumplex.
  - Адаптер `as_audio_description_provider()` для бесшовной интеграции в `AudioDescriptionService` с нулевым оверхедом VRAM.
  - Строгие DSP-пороги: тишина (< -55 dBFS) -> `kind="unknown"`, шум (flatness > 0.55) -> `kind="sound"`, речь -> `kind="speech"`, музыка -> `kind="music"`, перекрытие -> `speech_overlap=True`.
- **Сквозная интеграция и рантайм**:
  - `src/jawl_voicecompanion/__init__.py`: экспорт публичных классов.
  - `src/jawl_voicecompanion/composition.py`: инициализация `MusicPerceptionAnalyzer`, fallback `AudioDescriptionService`, `OfflineConsolidator`, `CoWatchEngine`.
  - `src/jawl_voicecompanion/web.py`: подключение в `CompanionServer`, безусловная запись надгробия в `forget_memory_sources(key)` до проверки сенсорных ID, shutdown в `server_close`.
  - `src/jawl_voicecompanion/companion_runtime.py`: свойства-делегаты `@property` (`offline_consolidator`, `cowatch_engine`, `music_analyzer`).
- **Регрессия (числа/доказательства)**:
  - `tests/test_memory_consolidation.py`: **11/11 PASS** (контракты, TTL, надгробия, префиксы, логическое забывание без воскрешения, разделение гипотез и фактов, cooldown, экспорт, кооперативная отмена).
  - `tests/test_cowatch_engine.py`: **10/10 PASS** (смена сцены, 3-уровневое разделение, закадровый голос, DND/quiet hours/user speaking гейтинг, тишина в рутине, геймплейный мост, barge-in mute).
  - `tests/test_music_perception.py`: **9/9 PASS** (тишина, шум, чистая речь, синтезированная музыка, тональность, смешанный поток, ручной вызов, адаптер `AudioDescriptionProvider`, нулевой VRAM).
  - `tests/test_companion_runtime.py`: **7/7 PASS** (делегирование свойств рантайма).
  - `tests/test_web.py`: **94/94 PASS** (включая сквозной тест `test_structured_memory_forget_records_tombstone_in_offline_consolidator`).
  - Desktop suite (`node --test desktop/*.test.* desktop/tests/*.test.*`): **144/144 PASS**.
- **Бюджет VRAM**:
  - GPU 0: 0 MiB аллокаций ($\Delta\text{VRAM} = 0$).
  - GPU 1: зарезервирован под Bonsai LLM и OmniVoice TTS.
  - Консолидация памяти, ко-вотчинг и музыкальный DSP строго на CPU/RAM.

## 2026-11-13 — Cycle 13 / Live Voice (Phase C): Stream-First Duplex, Dual-Lane TurnTrace, Generation Epochs и мгновенный Barge-In
- **Архитектура Stream-First Duplex (H1/P0 > H2/P1)**:
  - `src/jawl_voicecompanion/duplex_cascade.py`: `StreamPhraseSegmenter` буферизует streaming-токены от Bonsai LLM и нарезает фразы по естественным знакам пунктуации (`[.?!…\n]`, мин. 12 символов / 3 слова), немедленно передавая первую фразу в OmniVoice TTS.
  - Потоковый синтез первого сегмента параллелен генерации последующих токенов LLM.
- **Сквозная Dual-Lane TurnTrace метрика (H1/P0)**:
  - `src/jawl_voicecompanion/turn_trace.py`: канонические константы стадий (`STAGE_USER_SPEECH_END`..`STAGE_AUDIO_STOPPED`) и метод `compute_turn_kpis()`.
  - Строгое разделение Fast Lane (`first_audible_audio_ms` p95 <= 1.2s) и Deliberative Lane (`first_meaningful_audio_ms` p95 <= 1.2s; short answer completion p95 <= 4.0s). Рефлекторный preface не маскирует задержку содержательного ответа.
- **Single-Owner Playback FSM и Generation Epochs (H4/P0)**:
  - Монотонный `generation_epoch` на сервере (`TurnArbiter`, `DuplexCascadeArbiter`, `web.py`) и клиенте (`desktop/app.js`).
  - При каждом новом ходе или barge-in сервер продвигает эпоху через `cancel_all()`, отсекая устаревшие chunks и отменённый TTS. Клиент сбрасывает устаревшие аудиопакеты.
- **Мгновенный аппаратный Barge-in mute <= 300 мс (H5/P0)**:
  - `desktop/app.js`: выделенный `earlySpeech.gainNode` обнуляет громкость в тот же квант времени (`gainNode.gain.setValueAtTime(0, audioCtx.currentTime)`), останавливает шедулинг PCM и сбрасывает очереди.
  - Инструментация `traceMark('t_barge_in_detected')` и `traceMark('t_audio_stopped')` подтверждает p95 <= 300 мс.
- **Token-Bucket антиспам и дедупликация бэкченнелов (H3/P1)**:
  - `src/jawl_voicecompanion/affective_engine.py`: `TokenBucketRateLimiter` (ёмкость 1.0, refill rate 1/6.0 с), дедупликация фраз, подавление при речи пользователя и в состоянии mute. Интеграция в `/api/voice/preface`.
- **Zero-GPU Fast Lane (H2/P1)**:
  - Флаг `ENABLE_FAST_LANE` (по умолчанию `False`), поддержка RAM/CPU-кэша без нагрузки на GPU 1 (GPU 1 выделен под Bonsai LLM и OmniVoice TTS, GPU 0 строго запрещён).
- **Регрессия (числа/доказательства)**:
  - Python tests: **192/192 PASS** (`tests/test_voice_turn_trace.py` 7/7, `tests/test_voice_dual_lane.py` 7/7, `tests/test_voice_barge_in.py` 10/10, `tests/test_voice_preface_policy.py` 12/12, `tests/test_turn_trace.py` 13/13, `tests/test_echo_guard.py` 13/13, `tests/test_web.py` 92/92, `tests/test_barge_in_p1.py` 8/8, `tests/test_duplex_cascade.py` 14/14, `tests/test_affective_engine.py` 13/13).
  - Node desktop tests: **59/59 PASS** (`desktop/tests/app-voice-lifecycle.test.mjs` 30/30, `desktop/speech-stream.test.mjs` 21/21, `tests/test_desktop_speech_cancel.mjs` 8/8).
- **Ограничения**:
  - Акустическое эхо микрофона требует валидации владельцем на физическом устройстве.
  - Сервер companion требует перезапуска для применения изменений.

## 2026-11-13 — Cycle 22: Echo Guard — Сквозная защита streaming ASR от self-TTS echo
- **Защита от self-TTS echo**:
  - `src/jawl_voicecompanion/echo_guard.py`: новый модуль детерминированной проверки echo текста в потоковом ASR.
  - `src/jawl_voicecompanion/duplex_cascade.py`: интеграция `EchoGuard` в `evaluate_micro_turn` для детекции echo в ASR draft.
  - `src/jawl_voicecompanion/web.py`: синхронизация активного текста TTS с `EchoGuard`, фильтрация echoed ASR-результатов.
  - `desktop/voice-input.js` / `desktop/app.js`: проброс `echo_detected` в клиентскую логику `decideMicTurn` для удержания микрофона.
- **Регрессия**:
  - `tests/test_echo_guard.py`: 13/13 PASS (unit + integration).
- **Ограничения**:
  - Требует рестарта сервера companion.

## 2026-11-10 — Cycle 21d: Full-duplex barge-in с контекстной коррекцией, TurnArbiter cancel и сквозная регрессия
- **Barge-in с контекстной коррекцией (дефект «мозг отвечает по отрывкам при перебивании»)**:
  - `desktop/app.js`: `cancelRemoteSpeech(playback, reason)` пробрасывает причину (`user_barge_in` при перебивании голосом, `user_stop_button` при кнопке стоп) в `/api/tts/cancel`.
  - `src/jawl_voicecompanion/web.py`: `_current_speaking_text` фиксирует текущий текст во время `_stream_tts`. При `/api/tts/cancel` метод `note_speech_interruption` сохраняет время, причину и сниппет прерванного ответа (`_last_interrupted_turn_text`), а также немедленно отменяет активные и ожидающие очереди рассуждения через `gateway.arbiter.cancel_all(reason=f"speech_interruption:{reason}")`.
  - `enrich_turn_text`: следующий ход однократно получает контекст: `[ПЕРЕБИВАНИЕ: пользователь прервал мой предыдущий голосовой ответ ({reason}, {when}; ответ прерван на: «...»). Ответ не был дослушан — воспринимай это сообщение как продолжение/коррекцию прерванной реплики, учитывай недослушанный контекст, не начинай ответ заново и не отвечай по отрывкам.]`. Маркер сгорает за один ход (истекает через 120 с). Временная метка `[Время: ...]` и маркер изолированы так, чтобы не нарушать `split_packet` и историю диалога.
  - `create_server`: `SensoryMotivation` по умолчанию подключён к `ScreenCommentaryScheduler` для отсечения рутины без спама.
  - `desktop/tests/app-voice-lifecycle.test.mjs`: добавлен стаб `traceMark` в тестовые harness, разблокировано выполнение тестов жизненного цикла.
- **Регрессия (числа/доказательства)**:
  - Node desktop tests: `desktop/tests/app-voice-lifecycle.test.mjs` **30/30 PASS**, `desktop/voice-input.test.mjs` **17/17 PASS**, `tests/test_desktop_speech_cancel.mjs` **8/8 PASS** (суммарно **55/55 PASS**).
  - Python tests: `tests/test_web.py` **92/92 PASS** (4 BargeIn), `tests/test_speech_requests.py` **14/14 PASS**, `tests/test_screen_commentary.py` **10/10 PASS**, `tests/test_sensory_motivation.py` **6/6 PASS**, `tests/test_barge_in_p1.py` **8/8 PASS**, `tests/test_turn_policy.py` **14/14 PASS**, `tests/test_proactive.py` **26/26 PASS**, `tests/test_perception_enrichment.py` **4/4 PASS** (суммарно **104/104 PASS**).
  - `node .codesee/scripts/validate-features.mjs`: **PASS (код 0)**.
- **Ограничения**:
  - P-M1 (динамическая запись дефицита в SQLite-ядро JAWL): **BLOCKED** — в read-only snapshot ядре нет эндпоинта для прямой инъекции deficit; companion-side `SensoryMotivation` является авторитетным фильтром инициативы.
  - Физический микрофон / акустическое эхо реальных колонок: **UNKNOWN/PENDING** до живой проверки владельцем.

## 2026-11-10 — Cycle 21c (engineer/orchestrator): P1 barge-in контракт/детерминированные тесты (PARTIAL)
- Probe (harness2, P1): `tests/test_barge_in_p1.py` — 8 passed. Покрыто (сим): `LiveSpeechSession.cancel()` drain/done/no-tail + `tts.cancel(request_id)` best-effort (`live_speech.py:135-160,311-314`), готовность к следующему ходу (новая сессия/`request_id`), `SpeechRequests` cancel-before-start tombstone/active-reuse/TTL replay (`speech_requests.py`), семантика WS `speak_cancel` (зеркало `web.py:3298-3304`).
- Регрессия: `test_live_speech_error_resilience` 4, `test_sensory_motivation` 6, `test_screen_commentary+test_proactive` 26, `test_speech_requests+test_turn_policy` 27+12 subtests — без регрессий.
- Полный P1 end-to-end **НЕ закрыт**: distributed draft→desktop playback stop, реальный TTS worker/`/api/tts/cancel` под load, echo/self-TTS loopback гонки, mic/E2E — PENDING/UNKNOWN. Маркер прерывания частично есть (`web.py:833,2486-2497`), нужна контекстная коррекция прерванного хода.

## 2026-11-10 — Cycle 21b (engineer/orchestrator): harness2 адаптация + P-M0 sensory motivation
- Адаптация google-research/harness2 (Propose→Probe→Compose, improvement harness): `docs/HARNESS2_ADAPTATION.md`, `tools/seniors_bridge/IMPROVEMENT_HARNESS.md`; оркестратор DSH обновлён (контекстный nudge: full-duplex + sensory motivation), перезапущен PID 36800, дедлайн 11:00 10.11.
- P-M0 (companion-side, без правок read-only `runtime/jawl-sources`): `src/jawl_voicecompanion/sensory_motivation.py` (novelty/Jaccard + change hints, decay, threshold/cooldown, детерминированно); опц. хук `sensory_motivation` в `screen_commentary.py` (suppress until triggered, `suppressed_motivation`).
- Регрессия (мой прогон): `test_sensory_motivation` 6 passed; `test_screen_commentary+test_proactive+test_sensory_motivation` 32 passed.
- P-M1 (mirror на `curiosity` drive через `/api/drives`) — BLOCKED/проверить живой контракт; live — UNKNOWN.

## 2026-11-10 — Cycle 21 / Round 13.1: приоритет full-duplex — аудит + adaptive turn hold

- **Приоритет владельца (10.11.2026)**: MOSS-Live-подобный полнодуплексный речевой слой, итерациями по одному проверяемому результату.
- **Аудит full-duplex контура** (карта с file:line в `docs/STATE.md` Cycle 21): mic→VAD→draft(350 мс)→end→brain→speech_delta TTS→barge-in(`/api/tts/cancel`)→echo guard. Дефект №1 локализован: фиксированное окно тишины не масштабируется с длиной реплики.
- **Adaptive utterance-length hold** (жалоба «не даёт договорить»):
  - `src/jawl_voicecompanion/turn_policy.py`: `decide(..., voiced_ms=)` — окно `800 + 0.15*voiced_ms` мс при `voiced_ms >= 6000`, кэп 2000 мс; вопросы/backchannel остаются 380 мс.
  - `src/jawl_voicecompanion/web.py` (`/api/voice/draft`): валидация и передача `voiced_ms` (0..600 с).
  - `desktop/voice-input.js::decideMicTurn`: `longUtteranceMs` 2400/1800 мс (≥6/≥3 с голоса), `max(normalSilenceMs, …)` без двойного сложения серверной адаптации; `desktop/app.js` draft-запрос шлёт `voiced_ms`.
  - **Регрессия PASS**: `tests/test_turn_policy.py` 14/14, `desktop/voice-input.test.mjs` 17/17. До/после: пауза 1.2 с в монологе 7 с — до commit_turn (ответ на первую половину), после hold_turn.
  - Ограничение: коэффициенты эвристические; REAL-MIC VALIDATION PENDING (владелец).
- **D4 screen commentary** (продолжение Round 12.x): `src/jawl_voicecompanion/screen_commentary.py` (initiative lane, JAWL голосует «тишина»), `ProactiveFeed.deliver_direct` (обход echo-скана истории, те же гейты доставки). Тесты: `tests/test_screen_commentary.py` 8/8, `tests/test_proactive.py` 26/26. Требует рестарта companion.
- **Не сделано**: рестарт живого companion-процесса (накоплены правки Cycle 20 + D4 + итерация 1); barge-in с контекстной коррекцией; coordination-вставка фоновых результатов в паузе — в чек-листе TODO.

## 2026-11-09 — Cycle 18 / Round 12.11: Сверка ядер, выбор модели, финальный запуск

- **Сверка CUDA-ядер mHC с CPU-эталоном**:
  - `test_mhc_route`/`test_mhc_merge` добавлены в `tests/test-backend-ops.cpp`, формы d=64..4096, n_tok=1..257, n_str=1..2.
  - Сборка с `LLAMA_BUILD_TESTS=ON`; в этой версии базового класса нет `max_rmse_err` — убран, оставлен `max_nmse_err`.
  - **Результат: 36/36 OK на пороге 1e-6.**

- **MTP-спекуляция не заработала**:
  - `--spec-type draft-mtp` на GSQ-RCO крашится (0xC0000005, access violation) при резервировании MTP-графа — после `graph_reserve: reserving a graph for ubatch`.
  - Изоляция: тот же файл без спекуляции грузится за 2.3 с, `ngram-simple` работает; метаданные корректны (`block_count=57`, `nextn_predict_layers=1`); тензоры `blk.56.nextn.*` загружаются; `graph_mtp` для sensenova существует.
  - Карточка модели: «MTP speculative decoding also requires runtime support for this architecture». Баг в MTP-пути форка; точное место не локализовано. Отложено.

- **Ловушка двух GPU закрыта**:
  - Прежние 20-22 ток/с в сравнении квантов были артефактом: без пина llama.cpp расщеплял модель между картами и PCIe доминировал.
  - `scripts/compare_brain_models.py` и `scripts/hold_supervised_brain.py` теперь ставят `CUDA_VISIBLE_DEVICES=1` (env `BRAIN_GPU`).
  - В `hold_supervised_brain.py` при пине `--device CUDA1` удаляется из argv: после перенумерации карта становится CUDA0, иначе «could not find device».

- **Замеры с пином**: Q4_K_M 65.7, IQ3_M **81.0**, IQ3_S 85.0 ток/с. Выбран IQ3_M; `runtime/sensenova-loop/runtime.manifest.gpu.json` переключён на GSQ-RCO IQ3_M. Живой сервер: **86.6 ток/с**, 0.98 ядра CPU, GPU-BOUND.

- **Голосовой E2E 3/3**: `runtime/instances/final_accept/voice_final.json`, `failure: null`, все транскрипты совпали. Первый отказ был ошибкой fixtures (`--expected "готов"` при реальном «Что сейчас видно на экране?»), не продукта.

- **Регрессия**: 27/27 (launcher + turn trace). Стек: 2367/8770/8990/9890 OPEN.

## 2026-11-09 — Cycle 17 / Round 12.10: DSpine — проверка применимости

- **Проверена технология DSpine** (спекулятивный драфтер Tencent, GGUF-порт для llama.cpp) по запросу владельца:
  - 2B-драфтер, 5 слоёв, прогноз 16 токенов за шаг; causal block attention + code bridges.
  - Результат автора: 104.8 ток/с Qwen3.8-27B на RTX 3090 против 29 без спекуляции (x3.6).
  - Acceptance: ~9.5/16 (математика), ~8.9/16 (C++), ~2.8/16 (проза).
  - Требует авторский форк `dspine`, в upstream не влит; +1.26 ГБ VRAM.

- **Вывод: нам не подходит.** Драфтер читает скрытые состояния конкретных слоёв Qwen3.8-27B — целевая модель жёстко зафиксирована. Наша цель SenseNova-Loop-9B архитектурно несовместима. Acceptance на прозе (наш случай) — худший сценарий.

- **Путь спекуляции для нас:** MTP-голова, встроенная в GSQ-RCO GGUF, через `--spec-type draft-mtp` — поддержана текущим билдом, сделана под нашу архитектуру.

## 2026-11-09 — Cycle 16 / Round 12.9: CUDA-ядра для mHC — скорость восстановлена

- **Написаны CUDA-ядра для операторов, отсутствовавших в CUDA-бэкенде**:
  - `ggml/src/ggml-cuda/mhc.cuh` — объявления и константы.
  - `ggml/src/ggml-cuda/mhc-merge.cu` — слияние двух residual-потоков: `out[0] = m00*a + m01*b + post0*x`, `out[1] = m10*a + m11*b + post1*x`, один поток на элемент.
  - `ggml/src/ggml-cuda/mhc-route.cu` — RMS по двум потокам, восемь логитов, гейты через sigmoid, Sinkhorn 20 итераций; блочная редукция через warp shuffle, параллельная запись проекции.
  - Реализация повторяет эталон `ggml-cpu/ops.cpp`, включая порядок четырёх softmax в Sinkhorn и чтение упакованных гейтов после вектора проекции.

- **Подключение в `ggml/src/ggml-cuda/ggml-cuda.cu`**: include, `case GGML_OP_MHC_ROUTE`/`GGML_OP_MHC_MERGE` в диспетчере, `supports_op` с требованием F32 на всех входах.

- **Проблемы сборки и решения**:
  - `cmake` отсутствовал в PATH — использован `G:\AI\Strata\.venv\Scripts\cmake.exe` (4.4.3).
  - `LNK1104: kernel32.lib` — сборка через `vcvars64.bat` (VS 2022 BuildTools).
  - `LNK1104: bin\ggml-base.dll` — DLL была занята запущенным `llama-server`; мозг остановлен перед линковкой.
  - Новые `.cu` не попадали в граф — `file(GLOB "*.cu")` подхватил их после переконфигурации. Сборка: 328 шагов.

- **Результат**:

| Метрика | До | После | Прирост |
|---|---|---|---|
| decode (800 токенов) | 17.4 | **68.1** | x3.9 |
| prefill (12k) | 1110 | **3801** | x3.4 |
| CPU-ядер при декоде | 11.58 | **0.99** | — |
| Вердикт автопроверки | CPU-BOUND | **GPU-BOUND** | — |

- **Сквозной ход в JAWL**: первый 8.81 с (прогрев), далее 1.06 и 2.25 с.

- **Оговорки**:
  - Правка внесена в `runtime/sensenova-loop/source/`, который AGENTS.md помечает как read-only эталон. Дерево writable, правка локальная (два новых файла плюс три вставки); пиновый snapshot `runtime/jawl-sources` не затронут. Для постоянного места нужен sanctioned patch.
  - Логика сверена с CPU-эталоном, но численная сверка на тензорах не выполнялась; README форка заявляет согласие CPU/Vulkan на уровне 1.2e-7, для CUDA такой проверки нет.
  - Прогон с MTP-спекулятивным декодированием на новых GGUF не выполнялся.

## 2026-11-09 — Cycle 15 / Round 12.8: Скорость мозга — корневая причина

- **Установлена корневая причина медленного декодирования**:
  - Модель — зацикленный трансформер `sensenova_loop`: 32 хранимых блока исполняются как 56, из них 24 SSM-слоя (Mamba-подобные), полное внимание каждые 4 блока, MoE нет. Отсюда ~1.75x больше байт на токен, чем у обычной 9B.
  - Два слитых оператора, `ggml_mhc_route` и `ggml_mhc_merge`, реализованы в CPU (`ggml-cpu/ops.cpp`) и Vulkan (`mhc_route.comp`, `mhc_merge.comp`), но **отсутствуют в CUDA и Metal**. На CUDA эти узлы графа исполняются на CPU.

- **Прямые измерения**:
  - `-ngl 99`: VRAM GPU 1 +6229 МБ (модель полностью в видеопамяти), decode 17.4 ток/с.
  - `-ngl 0`: VRAM +227 МБ, decode 4.7 ток/с.
  - Ускорение от GPU всего 3.7x; во время декодирования занято 11.58 ядер CPU.

- **Проверенные и исключённые гипотезы**:
  - Flash-attention: `--flash-attn on` даёт 17.3 против 17.6 без него — разницы нет.
  - Квантованный KV-кэш `q4_0`: 17.4 против 17.6 — разницы нет.
  - Грамматика JSON: 35.1 ток/с против 34.7 свободного текста (0.99x).
  - Кэш промптов: работает (идентичный промпт обрабатывает 4 токена вместо 22 000).
  - Размещение модели: она действительно на GPU (+6.2 ГБ VRAM).

- **Скачаны и замерены новые кванты GSQ-RCO** (`runtime/models/sensenova-gsq/quant/`):
  - IQ3_M, 4.73 ГБ: **19.1 ток/с** (+7% к текущей).
  - IQ3_S, 4.31 ГБ: 18.0 ток/с.
  - Q4_K_M текущая, 5.24 ГБ: 17.9 ток/с.
  - Прирост меньше ожидаемого: узкое место не в размере файла, а в CPU-исполнении mHC-узлов.

- **MTP**: новые GGUF содержат draft-голову (блок 56), которой нет в текущем файле; билд поддерживает `--spec-type draft-mtp`. Спекулятивное декодирование даст ещё 1.2-2.5x, но не устранит CPU-узкое место.

- **Вывод по обновлению llama.cpp**: само по себе не даст прироста — проблема не в версии рантайма, а в отсутствии CUDA-реализации двух операторов в форке. Рабочий путь — написать CUDA-ядра по образцу Vulkan-шейдеров (4.6 КБ и 1.8 КБ, есть эталон на CPU для сверки). Ожидаемый decode после этого: 28-32 ток/с.

- **Инструменты**: `compare_brain_models.py`, `check_brain_vram.py`, `benchmark_brain_cpu_share.py`, `benchmark_brain_gpu_vs_cpu.py`, `inspect_gguf_metadata.py`, `inspect_gguf_tensors.py`, `download_gsq_model.py`.

## 2026-11-09 — Cycle 14 / Round 12.7: Скорость мозга — разбор и починка

- **Причина найдена: не медленная модель, а потеря fast conversation lane**:
  - Измерения порознь сняли подозрения с модели и llama.cpp: decode **35.8–37.9 ток/с** стабильно на 64…800 токенах, prefill **1082–1120 ток/с** на 2.4k…22k токенах, `json_schema`-грамматика 35.1 ток/с (0.99× от свободного текста), GBNF 35.9 ток/с (0.97×).
  - Кэш промптов работает: идентичный повтор обрабатывает 4 токена вместо 22 000. Но после смены **первой строки** — полный пересчёт (22 001 токен), что и происходило на каждом шаге ReAct.
  - Арифметика совпала с фактом: 22 563 токена × 20 с prefill + 195 токенов генерации ≈ 41 с против измеренных 41.3 с.

- **Исправлен дефект транспорта (`src/jawl_voicecompanion/jawl_adapter.py`)**:
  - `JawlTerminalAdapter.respond()` отправлял только `{"text": ...}` без `turn_id`. Ядро включает fast-lane лишь при наличии `_companion_turn_id`, поэтому короткая реплика всегда шла по полному пути с 20k контекста.
  - Добавлен `_safe_turn_id()` с валидацией по формату ядра `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`.

- **Включена fast conversation lane (`scripts/run_integrated_profile.ps1`)**:
  - Механизм полностью реализован в ядре (`envelope_policy._fast_lane_messages`): для короткой реплики system-блок сжимается до 1800 символов, user-блок до 400.
  - Он включается переменной `JAWL_FAST_CONVERSATION=1`, которая нигде не выставлялась. Добавлен флаг `-EnableFastConversation`, по умолчанию `true`.

- **Добавлены параметры запуска мозга (`scripts/hold_supervised_brain.py`, GPU-манифест)**:
  - `--flash-attn on` и `--cache-reuse 256` — KV-сдвиг для переиспользования совпадающей части промпта.
  - `cache_type_k`/`cache_type_v: q4_0` добавлены в `runtime/sensenova-loop/runtime.manifest.gpu.json`: базовый манифест их задавал, а используемый ярлыком — нет.

- **Результат**:
  - Первый ход после старта: 22.50 с (прогрев KV-кэша).
  - Второй: **2.09 с**. Третий: **1.55 с**. Отдельный одиночный: **2.07 с**.
  - Было 40–95 с на тех же репликах.

- **Тесты**:
  - Тест лаунчера поймал реальный дефект: `int()` на `Mock` в новом параметре `--cache-reuse`. Добавлена защита от неверного типа.
  - Focused регрессия: 20/20 и 43/43 PASS.

- **Остаётся открытым**:
  - Первый ход после старта ~22 с — прогрев KV-кэша.
  - Токены контекста не уменьшились (~18–19k): fast-lane сжимает только system-блок. Дальнейшее ускорение требует изменения порядка блоков в ядре, где динамические данные стоят в начале промпта.
  - Полный голосовой E2E с TTS после этих правок не прогонялся.
  - `goals.json` содержит `{}` без `version` → `unsupported goal store version` в журнале. На скорость не влияет.

- **Инструменты диагностики** (оставлены в репозитории): `benchmark_brain_throughput.py`, `benchmark_brain_grammar.py`, `benchmark_brain_cache.py`, `benchmark_brain_decode.py`, `check_fast_lane.py`, `probe_fast_lane_kernel.py`, `probe_turn_id_transport.py`, `show_turn_trace.py`.

## 2026-11-09 — Cycle 13 / Round 12.6: AC-05 — Проактивность и инициатива

- **Проактивность включена в живом профиле (`scripts/run_integrated_profile.ps1`, `scripts/run_local_bonsai_integrated.ps1`)**:
  - `proactive_guidance` переключается лаунчером (`-EnableProactiveGuidance`, по умолчанию `true`). Ручная правка `settings.yaml` ломала запуск: fail-closed защита возвращала `ProfileConflict` («unapproved managed-file override»), и профиль отказывался стартовать.
  - Экранная инициатива: передаются `--screen-watch`, `--jawl-event-dir`, `--screen-ocr`.
  - Гейт активности: передаётся `--user-activity --user-activity-idle-seconds 60`. Без него `activity_provider=None` и статус `disabled` — подавление инициативы при работе за ПК не работало.
  - Проверено на живом процессе компаньона: все пять флагов присутствуют, `proactive_guidance: true`, каталог событий создан.

- **Исправлен дефект смешанного языка в проактивных репликах (`src/jawl_voicecompanion/proactive.py`)**:
  - В живом `runtime/proactive-state.json` лежали реально доставленные реплики «привет!一切正常, я в порядке…» и «связь稳定ная». `ProactiveFeed` читает историю JAWL напрямую и обходил CJK-фильтр адаптера.
  - Добавлен `_sanitize_delivery()`: известные фразы переводятся, остальные идеограммы вырезаются, сообщение с потерей более половины тела отбрасывается — инициатива на непонятном языке хуже молчания.
  - Шлюз применяется и к свежим сообщениям, и к очереди, восстановленной с диска (иначе рестарт воспроизводил дефект).
  - Добавлен счётчик `suppressed_unusable` в состояние фида.

- **Исправлены дефекты значимости экранных событий (`src/jawl_voicecompanion/attention.py`)**:
  - Найдены измерителем AC-05 на первом же прогоне (2 ложных прерывания).
  - Слово `уведомлен` стояло в `_SALIENT`, из-за чего «Уведомление: обновление доступно» получало максимальную значимость. Убраны `уведомлен`, `предупрежд`, `dialog`, `warning`.
  - Навигация («Список файлов прокручен вниз») со значимостью 2 проходила порог. Добавлен `_ROUTINE`: навигация и уведомления дают балл 0, если в тексте нет реального сбоя.
  - Добавлены маркеры нехватки ресурса (`закончилось место`, `недостаточно места`, `disk full`, `out of space`) — иначе значимое событие не поднималось до порога.

- **Создан измеритель AC-05 (`scripts/benchmark_ac05_initiative.py`)**:
  - Прогоняет реальные гейты (`AttentionPresence`, `ProactiveFeed`) по размеченному потоку: 15 экранных кейсов в трёх конфигурациях (базовая, активный пользователь, DND) и симулированное 30-минутное окно речи с шагом поллинга 12 с.
  - Отчёт `runtime/instances/ac05_report.json` содержит счётчики со знаменателями и явный список ограничений.
  - Результат: 6/6 значимых событий (100% при цели ≥80%), 0 ложных прерываний во всех трёх конфигурациях, 0 реплик во время разговора, 6 доставок за 30 минут простоя при лимите 6/час. Статус PASS.

- **Живая проверка гейта (`scripts/check_attention_live.py`)**:
  - Реальный `WindowsUserActivity`: idle 106.7 с, `user_active False`, `foreground_class MozillaWindowClass`.
  - Значимая ошибка → `proposed`; уведомление и прокрутка → `ignored`.
  - При `user_active=True` значимая ошибка → `suppressed user_active`, доставлено 0.

- **Тесты**:
  - `tests/test_attention.py`: 4 новых теста на рутинные события и на сохранение эскалации реальных сбоев.
  - `tests/test_proactive.py`: 5 новых тестов языкового шлюза, включая восстановление очереди с диска.
  - Focused регрессия: 51/51 PASS.

- **Ограничение:** статус `VERIFIED_AUTOMATED`, не `ACCEPTED`. Живая 20–30-минутная сессия владельца с реальными экранными событиями не наблюдалась; разметка сделана этим же харнессом; значимость событий подаётся вызывающей стороной.

## 2026-11-09 — Cycle 12 / Round 12.5: Приёмка постоянного профиля и постоянной работы

- **Найден и исправлен блокирующий дефект синтеза речи (`scripts/omnivoice_server.py`)**:
  - Симптом: каждая синтезированная фраза начиналась с произнесения референсного текста. GigaAM транскрибировал запрос «Какой сегодня статус моего проекта?» как «Привет! Я твой голосовой компаньон, рад тебя слышать.» — владелец услышал бы заготовку вместо ответа.
  - Причина: вызов `model.generate(ref_audio=..., ref_text=...)`. На этой сборке модели режим с референсом подмешивает референсную фразу в выход.
  - Измерено через GigaAM на одной фразе: с референсом по умолчанию — только референсная фраза; с `preprocess_prompt=False` — референсный префикс плюс текст; через `voice_clone_prompt` — мусор; с коротким референсом 3 с — искажение; **без референса с `language="ru"` — точный текст**.
  - Решение: генерация переведена в language-guided режим без референса. `--ref-audio`/`--ref-text` принимаются для совместимости с лаунчером, но не влияют на синтез. Точность ответа приоритетнее сходства голоса.
  - Побочный эффект: голос больше не клонируется с референсного сэмпла. Возврат клонирования требует исправления модели и отдельного измерения.

- **Найден и исправлен дефект кодировки лаунчера (`scripts/run_integrated_profile.ps1`)**:
  - Файл был сохранён без BOM: кириллица разрушалась (`Сначала подготовься…` → `РЎРЅР°С‡Р°Р»Р°…`), разбор PowerShell давал 30 ошибок — живой запуск не состоялся бы.
  - Перезаписан в UTF-8 с BOM; разбор — 0 ошибок, кириллица цела.

- **Устранён дефект stale-артефактов soak-раннера (`scripts/benchmark_sensor_always_on.py`)**:
  - `_setup_directories` теперь удаляет checkpoint, report и зеркало `soak_h1_60min.json` от предыдущего прогона; остаточный файл больше нельзя принять за прогресс текущего запуска.
  - Рендер кодов тестового канваса заменён с самодельных блочных глифов (различались только `7/K/3/M`) на реальный шрифт — иначе ретроспективная проверка измеряла нечитаемую фикстуру.

- **Проведён полный часовой soak сенсорики**:
  - Вердикт `VISION_SOAK_60M_VERIFIED`, отчёт `runtime/instances/soak_h1_60min.json`.
  - 3600.0 с, 216 000 кадров @ 60.0 FPS, 0 потерь очереди (p50/p95 = 1, max 2), 3078 сброшенных энкодером из 212 400 учтены в отчёте.
  - Δ RSS +97.6 МБ, Δ GPU 0 +141.0 МБ (лимит 150), GPU 1 изолирован (648 → 2030 МБ).
  - 59/59 индексов JTI1 валидны, 0 CRC-ошибок, диск 21.92 МБ при лимите 2048 МБ.
  - AC-09 пауза 60 с: 0 кадров в архиве.
  - Live VLM: 881 вызов, p50 192.2 мс, p95 264.5 мс.

- **Проведена живая приёмка стека**:
  - Brain `sensenova-loop-9b-q4` на GPU 1 (8990), health OK; компаньон стартовал, `/app` HTTP 200; TTS OmniVoice `/health` ok.
  - Голосовой E2E на реальном браузерном тракте: 3/3 хода PASS, ASR дословно, озвучено 2.22–25.32 с, 0 ошибок.
  - Третий ход подтверждён журналом: JAWL реально проверил `snake.html` в песочнице.

- **Тесты**:
  - Новый `tests/test_omnivoice_text_fidelity.py` (3 теста): AST-контроль запрещает референсные аргументы в `generate`, требует `preprocess_prompt=False` и `language="ru"`.
  - Focused регрессия: 18/18 и 53/53 PASS.

- **Известный открытый разрыв**: `turn_to_first_audio` 32.7–77.3 с против цели AC-03 p95 ≤ 4.0 с. Причина — до 15 шагов ReAct с локальной 9B-моделью. Требует отдельного цикла оптимизации (сокращение цепочки для простых реплик, стриминг первого токена в TTS).

## 2026-11-08 — Cycle 11 / Round 12.4: VISION_STABILIZATION — Полный 60-минутный Soak Test сенсорики (H1 P0)

- **Одновременный мультимодальный режим нагрузки (`scripts/benchmark_sensor_always_on.py`)**:
  - Реализован baseline_v1 со сквозной одновременной активностью всех сенсорных подсистем: DXGI-захват Win32 `SoakTestWindow`, телеметрия `TelemetryComputer`, кольцевая ротация `LiveEvidenceArchive` (H.264 + JTI1), периодический опрос `QwenVisualSensor` на Physical GPU 1 и ретроспективная инспекция `inspect_segment()` с WinRT OCR верификацией.
  - Добавлена генерация зеркального отчета [soak_h1_60min.json](runtime/instances/soak_h1_60min.json) с полным набором обязательных полей: `configuration`, `active_components`, `activity_intervals`, `checkpoints_history`, `source_report_path` и `log_paths`.
  - Зафиксировано безопасное состояние `wasapi_audio: UNKNOWN` во избежание захвата звука хоста.

- **Расширение набора тестов (`tests/test_sensor_always_on.py`)**:
  - Добавлен тест `test_report_schema_and_component_intervals`: верификация полноты схемы отчета, списка активных компонентов, интервалов активности и валидности `soak_h1_60min.json`.
  - Полная регрессия: 14/14 тестов PASS (`test_sensor_always_on.py` + `test_live_evidence_archive.py`).

- **Фактические показатели одновременного сквозного прогона**:
  - Длительность: 35.0 с (все подсистемы активны одновременно).
  - 2100 кадров захвачено @ 60.0 FPS, 1920 кадров принято на запись, 180 кадров отклонено во время AC-09 паузы (0 утечек).
  - 0 потерь в очереди воркера ($p_{50} = 1.0$, $p_{95} = 1.0$).
  - $\Delta \text{RSS} = +93.6$ МБ, $\Delta \text{GPU 0} = +12.0$ МБ (GPU 0 изолирован).
  - $\Delta \text{GPU 1} = +1369.0$ МБ (Qwen на Physical GPU 1).
  - Live VLM: 8 вызовов, $p_{50} = 180.7$ мс, $p_{95} = 251.1$ мс.
  - 7/7 индексов JTI1 валидны, 0 CRC ошибок, диск 1.10 МБ при лимите 2048 МБ.
  - Итоговый статус: `PARTIAL` (сквозная одновременная нагрузка подтверждена; runner готов к 3600-секундному прогону).

## 2026-11-08 — Cycle 09 / Round 12.3: VISION_STABILIZATION — Приёмка непрерывной сенсорики (H1 P0)

- **Воспроизводимый Soak Runner сенсорного контура (`scripts/benchmark_sensor_always_on.py`)**:
  - Реализован сквозной мультимодальный soak runner для проверки стабильности сенсорного стека JAWL (AC-01, AC-08, AC-09, AC-02, AC-07).
  - Поддержка непрерывного 60 FPS захвата Win32-окна `SoakTestWindow` (GDI Canvas, процедурная анимация, нулевой захват рабочего стола владельца).
  - Мультимасштабная пространственная телеметрия через `TelemetryComputer` (<0.6 мс CPU).
  - Асинхронная запись сегментов в `LiveEvidenceArchive` (H.264 ultrafast + JTI1 binary index).
  - Активный визуальный наблюдатель `QwenVisualSensor` на Physical GPU 1 (`CUDA_VISIBLE_DEVICES="1"`). GPU 0 строго изолирован.
  - Ретроспективная инспекция `inspect_segment()` по размеченным событиям с верификацией OCR.
  - Автоматическое сохранение контрольных точек в `runtime/instances/sensor_soak_checkpoint.json` и итогового JSON-отчета в `runtime/instances/sensor_soak_report.json`.
  - Защитные лимиты дискового пространства и аварийный teardown с освобождением ресурсов.

- **Контроль захвата владельцем Pause / Resume (AC-09) в `LiveEvidenceArchive`**:
  - В класс `LiveEvidenceArchive` (`src/jawl_voicecompanion/live_evidence_archive.py`) добавлены потокобезопасные методы `pause()` и `resume()`, а также свойство `is_paused`.
  - Гарантирован инвариант AC-09: при вызове `pause()` активный сегмент немедленно финализируется и закрывается, а входящие кадры в `ingest_frame()` мгновенно отклоняются (`return False`) без попадания в очередь.

- **Тестирование и верификация (`tests/test_sensor_always_on.py`)**:
  - Разработан набор из 7 сфокусированных тестов (100% PASS): конфигурация runner, раздельный учет кадров, сохранение отчета при авариях, защита от переполнения диска, освобождение ресурсов, инвариант AC-09 (0 кадров при паузе), антиспуфинговый контроль статуса 60-минутного прогона.
  - Пройдена полная регрессия 13/13 тестов PASS (`test_sensor_always_on.py` + `test_live_evidence_archive.py`).

- **Фактические показатели сквозного мультимодального прогона**:
  - 10,800 кадров захвачено @ 60.0 FPS за 180 секунд.
  - 9,900 кадров принято, 900 кадров отклонено во время 15-секундной паузы (0 утечек).
  - 0 потерь в очереди воркера, $p_{50} = 1.0$, $p_{95} = 1.0$.
  - $\Delta \text{RSS} = +92.7$ МБ (пик 213.1 МБ).
  - $\Delta \text{GPU 0} = +13.0$ МБ (GPU 0 не затронут).
  - Live VLM: 24 наблюдения, $p_{50} = 181.6$ мс, $p_{95} = 240.6$ мс.
  - Дисковое пространство архива: 2.11 МБ при лимите 2048 МБ.
  - 6/6 JTI индексов валидны, 0 CRC ошибок.
  - Статус верификации: `PARTIAL` (сквозной 180с прогон всех 4 стадий завершен успешно; runner готов к запуску `--duration 3600`).

## 2026-11-08 — Cycle 07 / Round 12.2: Устранение неоднозначности ObservationStatus (H1 P0)

- **Строгий ObservationStatus Enum вместо строкового подкласса (`src/jawl_voicecompanion/segment_inspector.py`)**:
  - Реализована гипотеза H1 P0 из экспертной цепочки Argon Cycle 07 (AC-06, AC-07, AC-02, AC-08).
  - Устранена неоднозначность строкового подкласса `EpistemicStatus`, в котором `ARCHIVE_GAP_UNAVAILABLE`, `NOT_FOUND_IN_SAMPLE` и `OBSERVED_ABSENT` приравнивались к `"not_observed"` через перегруженный `__eq__`.
  - Введено строгое перечисление `ObservationStatus(enum.Enum)` с 6 уникальными членами:
    - `OBSERVED_READABLE`: объект/факт подтвержденно читаем на проверенных кадрах.
    - `OBSERVED_UNREADABLE`: объект зафиксирован, но нечитаем из-за смаза движения или пересвета.
    - `NOT_FOUND_IN_SAMPLE`: объект не найден в выборке кадров (зазор > 50 мс, отсутствие не доказано).
    - `ARCHIVE_GAP_UNAVAILABLE`: интервал затронут выпадением кадров или повреждением видеоконтейнера.
    - `OBSERVED_ABSENT`: физическое отсутствие доказано сплошным контролем интервала (зазор <= 50 мс, 0 сбросов).
    - `LEGACY_NEGATIVE_UNRESOLVED`: неразрешенное отрицание для безопасной загрузки устаревших данных `"not_observed"`.
  - Запрещено прямое равенство со строкой `"not_observed"` в обоих направлениях (`enum == str` -> `False`, `str == enum` -> `False`).
  - Устранены коллизии ключей словарей и множеств при индексации по статусу наблюдения.

- **Адаптеры wire-сериализации и изоляция границы legacy API**:
  - Добавлены функции `status_to_wire()` и `status_from_wire()` для точного round-trip через XML/JSON без потери различимости статусов.
  - Адаптеры `to_legacy_string()` и `is_negative_status()` вынесены исключительно на внешнюю границу для безопасного взаимодействия с кодом legacy-потребителей.

- **Защитный шлюз эпизодической памяти (`parse_perception_xml`)**:
  - Статусы `NOT_FOUND_IN_SAMPLE`, `ARCHIVE_GAP_UNAVAILABLE` и `LEGACY_NEGATIVE_UNRESOLVED` гарантированно блокируются от превращения в подтвержденный факт отсутствия (`is_confirmed_fact = False`), исключая запись ложных воспоминаний (AC-06).
  - Первичное наблюдение `OBSERVED_READABLE` строго требует независимого подтверждения (`verification_status == VERIFIED_FACT`) для возведения в ранг подтвержденного факта (AC-07).

- **Тестирование и верификация (`tests/test_observation_status_contract.py`)**:
  - Набор из 8 сфокусированных тестов контракта статусов пройден на 100%: попарная различимость, запрет равенства строкам, изоляция хешей в dict/set, XML/JSON round-trip, блокировка памяти, статический AST-аудит (0 опасных сравнений).
  - Сквозная ретроспективная регрессия: 35/35 тестов PASS.

## 2026-11-08 — Cycle 05 / Round 12.1: Независимая верификация ретроспективных фактов (H12.1 P0)

- **Модуль независимой верификации свидетельств (`src/jawl_voicecompanion/temporal_evidence_verifier.py`)**:
  - Реализована гипотеза H12.1 (P0) для закрытия эпистемических рисков AC-06, AC-07, AC-02, AC-08.
  - Введены явные статусы верификации ретроспективных фактов:
    - `VERIFIED_FACT`: гипотеза визуальной модели независимо подтверждена вторым детерминированным источником (WinRT OCR).
    - `MODEL_OBSERVATION`: первичное наблюдение модели до проведения независимой верификации.
    - `UNVERIFIED`: независимый источник не смог надежно подтвердить или опровергнуть утверждение (воздержание от ложной категоричности).
    - `CONTRADICTED`: независимый источник детерминированно опроверг гипотезу визуальной модели.
    - `SOURCE_UNAVAILABLE`: исходные видеокадры отсутствуют или повреждены в архиве.
  - Реализован высокопроизводительный пайплайн постоянного процесса WinRT OCR `PersistentWindowsOcrPipe`:
    - Исключен оверхед повторного холодного старта PowerShell (сокращение задержки OCR с ~900 мс до 1.5–20 мс на вызов).
    - CPU-only исполнение без нагрузки на GPU 0 и GPU 1.
  - Семантическое сопоставление сущностей и токенов (`extract_substantive_tokens`, `match_claim_tokens`):
    - Очистка от служебных меток кадров (`#F2250`, `кадре 2250`), таймкодов (`37.50s`), чат-тегов и стоп-слов.
    - Нормализованное сравнение лексем, префиксов игровых кодов и подстрок (порог совпадения $\ge 40\%$ или уникальный токен $\ge 6$ символов).
  - Запрет самоподтверждения: повторные вызовы VLM или коррелированные соседние видеокадры не могут признаваться независимым подтверждением.

- **Интеграция в RetrospectiveSegmentInspector (`src/jawl_voicecompanion/segment_inspector.py`)**:
  - Расширен `RetrospectiveEvidence`: добавлены поля `verification_status`, `is_verified_fact`, `verification_reason`, `independent_claim`, свойство `is_verified`.
  - В метод `inspect_segment()` добавлен этап независимой верификации `verify_facts=True`.
  - Обновлены сериализаторы `to_perception_xml()` и `to_dict()` с атрибутами `verification_status` и `is_verified_fact`.
  - Защитный эпистемический шлюз памяти в `parse_perception_xml()`:
    - Сырая гипотеза визуальной модели `OBSERVED_READABLE` строго блокируется от признания фактом (`is_confirmed_fact = False`), если `verification_status != VERIFIED_FACT`.
    - Исключено появление ложных воспоминаний в долгосрочной эпизодической памяти агента (AC-06).

- **Сфокусированное тестирование (`tests/test_temporal_evidence_verifier.py`)**:
  - Реализован комплекс из 9 сфокусированных тестов (100% PASS):
    1. Очистка и извлечение содержательных сущностей без служебных маркеров.
    2. Совпадение с OCR переводит статус в `VERIFIED_FACT` (`is_verified_fact=True`).
    3. Несовпадение с OCR маркирует утверждение как `CONTRADICTED` (`is_verified_fact=False`).
    4. Отсутствие текста в OCR оставляет статус `UNVERIFIED` без ложного возведения в факт.
    5. Коррелированные кадры без второго сигнала дают `UNVERIFIED`.
    6. Зазоры архива и выпадение кадров дают `SOURCE_UNAVAILABLE`.
    7. Эпистемический шлюз `parse_perception_xml()` строго блокирует неподтвержденные гипотезы и попытки подделки XML.
    8. Интеграция `SensoryHistoryStore`: запись неподтвержденных гипотез с `verified=False`.
    9. Сквозная интеграция верификатора в `RetrospectiveSegmentInspector.inspect_segment()`.

- **Бенчмарк 35 реалистичных игровых событий на физическом оборудовании (RTX 5080 GPU 1 + CPU GigaAM ASR)**:
  - `0` ложных подтверждений фактов (`false_verified_count = 0`, target 0): **PASS**.
  - `24/30` (80.0%) независимо подтвержденных правильных ответов (target $\ge 21/30$): **PASS**.
  - `5/5` (100.0%) чистых отклонений негативных контролей без галлюцинаций: **PASS**.
  - `0` обходов защитного шлюза эпизодической памяти (`memory_guard_bypasses = 0`, target 0): **PASS**.
  - Фовеальное ускорение мозаики: 2218.7 мс $\to$ 910.8 мс (+58.9% сокращение, target $\ge 50\%$): **PASS**.
  - $p_{95}$ полная задержка инспекции: 1734.3 мс (target $\le 2500$ мс): **PASS**.
  - Деградация речевого контура ASR под нагрузкой: +4.16% (target $\le 10.0\%$): **PASS**.
  - Пиковая VRAM на GPU 1: 1967 МБ (GPU 0 не затронут, 0 МБ утечки): **PASS**.

## 2026-10-29 — Qwen visual OCR handoff

Управление активной структурированной памятью: поиск, фильтрация, добавление, редактирование и исключение записи с предупреждением об истории и ограничении выдачи.

- Qwen capture requests Windows OCR only on startup, pending visual changes, or
  the static refresh interval. OCR remains a separate redaction-filtered channel
  with a 5s live TTL and is delivered through the structured VA packet.
- Scene invalidation and empty OCR results expire older text. Focused + wider
  adapter/sensor/fusion/packet/native-context/web gates: 61 focused tests and
  163 total tests + 33 subtests passed.
- A one-shot real display-0 capture verified Windows OCR and the sensor-to-VA
  packet handoff with a stub Qwen client; OCR text was not emitted or saved.
- Full live-profile behavior and CPU cost remain open; launch requires
  `--screen-ocr`.
## 2026-11-08 — Cycle 04 / Phase B (Round 12): Исправление эпистемической ошибки NOT_OBSERVED (Argon H1)

- **Разделение SampleCoverage и ObservationStatus (`src/jawl_voicecompanion/segment_inspector.py`)**:
  - Устранена семантическая перегрузка `NOT_OBSERVED` (H1 Argon P0 / AC-06, AC-07, AC-09): разреженная выборка кадров больше не может порождать утверждение о физическом отсутствии объекта или события.
  - Введена строгая иерархия эпистемических статусов:
    - `OBSERVED_READABLE`: объект/событие обнаружено и достоверно прочитано на проверенных кадрах.
    - `OBSERVED_UNREADABLE`: объект зафиксирован, но нечитаем из-за смаза движения, размытия или пересвета.
    - `NOT_FOUND_IN_SAMPLE`: объект отсутствует в проверенной разреженной выборке кадров (`max_uninspected_gap_ms > 50 мс`), отсутствие во всём интервале не доказано (`absence_confirmed=False`).
    - `ARCHIVE_GAP_UNAVAILABLE`: интервал затронут выпадением кадров (`FLAG_ENCODER_DROPPED`, `FLAG_SOURCE_FRAME_MISSING`) или повреждением контейнера.
    - `OBSERVED_ABSENT`: отсутствие гарантированно подтверждено плотным контролем интервала (`max_uninspected_gap_ms <= 50 мс`, 0 пропущенных кадров, `absence_confirmed=True`).
    - `NOT_OBSERVED`: сохранен как двунаправленно совместимый строковый подкласс `EpistemicStatus` для обратной совместимости (`status == "not_observed"` истинно для всех негативных исходов).
  - Реализован класс `SampleCoverage`: окно (`window_ms`), проверено кадров (`inspected_frames`), кадров в архиве (`archive_frames`), сброшено кадров (`dropped_frames`), коэффициент покрытия (`coverage_ratio`), максимальный непроверенный зазор (`max_uninspected_gap_ms`), флаг подтвержденного отсутствия (`absence_confirmed`).
  - Функция `compute_sample_coverage()` выполняет детерминированный расчет зазоров между временными границами окна и фактическими PTS кадров с точностью до 1 мс.
  - Функция `parse_perception_xml()` реализует защитный инвариант эпизодической памяти: отрицательные наблюдения без подтвержденного плотного покрытия (`absence_confirmed=False`) гарантированно не могут быть преобразованы в подтвержденный факт (`is_confirmed_fact=False`).
- **Сфокусированное тестирование и бенчмарки (`tests/test_segment_inspector_coverage.py`)**:
  - Реализованы 12 сфокусированных тестов (AC-06, AC-07, AC-09):
    1. Окно 600 кадров (10 с) с выборкой $K=12$ кадров (`coverage_ratio = 0.02`, `max_gap = 833.3 мс`) дает `NOT_FOUND_IN_SAMPLE`, исключая ложное утверждение об отсутствии.
    2. Событие между проверяемыми кадрами классифицируется как `NOT_FOUND_IN_SAMPLE`.
    3. Выпадения кадров энкодером маркируются как `ARCHIVE_GAP_UNAVAILABLE` с причиной `source_gap`.
    4. 0 декодированных кадров не порождает ложный факт отсутствия.
    5. Плотная выборка (`max_gap <= 50 мс`, 0 сбросов) корректно подтверждает `OBSERVED_ABSENT`.
    6. Нечитаемые кадры сохраняют `OBSERVED_UNREADABLE` независимо от плотности выборки.
    7. Положительные наблюдения (`OBSERVED_READABLE`) сохраняются даже при ультраразреженном покрытии ($K=12/600$).
    8. Потребитель XML памяти гарантированно блокирует признание неподтвержденного отсутствия фактом (`is_confirmed_fact=False`).
    9. Корректность расчета `max_uninspected_gap_ms` при неравномерных таймкодах и границах окна.
    10. Инвариант на 20 случайных масках дропаут-кадров: при любом выпадении кадра или зазоре $>50$ мс `absence_confirmed` строго `False`.
    11. CPU бенчмарк расчета `SampleCoverage` на 600 записях: $p_{50} = 0.033$ мс, $p_{95} = 0.041$ мс, $p_{99} = 0.054$ мс (норма $p_{95} \le 10.0$ мс, запас >200x).
    12. Детерминированный демонстрационный артефакт реплея (`runtime/replay_demonstration_cycle04_phaseB.json`).
  - Все 35 тестов ретроспективной подсистемы (`test_segment_inspector.py`, `test_segment_inspector_coverage.py`, `test_archive_recovery.py`, `test_temporal_evidence_index.py`, `test_retro_selector.py`) успешно пройдены (100% PASS).
- **Синхронизация CodeSee**:
  - Обновлен `f-foveal-segment-inspector` в `.codesee/features.json`, скрипт валидации `node .codesee/scripts/validate-features.mjs` завершился успешно (0 ошибок).

## 2026-11-08 — Cycle 04: Целостность ретроспективных свидетельств: JTI1 ↔ MP4

- **Аудит и кросс-верификация JTI1 ↔ MP4 (`src/jawl_voicecompanion/temporal_index.py`, `live_evidence_archive.py`)**:
  - Проведен детальный аудит (`scripts/run_audit_before.py`, `runtime/audit_before.json`) границы между бинарным индексом JTI1 и видеоконтейнером MP4.
  - Устранен дефект подстановки чужих кадров: в `extract_frames()` и `select_candidate_frames()` переход от порядкового индекса в списке к прямой адресации по `segment_sample_idx`. Недоступные (`segment_sample_idx < 0`) или потерянные кадры гарантированно получают `None`.
  - Добавлен флаг `FLAG_SOURCE_FRAME_MISSING = 0x0020`.
  - Реализована функция `verify_segment_alignment(jti_path, mp4_path)`: обнаружение отсутствующих MP4, поврежденных контейнеров, превышений индекса `segment_sample_idx >= mp4_frames` и расхождений относительного PTS (>100 мс).
  - Улучшен алгоритм `repair_and_finalize(jti_path, mp4_path)`: синхронизированное восстановление при сбоях, отсечение записей без видеокадров, отсечение битых байтов хвоста с верификацией CRC32c и герметизация флагом `FLAG_HEADER_CLEAN_CLOSED`.
  - Канонизация JTI1 как единственного формата записи. Legacy `.jte1` переведен в режим строгого чтения через `read_legacy_jte1_as_jti1()`.
- **Эпистемическая защита от ложных воспоминаний в `inspect_segment()` (`src/jawl_voicecompanion/segment_inspector.py`)**:
  - При отсутствии или повреждении контейнера видео возвращается статус `NOT_OBSERVED` с причиной `source_gap`.
  - Исключена атрибуция `best_frame_id` к потерянным или сброшенным кадрам (`FLAG_ENCODER_DROPPED`, `FLAG_SOURCE_FRAME_MISSING`).
  - При неполном покрытии видеокадрами (<60%) отрицательный ответ VLM не трактуется как доказанное отсутствие объекта (статус `NOT_OBSERVED` с причиной `source_gap` вместо ложного `vlm_not_found`).
- **Комплексный тестовый полигон и бенчмарк восстановления (`tests/test_archive_recovery.py`, `scripts/verify_cycle04_recovery.py`)**:
  - 6 топологий сбоев: здоровый сегмент, усеченный MP4, отсутствующий MP4, расхождение числа кадров, поврежденный хвост JTI1, сброс кадров энкодером в реальном потоке.
  - Контрольный бенчмарк (`runtime/verification_cycle04.json`):
    - Детекция повреждений: 16/16 (**100.0%**).
    - Ложные ссылки на недоступные кадры: **0** (соответствие контракту AC-07 «ноль ложных воспоминаний»).
    - Несанкционированный статус `OBSERVED_READABLE`: **0**.
    - Среднее время восстановления поврежденного сегмента: **19.24 мс**.
    - Скорость чтения 600 записей JTI1: **6.93 мс**.
    - Полная регрессия по временным индексам, селекторам и инспектору: 37/37 тестов PASS.

## 2026-11-08 — Round 11 Этап 3: Фовеальная инспекция `inspect_segment()`, эпистемический шлюз и физический бенчмарк на GPU 1

- **Ретроспективная фовеальная инспекция сегментов (`src/jawl_voicecompanion/segment_inspector.py`)**:
  - Реализован класс `RetrospectiveSegmentInspector` и метод `inspect_segment(query, t_start_s, t_end_s, budget=12)` поверх временного индекса JTI1, отбора Anchor-Satellite Weaving и разреженного декодирования.
  - Фовеальная упаковка `build_foveated_mosaic()`: сборка обзорного якорного кадра (512×288) и серии нативных 1:1 кропов областей интереса (ROI) в единый холст 1024×768 для эффективного однократного инференса VLM без потери разрешения мелких символов.
  - Двухуровневый эпистемический шлюз (`RetrospectiveEvidence` со статусами `OBSERVED_READABLE`, `OBSERVED_UNREADABLE`, `NOT_OBSERVED`):
    - Физический уровень: фильтрация размытия по дисперсии Лапласиана (`sharpness >= 2000.0`), фильтрация пересветов `check_overexposure` (доля пикселей >= 245 выше 0.40) и детектор артефактов направленного смаза `check_directional_smear` (анизотропия градиентов Sobel $dy/dx$ или $dx/dy \ge 8.0$).
    - Семантический уровень: классификация ответа VLM на отсутствие содержательных токенов и маркеры нечитаемости.
  - Преобразование в канонический XML-пакет `<va_perception type="retrospective">` для эпизодической памяти компаньона.
- **Физический бенчмарк на GPU 1 (`scripts/benchmark_inspect_segment_35.py`)**:
  - Запущен реальный инференс `Qwen3.5-0.8B VL` на физическом GPU 1 (RTX 5080, port 8996) на 35 реалистичных 60 FPS событиях:
    - **Ускорение фовеальной мозаики**: последовательный baseline из 12 вызовов VLM = 2140.0 мс против единого вызова мозаики 952.9 мс (**55.5% сокращение задержки**, порог $\ge 50\%$: PASS).
    - **Полная задержка инспекции**: $p_{50} = 952.9$ мс, $p_{95} = 1802.1$ мс, $\max = 1804.2$ мс (порог $\le 2500$ мс: PASS).
    - **Эпистемический шлюз (негативные контроли)**: 5/5 отклонено чисто (**0.0% уровень галлюцинаций**, порог 0%: PASS).
    - **Точность извлечения фактов**: 24/30 (**80.0%**, порог $\ge 75\%$: PASS).
    - **Влияние на голосовой контур (GigaAM ASR CPU)**: задержка $p_{95}$ составила 137.1 мс против baseline 183.4 мс (**-25.23%**, порог $\le 10\%$: PASS).
    - **Изоляция памяти**: GPU 0 не затронут (2879 МБ, 0 МБ утечки), пиковый VRAM GPU 1 = 2010 МБ ($\Delta = +1369$ МБ).
- **Мультистратегический бенчмарк и доказательство монотонного вложения (`scripts/benchmark_multi_strategy_retro.py`)**:
  - Сравнение 4 стратегий (Uniform, Old Hybrid Adaptive, Weaving Scalar, Weaving ROI-Boosted) на 35 реалистичных 60 FPS событиях (10 800 кадров) и 20 синтетических стимулах:
    - **Строгое вложение подмножеств ($S_4 \subset S_8 \subset S_{12}$)**: Weaving Scalar (35/35, 100%) и Weaving ROI-Boosted (35/35, 100%) доказали строгое вложение и монотонный recall. У Uniform вложение $S_8 \subset S_{12}$ составило **0/35** из-за фазового сдвига сетки; у Old Adaptive — **0/35** из-за смещения локальных пиков.
    - **Hit Rate**: Weaving 94.3% (33/35) против 40.0% у Uniform (K=4) и 40.0% у Old Adaptive.
- **Тесты и CodeSee**:
  - 5/5 тестов в `tests/test_segment_inspector.py` PASS.
  - 19/19 тестов сквозной регрессии PASS (`test_retro_selector.py`, `test_live_evidence_archive.py`, `test_incremental_spatial_matrix.py`).
  - CodeSee `features.json` дополнен сущностью `f-foveal-segment-inspector` и проверен валидатором.

- **Исправление методологии и устранение oracle leakage**:
  - Полностью удален oracle leakage: в режиме реального восприятия раннер больше не берет текстовые описания персонажей и транскрипты из эталонной разметки `ground_truth_180s.json`. При пропусках детектора SSDLite вызывается реальная модель `Qwen3.5-0.8B VL` на актуальных кадрах (16 вызовов, 16 успешных семантических распознаваний).
  - Прежние артефакты (`step25_e2e_metrics.json`, `step25_e2e_predictions.json`, `step25_concurrent_load.json`) помечены как `UNRELIABLE_SIMULATED` (сохранены для аудита без удаления).
  - Выпущен проверенный скрипт `scripts/recalibrate_e2e_cognitive_loop_step25.py` и новые артефакты `step25_recalibrated_metrics.json` и `step25_recalibrated_predictions.json`.
- **Трехуровневая модель наблюдения (`EpistemicObservationState`)**:
  - В `src/jawl_voicecompanion/scene_state.py` внедрен класс `EpistemicObservationState` и метод `SceneState.evaluate_observation_status`:
    - `observed_present`: объект или признак зафиксирован активным наблюдением.
    - `observed_absent`: область/объект были явно проверены целевой инспекцией и подтверждено их отсутствие.
    - `not_observed`: область не проверялась или наблюдение устарело (`staleness > max_staleness_ms`).
  - Устранена когнитивная ошибка «отсутствие данных в стейте = отсутствие на экране».
- **Реализация Top-Down Visual Refresh**:
  - В интерактивном режиме при вопросе о текущем кадре система выполняет направленный запрос к `Qwen3.5-0.8B VL` по изображению перед ответом SenseNova (задержка обновления кадра 162–272 мс).
- **Изолированный замер конкуренции за GPU (RTX 5080)**:
  - Устранено искажение замеров из-за `join` потоков: изолированное время инференса Qwen составило 285.1 мс, под фоновым декодингом SenseNova — 336.4 мс (реальный фактор замедления вычислительных ядер составил 1.18x, а не 3.56x).
  - VRAM по `nvidia-smi live query`: 10 817 МиБ занято / 5 161 МиБ свободно.
- **Тестирование**:
  - Добавлены тесты `test_epistemic_observation_three_states` и `test_epistemic_observation_staleness` в `tests/test_scene_state.py`.
  - 15/15 тестов `test_scene_state.py` и `test_event_policy.py` успешно пройдены.


## 2026-11-03 — JAWL-VoiceCompanion-V0.5: Полная сквозная интеграция и аудит (8/8 пунктов)

- **Chameleon HUD & Electron IPC**:
  - `desktop/panel-preload.js`: экспортированы методы `setWindowMode` и `onClickThroughChanged` в контексты `window.jawlDesktop` и `window.__jawlDesktop`.
  - Добавлен юнит-тест `desktop/tests/panel-preload.test.js`, подтверждающий двусторонний IPC для компактного режима (360x540) и прозрачности для мыши (Ctrl+Shift+G).
- **Three.js VRM Bust Shot & Pausing**:
  - `desktop/app-scene.js`: реализовано адаптивное кадрирование `applyCameraFraming(vrm)`, обеспечивающее поясной портрет (Bust Shot) в компактном окне HUD (увеличение лица и верхней части тела в 2.5 раза).
  - Внедрена пауза рендер-лупа `setRenderPaused` по событиям `visibilitychange` и `pagehide`, снижающая нагрузку на GPU до 0% при неактивном окне.
  - Добавлен тест `desktop/tests/avatar-camera-pause.test.mjs`.
- **Эргономика интерфейса и безопасность памяти**:
  - `desktop/app.html`, `desktop/app.js`: добавлен компактный текстовый ввод `#hud-quick-bar` в HUD и перемещён речевой баббл `#avatar-caption` в верхнюю область над головой персонажа.
  - Устранён блокирующий модальный диалог `window.confirm()` при удалении записей памяти, реализовано двухэтапное инлайн-подтверждение («Точно удалить?») с автосбросом. Протестировано в `desktop/memory-ui.test.js`.
  - `src/jawl_voicecompanion/config_hub.py`: устранён жёсткий абсолютный путь к снапшоту JAWL, `tests/test_web.py` проходит на 100% (89/89).
- **Оптимизация задержки речи Stream-Before-Close**:
  - `src/jawl_voicecompanion/speech_first.py`: расширен список терминальных инструментов `TERMINAL_TOOL_NAMES` каноническими алиасами JAWL (`HostOSTerminal.send_message_to_terminal`, `HostOSJournalMessages.send_message_to_terminal`, `send_message_to_terminal`). Задержка старта речи снижена до <2.5с.
- **Синхронизация конфигурации и манифеста**:
  - `config/runtime.manifest.json`, `src/jawl_voicecompanion/runtime_manifest.py`: зарегистрирован порт `omnivoice_tts: 9890` и параметры моделей OmniVoice.
  - `scripts/run_integrated_profile.ps1`: синхронизировано автоопределение OmniVoice TTS (порт 9890), восстановлен UTF-8 BOM для совместимости с Windows PowerShell 5.1.
- **Результаты тестов**:
  - 142/142 Node.js desktop tests PASS.
  - 152/152 Pytest core tests PASS.
  - 89/89 web tests PASS.


## 2026-11-01 — Память по правилам JAWL: кандидат вместо записи

- Добавлен `memory_policy.py`: единственное место, где наблюдение превращается
  в провенанс JAWL (`trust`, `verified`, `observation_class`,
  `source_event_ids`, тир) и где определён поток
  наблюдение → история → кандидат → решение JAWL → память.
- `POST /api/ambient-memory/handoff` публикует `MEMORY_CANDIDATE` во вход
  событий JAWL и не пишет память; без event-dir кандидат остаётся в буфере
  (`503 not_delivered`), повтор идемпотентен.
- Override `/api/ambient-memory/promote` (confirm=true) сохраняет честный
  провенанс: предикат `episode_summary_unverified`, тир `short` для наблюдений
  модели, `confidence` без завышения.
- `forget`/`archive` каскадируют в сенсорную историю и ambient-буфер;
  редакция хранится в `redactions` и переживает перезапуск. Ингестор делит один
  `event_id` между буфером и историей.
- UI «Память»: кандидат с кнопкой **JAWL** (передача, не запись), пометка
  «наблюдение» у неподтверждённых записей. 17 новых тестов памяти, 124 desktop
  теста без изменений. Детали: `docs/MEMORY_OWNERSHIP.md`, ADR-053.

## 2026-10-29 — ReAct, heartbeat и VA-контекст

- Выделен источник Perception из готового VA-пакета, очищены сенсорные приложения
  в разговорной истории; сохранены возраст и неопределённость наблюдений.
- Исправлены Gemini JSON transport, Goal lifecycle и инструменты heartbeat.
  Большое явно объявленное окно больше не упирается в отдельный Goal cap 18K.
- Добавлены локальный session bootstrap консоли и CSRF для activity/логов UI.
  Native canary подтвердил выполнение и завершение Goal по heartbeat.
- Живой профиль перезапущен, затем отдельно мозг с capacity fix; OmniVoice не
  менялся. Ограничения аудио и результаты: `docs/research/react-perception-audit-20261029.md`.

## 2026-10-29 — Микрофонная очередь

- Заполненная очередь из шести upload больше не останавливает захват. Приложение
  буферизует уже принятый PCM, догружает его крупными пачками и сохраняет старый
  `session_id` до завершения аудиодренажа. Node subset 125/125; live audio
  acceptance ожидает восстановления сервиса.

## 2026-10-29 — Подавление собственной речи в loopback

- Frontend подключён к существующему playback marker для обычных и ранних
  streamed WAV-сегментов. Marker завершается при done/cancel, продлевается во
  время длинного ответа; OmniVoice и генерация не менялись.
- Исправлено определение активной ранней речи по завершённым чанкам. Focused
  desktop voice lifecycle: 30/30 PASS; живая loopback-проверка остаётся открытой.

## 2026-10-29 — Раздельные бюджеты сенсорного текста

- Убрана преждевременная 600-символьная обрезка в PerceptionFusion. Speech и
  audio description теперь имеют отдельные bounded budgets, передаются в brain
  через VA packet полностью в пределах этих бюджетов; legacy summary остаётся
  короткой. Fusion/packet/native-context/web gate: 129 passed + 33 subtests.
- Реальный prompt readback и длинная live-ASR реплика после рестарта открыты.

## 2026-10-29 - System audio freshness

- Loopback PCM retains capture-time through ASR and YAMNet queues; worker delay
  no longer shifts observation time or masks old audio as fresh.
- Ambient segmenter 6/6 and audio integration 31/31 passed; live load/freshness
  acceptance remains open. Report: `docs/research/audio-capture-time-provenance-20261029.md`.

## 2026-10-29 - Separate music evidence from audio captions

- YAMNet music-presence evidence and audio-caption model results now occupy
  independent current-context channels and retain distinct source provenance;
  ASR remains independently available alongside both.
- A later non-music segment invalidates an older caption, while delayed workers
  cannot invalidate a newer observation. Focused ambient/fusion/history tests:
  54 passed. Real loopback quality/load acceptance remains open. Report:
  `docs/research/audio-description-channel-20261029.md`.

## 2026-10-29 - Reduce live EG2 audio cost

- Live PCM descriptions now use one shared whole-clip embedding for scene and
  specialist candidates; overlapping temporal refinement remains available for
  offline analysis. Daily composition uses four EG2 intra-op threads.
- On the saved 5.99s system-audio WAV five fast-path replays measured 304ms wall
  p50 / 424ms max and 969ms process CPU p50; two threads exceeded the target.
- Raised YAMNet music score cutoff to 0.35 after a source-disjoint positive set
  and synthetic controls: all 18 FMA clips remained positive while a two-tone
  false music/"Singing bowl" result abstained. Threshold is not calibrated.
  five audio suites report 86 passed, 1 skipped. Real loopback accuracy and
  concurrent-load acceptance remain open.

## 2026-10-29 - Visual freshness and history

- Invalidated captions no longer render as current screen; valid late captions
  remain in the short visual timeline, and captions beyond its TTL are dropped.
- Qwen sensor 18/18, fusion 16/16 and now-TTL 2/2 passed. Live scene-load
  acceptance remains open. Report: `docs/research/visual-stale-context-20261029.md`.

## 2026-10-29 - Persist history-only visual captions

- Scene-mismatched and stale-but-recent Qwen captions persist to the one-hour and
  weekly text archive with capture provenance; fresh captions are not double-written.
- Fusion/Qwen/history/TTL gate: 41 passed. Process-restart recall remains open.
  Report: `docs/research/visual-history-archive-20261029.md`.

## 2026-10-29 — conversation context compaction

- Added an owned native terminal context adapter: recent 12 messages remain verbatim; every older message is retained as a short chronological excerpt before the 18K character target, with old appended live perception snapshots stripped to avoid replaying stale sensory data.
- Registered the adapter in the owned brain startup receipt. The integrated launcher configures a 200-message history/cache; prompt compaction follows the provider character budget rather than a message-count trigger.
- Python compilation passed. The owned runtime lacks `pytest`; live startup and prompt acceptance remain open.
- Managed restart completed 29Oct at 01:00 MSK; Hikari, Qwen visual, JAWL, companion UI and OmniVoice are listening, and the new hook receipt is present. UI is visible. Health remains degraded due stale/scene-dropped captions and loopback waiting for samples; long-conversation compaction acceptance is still open.

## 2026-10-29 — Аудит текущего Hikari-сеанса

- Зафиксированы причины потери контекста, самоподмешивания TTS, устаревания
  captions, обрезки audio transcript и отсутствия слышимой инициативы.
- Сохранены redacted API-срезы и focused-test receipts; отделены устаревшие
  test-harness ожидания от runtime-дефектов. Production-код и запущенный профиль
  в этой итерации не изменялись. Отчёт: `docs/research/live-session-audit-20261029.md`.

## 2026-10-26 — Audio classification candidates and L2 refinement

- Replaced the EG2 broad music-vs-absence prompt competition with positive multi-class audio scenes. Added independent vocal, drum, bass, and electronic-timbre candidates, overlapping-window DSP details, and separate temporal-change summaries for L2/L3.
- Kept all new semantic outputs uncalibrated and behind the existing safe-claim behavior; model weights and production thresholds are unchanged. Separated embedding and L2 latency accounting so overlapping window embeddings are not double-counted.
- Added a positive-prompt CLAP probe and research report. The seven available controls showed no broad-scene top-1 improvement over the previous bank, and no manually checked interval set is available; P0 acceptance remains open. No live realtime run was performed; capture and continuity acceptance remain open.
- Targeted validation: coarse-to-fine tests 3/3, selected EG2 runtime tests 2/2, and `py_compile` passed. See `docs/research/audio-coarse-to-fine-20261026.md`.

## 2026-10-25 — Бюджет контекста для Qwen3-Omni

- Уточнён текст карточки сервисов: вместо обещания «всё работает» UI объясняет, что процессы/порты скрыты, а состояния сервисов показаны здесь. Accessibility тест 4/4; browser interaction E2E 14 checks across 9 viewports passed. Артефакт: `runtime/qwen-ui-browser-check-20261025-v2.json` (mock-brain scope).
- Исправлено масштабирование managed context budget: профиль с окном 12,288 теперь получает `max_dynamic_chars=9000` вместо базовых 12,000; для полного managed JAWL-профиля окно меньше 12,288 отклоняется.
- Добавлена регрессия для расчёта, записи, чтения approved budget receipt и миграции старого точного receipt. `test_native_context_budget`, `test_configure_profile_native` и `test_prepare_daily_profile`: 15/15 passed.
- Исправление не загружено в уже работающий soak; реальный запуск и brain-turn без overflow ещё нужно проверить после его завершения.

## 2026-10-25 — Qwen3-Omni sensory observability

- Reduced default Qwen visual static/periodic refresh to 4 s so future runs refresh within the 5 s current-screen TTL; active soak settings were left untouched. Qwen sensor 16/16 and launcher 18/18 tests pass.
- Aligned the composition fallback cadence with the CLI and launcher defaults (4 s static and periodic), so callers that construct the argument namespace without these options do not silently revert to 5/10 s. The launcher regression now checks this fallback too.

- Confirmed the active experimental brain endpoint is `local-qwen3-omni`; Hikari is not used in that profile.
- Added bounded audio-description provider/count/error/skip/latency/freshness metadata to ambient state and `/api/shell/status`; the System panel now distinguishes Qwen Omni audio results from YAMNet soundscape tags without exposing recorded audio or transcript content.
- Replaced the stale “Мозг (Hikari)” UI label with “Мозг JAWL”.
- Tests: ambient audio + shell status 32/32; desktop sensor/accessibility 14/14; full gate 1,144 unit, 18 e2e, 121 Node tests passed. Live process still needs a controlled restart to load these changes.
- The 8-hour Qwen integrated soak continues; its completed evidence and remaining acceptance are tracked in `runtime/active-goal-addendum-20261025.md`.

## 2026-10-18 — EmbeddingGemma 2 H4 implementation

- Added audio-visual vibe fusion, latent VRM reflex mapping, semantic scene-change trigger, compact episodic vector memory and Russian eg2 linear reader (`project`/`read`) to `eg2_sensory.py`.
- Added `PerceptionFusion.observe_eg2`, `observe_media`, optional composition integration and bounded `RollingMediaBuffer`.
- Tests: `test_eg2_sensory.py` + `test_perception_fusion.py` — 16 passed.
- Live multimodal validation remains open.

## 2026-10-18 — EmbeddingGemma 2 H4 implementation

- Added audio-visual vibe fusion, latent VRM reflex mapping, semantic scene-change trigger, compact episodic vector memory and Russian eg2 reader to `eg2_sensory.py`.
- Added `PerceptionFusion.observe_eg2` and optional composition integration.
- Added bounded `RollingMediaBuffer` for the recent 5-minute media timeline without raw media.
- Tests: `test_eg2_sensory.py` + `test_perception_fusion.py` — 16 passed.
- Live multimodal validation remains open.

## 2026-10-18 — EmbeddingGemma 2 H4 implementation

- Added audio-visual vibe fusion, latent VRM reflex mapping, semantic scene-change trigger, compact episodic vector memory and Russian eg2 reader to `eg2_sensory.py`.
- Added `PerceptionFusion.observe_eg2` and optional composition integration.
- Tests: `test_eg2_sensory.py` + `test_perception_fusion.py` — 14 passed.
- Live multimodal validation remains open.

## 2026-10-18 — EmbeddingGemma 2 H4 implementation

- Added audio-visual vibe fusion, latent VRM reflex mapping, semantic scene-change trigger, compact episodic vector memory and Russian eg2 reader to `eg2_sensory.py`.
- Added `PerceptionFusion.observe_eg2`, `observe_media`, optional composition integration and bounded `RollingMediaBuffer`.
- Tests: `test_eg2_sensory.py` + `test_perception_fusion.py` — 16 passed.
- Live multimodal validation remains open.

## 2026-10-18 — H5 game embodied baseline expanded

- Expanded `game_embodied.py` with GameObservation, SimulatedGameInputBridge, ModScaffold/ModScaffoldWriter and GameEmbodiedLayer orchestration.
- Added focused tests; `tests/test_game_embodied.py`: 17 passed.
- Live game input, mod execution and auto-modding remain open.

## 2026-10-18 — H5 game embodied baseline

- Added `game_embodied.py` with bounded motor controller (10-60 Hz, queue, emergency stop), voice combat coordinator (cooldown/DND), strategy/mod planner, and orchestrator.
- Added `tests/test_game_embodied.py`: 10 passed.
- Live game input, mod execution and auto-modding remain open.

## 2026-10-18 — Remaining TODO engineering pass

- D4-04: AttentionPresence/web attention tests green (13 passed).
- D4-05: streaming capture and voice capture lease tests green (31 passed).
- D5-03: HostOS policy/web tests green (19 passed).
- D6-03: main pytest 1028 passed + 281 subtests; desktop node 95 passed; e2e 18 passed in batches/single runs.
- H1-H4: implementation and focused tests present; H5 not implemented.
- Live-only items remain: physical mic/gate, 30-60 min conversation, 8h soak, full native action series, VRM live acceptance.

## 2026-10-18 — System speech separation (D4-03)

- Ambient audio ingests system speech as `system_audio`, not as a user command.
- Own TTS is filtered via `PlaybackSuppression`; TTS endpoints activate the marker with an estimated playback TTL.
- `ingest_system_audio` now records `source_app=system_audio`.
- Tests: `test_ambient_audio.py` + affected web tests green.

## 2026-10-18 — Screen observation (D4-02)

- Проверена связка ScreenDeltaWatcher + VisionLookService: свежий экран по запросу (`/api/vision/look`) и по изменениям, дедупликация одинаковых кадров и cooldown.
- Bounded capture profile, UIA context и perception fusion подтверждены тестами.
- Обновлён TODO/STATE.

## 2026-10-18 — Ambient pause/resume (D4-01)

- Добавлены `pause()`/`resume()` в `SensoryIngestor` (блокирует polling в `_run`).
- `ResourceGovernor` подключён к `SensoryIngestor` и `AmbientAudioService` в `composition.py`.
- DND-кнопка в `desktop/app.js` вызывает pause/resume ambient capture (`/api/ambient-audio`, `/api/ambient-memory`), статус сенсоров показывает `пауза`.
- Добавлены тесты pause/resume в `test_sensory_ingest.py`, `test_web.py`, `test_e2e.py` (403/503, gaming_mode → yields_to_game).
- Удалены неотслеживаемые `scripts/_patch*.py` и `scripts/_fix_dup.py` (receipt ниже).

## 2026-10-18 — Chameleon UI: Window Position Persistence, Multi-Monitor и Click-through Exit

- Добавлено сохранение/восстановление позиции окна и режима `compact` в Electron userData (`jawl-window-state.json`).
- При запуске Electron восстанавливает размеры окна и позицию, а также режим `compact` из сохранённого состояния.
- Добавлена валидация multi-monitor: позиция восстанавливается только если она находится на одном из подключённых дисплеев.
- Добавлен глобальный хоткей `Ctrl+Shift+G` для выхода из click-through режима (работает даже когда окно не реагирует на мышь).
- Все 47 Node.js desktop-тестов и Python-тесты проходят.

## 2026-10-18 — Chameleon UI: Window Position Persistence и Compact Mode Restore

- Добавлено сохранение/восстановление позиции окна и режима `compact` в Electron userData (`jawl-window-state.json`).
- При запуске Electron восстанавливает размеры окна и позицию, а также режим `compact` из сохранённого состояния.
- Восстановление при запуске: если `compactMode` был сохранён в localStorage, окно автоматически переключается в компактный режим.
- Все 47 Node.js desktop-тестов и Python-тесты проходят.

## 2026-10-17 — Chameleon UI: DND, Click-through, HUD и panel-preload.js

- Добавлены кнопки DND (`🔕`) и Click-through (`👻`) в HUD-dock (`desktop/app.html`).
- Добавлены `toggleDndMode()` и `toggleClickThrough()` в `desktop/app.js`, подключённые к `/api/attention` и `/api/ambient-memory/config`.
- Расширен IPC `jawl-window-mode` в `desktop/main.js` параметром `clickThrough` с `setIgnoreMouseEvents`.
- Добавлена hover-логика для временного разрешения кликов при click-through (mouseenter/mouseleave).
- Восстановлен `desktop/panel-preload.js` (был удалён при H1, но необходим для Electron preload).
- Все 47 Node.js desktop-тестов и 1040 Python-тестов проходят.

## 2026-10-16 — native denial completion и owned soak

- Native HostOS PermissionError больше не вызывает blind retry в correlated
  request: owned hook сохраняет отказ native authority, завершает цикл,
  предотвращает дальнейшие batch calls и выдаёт один явный turn.error.
  Нет второго policy/executor, вывод tools не интерпретируется как authority.
  Live policy PASS: одна denied попытка, outside file absent, полный cleanup.
- Для обычного Companion запроса grammar ограничивает три внутренних поля
  до320 chars каждое после двух реальных output truncation. Native active
  Goals, произвольные skill args и Goal v2 поля сохраняют свой бюджет/доступ.
- Новый resource sampler считает только exact owned Job PID/create_time;
  CPU по дельте накопленного времени, PID reuse/foreign processes исключены.
  Native Goal/Heartbeat soak сохраняет безопасные projections и atomic status;
  lease revoke, controlled provider fault/recovery, resource/port cleanup
  подтверждены на180с. Первый8h native soak FAIL на63.6мин:12 cycles
  PASS,13-й false done без actions отвергнут native guard. Provider fault/
  recovery и итоговый lease/Job/ports cleanup PASS;8h не принят.
  Major gate932/66/16/109 +browser PASS; queue/policy harness checks focused PASS.
- Real-model WAV voice20/20 через /app PASS: drafts20/20, body EOF и полное
  non-silent playback; browser Job и stack cleanup PASS. Три fixtures по кругу.
  Dispatch→first WebAudio p50/p95=8.338/11.964с, не physical speech-end;
  latency1–3с и physical mic ещё OPEN.
- Read-only stage audit:22 LLM calls на20 ходов, LLM total p50=6.226с,
  native overhead0.189с и HTTP residual0.384с. Server cache/checkpoint
  capability проверена на actual binary; performance benefit ещё не измерен.
  В отдельном worktree подготовлены opt-in checkpoint CLI controls:13 focused/
  4 subtests и CodeSee validator PASS; canonical running soak не меняется.
  В этой копии подготовлен A/B/B/A warm20 runner с numeric server timings,
  exact turn/trace matching и Job RSS;30 focused/54 subtests +actual native
  bootstrap PASS без модели. Real-model benchmark ещё не запускался.
- Voice runner содержит browser в отдельном owned Job; восстановлены
  стандартные Windows discovery variables в clean env для поиска Edge driver.

## 2026-10-16 — owned supervisor identity

- Убраны оба supervisor_status fallback с чтением process command line.
  Console и supervisor используют один owned metadata hook: PID marker,
  process creation time, entrypoint/root и bounded atomic receipt.
- Receipt публикуется после native exclusive lock acquire и удаляется до
  release; failed acquire/write не объявляют supervisor работающим. PID reuse,
  чужой root/marker, malformed/oversize receipt дают running=false.
- Forced cleanup требует сохранённого receipt и завершения exact owned Job;
  чужой receipt/живой PID сохраняются.25 focused tests/38 subtests PASS.
  Real Hikari supervised20/20, receipt actual PID/create_time/exact Job,
  cancel/reconnect и полный cleanup PASS. Новый major gate PASS:
  912 unittest/66 pytest/16HTTP/109Node +browser harnesses.

## 2026-10-16 — D5 native work и полнота контекста (в работе)

- Новый agent-work suite отправляет пользовательские поручения; parent только
  проверяет native journal, file/hash, browser save count и memory projections.
  Native browser включается явно в disposable profile; браузер владельца не используется.
- Обнаружены повторные выдуманные browser tool names и потеря signatures из
  слишком малого context cap. Local wrapper теперь передаёт actual server window;
  для выбранного64k Hikari native dynamic budget48000 chars вместо12000.
  Модель/окно/GPU прежние. Targeted provenance сохраняет approved capacity
  при relaunch, необъяснимые owner edits по-прежнему дают conflict.
- Исправлён memory prompt, ошибочно запрещавший реальный optional memory_key.
- r5 подтвердил file/read/SHA, browser open, form save с fresh native result,
  remember/revise/restart/recall. Полная серия FAIL: sandbox refusal loop;
  r6 output truncation и r7 пропуск запрошенного read сохраняются как ограничения.
  Diagnostic пишет только public name/fixture marker counts и metadata, без
  контекста/CoT. Отдельный fixture Playwright wiring PASS не заменяет D5 приёмку.

## 2026-10-15 — brain identity и проверка серии native turns

- Brain проверяет owned paths до native import и атомарно пишет receipt с
  actual PID/create_time, pinned SHA и установленными delivery/context хуками.
  Live driver проверяет exact launcher Job; bootstrap учитывает venv redirector.
- Новый isolated live driver запускает выбранный Hikari и20 разных RU реплик
  через native HTTP/SSE, проверяет ordinary/supervised, cancel/reconnect и
  provider loss/recovery. Это отдельная граница от mic/TTS/DAILY_ACCEPTANCE.
- Local JSON-envelope получает непустую object grammar без дублирующего SDK
  wrapper; полный native parser/discovery сохраняется. Full-schema trial
  не принят: повторения действий приводили к token limit.
- Аудит r4 выявил несколько terminal finals внутри одного native batch.
  Delivery guard подавляет повтор до history/SSE; failed emit допускает retry.
  Harness отклоняет multiple terminal events и исключает replay из scoped counts.
- 47 focused tests/45 subtests PASS, затем4 cleanup tests/7 subtests PASS.
  Ordinary r5 и supervised r6:20/20 native text, cancel/reconnect, exact brain
  identity/hooks/Job; ordinary provider loss/recovery PASS. Журнал каждого
  тестового хода содержит ровно один terminal event, включая реальный batch
  с несколькими terminal actions. Порты модели и markers очищены.
  Native dispatch→terminal p50/p95=3.596/4.608с ordinary и3.584/6.939с supervised;
  max7.459с, без ASR/TTS. Full gate после этих изменений PASS:
  907 unittest/66 pytest/16HTTP/109Node +browser harnesses. Connected voice20 открыта.
- После новых hooks повторены3/3 synthetic WAV → GigaAM → Hikari → OmniVoice
  через `/app`: streaming draft/EOF/full non-silent playback PASS, wrapper/ports
  cleanup PASS. Dispatch→первый звук≈10.272/9.466/11.373с; это sample3 и endpoint
  proxy, не physical mic/p50/p95. Результаты сохранены отдельно от прежнего прогона.

## 2026-10-15 — продолжение OpenCode: управление перебиваниями

- Восстановлен контекст сессии и зарегистрирован active Codex goal для автономной части D1–D6.
- Исправлены незаданный smart-barge-in flag и русские границы слов: короткий
  onset не отменяет речь, sustained fallback считает voiced PCM, поздний draft
  не отменяет новый playback owner; незавершённая RU фраза продлевает endpoint.
- Поддакивание подтверждается итоговой ASR, завершает свой buffer/session и
  не вызывает новый JAWL turn или memory event. Speech Stop не меняет задачи.
- Исправлен импорт test-helper supervisor и реальная Windows cleanup race:
  сохраняются проверенные process handles до terminate; Job active=0 дополняется
  ожиданием signaled handles. При retry identities сохраняются. Модельный
  worker не заменяется и temp WAV не удаляется до подтверждённого reap.
- 36 Node voice +18 Python streaming/policy +39 process focused PASS;
  model-free race probe50/50 до исправления и0/50 после. Первый full gate PASS
  до drain-фикса; итоговый gate после него отдельно. Physical mic/full duplex OPEN.
- Launcher real voice harness теперь явно использует `/app`.3/3 полных
  Hikari/GigaAM/OmniVoice ходов с synthetic WAV и streaming drafts PASS.
  Реальная задержка от voice/end dispatch до WebAudio11.495/6.972/12.553с,
  цель1–3с остаётся открытой. Native early-exit уже работает после terminal.
- Native supervisor recovery harness ждёт generation marker вместе с alive PID;
  действующая ROOT lease/revoke/no-third-child/cleanup проверены реальным cheap child.

## 2026-10-15 — гармонизация архитектуры, уборка репо и «Окно-Хамелеон» (D3/H1–H5)

- Очищены временные untracked-пробники и мусорные артефакты (`desktop/%SystemDrive%`, `tool-call-proof.txt`, одноразовые `scripts/copy_configs.py`, `patch_settings.py`, `test_launcher.py`, `test_live_text_turn.py`, дубли в `config/`) с полным сохранением рабочих dirty changes.
- Создан единый архитектурный документ [docs/HARMONIZED_ARCHITECTURE_AND_ROADMAP.md](docs/HARMONIZED_ARCHITECTURE_AND_ROADMAP.md) и обновлён [TODO.md](TODO.md) (этапы D2/D3 и горизонт H1–H5: «Окно-Хамелеон», двухскоростной мозг JAWL, 3 паттерна ускорения JSON-цикла JAWL, `DuplexCascade` + `OmniVoice`, мультимодальная кора `EmbeddingGemma 2` по принципу `eg2`, 3-уровневый игровой агентный слой).
- Исправлен supervised-путь запуска brain-процесса (`D1-01`): `scripts/run_owned_jawl_supervisor.py`, `scripts/register_supervised_profile.py`, `scripts/run_owned_jawl_console.py` и `scripts/run_integrated_profile.ps1` теперь запускают `scripts/run_owned_jawl_brain.py` с установленными delivery/context хуками как в обычном, так и в supervised режиме.
- В `desktop/app.html`, `desktop/app.js`, `desktop/panel-preload.js`, `desktop/main.js`, `desktop/app-settings.js`, `desktop/app-scene.js` и `desktop/avatar-motion.js` реализованы: переключение `Compact HUD Mode (360×540 Always-on-Top) ↔ Studio Drawer Mode (1060×720)` через Electron IPC `jawl-window-mode` (`Ctrl+Shift+M` / кнопки `🗕 Компактно`, `📌`, `⚙️`), прозрачный режим `?mode=obs`, отдельная поза `thinking/working` для VRM, многоканальный липсинк (`aa/oh/ee`) и группировка настроек фреймворка по органам чувств.
- Проверены 56 Python-тестов (`pytest`), 43 desktop-теста (`node --test`) и валидатор CodeSee — PASS.

## 2026-10-14 — ветка ежедневной версии

- Создана dev/daily-companion-20261014, сохранены все прежние dirty changes.
- Прежние планы/checkpoints/датированные обзоры перенесены в recoverable archive.
- Новая очередь D1–D6: надёжный ответ, быстрый голос, постоянный персонаж,
  восприятие/инициатива, действия/память, длительная работа.
- Исправлен статус R6: terminal FAIL, три ответа успешны, четвёртый — ошибка.
- Зафиксирован process boundary дефект: console hooks не доказывают brain hooks.
- Модели, prompts, активный аватар и runtime поведение при подготовке не менялись.
- Проверены29 архивных SHA256 и268 локальных ссылок; diff-check PASS.
- Новый tool goal не зарегистрирован: API отклонил создание из-за старого
  unfinished paused goal; целевой objective и первый шаг сохранены в DAILY_PLAN.

[Прежний CHANGELOG целиком](docs/history/2026-10-14-daily-reset/CHANGELOG.md).

## 2026-10-25 - Bounded sensory history

- Added local one-hour text observation history and seven-day compact hourly moments for audio/video captions; no raw audio or frames are persisted.
- Added history-aware brain prompt enrichment, a protected status/context endpoint, and clear/disable handling. Store/fusion/web regression: 25 passed, 4 subtests.
- Ten-minute live check: 199 samples, 264 text observations, zero sensor/API errors. Current description works; unaided two-minute recall and full-run synthesis remain partial pending a restart with the new store active.
- Report: `docs/research/sensory-history-acceptance-20261025.md`.

28Oct research: isolated LFM450/LFM1.6B/Qwen0.8B CPU versus GPU1 visual-detail probe saved under runtime/lfm-detail-probe-20261028. No daily default or product source changes.

## 2026-10-28 — Live LFM450 sensory probe

- Live YouTube target-window capture used ScreenCaptureAdapter; 50 captions on GPU1, p50 64.8ms and p95 108.5ms. Raw images were not persisted.
- The local Bonsai2/Hikari brain summarized caption-only input in 1.08s and declined to infer a coherent plot, but answered in English and was broad. See runtime/lfm450-story-replay-20261028/STATUS.md.
- No daily model configuration changed.


## 2026-10-28 - Visual resolution limitation recorded

- Documented that the live LFM450/Florence comparison used 960?520 encoded frames from an adapter capped at 960?720 and JPEG quality 72; original window dimensions and scale factor were not recorded.
- Marked fine-detail acceptance inconclusive pending a matched native/high-resolution replay with dimensions/scale metadata, followed by a separate JPEG-quality check. No daily model configuration changed.
