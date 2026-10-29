## 2026-10-29 — Qwen visual OCR handoff

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
# Изменения

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
