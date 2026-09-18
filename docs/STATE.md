# Состояние разработки

## Ночная сессия 3 — 2026-09-19 (goal round 2)

- **D4 ПОДТВЕРЖДЁН живьём**: turn, отправленный сразу после рестарта агента
  (stop → start → chat в течение 2 с), восстановился и получил ответ за
  **10.4 с** («На связи, Артём. Рестарт прошёл…») — раньше этот сценарий
  давал 120-секундный timeout. Fast-fail + ресабмит + anti-repeat исключение
  работают вместе.
- **Speaking-сигнал ПОДТВЕРЖДЁН живьём**: во время 5.6-секундного TTS-стрима
  поллер `/api/state` поймал `speaking=True, amplitude=0.6` (6 попаданий из
  100). Фикс «обновлять на каждом чанке» работает — липсинк-сигнал реально
  течёт в state и нативный клиент его читает. (Ранние hits=0 были гонкой:
  короткий стрим заканчивался до старта поллера.)
- **D1-реверс (продолжение)**: бинарный анализ 50 новых v5-секций (102–151)
  дал размеры, но не семантику (секции — смесь int-индексов и float-дельт без
  карты). Попытка через `moc2cmo` (decompile v5 → cmo3, 7.2 MB) доказала, что
  v5 полностью парсится, но cmo3 — проектный файл, не рантайм. Вывод: реализация
  blendshapes в Mocari = вендоринг 11k строк + реверс проприетарных секций —
  многодневная рискованная задача. `apply_art_mesh_blend_shape_delta` в Mocari
  — заглушка без парсера и без вызова.
- **Решение по mao_pro**: рот уже работает через WebView2/Cubism Core
  (браузерный runtime, `/avatar`); нативный pure-Rust путь — Hiyori (v3).
  Выбор между «вендорить+реверсить Mocari под v5» и «mao_pro только через
  WebView2» — за владельцем.
- **Допроверка экосистемы**: `moc2cmo` (единственный публичный Rust-парсер
  moc3 v5, тот же автор) имеет 0 упоминаний blend_shape — он декодирует v5 в
  cmo3-проект, но blendshape-деформацию не реализует ни один публичный
  Rust-инструмент. Реверс 50 секций вслепую = многодневная задача без ground
  truth; по правилам дисциплины (смена подхода вместо повторения) остановлен.
- Экспериментальная зависимость moc2cmo убрана из Cargo.toml; build зелёный.

## Ночная сессия 2 — 2026-09-19 00:10

- **D1-реверс продвинут**: дамп count-info moc3 v5 vs v3 показал 10 новых
  слов (w25=33, w26=124, w27=3, w28=31, w29=234, w30=7, w31=14, w32=1, w33=3,
  w34=0) и ~50 новых секций (102–151) у mao_pro, отсутствующих у Hiyori.
  Гипотеза: w26=124 ≈ blendshape-биндинги на ротовые параметры; w29=234 ≈
  blendshape-кейформы. Патч Mocari требует маппинга секций — задача открыта.
- **Avatar speaking-фикс**: set_avatar_audio теперь обновляется на КАЖДОМ
  TTS-чанке (раньше только на первом — snapshot устаревал за 0.75 с и флаг
  speaking был ненаблюдаем). Механизм проверен живьём: POST /api/avatar/audio
  → /api/state сразу отдаёт speaking=True, через 1 с (stale 0.75 с) — False.
  Коммит e9df481, тесты 67/67 web.
- **Live-проверка TTS→speaking не завершена**: стрим синтеза быстрый
  (387–782 мс), а поллеры в тестах не имели session-cookie (403 глушился
  try/catch). Нужен повторный замер с сессией в поллере после подъёма стека.
- **Стабильность стека**: релеи/лаунчеры, запущенные из agent-сессии, снимаются
  wrapper-cleanup; несколько циклов «stop-file → heartbeat timeout». Канонический
  путь — запуск из окна пользователя. Стек сейчас ОСТАНОВЛЕН.

## Прогресс Фазы D — 2026-09-18 (ночная сессия)

- **D1 — решено обходным путём, v5-blendshapes отложены**: Mocari не применяет
  blendshapes moc3 v5 (доказано сканом всех 128 параметров mao_pro: 0 вершин/
  0 opacity на рот; `apply_art_mesh_blend_shape_delta` существует, но не
  вызывается). Hiyori (moc3 v3, официальный free sample) работает полностью:
  ParamMouthOpenY двигает 171 вершину, diff рта в нижней трети лица. Дефолтная
  модель аватара — Hiyori (`JAWL_AVATAR_MODEL` переопределяет); mao_pro
  вернётся после патча Mocari или через WebView2/Cubism Core.
- **D2 — DONE**: эмоции через прямые параметры (EyeSmile/BrowAngle/BrowForm/
  Cheek — доказанно деформируют сетку) с фейдом ~250 мс. Headless: happy
  597 px, surprised 832 px, angry 512 px отличий от neutral, все в области
  лица (y 102–145).
- **D3 — DONE**: idle motion (MotionPlayer, looping) + apply_physics(dt) +
  apply_pose(dt) каждый кадр; процедурный sway/breath как фолбэк.
- **D4 — DONE**: turn-recovery в terminal gateway: generation-счётчик
  транспорта, быстрый fail при рестарте агента до первого события turn'а,
  один авторесабмит с новым turn id. Anti-repeat промпт: прямой
  пользовательский запрос требует ответа всегда (синхронизировано в
  config/jawl). Тесты 11/11 terminal, 78/78 web.
- **D5 — DONE**: OBS chroma-key `--obs` (#00FF00); headless-кадр: 87% keyable
  фона, персонаж 12.9% кадра.
- Остаток D1: вендорить Mocari и реализовать blendshape-секцию moc3 v5 для
  mao_pro (рот/щёки) — отдельная исследовательская задача.

## Прогресс Фазы A — 2026-09-17 (в работе)

- **A0 — DONE (live)**: браузерная приёмка настроек на живом профиле прошла
  (`scripts/run_settings_browser_acceptance.py` → PASS, `runtime/settings-browser-acceptance.json`).
  Исправлены два реальных дефекта: telegram-секция IFACE_SECTIONS (`keys:` →
  `fields:`) и timezone readback drift (строка → int).
- **A1 — DONE (live)**: episodic timeline TimeService (`episodic_timeline.py`),
  `/api/timeline`, подключён к chat/voice; live-verified — реальный chat-turn
  перерезал idle → conversation. Тесты 8/8, web 67/67.
- **A2 — частично (live)**: инвариант памяти подтверждён (факт сохранён и
  отозван в следующем ходу, текст+эмоция+аватар согласованы). Инвариант
  «голос→policy→инструмент→postcondition» НЕ закрыт: профиль на HostOS level 0
  (sandbox, мутации запрещены), а смена уровня через UI падает 503
  (set_hostos_level делает stop/start агента через console API и теряет связь).
  Длинный многошаговый ReAct-ход через релей выбил companion (launcher exited).
- **A2 — DONE (live, частично в scope)**: все три инварианта подтверждены живьём.
  (1) Память: факт «кодовое слово coh-…» сохранён и отозван в следующем ходу.
  (2) Инструмент+postcondition: agent вызвал `HostOSSearch.list_directory` по
  промпт-фиксу (раньше 15 шагов уходило в `search_skills` dead-end), получил
  реальный листинг sandbox (`_system`, `izumrudny`, `voice`) и ответил за 37 с
  с именами из результата — postcondition доказан логом. (3) Текст+эмоция+
  аватар приходят в одном envelope. Граница: OBSERVER читает только framework
  dir; для host-wide поручений нужен OPERATOR (смена уровня через UI падала
  503 — сделан устойчивый retry в jawl_web.set_hostos_level, код закоммичен,
  live-проверка уровня ещё впереди).
- **A3 — DONE (live)**: интерактивный SLO на тёплом профиле. Warm turn→first
  audio: p50 6.9 с, max 8.4 с (цель ≤6 с turn / ≤10 с first-audio — в норме на
  тёплой цепочке; deepseek-релей отвечает за 3.4–7.6 с, TeraTTS 0.5–1.9 с).
  Cold first-audio после рестарта 8.9 с (модели уже загружены лаунчером, поэтому
  «холодный» старт у пользователя = честный статус rail, не молчание). Замеры:
  4 тёплых хода + cold. Barge-in реализован (playback_suppression + cancel);
  полный live voice barge-in E2E остаётся в бэклоге R3.
- **A4 — DONE (measured)**: Bonsai подтверждён на GPU1 (VRAM 13.4/16 GB, util
  94%), профиль без Bonsai ≈ 4 GB committed RAM (TTS 2.4 + VoiceMem 0.7 +
  companion ~1) — в целевом бюджете ≤8 GB. 17 GB «private» у llama-server —
  это reclaimable mmap page cache (после working-set trim WS падает до 240 MB);
  в системе 27 GB свободно, давления нет. Смена `--load-mode dio`/`--no-mmap`
  НЕ применена: она рискует скоростью/качеством vision, а реальная проблема —
  не память, а скорость зрения: 27B Q1 на 16-GB карте даёт ~100 с на скриншот
  (два прогона, один из них >120 с таймаут). Это отдельная задача (модель
  зрения слишком тяжела для «постоянного» watching), не часть A4.
- **A5 — PROTOTYPE (live-verified seams)**: `rust-client/` — минимальный нативный
  клиент (Rust 1.95, cpal + ureq + winit + ctrlc). Прототип доказал на живом
  стеке: (1) связь с компаньоном — `GET /api/health` вернул
  `status=degraded mode=jawl_terminal_gateway`; (2) владение микрофоном — открыт
  реальный вход Chat-Audeze Maxwell, 48000 Hz/1ch через cpal/WASAPI. Это
  фундамент ADR-036: аудио и в будущем Live2D/окно/OBS живут вне браузера.
  Следующий слой: нативный Cubism SDK поверх winit-окна + стрим аудио в
  companion по bounded-контракту. Браузерный голос не тронут до live-приёмки
  нативного контура.
- Дальше: нативный Live2D + аудио-стриминг в клиенте; открытый вопрос — замена
  тяжёлой VLM зрения (27B Q1 ~100 с/скриншот слишком медленно).

## Прогресс Фазы C — 2026-09-17 (в работе)

- **C1 — DONE**: выбран **Mocari** (pure-Rust Live2D/Cubism-compatible runtime,
  MIT, активно поддерживается) вместо проприетарного Cubism Native SDK (C++,
  лицензия, тяжёлый билд). Без внешних бинарных зависимостей, читает наш
  `.model3.json`/`.moc3`.
- **C2 — DONE (renders)**: нативный аватар рендерится в Rust. `rust-client
  --avatar` грузит mao_pro (260 drawables, 1 текстура), software-растеризатор
  (CPU, без GPU/wgpu — wgpu-hal не собирался на этом toolchain) рисует
  персонажа в окне winit с idle-анимацией (sway + breathing + mouth).
  Headless-режим (`--avatar --headless`) сохраняет кадр в
  `runtime/avatar-render.png`; проверка структуры кадра подтвердила связную
  фигуру с тонами кожи/волос, не шум. Исправлен маппинг координат: вершины в
  нормализованных model units, не в пикселях (bbox-fit).
- [!] Ограничение этой сессии: живой стек (компаньон + релей) поднимается
  лаунчером, но фон-запуски из моей сессии снимаются очисткой обёртки между
  goal-раундами (AGENTS.md уже предупреждал). Поэтому live-проверка
  «аватар реагирует на состояние компаньона» и C3/C4 требуют, чтобы стек
  был запущен из обычного окна PowerShell (см. TODO: каноническая команда).
  Команда: `powershell -File scripts\run_integrated_profile.ps1 -ProfileName
  daily -StartLocalAudio -UseVoiceMem -AsrBackend gigaam -TtsProvider tera
  -EnableProsodyPlanner -EnableStreamingAsr -UseOpenCodeRelay -EnableScreenWatch
  -EnableSensoryWorker -AmbientTriageSeconds 300 -JawlModelOverride deepseek-v4-flash`
- Следующее: управление выражением/движением от состояния компаньона
  (emotion/motion/lip-sync из ответа), затем C3 turn-recovery, C4 overnight.

## Прогресс Фазы B — 2026-09-17 (в работе)

- **B1 — DONE (live)**: screen-watch зрение перенесено с Bonsai-27B (8986) на
  Qwen3-VL-2B Q4_K_M (8983, GPU1). Живой ответ на «что на экране» — 4.2 с
  (было ~33 с) с точным описанием; RU OCR на gate-фикстуре 798 мс, warm
  174–387 мс. VRAM GPU1 упала с 13.4 до 10.9 GB. `run_integrated_profile.ps1`
  теперь поднимает qwen3-vl на 8983 и подключает screen-watch к нему; Bonsai
  остаётся на 8986 для тяжёлого анализа по запросу.
- **B2 — DONE (механизм), задача на OPERATOR открыта**: уровни HostOS меняются
  через config+restart (SANDBOX → OPERATOR подтверждён `access_level=2`,
  персистится). Устойчивый stop→poll→start с retry работает. НО: на OPERATOR
  многошаговый task-turn в «sandbox»-формулировке ушёл в timeout — агент после
  рестарта начал новый цикл, а anti-repeat подавил повторный ответ. Это не
  баг уровня, а известная хрупкость turn-lifecycle после restart (heartbeat +
  anti-repeat глушат follow-up). Нужна отдельная правка turn-recovery.
- **B3 — DONE (native voice pipeline live)**: `rust-client/` теперь владеет
  микрофоном, делает session-handshake с компаньоном и стримит аудио в
  `/api/voice/audio`. Live-проверено: 48000 Hz/1ch → 16 kHz mono s16le, чанки
  по ~37 KB уходят и принимаются (HTTP 200) в ASR-контур. Это доказывает
  нативный аудио-владелец (ADR-036) вне браузера. Live2D рендер в Rust —
  отдельный шаг: нативный Cubism SDK (C++, проприетарный) на диске нет, а
  текущий аватар — web-runtime; для нативного окна нужен либо Cubism Native,
  либо решение о рендере (см. DECISIONS при выборе).
- Дальше: нативный Live2D (выбор рендера) + turn-recovery после agent restart.


## Текущий goal — 2026-10-05

Приняты и зафиксированы решения (ADR-036..039): Rust-клиент как владелец
аудио и Live2D (без тяжёлого движка), мозг — deepseek-v4-flash через
OpenCode-релей (провайдер заменяемый), единый episodic timeline как
TimeService, Bonsai → GPU1 с on-demand unload. Активна Фаза A (TODO): U6
live-приёмка, episodic timeline, coherence E2E, SLO контура, ресурсы,
прототип Rust-клиента.

## План единой панели — 2026-09-15

Установлены 19 UX/UI skills. По исходникам оригинальной панели JAWL и адаптеров
Companion подготовлен [план U0–U6](UNIFIED_UI_INTEGRATION_PLAN.md): общая
навигация, единственный writer настроек, полная parity, сохранение native policy
и лучшего Companion voice pipeline. Iframe — только переходный механизм.
Следующий шаг: полный реестр полей/операций и baseline (U0).
Это документационный срез: runtime/UI не изменены, свежий browser/live gate
не запускался; production-ready не заявляется.

## Текущий канон — 2026-09-14 (обновлять при смене канона)

- Мозг: `deepseek-v4-flash` через OpenCode-релей 8891 (`-UseOpenCodeRelay`);
  baseline `config/jawl/settings.yaml` выровнен, `thinking_policy: first_step`.
  Бенч 2026-09-14: p50 2.4 с, JSON-конверт 100%; прочие Zen/GO-модели недоступны.
- ASR: GigaAM v3 (crispasr batch final, `giga_final.py`); Qwen3-ASR — опциональный
  фолбэк, по умолчанию не стартует. TTS: TeraTTSv2 (9889); prosody planner (8987)
  опционален и может быть выключен ради задержки.
- Зрение: постоянно — Bonsai (8986) + screen-watch + PerceptionFusion + гейт
  внимания; Bonsai поднимать до профиля.
- Интерфейс: единая оболочка компаньона (2367), консоль JAWL встроена вкладкой
  «Пульт JAWL» (`/console/`); WS-транспорт — только opt-in
  (`localStorage['jawl-ws']='1'`), включение по умолчанию — после протокольных тестов.
- Запуск: каноническая команда в `TODO.md`; сначала `scripts\run_coding_server.ps1`.
- Релей принадлежит запуску: если стартовал лаунчер — снимается его teardown'ом;
  внешний релей не трогается.

### Sber GigaAM canonical final — 2026-09-13

The canonical final transcript now comes from Sber GigaAM via crispasr file
mode (`giga_final.py`, `CrispASRFileTranscriber`): an A/B on the same 9.6 s
Russian clip showed GigaAM at 0.58 s / 21x realtime versus Qwen3-ASR at
1.19 s, with better case forms and punctuation («в лукошке», quoted
sentences). Investigation notes: the crispasr streaming mode emits no
`final` on silence and its partial window rolls (drops the head of long
utterances), which is why the file-mode batch over the buffered utterance
is the right final path; Qwen stays as fallback and its buffer is discarded
without a provider call (`ExternalASRService.discard`). Live voice turn:
5.17 s total (transcript ~0.5 s + deepseek answer ~4.5 s). Also fixed a
stale-replay hazard in the terminal gateway (pending bucket cleared on
submit, so a reused turn id cannot inherit replayed finals).

### DeepSeek brain + fast draft lane — 2026-09-13

The live brain moved to `deepseek-v4-flash` from the OpenCode GO catalog
(same relay; 15k-token provider cycles ~2-3 s vs big-pickle's 8-15 s; live
heartbeats 3.0 s, no tool protocol errors; `thinking_policy: first_step`).
To hide the remaining busy-wait when a new turn arrives while JAWL is still
working, the companion now serves `GET /api/perception/now` (freshest
fusion line) and the UI shows it as a dim provisional "Смотрю: ..." message
on every voice final and chat send; the real answer replaces it. When a
message arrives mid-turn, the turn text carries a bounded note that the
previous reply may still be in progress, so the agent treats both as one
context (JAWL steer/defer semantics). A brevity rule caps inner thought
fields at ~40 words per step. Framework load snapshot: ~20.3 GB RAM total
(Bonsai server 12.5, Tera 2.4, Qwen-ASR 1.4, JAWL agent 1.1, VoiceMem 1.3),
GPU1 7.3/16.3 GB, idle CPU ~25% of one core.

### Screen questions grounded — 2026-09-13

Direct screen questions no longer make the agent hunt for a missing
observation tool: the Companion enriches such turns (экран/скрин/«что
происходит»/«что видно») with the freshest fused perception observation
(chat, stream, voice, WS paths), the prompt rule forbids tool-hunting and
false "module disabled" claims, and the profile now runs
`thinking_policy: never` (hosted reasoning 2419 -> ~250-440 tokens per
step). Live check: a screen question answers in ~33 s with an actual
description of the focused window and content. Earlier log evidence: the
agent had already commented on a fused observation on its own at 17:04,
then burned 74 s on two empty skill searches at 17:05 before the fix.

### P2: single-connection WebSocket transport — 2026-09-13

The last N.E.K.O.-inspired phase landed: the Companion now serves one
RFC 6455 WebSocket at `/api/ws` (stdlib, no dependencies; handshake,
masked frames, fragmentation, ping/pong/close). Actions: `chat` (streams
deltas + final over the socket), `voice_chunk`/`voice_end`/`voice_reset`
(shared helpers with the HTTP voice handlers), `ping`. Auth is the session
cookie + origin allow-list at the handshake. The browser transport is
opt-in (`localStorage['jawl-ws'] = '1'`): voice chunks and utterance
finalization move to the socket when enabled; HTTP stays the default.
Tests: `tests/test_ws.py` 3/3 (auth gate, ping/chat roundtrip, voice gap);
live probe: 101 handshake, pong, chat delta+final 9.8 s, voice_reset ack.
Regressions: test_web 42/42; full gate re-run after the change: 12/12 PASS.

### Phases closed: vision live, fusion, P1-lite/P3/P4 — 2026-09-13

Active vision is permanently wired: the launcher's `-EnableScreenWatch`
starts the VLM screen watcher (Bonsai on 8986 as eyes, companion level 1
auto-set), creates the correct JAWL event intake
(`sandbox\_system\instances\daily\.jawl_events` — the agent polls it every
second) and `-EnableSensoryWorker` autostarts the sensory worker
(window/music/speech). `PerceptionFusion` merges the freshest screen
caption, window, music and speech into ONE observation before the attention
gate (threshold/cooldown/budget) forwards it to JAWL; live evidence:
9 wakeups, fused summaries, prompt rule `ZZ_SCREEN_COMMENTARY.md` for
occasional short comments. Operator visibility: `runtime/voice-events.ndjson`
(asr_final, screen_delta, system_music/speech). P1-lite: arbiter queue bound
(8, overflow cancels the least important waiter) and a terminal-gateway
circuit breaker (4 consecutive failures -> 30 s cooldown); eager connect so
doctor is green from startup. P3: proactive queue is persisted (survives
restarts). P4: `ZZ_ANTI_REPEAT.md` prompt rule. Ambient triage scheduler now
runs (300 s). Fresh full gate after all changes: 12/12 PASS.

### P0: terminal gateway transport live — 2026-09-12

The N.E.K.O-driven P0 landed: the Companion now keeps ONE persistent TCP
connection to the JAWL agent terminal (`jawl_terminal.py`,
`JAWL_GATEWAY <seq>` handshake with replay-from-cursor, correlated
`turn_id` turns, cancel control line, reconnect with backoff). Chat turns no
longer route through the console HTTP bridge and its idle/connecting race,
gap cursors or stuck-input failure modes; `JawlChatRouter` keeps the console
adapter for memory/journal/persona APIs. Live profile reports
`mode=jawl_terminal_gateway`; live turns answered ("Готов.", "На связи.",
8.5–10.5 s on big-pickle). Tests: terminal 4/4 (roundtrip, cancel,
reconnect replay, turn.error), regressions web 42/42, jawl_web 27/27,
proactive 11/11. Also switched the JAWL profile baseline to
`event_acceleration.active_cycle_policy: defer` so autonomous events stop
cancelling active user turns (their own example default). Local Bonsai was
rejected as the live brain: the Q1 quant fails the strict JSON tool
protocol ("Tool protocol error"), cloud big-pickle stays.

### EOPA-lite initiative gates — 2026-09-12

The proactive feed now has an initiative policy beyond idle/rate limits:
delivery is restricted to learned active hours (hours with conversation on
at least two distinct days in the last two weeks; empty learning means no
blocking), delivered items carry useful/noise feedback buttons that open an
exponential quiet window (30 min doubling up to 4 h) and reset on "useful",
and identical texts are suppressed for 24 h. State persists in
`runtime/proactive-state.json`; `POST /api/proactive/feedback` accepts the
verdicts. Tests: proactive 11/11, test_web 42/42.

### Single-origin console proxy — 2026-09-12

Ф3 phase 2 landed: the Companion now reverse-proxies the JAWL console under
its own origin (`/console/` for files, `/console-api/*` mapped to the
console's `/api/*`). The console token is injected server-side
(`X-Console-Token`), console.js is rewritten on the fly so its absolute
`"/api/...` calls resolve inside the proxied namespace, SSE responses
(chat/logs streams) are relayed without buffering, and the whole namespace
is gated by the Companion session cookie (POSTs additionally honour the
origin allow-list). The UI gained a "Консоль JAWL" card linking to
`/console/`. Verified live: full console UI (JAWL v0.17.0-stable) renders
and its APIs answer through 127.0.0.1:2367; test_web 42/42 including a new
proxy test.

### Sensory bridge live + phases gate — 2026-09-12

Ф4 is closed as a live loop: `SensoryIngestor` tails the sensory worker's
NDJSON (`--sensory-file`, forwarded by the launcher as `-SensoryFile`,
which enables `--ambient-memory`), maps changed screen frames / music /
speech into bounded ambient observations (music deduplicated, privacy
filters stay in AmbientMemoryBuffer) and surfaces its counters in
`/api/ambient-memory` and doctor (`sensory_ingest`). Live evidence: a real
45 s worker run (91 screen frames -> 2 changed ingested, 4 music, 1 speech,
0 errors) produced 7 observations; zen-session8 runs the profile with the
bridge enabled. Full regression gate after all phases: 12/12 steps PASS
(compile, snapshot verify, secret scan, unit batch, e2e, browser E2E, mic
gate, ps1 parses, git diff). CodeSee was also adopted: the repo now carries
`.codesee/features.json` (7 epics / 18 features, validated) plus the
installer's AGENTS.md section, and a local viewer runs at
http://localhost:5173/.

### Proactive channel v0 + service visibility + coding lane — 2026-09-12

Phase work landed in one pass: (1) Ф2 v0 proactive channel
(`src/jawl_voicecompanion/proactive.py`): the feed polls the JAWL chat
history via the native client (`JawlWebClient.chat_history`), seeds a
baseline on first poll (old history is never delivered), filters the
Companion's own turn echoes, and gates new initiative by conversation idle
(45 s after the last turn), rate limits (5 min gap, 6/hour) and a bounded
queue (20); `muted` (silence) and `speak` switches are exposed through
`/api/proactive` and `/api/proactive/settings`, with a "Инициатива JAWL"
card in the system tab. Auto-speak of delivered items is deliberately
deferred until barge-in tuning. Tests: test_proactive 7/7, test_web 41/41.
(2) Ф3 phase 1: `/api/doctor` now aggregates the streaming ASR lane state
and bounded probes of the local helpers (planner 8987, coding 8986, relay
8891) - all services visible in one UI panel, fail-soft at 1.5 s.
(3) Ф5 coding lane: `scripts/run_coding_server.ps1` serves Bonsai-27B Q1
on 8986 and the `bonsai-local` provider is registered in the operator's
opencode config.

Restart-hygiene root cause found: orphaned JAWL agents
(`runtime\jawl-sources\jawl-20260906-daily-v2\src\main.py`) survive a
console kill; the next launcher attaches to the stale agent whose cycle
does not produce a fresh heartbeat marker within 300 s, so the profile
fails closed. Restart procedure now kills stray `src/main.py` processes and
duplicate relays before launch. Live session zen-session7 is up (Companion
2367 READY, JAWL online, doctor green on all workers).

### Reflection layer shipped (VoiceMem consolidation v1) — 2026-09-12

The adopted reflection pattern is live: `scripts/voice_reflection.py` splits
the dialogue history into closed segments (30-min gaps, 10-min close age),
consolidates each segment with ONE bounded LLM call (Zen relay / big-pickle),
and writes the results into canonical JAWL memory through its own
session-protected route (`operation=remember`, kind summary/fact/preference,
`source=reflection`, stable `reflection-*` keys). Checkpoint
(`runtime/reflection-state.json`), journal (`runtime/reflection-journal.ndjson`)
and `scripts/run_voice_reflection.ps1` with a 20-minute loop provide
crash-safe periodic operation. Verified: 43 structured memories present in
`agent.db` (structured_memories), including reflection summaries/facts.

Paths: JAWL memory is the canonical owner (no second authority); the
VoiceMem sidecar write path turned out to be unusable for external writers
(local Qdrant single-instance lock) and was replaced by the canonical route;
an offline VoiceMem helper (`services/voicemem_ingest_helper.py`) remains for
standalone use.
### Zen test lane (big-pickle) + instant-answer status — 2026-09-12

The OpenCode Zen relay lane is now a first-class test provider: the
Antigravity CLI (agy 1.2.1) is geo-blocked for this account ("not eligible
... not available in your location"; SOCKS 3067 does not help), so the fast
cloud lane comes from the operator's Zen key via the in-repo relay
(`scripts/opencode_header_relay.py`, 8891). Measured: `big-pickle` answers
in 1.4-1.8 s with clean Russian; JAWL startup heartbeat over the relay
completes in ~5 s (companion READY in 8 s). `gemini-3.8-flash` returns 500 on
the free tier through the relay.

Barge-in behaviour now: the interruption itself is instant (120 ms duck ->
cancel -> continuous listening; verified adaptive gap=12 run), and the new
answer starts as soon as the LLM replies - with big-pickle that is ~2 s, the
ChatGPT-like feel. Remaining latency contributor: JAWL autonomous heartbeat
cycles interleave with the voice turn; limiting autonomous chatter while a
correlated voice turn is active is the next tuning step.

Repro: start the relay with the Zen key (OPENCODE_RELAY_KEY from
auth.json) on 8891, launch the profile with `-UseOpenCodeRelay
-JawlModelOverride big-pickle`.
### Adaptive full-duplex voice shipped — 2026-09-12 night

The full-duplex milestone from the TinyDuplex research is implemented and
accepted live: streaming ASR lane (CrispASR + GigaAM-v3, RU partials every
~0.5–0.8 s with punctuation, fed from the browser PCM path; canonical final
stays Qwen3-ASR), semantic end-of-turn (`turn_policy.py`: trailing «и/но/что/
в…» holds one bounded silence extension 800→2000 ms; verified live on the
draft "...поверить. Но"), adaptive draft cadence (800 ms streaming / 2500 ms
fallback), DUCK-before-STOP (~120 ms fade), backchannel v0 («Угу.» after 7 s
of user speech, quiet, never owns the turn), hands-free default on.
Real-browser barge-in passed at gap=12 — cancel mid-speech at 15.3 s while
the first TTS streams ran 9.5–11.9 s, second turn captured, both transcripts
matched (`runtime/browser-barge-in-adaptive-gap12-20260912.json`). New unit
tests: turn_policy (7), streaming_asr (4). Details:
[DUPLEX_RESEARCH_ADOPTION.md](DUPLEX_RESEARCH_ADOPTION.md).

### Night session 2026-09-11 — vision review, fixes, model verdicts

Full review against the operator's idea is in
[COMPANION_VISION_REVIEW.md](COMPANION_VISION_REVIEW.md). Key outcomes:

- **Memory myth corrected:** fresh JAWL console+agent = 54 MB RSS, Companion
  = 30 MB (port-verified). The earlier "6.8-11 GB JAWL" figure was a
  misattributed process. The unification refactor was **declined** —
  measured bottleneck is the LLM route, not process boundaries.
- **Fixes shipped tonight:** emoji stripped from all speech paths + prompt
  rule; SER gate in the sensory worker (music no longer becomes speech
  events, verified on real clips); live ASR switched to Qwen3-ASR; Tera
  default restored (single baked voice); VoxCPM parked; barge-in harness
  diagnostics; full regression gate re-passed (396 + 16, exit 0).
- **Model verdicts:** TAARDIS-27B (ternary Qwen3.8) REJECT — RU fail and
  0/3 executed coding tasks; GSQ-RCO IQ2_S RU-pass but engine-slow
  (24 t/s gen / 19 prompt) — reference only; **Bonsai-27B Q1 PASS**
  (RU, vision, 3/3 HumanEval-class coding executed, 101-104 t/s) — stays
  the brain; local coding lane can use its llama.cpp endpoint today.
- **Research recorded:** proactive-initiation gating (EOPA-style evidence
  thresholds, low default proactivity, silence control) and
  segment/recurrence-triggered memory consolidation (RecMem/GAM/
  LycheeMemory) — roadmap in the vision review, §5-§7.
- **Ports/UI:** phased plan agreed-in-principle (single Companion origin
  as reverse proxy; navigation consolidation; memory review UI); no
  restructuring performed without operator sign-off. Personality slot
  stays empty until the natal-chart synthesis arrives.

### N.E.K.O family audit (2026-09-10 evening)

Audited all Project-N-E-K-O repositories (the closest public relative of our
product). Full report with per-repo verdicts and the ranked take-list in
[NEKO_FAMILY_AUDIT.md](NEKO_FAMILY_AUDIT.md). Top takeaways: (1)
GPT-SoVITS behind their GSV-Bridge pattern = the cheap RU voice-clone lane
(5 s reference, queued worker, v3 WebSocket streaming, hot voice swap);
(2) their five-tier memory (working/recent/fact/reflection/persona) plus
~120 KB of production anti-repetition machinery validates and extends our
L0/L1/L2 sensory-memory plan; (3) proactive initiation, memory review UI,
and the RN Live2D+PCM phone client are directly reusable patterns.

### Per-sentence emotion pipeline live (2026-09-10 evening)

Voice lane now emotes per sentence: a gemma-3-1b planner (GPU1, 8987,
~1 s/plan) annotates every sentence with a clamped WORLD2 envelope
(pitch/F0-range/energy/speed); TeraTTSv2 renders sentence 1 neutral
immediately and the tail with individual envelopes. WORLD-based prosody
(formant-preserving + punctuation pauses) replaced the rejected
phase-vocoder; operator listening verdicts recorded in
[VOXCPM_INTEGRATION_20260909.md](VOXCPM_INTEGRATION_20260909.md).
Live defaults: TeraTTSv2 voice + Qwen3-ASR; VoxCPM voice-clone parked by
operator decision. Unit tests 13/13 (planner annotation + neutral
degradation). In parallel: TAARDIS-27B (Qwen3.8 ternary, 5.9 GB + Doctors
corrections) is being built against a synthetic CUDA 12.8 toolkit on G:\
(cublas was missing from the installed toolkit; import libs were generated
from Ollama's cublas DLLs) — the realtime-brain candidate; Round 5 note in
[MULTIMODAL_MODEL_GATE.md](MULTIMODAL_MODEL_GATE.md).

### Bonsai-27B Q1_0 bench — one model for brain+eyes (2026-09-10)

Prism ML `Bonsai-27B-gguf` Q1_0 (3.8 GB) + mmproj Q8 (0.63 GB) runs on our
existing llama.cpp CUDA b10883 (GPU1, load 0.16 s, VRAM 5.4 GB, 10.6 GB
still free): RU text coherent at **102 tok/s** generation and **2164 tok/s**
prefill (the JAWL 11k route projects from 12–27 s to ~5 s), RU screen OCR
PASS with exact strings, desktop captions more detailed than Qwen3-VL-2B
(reads on-screen file names). Reasoning must be disabled per request;
counting tasks show 1-bit precision limits; JAWL tool-call compliance
untested. The linked AMD Strix-Halo release is not applicable to NVIDIA
hardware; the ternary Q2_0 (7.17 GB) + DSpark drafter remain the upgrade
path if VRAM allows. Round 5 candidate recorded in
[MULTIMODAL_MODEL_GATE.md](MULTIMODAL_MODEL_GATE.md). This supports the
operator's decision to drop a dedicated background VLM: cheap extractors
run the sensory stream, Bonsai covers conversation and on-demand vision.

### Multimodal gate Round 4 — modular sensory bundle PASS (2026-09-10)

The modular sensory bundle passed the gate at integration level:
Qwen3-VL-2B Q4 (llama.cpp CUDA, GPU1, 8983) — RU screen OCR exact ×2
(0.2–1.7 s vs 83.8 s CPU), whisper ASR, audio→ASR→VLM binding ×2 (question
from synthesized audio answered with exact on-screen facts, 0.4 s),
realtime tier latencies fit (warm captions 2.5 s, CLAP 30 ms/chunk,
MobileCLIP2-S0 36 ms/frame CPU, SER 0.3–0.5 s), negative controls honest
(1×1 px → no hallucination; music→SER `other` 0.982). DSP prosody engine
added to the VoxCPM worker (pitch/energy/speed envelopes, text-identical
whisper roundtrip). Full evidence and costs (VoxCPM ≈ 11 GB RAM resident)
in [MULTIMODAL_MODEL_GATE.md](MULTIMODAL_MODEL_GATE.md) Round 4 and
[SENSORY_STACK_DESIGN.md](SENSORY_STACK_DESIGN.md). Remaining: sensory
worker soak verification, MobileCLIP/OCR integration into the worker,
ambient/VoiceMem wiring, then a fresh 8-hour duration rerun.

### Sensory stack design and Rick Astley bench — 2026-09-10

The streaming sensory architecture is fixed in
[SENSORY_STACK_DESIGN.md](SENSORY_STACK_DESIGN.md): fast specialized models
run constantly, heavy VLM periodically, the LLM reads compact
`MusicState`/`VisualState`/`SpeechState` JSON, never raw media. Live bench on
60 s of YouTube playback (loopback + 57 frames): MusicState (librosa
BPM/beat/key + Basic Pitch notes, 5.1 s for 60 s audio) and CLAP GPU tags
(30 ms/chunk; "energetic dance music" + "upbeat male pop vocals" — correct)
work; Qwen3-VL-2B Q4 via llama-server on GPU1 (8983) captions desktop frames
in 2.5 s warm; whisper on music hallucinated text, confirming the
VAD-gated ASR design. MobileCLIP2/PP-OCRv6/DUSHA SER/sensory_worker
prototype are the next adoption steps (order in the doc).

### Full-duplex research adoption — 2026-09-10

Read `G:\AI\tinyduplex\FULLDUPLEX.md` + `MVP_LOCAL_PC.md`. Adopted mapping is
fixed in [DUPLEX_RESEARCH_ADOPTION.md](DUPLEX_RESEARCH_ADOPTION.md): the
two-lane design (Companion realtime ⇄ JAWL async) is validated; the voice
lane must stop blocking on the full JAWL turn (ack/backchannel lane is the
fix). Cheap adoptions now: DUCK-before-STOP on barge-in, rule-based
backchannel clips, VAD≠end-of-turn (120 ms commit, syntactic hold), faster
ASR draft cadence, adaptive sensory rate (update only on representation
change). Sensory context uses L0 ring buffer → VoiceMem → JAWL memory tiers.
Adopted SLO table (ack first-audio ≤1.2 s p50, barge-in detection ≤80 ms
p95, playback stop <100 ms, queues ≤200 ms). Tiny turn-taking classifiers
and true duplex listen-during-speech are post-MVP (AEC is a prerequisite).

### Voice stack and release slice — 2026-09-10

The integrated launcher supports `-TtsProvider voxcpm` (GPU1 worker, reuse +
health-check) alongside `-AsrBackend whisper`. A disposable connected
profile (VoxCPM2 + whisper-turbo + Gemma/Ollama) passed real-browser voice
E2E 3/3 and real-browser barge-in at gap=20 (two turns, cancel during first
speech, two TTS streams, 21 buffers, transcripts matched); gap=9 is
impossible with whisper-turbo because uploads pause during ~16 s
end-processing. Evidence: `runtime/browser-voice-e2e-20260909-voxcpm-whisper.json`,
`runtime/browser-barge-in-voxcpm-whisper-gap20-20260909.json`,
details in [VOXCPM_INTEGRATION_20260909.md](VOXCPM_INTEGRATION_20260909.md).

The clean-install slice passed: rebuilt wheel hash-verified against
`dist/SHA256SUMS.txt`, secret scan 0 findings, fresh isolated venv install +
CLI help outside the source cwd, rollback-reinstall verified, and a new
workers/assets integrity manifest with licences was written to
`runtime/workers-manifest-20260909.json`. The full repository gate after the
changes passed: 394 non-E2E + 16 E2E tests, six-viewport browser interaction,
synthetic mic gate, Node check, PowerShell parse and `git diff --check`
(`runtime/full-gate-20260910-voxcpm.log`). Remaining external gates are
unchanged: physical microphone/AEC, OBS capture, long unattended duration,
memory consolidation/ambient, and user acceptance of a clean install on a
separate machine.

### Voice worker measurements — 2026-09-09 evening

- Whisper-turbo ASR worker (`-AsrBackend whisper`, port 8984, 12 threads,
  beam 5) transcribed the 8.8 s VoxCPM2 RU clip in 3.39–3.69 s (RTF ≈ 0.385)
  with an exact-content transcript. This is worker evidence only; the
  connected profile still defaults to `-AsrBackend qwen` until a live profile
  rerun switches the backend.
- VoxCPM2 native `/tts/stream` re-bench: first-audio warm `0.152–0.175 s`
  (cold `1.5 s`), RTF `0.87`, `/cancel` stops within ~0.5 s and the next
  request recovers. Numbers and the VRAM note are in
  [VOXCPM_INTEGRATION_20260909.md](VOXCPM_INTEGRATION_20260909.md). The
  worker was stopped before the eight-hour soak to free GPU1.
- Eight-hour unattended acceptance `qwen-ollama-unattended-8h-v4-20260909`
  was manually aborted by the operator after ~12 minutes (not a cycle
  failure): cycles up to 0004+ completed write/read/cleanup normally, the
  orchestrator then closed owned ports and revoked cleanup correctly, so its
  summary records the manual stop as `exit=2`. The operator then requested a
  30-minute variant: `qwen-ollama-unattended-30m-v4-20260909` PASSED with
  34/34 cycles at `temperature=0.0` — zero forbidden actions, zero unexpected
  tools, zero idempotent no-op retries, exactly one real write per cycle,
  34/34 SHA postconditions and native cleanups, unattended lease revoked,
  owned ports closed. Evidence:
  `runtime/qwen-ollama-unattended-30m-v4-20260909.json`. This closes the
  30-minute corrected-harness slice; the eight-hour duration gate itself
  remains intentionally short-run accepted and is still open as a duration
  claim.

## Latest Goal compatibility slice — 2026-09-09

The presentation origin now has an independent read-only token for any
non-loopback bind. The control-plane LAN credential is not reused, and the
avatar page forwards only the presentation token to its two read-only state
requests. Loopback OBS behavior is unchanged. This is a security boundary
fix, not evidence that physical OBS capture or the long presentation soak has
passed.

Latest repository gate: 394 Python tests, 16 HTTP E2E, six-view browser,
synthetic microphone, Node mic gate and `git diff --check` — all passed.

The runtime refactor now has both halves of its first slice: `CompanionRuntime`
owns the bounded, idempotent control/presentation lifecycle and `composition.py`
owns component construction. This unifies the organism's runtime boundary
without merging JAWL cognition with VoiceMem or creating a second memory/tool
authority. Shutdown now also performs a bounded presentation-thread join; the
public server factories remain compatible.

The release-input secret scanner also passed with zero findings across 1192
source/config/docs files, and a fresh isolated venv imported the rebuilt wheel
and ran CLI help outside the source cwd. Runtime workers/assets and rollback
remain separate acceptance gates.

Real Windows WASAPI loopback also passed a short bounded smoke through
`pyaudiowpatch`: 93 chunks, 48 kHz stereo, zero dropped chunks and no raw
media persisted. Physical mic/AEC and long ambient capture remain unverified.

### Connected voice and VoiceMem state — 2026-09-09

The bounded local-Qwen profile now passes the real connected acceptance rather
than only mock/HTTP checks. VoiceMem local-memory mode uses the same local
OpenAI-compatible endpoint as JAWL and bypasses the system proxy only for
loopback; its previous `voicemem_stream_failed` path was reproduced and
fixed. Evidence shows 3/3 browser voice turns, canonical memory and native
write/read/restart recovery, followed by VoiceMem `accepted=6`,
`completed=6`, `failed=0` and status `ready`.

The fresh barge-in acceptance also passes at the measured Qwen latency profile:
the first TTS stream is cancelled, the second turn is correlated, and two
WebAudio buffers are scheduled. Gap=2 remains intentionally recorded as a
negative latency diagnostic; it is not used as a realtime-quality claim.

The release wheel was rebuilt and verified with `dist/SHA256SUMS.txt`; a fresh
target-directory installation passed package import and untruncated CLI help.
Worker/model/assets installation and rollback remain separate open gates.

The connected Qwen r3 browser acceptance additionally passed the Memory tab
create/revise flow, native JAWL restart, revised-value recall and cleanup:
`runtime/memory-ui-qwen-r3-20260909.json`.

### Long-run unattended variance — 2026-09-09

The latest eight-hour Ollama unattended run stopped fail-closed at cycle 39.
The provider completed the native write/read, then called forbidden
`GoalSkills.update_goal` and repeated the writer as an idempotent no-op before
finishing the Goal. The native postcondition and cleanup were correct, but the
provider protocol was not: this is negative variance evidence, not an
eight-hour production claim. The orchestrator closed owned ports and revoked
the unattended lease. Evidence:
`runtime/unattended-qwen-ollama-8h-v3-20260909.json`.

The soak harness was corrected after this run: an idempotent writer retry is no
longer counted as a second real write, while forbidden legacy Goal calls found
in durable Goal evidence now fail the cycle explicitly. Focused harness tests
pass. A fresh long-run is required after this correction.

The soak harness now makes the protocol precedence explicit and independently
checks terminal phase, completed step, empty pending/blocker state, and an
all-successful last action batch. The corrected v2 run stopped at cycle 5:
after successful native write/read the provider invented the nonexistent
`GoalSkills.complete_goal` action, so JAWL rejected false completion. Cleanup,
lease revoke and port closure passed. A disposable-profile temperature
override was added; the v3 smoke passed 2/2 at `temperature=0.2`. Fresh v3
eight-hour acceptance `qwen-ollama-unattended-8h-v3-20260909` is currently
active on ports 8770/2368/8767; the full-duration claim remains open until its
final report.

The first fresh unattended Qwen probe exposed a real provider-compliance
negative: after a valid write/read the model omitted the required terminal
ledger and JAWL returned `blocked`. The harness now cleans such fixtures via
the native delete route; its fixed connected rerun passed 3/3 and revoked the
unattended lease. Eight-hour soak and broader provider variance remain open.

The same three-cycle acceptance also passed through the persistent Ollama
OpenAI-compatible endpoint on `11434` using
`qwen3.8-27b-abliterated:latest`: native write/read, durable postcondition,
recoverable cleanup and lease revocation all passed. Evidence:
`runtime/unattended-qwen-ollama-3cycle-20260909.json`. The disposable
`llama-server` endpoint on `53092` was not required for this run.

The pinned JAWL loop now has a fail-closed compatibility path for a legacy
empty provider envelope after native work. It requires a terminal durable
ledger, no pending steps/next action/blocker, and `success` for every outcome
in the last action batch. Focused policy tests: 6 passed; snapshot verifier:
348 files, digest `89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d`.

The new `scripts/run_unattended_provider_recovery.py` follows the proven
Goal/Heartbeat path, requires a durable write before the outage, and fails
closed otherwise. Live31 passed the complete provider/JAWL recovery acceptance
with exact relay stop, restore, restart, native readback, reconciliation,
exactly one real write, cleanup and lease revocation. Live30-r2/r3 remain
negative safety evidence where invalid provider completion was blocked. The
opt-in `--auto-stop-provider` mode is restricted to a verified non-baseline
loopback relay; `scripts/run_provider_recovery_live.ps1` provisions the
disposable level-3 profile without touching baseline ports.

Live evidence remains negative in
`runtime/unattended-goal-soak-live12-20260909.json`: GPU1 JAWL completed native
write/read, but the local Gemma timed out before a terminal Goal response and
the ledger stayed `initial`. The harness correctly rejected completion after
300 seconds. The provider's roughly 10k-token startup request also exceeded
120 seconds, so this model is not a production realtime baseline.

The latest correction also excludes communication-only terminal messages from
Goal completion evidence. The first real two-cycle unattended soak then passed
with native postconditions and lease revocation; provider restart/failure
recovery during unattended work remains open.

The OpenAI-compatible loopback relay was also corrected to preserve chunked
HTTP/1.1 streaming. A direct probe received all 7 SSE events through the
relay, including `[DONE]`. This removes a transport truncation/hang cause but
does not close the provider/JAWL restart-recovery gate; the disposable live25
experiments remain negative diagnostics.

The provider-recovery harness now aborts and persists a negative report when
the durable native write boundary is not reached; it no longer continues into
restore/readback on a later unrelated heartbeat. `live26` therefore remains
negative provider-schema evidence rather than a recovery claim.

## Актуальная сводка — 2026-09-09

Приложение находится между интеграционным beta и production hardening, а не
в статусе production-ready. Последний полный gate после native-delta adapter
slice прошёл: 372 unit/regression теста, 16 HTTP E2E, browser interaction
на шести разрешениях, synthetic mic gate и `git diff --check` (`run_full_gate.ps1`,
exit 0). Связанные локальные срезы уже доказаны отдельно:
реальный Companion → JAWL → Ollama native action, три browser voice turns,
canonical memory revise/restart/recall, strict barge-in, restart во время
inference и provider-failure recovery. Они перечислены с артефактами в начале
`TODO.md` и не должны описываться старым текстом ниже как полностью
непроверенные.

Последнее изменение — опциональный VoxCPM2 worker: native `/tts/stream`,
bounded chunk cancellation через `/cancel`, zero-shot по умолчанию; TeraTTSv2
остаётся основным быстрым TTS. Evidence и ограничения:
[`VOXCPM_INTEGRATION_20260909.md`](VOXCPM_INTEGRATION_20260909.md).

Integrated launcher теперь умеет явно выбирать native access level `0..3` и
включать Debug Broker только для выбранного disposable-профиля. Level-3
launcher live-проверен: 93 native skills прошли матрицу `0→3`, а 8 read-only
проб прошли через маршруты HostOS/HostTerminal/DebugBroker. Это подтверждает
штатный путь нативных инструментов, но не закрывает unattended heartbeat,
checkpoint/reconciliation и 8-hour soak.

В browser-контуре исправлен потенциально бесконечный `AudioContext.resume()`:
возобновление теперь bounded, а voice/avatar monitor деградирует явно вместо
зависания UI. После исправления browser interaction и полный mock/HTTP gate
снова прошли.

После этого исправлен transport-level edge case в owned JAWL snapshot:
локальная модель могла поместить валидный Goal-v2 `execute_skill` wrapper внутрь
`actions[]`. Теперь только однозначный wrapper нормализуется в canonical
`ActionCall`; произвольный `SQLTasks.*` не получает alias и остаётся под
registry/policy guard. Regression и live GPU1 browser profile 3/3 прошли;
актуальный snapshot digest после добавления native action-intent recovery и
bounded duplicate-goal continuation:
`89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d`.

Live crash-boundary work выявил важное правило для Goal Ledger: после restart
JAWL может сам начать read/reconciliation до operator-подтверждения. Поэтому
recovery intent теперь сохраняется при последующих планах с повторяющимся
локальным id; reconciliation использует `(tool, action_id)`. Исправление
прошло unit-тест и свежий live acceptance после обновления snapshot; evidence
зафиксирован в `runtime/goal-reconciliation-live-20260909T024434Z.json`.

Новый unattended harness (`scripts/run_unattended_goal_soak.py`) теперь
проверяет native ROOT lease, bounded Goal cycles, action journal,
postcondition и cleanup. Full gate после добавления harness-теста прошёл 360
тестов. Live acceptance пока отрицательный: lease был реально выдан и
отозван, но `jawl-gemma4-it:latest` оставил Goal в `waiting` без native
action. Отчёт: `runtime/unattended-goal-soak-live2-20260909-r2.json`.
Это provider/model compatibility finding; unattended и 8-hour soak остаются
открытыми.

Главный следующий срез — не новая модель, а единый связанный daily profile,
который в одном экземпляре докажет memory → voice → native action → verified
result → restart/recovery. После него идут физическая акустика, Full Access /
heartbeat / unattended soak, memory consolidation/erasure, Live2D/OBS hardening,
LAN/release и только затем production claim. Vision пока deferred до выбора
модели, соответствующей универсальному multimodal gate.

Companion теперь умеет принимать только коррелированные user-safe
`assistant.delta`, сверяет их с authoritative `assistant.final` и удаляет
provisional UI при terminal error/mismatch. Текущий pinned JAWL всё ещё
публикует только финальный event, поэтому это capability seam, а не claim
настоящего token-level realtime.

Этот daily profile теперь принят: `runtime/connected-daily-acceptance-20260909-r3.json`.
Один реальный профиль прошёл remember/revise, три русских browser voice turn,
native write/read, JAWL restart, canonical memory recall после restart и
recoverable cleanup. Первый отказ был не потерей памяти, а startup race: общий
health уже показывал `jawl=connected`, но aggregated status оставался `degraded`
из-за отключённых optional adapters; acceptance теперь проверяет JAWL control
plane отдельно и ждёт native memory projection.

Следом принят representative Full Access slice на том же pinned JAWL snapshot.
Уровни 0–2 проверены по канонической границе sandbox/framework, level 3 —
реальным native write с cleanup, emergency-stop fail-closed/reset и bounded
ROOT autonomy lease. Catalog содержит 84 HostOS, 2 HostTerminal и 7 DebugBroker
skills; availability совпала с required access level для всех 0–3. Read-only
namespace probes прошли через native `/api/hostos/skill` и `/api/debug/skill`.
Evidence: `runtime/native-policy-levels-0-2-20260909.json`,
`runtime/native-policy-level-3-20260909.json`,
`runtime/native-catalog-matrix-full-access-20260909-r2.json` и
`runtime/native-namespace-full-access-20260909-r2.json`. Это не закрывает
unattended heartbeat, crash checkpoint/reconciliation и 8-hour soak.

Opt-in lifecycle wiring теперь проверено отдельным живым disposable-прогоном:
`-EnableSupervisor` регистрирует профиль в нативном JAWL InstanceManager,
запускает pinned `src.instances.supervisor`, а web-console делегирует ему
start/stop. Supervisor и child используют тот же `JAWL_INSTANCES_ROOT` и
sandbox, что и integrated launcher; намеренная остановка переводит durable
`desired_state` в `stopped`, поэтому не маскируется под crash. Startup race
статуса и stale `supervisor.pid/lock` после force-stop закрыты bounded-логикой.
Evidence: `runtime/supervised-profile-acceptance-20260909-r3.json`.
Отдельный live gate `runtime/supervised-recovery-acceptance-20260909.json`
подтвердил, что действующий ROOT lease разрешает один bounded restart, а revoke
lease переводит профиль в `crashed` без третьего child. Это не доказывает
reconciliation незавершённого task-ledger/checkpoint или 8-hour soak.

## Актуальное дополнение — 2026-09-08

### P0-B: provider failure после durable native effect — принято

Live acceptance `runtime/provider-failure-native-recovery-current-v11.json`
прошёл на локальном Gemma baseline. После фактической записи через
`HostOSWriter.write_file` изолированный Ollama на `11435` был остановлен.
Companion получил коррелированные terminal `error` и non-speakable `final`,
после восстановления провайдера JAWL был перезапущен, native readback
вернул совпавший SHA-256, journal подтвердил ровно одну реальную запись, а
recoverable cleanup удалил файл.

В ходе этого recovery-среза исправлены три дефекта owned snapshot:

- `turn.error` теперь действительно переводится в типизированное gateway-
  событие, а не ошибочно в `tool.completed`;
- gateway `StreamWriter.drain()` ограничен таймаутом и не удерживает ReAct;
- terminal `EventBus.flush()` имеет bounded safety timeout.

v6 и v7 не принимаются: там была durable recovery, но отсутствовали
терминальные stream events. v8/v9 остановили провайдер после штатного
завершения turn A, а v10 показал unbounded writer wait. Они сохранены как
диагностика и не заменяют v11.

Snapshot verifier: 348 файлов; актуальный digest указан в верхней сводке
этого документа.

CosyVoice3 `Fun-CosyVoice3-0.5B` проверен отдельно на CPU в
`G:\\AI\\CozyVoice`: русская инструкция отработала, но 36,2 секунды аудио
генерировались 126,7 секунды, RTF 3,50, а первый чанк пришёл только в конце
генерации. Поэтому CosyVoice3 не считается realtime или production TTS.
Результат, команда и ограничения находятся в
[COSYVOICE3_CPU_BENCHMARK.md](COSYVOICE3_CPU_BENCHMARK.md). В основном пути
остаётся TeraTTSv2; CosyVoice3 — изолированный opt-in backend для будущей
проверки клонирования/качества. Внешняя папка `G:\\AI\\CozyVoice` не менялась.

Этот результат не закрывает оставшиеся P0: cold/warm latency,
clean-install/manifest acceptance и источник исторического 503. Restart во
время inference и provider failure после durable native effect закрыты
отдельными live acceptance ниже.

В этом же срезе acceptance-скрипт restart-inference усилен: он теперь читает
durable action journal и требует ровно одну успешную запись
`HostOSWriter.write_file` для уникального marker. Наличие файла и совпадение
SHA без journal-проверки больше не считается доказательством отсутствия replay.
Live provider-failure прогон теперь принят в
`runtime/provider-failure-native-recovery-current-v11.json`; расширенные
crash-during-syscall и unattended recovery по-прежнему не приняты.

Попытка live-прогона 2026-09-08 на изолированном профиле
`restart-infer` (JAWL `8778`, Companion `2398`) остановилась до turn A:
локальный процесс на `11434` успешно отвечает на `/api/tags`, но возвращает
404 на `/api/chat`, `/api/generate` и `/v1/chat/completions`. В журнале JAWL
зафиксирован `model 'jawl-gemma4-it' not found`; owned baseline теперь явно
использует установленное имя `jawl-gemma4-it:latest`. Это provider/endpoint
несовместимость текущего Ollama-сервера, не доказательство сбоя checkpoint
recovery. Порты профиля освобождены; gate остаётся открытым до проверки
рабочего OpenAI-compatible или нативного Ollama chat endpoint.

Пробный live-гейт на Gemma-4 E2B Q8 через CPU `llama-server` дошёл дальше:
`restart_landed_midflight=true`, `restart_route_answered=true`,
`restart_agent_ready=true`, файл пережил restart. Первый реальный write был
выполнен после проверки отсутствия файла; последующий вызов после restart
вернулся как `idempotent no-op` и не изменил содержимое. Старый скрипт всё же
пометил прогон failed, потому что 120-секундный Companion timeout оборвал
медленный turn B до передачи SHA в final envelope и считал no-op второй записью.
Acceptance исправлен: профиль получил настраиваемый chat timeout, а journal
теперь разделяет `actual_write` и безопасный `idempotent_noop`. Evidence исходного
прогона: `runtime/restart-inference-acceptance-2026150854Z.json`; требуется
повторить финальный прогон с исправленным harness.

Актуальный R1-срез: owned snapshot `jawl-20260906-daily-v2` проверен как 348
файлов с digest `ec765835d627431d…`; полный gate указан в актуальной сводке выше. Это
не означает готовность live voice, semantic recall, native action или Live2D:
они остаются открытыми в активном goal.

Аудит 2026-09-06: HEAD `1bb3117` плюс незакоммиченные изменения
config/prompt/profile tooling. Статус продукта: **интеграционный прототип**.
Текущая очередь — [план восстановления](RECOVERY_PLAN.md) R1 → R4 и
[TODO](../TODO.md). Замысел — [PRODUCT](PRODUCT.md).
Прежняя хронология сохранена в Git; не использовать старые команды как
актуальный профиль без проверки конфигурации.

После этого gate исправлена гонка screen-event IPC и подтверждены targeted
screen/event tests (8 passed). Attachment capability также ограничена реально
поддержанными TXT/MD до выбора Vision/multimodal handlers.

Последний connected startup на временном OpenCode Zen profile успешно поднял
JAWL/Companion/Live2D, но provider вернул HTTP 429 `FreeUsageLimitError` для
startup и user turn. Поэтому сквозной LLM/voice acceptance остаётся открытой;
это внешний лимит, а не доказательство готовности контура.

Verifier также обнаружил generated logs/pyc в pinned snapshot после запусков;
они удалены как артефакты, не как исходный код. Snapshot снова проходит с тем
же digest `fd1bb8…`; дальнейшие диагностические Python-запуски должны включать
`PYTHONDONTWRITEBYTECODE=1`.

## Подтверждено в этом аудите

- Один live gateway turn завершился за ~48 с:
  `runtime/daily-live-64k.json`. Это частичная совместимость локальной LLM.
- `daily-memory-write.json` имеет `pass:true`, но сама сводка не проверяет
  содержание памяти. Пять последующих `daily-memory-recall*.json` failed:
  четыре timeout 240/360/180/150 с и затем SSE EOF.
- Последний browser voice report failed с Selenium timeout 120 с и нулём
  сохранённых turns. Три успешных разговора через основной UI не доказаны.
- Synthetic no-speech/акустические fixtures, ASR/TTS workers, responsive UI,
  native adapters и memory API существуют; текущий полный gate прошёл. Это всё
  ещё не заменяет физический микрофон, длительный soak и unattended recovery.
- Исходный 503 в `runtime/full-gate-20260905T101053Z.log:670` — неожиданная
  ошибка установки уровня 3. Объяснение через intentional emergency-stop
  fixture не подтверждает причину именно этой ошибки; расследование открыто.

## Регрессии, которые исправлять первыми

1. Глобальная `HostOS` blocklist удалена из owned snapshot; полномочия
   остаются у JAWL policy 0–3. Live native поручение ещё не доказано.
   Оригинальные adaptive rules восстановлены; live native поручение ещё не
   доказано.
2. Повреждённый context patch удалён, оригинальные adaptive rules JAWL
   восстановлены; v2 snapshot clean-verified (348 файлов, digest 3d74…).
3. `prepare_daily_profile.py` ведёт managed hash и backup при sync; профиль
   обновлён без конфликтов, preflight прошёл, отдельный cache создан.
4. Browser voice harness обходит capture/gate и штатный playback/аватар.
   Нужны смысловые проверки ответа, terminal status и реальный UI-путь.
5. Память нельзя свести к SQLNotes. Важные facts/preferences, рабочие notes,
   задачи, journal и sensory evidence должны сохранять свои роли.

## Что делать дальше

R1: native tools + patch delivery + effective config/model/context.
R2: bounded foreground, причина recall timeout, UI fact revise/restart/recall.
R3: три RU synthetic voice turns, один playback/avatar, latency и interruption.
R4: native поручение, postcondition, recovery, исходный 503, полный gate.

Сохраняются все требования: одна личность JAWL, VoiceMem-контекст, heartbeat,
HostOS 0–3/unattended, удобный Aero UI, 2D/OBS, LAN, будущий stream chat.
Vision отложен. Физический микрофон, реальный Live2D/OBS и ночная автономность
имеют отдельную незавершённую приёмку. Локальная LLM — рабочий кандидат;
её доступность в этом документальном проходе не проверялась.

## Goal и границы прохода

Формулировка goal зарегистрирована и активна. R1 уже изменил owned runtime,
config и profile tooling; protected репозитории не изменяются. Авторство старых
правок не выводится из дат.

## Latest runtime evidence — 2026-09-06

## P0 restart acceptance update — 2026-09-08

The managed restart path now passes active native inference recovery. Restart
landed midflight, JAWL became ready again, the durable sandbox file survived,
the final Companion envelope reported the exact disk SHA-256, and the action
journal recorded exactly one real `HostOSWriter.write_file` side effect.
Evidence: `runtime/restart-inference-acceptance-2026160037Z.json`.

The owned delivery contract was strengthened so completed native read results
cannot be replaced by a generic greeting or memory-derived answer. Earlier
failed runs remain historical diagnostics; they are not acceptance evidence.

P0-B provider-failure recovery is also accepted. A provider stream that fails
after a delta now terminates with one bounded error event carrying
`discard_deltas=true` and a non-speakable error envelope; an empty/invalid JSON
response follows the same terminal path. The next turn recovers on the same
gateway with a new correlation/turn ID. Evidence:
`runtime/provider-failure-acceptance-20260908T163148Z.json`.

## P0-B connected local acceptance — 2026-09-08

The missing Ollama model was repaired from the existing LM Studio GGUF using
`config/ollama/jawl-gemma4-it.Modelfile`; the prior Ollama manifests had no
blob weights and correctly failed closed with HTTP 404. A fresh managed profile
then passed the real connected slice: Companion `2367` → pinned JAWL `8767` →
Ollama `11434` selected `jawl-gemma4-it:latest`, and the correlated text lane
returned `CONNECTED_TEXT_OK` through the canonical
`HostTerminalMessages.send_message_to_terminal` delivery. The same session
executed native `HostOSWriter.create_directories`, `write_file`,
`HostOSReader.read_file`, `delete_file`, and `delete_directory`; the readback
SHA-256 matched the expected bytes and cleanup left no target. Evidence:
`runtime/connected-native-action-p0-local2-v4.json`.

The profile was stopped cleanly. This accepts the local text/native disposable
slice only; it does not prove voice, memory restart, GPU1-only placement,
barge-in, or production readiness. Port `8770` remains closed and FoxMCP on
`8765` was not modified.

The full repository regression is green after this change: `366 passed, 46
subtests passed`. Pytest collection is explicitly scoped to `tests/`, so
external Crane runtime tests and their optional model dependencies remain
isolated from the Companion gate.

The full regression is green (`353 passed, 28 subtests passed`). A fresh isolated profile reached JAWL startup and a local Ollama handshake, but the user native turn never emitted a correlated final event: the selected model produced repetitive or invalid tool calls. The profile was shut down; no production claim is made. Physical GPU1-only loading also remains unverified.
The owned profile now explicitly uses canonical `json_envelope` transport for local-provider compatibility. Startup verified the effective setting, but it did not yet produce a correlated Companion final, so this change is diagnostic progress rather than acceptance.
The owned delivery patch now prevents a correlated Companion turn from hanging when JAWL has no terminal tool action: it emits one final response or an explicit error. A real browser probe confirmed bounded failure in about 13 seconds; model compatibility remains open.
TokenRouter `/v1/models` is reachable, but bounded direct completions for GLM free/flash timed out (120 s/40 s). The endpoint is therefore not a usable connected baseline at this audit point.
Internal `[Observation]/[Reasoning]/[Reflection]` content is now rejected at the terminal event boundary and cannot be broadcast as user text. An earlier local-model probe failed to call the terminal skill; the later connected baseline passed terminal delivery and native side-effect, while voice/memory acceptance remains open.
Live browser validation confirms the safety behavior: an incompatible local model yields `native_turn_failed` and a bounded error envelope in about 15 seconds, without exposing its internal reasoning.
The source snapshot now includes an owned path-resolution correction: logical
`sandbox/...` paths resolve to the named profile sandbox injected into HostOSClient,
not to the immutable source tree. The earlier native side-effect probe exposed
this defect and failed closed; a fresh write/read/postcondition probe remains open.
An earlier malformed direct probe made `jawl-gemma4-it` appear not to emit an
OpenAI tool call; a corrected direct probe and connected profile now do emit and
execute terminal/native calls. A temporary Ollama server used to test
GPU1 affinity was stopped; the backend still placed model work on GPU0, so GPU1-only
isolation is not claimed. Port `8770` is closed; FoxMCP `8765` is intentionally
left running, and the main Ollama service remains on `11434`.
The corrected path-resolution probe is now green: JAWL used `HostOSWriter` and
`HostOSReader` through the connected Companion turn, verified `NATIVE_OK` with
SHA-256 `3ca5c1e51ffd4450d2df06df2cfa51436ab6233a88674c9df865cef291257254`,
and moved the disposable file to recoverable quarantine. Current snapshot digest:
`9e091dfd22b2e39ced592c7b02a40df94c3f659bfc3c24ddd7785fb9ea3b641b`.

The follow-up ASR comparison separates the remaining voice blocker: the Tera
reference sample transcribed successfully on temporary Qwen3-ASR (`61` chars,
RTF `0.077`), while all three regenerated synthetic question WAVs returned an
empty transcript. Their peak level was normalized, but that is not evidence of
speech intelligibility. The browser harness consequently stopped at
`wait_voice_message`; connected voice is not accepted yet. Temporary diagnostic
port `8985` and managed ports `8770/2367/8766/8984/9889` are closed.

### Latest connected voice evidence — 2026-09-06

After the launcher fail-fast fix, the integrated profile was rerun with both
`-StartLocalAudio` and `-UseVoiceMem` against local Ollama `jawl-gemma4-it`.
The fresh `runtime/browser-voice-e2e.json` passed 3/3 turns through real browser
capture, gate, Qwen3-ASR, JAWL, TeraTTS and playback/avatar events. It records
three unique session IDs, 15/22/21 audio uploads, one TTS request per turn and
three screenshots. This accepts the connected synthetic voice slice only; it
does not accept memory restart, native side effect, barge-in or full production.

### Current audit correction — 2026-09-06

The authoritative repository state is HEAD `5f5ec7f` (`jawl: update prompt
rules, delivery contract, settings for gemma4-it`), with the working tree
containing additional uncommitted runtime, documentation and test changes.
The pinned snapshot is `jawl-20260906-daily-v2` with digest
`9e091dfd22b2e39ced592c7b02a40df94c3f659bfc3c24ddd7785fb9ea3b641b`.
MiniCPM-o 4.5 is closed for the RU path and is documented as an opt-in EN
coprocessor only. The universal pre-integration protocol is
`docs/MULTIMODAL_MODEL_GATE.md`.

The next live run fixed the apparent Tera failure: Windows PowerShell had been
serializing the JSON request body with a non-UTF-8 code page. Sending explicit
UTF-8 bytes produced valid Russian WAVs; Qwen3-ASR accepted all three (`35/55/53`
characters, median RTF `0.132`). The real browser voice E2E then passed all three
turns through capture/gate, ASR, JAWL/local Gemma, Tera TTS and playback/avatar
events. Evidence is in `runtime/browser-voice-e2e.json` and three screenshots.
The report now records the final transcript text; the fake-file browser device
replays a short prefix during the capture tail, so transcripts contain a
bounded repeated prefix. This is a harness artifact to remove or separately
assert before claiming barge-in/duplicate-free production behavior.

Live memory API evidence is mixed: JAWL `remember` and `revise` succeeded with
revision 2 superseding revision 1, but a follow-up Russian chat under the same
local Gemma profile answered as though the user text were corrupted. The HTTP
client sent UTF-8 correctly; semantic recall and restart persistence therefore
remain unaccepted pending provider/JAWL context investigation.

### Conversation history persistence — 2026-09-07

The panel no longer loses the chat on Ctrl+F5: every dialog turn (text, voice,
and TXT/MD attachments) is appended to a bounded JSONL store
(`runtime/conversation.ndjson`, up to 4 MB / 400 turns) by
`TextGateway._record_turn` via `ConversationHistory` (mirrors the `AuditLog`
rollover pattern). `GET /api/history` (session-protected, 403 without the
browser cookie) returns the log; the panel calls it once in `bootstrap()` (not
in the refresh loop, so no duplicates) and re-renders prior turns. The store
survives companion restarts and page reloads, like the original JAWL console
log. Verified live: 403 without a session, a real chat turn round-trips into
`/api/history` and the JSONL file; gateway tests cover disk round-trip and the
store-over-memory precedence.

### Voice UX hardening — 2026-09-07

Keyboard/noise hallucinations are now filtered at the ASR boundary instead of
entering the dialog. `is_meaningful_transcript()` in `web.py` drops prompt-echo
("Transcribe the audio exactly as spoken."), single-character filler ("嗯") and
punctuation-only text; real short utterances («Ок», «Да», «Ладно») pass. A
filtered end returns `filtered: "asr_noise_hallucination"` with no JAWL turn, and
the panel surfaces a technical notice rather than silence (frontend
`handleVoiceResponses` + unified stop-path). Unit-verified against all known bad
and good cases.

A live draft transcript ("по словам") is now available: `ExternalASRService.draft()`
transcribes the buffered utterance without clearing it (2 s throttle, fail-soft),
exposed as `POST /api/voice/draft`. The panel polls it every 2.5 s while speaking
and renders "услышано: …" in a dash-bordered block under the mic status; it is
hidden on mic-off and cleared after a final utterance.

The integrated launcher is now idempotent for TTS/ASR workers: a relaunch reuses
a healthy already-running worker on its port instead of failing the whole
profile (previously a leftover worker aborted boot). Verified live: daily profile
fully up, `/api/doctor` all ready (jawl=online, voicemem=ready, asr=online,
tts=ok, avatar=ready).

The ASR filter was tightened after a live throat-clear produced «嗯嗯嗯。» which
reached the dialog and the companion answered it: CJK/Hangul in a Russian
transcription is now treated as an ASR language-switch artifact, and a
single-repeated-character utterance («ммм», «ааа», «嗯嗯嗯») is rejected. Test
matrix: the prompt echo, filler CJK, repeated single characters, and
punctuation-only text are all dropped; «Ок», «Да», «Нет», «Угу», «Ладно» and
normal sentences pass. Error envelopes are additionally normalized to
`speak: false` at the gateway boundary (native provider error state), and the
panel no longer voices error turns in any path (streamed chat, non-stream
`/api/chat`, and voice finals): deltas are kept out of streaming speech until
the final envelope confirms speaking is allowed.

### Memory acceptance correction — 2026-09-06

The follow-up investigation used the real Companion control route backed by
native JAWL, not a mock. A unique fact was created, revised to revision 2,
the JAWL agent was restarted, and the active revision was read back afterward.
The next Russian chat returned the exact revised value and a normal speaking
envelope. Evidence: `runtime/memory-restart-acceptance-20260906.json`.
This accepts the API/control-path memory slice. Browser-click coverage and a
clean profile without legacy conflicting preferences remain open; the fixture
was removed through canonical `forget`, so the daily profile was not left with
the acceptance fact.

### Native action acceptance correction — 2026-09-06

The live browser-session control route successfully proxied a disposable
filesystem action to native JAWL at access level 0: create directory, write a
marker, read it back with matching postcondition, then delete file and
directory. Every result reported `native=true` and `is_success=true`; the
target was absent after cleanup. Evidence:
`runtime/native-action-ui-acceptance-20260906.json`.
This does not yet prove voice-to-action binding, task checkpoint recovery or
interruption safety.

### Interruption and storage correction — 2026-09-06

The pinned JAWL SQL runtime now configures SQLite `busy_timeout=30000` and WAL;
the manifest was regenerated and `verify_jawl_snapshot.py` passed with digest
`9e091dfd22b2e39ced592c7b02a40df94c3f659bfc3c24ddd7785fb9ea3b641b`.
The first fresh live attempt was invalid because Ollama was not running and
returned a bounded provider transport error. After Ollama was restored, a real
concurrent Companion test passed: the first native turn was cancelled by the
second, the second returned a normal correlated final response, and no new
SQLite lock appeared in the fresh-process log. Evidence:
`runtime/interrupt-acceptance-20260906.json`.
This closes only the tested barge-in/storage slice; provider-failure recovery,
voice-to-native action, task recovery, restart stale-speech checks, and the full
production gate remain open.

### Clean-profile voice-to-native probe — 2026-09-06

The integrated launcher now accepts a validated `ProfileName` and prepares the
matching isolated JAWL profile instead of always reusing `daily`. A disposable
clean profile was started on `2371/8771/8767`; its real browser voice path
reached Qwen ASR and JAWL. JAWL selected native `HostOSWriter.write_file` with
the corrected `filepath` schema, then `HostOSReader.read_file`; the observed
file contained `готово`. This proves capability of the voice-to-native path,
but is not yet the required exact acceptance: Tera/ASR distorted the longer
command and the model also inspected a previous disposable file. Both files
were removed afterward. The strict voice-to-native postcondition and task
checkpoint/recovery therefore remain open.

The action-journal resource projection was then corrected in the owned JAWL
snapshot: logical `sandbox/...` path parameters now resolve against the
injected profile `JAWL_SANDBOX_DIR`, preventing source-looking lock keys. The
new manifest digest is `f241dca66e575a9efe759b80423f5928e1e2779c69a8ab396b07f93ef6158070`;
snapshot verification passes. A fresh native action rerun is still required
to promote this observability fix from focused verification to live evidence.

The post-change local gate is green: 332 unit/regression tests, 16 HTTP E2E
tests, browser interaction/responsive checks, synthetic microphone gate, and
`git diff --check`. This is a regression result only; it does not promote the
incomplete connected daily scenario to RC.

### Resource projection acceptance - 2026-09-06

A fresh isolated `resource-check` profile repeated the native disposable-file
scenario after the projection patch. All five operations were native and
successful; the read-back content was `RESOURCE_KEY_OK`, its SHA-256 was
`3fc0c93fceec267d1ff7514044862b64580a7fd9851b95a2c7cb6564d817fe4c`, and the
target was absent after native cleanup. The journal now records the profile
sandbox path, not the pinned source path. Evidence:
`runtime/resource-key-acceptance-20260906.json`.

The snapshot verifier remains green with digest
`f241dca66e575a9efe759b80423f5928e1e2779c69a8ab396b07f93ef6158070`.
The regression gate now redirects any JAWL default logging fallback into its
isolated `_regression-gate` profile. A fresh full run created no files in the
pinned snapshot; the snapshot remains immutable and verifier-green.

The Companion transport now carries one bounded `correlation_id` through chat
and voice events, gateway state, and native JAWL submission; native mode uses
that identifier as the JAWL `turn_id`. A gateway regression test and the full
local gate pass. A fresh connected voice run still remains necessary to prove
the identifier in the same browser response, native event stream, and action
journal artifact.

The attempted live correlation run on an isolated profile was not accepted:
the local `jawl-gemma4-it` provider produced an invalid-response retry and did
not reach a terminal browser voice response before the profile deadline.
Evidence is recorded in `runtime/correlation-voice-acceptance-20260906.json`;
this is provider compatibility evidence, not a correlation pass.

### Provider startup probe - 2026-09-07

The temporary local baseline was changed to `gemma-4-12b-obliterated:latest`.
Direct Ollama JSON probe passed in 6.51 seconds, but a clean JAWL profile then
stalled in the first startup ReAct call at 8,369 input tokens before its web
readiness/terminal response was available. The profile processes were stopped
after the bounded probe. Evidence:
`runtime/provider-startup-acceptance-20260907.json`.
This proves isolated provider JSON syntax only; it is not live JAWL or voice
acceptance.

### Strict voice-to-native correction — 2026-09-06

The second empty profile (`voice-native-strict`) used an ASR-safe Russian
command. Its real browser capture reached Qwen ASR and the same JAWL profile;
the native action journal records `HostOSWriter.write_file` for
`sandbox/проверка` with `готово`, `HostOSReader.read_file` returned the same
content and SHA-256, and the Companion browser-session route then invoked
native `HostOSWriter.delete_file`. The target was absent afterward. Evidence:
`runtime/voice-native-strict-acceptance-20260906.json`.
This closes the connected voice→native disposable postcondition slice. It does
not close task checkpoint/recovery, provider-failure/restart stale speech, or
the complete daily production gate.

### Launcher recovery hardening — 2026-09-07

An interrupted Codex run left two `coder-live` process trees serving the same
profile ports. The repository and pinned JAWL snapshot remained intact, but
requests could be routed to different Companion/JAWL pairs. The integrated
profile launcher now holds `runtime/instances/<profile>/run.lock` with
exclusive OS file sharing for its lifetime, preventing duplicate launchers;
the lock is released automatically when the launcher process exits. Snapshot
verification and the 14 gateway tests pass after recovery. JAWL readiness still
needs a stronger post-heartbeat acceptance signal before the full live gate can
pass. The launcher now waits, within a configurable bounded timeout, for the
current startup ReAct cycle's `Concluding cycle` marker before starting the
Companion; stale log entries are ignored using the current launch timestamp.
The isolated `readiness-check` smoke reached the real post-heartbeat readiness
marker and then exposed the next genuine failure: the temporary local coder
model returned an empty final answer on the second ReAct step after its bounded
retry. The launcher shut the profile down cleanly and released all ports.
Evidence: `runtime/readiness-smoke-20260907.json`. This is not a live voice
acceptance and the provider remains rejected for the production gate.

The follow-up `reasoning-check` profile passed through the fixed adapter:
JAWL/Companion returned a non-empty Russian response over HTTP 200 with the
requested correlation ID, speech flag, emotion and interruptibility. The
profile also stopped cleanly. Evidence:
`runtime/reasoning-effort-acceptance-20260907.json`. This accepts the local
provider for the text baseline only; voice, native side effects and restart
acceptance remain open.

The latest isolated `voice-acceptance-2` report records three successful real
browser-capture turns through Qwen ASR, JAWL and TeraTTS, with one consistent
session/correlation ID per turn and Live2D route screenshots. The report's
protocol acceptance is positive, but the surrounding process was stopped after
JAWL emitted an unrelated autonomous `HOST_TERMINAL_MESSAGE` memory cycle;
that cycle attempted the nonexistent `SVM_Preference` skill and generated
invalid action aliases. This is why the audible test phrase could begin and
then stop. The run is not promoted to full production acceptance until
autonomous-event isolation, first-audio timing and barge-in are proven.

The full local gate was rerun after the adapter and launcher changes with
output captured in `runtime/full-gate-after-reasoning-20260907.log`; exit code
was 0. This confirms no regression in the repository test/browser contract,
but it does not promote the text-only smoke to the required connected voice
acceptance.

### Simulated response streaming — 2026-09-07

The JSON-envelope transport does not expose token deltas for native JAWL
responses. The UI now simulates incremental speech after the envelope arrives:
the final text is split into bounded phrases and fed through one cancellable
TTS queue, while scheduled Web Audio sources share the same barge-in owner.
Voice audio chunks no longer call `speak()` independently, preventing a later
chunk from cancelling an earlier phrase. This is deliberately documented as
simulated response streaming, not token-level LLM streaming. The mock browser
regression passes; a fresh real three-turn voice acceptance remains required.
# UI memory refresh correction — 2026-09-07

The Companion memory panel now reads canonical records from its dedicated
`/api/jawl/memory` route instead of attempting to extract structured records
from `/api/jawl/overview`. Refresh requests are fail-soft, so a degraded
secondary panel cannot hide an available memory response. The new browser
harness also selects the actual `preference` option and cleans fixtures through
native `forget`.

Regression evidence: `runtime/memory-ui-regression-20260907.json`, 60 web/JAWL
tests, responsive browser E2E across six viewports. Live UI acceptance remains
open: create/revise/native-restart passed, but post-restart DOM recall did not
yet pass in the current local profile and is not claimed here.
# Native restart readiness correction — 2026-09-07

The Companion UI restart path now requests `wait_for_memory=True`. The native
agent must be running and the canonical structured-memory endpoint must answer
before the route reports readiness; the compatibility adapter default remains
the previous status-only behavior. The bounded readiness window is 180 seconds
for the managed profile because the observed local restart can take longer
than the heartbeat signal.

The live preference acceptance still needs one rerun against this lifecycle
fix. Earlier runs proved UI create/revise and native restart, but not the final
post-restart DOM recall; no production claim is made yet.
# Dashboard refresh single-flight correction — 2026-09-07

Dashboard refreshes are now single-flight with a queued follow-up. Bootstrap,
memory search, filters and action buttons cannot issue overlapping 13-endpoint
refresh batches while native JAWL is restarting. This preserves the existing
fail-soft endpoint behavior and prevents a slow secondary route from starving
the memory panel.

Evidence: `runtime/refresh-single-flight-e2e-20260907.json` and 61 web/JAWL
regression tests. The connected post-restart preference DOM acceptance remains
open until rerun against this change.
# Live memory acceptance result — 2026-09-07

Reruns `final6`–`final9` consistently proved browser create, browser revise,
`preference` kind, native restart and canonical cleanup. They did not prove
post-restart DOM recall: the Companion memory request remains unavailable or
does not render within the bounded acceptance window after native agent
restart. This is still a P0 blocker; the connected memory scenario is not
accepted and the goal remains open. Evidence is retained in the corresponding
`runtime/memory-ui-acceptance-20260907-final*.json` reports and profile logs.
# Restart readiness hardening — 2026-09-07

The managed UI restart readiness probe now requires two consecutive full
`adapter.memory()` projections, not merely agent status or one control-socket
reply. This targets the observed post-restart native-control queue race while
keeping JAWL as the sole memory owner. Companion/JAWL web regression remains
green at 61 tests; a fresh live acceptance is still required.

## 2026-09-07 persistence acceptance correction

The memory UI harness now has independent `write`, `verify`, and legacy `all`
phases. A real browser run created and revised a Russian preference through the
Companion UI, stopped the complete managed profile, started the same profile,
and recalled the revised value through the UI. Evidence:
`runtime/memory-ui-write-20260907.json` and
`runtime/memory-ui-verify-20260907.json`.

This closes semantic memory persistence across a full managed-process restart.
The native-agent restart lifecycle remains a separate open issue and is not
silently classified as fixed. Canonical JAWL memory ownership and API remain
unchanged.

Fresh connected voice acceptance passed 3/3 on `voice-connected-20260907`:
browser capture/gate → Qwen3-ASR → the same JAWL instance with local Ollama
LLM → TeraTTS stream → the single browser playback owner and avatar audio
state. Evidence: `runtime/voice-connected-e2e-20260907.json` and
`runtime/voice-connected-asr-20260907.json`. Each turn has one consistent
session and correlation ID, and the provider returned non-empty Russian
transcripts. This accepts the base connected voice slice only; barge-in,
voice-to-native action, task recovery, and provider-failure restart remain
separate gates.

The timing-enabled connected run (`runtime/voice-timing-e2e-20260907.json`)
passed all three turns and recorded the first real latency baseline: cold turn
to first audio was about 124.3 s (voice-end request about 120.5 s); warm turns
were about 11.6 s and 12.9 s to first audio. TTS headers followed the final
voice response in about 18–19 ms. This proves the path, but the cold-start and
JAWL/LLM latency are not production-realtime; fast-chat latency optimization
and explicit reasoning-policy verification remain required.

The full local regression gate completed after these changes: 336 unit/regression
tests, 16 local HTTP E2E tests, responsive browser interaction, synthetic mic
gate, Node mic-gate check, and `git diff --check` all passed. This is regression
evidence only; it does not promote mock/local checks to production acceptance.

The legacy native-agent restart acceptance also passed after the harness fix:
`runtime/memory-ui-all-20260907.json` proves UI create/revise, authenticated
JAWL agent restart, and revised-value recall. The earlier failure was a test
race caused by not awaiting the dashboard `refresh()` Promise, not a memory
loss. Native-agent restart is therefore accepted for this tested memory path;
broader stale-speech/task-recovery restart behavior remains open.

## 2026-09-07 browser interruption correction

The strict browser barge-in run is not accepted. It produced two successful
voice turns and two TTS streams, but the first `/api/tts/cancel` occurred after
the first playback window rather than between TTS start and the second voice
turn completion; the second Russian transcript also matched only partially.
The evidence is retained in `runtime/browser-barge-in-20260907-strict.json`.
A retry after aligning the frontend trigger with the calibrated microphone
gate could not reach the temporary Companion port because the isolated profile
did not finish startup; its report is
`runtime/browser-barge-in-20260907-strict-retry.json`. The frontend change is
limited to using the same calibrated gate for VAD and interruption detection;
no JAWL source or protected external repository was changed. True
playback-time interruption, cancellation of stale inference, and replacement
turn acceptance remain production gates.

## 2026-09-07 browser barge-in acceptance

A fresh integrated profile passed the strict synthetic browser interruption
gate: `runtime/browser-barge-in-20260907-strict-retry3-gap9.json`. The run
captured two Russian turns through browser mic/gate and Qwen ASR, opened two
TTS streams, started two WebAudio buffers, and observed cancellation after the
first buffer had started but before the second `/api/voice/end` completed.
Both expected transcript markers matched. The calibrated microphone gate is
now shared by VAD and barge-in detection. This is a real playback interruption
acceptance for the simulated-after-envelope TTS path, not proof of token-level
LLM streaming or restart-safe stale-task recovery.

The Companion restart soak also passed 3/3 cycles with 15 health samples,
graceful shutdowns, no forced stops and no leaked control/presentation ports.
Evidence: `runtime/restart-soak-20260907.json`. This covers the standalone
Companion lifecycle only; provider-failure recovery and JAWL task/speech
checkpoint recovery remain separate.

The post-barge-in full local regression gate also completed successfully:
336 unit/regression tests, 16 HTTP E2E tests, responsive browser interaction,
synthetic mic gate, Node mic-gate check, snapshot checks and `git diff --check`.
The intentionally negative short/noise ASR fixture remains diagnostic output
inside the gate; it is not used as connected voice acceptance evidence.

## 2026-09-07 connected voice-to-native correlation acceptance

A fresh managed profile passed the connected browser voice→native action gate.
The browser report is `runtime/voice-native-correlation-20260907.json`; the
consolidated evidence is
`runtime/voice-native-correlation-acceptance-20260907.json`. The same
correlation `turn-voice-1788743134288-1` appears in browser transport and in
JAWL's durable action journal as `companion_turn_id`. JAWL executed native
`HostOSWriter.write_file`, `HostOSReader.read_file`, and a second disposable
write; the readback SHA-256 matched, and both targets were later removed by
native recoverable cleanup. The pinned snapshot verifier passed with digest
`aa7677bca6b03e59f859a3eb0c909530f80acb66eb538b86281dc600755db6ae`.

This closes the connected voice/native/postcondition/correlation slice. It does
not close exact ASR byte fidelity, provider-failure task checkpoint recovery,
or duplicate-side-effect behavior across restart.

## 2026-09-07 restart-safe speech guard

Companion now exposes a process-scoped, non-persistent `runtime_instance_id` in
`/api/health`. The browser probes this lightweight endpoint every two seconds.
When the identifier changes, it stops local WebAudio, clears the active
simulated-stream session and requests backend cancellation best-effort; local
playback stops even when the old backend is already unavailable. This preserves
the existing Companion playback design and does not replace JAWL's
task/checkpoint ownership. Web tests: 36 passed. Integrated restart during
active JAWL inference, checkpoint recovery and duplicate-side-effect proof
remain open.

## 2026-09-07 native duplicate-side-effect finding and guard

During a real managed local-Ollama profile, a single disposable voice/text
request caused the model to redeclare the same `HostOSWriter.write_file` action
three times after the first write had already succeeded. The file content stayed
correct, but this was not acceptable exactly-once evidence. The correction is in
the native JAWL writer: an exact UTF-8 byte match now returns an explicit
idempotent no-op instead of replacing the file again. A direct native runtime
probe verified first call `True`, second call
`True (idempotent no-op; requested content already matched)`, and unchanged
content. Snapshot verifier is green with digest
`3a15a6b057f56eaa28a186e0b46525a909220004f7a5e5c4e6ba8f6fa457a8f2`.

This guard covers repeated identical writes. It does not yet prove exactly-once
semantics for every native tool, uncertain effects after process death, or
durable Goal checkpoint recovery; those remain open acceptance gates.

## 2026-09-07 native Goal checkpoint recovery

The pinned native `GoalManager` was exercised with a durable ledger checkpoint,
an injected provider-failure cycle, and a fresh manager instance. The goal stayed
`active` with `pending_work=true`; restart restored phase `write`, next action
`read file`, checkpoint summary, and advanced the lane epoch to prevent stale
continuation. Evidence:
`runtime/native-goal-provider-failure-recovery-20260907.json`.

This accepts the native persistence/recovery invariant, not the full live gate:
provider failure during a real managed voice turn with an uncertain native
effect still requires process-level evidence and postcondition reconciliation.

## 2026-09-07 managed native restart probe

The managed profile `recovery-live2-20260907` also passed the Companion's
normal `/api/jawl/restart` path: the old native agent stopped, a fresh native
agent started, and readiness was reported only after the new instance was
available. A subsequent real `HostOSWriter.write_file` followed by
`HostOSReader.read_file` returned the expected 16-byte content and SHA-256.
This is evidence for the owned restart/readiness path and post-restart native
operation, not for interruption in the middle of an uncertain side effect:
the write began after the restart had completed. The process-level
crash/uncertain-effect acceptance remains open and is intentionally not
marked production-ready.

## 2026-09-07 GoalSkills provider compatibility finding

A fresh managed profile was given an explicit Russian long-running-goal
request. The selected local Gemma provider produced a short terminal-message
confirmation but emitted no `GoalSkills.create_goal` action and persisted no
active goal. The request therefore cannot be used as checkpoint-recovery
evidence; the response is treated as a model/tool-calling failure, not as a
successful goal. No Companion-side task owner or automatic goal shim was added:
JAWL remains the sole owner of goals. A provider/model that reliably emits the
canonical GoalSkills calls is required for the live goal recovery gate.

## 2026-09-07 live GoalSkills restart acceptance

After restoring the canonical adaptive context namespaces, a fresh managed
profile completed the real GoalSkills path: `HostOSWriter.write_file` created a
disposable artifact, `GoalSkills.create_goal` persisted an active goal, and the
owned `/api/jawl/restart` route returned ready. The new JAWL instance restored
the same goal with `lane_epoch=2`. A follow-up cycle called
`HostOSReader.read_file`, observed SHA-256
`d0ba3bfe7752501ec1be0e55abd09354148b6038feaf08b6a8b741532c04cc38`, and
called `GoalSkills.update_goal(status=complete)`. Evidence:
`runtime/goal-restart-live-acceptance-20260907.json`.

This closes the live goal creation/restart/recovery/postcondition slice. It
does not close crash during an uncertain native side effect or blanket
exactly-once semantics for arbitrary tools.

## 2026-09-07 post-context live voice gate

After the adaptive-context correction, a fresh managed profile passed all three
Russian synthetic browser capture turns through Qwen3-ASR, the same JAWL/local
LLM, TeraTTS and the shared browser playback/avatar path. All three expected
transcripts matched, each turn had one consistent correlation ID, and the
native voice endpoints returned successfully. First-audio timings were
13,883 ms, 22,507 ms and 49,427 ms; the third turn remains a latency blocker,
not a transport failure. Evidence is the refreshed
`runtime/browser-voice-e2e.json` with URL `http://127.0.0.1:2396`.

An earlier attempted run without `-StartLocalAudio -UseVoiceMem` produced
503s because ASR/TTS were intentionally unconfigured; it is recorded as a
harness configuration failure, not product acceptance.

## 2026-09-07 context-budget latency experiment (rejected)

A temporary reduction of the managed context budget to 42,000 dynamic chars,
10,000 skill chars and 6,000 provider-block chars preserved the 3/3 voice
correctness gate but measured first-audio at 24,787 ms, 24,829 ms and 43,117
ms. The model also emitted more invalid invented skill names. The change was
reverted; no quality regression is retained. Latency work therefore requires
provider/model or request-path optimization, not blind context truncation.

## 2026-09-07 stale terminal namespace compatibility

The live logs showed one local model spelling the canonical terminal delivery
skill as `HostOSJournalMessages.send_message_to_terminal`. JAWL now maps this
single unambiguous stale spelling to
`HostTerminalMessages.send_message_to_terminal` through its existing alias
resolver. It adds no skill or execution path and still uses the native guard,
journal and policy. Ambiguous inventions such as `validate_test_file` remain
rejected rather than being silently mapped to an unsafe operation.

## 2026-09-07 restart-during-inference gate progress and provider finding

A new strict harness `scripts/run_restart_inference_acceptance.py` drives the
remaining P0 scenario on an isolated `restart-infer` profile: turn A performs a
native disposable write+read, the managed `/api/jawl/restart` lands mid-flight,
turn B must inspect the resource and report unforgeable evidence (SHA-256
compared against the on-disk file).

Facts established across five live runs (evidence
`runtime/restart-inference-acceptance-2026*.json`):

- The restart route reliably lands mid-flight (8 s trigger), reports
  `agent_ready=true` after two memory projections, and the uncertain native
  side effect is durable: in two runs the pre-restart `HostOSWriter.write_file`
  survived the restart and the on-disk content matched the unique marker.
- A real JAWL defect class was reproduced and fixed in the owned snapshot: the
  local model repeatedly re-sent the same successful
  `HostTerminalMessages.send_message_to_terminal` action, exhausting the 15-step
  ReAct budget before any terminal conclusion (five consecutive startup/readiness
  failures). The owned `l3_agent/react/loop.py` now keeps the last executed
  action batch and, when the model repeats an identical batch that had fully
  succeeded, concludes the cycle without re-execution and without a synthetic
  completion ("Duplicate successful action batch. Concluding cycle without
  re-execution."). The managed launcher readiness marker now accepts this
  legitimate conclusion. Snapshot verifier green, digest `403420ad…`.
- Remaining blocker (provider/model, not JAWL): the selected local
  `gemma-4-12b-coder-fable5-composer2.5-v1` cannot pass the inspection step
  honestly. Observed twice: it reported the marker from conversation history
  while the file did not exist (run 3), and it reported a SHA-256 without
  calling `HostOSReader` (run 4: fabricated hex; run 5: ignored the question).
  The on-disk postcondition probe correctly rejects these. Production
  restart-inspection therefore stays gated on a provider/model that verifies
  resources instead of trusting history; `jawl-gemma4-it` remains the accepted
  text baseline and is restored as `main_model` in `config/jawl/settings.yaml`.

The isolated `restart-infer` profile was stopped after the runs; the daily
profile and its web UI remained healthy throughout.

## 2026-09-07 — Perception: Russian ASR swapped to faster-whisper large-v3-turbo (int8 CPU)
Decided/actioned:
- Root-cause of the "фразы до конца не записываются" complaint: client draft/finish
  mechanics never consume the audio buffer; the tail loss came from the weak
  Qwen3-ASR-0.6B (0.6B) sidecar truncating/stalling on final phrases.
- Replaced it with faster-whisper large-v3-turbo (CTranslate2) served by
  `scripts/asr_whisper_server.py` (stdlib HTTP, OpenAI-compatible
  `/v1/audio/transcriptions` + `/health`), same 127.0.0.1:8984 slot the
  companion already polls — the live companion needed no restart and now reports
  `asr: online` in /api/doctor.
- Weights: MSPR systran/faster-whisper-large-v3-turbo is gated (401); used
  `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (== deepdml oid
  b5de55e781fd93b7...; model.bin size 1617884929, sha256
  e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da) placed at
  `runtime/models/whisper-turbo`. huggingface_hub (even HF_HUB_DISABLE_XET=1)
  returns empty blobs for this repo; downloaded via direct (no-proxy)
  range-slices 110-250MB -> merged + sha-verified.
- The repo ships no vocab.json; ctranslate2 4.8.x refuses to load until
  `vocabulary.json` (from deepdml mirror, 1068114 B) is present.
- Bench on synthetic RU TTS wav (21.1s): latency 3.44s = ~6.1x realtime on CPU,
  full Russian text with proper punctuation, no tail loss.
- launcher `scripts/run_integrated_profile.ps1`: `$whisperModel` now the local
  dir, ASR branch spawns whisper server (`.env` unused), healthy leftover ASR
  worker on 8984 is reused on relaunch (manual and launcher-managed are
  interchangeable).
Open:
- Full launcher-boot path with --asr-model whisper-turbo will be exercised on
  the next natural profile restart.
- Vision VLM bench (SmolVLM2-500M / Namo-500M / Moondream2) re-queued; weig-hts
  partially downloaded; resume after ASR milestone.

## 2026-09-07 — Perception continuation: vision bench results (SmolVLM2)
- vision-venv: + torchvision 0.29.0+cpu, num2words, (moondream pip = cloud client, not used).
- Weights via direct (no-proxy) deterministic range-slices (~110-250MB) at ~2.6MB/s:
  runtime/models/vlm/{SmolVLM2-500M-Instruct(2030MB sha ok by size), Namo-500M-V1(1908MB), moondream2(3.85GB bg, finished)} + small configs.
- huggingface_hub snapshot is broken for these repos via proxy (0-byte blobs) - slice path is the working method.
- bench `runtime/vision-smoke/bench_vision.py --model smol|namo|moondream`; results.json updated.
  SmolVLM2 quirk: image_seq_len=64 (pooler tokens per subimage) + size longest 2048.
  ~8s/frame CPU, conditional (layout/ambient only, weak Cyrillic OCR at 500M).
- Namo/moondream blocked in transformers 5.16.1 (no model classes; no usable pip pkg);
  recorded as pending in MULTIMODAL_MODEL_GATE.md.

## 2026-09-07 — Vision round 2: moondream2 + namo run on CPU
- moondream2: remote-code package in model dir; manual HfMoondream load (0 missing
  keys); query() reads partial RU ("Прибыль 1 240 500 рублей"). ~11s/frame.
- Namo: clone -> runtime\vlm-namo\namo (3 compat patches: register try/except,
  repo AIMv2Config for tower, hidden_size=1024). Added deps einops/loguru/
  termcolor/timm/peft/requests. Reads digits/dates of form; fast 4.4s/frame.
- results.json now has smolvlm2-500m + moondream2 + namo-500m (bench --model).
- CPU RU OCR verdict for all three: fragments yes, reliable extraction no.
  -> OCR-only rejected; VLM = ambient/layout. Tesseract RU is fallback for text.
## 2026-09-08 P0 managed-profile and route-latency gate

The clean managed profile `clean-manifest-20260908` passed preparation and
preflight against the pinned 348-file JAWL snapshot. The source manifest and
profile source identity matched digest
`8f6dfc5f31ad31ee98b11ec6d1a800ff95f52528f58ab3de50efb59955b1a8c8`, and the
embedding cache was ready. An installed wheel also served control and
avatar/OBS frontend assets from a separate working directory; this is
packaging evidence, not a live-provider release claim.

The real connected route `Companion 2401 → JAWL 8781 → Ollama 11434` passed two
native acceptance turns on `jawl-gemma4-it:latest`: first route turn after
profile readiness `5.085 s`, second consecutive turn `5.944 s`. Both correlated
the final envelope and completed native disposable write/read/cleanup. The
first turn is only an application-route cold slice because the provider/model
had already passed JAWL startup heartbeat; provider cold-load, first-audio,
streaming TTS, microphone and barge-in latency remain open.

Evidence: `runtime/latency-gate-20260908.json`,
`runtime/clean-install-acceptance-20260908.json`.
### Current acceptance correction — 2026-09-09

The first unattended report is a pre-fix negative diagnostic. The current live
functional rerun passed one real cycle: native ROOT lease, write/read, Goal
completion, independent SHA/postcondition, and native cleanup. Evidence:
`runtime/unattended-goal-soak-live4-20260909.json`. The long 8-hour soak and
crash/provider reconciliation remain open.

### Current unattended correction — 2026-09-09

The two-cycle live6 report is negative evidence, not an acceptance: cycle 1
passed, while cycle 2 attempted native `GoalSkills.update_goal` with an
unresolved action and JAWL correctly rejected completion. The acceptance
harness now treats provider-reported `failed` as terminal and explicitly
requires direct Goal Protocol v2 `state=done` for this disposable task. The
native GoalSkills implementation remains canonical and unchanged. A fresh
two-cycle run is required before unattended heartbeat can be called accepted.
