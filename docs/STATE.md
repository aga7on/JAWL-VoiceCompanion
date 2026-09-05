# Состояние разработки

Synthetic voice-robustness slice (P0-C foundation) is in: `ASRNoSpeech` is a
first-class outcome — `ExternalASRService.finish` returns `no_speech`
(injectable `clock` makes TTL eviction/disconnect tests offline-deterministic),
and `/api/voice/end` maps it to a neutral empty transcript. The deterministic
generator `scripts/make_synthetic_audio_cases.py` builds 12 acoustic cases
(tempo/pause/quiet/faint/noise/phrase-end/consecutive) with a `cases.json`
expectation manifest; `scripts/run_asr_profile.py --expects` now fails only
when required speech is absent while tolerated noise-floor no-speech still
counts as covered. `scripts/check_mic_gate.mjs` verifies browser backpressure at
`MAX_PENDING_AUDIO_CHUNKS` (8). Live ASR acceptance of the matrix via
`scripts/run_synthetic_cases_live.ps1` (local Qwen3-ASR-0.6B) is PENDING an
ASR worker run; this slice deliberately does not yet satisfy Partial ASR
streaming, cancellable streaming TTS, semantic barge-in or interruption E2E.

Local LLM check for the next live run: LM Studio `127.0.0.1:1235` answers but
requires an API key (401); Ollama `127.0.0.1:11434` answers without auth and
hosts `gemma-4-12b-obliterated:latest` — owned JAWL can target it via
`LLM_API_URL=http://127.0.0.1:11434/v1` + `main_model=gemma-4-12b-obliterated:latest`.
No live provider turn is claimed yet; full suite is green (345 pytest + 28
subtests, synthetic Mic gate Node, diff check).

UI acceptance remains OPEN: [six-point audit](UI_ACCEPTANCE.md). The latest
browser voice attempt (2026-09-06) reached the integrated profile; the user
heard generated error speech, but Selenium hit its 120-second HTTP read timeout
while the local CPU/OpenCode turn was still running. This is a
failed/unaccepted live run, not a pass. The earlier 30-second async-script limit
was changed to 180 seconds; the application turn still needs a bounded
completion/cancellation path below the driver limit. The desktop
screenshot supplied by the owner differs from the old narrow headless capture.
Responsive Edge checks now pass all six tabs at six viewport sizes, including
320px and 390px widths, with screenshots in `runtime/browser-evidence/responsive/`.
This is mock/viewport evidence; real tablet, keyboard and microphone are pending.
LAN/HTTPS and the first memory-library UI slice are implemented; live tablet,
live recall and the connected daily scenario remain pending.

Latest full-gate capture after the browser voice and memory-documentation
changes is `runtime/full-gate-20260905T212025Z.json` with exit code 0. The paired log
records 308 non-E2E tests, 16 HTTP E2E tests, compile
and syntax checks, synthetic microphone, Node, and diff checks. Earlier gate
artifacts remain historical evidence and are not overwritten.

`scripts/run_browser_voice_e2e.py` provides the browser-side synthetic audio
driver for the eventual live run. It requires an already connected real
profile and explicit `--live`; the current refusal artifact records that live
execution was not attempted without a provider.

`run_local_bonsai_integrated.ps1 -RunSeconds 1` passed owned startup and
shutdown with local Qwen3-VL-2B, Qwen3-ASR, TeraTTSv2 and VoiceMem on isolated
ports. Evidence is `runtime/local-bonsai-integrated-profile.json`; it is
startup-only. The new `-RunBrowserVoiceE2E` switch is available for the real
three-WAV browser path but has not yet been accepted.

The current owned-runtime preflight passes (`embedding_cache=ready`,
`missing=[]`). A live provider run remains unavailable because no
`LLM_API_KEY_1` is present in process, user, or machine environment; the
credential must be supplied process-locally and must not be stored in this
repository.

The OpenCode Zen model catalog is reachable without credentials (HTTP 200).
It currently advertises `big-pickle` and `deepseek-v4-flash-free`; this is
catalog evidence only. Authenticated completion remains pending until the
owner supplies `LLM_API_KEY_1` through the process environment.

The current UI slice makes the overview a chat-first surface, removes the
duplicate avatar action row, adds attachment/emoji/slash/microphone controls,
and moves low-frequency vision and initiative settings into System. TXT/MD
files are read into the text request; unsupported binary media produces an
explicit capability error. Microphone device selection persists in browser
storage. Edge render smoke passed with screenshots in
`runtime/browser-evidence/20260905T195242Z/`. Browser interaction E2E also
passed in explicit mock-brain mode; its control screenshot is retained under
`runtime/browser-evidence/interaction/`. Neither check claims live-provider
acceptance.

The first real local core/audio run completed one synthetic Russian WAV through
Qwen3-ASR -> owned JAWL -> TeraTTSv2 with VoiceMem enqueue: 50 chunks, one
VOICE_TURN, one response, and a 44.1 kHz WAV. Evidence is
`runtime/local-live-audio-pipeline.json` with correlation ID
`audio-profile-ebab346687a24819b7a75d72bb02bce6`. A later turn was interrupted
by the bounded run window and is recorded as failed.

Qwen3-VL-2B-Q4_K_M was then tested text-only (Vision disabled) and returned a
valid terminal JAWL JSON with empty actions during the real heartbeat. Gemma's
tool output was invalid, while the ternary Bonsai GGUF cannot be loaded by the
available llama runtime. This makes Qwen the current local candidate, pending
a complete user-turn and native-task run.

The launcher credential handoff is now environment-only for the owned JAWL
child; targeted launcher safety tests passed. A local Bonsai integrated run
was not claimed because this shell rejected the secret-shaped environment
assignment before process creation.

The 503 seen in the current gate is now attributed to the deliberate offline
JAWL-control fixture: the test verifies fail-closed emergency-stop semantics,
not an intermittent production failure. The older external QWB 503 was
recorded as `upstream_waf_challenge`; no control retry is performed. A live
provider-specific 503 remains untested while credentials are absent.

`run_audio_pipeline_profile.py` now records a per-run correlation ID and
separate stage timings; its contract tests and local E2E remain green.

Browser interaction E2E passed against an isolated Companion mock instance:
`runtime/browser-interaction-e2e.json`. Edge exercised real DOM controls for
gate persistence and chat rendering and saved a screenshot. The report is
explicitly mock-brain evidence, not live JAWL/LLM or voice acceptance.

Live local audio chain evidence (2026-09-05): three Russian utterances were
generated by TeraTTSv2 and sent to local Qwen3-ASR-0.6B on CPU. Report:
`runtime/synthetic-questions-profile.json`, passed, median final-utterance RTF
0.111, all three results non-empty. This does not prove browser microphone,
streaming partials, JAWL+LLM, playback, interruption, or avatar behavior.

The integrated launcher now has an opt-in `-StartLocalAudio` path that starts
and health-checks both local workers, wires their loopback endpoints into the
Companion, and stops them during teardown. It has not been accepted as a full
scenario because the live JAWL provider credential is still absent.

The refreshed full gate after loopback security integration is saved at
`runtime/full-gate-20260905T190000Z.json` with `exit_code: 0`; its paired log
records 301 non-E2E and 16 HTTP E2E tests plus auxiliary checks.

After the loopback JAWL token policy change, web and local E2E regression
passed 52 tests; the full gate is intentionally still pending for this change.

Integrated loopback control no longer needs a generated console token. Empty
tokens are accepted only for loopback JAWL URLs; remote URLs remain token
protected. This keeps the integrated profile secret-free at rest.

Real local TeraTTSv2 CPU run passed three Russian synthesis requests. Evidence
is `runtime/tera-live-profile.json`: median RTF 0.162, p95 complete response
0.589 s. It remains a complete-WAV worker measurement, not first-audio,
microphone, or full JAWL pipeline acceptance.

Installed Edge produced and visually passed control/avatar PNG evidence under
`runtime/browser-evidence/20260905T154359Z/`. This validates browser rendering
and the isolated 2D fallback only; it is not real Live2D/OBS acceptance.

The integrated launcher now checks `LLM_API_KEY_1` before creating any JAWL
process, preventing a half-started profile when live provider configuration is
incomplete. Credentials are never written to the repository.

The integrated lifecycle probe reaches the JAWL console, then the agent exits
at provider validation because the configured OpenAI-compatible cloud provider
requires `LLM_API_KEY_1`, absent from process/user/machine environment. The
launcher now surfaces this exact failure and its startup log rather than
waiting for a terminal port. No credential was written to the repository.

Saved full-gate evidence: `runtime/full-gate-20260905T183500Z.json` has
`exit_code: 0`; the paired log records 301 non-E2E and 16 HTTP E2E tests plus
compile/syntax, synthetic mic, Node, and diff checks. This remains repository
evidence and does not prove live provider or physical-device acceptance.

## Latest technical slice

The owned JAWL runtime now has a pinned source snapshot, a verified Python
3.11 environment, and reproducible profile preparation. `SOUL.md` is staged
at `runtime/instances/daily/prompts/personality/SOUL.md`; working config,
data, logs, and sandbox are isolated from source and protected repositories.
Launch JAWL with `scripts/run_daily_profile.ps1` on its separate console port
`8770`; Companion control remains `2367`. The
launcher never stores or prints credentials and only inherits existing
`LLM_API_KEY_*` variables. This is not live acceptance yet: provider,
browser E2E, physical microphone, OBS/Live2D, and the complete connected
scenario remain open in TODO.

The first process-level startup smoke on the owned profile reached SQL and
vector initialization, then exceeded the short smoke window while downloading
the embedding model. It was stopped deliberately. This exposes a required
preflight/warm-cache step and readiness probe before live E2E; no provider or
user credential was used.

After warming the locally available embedding cache, a second process-level
run reached `JAWL started successfully` and completed stop-file shutdown with
`Shutdown complete` and PID cleanup. The first shorter shutdown window was
insufficient; the accepted profile check now has an explicit preflight instead
of relying on timing.

The subsequent full gate passed 301 non-E2E and 16 HTTP E2E tests, plus
compile/syntax, synthetic mic, Node and diff checks. Its ad-hoc capture wrapper
had a PowerShell-version timestamp incompatibility, so the run is recorded as
passed in the session output but not promoted as a new saved evidence artifact.

Дата: 2026-09-05. Статус: **интеграционный прототип**.
Это текущая сводка, не журнал многократно повторённых прогонов.
[PRODUCT.md](PRODUCT.md) — замысел; [TODO.md](../TODO.md) — продолжение;
[TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md) — риски и приёмка.

## Следующая активная цель

Предыдущий goal (ambient Start/Stop, STATE, сохранённый full gate) завершён.
Текущий приоритет — единый профиль запуска и связный сценарий из
[TODO](../TODO.md#активная-цель--первый-связный-ежедневный-сценарий):
голос → ответ того же JAWL → память → native поручение → проверенный результат
→ recall/задача после restart. Критерии включают реальные модели, browser E2E,
измерение задержек и сохранённый отчёт; синтетические входные WAV допустимы.
Микрофон владельца, настоящий Live2D/OBS и ночная автономность остаются
отдельными незавершёнными приёмками общего roadmap.

Главный разрыв: manifest пока только валидируется, CLI по умолчанию выбирает
mock, совместимая поставка JAWL и единый startup/shutdown не приняты.
Следующая работа должна замыкать эти связи и пользовательский сценарий.

Первый P0-A проход: [runtime inventory](JAWL_RUNTIME_INVENTORY.md) сопоставляет
native routes с исходниками, фиксирует reference HEAD/MIT и выборочные хеши.
Проверено, что main читает shared `.env`, а instance bootstrap копирует рабочие
config и всё дерево prompts. Старые runtime dirs не доказывают независимую
поставку исходников. Следующий шаг — собственная source dependency и профиль
с чистыми настройками, затем launcher integration. В этом проходе запусков
JAWL и изменений protected upstream не было.

Первая попытка установки остановилась на конфликте upstream requirements:
`aiogram~=3.17.0` требует `pydantic<2.11`, JAWL — `pydantic>=2.11`.
Добавлен owned `config/jawl/requirements-runtime.txt` с aiogram 3.25.x;
конфликт исправлен в owned profile `requirements-runtime.txt`; Python 3.11
окружение установлено, `pip check` прошёл, точный lock сохранён.
Импортный граф и readiness ещё нужно принять; snapshot и protected upstream
не менялись.

Следующий P0-A срез сохранил собственный source snapshot из 348 файлов в
`runtime/jawl-sources/jawl-20260905-daily-v1` через `stage_jawl_source.py`.
Все хеши manifest сверены; 2 теста сборщика и compileall копии прошли.
Рабочие config/persona/secrets не переносились. До запуска остаются свой
SOUL/config, dependency lock/import checks и интеграция launcher; runtime_ready
в manifest явно false. Это сборка исходников, не принятый live сценарий.

## Завершённый срез и evidence

 Получена ревизия ambient-сегментера; гонка конкурентных `Start`/`Stop` закрыта
 lifecycle-lock в Companion и детерминированными тестами. Предыдущий агент Luna
 остановился из-за лимита; после сброса квоты этот срез завершён.

 Targeted ambient suite: 33 теста прошли. Финальный полный gate
 `20260905T115735Z` завершён с `exit_code: 0`: compileall, server syntax,
 281 non-E2E unittest, 14 HTTP E2E, synthetic mic gate, Node mic check и
 `git diff --check` прошли. Отчёт: `runtime/full-gate-20260905T115735Z.json`;
 полный вывод: `runtime/full-gate-20260905T115735Z.log`. Это fake/synthetic
 evidence; live devices, provider, OBS, native JAWL runtime и production
 acceptance не следуют из этого gate.

После этого gate добавлены ещё не включённые в его отчёт изменения: Companion
сохраняет полный native JAWL response envelope (включая emotion/voice/avatar,
actions и response identity), различает terminal provider error и обычный
текстовый fallback, а native SSE умеет ограниченный reconnect по `event_seq`.
Также появился bounded transport-agnostic stream-chat ingest/API с optional
JAWL event sink. Native изменения дополнительно прошли новый полный gate и
HTTP E2E, но это всё ещё не доказательство live JAWL/OBS/provider приёмки.
Реальный connector чата, moderation/attention routing и browser E2E остаются
в TODO.

Отдельно зафиксирована prompt-архитектура JAWL в
[JAWL_PROMPT_ARCHITECTURE.md](JAWL_PROMPT_ARCHITECTURE.md): повтор system
prompt на каждом ReAct-шаге является механизмом реконструкции, а provider
session/cache — только оптимизацией.

Свежий полный gate после этих изменений: `20260905T100007Z`,
`exit_code: 0`. В нём прошло 295 non-E2E и 16 HTTP E2E тестов, compileall,
 syntax checks, synthetic mic gate, Node mic check и `git diff --check`.
Отчёт: `runtime/full-gate-20260905T100007Z.json`; полный вывод:
`runtime/full-gate-20260905T100007Z.log`.

После него добавлены versioned secret-free runtime manifest и validator:
`config/profile.example.json` проверен без запуска сервисов и без записи
секретов; launcher пока не читает manifest как единый startup profile.
Актуальный полный gate после этой правки: `20260905T101615Z`,
`exit_code: 0`, 299 non-E2E и 16 HTTP E2E; также прошли compileall,
py_compile, synthetic mic gate, Node mic check и `git diff --check`.
Отчёт-метаданные: `runtime/full-gate-20260905T101615Z.json`; полный вывод:
`runtime/full-gate-20260905T101615Z.log`. Первый запуск после правки дал
один HTTP 503 в тестовом JAWL control fixture, но отдельный и
повторный полный E2E прошли. Причина 503 не установлена; объяснение нагрузкой
было предположением. Расследование остаётся в TODO. Это не live evidence.

В рамках native E2E обнаружен и исправлен EOF-край: закрывшийся SSE мог
оставить уже прочитанный final в bounded queue, но клиент преждевременно
считал поток пустым. Reader теперь сначала дренирует pending packets; это
проверено reconnect-сценарием через HTTP Companion.

## Последнее уточнение и частичный readiness-срез

По уточнению владельца обычный профиль должен воспринимать звук/экран после
первичной настройки источников, автоматически регистрировать опыт в памяти
JAWL, давать полезную работу в default sandbox/CDP и отдельное публичное
Live2D-представление для OBS. Добавлены требования аккаунтов/публикаций и
самонаблюдения. Это целевой дизайн; capture defaults в runtime не переключены,
захват устройств/аккаунтов/OBS не запускался. Protected upstream не изменялся.

Предшествующий кодовый срез изменил doctor и target-release проверки:
configured не подтверждает JAWL/Vision/ambient ready, неоднозначные dependency
health отклоняются, native policy требует authority=jawl и корректный уровень.
Правки в tests/test_doctor.py, test_target_release_profile.py, test_e2e.py.
Это частичное A2, не доказательство связанного live профиля.

Ранее был промежуточный full gate с 258 non-E2E pass и одним HTTP E2E fail;
после исправления ожидания focused HTTP E2E прошёл 1/1. Финальный gate и его
сохранённые результаты указаны выше. Live devices/provider, visual browser и
OBS этим срезом не проверены.

История делегации: docs-проход и статическая карта в
 [CORE_OWNERSHIP.md](CORE_OWNERSHIP.md) завершены; третий revision launcher у
 Gauss принят main как PARTIAL offline safety slice; ambient rotation и
 lifecycle-race slice приняты как PARTIAL synthetic evidence. Baseline packaging
 decision и live integration ещё не
приняты; карта — предложение, не реализация, и отключение durable VoiceMem
writes этой сводкой не утверждается. Lifecycle-гонку main завершил локально
после ревью. Эта история не подтверждает наличие работающих субагентов сейчас.

Предыдущая ревизия была отклонена из-за overwrite отчёта/записей вне root,
protected-runtime containment gaps, PS API/type semantics и того, что pytest
не обнаруживается unittest gate. Main проверил код и тесты launcher: unittest
8 OK без skips, PS AST pass, diff pass; AST-extracted PS helpers проверены для CreateNew nonoverwrite,
containment и отказа файла под junction. Убраны unsafe defaults/token argv/
arbitrary port-owner killing; добавлены env allowlist, protected paths,
explicit Live/owned marker и bounded profile deadline. Это не доказывает
полную безопасность: LIVE запуск запрещён до owner-approved runtime/loader
review и полной isolated process lifecycle validation; parent-exit cleanup race
может оставить orphan, A3 не закрыт. Финальный local full gate имеет
`exit_code: 0`, но это не заменяет owner-approved runtime/loader review или live
acceptance.

## Предыдущая работа: аудит документации

Сопоставлены требования владельца, основные документы, контракты, startup/
readiness/audio/profile code и доступные JSON-отчёты. Уточнены единый продукт,
Full Access, память, UI, профили моделей, порядок реализации и уровень evidence.
Дополнительно уточнено направление «согласованного организма»: общий цикл
восприятия/решения/обратной связи, карта перекрывающихся механизмов и coherence
E2E. Биология — инженерная аналогия; JAWL — база развития owned ядра.
Runtime-код, конфигурация, веса и внешние репозитории в этом проходе не менялись.
Модели/сервисы, микрофон, OBS, native gate и бенчмарки не запускались.

Проверка документации: 25 активных Markdown-документов (исторические снимки
исключены), 64 локальные ссылки, целевые anchors, code fences и whitespace —
без ошибок; `git diff --check` прошёл. Поиск key-shaped `sk-…` строк в этих
документах дал 0 совпадений; это не полный secret scan репозитория/истории.

Прежние README/TODO/STATE/ARCHITECTURE/AUDIT сохранены в
[history](history/2026-09-05-before-product-audit/README.md) с предупреждением.
Исторические статусы и команды из них не являются текущей инструкцией.
Рабочие code changes других итераций сохранены; аудит документации их не сертифицирует.

## Где находится проект

- Наш repo: `G:\AI\JAWL-VoiceCompanion`, dirty worktree, множество tracked/
  untracked runtime/test/UI изменений. Не сбрасывать и не коммитить их пакетом.
- `G:\AI\JAWL-Coding`: внешний protected reference. В git status есть
  изменённые исходники и untracked gateway/structured-memory/autonomy. Это факт
  checkout, не доказательство автора. Не утверждать «исторически никогда
  не менялся». Текущий аудит читал только git status/исходники, ничего не писал.
- `G:\AI\VoiceMem` и `G:\RE`: внешние зависимости; junctions сохранить.
- Control/presentation defaults: 2367/8766; 8765 оставлен FoxMCP.
  Наличие listener сейчас не проверялось и не гарантируется этой сводкой.

## Что есть и где заканчивается доказательство

| Подсистема | Наблюдаемое состояние | Открыто |
|---|---|---|
| UI | Mint/Aero HTML, вкладки, чат, inline CSS 2D | Качественная visual/interaction приёмка; удобное управление persona/задачами |
| Startup | run_web с optional flags, проверкой портов | Без флагов `phase1_mock_brain`; нет принятого единого профиля |
| JAWL adapter | Native SSE/turn/control в Companion, counterpart в dirty JAWL | Поставка версии, handshake, identity, daily integrated path |
| Tools | Proxy HostOS/Terminal/Debug, native authority; local dev fallback | MCP/browser/full mutation/recovery parity, no-bypass end-to-end |
| Voice | Worklet gate, final-ASR, async VoiceMem ingest | Физический микрофон, partial streaming, AEC/barge-in, реальные latency |
| TTS | Tera и Qwen Base workers/CLI; sentence transport | Qwen default по желанию владельца, capabilities/fallback UI, эмоции и native cancellation |
| Ambient | Capture/ASR/triage, непрерывная bounded сегментация, lifecycle fix, manual promotion | Live loopback/soak, durable episodes, автоматическая консолидация |
| Memory | JAWL API для revisions/validity/journal | Clean-version ownership, whole-profile restart/recall/erasure acceptance |
| Vision | Capture/UIA/plan/token seams | Выбор VLM отложен; closed loop не принят |
| Avatar/OBS | Separate origin, fallback, optional bundle adapter | Реальный общий персонаж, OBS/audio ownership/DPI/8h |
| Operations | Gate/profile/build tooling | Harness safety fixes, honest ready state, clean install/долгий прогон |

## Evidence: читать в пределах конкретного профиля

При документальном аудите прочитаны существующие отчёты; это не новые прогоны.
Они локальные, часть не в git, не все содержат версию/хеш источников. Для новой
конфигурации прежнее `pass` не переносится автоматически.

- `runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`: native
  gateway 100-turn pass через тестовый OpenCode relay. Не полная voice/UI/PC приёмка.
- `runtime/native-jawl-namespace-parity-20260905.json`,
  `runtime/native-jawl-catalog-matrix-20260905.json`,
  `runtime/native-jawl-policy-20260905-fixed.json`: catalog/projection и
  ограниченные native probes; не выполнение всех инструментов.
- `runtime/audio-pipeline-qwen-20260904.json`: ASR→response route→TTS, queued
  VoiceMem, total 20.511 s; `end_seconds=0.391` — не вся голосовая задержка.
  Harness не подтверждает identity/native LLM, выполнение memory ingest или
  реальный playback. Нельзя называть это полной JAWL voice acceptance.
- `runtime/target-release-profile-20260905-jawl.json`: доступность Companion
  surfaces и отдельно JAWL status/policy с provider sink. Проверки не доказывают,
  что именно этот Companion подключён к именно этому JAWL.
- `runtime/restart-soak.json`: 5 коротких degraded циклов, 30 health samples;
  суммарно около 5.45 s, не ночной нагрузочный soak.
- Предыдущие записи о wheel/CLI и Edge DOM — ограниченное packaging/marker
  evidence, не работа установленного приложения и не визуальное качество.

Ранее в документах заявлялось «официальный full gate 252 non-E2E + 14 HTTP
E2E»; это заменено свежим сохранённым gate выше. Один HTTP 503 в
первом повторе не переносится в production-приёмку и не считается доказанным
устранением причины нестабильности.
Запись «1679 passed / 13 skipped JAWL» также историческая, не свежая проверка.

## Решения, которые нельзя потерять при передаче

- Один JAWL агент + Companion + VoiceMem; direct LLM adapter — только тест.
- Full Access/unattended — требование, а не отложенный «опасный лишний контур».
- Qwen3-TTS основной желаемый, Tera быстрый fallback; текущий CLI ещё default Tera.
- Qwen3-ASR final mode; музыка/тембр требуют отдельных capabilities.
- VLM не выбирать до решения владельца. Лицензированный Live2D bundle ещё нужен.
- Ручное ambient promotion — текущее ограничение, не окончательная архитектура.
- User-owned upstream не менять и не запускать write-producing тесты в нём.

Следующий шаг — P0-A в TODO: ownership/versioned runtime и безопасные профили,
затем демонстрируемый разговор+поручение+голос/интерфейс. Не новая серия
одинаковых wheel builds. Полный список проверки результата — в аудите.
## 2026-09-05 live validation correction

The post-change full gate passed with exit code 0:
`runtime/full-gate-20260905T172607Z.json` and its paired log. This validates
the repository regression suite and auxiliary checks, not the failed extended
live Qwen run below.

The owned JAWL registry now has two explicit compatibility aliases from the
observed historical `HostOSTerminal.*` names to the native
`HostTerminalMessages.*` skills. They use the existing registry, parameter
guard, RBAC and execution engine; arbitrary unknown names remain rejected.

The extended local Qwen/VoiceMem run is not a three-turn acceptance. The first
synthetic Russian question passed ASR -> owned JAWL -> TeraTTS with correlation
`audio-profile-52faa6e52c4f46e5b72742ece4b1f6df` and 1.617 s total elapsed time.
The second produced a final voice response but JAWL spent 120.768 s in a
ReAct cycle, exceeded the harness's 8 s bound, and generated no TTS; its
correlation is `audio-profile-c26bf42f9ff949f4a102697dba9ed057`. The third
question was not executed. Logs show unavailable `HostOSTerminal.*` skill
names, so the local model is not yet protocol-compatible for production.

An isolated follow-up profile reported ASR -> response -> TeraTTS in 2.307 s
(`runtime/alias-live-q2.json`, correlation
`audio-profile-50a0f0262b6b448688f935283f4102bf`). The JAWL log did not capture
an alias invocation before shutdown, so this is not proof of invalid-plan
recovery.

Native HostOS live evidence: `runtime/native-action-live-20260905202420.json`,
correlation `native-action-1783f5b355ca457c836e07625d226c94`. Owned JAWL
performed the disposable directory/file/metadata/monitoring sequence through
`/api/hostos/skill`; all five actions returned HTTP 200 with `native=true` and
cleanup removed the marker and directory. The UI/voice-originated task remains
unverified.

The next model-originated task attempt was not accepted: the owned JAWL chat
endpoint returned HTTP 409 twice while the startup heartbeat held the agent;
the following local Qwen call reached the provider timeout/retry boundary.
This exposes a P0 scheduling issue between heartbeat and foreground turns,
which must be fixed with bounded cancellation/defer semantics rather than
blind chat retries.

The web handlers now acquire the asynchronous terminal bridge and wait for
connection readiness before sending. A fresh owned-profile POST returned HTTP
200 with a user sequence instead of 409; the short probe ended before the
model response, so full completion and fair heartbeat scheduling remain
unverified. Full gate: `runtime/full-gate-20260905T174510Z.json` (exit code 0).

The UI memory contract is live-verified end-to-end in
`runtime/live-ui-memory-restart-20260905.json`: a unique preference was
stored through Companion `/api/jawl/memory` with `native=true`, found before
restart, native restart returned `agent_ready=true`, and a bounded follow-up
read found the same value after restart. An immediate first read was too early
and was repeated only after readiness.
The subsequent regression gate passed at
`runtime/full-gate-20260905T180113Z.json`.

`JawlWebAdapter.restart_agent()` now waits up to a bounded interval for native
JAWL status `running=true` and `starting=false`; it reports failure instead of
claiming restart success when the console is unavailable. Regression gate
after this change: `runtime/full-gate-20260905T180606Z.json` (exit code 0).

Lifecycle timeout was corrected after logs showed native JAWL restart taking
about 60 seconds. Stop/start/status now use a bounded 120-second timeout while
ordinary requests keep the short timeout. Regression gate:
`runtime/full-gate-20260905T181140Z.json` (exit code 0).

An intervening gate briefly exposed a fixture race; the focused E2E passed on
repeat and the immediate full-gate rerun passed at
`runtime/full-gate-20260905T181942Z.json`. The failed artifact remains in
runtime history for diagnosis.
