# TODO — путь к работающему компаньону

Synthetic voice robustness slice (P0-C foundation) landed: `ASRNoSpeech` is now
a first-class outcome — `ExternalASRService.finish` reports `no_speech`, the
`/api/voice/end` endpoint returns a neutral empty transcript, and swappable
`clock` injection makes TTL-eviction/disconnect tests deterministic offline.
`scripts/make_synthetic_audio_cases.py` derives 12 deterministic acoustic cases
(tempo/pause/quiet/faint/noise/phrase-end/consecutive) with a `cases.json`
expectation manifest consumed by `run_asr_profile --expects`, which now
distinguishes "missing required speech" from tolerated noise-floor no-speech.
`scripts/check_mic_gate.mjs` verifies browser backpressure at
`MAX_PENDING_AUDIO_CHUNKS` (8). Live ASR acceptance of the matrix
(`scripts/run_synthetic_cases_live.ps1`, local Qwen3-ASR-0.6B) is PENDING an
ASR worker run. This slice does NOT yet deliver Partial ASR streaming,
cancellable streaming TTS, semantic barge-in or browser/device interruption E2E —
those remain the accepted P0-C exit criteria.

Local LLM reality check for the next live run: LM Studio `127.0.0.1:1235`
answers but demands an API key (401); Ollama `127.0.0.1:11434` answers without
auth and hosts `gemma-4-12b-obliterated:latest` (and a 12B coder variant). Owned
JAWL can target it via `LLM_API_URL=http://127.0.0.1:11434/v1` +
`main_model=gemma-4-12b-obliterated:latest` (no credential needed for loopback).
No provider live turn is claimed yet.

Current UI acceptance is OPEN: see [the six-point audit](docs/UI_ACCEPTANCE.md).
Latest browser voice attempt (2026-09-06) reached the live integrated profile,
and the user heard the generated error speech, but the harness failed with a
120-second Selenium HTTP read timeout while the local CPU/OpenCode turn was
still running. This is not accepted as a voice E2E pass. The earlier 30-second
async-script limit was raised to 180 seconds; the next fix must bound the
application turn below the driver limit and preserve cancellation evidence.
Memory audit correction: `ambient episode` is only the bounded T1/T2 background
candidate. It is not the canonical JAWL episodic/tick memory. Before calling the
memory library production-ready, expose the native JAWL collections (tasks,
notes, facts/preferences/traits/summaries, mental states, drives, hypotheses,
ticks/timelines and daily journal) plus VoiceMem heartnotes, response experience
and audio evidence as distinct views, with one ownership/consolidation contract.
Voice parity remains OPEN: streaming/cancellation seams exist, but reliable
behavior is currently half-duplex finalized turns. P0-C still needs partial ASR
delivery, cancellable native JAWL streaming, first-audible timing, semantic
barge-in classification and browser/device interruption E2E; RMS-triggered TTS
cancellation alone is insufficient.
Responsive browser checks passed at six explicit viewport sizes; LAN support
is the current implementation slice. Memory library now has layers/search/edit/
forget UI, but live recall is still unaccepted. Slash menu, binary media, and
the live daily conversation remain incomplete. Audio lamps now follow actual
WebAudio amplitude/gate; synthetic tone/silence browser check passed.

Latest full-gate capture after the browser voice and memory-documentation
changes:
`runtime/full-gate-20260905T212025Z.json`, exit code 0; paired log is the
authoritative detailed record with 308 ordinary tests and 16 HTTP E2E tests.
The earlier `190000Z` and `181942Z` passes and transient
`181650Z` failure remain preserved as historical diagnostics.

Added `scripts/run_browser_voice_e2e.py`: with explicit `--live` and three WAVs
it sends PCM from the browser origin through Companion ASR, closes each turn,
requests TTS and waits for browser playback. Without a live profile it refuses;
`runtime/browser-voice-refusal.json` records that no false pass was claimed.

The local launcher now accepts `-RunBrowserVoiceE2E` and forwards three
synthetic fixture WAVs into that browser driver after owned JAWL/ASR/TTS/
VoiceMem startup. A lifecycle-only run passed at
`runtime/local-bonsai-integrated-profile.json`; it remains startup-only because
the browser voice switch was not used.

Current owned-runtime preflight (2026-09-05) passes with
`embedding_cache=ready` and `missing=[]` via
`scripts/preflight_jawl_runtime.py --allow-missing-model`. No LLM credential
is currently present in process, user, or machine environment, so a live
provider run is intentionally not claimed or started; the next live run must
inject `LLM_API_KEY_1` through the process environment only.

Provider connectivity probe (2026-09-05) reached
`https://opencode.ai/zen/v1/models` with HTTP 200; the catalog currently
includes `big-pickle` and `deepseek-v4-flash-free`. This proves endpoint
reachability only, not authenticated completion or tool compatibility.

UI direction slice (2026-09-05): the overview is now centered on one chat;
duplicate buttons under the avatar were removed. The composer has attachment,
emoji, slash-command and microphone controls; TXT/MD attachments are included
in the actual text request, while binary media reports an explicit capability
error. Microphone selection is persisted per browser, and vision/initiative
controls are moved to System as lower-frequency settings. Browser render smoke
passed with evidence under `runtime/browser-evidence/20260905T195242Z/`; browser
interaction E2E also passed in explicit mock-brain mode with screenshot evidence
under `runtime/browser-evidence/interaction/`. These are UI checks, not live
provider acceptance.

Latest extended live attempt (2026-09-05) is deliberately not accepted as a
three-turn pass: question-01 completed end-to-end in 1.617 s (ASR 0.373 s,
JAWL response 0.381 s, TeraTTS 0.837 s), correlation
`audio-profile-52faa6e52c4f46e5b72742ece4b1f6df`; question-02 reached one
`VOICE_TURN` and one response but the local Qwen ReAct cycle took 120.768 s,
exceeded the 8 s bound, and no TTS was produced, correlation
`audio-profile-c26bf42f9ff949f4a102697dba9ed057`; question-03 did not start.
JAWL logs also show the model emitting unavailable `HostOSTerminal.*` skills.
P0 remains: make the model/tool catalog contract authoritative and bound a
single user-turn so an invalid tool plan cannot stall the voice pipeline.
The owned JAWL snapshot now resolves the two observed historical
`HostOSTerminal.*` spellings to the native `HostTerminalMessages.*` skills
through the normal registry/guard path; this is covered by targeted tests and
the refreshed source manifest. A new live three-turn run is still required.
An isolated follow-up audio profile reported ASR -> response -> TeraTTS in
2.307 s (`runtime/alias-live-q2.json`, correlation
`audio-profile-50a0f0262b6b448688f935283f4102bf`), but the JAWL log did not
record the alias call before shutdown, so this is supporting evidence only.

Native JAWL HostOS primitive slice is live-verified against the owned
console: create directory -> write disposable marker -> set metadata -> track
and inspect -> untrack/delete. Every action returned `HTTP 200`, `native=true`,
cleanup was confirmed, and correlation is
`native-action-1783f5b355ca457c836e07625d226c94`. Evidence:
`runtime/native-action-live-20260905202420.json`. This proves the native
primitive and cleanup, not yet a model-originated UI/voice task.

JAWL web chat delivery now waits for its asynchronous terminal bridge to reach
`connected` before sending. A fresh live POST returned HTTP 200 with a user
sequence instead of 409; the short probe ended before the model response, so
full foreground completion remains open.

The UI memory contract is now live-verified end-to-end: a unique preference
was written via Companion `/api/jawl/memory` with `native=true`, found before
restart, the native `/api/jawl/restart` returned `agent_ready=true`, and a
bounded follow-up read found the same value after restart. Evidence:
`runtime/live-ui-memory-restart-20260905.json`. The first immediate read was
too early and was repeated only after readiness; it is not hidden as success.
An intervening gate exposed a transient fixture race; the focused E2E passed
on repeat and the immediate full-gate rerun passed. Both artifacts remain in
runtime history.

Model-originated task attempt (2026-09-05) remains failed/unaccepted:
owned JAWL was occupied by its startup heartbeat, both chat submissions
returned `HTTP 409 Conflict`, and the subsequent local Qwen call reached the
provider timeout/retry boundary. P0 action: give foreground user turns a
bounded scheduling lane and cancel/defer heartbeat work at a safe boundary;
never hide the conflict with blind retries.

First real local core/audio run (2026-09-05): Gemma-3-1B GGUF through
llama.cpp started owned JAWL; with VoiceMem, Qwen3-ASR and TeraTTSv2, one
synthetic Russian WAV completed ASR -> JAWL -> TTS: 50 chunks, one VOICE_TURN,
one response, VoiceMem queued, and a 44.1 kHz WAV. Evidence:
`runtime/local-live-audio-pipeline.json`, correlation ID
`audio-profile-ebab346687a24819b7a75d72bb02bce6`. A later turn was interrupted
by the short run window and is not counted as accepted.

Local model compatibility update: Qwen3-VL-2B-Q4_K_M (text-only, no Vision
path enabled) produced a valid JAWL terminal JSON with empty actions during
the real heartbeat and completed its ReAct cycle. Gemma-3-1B produced invalid
tool JSON; Bonsai ternary GGUF is unsupported by the available llama runtime
(`invalid ggml type 142`). A complete user-turn and native task still need a
longer live run window.

Integrated launcher credential handoff was corrected: `LLM_API_KEY_1` is now
passed to the owned JAWL child only through process environment, never through
arguments or logs. Safety regression coverage passed (12 targeted tests).
The local Bonsai integrated run could not be executed in this shell because
the command policy rejected the secret-shaped environment assignment; this is
an execution limitation, not live evidence.

503 investigation: the current full-gate 503 is intentional fixture behavior
(`_UnavailableJawlControl`) for fail-closed native emergency-stop testing; the
test asserts `ok:false`, HTTP 503, and the local emergency latch remains set.
The historical external QWB 503 was separately identified as
`upstream_waf_challenge`; neither case permits blind retries of a control
operation. A live-provider 503 trace remains unverified until that provider is
configured.

The live audio profile now emits a per-run correlation ID and stage timings
(session bootstrap, ASR upload, final response, and TTS completion) so the
future browser/JAWL scenario can be audited as one trace.

Real browser interaction evidence (2026-09-05) is saved in
`runtime/browser-interaction-e2e.json` and
`runtime/browser-evidence/interaction/browser-interaction-control.png`:
Edge loaded the UI, changed/persisted the gate, submitted a chat message, and
observed the rendered reply. This is an isolated `mock_brain` acceptance slice;
it does not prove live JAWL/LLM, memory recall, browser ASR, or TTS playback.

Live local audio chain evidence (2026-09-05): `scripts/run_synthetic_questions_live.ps1`
generated three Russian question WAVs with TeraTTSv2 and transcribed them with
the local Qwen3-ASR-0.6B CPU server. Report: `runtime/synthetic-questions-profile.json`;
status passed, median final-utterance RTF 0.111, all three results non-empty.
This is not yet browser microphone capture, streaming partial ASR, JAWL+LLM,
TTS playback, interruption, or avatar acceptance. The harness builds Russian
utterances from Unicode code points because Windows PowerShell 5.1 can decode
UTF-8 source without a BOM incorrectly.

`scripts/run_integrated_profile.ps1` now accepts `-StartLocalAudio` and owns
the local TeraTTSv2/Qwen3-ASR worker lifecycle, health checks, and Companion
audio endpoint wiring. A live integrated run still requires the external LLM
credential and remains unaccepted until the full scenario is executed.

Full gate refreshed after loopback security integration: accepted evidence is
`runtime/full-gate-20260905T190000Z.json` (`exit_code: 0`), with 301 non-E2E
and 16 HTTP E2E tests, compile/syntax, synthetic mic, Node and diff checks.

Loopback token rule change passed web + local E2E regression: 52 tests. The
full gate was subsequently refreshed: `runtime/full-gate-20260905T190000Z.json`
(`exit_code: 0`).

Loopback JAWL console integration no longer creates an ephemeral token that
could leak into console logs: Companion permits an empty token only for
loopback JAWL URLs, while non-loopback URLs still require an explicit token.

Real local TeraTTSv2 CPU profile passed three Russian synthesis requests;
report: `runtime/tera-live-profile.json`. Median RTF was 0.162 and p95
complete response time was 0.589 s. This proves the local TTS worker contract,
not streaming first-audio latency or the full JAWL voice scenario.

Browser render evidence (2026-09-05): installed Edge passed the render smoke
and saved `runtime/browser-evidence/20260905T154359Z/control.png` and
`avatar.png`. Both were visually inspected; the avatar remains a 2D fallback,
not real Live2D/OBS acceptance.

The integrated launcher now fails before opening JAWL when `LLM_API_KEY_1` is
absent, making the live-provider prerequisite explicit and deterministic.

Current live blocker (2026-09-05): the integrated lifecycle probe reaches the
JAWL console, but the agent exits during provider validation because
`LLM_API_KEY_1` is absent. The launcher now reports this startup failure and
its log instead of mislabeling it as a missing terminal port. No credential is
stored in the repository.

## Latest P0-A slice (2026-09-05)

- [x] Pinned owned JAWL source snapshot and Python 3.11 runtime verified:
  `pip check`, import graph, and prompt/config validation pass.
- [x] Added idempotent `scripts/prepare_daily_profile.py`. It stages prompt
  assets, the owned `SOUL.md`, config, data, logs, and sandbox under
  `runtime/instances/daily` without overwriting existing files.
- [~] Added `scripts/run_daily_profile.ps1` for the separate JAWL console on
  `8770`; Companion control remains `2367`. Live
  provider credentials, browser E2E, and the complete daily scenario remain
  open acceptance items below.
- [!] First real owned-JAWL startup smoke reached SQL/vector initialization but
  spent its bounded window downloading the embedding model. Add a preflight
  warm-cache/readiness probe and only accept startup after the vector backend
  is ready; the smoke was stopped and is not evidence of a failed JAWL core.
- [x] Warm-cache startup now reaches `JAWL started successfully`; stop-file
  shutdown completed with `Shutdown complete` and PID cleanup in 60 seconds.
  Added `preflight_jawl_runtime.py`; cache readiness is explicit. Provider
  connectivity remains intentionally unproven in this smoke.
- [x] Saved accepted full-gate evidence using the compatible capture wrapper:
  `runtime/full-gate-20260905T183500Z.json` (`exit_code: 0`), with paired log
  recording 301 non-E2E and 16 HTTP E2E tests and auxiliary checks.
- [~] Current full gate passed 301 non-E2E tests, 16 HTTP E2E tests, compile,
  synthetic mic, Node and diff checks. The ad-hoc capture wrapper used an
  unsupported PowerShell `Get-Date -AsUTC` flag, so its new metadata filename
  was not accepted; use a compatible timestamp wrapper on the next gate and
  do not treat this run as a replacement for the saved evidence artifact.

Актуально: 2026-09-05. Цель — [PRODUCT.md](docs/PRODUCT.md).
План ниже заменяет прежнюю очередь «release blockers» и повторяющиеся отчёты.
История сохранена в [архиве](docs/history/2026-09-05-before-product-audit/TODO.md).

`[ ]` не принято; `[~]` код/частичное evidence есть, сценарий не принят;
`[!]` нужно решение/действие владельца; `[x]` выполнена ровно указанная
проверка. Наличие скрипта, поля или HTTP 200 не закрывает функцию.

## Активная цель — первый связный ежедневный сценарий

Приоритет: P0-A → P0-B + P0-C в одном воспроизводимом профиле.
Результат должен быть доступен из обычной панели приложения.

1. Зафиксировать совместимую поставку JAWL и собственные config/data/log/cache;
   подключить manifest к launcher, readiness и остановке всей платформы.
2. Провести минимум три русских синтетических аудиовопроса через браузерный
   путь ASR → тот же JAWL с реальной LLM → TTS → один playback/аватар.
   Измерить cold/warm задержки по стадиям; физический микрофон принять отдельно.
3. Сохранить факт/предпочтение, исправить его через панель и доказать влияние
   на следующий ответ и recall после перезапуска без второй памяти личности.
4. Из панели/голоса выполнить поручение через native JAWL: изменить disposable
   файл/состояние тестового приложения, проверить результат и показать артефакт.
5. Проверить interruption, provider failure и restart: нет повторного действия,
   устаревшей озвучки или потерянной задачи; итог и причина отказа видны в UI.
6. Пройти browser interaction E2E, сохранить изображения ключевых состояний,
   полный gate и отчёт связанного сценария с версиями и correlation IDs.

Закрытие этой цели требует всех перечисленных результатов. Независимые smoke,
новая документация и зелёный fake gate её не закрывают. P1–P3 (автопамять,
ночной Full Access, настоящий Live2D/OBS, чат/соцсети и поставка) сохраняются
в общей очереди. Vision ждёт выбора владельца. Отсутствующий live ресурс
фиксировать как незавершённую проверку; не подменять его mock.

## D0 — вернуть документацию к замыслу

- [x] Зафиксировать одну платформу, Full Access/unattended, память, голос,
  2D/OBS и мятный Aero UX; разделить намерение, код и evidence.
- [x] Убрать преждевременный RC-статус и дубли текущего плана, сохранить историю.
- [x] Уточнить Qwen основной / Tera быстрый fallback, Vision deferred,
  software mic gate, ASR отдельно от понимания звука.
- [x] Записать protected-upstream границу и недостатки test harness.
- [ ] Реализация исправлений ниже. Аудит документов сам по себе их не исправляет.

### Техническое уточнение по продолженному срезу

- [~] Добавлен секрет-free versioned runtime manifest
  [`config/profile.example.json`](config/profile.example.json) и безопасный
  валидатор [`scripts/validate_profile.py`](scripts/validate_profile.py):
  проверяются bounded paths, порты `2367/8766`, резерв `8765`, компоненты и
  consent-флаги без запуска сервисов и без записи секретов. Интеграция профиля
  с launcher/installer, pinned JAWL runtime и полный startup/shutdown lifecycle
  ещё не закрыты.
- [~] Добавлен разбор prompt-архитектуры JAWL в
  [JAWL_PROMPT_ARCHITECTURE.md](docs/JAWL_PROMPT_ARCHITECTURE.md): `SOUL`,
  `INSTRUCTIONS`, выбранный function-call protocol и optional modules теперь
  считаются частью versioned профиля JAWL, а не второй логикой Companion.
- [~] Bounded stream-chat ingestion/API и запись наблюдения в JAWL event sink
  добавлены; реальный polling Twitch/YouTube/Restream, moderation/attention,
  URL metadata policy, аккаунты и UI остаются незакрытыми P1.
- [~] Native response preservation, terminal error semantics, reconnect с
  cursor и cancellation теперь покрыты HTTP E2E через тот же Companion с
  typed native fixture; сквозной прогон через конкретный live JAWL profile,
  tool outcome и production transport всё ещё требуется до закрытия P0-B.

## Принцип выполнения плана: согласованное поведение

Подсистемные галочки не равны готовому организму. Каждый срез должен замыкать
хотя бы один путь observation → attention/state → decision → action/expression →
verified feedback → memory/task update. Использовать существующие механизмы,
не плодить агентов/«отделы мозга» ради биологической аналогии.

- [~] Статическая карта перекрытий Heartbeat/Attention/TurnArbiter, VoiceMem
  recall/JAWL RAG, persona/affect/avatar state и episode/durable memory
  завершена в [CORE_OWNERSHIP.md](docs/CORE_OWNERSHIP.md); baseline packaging
  decision и live integration остаются pending. Для каждого механизма нужен
  один owner, вход/выход, что выключено и зачем.
- [ ] Минимальный общий bounded context/state snapshot и event correlation:
  focus/task/session/observations/response state, без второй mutable persona DB.
- [ ] Coherence E2E: фоновое наблюдение → поздний recall с источником;
  поручение → interruption → продолжение той же задачи → verified result;
  исправление предпочтения → согласованные текст/голос/аватар после restart.
- [ ] Проверить отсутствие двойного ответа, двойного tool execution,
  конкурирующих wake loops и расхождения эмоции между тремя представлениями.
- [ ] Любой новый psychological/biological-inspired механизм обосновать
  измеряемой пользой, лимитами ресурсов и сценарием. Не добавлять «самоэволюцию
  кода» или самоповышение полномочий как следствие этой аналогии.

## P0-A — воспроизводимая основа без изменения upstream

- [~] Инвентаризировать требуемые native JAWL additions и версии зависимостей:
  что в Companion, что в dirty JAWL, какие gateway/policy/memory capabilities
  требуются. Не назначать авторство по timestamps и не откатывать чужие diff.
  Read-only карта routes/owners, HEAD, MIT, выборочные хеши и опасные bootstrap
  defaults зафиксированы в [JAWL_RUNTIME_INVENTORY.md](docs/JAWL_RUNTIME_INVENTORY.md).
  Полное замыкание поставки и dependency lock ещё не выполнены.
  Source snapshot из 348 файлов сохранён в `runtime/jawl-sources/jawl-20260905-daily-v1`;
  хеши сверены, compileall копии и 2 теста сборщика прошли. Далее собственные
  config/SOUL и owned requirements добавлены; исходная зависимость имела
  конфликт aiogram 3.17 с Pydantic 2.11. Конфликт исправлен в owned profile;
  Python 3.11 environment установлено, `pip check` прошёл, lock сохранён.
  Далее runtime import/readiness,
  затем launcher integration.
- [!] Согласовать способ поставки совместимого JAWL (зафиксированная dependency/
  owned fork с лицензиями) и runtime location. `G:\AI\JAWL-Coding` не менять,
  не писать туда тестовые state/config/logs, не запускать там автозаписывающий код.
- [ ] Заменить машинно-зависимые профили собственными config/data/log/cache
  и явными версиями. Изолировать тестовые credentials/environment;
  запретить запуск Telethon/MCP/debug auto-start из скопированной рабочей конфигурации.
- [~] Исправить `run_target_jawl_smoke.ps1` до любого следующего запуска:
  отдельный runtime, live opt-in, fail-path отчёт, уникальный run ID,
  allowlisted environment, токен не в argv/log, process identity + creation
  time вместо убийства любого нового владельца порта. Третий revision принят
  main как PARTIAL offline safety slice: unittest 8 OK без skips, PS AST pass,
  diff pass; AST-extracted PS helpers проверены для CreateNew nonoverwrite,
  containment и отказа файла под junction. Убраны unsafe defaults/token argv/
  arbitrary port-owner killing; добавлены env allowlist, protected paths,
  explicit Live/owned marker и bounded profile deadline. LIVE запуск запрещён до
  owner-approved runtime/loader review и полной isolated process lifecycle
  validation; parent-exit cleanup race может оставить orphan, A3 не закрыт.
- [~] Сделать readiness по активному профилю и фактическому JAWL instance:
  версия, provider, policy authority, memory capabilities. Ни `configured`,
  ни HTTP 200 недостаточны. Demo/partial/ready должны различаться в UI.
  Частичный срез: configured больше не подтверждает JAWL/Vision/ambient ready;
  dependency health проверяет положительные маркеры, policy — native authority.
  Identity и proof-of-path остаются открытыми.
- [ ] Сохранённый профиль запуска/остановки всей платформы: порядок сервисов,
  readiness/warmup, занятый порт/нет весов/нет места, graceful shutdown,
  только собственные процессы. Не устанавливать лишние модели автоматически.

Последняя проверка после добавления manifest/validator: полный gate
`runtime/full-gate-20260905T101615Z.log` завершился с `exit_code: 0` — 299
non-E2E и 16 HTTP E2E тестов, compileall/py_compile, synthetic mic gate,
Node mic check и `git diff --check`. Это локальное fake/synthetic evidence;
оно не закрывает live JAWL, реальный provider, физический микрофон, OBS или
production startup.

Приёмка: из чистого runtime запускается известная конфигурация, журнал связывает
Companion с конкретным JAWL и выбранными workers; protected repo и FoxMCP
не изменены. Отказ зависимости виден и не подменяется mock.

## P0-B — первый целый сценарий: общение и поручение

- [~] Native Gateway/JSON correlation/reconnect/cancel есть; повторно проверить
  **через тот же Companion**, а не прямыми независимыми запросами к JAWL.
  Убедиться в сохранении текста, emotion/voice/avatar, tool errors.
- [ ] Настроить временный Big Pickle внутри согласованного JAWL profile;
  минимальная совместимость text/JSON/tools/empty final/timeout, без обещания
  вечной бесплатности. Relay из старого smoke не считается production transport.
- [ ] Смена provider через JAWL, capability-driven native tools/JSON envelope;
  regression для QWB-JAWL и local adapter без дублирования памяти/личности.
  Реальный QWB endpoint проверить при доступности, не блокируя остальные срезы.
- [ ] Персона/черты/важные факты редактируются в панели через JAWL, отражаются
  в следующем разговоре и переживают restart. История одна для текста и голоса.
- [ ] Пройти реальное безопасное поручение: открыть тестовое приложение,
  изменить disposable файл, проверить состояние, получить честный итог в чате.
  Инструменты — JAWL, не local fallback.
- [ ] Проверить Heartbeat инициативу и задачу без открытой панели;
  DND подавляет разговорную инициативу, не теряет согласованную работу.
- [ ] Тайм-аут/пустой JSON/provider outage дают terminal error и восстановление,
  не бесконечное ожидание и не придуманный успех.

Приёмка: одно связное общение с фактом памяти → поручение → native action →
проверенный результат → повторное обращение после restart. Затем 100-turn
profile с восстановлением соединения; прежний live Big Pickle результат
сохраняется как evidence своего отдельного окружения, не обнуляется.

## P0-C — голос и реальный UX этого сценария

- [~] Gate/пики/калибровка/hands-free и Qwen final-ASR существуют.
  Прогнать синтетические 2–3 слова/с, паузы, тихую речь, шум, конец фразы,
  переполнение очереди, disconnect, несколько фраз подряд.
- [ ] Для каждого turn измерить endpoint delay, ASR, LLM TTFT/final,
  TTS first audible и total p50/p95, отдельно cold/warm. Принять профиль по
  полной задержке, не сравнивать RTF с количеством слов пользователя.
- [ ] Закрепить Qwen основной / Tera low-latency fallback в конфиге и UI.
  Показать реальный provider/capabilities/клон/ограничения. Автопереключение
  включать только по заданной политике; не обещать Qwen real-time на CPU.
- [ ] Сопоставить эмоции ответа с реально поддерживаемой просодией/выражениями;
  отдельная RU оценка качества, unsupported style → neutral с диагностикой.
- [ ] Barge-in: быстро остановить playback, отменить/освободить inference,
  не озвучить stale audio; отличить уточнение, backchannel и новый запрос.
- [~] VoiceMem async queue не блокирует ASR turn; проверить downstream ingest,
  retrieval, ошибку/перегрузку и restart, а не только `status=queued`.
- [!] Позже с владельцем: dynamic mic, AEC/эхо, разрешения браузера, устройства.
  До этого продолжать синтетику, не называть её физическим микрофоном.
- [~] Aero-основа и CSS 2D есть. Довести сцену+чат+задачу, ясные настройки
  персонажа/голоса/памяти/доступа, loading/error/empty/save states,
  keyboard/focus, контраст, scaling 100/150%. Визуальная оценка владельцем.
- [ ] Browser E2E кликает реальные controls, проверяет сохранение и видимый
  результат. Скриншоты главных состояний; DOM-marker smoke оставить узким.

Приёмка: 3+ синтетических вопроса через browser audio routes → реальный JAWL →
выбранный TTS → единственный playback + avatar; затем настоящий микрофон.
Целевые задержки выбрать по измерениям и ощущениям, не объявлять SLO выполненным заранее.

## P1-A — Full Access и нативные инструменты

- [ ] Полезный default sandbox: отдельный CDP browser и workspace, явные
  filesystem/process/network capabilities; доказать изоляцию, а не только
  отдельный browser profile. Проверить поиск, навигацию, download и deny выхода
  за scope. Общий desktop — по native уровням, без скрытого повышения прав.
- [ ] Социальные аккаунты персонажа: подключение владельцем, отдельные scopes
  read/draft/publish, unattended policy, секреты вне model context, preview,
  журнал и reconciliation после неопределённого результата публикации.
- [ ] Будущий livestream chat: принимать заданный владельцем chat/Restream URL;
  передавать bounded viewer text в то же JAWL attention для редких контекстных
  реакций, с rate limit, DND и moderation. Viewer text — untrusted и не имеет
  authority на ПК; подключение аккаунта сейчас не добавлять.

- [~] Levels 0–3/catalog/read-only/filesystem slice проверялись отдельно.
  Собрать capability/parity таблицу всех нужных JAWL namespaces, включая
  MCP/browser и `G:\RE`, с accepted/unsupported/error и причиной.
- [ ] На уровне 3 разрешённые нативные инструменты доступны без второго
  фильтра/песочницы Companion. На 0–2 проверить expected deny/approval.
- [ ] Проверить representative safe fixtures по рискам: filesystem, execution,
  GUI, terminal, coding, MCP/browser, Debug Broker. Для каждого — успешный
  результат, отказ, cancel, stop, audit; не исполнять разрушительные операции
  на рабочем ПК ради галочки «все skills протестированы».
- [ ] Ночной unattended profile: срок покрывает выбранный интервал, без
  per-action prompts на разрешённые задачи, видимая expiry/renewal,
  stop/revoke/downgrade, crash recovery только по действующей политике.
- [ ] Durable task checkpoints и сверка уже выполненных действий после сбоя.
  Replay событий не считать exactly-once mutations; неопределённый итог
  требует проверки, а не автоматического повторения.
- [ ] Утренний журнал: результат, артефакты, незавершённое, причина остановки.
  Не раскрывать секреты, raw TTD и скрытые рассуждения.
- [ ] 8-часовой профиль автономной работы на disposable заданиях, с измерением
  ресурсов/ошибок и отказами провайдера. Один пятицикловый startup smoke не подходит.

## P1-B — память и окружающий контекст

- [ ] Обычный профиль с включёнными микрофоном/системным звуком/экраном после
  first-run выбора источников и OS/browser permissions. Persisted preferences,
  visible capture/pause/revoke, missing device/model и отказ разрешения;
  не включать отсутствующую VLM фиктивно. Проверить restart и приватный режим.
- [ ] Автоматическая запись attributed observations по мере поступления;
  отделить регистрацию эпизода от canonical fact и постоянного хранения raw.
  Контекст возможностей/сбоев/фокуса общий для JAWL и UI; неизвестное не выдумывать.
- [~] Ambient-сегментация ротирует ограниченные PCM-фрагменты по времени и
  размеру, учитывает idle, backpressure и generation при Start/Stop. 33 ambient
  теста и финальный full gate прошли; остаются физический loopback, длительный
  soak, per-app attribution и live provider acceptance.

- [~] JAWL structured memory/daily journal API описан и частично проверен.
  Принять persona/facts/revise/forget/validity/recall после restart на выбранном
  SQLite/vector/graph runtime; реальные capabilities, не import-only stub.
- [ ] Различить forget/archive и физическое erasure; консистентно чистить recall/
  embeddings/derived summaries по выбранной политике. Не заявлять удаление,
  если осталось append-only содержимое.
- [~] Self-TTS suppression и WASAPI synthetic slice есть; измерить эхо,
  наложение двух источников и потери. Не приписывать mixed loopback активному
  приложению; приватные источники требуют надёжного исключения или паузы.
- [ ] T1 → T2 → JAWL: короткие наблюдения, сжатие, TTL, объединение дубликатов,
  противоречия, рестарт. Полчаса/неделя — настраиваемые ориентиры.
- [ ] В обычном настроенном профиле добавить автоматическую консолидацию JAWL,
  ручной review оставить режимом. Ambient не порождает команды/факты о
  владельце без источника, не меняет persona сам.
- [~] AudioDescriptionService — только seam. Позже выбрать/проверить
  sound/music captioner и affect/speaker capabilities; Qwen3-ASR не captioner.
- [ ] Одновременные user turn/ambient/triage/игра: speech priority,
  измеренные CPU/RAM/VRAM бюджеты и visible dropped/degraded metrics.

## P1-C — 2D персонаж, окно и OBS

- [ ] Stream-профиль: приватные чат/память/уведомления не попадают на presentation
  страницу и в публичную речь; публичный/частный вывод различимы. Проверить
  reconnect/ошибки/смену сцены и отсутствие control credentials в OBS.

- [~] Separate presentation origin/URL/fallback есть; встроенная CSS-фигура
  пока не зеркало произвольного Live2D model3.
- [!] Выбрать внешний лицензированный/собственный 2D bundle; разработку
  остальных сценариев продолжать на fallback. 3D не добавлять.
- [ ] Один renderer/state contract для панели, отдельного окна и OBS;
  expression fallback, lip-sync от фактического playback, одна audio authority.
- [ ] Проверить transparent OBS, drag/click-through/topmost, DPI/multimonitor,
  reconnect, закрытие панелей, 8-часовое представление без утечек.
  Указывать фактические возможности browser shell, не обещать native compositing.

## P2 — Vision после решения владельца

- [!] Получить окончательный выбор VLM. Не скачивать/включать новую модель
  вместо владельца; Qwen3-VL-2B остаётся сильным кандидатом.
- [~] UIA/capture/plan seam есть. Проверить свежие observations после каждого
  действия, калибровку/DPI, stale rejection и app-level postcondition.
- [ ] Подключить отложенные visual episodes к той же памяти/Attention,
  описания по запросу и rate-limited изменения экрана; privacy/data-class consent.
- [ ] Принять VLM closed loop отдельно от CLI/UIA действий, не тормозить ими
  полезную автономность без VLM.

## P3 — приёмка заявленной версии и поставка

- [ ] Закрыть все применимые строки [матрицы](docs/TECHNICAL_AUDIT.md#приёмочная-матрица).
  Major runtime update: full regression + browser E2E + затронутые live profiles.
- [x] Сохранён полный gate `20260905T101615Z`: exit 0, 299 non-E2E и 16 HTTP
  E2E, compile/syntax, mic/Node/diff. Приёмка относится к этому срезу кода.
- [ ] Расследовать единичный HTTP 503 в native-policy E2E (лог
  `runtime/full-gate-20260905T101053Z.log`): причина не установлена.
  Успешный повтор не доказывает устранение дефекта; не добавлять слепые retries
  к управляющим операциям без проверки их последствий.
- [ ] Clean install вне source cwd: весь выбранный профиль, workers/assets,
  backup/schema migration/rollback, а не только import и CLI --help.
- [ ] Манифест версий/хешей/лицензий и отсутствие секретов в логах/артефактах.
- [!] Владелец отзывает опубликованные в чате ключи TokenRouter и OpenCode;
  агент не печатает, не копирует и не отзывает их сам.
- [ ] RC только после полного ежедневного сценария; production-ready только
  после выбранной feature matrix, долгого профиля и пользовательской приёмки.

Следующий implementation slice — **P0-A**, затем **P0-B + P0-C**.
Не повторять сборку или один и тот же зелёный smoke без нового изменения/гипотезы.
Если блокируется внешняя модель/ассет, делать доступные независимые задачи;
не расширять полномочия ради «не останавливаться».
