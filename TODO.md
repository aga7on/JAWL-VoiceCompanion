# Единственная очередь — ежедневный компаньон

16 октября 2026. Статусы: [ ] не принято, [~] частично, [x] подтверждено.
[План](docs/DAILY_PLAN.md) · [приёмка](docs/DAILY_ACCEPTANCE.md) · [факты](docs/STATE.md).
Старый полный TODO сохранён в архиве; отложенные требования — [BACKLOG](docs/BACKLOG.md).

## D0 — подготовка новой ветки

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
  focused tests и native text серией; connected voice error/20-turn ещё открыты.
  не озвучивать thoughts; harness прекращает ожидание TTS при terminal error.
  15Oct: native text final/error подтверждены; повтор terminal action внутри
  batch подавляется до history/SSE. Native provider loss даёт один turn.error,
  восстановление — один ответ; connected voice error/20-turn приёмка открыта.
- [~] D1-03: серия text/voice с текущими моделями без исчезновения ответа,
  reconnect/error/retry без двойной доставки и слепого повтора действий.
  15Oct:3/3 real-model WAV→/app→JAWL→OmniVoice хода завершены полностью;
  streaming draft3/3, каждый response body EOF, non-silent playback до конца.
  Native HTTP/SSE20/20 отдельно PASS в ordinary и supervised: exact turn_id,
  cancel/reconnect, нет двух terminal events одного хода. Ordinary provider
  loss/recovery PASS.16Oct ordinary connected WAV voice20/20 PASS: real ASR/
  brain/TTS и /app, drafts20/20, body EOF/full playback, exact Job/ports cleanup.
  Три фразы по кругу; physical mic и voice provider error/recovery OPEN.

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
- [~] D2-02: простой разговор без ненужных tool loops (`Single-Step Fast-Exit`
  в `ReactLoop`, если вызван только речевой ответ без `memory/hostos/terminal`);
  explicit goal сохраняет полноценный агентный арсенал/reasoning и краткие голосовые checkpoints.
  18Oct: native turn context добавляет fast hint только для conversational turns; native delivery guard подавляет лишний terminal completion; focused tests green. Live 20-turn plain-chat timing still open.
- [~] D2-03: физический mic/gate/тихая речь, паузы2–3слова/с; не режет начало/конец.
  18Oct: streaming capture tests 31 passed; voice capture lease tests green; physical mic/gate/live acceptance remains.
- [~] D2-04: надёжный Stop/перезапуск речи/нет stale audio; разговор с наушниками
  первым, acoustic barge-in следующим. Full duplex не blocker первой версии.
  15Oct: исправлены выключенная ветка smart-barge-in и RU word boundaries.
  Поддакивание подтверждается canonical ASR без нового JAWL turn; паузы bounded,
  отмена привязана к playback owner. 36 Node +18 Python PASS; physical mic OPEN.
- [~] D2-05: при ошибке сохранять текст и понятное состояние; речь Stop не теряет goal.
  18Oct: native delivery guard emits bounded turn.error and preserves goal state; focused tests green. Live provider fault/restart acceptance still open.

## D3 — персонаж постоянно рядом («Окно-Хамелеон», можно параллельно D2)

- [x] D3-01: единое окно `desktop/app.html` в режиме «Хамелеон» (Compact HUD `360×540` поверх окон `Always-on-Top` ↔ выдвижная Studio Drawer `1060×720` с настройками всего фреймворка по клику на ⚙️ и IPC `jawl-window-mode`) реализовано и проверено unit-тестами. 17Oct: добавлены кнопки DND (`🔕`) и Click-through (`👻`) в HUD-dock, IPC `jawl-window-mode` расширен параметром `clickThrough` с `setIgnoreMouseEvents`; hover-логика для временного разрешения кликов при click-through. 18Oct: добавлено сохранение/восстановление позиции окна и режима `compact` в Electron userData; восстановление при запуске; multi-monitor валидация позиции при восстановлении; глобальный хоткей `Ctrl+Shift+G` для выхода из click-through.
- [x] D3-02: текст над головой из того же ответа, парящий мини-док (`🎙`, `⏹`, `👁`, `🔕`, `👻`, `📌`, `⚙️`) прямо под VRM без панели диагностики, сгруппированные по органам чувств настройки JAWL/VoiceMem/Companion в одном месте реализованы. 17Oct: кнопки DND и Click-through подключены к `/api/attention` и `/api/ambient-memory/config`; статус синхронизирован с сервером. 18Oct: восстановление позиции окна и режима compact при запуске.
- [~] D3-02: текст над головой из того же ответа, парящий мини-док (`🎙`, `⏹`, `👁`, `🔕`, `👻`, `📌`, `⚙️`) прямо под VRM без панели диагностики, сгруппированные по органам чувств настройки JAWL/VoiceMem/Companion в одном месте реализованы; остаётся live приёмка с реальным стеком. 17Oct: кнопки DND и Click-through подключены к `/api/attention` и `/api/ambient-memory/config`; статус синхронизирован с сервером.
- [~] D3-02: текст над головой из того же ответа, парящий мини-док (`🎙`, `⏹`, `👁`, `🔕`, `👻`, `📌`, `⚙️`) прямо под VRM без панели диагностики, сгруппированные по органам чувств настройки JAWL/VoiceMem/Companion в одном месте реализованы; остаётся live приёмка с реальным стеком. 17Oct: кнопки DND и Click-through подключены к `/api/attention` и `/api/ambient-memory/config`; статус синхронизирован с сервером.
- [x] D3-03: текущий VRM idle/listen/think/speak (включая читаемую позу `thinking/working` и обогащённый липсинк `aa/oh/ee`) связаны с одним turn; единое ядро `app-scene.js` (включая `?mode=obs`). Не делать новый арт условием запуска. 17Oct: добавлена поза `thinking/working` (upperChest lean + forearm/hand pose) в `avatar-motion.js` и `app-scene.js`; липсинк `aa/oh/ee` в `applyLipSync`.

## D4 — видеть, слышать и уместно проявлять инициативу

- [~] D4-01: screen/system-audio sources после настройки; bounded recent context,
  timestamps/TTL, ошибки и pause видны; фон уступает разговору/игре. 17Oct: ambient pause/resume (audio+memory+sensory ingest), DND button pauses ambient capture, paused state in sensor status, ResourceGovernor yields_to_game; tests green.
- [~] D4-02: JAWL получает свежий экран по запросу и изменениям; описывает
  реальные RU окна. Не отправлять каждый кадр без необходимости. 18Oct: VisionLookService dedup/cooldown, ScreenDeltaWatcher backoff, /api/vision/look, UIA context, perception fusion; tests vision/presence/screen_adapter/e2e зелёные.
- [~] D4-03: системная речь отделена от пользователя/собственной TTS,
  временная память с provenance; перезапуск/TTL/очистка. 18Oct: ambient audio ingests system_audio, playback suppression фильтрует own TTS, TTS endpoints активируют suppression с TTL, source_app=system_audio; tests ambient_audio/web зелёные.
- [~] D4-04: инициативный комментарий через общий Heartbeat/attention,
  cooldown/DND/приоритет пользователя, без двойного разговора. 18Oct: AttentionPresence tests 13 passed; web attention tests green; live initiative acceptance remains.
- [~] D4-05: совместное прослушивание: захват не ломает голос; metadata/речь
  можно использовать честно. Реальное описание музыки — отдельная capability
  из BACKLOG, без выдуманного «слышания» и без обещания пения. 18Oct: streaming capture tests 31 passed; voice capture lease tests green; live co-listening acceptance remains.

## D5 — полезный агент и непрерывная память

- [~] D5-01: три настоящих поручения в тестовых окнах/браузере/файлах:
  действие → проверка результата → короткий отчёт, с уровнями native policy.
  16Oct r5: file/read/SHA, browser open и form save PASS; fresh native result
  до terminal, один POST. Последний sandbox case FAIL из-за15 повторов;
  owned native-denial hook исправлен, отдельный live policy сценарий PASS.
  Полная серия ещё OPEN: r6 output truncation, r7 пропуск повторного чтения.
- [~] D5-02: факт → исправление → restart → recall меняет ответ той же личности;
  задачи переживают Stop речи и отказ провайдера без дубля эффекта.
  16Oct r5 real user turns: stable memory_key, revision1→2, новая brain generation,
  fresh SQLStructuredMemory.list_memories и ответ revised value PASS. Задачи
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
- [~] D6-02: разговор30–60мин, затем8h soak с потерей/возвратом worker,
  без бесконтрольного роста RAM/логов/очередей и без повторов действий.
  16Oct новый owned native soak: exact Job/creation identity sampler без cmdline/cwd,
  native Goal write/read, lease revoke, controlled provider fault/recovery и cleanup
  PASS на180с. Первый8h native soak FAIL на63.6мин:12 cycles PASS,13-й
  Goal объявил done без actions, native guard перевёл его в blocked.
  Controlled fault/recovery PASS; lease revoke/Jobs/ports cleanup PASS.
 8h не пройден; false-completion repair и новый прогон OPEN. Это не mic/audio soak.
- [~] D6-03: применимый major regression + DAILY_ACCEPTANCE, короткая инструкция
  владельцу и перечень известных ограничений. Это daily release, не весь production TODO. 18Oct: main pytest 1028 passed + 281 subtests; desktop node 95 passed; e2e 18 passed in batches/single runs; live DAILY_ACCEPTANCE items remain.
  16Oct новый full gate PASS:932 unittest/66 pytest/16HTTP/109Node +browser
  harnesses; queue projection checks отдельно12 focused PASS. Новый real-model WAV voice3/3 и native text20/20 обоих режимов PASS.
  DAILY_ACCEPTANCE mic/full actions/durable-task Stop/8h ещё не принята.
  Connected WAV voice20 и memory correction/restart/recall подтверждены. Исторический
  14Oct Argon heartbeat FAIL сохранён в runtime/supervised-profile-acceptance-20261014T174524Z.json.

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
  отказ от жёсткого VAD в пользу микро-ходов (`overlap_window ≈ 0.5–0.6 с`); управление очерёдностью речи через 6 спецтокенов (`<|user is talking|>`, `<|user is thinking|>`, `<|assistant_backchannel|>`, `<|user finish talking|>`, `<|user interruption|>`); мгновенный потоковый синтез микро-чанков в `OmniVoice` с клонированным голосом.
- [~] **H4 — Мультимодальная сенсорная кора на базе `EmbeddingGemma 2` (по принципу `eg2.haku.sh`):**
  18Oct: audio-visual vibe fusion, latent VRM reflex, semantic scene-change trigger, compact episodic vector memory, Russian eg2 reader, PerceptionFusion.observe_eg2 and optional composition integration; tests eg2/perception fusion 14 passed. Live multimodal validation remains.
  - *Zero-Decoder Visual Probe:* мгновенная классификация кадров экрана через матрицу концептов в RAM за ~15 мс (вызов тяжёлой VLM только для детального OCR);
  - *Audio-Visual Vibe Fusion:* одновременное понимание музыки, звуковых эффектов, интонации голоса и видеокадра при совместном просмотре фильмов/аниме (с соблюдением co-watching etiquette — реакция лицом во время диалогов, голос в паузах);
  - *Латентные рефлексы VRM:* прямая реакция эмоций/тела аватара на вектор экрана/звука за ~20 мс в обход LLM;
  - *Семантический детектор смены сцены* (`cos_sim` соседних кадров для пробуждения `Attention`/`Heartbeat`) и *компактная векторная эпизодическая память дня* (~10 МБ/час без raw video);
  - *Русский `eg2` reader:* линейный проектор аудио-слайсов в русские словоформы/токены для сверхбыстрого потокового ASR.
- [~] **H5 — Игровой моторно-тактический слой (Game Embodied Layer 10–60 Гц + Auto-Modding):**
  18Oct: expanded engineering baseline in `game_embodied.py`: motor controller, voice combat coordinator, strategy/mod planner, GameObservation, SimulatedGameInputBridge, ModScaffold/ModScaffoldWriter, GameEmbodiedLayer orchestration; tests 17 passed. Live game input, mod execution and auto-modding remain open.
