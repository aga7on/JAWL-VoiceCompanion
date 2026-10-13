# JAWL VoiceCompanion — инструкции агентам

## Приоритетный checkpoint — 13Oct

14Oct current: gate23657 TERMINAL0/875-66-16-104+browser, baseline362/6721866f…
unchanged. R6 NOW running exec1688/report live-voice-turn-context-20261014-r6.json;
poll same handle, no app edits/duplicate launch. Same models/WAVs, binding+noloop.
All agents closed. Historical R6-not-run/gate-running below superseded by STATE top.

14Oct newest supersedes R5-live below: R5 terminal1, first required draft/fullaudio
PASS, second native turn.error/noTTS. Exact Job/listener cleanup PASS. Test WAV
loop caused another utterance at161s, now %noloop (not cause of earlier error).
Owned context binding NOW wired:25focused PASS3.14/3.11 +actual console probePASS.
Fullgate23657 RUNNING/log gate-turn-context-20261014.log; baseline362/6721866f….
R6 runner prepared but NOT run. No active model profile/allagentsclosed. STATE top.

14Oct newest: fullgate97728 terminal0/861unit66pytest16HTTP104Node+browser;
baseline360/d365b1ed… unchanged. R5 LIVE exec69826, profile ready/exact Job owns
2367/8766/8770/8990/9890, runtime953db7f2bb5a48438ff733f92e4dd272, browser27448.
Wait same handle/report, no duplicate/restart/app edits. STATE top has paths.
Native context discovery: _heartbeat_provider CURRENT→HEARTBEAT afterstep1;
Ohm prepares NEW owned registry/budget context-provider/tests only, not wired.
Do not confuse no-concurrent-loop finding with no-context-relabel finding.

14Oct Moscow latest supersedes below: strict draft gate22 tests +capture
lifecycle/helper34 PASS; new baseline360/d365b1ed… Fullgate session97728 RUNNING,
gate-strict-draft-diagnostics-20261013.log (UTC-tag). All agents closed. R5 runner
newtag/currentbaseline/--require-draft-preview not run. Attempt7 capture fetch20
TypeError+mic off, not proven headless/AudioWorklet freeze. Cleanup distinguishes
listen absence from bind/TIME_WAIT; historical9890 false not rewritten. STATE owns
evidence; B2-02 partial. Keep OmniVoice/active avatar and protected sources unchanged.

Actual latest: default голос — OmniVoice (owner13Oct; manifest launch.tts_provider;
Tera остаётся выбираемым), frozen baseline360 `79226e1b…`. Strict r4 attempts4–7:
prompt-fix поднял доставку (turn1–2 PASS полная озвучка), OmniVoice-слушатель9890
в Job; остаётся turn3 (headless-флейк захвата / длинный «статус»-ход) — повтор OPEN.
Отчёты `…attempt{1..7}*` и границы — верх STATE. Записи ниже исторические.

Новейший: draft consumer уже served/wired `/app`,29Node +asset HTTP +8 prior
synthetic browser checks PASS; actual draft display/stale UI не принят. Новый
fullgate session29814 running, log gate-voice-draft-20261013.log, baseline360/
df1daed7… — верх STATE. Laplace НИЧЕГО не запускал, закрыт; его runtime runner
ссылается на старый358 baseline, перед live review/update. Не повторять старое
«ждать Laplace/не wiring» ниже. Models/default avatar unchanged, goal active.

Owned completion guard уже подключён в run_owned_jawl_console.py. Не делать
заново:11 guard/snapshot +12 launcher PASS3.14/3.11, actual console import/install
probe PASS; full gate session31873 terminal0:844/66/16 +browser stages. Receipt
gate-native-delivery-20261013.json, baseline358/9ab84ada… в STATE. Guard не ответ
модели и не B2 acceptance. Новый bounded r4 live run делегирован Laplace;
helper voice-draft.js отдельно Peirce, без wiring до завершения run — IDs в STATE.
Перед запуском проверить конкретные agent/process/report, не дублировать runtime.
Далее delivery recovery и partial UI; protected snapshot immutable.

Новейший strict live acceptance FAIL: first2 turns full-audio PASS, third status
turn missing final after native duplicate_success_concluded; all own ports gone.
Верх STATE: exact repro/next completion guard and offline embedding seeding debt.
Не rerun целый стек без новой гипотезы/исправления. Protected snapshot unchanged;
guard/fixes только через owned runtime boundary, не редактировать pinned source.

Новейший user night changes: connected `/app` route уже прогонялся; не повторять
ради отметки. Верх STATE review: playback start не доказывает completion, B2-01
partial; empirical timing review вместо экстраполированного p95. Приоритет:
strict playback/EOF gate, empty-terminal actions и потеря UI turn при mic Stop.
Review fixes implemented +fullgate `gate-b2-voice-review-20261013.json` passed/
child0:832/66/16/86/6/8. Fresh live correlated delivery/completion после profile
sync/restart ещё OPEN; только static prompt/controlled JS compliance проверены.
Нижний next «connected synthetic run» относится к checkpoint до ночных тестов.

Новейший: final-ASR owned DEVNULL/tree-before-temp-cleanup +actual GPU1 Hikari
generation cancel/followups PASS, real GigaAM3 WAV PASS. Latest fullgate
`gate-final-asr-gpu-20261013.json` **PASS/child0**, baseline353 — STATE.
B2-01 `/app` accepted 13Oct (3 RU WAV fake-input device, receipt
`browser-voice-e2e-20261013-app.json` PASS, VRM скриншоты) — STATE; B2-03 13-turn
серия частично; ночной gate `full-gate-night2-20261013` exit0. Следом B2-02 partials
UX (bounded/stale-drop `/app`) и terminal-канал fix; физический mic/OBS/арт —
owner-pending.

Новейший: StreamingASR/VoiceMem теперь owned atomic PIPE Job; EOF/tree/retry
tests PASS3.14/3.11. Final `gate-pipe-owner-20261013.json` passed/child0:
814/66/16/86/6/8 synthetic checks, baseline352 — верх STATE.
Следом `giga_final.py` file-mode ownership и actual live voice acceptance.
Нижние per-worker/direct PIPE next steps — исторические checkpoints.

Новейший срез: per-worker nested Job + bounded ActiveProcesses0 teardown;
4 actual tree tests PASS3.14/3.11, final `gate-worker-tree-20261013.json` passed/
child0:805/66/16/86/6/8 synthetic checks; baseline349 в STATE. Следом direct Popen/PIPE owners, не снова
per-worker restart. Нижние записи — checkpoints до этого изменения.

Верх `docs/STATE.md` актуальнее исторических записей ниже. RuntimeSupervisor
early create→Job gap закрыт JOB_LIST; direct Popen owners и per-worker restart
descendant teardown ещё OPEN. Финальный receipt `gate-atomic-job-20261013-r2.json`
проверять до заявления PASS; baseline348 `baseline-b1-atomic-job-20261013-r3.json`.
CPU Hikari не reload без новой гипотезы. Не принимать UAC/EULA за пользователя.
Goal active, весь продукт не RC; defaults/active avatar сохранены.

## Последнее поручение — 2026-10-10: работать по TODO через новый goal

Текущий scope — реализация по TODO: B0 → B1 → B2 → B3 → P/U/A → B4.
Новый goal создан. Работать небольшими проверяемыми срезами, экономно
делегировать Luna с непересекающимися write scopes. Первый срез — manifest,
defaults и воспроизводимый запуск. Не менять модели/active avatar скрытно;
protected upstream остаются read-only, захват устройств требует источников/consent.
Карта документов — `docs/README.md`; единственная очередь — `TODO.md`;
факты/evidence — `docs/STATE.md`; полный остаток/оценка — `docs/WORK_REMAINING.md`.
Последний полный regression — 12OctMoscow, direct child exit0 и receipt passed:
779 Python unit /66 manifest-worker/diagnostics pytest /16 HTTP /86 Node /6 legacy browser /
8 desktop composite checks. Это synthetic/fixtures, не production/live/device/art
acceptance; gate-client-post-20261012 log/receipt,343 frozen sources и
отдельные actual Tera/installed SDK/owned native console probes — в STATE.
Owned HTTP cancel-before-dispatch и diagnostics owner fence добавлены без
upstream patch; ID registry process-local/TTL bounded, не exactly-once.
Default client POST total deadline/scoped abort проверен HTTP/TLS loopback;
opaque custom opener reap не заявляется. Actual Hikari CPU r1/r2 FAIL:35s без
подтверждённого prefill/generation progress; own cleanup PASS, не compute release.
CPU не reload без новой гипотезы; 13Oct early gap закрыт для RuntimeSupervisor,
следом B1 per-worker restart descendants и отдельные direct Popen owners.
Selected GPU1 release остаётся OPEN. Новый diagnostic harness9 tests PASS/345-source
baseline — STATE; last fullgate покрывает unchanged343 application sources, не новый full gate
без code change. Последний SDK probe не доказывает освобождение GPU.
Датированные research/reviews и архив не являются активным планом.
Документальная запись goal не доказывает работающий фоновый goal.

## Сохранённый runtime scope — 2026-10-05

После обзора владелец попросил развивать перспективные направления и
подтянуть модель. Работа над отдельным VRM-кандидатом возобновлена; выбирать
проверяемые небольшие срезы, сохранять активный аватар и прошлые артефакты.
Последнее уточнение владельца: в первую очередь закрыть видимые стыки
«кисть–манжета» и «штанина–ботинок», включая сгибы, а не только проверить веса.
Текущий срез — Interface V9 поверх Hair V8 и scene handoff/Stop lifecycle.
Нужны подогнанный контур, перекрытие краёв и согласованные веса; простое Join
объектов не устраняет щель. Сходство волос/одежды и полная физика ещё открыты.
Последняя проверка — верх STATE.
Выводы исследования: `docs/RESEARCH_3D_AI_NEWS_AIRI.md`, очередь — верх TODO.
Не переносить whole AIRI/второй мозг или тяжёлые authoring зависимости ради
названия; кодовые заимствования сравнивать с уже лучшими контрактами Companion.
Новые модели/провайдеры не подменять скрытно. Старый delivery goal не завершён.

## Миссия и порядок чтения

Актуальная продуктовая граница: Companion — оболочка Electron со сценой VRM
(three-vrm), голосом и веб-панелью; визуальная среда — 3D VRM. JAWL остаётся
единственным агентным контуром. Актуальное состояние: `docs/STATE.md`;
последний model slice: `docs/CHARACTER_INTERFACE_V9_REVIEW.md`;
историческая поставка: `docs/CHARACTER_DELIVERY_20261004.md`.

Целевой delivery plan: `docs/PRODUCTION_DELIVERY_GOAL.md`. При моделировании
обязательно читать `docs/CHARACTER_ART_DIRECTION.md`: blocking до деталей,
90% likeness — цель с рубрикой и приёмкой, не автоматически измеренный факт;
физика helpers не равна завершённой физике ткани/тела. Модель лично ведёт
координатор, code slices делегируются с непересекающимися write scopes.

Строим **одну платформу агента-компаньона**, не три несвязанных приложения.
JAWL: личность, Heartbeat/ReAct, долговременная память, задачи и нативные
инструменты; Companion: Electron/VRM, голос и веб-панель; VoiceMem: восприятие/контекст.
Не вырезать agentic контур из продукта и не заводить второй мозг.

Перед существенной работой полностью прочитать:
`docs/PRODUCT.md` → `docs/STATE.md` → `TODO.md` →
`docs/TECHNICAL_AUDIT.md`; для изменяемой границы — архитектуру/контракт.
Для стабилизации также прочитать `docs/RECOVERY_PLAN.md`: порядок B0–B4,
сохранённые recovery-инварианты и запрет подмены полноценного агента
ограниченным диалоговым профилем. Исторический R1–R4 не вторая очередь.
Уменьшение prompt-каталога не должно
отключать discovery или подменять native policy глобальным HostOS blocklist.
Проверить `git status --short --branch`, выбрать один проверяемый срез.
История и CHANGELOG не переопределяют текущую очередь/замысел.
Последнее явное поручение пользователя задаёт scope: просьба править только
доки не разрешает запуск/изменение runtime даже при старом большом goal.

## Обязательные продуктовые решения

- Русское общение голосом/текстом с одной личностью и памятью, настраиваемые
  черты/факты, уместная инициатива, реальные поручения на ПК.
- HostOS levels 0–3; Full Access + unattended для автономной работы ночью —
  обязательный режим. Не вводить per-action prompts для уже разрешённых
  действий этого профиля. Политику исполняет JAWL; стоп/исключения/ОС сохраняются.
- Веб-панель в мятном Windows Aero стиле; desktop-оболочка Electron с
  VRM-сценой и панелью. OBS-поверхность сохраняется. Адаптивный веб-интерфейс
  для телефона/планшета и LAN-доступ явно запрошены владельцем.
- Текущая аватарная реализация — 3D VRM в Electron (`desktop/`, three-vrm);
  Live2D/Mocari удалены по ADR-045. Не описывать продукт как 2D-only.
- OmniVoice (9890, ref-голос, cuda:1) — текущий синтез по умолчанию
  (решение владельца 13Oct, ADR-047). TeraTTSv2 (ru_f1, 9889) остаётся
  выбираемым провайдером.
  Prosody planner (gemma-3-1b,
  8987) опционален и может быть отключён ради меньшей задержки голоса.
  Qwen3-TTS — non-default source-level adapter/research capability, не выбранный
  production-профиль. VoxCPM также имеет optional code path без смены дефолта.
- GigaAM v3 (crispasr, batch final + streaming partials) — канонический и
  единственный ASR
  движок (решение владельца 2026-09-21: фолбэк не нужен). Provider-путь
  `--asr-url/--asr-model`, бэкенды Qwen3-ASR/whisper и «fallback lane» удалены;
  буфер реплики (`UtteranceBuffer`) — часть ядра, а не второй движок.
  ASR не описывает музыку/тембр/настроение без отдельно проверенной capability.
- Vision-профиль: Bonsai (8986) + screen-watch + PerceptionFusion; наличие
  кода/профиля не равно current RU OCR/grounding/action-loop acceptance.
  `run_coding_server.ps1` поднимает старый Bonsai Q1, не Hikari brain;
  Основные PS/Python/Electron defaults сведены через manifest (B0); Rust parity,
  whole-profile/live/effective UI acceptance остаются OPEN. Тяжёлые модели
  не менять скрытно.
- Текущий выбранный brain — Bonsai-2 27B Hikari PQ2_0 на GPU1.
  Big Pickle/OpenCode — исторические тестовые providers. Будущий QWB/cloud/local —
  за JAWL provider contract, не direct Companion LLM как второй агент.
- Ambient system audio/screen — отдельная низкоприоритетная память.
  Целевой обычный профиль: чувства включены после первичной настройки источников,
  наблюдения записываются автоматически, консолидацией владеет JAWL.
  Ручной review не вечный предел; нынешний opt-in код не считать уже изменённым.
- Меньше зависимостей и дублирования, bounded RAM/очереди, понятный код.
  Не оптимизировать число строк ценой тестов, lifecycle и trust boundaries.

## Эволюция согласованного ядра

JAWL — исходная основа, не неизменяемый black box. Развитие принадлежит нашему
owned runtime/version после решения P0-A; protected reference не трогать.
Не сохранять дублирующие механизмы только потому, что они есть в двух upstream.
Сначала карта ownership/перекрытий и общий feedback cycle, затем изменение.

Биология/психология — аналогии, не лицензия на усложнение. Не добавлять
независимые агенты/планировщики на каждую эмоцию/«отдел мозга». Один decision
owner, bounded state/context, сенсорные workers без собственной личности,
coherence E2E: память действительно меняет ответ, инструмент меняет состояние
задачи, голос/аватар выражают одно решение. Неизмеримое «стало более живым»
не закрывает задачу; автоматическое переписывание кода/прав сюда не входит.

## Scope файлов и внешние зависимости

Наш единственный development repo: `G:\AI\JAWL-VoiceCompanion`.

Read-only reference/upstream, если пользователь отдельно не разрешил изменения:

- `G:\AI\JAWL-Coding` — JAWL;
- `G:\AI\VoiceMem` — VoiceMem;
- `G:\AI\_tmp\soul-of-waifu`;
- `G:\AI\_tmp\companion-repos\Open-LLM-VTuber`, `Warashi`, `Miru`,
  `Mana`, `AniCompanion` — исследованные patterns.

Запрет upstream write включает запуск тестов/приложений, создающих там
pycache, data, logs, config, runtime или меняющих рабочий экземпляр через API.
Для live tests нужен согласованный отдельный runtime с отдельными config/
data/log/cache/env. Вывод нового fork/dependency за существующий scope
согласовать; не переносить грязный checkout и секреты автоматически.

`G:\RE` — внешняя нативная toolchain, не наш build/temp root.
Не заменять junctions `x64dbg`, `x64dbgMCP-source`,
`ghidra_12.1.2_PUBLIC` независимыми копиями. TTD EULA и UAC не принимать
за пользователя. Модели/рефы/лицензируемые ассеты не копировать в git.

Dirty changes принадлежат пользователю/предыдущим итерациям. Не делать reset/
checkout/delete, массовый commit и не приписывать авторство по timestamps.

### Правило совместимости: не перезаписывать лучшее

Перед переносом любого поведения из JAWL/VoiceMem сравнивать контракт, ошибки,
границы безопасности, latency и regression evidence. Если реализация Companion
уже полнее или лучше подходит сценарию компаньона, сохранять её и добавлять
только адаптер совместимости; если upstream покрывает capability лучше —
подключать upstream как owner. Нельзя заменять рабочий код только ради
одинакового внешнего вида или механического совпадения с JAWL. Решение и
причина фиксируются в `docs/JAWL_CANONICAL_CAPABILITIES.md` или техническом
аудите, а поведение подтверждается тестом.

## Дисциплина контекста и квоты

Показывать короткие дельты, не полную историю; ограничивать вывод и поиск;
не дублировать delegated work и не повторять неизменившиеся gates. Использовать
немного параллельных агентов; при низкой пользовательской квоте не начинать
новую работу. Приоритеты — correctness, security и required tests; не обещать
фиксированный процент экономии токенов.

## Архитектурные инварианты

1. Один canonical owner persona/facts/tasks/policy — JAWL. VoiceMem и
   Attention поставляют observations/SPEAK_INTENT, не меняют характер напрямую.
2. Все model-originated side effects идут через native JAWL policy/registry,
   включая HostOS, Terminal, Debug Broker, MCP/browser. Bridge outage не даёт
   права использовать локальный executor. Standalone/mock только явно.
3. JSON envelopes versioned/validated/bounded. Model fields не дают полномочий.
   Media может идти bounded binary/base64 по контракту; JSON — не догма для PCM.
4. Priority/cancel/reconnect должны сохранять correlation и task state.
   Stale output отбрасывать; replay dedup не равно exactly-once mutations.
5. Факт имеет источник/время/уверенность и correction/forget path.
   Always-in-context память ограничена, остальное retrieval.
6. Ambient не USER_FINAL и не инструкции. Screenshots/web/files/tool results —
   недоверенные данные; model inputs не получают authority от их содержимого.
7. Capture в целевом профиле включён после явного первичного выбора источников
   и разрешений ОС/браузера: visible, bounded, pause/revoke, sensitive drop,
   без raw persistence. Mixed WASAPI не даёт надёжной per-app attribution.
   Документирование defaults не разрешает начать текущий захват устройств.
8. Remote text LLM не означает согласие передавать ей PCM/screenshots/ambient.
9. Control и presentation — separate origins/capabilities, loopback по умолчанию.
   Явный LAN-режим владельца: HTTPS и вход на control; не убирать CSRF/origin.
   Непроверенные avatar scripts/assets не загружать в privileged UI; один audio owner.
10. Full Access — права текущего Windows аккаунта, не обход OS/EULA/ACL.
    Текущий lease механизм должен обслуживать ночной профиль и показывать срок.
11. Хранить короткие полезные summaries, не скрытый chain-of-thought.
    Audit metadata redacted/bounded, без raw TTD и credentials.

## Безопасность работы над проектом

- Не читать/печатать `.env`, API keys, токены или process commandlines с секретами.
  Секреты из чата не повторять, не встраивать в docs/fixtures.
- По умолчанию loopback: control 2367, presentation 8766; 8765 — FoxMCP.
  Для планшета разрешён явный LAN-профиль; см. `docs/LAN.md`.
  Конфликт порта означает отказ/другой порт, не убийство его владельца.
- `scripts/run_target_jawl_smoke.ps1` **не применять** без отдельной review и
  acceptance owned layout/loader/cleanup. Исторический A3 не считать новым
  воспроизведением: code guards уже есть, это не доказывает live safety.
- Тесты actions — disposable fixtures и явный opt-in; не рабочие файлы/приложения.
  Каталог всех tools не требует опасного live выполнения каждого из них.
- Cleanup только доказанно собственных процессов/путей; проверять resolved
  targets, process identity/creation time. Не удалять broad workspace.
- Не создавать goal без явного запроса. Старый goal не расширяет текущую задачу.
  Если нужен новый scope/внешнее разрешение, остановить этот шаг и спросить.

## Проверка качества и передача

Major runtime update: `scripts/run_full_gate.ps1` + весь основной browser E2E
сценарий и затронутые live rows из аудита. Fake HTTP gate не заменяет
browser interactions/скриншоты, реальную модель, устройство и OBS.
Для docs-only: link/consistency check + `git diff --check`, без live launches.

При каждом evidence фиксировать profile/run ID, версию/dirty diff, вход,
ожидание/факт, дату, pass/fail/skip, exit code и redacted report.
Отдельно: unit, fake HTTP, synthetic media, real provider, real device.
`configured`/HTTP 200/`queued`/DOM marker не equals ready/ingested/красиво.

Долгую command session отслеживать до exit с её ID. Потерянный stdout не
считать pass, orphan-runtime bug или поводом бесконечно перезапускать gate.
Не повторять одинаковые сборки/зелёные тесты без новой гипотезы/изменения.

После среза:
- TODO — статус только проверенного результата;
- STATE — короткая сводка, что изменено/проверено/ограничено, следующий шаг;
- CHANGELOG — существенное изменение; DECISIONS — изменившийся выбор;
- оставить reviewable diff, без посторонних правок.

Не объявлять RC до целого daily scenario, production-ready до полной
применимой матрицы и пользовательской приёмки. Называть реальные пробелы.

<!-- BEGIN: CodeSee integration -->
## CodeSee 功能图

本项目用 CodeSee 把功能逻辑以语义流程图呈现。
数据在 `.codesee/features.json`，由你（AI）维护。

### 触发规则

**触发 1：首次扫描**
若 `.codesee/features.json` 不存在或缺少 `version` 字段：
→ 执行 `.codesee/prompts/scan.md`（会自动判断走 light / heavy / planning 哪一档）

**触发 2：每轮代码改动后**
完成改动后，在回复用户前主动：
→ 执行 `.codesee/prompts/sync.md`

跳过条件：纯样式/重构/重命名，或用户明确要求跳过。

**触发 3：用户显式要求**
"刷新功能图""更新 codesee""扫一下" → 按上述策略执行。

**触发 4：生成导览（仅显式要求，不自动跑）**
用户说"生成导览""加个 tour""给新人做个引导" → 执行 `.codesee/prompts/scan-tour.md`，
为 `features.json` 写一条引导式导览（tours 字段）。**绝不在 scan/sync 流程里自动触发。**

### 项目阶段

CodeSee 同时支持四种阶段：

- **SDD 项目**（有 `.specify/` / `.trellis/` / `.bmad-core/` / `.agents/skills/` 等）→ scan.md 路由到 `scan-sdd.md`，**直接消费 spec/PRD 文档**，不读源码（最准确、最省 token）
- **规划阶段**（只有文档，没代码）→ scan.md 会路由到 `scan-planning.md`，产出"规划版" features.json，所有 feature 标 `tags: ['planned']`
- **实现阶段**（有代码）→ scan.md 路由到 light/heavy，产出正式 features.json
- **混合阶段**（部分实现）→ sync.md 自动把 `planned` 的 feature 升级为 `implemented`

### Checkpoint 协议（重要）

大任务（涉及 5+ 文件）必须拆成 checkpoint，**每完成一个逻辑闭环立即 sync**，不要等全部写完才一次性更新。

- 逻辑闭环 = 用户能感知的、可独立验证的小功能（如"添加购物车 API + 表 + 按钮"）
- 流程：实现闭环 1 → sync → 实现闭环 2 → sync → ... → 最终整体核查
- 全部完成后必须做最终核查（覆盖度 / 关系 / epic_flow / refs 准确性 / 跑校验器）

详见 `.codesee/prompts/sync.md` 的 "Checkpoint 协议" 章节。

### 核心约束

- ❌ 不修改 `.codesee/prompts/` 与 `.codesee/scripts/` 下的文件
- ❌ 不修改 `locked: true` 的 feature
- ❌ 不重命名既有 id（废弃用 tags: ['deprecated']）
- ❌ 不跳过校验
- ✓ step.name 必须用 manifest.lang 指定的语言写动词短语
- ✓ flow.kind 必填
- ✓ 写入后跑 `node .codesee/scripts/validate-features.mjs`，退出码 1 必须修

### 参考文件

- Schema + 示例：`.codesee/prompts/_schema.md`
- 规则详情：`.codesee/prompts/_rules.md`
- 扫描：`.codesee/prompts/scan.md`
- 同步：`.codesee/prompts/sync.md`
- 导览生成（实验性，仅显式调用）：`.codesee/prompts/scan-tour.md`
- 校验：`.codesee/scripts/validate-features.mjs`
- 增量补丁：`.codesee/scripts/apply-patch.mjs`（sync 优先模式）
- 数据：`.codesee/features.json`
- Hooks（可选自动提醒）：`.codesee/hooks/README.md`

> 执行 scan/sync 前先告诉用户你要做什么。
<!-- END: CodeSee integration -->
