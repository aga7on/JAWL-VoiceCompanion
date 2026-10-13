# Текущее состояние JAWL Companion

## 14Oct — context gate PASS, R6 запущен на frozen baseline

Gate23657 TERMINAL/exit0:875unit/66pytest/16HTTP/104Node +browser6/desktop8,
log+receipt gate-turn-context-20261014.{log,json}; original362 hashes unchanged.
Synthetic regression, not live acceptance. R6 started exec1688, report
`live-voice-turn-context-20261014-r6.json`, same isolated profile/models/WAVs,
strict draft+single-pass fake audio+owned context binding. Deadline480s and8GiB
floor, own Jobs; do not duplicate/restart/change app while active. New outcome
not yet available; previous R5 failure retained. All agents closed.

## 14Oct — R5 FAIL/cleanup PASS; context binding wired +noloop; gate running

R5 exec69826 TERMINAL/exit1. First turn required draft gate PASS:12 exact preview
samples, content max49, scoped streaming fetches12, cleared after end/no late
preview; TTS1/full non-silent2.68s/EOF. Second turn native events95=turn.started,
96=turn.error, voice/end HTTP200 at11.089s; no TTS. Capture diagnostics empty.
SuiteFAIL, not B2-01 acceptance. Browser Job drained/supervisor stopped, all5
listeners absent AND bind available; original360 hashes unchanged, guard no fault.
Reports `live/browser-voice-strict-draft-diagnostics-20261013-r5.json` retained.

Separate harness defect: second voice/end appeared at161.051s after the original
at6.547s. Chromium fake WAV loops without %noloop; source confirms single-pass
suffix (media/base/media_switches.cc, official Chromium). Changed option to
%noloop,23 harness tests PASS. This removes repeated synthetic input during long
wait, does NOT explain/fix native turn.error preceding the repeat. Do not claim
all historic flakes are replay or headless faults.

Owned turn-context provider now installed by launcher;12 context (including exact
native budget methods) +13 launcher tests PASS3.14/3.11. Actual console probe
`owned-console-turn-context-20261014.json` PASS/runner0, marker confirmed,
startup2.164s, auth401/cancel200/tombstone409, exact Job listener33868/launcher15172,
listener gone. Launcher terminated by Job/exit1 expected, not graceful0.
No agent/model/device in that console probe. Tight native budget can truncate
binding; no retention/model-compliance guarantee from these tests.

Baseline362 `baseline-turn-context-20261014.json` SHA6721866f391c0236fa5f6b6dfb933afcb78de0063dd72eb459952d49a6ce5610.
Fullgate session23657 RUNNING/log gate-turn-context-20261014.log. All agents closed.
R6 runtime runner prepared newtag/baseline362/strict draft/noloop, NOT run. Next:
await gate terminal, then one bounded R6 with current models/avatar unchanged.
CodeSee modified1/27, validator0/61 historical style warnings.

## 14Oct — diagnostics gate PASS, R5 запущен; context ambiguity найдена

Fullgate97728 TERMINAL/exit0:861 unit/66pytest/16HTTP/104Node +browser6/desktop8.
Persistent log+receipt `gate-strict-draft-diagnostics-20261013.{log,json}`;
360 original source hashes unchanged after gate. Synthetic, не model acceptance.
R5 запущен exec session69826, owned runner report
`live-voice-strict-draft-diagnostics-20261013-r5.json`; только fakeWAV, protected
read-only/OmniVoice/current GPU1 brain unchanged. Не дублировать run/не менять
app inputs пока идёт; guard deadline480s/RAMfloor8GiB/exact Jobs.
Runtime ready proof: instance953db7f2bb5a48438ff733f92e4dd272, launcher32824;
2367/8766 pid15296,8770 pid29416,8990 pid21656,9890 pid34892, all owns_pid=true.
Browser27448 running strict_browser_turns; no result yet, not acceptance PASS.

Read-only discovery corrects earlier broad inference about context retention:
loop passes original event/payload to context_builder EVERY step, НО native
ContextBuilder._heartbeat_provider after step1 explicitly archives original
trigger and emits CURRENT=HEARTBEAT/empty payload (builder.py577–587).
Это возможный ambiguity source для observed reply loss, не доказательство всех
failures, особенно не transport TypeError. Protected code не редактируется.
Ohm `01a13715-86fd-7a51-9e96-21c7dab408cf` готовит NEW owned turn-context
provider/tests через native registry+budget, без launcher wiring и model run.
Интегрировать только после R5 terminal/review; context fix НЕ входит в R5.
Далее: Ohm завершён/закрыт; main reviewed provider +11 tests PASS3.14/3.11.
`native_jawl_turn_context.py`/tests существуют, НЕ wired/NOT inputs R5. Build
wrapper registers fixed-size INTERFACES provider once per native registry,
only valid payload turn_id matching native active context; no user text/CoT,
no append-after-budget. Collision fails closed, no global registry-instance
collection. Tests use injected native API plus exact archived-heartbeat AST;
actual launcher imports/native compaction/model adherence ещё не проверены.
Next after R5: integrate owned launcher +actual isolated console probe, native
budget fixture, fullgate/new baseline before testing model hypothesis.

## 14Oct (Москва) — strict draft gate reviewed, новый fullgate running

Raman завершён/закрыт. Main22 harness tests PASS: exact scoped streaming content,
exact DOM prefix, raw content<=160 across ALL samples, no late reappearance,
post-final clear, required flag fail propagation; optional mode не маскируется
как required acceptance. Collector accepts bounded20 sanitized capture events,
unknown app error class preserved; malformed/extra sensitive fields rejected.
Это fixtures, НЕ новый live preview PASS. App lifecycle/helper34 Node PASS.

Frozen baseline360 `baseline-strict-draft-diagnostics-20261013.json` SHA
d365b1ed2b3fdea8f35e51637d02c4b378bba4ec89e181984b0bf56f98f2cbad.
Artifact names retain20261013 UTC run tag; user-facing checkpoint now14Oct Moscow.
Fullgate session97728 RUNNING, log `gate-strict-draft-diagnostics-20261013.log`.
Не перезапускать пока handle жив. Runtime runner имеет новый tag
strict-draft-diagnostics-20261013-r5/current baseline и --require-draft-preview;
пока НЕ запускался. OmniVoice/default avatar сохранены.

Read-only heartbeat check: native heartbeat awaits _active_react_task; searched
entry path is serialized. Это не доказательство параллельной ReAct гонки в
старом fail и не оправдание замены owner. Модельный delivery failure остаётся
отдельно от transport failure capture. После gate: bounded r5 с диагностикой,
никаких слепых повторов при том же failure без новой гипотезы.

## 13Oct — redacted capture diagnostics реализована, strict draft gate review

app.js при audio upload failure публикует bounded `jawl-voice-capture`: fixed
reason (transport/http/backpressure/other), allowlisted error class/status,
AudioContext/track state, queue<=6, worklet counter и last-frame age. Никаких
error.message/PCM/transcript/capture_id/credentials. Ошибка самой диагностики
не блокирует stopMic.18 actual-function lifecycle +16 helper Node PASS, включая
TypeError/HTTP409/queue overflow и sentinel-redaction. Не root-cause fix старого
сбоя и не гарантия исправления network path. Новый fullgate ещё не запускался.

Raman добавил explicit `--require-draft-preview`: exact prefix/content/scoped
fetch/timed clear assertions,18 controlled harness tests PASS main. Review
обнаружил any-clear→late-preview и mixed oversize loopholes; доработки +bounded
capture event collector запрошены агенту в его прежних двух файлах. Live повтор
без завершённого review/new baseline запрещён; B2-02 partial.
CodeSee modified1/27, validator0/61 existing style warnings.

## 13Oct — review новых OmniVoice/live изменений: acceptance уточнена

Read-only review подтвердил новый default OmniVoice, prompt delivery-after-failure,
новые live attempts и full-gate-omnivoice exit0/log:844/66/16/103 +browser stages.
Protected snapshot348/SHAfa7587eb… intact. Относительно frozen Omni baseline360/
79226e1b… изменён browser voice harness;5 existing harness tests PASS, не новый
fullgate текущей версии. RESPOND_DIRECTLY SHAa7842e3c… отдельно (MD вне source lock).

Attempt7 metadata: turn3 /api/voice/audio запросы1..19 HTTP200 (последние около
3–4ms); запрос20 started2092.7ms, status/null, ended/null, error=TypeError.
voice/end0, draft2, mic_status в diagnostics «Микрофон выключен.». app uploadChunk
при fetch failure вызывает stopMic. Поэтому headless/AudioWorklet freeze НЕ
доказанная причина: есть transport failure и штатная остановка capture. Следом
нужна диагностика browser fetch/network/server cause, не новый слепой model run.
Сырые CoT/содержимое запросов в этот review не копировались.

Cleanup attempt7: browser_job_drained=true, supervisor_stopped=true, но
ports_gone9890=false. Исторический отчёт не изменён. Сейчас listeners на всех
2367/8766/8770/8990/9889/9890 отсутствуют, не доказательство состояния в тот момент.
Runtime diagnostic теперь различает listener_absent и bind_available: bind
может отказать из-за TIME_WAIT.2 controlled cases PASS (no listener/bind failure;
existing listener/bind success). Это устраняет ошибочную интерпретацию будущих
отчётов, НЕ доказывает TIME_WAIT как причину старого false. Архивные log paths
в reports указывают на прежние имена; actual файлы имеют suffix attempt7-omnivoice.

B2-02 возвращён partial: preview telemetry допускает generic status и не является
обязательным assertion.16 helper/actual-function VM evidence сохраняется; strict
draft gate делегирован Raman `01a13707-c6d3-7873-a348-cbb61ea9ea2a` с disjoint
scope scripts/run_browser_voice_e2e.py +tests/test_browser_voice_harness.py.
Новые модели/захват/повтор live suite в этом review не запускались.

## 13Oct — TODO sweep: закрытия и точные остатки (новейший)

Автономный проход очереди после OmniVoice-переключения. **Закрыто по evidence:**
B3-08 (terminal status/reconnect/no-replay в gate; исторический503 закрыт в history:
bounded Ollama transport failure, не воспроизводится, test_e2e16/16, «external cause
remains unproven» = диагностический риск); U-02 (11 ConfigHub unit + browser settings
acceptance в gate); B1-04 (audio-owner принят: DECISIONS + `test_lease_renews_expires_
and_requires_matching_identity` + busy-owner rejections); B0-03 (5× live-стартов whole
owned профиля из C:\ 13Oct, owner-записи; gate busy-port/foreign-cwd без моделей).
**Уточнено/частично:** B0-02 (overview отдаёт model=local-bonsai2/persona/access, но
context/profile readback отсутствует; `"omnivoice": TeraTTSHttpClient` в composition —
по контракту ADR-045; `runtime/b0-02-*`); B3-02 (политика REASONING_POLICY есть,
поведение-верификация открыта); B3-03 (heartbeat deferral на safe boundary + proactive
tests); B3-04 (отдельные звенья в test_e2e; полный сценарий открыт); B3-05 (goal
сохранён при TTS-stop/turn-cancel — тест в gate; live provider-failure открыт);
B3-06 (live-матрица требует operator token — не читаем; fixtures есть); B3-07 (только
доки); P-01 (live counts всех слоёв + endpoints; per-type acceptance открыто); P-02
(restart-survivability покрыта; влияние факта на ответ открыто); P-03 (политика в
доках; erasure-пайплайн/тест открыты); U-01 (capabilities-снимок снят; per-row
registry открыто); U-03 (reconnect/cancel/history живо; pagination не найден);
U-04/U-05/U-06 (attachments нет; memory-вид есть; tasks-панель — частично);
U-09 (OBS — owner until machine with OBS); B4-02 `runtime/budget-20261013.json`
(RAM/VRAM/модель/тайминги; frame-time/OBS/install/soak не мерены); B4-05 (secret scan
PASS daily; ключи — owner). **Owner-pending** (пропуск по указанию): B2-04/05/06,
A-02..06, U-07/08/09, S-01/02, B4-01.

## 13Oct — OmniVoice по умолчанию + strict r4 attempts4–7 (предыдущий)

Владелец переключил голос на OmniVoice и подтвердил живьём («слышу озвучку»).
Default: `config/runtime.manifest.json` → `launch.tts_provider="omnivoice"` (оба
launcher'а читают манифест; TeraTTSv2 остаётся выбираемым `-TtsProvider tera`,
9889). Новый frozen baseline360 `baseline-omnivoice-20261013.json` SHA `79226e1b…`
(манифест входит в baseline). Runner обновлён: PORTS→9890, убран hardcoded
`-TtsProvider tera`, browser timeout75→150; prompt `RESPOND_DIRECTLY.md` усилен
(«после failed tool — доставка ответа в том же turn») и перестажирован в профиль.

Attempts: 4 (prompt-fix, Tera): turn1–2 PASS полная озвучка/EOF, turn3 время.
5: preflight `application_baseline_changed` (ожидаемо — новый baseline). 6:
hardcoded tera9889 vs PORTS9890. **7 (OmniVoice)**: exact Job владеет
2367/8766/8770/8990/**9890** (pid19064), turn1–2 PASS: tts_req1, playback
2.68s/3.24s, EOF; turn3 — app/headless-флейк: 20 realtime-чанков, затем ворклет
перестал отдавать данные (mic «включён», gate closed, drafts2), `voice/end` не
отправлен. Класс turn3: длинный «статус»-ход (>75/150с в разных прогонах) и
замирание захвата на 3-м headless-сеансе. Отчёты `…attempt{1..7}*` сохранены,
порты/дерево после прогонов чистые. Повтор suite без новой гипотезы — не запускать.

Regression: `full-gate-omnivoice-20261013` **exit0** (844unit/66pytest/16e2e/103Node
+ browser6/desktop8, все стадии PASS, `git diff --check`0) — переключение дефолта
gate не сломало. B2-02 e2e: проба `browser-voice-draftprobe-20261013.json` PASS
на OmniVoice — 13 `/api/voice/draft` mode=streaming, текст рос 0→8→…→49,
26 DOM-семплов превью (max73≤160), очистка после финала, озвучка2.36s+EOF.
B3-01: envelope последнего turn полный (`runtime/b3-01-envelope-20261013.txt`):
response_id/turn_id/text/speak/emotion/avatar/voice/actions/interruptible/proactive,
«Уже запомнил: любимая еда — Паста.», actions0. B2-03: серия n=14 (first-audio
p50 11.8с/p95 35.2с); попытки b2-03b r1/r2 упали на turn1 TTS-wait (тот же
heartbeat/no-terminal класс) — надёжность voice-turn остаётся ограничением.

## 13Oct — strict r4: Selenium env фикс + heartbeat-флейк (предыдущий)

Runner `runtime/run_strict_delivery_probe.py` (baseline360 r2): браузерному child
добавлен `browser_environment()` — user-site (host Selenium) только для browser-
обёртки; `PYTHONNOUSERSITE` для остальных детей сохранён. Attempt1 без фикса —
`selenium_import:ModuleNotFoundError` (сохранён `…-r4-attempt1-selenium*`).

Attempt2: owned runtime healthy, turn1 принят полностью — completion-aware:
TTS request1, playback_completed_nonsilent3.42s, EOF=true; turn2 — агент подхватил
остаток «статус»-контекста (heartbeat-ответ14:56:05), коррелированный turn без
terminal-события → guard дал `turn.error` → нет TTS. Attempt3: turn1 — модель на
step1 пишет «Turn delivery required», `remember` падает (ключ уже есть), step2
переосмысляет как «Heartbeat tick; no user-facing reply required» → «Empty actions
list» → `turn.error` (seq34-38). Отчёты `…-r4-attempt{2-interleave,3-heartbeat}*`,
evidence-каталоги там же; порты после прогонов свободны.

Класс флейка (совпадает с утренними ≥4×): после провалившегося tool-вызова
продолжение turn теряет обязательство «отдать terminal-ответ» и закрывается молча;
RESPOND_DIRECTLY.md (уже в strict-профиле, c `_companion_turn_id`) это не удерживает.
Guard корректно превращает в bounded turn.error, fabrication нет. Повтор strict
suite OPEN: предпочтителен fresh-профиль (текущий несёт остатки прежних прогонов)
и/или prompt-fix «после tool failure — reply в текущем turn».

## 13Oct — draft gate r1 FAIL/VM import fixture, исправлено; r2 running

Gate session29814 terminal1: Python844/pytest66/HTTP16/legacy browser прошли,
Node lifecycle tests не запускали mic из-за нового dynamic import в VM без
loader mapping. Actual synthetic Edge run ранее PASS; это не повод игнорировать
fixture. Исправлен только VM module mapping с реальным draft-controller и fake
clock. Новый тест actual app function bodies проверяет scoped request, bounded
preview, отсутствие chat persistence и очистку finalization/Stop.33 focused
Node checks PASS. Full gate теперь включает voice-draft.test.mjs явно.

New baseline360 `baseline-voice-draft-20261013-r2.json` SHA3a957f2f…;
runner обновлён на него. New gate session35608 running, persistent log
`runtime/gate-voice-draft-20261013-r2.log`; не rerun пока handle жив.
Модельный live run по-прежнему НЕ запускался; browser draft-content/stale DOM
проверки и реальные partial/voice latency ещё OPEN. Никакого production PASS.

## 13Oct — live runner review/preflight исправлен, модели ещё не запущены

Main reviewed runtime/run_strict_delivery_probe.py: исправлены синтаксис cwd,
scripts import path, old358→current360 baseline, неподдерживаемый resolver --json,
self-created report collision, Selenium offline env, cleanup failure→failed.
Read-only preflight/import smoke PASS:360 hashes match, CUDA1/64k resources/ports
and existing isolated embedding/WAVs verified. Это НЕ live/model acceptance.
Runner остаётся runtime diagnostic (не reusable production entry); после gate
session29814 terminal проверить ресурсы снова и выполнить один bounded run.
Модели/дефолты/active avatar не переключались.

## 13Oct — draft consumer подключён к `/app`, synthetic browser PASS

Luna helper16 tests и main capture13 tests PASS; real HTTP asset route test PASS.
app.js polls existing `/api/voice/draft` every350ms, single-inflight, own abort;
captured lease/session/correlation/generation stale fence, transient text<=160
в mic status, full helper bound2000. Stop/finalization abort+clear, optional
unavailable/error lane не останавливает final ASR. Никакого partial→memory/final.
Static `/voice-draft.js` served explicitly; app.html uses overflow-wrap:anywhere
для длинного неделимого текста, без новой палитры/компонентного фреймворка.

`runtime/desktop-voice-draft-20261013.json` terminal0/PASS,8 prior browser checks:
real `/app` capture/lease/upload/ordered PCM TTS cancel/replacement, mockbrain,
synthetic oscillator+tone only. Screenshot просмотрен; он показывает voice
settings, НЕ preview during speech. Harness не проверяет draft content/stale UI,
это ещё OPEN, как actual GigaAM partial model latency и physical mic.
CodeSee modified1/27, validator0/61 existing warnings. Previous fullgate844
предшествует wiring и не подтверждает изменённые inputs; нужен новый gate/baseline.

Laplace подтвердил ничего не запускалось; создан только
`runtime/run_strict_delivery_probe.py` со старым358 baseline, НЕ запускать без
review/update. Агент закрыт. Предыдущий r4 pending checkpoint ниже исторический.
OBS/AV RAM ring buffer сохранён как S-03 candidate, никаких capture/downloads.

## 13Oct — следующий strict live run делегирован, partial UX gap подтверждён

После terminal gate проведён resource preflight: пять целевых портов свободны,
GPU1 363MiB/16303, RAM available66992788KiB. Luna-agent Laplace
`01a134e6-2b02-70c0-9503-bff1e44ae011` готовит один bounded real-model run
`strict-delivery-20261013-r4` в прежнем isolated seeded profile, только fake WAV
input. Пока отчёт/terminal outcome отсутствуют, считать запуск/успех непроверенными.
Не дублировать run; дождаться конкретного agent/process/report.

Независимый read-only code audit B2-02: app.js uploadChunk только проверяет status,
не читает JSON; external_final `/api/voice/audio` отдаёт events[]. `/api/voice/draft`
реализован, но `/app` его не потребляет и не подписан на WS. Live partial UX
на этой поверхности фактически отсутствует. Это отдельный следующий bounded
consumer/stale-drop slice, НЕ основание добавлять ещё один ASR или считать
USER_PARTIAL из voice/end доказательством отображения во время речи.
Контракты jawl/voice актуализированы под guard и consumer-инварианты; diff-check0.
Отдельный Luna-agent Peirce `01a134e8-9837-77b0-8969-b8b3df63568e` готовит
только новые `desktop/voice-draft.js`/tests, без wiring в app.js и без запуска
моделей. Применение в UI отложено до завершения Laplace run; draft не memory/final.
Helper теперь существует; main independently ran16 Node tests PASS после review.
Добавлены pre-dispatch Stop fence (tick microtask не запускает request после stop)
и finite-positive timeout<=30s validation. Peirce завершён/закрыт. Node сохраняет
прежний MODULE_TYPELESS_PACKAGE_JSON warning; package type ради него не менялся.
Helper НЕ импортирован/НЕ served: web.py explicit asset map ещё требует
`/voice-draft.js`, плюс integration tests asset/request/lifecycle и UI preview.
CodeSee не расширялся под неприсоединённый helper. Baseline358/gate остаётся
проверкой прежних application inputs, не приёмкой нового helper/wiring.
У Laplace запрошен immediate phase/handle update: runner/report пока отсутствуют;
не считать разговор/намерение доказательством начатого model test.

## 13Oct — owned completion guard подключён, regression PASS

`native_jawl_delivery.py` установлен только через owned console entry после
isolation/snapshot verification. Guard наблюдает подтверждённые terminal events;
завершение correlated cycle без ответа даёт fixed bounded turn.error вместо
ожидания outer timeout. Success/cancel/background и native goal state не подменяет.
Native `_handle_completion` сохраняет private tick/status, но его thoughts-final
envelope удаляется до создания EventBus handlers. Никакого fabricated ответа.

Review первого варианта обнаружил отсутствие этого suppression. Независимый
AST-extracted exact snapshot test сначала FAIL/assistant.final, после исправления
PASS.11 focused guard/snapshot +12 launcher tests PASS на3.14/3.11 с `-B`.
Native EventBus создаёт задачи при publish и наследует context; pre-existing
worker concern не подтверждён для текущего snapshot. Protected348/SHAfa7587eb…
проверен неизменным стартом gate.

Full regression `scripts/run_full_gate.ps1`, exec session31873 TERMINAL/exit0:
844 unit /66pytest /16HTTP /6legacy browser /8desktop checks. Node stage
passed checked command; count не сохранён в truncated stdout. Receipt
`runtime/gate-native-delivery-20261013.json`: chunked observed output, не full log.
Known pinned config_io ResourceWarnings остаются. Post-gate358 hashes unchanged,
snapshot348/SHAfa7587eb… повторно PASS. Это synthetic regression, не live voice.
Actual isolated console probe `runtime/owned-console-delivery-20261013.json`
PASS/runner0: real pinned imports +owned install marker confirmed, startup2.873s,
auth401/cancel200/tombstone409. Exact Job member listener21268/launcher16696,
listener gone после stop; observed launcher exit1 — Job termination, не graceful0.
Никакой agent/model/device не запускался. Protected imports с `-B`.
Baseline `runtime/baseline-native-delivery-20261013.json`:358 sources,
SHA9ab84adaa11beda11e40dc5587ee28f11113a78fcbfefad21378dd7e46456609,
HEAD0e53329f…; dirty changes сохранены, массового commit нет.
CodeSee:1 feature modified/27 total, validator0/61 прежних style warnings.
Далее: strict live acceptance на real models, после проверки свободных ресурсов.
Это guard ошибки, НЕ исправление качества ответа/скорости модели. B2/B3 OPEN.

## 13Oct — отдельный model research, без смены stack

Два делегированных read-only исследования сведены в
[обзор](RESEARCH_MICROTURN_EMBEDDINGGEMMA2.md): micro-turn LoRA как идея
turn-taking, EmbeddingGemma2 как кандидат мультимодального retrieval. Русское
качество и локальные задержки не измерены; видео целиком не просмотрено,
transcript недоступен. Ничего не скачано/переобучено/переключено. Определены
сравнительные gates и отдельный shadow-index/rollback; S-03 остаётся OPEN.
Основная очередь не меняется: owned completion guard после native duplicate
success → delivery recovery → strict live voice. Guard делегирован отдельному
Luna-агенту; на момент записи реализация и новый PASS ещё не подтверждены.
Подготовлен isolated dynamic loader seam `load_delivery_extension` в owned
console entry; ещё НЕ вызывается и поведение native runtime не меняет.
Существующие11 launcher/isolation tests PASS на Python3.14 (`-B`); это не
доказательство guard/delivery. Protected native source не редактировался.
Research docs: локальные ссылки существуют; standard diff-check exit0.

## 13Oct — strict live `/app` completion: 2 turns PASS, suite FAIL (новейший)

No application sources/models/avatar changed in this slice. New owned profile
`accept-voice-strict-20261013`, launcher cwd `C:\`, sandbox0, no screen/system/mic
capture; Edge fake-input WAV only. Outer RuntimeSupervisor Job + RAM/deadline
guard own the whole profile; exact membership proved for2367/8766/8770/8990/9889.
Current scoped delivery prompt copied SHA d34dd01b… verified; no upstream writes.

Reports retained:
- `runtime/live-voice-strict-20261013.json` FAIL/startup: fresh offline profile
  lacked JAWL embedding weights. Native FastEmbed labelled missing cache corruption;
  no browser/audio test started. All five ports closed, own cleanup no errors.
- `…-cache-seed.json`: only existing MiniLM ONNX weights copied from previous owned
  `accept-voice-20261013/data/vector/embeddings/models--qdrant--…` into this test's
  embeddings dir.8 files/252141082 bytes, all SHA256 match. No database/persona/
  config copied, no network/download, source cache retained. Test cache retained
  for reproducibility, not a new default/model or git asset.
- `…-r2.json` FAIL/browser bootstrap: Selenium could not discover Edge with missing
  ProgramFiles(x86). Model/profile startup and exact listener proof succeeded;
  no input was captured. Existing Edge/EdgeDriver155.0.4283.45 found offline;
  controlled env check showed adding this machine path enables discovery.
- `…-r3.json` FAIL/child1: strict `/app` browser suite reached two completed turns,
  third timed out75s. All listener ports subsequently closed, no cleanup/guard error.
  Browser report: `runtime/browser-voice-strict-20261013-r3.json`, screenshots in
  `runtime/browser-evidence/voice-strict-20261013-r3/`.

Turn1 favourite food: normalized transcript correct, native remember + terminal
success, full non-silent playback3.012s, turn→first scheduled sound17.501s,
total21.330s. Turn2 short-answer preference: same properties, audio3.397s,
first13.736s/total18.173s. Existing consumer EOF and AudioContext completion checked;
not hardware audibility/physical duplex proof. Third status-project question:
`/api/voice/end` stayed pending, no TTS requested, no completed UI response.
Fourth duplicate-preference case was NOT reached, so prompt recovery unverified.

Specific native completion gap: correlated turn `turn-voice-1791886758333-1`
has turn.started + successful tool lifecycle, no assistant.final/turn.error.
Agent log13:19:26 local shows SQLStructuredMemory.list_memories success;13:19:33
records `Duplicate successful action batch… Concluding cycle`. Pinned
`src/l3_agent/react/loop.py` duplicate-success branch sets outcome
`duplicate_success_concluded` and breaks without `_handle_completion`/terminal
event; finally clears active turn correlation. Thus the UI waits after that cycle
ended. This is not evidence of slow inference for the entire75s. Protected source
unchanged. Next fix: owned native completion boundary must emit one correlated
error on undelivered cycle termination (never expose thoughts/fabricate reply),
preserve successful terminal delivery and durable goals/cancel semantics; then
bounded delivery recovery/fast-chat routing and repeat strict live acceptance.

B2-01 remains partial (2 complete turns, minimum3 not met), B3-01 OPEN. Cold/offline
embedding asset bootstrap needs a B0 manifest/preflight solution. Do NOT junction
instance embedding cache to a protected/shared model directory: native cache-recovery
code recursively removes model_path after any load exception. Seeded isolated cache
was intentional to confine that behaviour. Source changes only docs in this slice;
last fullgate832 remains regression history, not acceptance of this failed suite.
Post-run verification:355 source hashes unchanged, protected snapshot348/SHA
fa7587eb… intact, GPU1 back to395MiB (pre-run baseline); all five ports absent.
5 changed docs UTF8/local links PASS, standard diff-check0. No new fullgate run
because application source unchanged; actual negative evidence is retained.

## 13Oct — review ночных изменений и границ voice acceptance (новейший)

Implemented review fixes: root URL + `--ui app` resolves to `/app`, navigation
checks refuse unexpected/foreign targets. Completion gate observes the existing
TTS reader's EOF (no duplicate reader), errors/cancel, non-silent source buffers,
wall AND AudioContext elapsed time/early stop; preserves original onended.
Five focused URL/controlled-JS tests PASS, including delayed EOF and truncated/
silent/rejected playback. Failure diagnostics omit DOM/function references so
JSON report serialization does not hide playback errors. Not hardware audibility.

Read-only Luna B3 audit found a contradictory general `actions: []` instruction
in owned RESPOND_DIRECTLY alongside required correlated terminal delivery. This
is a plausible contributor, NOT proven cause for all failures. Clarified only
`_companion_turn_id` delivery/terminal-success; background silence and native
policy preserved. Duplicate memory-key recovery is bounded to native lookup/
revise, not repeat remember; failure must be reported honestly. Four static
prompt tests PASS; model compliance still requires live validation after profile
sync/restart. No protected source or current instance prompt was patched.
`RESPOND_DIRECTLY.md` SHA256 `d34dd01b21447711383805cb8ea7649e4dbd8ab5e5a7be45978094297a699a78`;
unchanged delivery override SHA256 `7edbc07365d266113466da9e807144c1bdf1095a831d9ded271b58767d3cdfd5`.
Baseline355 `runtime/baseline-b2-voice-gate-review-20261013-final.json`, source SHA
`774542d2426b3a4746fd42681f2ec4d99f02a4982cd45377eec573e900939ef7`;
Markdown prompts are separately hashed above (baseline source suffix excludes MD).
Fullgate `runtime/gate-b2-voice-review-20261013.json` **PASS/observed child0**:
13Oct09:57:27–10:02:26 UTC (12:57–13:02 Москва),832 unit/66pytest/16HTTP/86Node/
6browser/8desktop.355 frozen hashes matched; protected snapshot348 unchanged.
94 known ResourceWarning debt сохраняются.5 edited docs UTF8/local paths PASS,
standard diff-check0. Это synthetic regression, не strict live voice completion.
Agents closed. CodeSee modified1/total27, validator0 (style warnings retained).
Next: strict live `/app` completion and correlated greeting/fact/duplicate-memory
delivery on an explicitly owned no-capture profile; then Stop/finalization race.

После user changes проверены не только два изменённых source scripts, но и новые
night docs/reports/owned instance. Existing connected runs не повторялись.
Последний сохранённый own fullgate `gate-final-asr-gpu-20261013.json` terminal
PASS/child0:823 unit/66pytest/16HTTP/86Node/6browser/8desktop; snapshot unchanged.
Поздний `full-gate-night2-20261013.json` тоже exit0. Однако strict `/app` playback
completion не покрыт этими receipts; старый browser gate считает play attempt/
buffer start успехом, не доказывая законченный звук. B2-01 переведён в partial:
route/transcript/native response/playback start подтверждены, completion ещё нет.

Ночной timings report13 успешных turn сохранён. Его p95 выше sample max —
экстраполированная/неописанная оценка, не empirical percentile. Новый review
`runtime/b2-03-timings-20261013-reviewed.json` (без inference rerun) явно использует
rank=(n−1)*p linear interpolation: turn→first-start p50 11.712s/p95 24.654s/max32.105s;
voice/end request p50 4.859s/p95 16.714s/max24.211s. Это selected successful runs,
не failure-rate/SLA. Turn timestamp включает речь пользователя; не называть его
задержкой ответа после окончания фразы. Значения ниже35.8/28.0 — старая оценка.

Known night blockers сохраняются: сообщалось о ≥4 пропущенных ответах, длинные status-task
turns и stopMic во время finalization теряет UI response. Не считать каждый
`Empty actions list` пропуском: некоторые идут после успешной terminal delivery
или SYSTEM_CORE_START; нужна correlation с final/error. Отдельный подтверждённый
failure — повтор `remember` с уже существующим preference key. Работа направлена на
эти реальные пробелы, не на повтор отдельных ASR/LLM speed probes. Read-only B3
prompt/terminal audit делегирован Luna; harness URL/completion fix отдельно.

## 13Oct — B2-01 принято на основном `/app` (новейший)

Owned профиль `accept-voice-20261013` запущен из `C:\` (launcher26668,
RunSeconds3600); владение проверено деревом (22 процесса), Tera/Hikari healthy,
fresh agent instance `d51c9cec…`. Прогон `scripts/run_browser_voice_e2e.py --ui app
--live` → `runtime/browser-voice-e2e-20261013-app.json` **PASS** (3 turn, exit0),
скриншоты `runtime/browser-evidence/voice-20261013-app/` (VRM-сцена, ответ в чате).
Вход: Tera-синтезированные RU WAV (16k, тишина150с) через Edge fake-input device;
приложение само владеет getUserMedia/gate/VAD/upload/finalize/TTS.

Итоги turn: «Запомни…Паста» ok, первый звук11.0с; «Запомни…короткие»19.7с;
«статус проекта»32.1с. У каждого: transcripts чистые, одна session/correlation,
voice_ends1, TTS играл (2–3 AudioBufferSource), без duplicate/error. Ответы по
смыслу; «статус» отвечен с проверкой задач («нет активных проектов… всё спокойно»).

B2-03 частично: 13 успешных синтетических turn (`control`+/app,5 прогонов):
turn→first-audio p50 11.7с/p95 35.8с, total p50 11.9с, voice/end→TTS headers
p50 10мс, voice/end request (ASR+JAWL) p50 4.9с/p95 28.0с. LLM TTFT/queue/
cold-warm отдельно не изолированы; набор синтетический.
Артефакт `runtime/b2-03-timings-20261013.json`.

Ночной regression на дереве этой ночи: `runtime/full-gate-night2-20261013.{log,json}`
**exit0** (823 unit/66 pytest/16 HTTP/86 Node/6 browser/8 desktop,17 PASS-стадий,
`git diff --check`0). Первый прогон `full-gate-night-20261013` сохранил1 флейк
`test_success_reaps_grandchild_before_temporary_files_are_removed` (изолированно3/3
PASS и полный unit-rerun OK; лог первого прогона сохранён как evidence флейка,
reap-логика не менялась). CodeSee validator exit0 (харнесс не в features.json).

Изменения харнесса для `/app` (`run_browser_voice_e2e.py`): `--ui app` (селекторы
`#chat-send/#chat-mic/#chat-log .msg`), event-driven поток (без фиксированного сна
и stop — приложение финализирует само по тишине), роль сообщения по классу `.msg`,
остановка mic после collect для освобождения lease, предел длительности WAV60→300с.

Дефекты/наблюдения (открыто):
1) terminal-канал нестабилен: модель периодически закрывает turn без
   `send_message_to_terminal` («Empty actions list»), gateway возвращает error-envelope
   «JAWL недоступен…», speak=False — озвучки нет. Наблюдено после preference-памяти на
   фактовом вопросе и на «Запомни…короткие» в повторных прогонах (воспроиз.≥4×).
   Кандидат B3-01; влияние на надёжность voice-turn.
2) `/app` слушает непрерывно: после финализации mic остаётся armed; перекрывающаяся
   речь открывает новую сессию и отменяет текущий TTS (barge-in) — учтено в
   харнессе разделением turn; акустический duplex — B2-05.
3) «статус проекта» запускает многошаговое расследование memory/journal; следующая
   реплика может ждать его завершения (наблюдено166с при живом расследовании).
4) Ручной stop микрофона во время финализации прерывает in-flight `/api/voice/end`
   на клиенте (`stopMic→abort`): сервер turn записывает, UI его теряет.
   Кандидат B1-05/B2-05.

Границы: синтетический WAV-источник (не физический mic), всё в owned instance;
модели/active avatar не менялись; в сцене sample VRM.

## 13Oct — connected voice synthetic acceptance (предыдущий)

Первый connected run owned live-профиля `accept-voice-20261013` через
`scripts/run_local_bonsai_integrated.ps1` (manifest defaults: Hikari `local-bonsai2`
CUDA1/ctx65536, TeraTTSv2 ru_f1, GigaAM v3 final; `-NoBrowser`; без screen/sensory/
ambient capture). Владение: все слушатели 2367/8766/8770/9889/8990 принадлежали дереву
launcher (22 процесса), instance `a6ac3b1d…`, brain и Tera healthy.

`scripts/run_real_voice_synthetic_acceptance.py` ранее не запускался и не отслеживается
git (`??`). Один file/PCM синтетический turn, без устройств:
- attempt1 `runtime/real-voice-synthetic-20261013-attempt1-threshold10.json` **FAIL**:
  preflight, Tera-фикстура, PCM upload 204ms, GigaAM transcript (42 кириллических буквы,
  тема совпала) пройдены. JAWL ответил «Термометр.» (9 букв), ответ ушёл через
  `send_message_to_terminal` и попал в `text`. Харнесс отбросил его порогом ≥10 букв:
  ложный отказ, порог не калиброван под однословный ответ.
- Правка харнесса (строка ~485): порог ≥5 кириллических букв; содержательный gate оставлен
  прежним (термометр/градусник). Это изменение критерия после наблюдения провала: записано явно.
- attempt2 `runtime/real-voice-synthetic-20261013.json` **PASS**, exit0, 7/7 стадий:
  fixture 3.519s; PCM upload 146ms; voice_end→JAWL 4227ms; answer→playable Tera TTS 428ms
  (1.574s, peak 7600, rms 1278.5); lease released, pending cleanup нет.

Не закрыто по B2-01: один synthetic turn вместо 3 WAV; вход не физический mic и не
`/app` actual capture; WebAudio/VRM playback, first-audible в браузере, echo/barge-in
не проверялись. Ответ зависит от вызова terminal-инструмента: без него адаптер даёт
degraded (по коду `jawl_adapter.py`). Reviewable diff харнесса в git отсутствует, правка
описана здесь.

Остановка: досрочно деревом launcher (`runtime/voice-accept-stop-20261013.json`), не
RunSeconds. Launcher finally/integrated report не записаны. Порты закрыты, GPU1 вернулась
к ~387MiB. `*.lock` файлы instance остались: проверить при следующем старте. Дефект моей
проверки: pre-kill assertion по StartTime упал (`DateTimeOffset.DateTime`); kill выполнялся
по PID 12424 и дереву из 22 процессов, совпавшему с ранее проверенным; формальной проверки
времени старта перед kill нет.

CodeSee: features.json не ссылается на харнесс и не менялся; read-only validator exit0
(предупреждения по длине step names feature 26 были до этого среза).

Следом: 3 RU WAV через реальный `/app` capture с отдельным consent-шагом и WebAudio
playback; first-audible/p50/p95 из браузера.

## 13Oct — final ASR ownership + actual GPU1/CPU inference (предыдущий)

Final GigaAM file-mode теперь использует atomic owned DEVNULL worker и всегда
reap-ит дерево, даже после normal root exit, до чтения/cleanup WAV/JSON.
При teardown fault только собственный temp-каталог сохраняется (может содержать
чувствительный WAV); ошибка не считается success. Successful cleanup удаляет
его как раньше.11 final-ASR tests PASS3.14/3.11, включая dead-root grandchild,
cancel/concurrent calls и fault-retained directory. Luna tests закрыты.

GPU1 fresh resource check:381MiB used/16303MiB, RAM~71.6GiB; foreign процессы не
останавливались. Opt-in GPU1 mode added to existing model probe, strict CUDA1/
positive layers/free VRAM≥weights+2GiB/RAM guard. CPU mode remains separate.
7 GPU helper tests PASS; initial new env test mock reused mutable dict, corrected.
Actual reports:
- `llm-model-cancel-gpu1-20261013.json`: SKIP, clean env lacked ProgramFiles,
  NVML failed; no model launched. Controlled env delta isolated ProgramFiles
  (or ProgramW6432) as sufficient; only ProgramFiles machine path added, not
  profile paths/credentials. This does not broaden protected source access.
- `…-r2.json`: FAIL after prefill cancel→idle170.944ms; output cap12 returned
  no user text. Cause not proven reasoning; tiny diagnostic budget was unsuitable.
- `…-r3.json`: PASS/parent+child0, canonical output2048, prefill cancel→idle62.789ms,
  same-client RU answers0.936/0.742s.
- `…-r4.json`: PASS/parent+child0, strict actual generation observed n_decoded2;
  cancel→idle78.267ms, startup2.899s, followups «Да, готова.»0.931s/«Четыре.»0.773s.
  Same selected Hikari PQ2_0/CUDA1/layers99/ctx65536/threads12. Own Job/listener
  gone, no guard error. Not concurrent stream B, long-context quality or full agent.

Actual final GigaAM CPU on three old Tera synthetic WAVs:
`runtime/asr-final-actual-20261013.json` execution PASS/exit0:0.480/0.206/0.257s,
RTF0.137/0.059/0.055. Review `…-reviewed.json`: all three normalized word sequences
match. Old Tera expected-text fields have reversible encoding mojibake; reviewed
report recovers them without modifying originals. New ASR transcripts valid RU.
No microphone, playback, ambient capture or whole voice/LLM/TTS E2E performed.

Baseline353 `runtime/baseline-b1-final-asr-gpu-20261013.json`, SHA256
`06eeda7880ce3593fde54d5769ee556bb6f530346accc7a095d2c6eae49a1b11`, HEAD0e53329.
Fullgate `runtime/gate-final-asr-gpu-20261013.json` **PASS/observed child0**:
UTC 00:35:37.069987→00:40:37.663336, runner28200/child12052. Log
`…-20261013.log`:823 unit /66 pytest manifest-worker+diagnostics /16 HTTP /
86 Node /6 legacy browser /8 desktop composite checks, `git diff --check`0.
No FAILED/ERROR/Traceback; 94 known ResourceWarning debt без clean-stderr
заявления. Previous814 PASS ниже — историческое покрытие, не этот прогон.
CodeSee validator для этого среза не запускался (run_full_gate его не содержит).
Next: connected RU ASR→native JAWL→TTS synthetic turn, first-audible/interrupt/
replacement timing; microphone/device/art acceptance still separate. Do not
relaunch CPU Hikari probes.

## 13Oct — Windows PIPE ownership (новейший checkpoint)

`windows_process.py` получил optional binary PIPE stdin/stdout с exact child
HANDLE_LIST, CRT ownership transfer и DEVNULL stderr; default DEVNULL сохранён.
`owned_pipe.py` владеет отдельным atomic Job, terminate/kill завершают дерево,
wait проверяет empty-before-close даже после смерти root. Cleanup failure
сохраняет Job/cleanup_pending. StreamingASRBridge и VoiceMemProcessClient используют
этот путь; POSIX пока обычный Popen, native policy/models/defaults не менялись.

VoiceMem close/replacement теперь сначала reap tree+reader, затем замена;
abort сначала terminate, не buffered stdin.close. В процессе воспроизведён
reader timeout: reader-finally ждал lifecycle lock, которым close владел во время
join. Reader теперь только посылает EOF, dead state вычисляет owner. FAIL сохранён
как обнаруженная регрессия, затем14 sidecar tests PASS3.14/3.11, включая blocked
12KB writer cancel и reader-start failure.17 streaming tests PASS3.14/3.11.
Luna:3 factory PIPE tests и4 owned-tree/EOF/retry/foreign-control tests PASS
3.14/3.11. При review исправлен тест retry, который возвращал real_drain вместо
вызова; финальная проверка действительно вызывает его. Оба агента закрыты.

Baseline352 `runtime/baseline-b1-pipe-owner-20261013.json`, SHA256
`74678a1b049dab207a292cc8208b253f77fd7e9b4a1a0edaba049bbdc8030cb9`.
Full gate `runtime/gate-pipe-owner-20261013.json` **PASS/observed child0**:
13Oct00:21:13–00:25:59 UTC,814 unit/66 pytest/16 HTTP/86 Node/6 legacy browser/
8 desktop checks.352 frozen source hashes matched; protected snapshot348 unchanged.
94 known ResourceWarning debt, не чистый stderr. CodeSee modified2/total27,
validator0;5 edited docs UTF8/local paths PASS, standard diff-check0.
Предыдущий805-test PASS ниже — историческое покрытие прежних исходников.
Не real GigaAM/E5/model warm/cancel latency, не microphone/barge-in acceptance.
Открыт отдельный file-mode final ASR `giga_final.py` (DEVNULL Popen + JSON на диске),
actual model compute release и весь daily voice scenario. Не распространять
PIPE guarantee на все subprocess. Header старого windows_process docstring ещё
описывает DEVNULL-only первоначальный scope; текущий контракт — эта запись.
Read-only review next: final ASR finally reap-ит только если root poll()==None;
при normal root exit descendants не проверяются до чтения/удаления temp JSON/WAV.
Нужно сохранить file protocol/50ms cancel polling и убрать это ownership окно,
а не загружать ASR заново ради теста. Новое PIPE покрытие его не закрывает.

## 13Oct — адресное завершение worker generation (новейший checkpoint)

Каждый Windows worker RuntimeSupervisor теперь атомарно создаётся в двух Jobs:
global parent-death containment + собственный worker Job. Stop/restart завершает
только worker Job и проверяет ActiveProcesses0 до CloseHandle/замены. Уборка
работает и при уже умершем root; повторный start убирает старую generation.
Ошибка/deadline teardown при restart сохраняет ownership и запрещает replacement,
не расходуя restart budget. POSIX/direct Popen owners не изменялись.

Luna добавила4 real cheap tree tests PASS Python3.14 и pinned3.11: restart A,
dead-root restart/start, full Stop; B root/grandchild не затронуты. Координатор:
17 supervisor/3 ownership/3 atomic/9 process tests PASS; отдельная injected
teardown failure проверяет no-spawn/retained ownership. В test fixture сначала
исправлен отсутствовавший обязательный probe аргумент; runtime FAIL этим не заявлен.
Новый baseline349 sources `runtime/baseline-b1-worker-tree-20261013.json`, SHA256
`02de9174441a931703767847b9e2076b9f3efc793247cdcdf602c982ff99330f`.
Полный gate `runtime/gate-worker-tree-20261013.json` **PASS/observed child0**,
13Oct00:10:23–00:15:07 UTC:805 unit/66 pytest/16 HTTP/86 Node/6 legacy browser/
8 desktop checks. Synthetic/mock, не actual live voice acceptance.349 frozen
source hashes повторно matched. Snapshot348/SHA fa7587eb… unchanged.94 known
ResourceWarning остаются debt.6 edited docs UTF8/local paths PASS, diff-check0.
CodeSee modified1/total27, validator0 (61 style warnings); Luna закрыта.
Нижний800-test PASS относится к предыдущему atomic-only срезу.

Это закрывает per-worker Windows descendant restart для supervised workers,
но не actual model inference cancellation, direct PIPE transports, POSIX trees,
whole-profile/live voice/device/art acceptance. Следующий B1 шаг — аудит ownership
ASR/sidecar direct Popen и границ отмены; тяжёлый Hikari CPU не повторять без гипотезы.
Read-only inspection next: `voicemem_client.py` `_ensure_process` использует PIPE
Popen без Job; close/abort terminate root, а замена dead root не доказывает reap
старого reader/descendants. `streaming_asr.py` также содержит direct Popen и
root terminate/kill. Это конкретная граница следующего изменения; не переносить
DEVNULL-only factory на PIPE вслепую. Listener/cancel evidence выше её не закрывает.
Actual owned console на новом коде `runtime/native-console-worker-tree-20261013.json`
PASS/exit0, startup0.717s/auth401/cancel200/turn409/exact Job/listener gone;
no agent/model/device. Luna завершена/закрыта, её write scope — только новый test.

## 13Oct — атомарный Windows Job: текущий срез B1

RuntimeSupervisor start/restart теперь создаёт DEVNULL workers через
STARTUPINFOEX/JOB_LIST: containment действует до исполнения child, без running→assign
или suspended→assign окна. Job handle не наследуется; проверка membership использует
retained process handle, не повторное открытие PID. Unsupported/failed API — отказ,
не fallback на незащищённый Popen. POSIX путь и native policy не изменены.
Новый модуль `windows_process.py` не является общим заменителем Popen/PIPE.

Focused: 19 supervisor/ownership tests PASS; 9 Windows process tests и 3 atomic
Job tests PASS на Python3.14. Atomic tests также PASS на pinned Python3.11 с
venv wrapper→actual worker→grandchild. Hard-kill parent до verification не оставляет
worker/grandchild; outer safety Job проверен пустым до его закрытия, foreign control
жив. Negative legacy-create control воспроизводит отсутствие inner containment.

Actual console probe `runtime/native-console-atomic-job-20261013-r1.json` FAIL:
одинаковые NO_PROXY/no_proxy отвергались environment builder. После red→green
unit исправления одинаковые aliases объединяются, конфликтующие значения всё ещё
отклоняются без value echo. r2 PASS/exit0: startup0.717s, native auth401/cancel200/
turn409, exact owned listener и cleanup; без agent/model/device запуска.

Промежуточный `runtime/gate-atomic-job-20261013.json` PASS/child0, но относится
к исходникам ДО env исправления и не является финальной проверкой текущего кода.
Финальный gate: `runtime/gate-atomic-job-20261013-r2.json`; frozen baseline:
`runtime/baseline-b1-atomic-job-20261013-r3.json` (348 sources). До terminal receipt
его статус не считать PASS. Финальный terminal receipt теперь **passed/child0**:
13Oct00:02:08–00:06:45 UTC (03:02–03:06 Москва),800 unit/66 pytest/16 HTTP/
86 Node/6 legacy browser/8 desktop checks. Synthetic/mock, не hardware acceptance.
348 frozen hashes matched, source SHA256
`7b8154cbe144dcbcc0eb32465fae61b7d7273304e840b72734c561b247a3a0bb`;
pinned snapshot348 files unchanged, SHA256
`fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.
94 known ResourceWarning остаются debt; stderr не объявляется чистым.
CodeSee modified1/total27, validator0 (61 style warnings),6 edited docs UTF8/
local paths PASS и standard git diff --check0. Нижние записи12Oct — история.

B1 остаётся partial: отдельный restart worker ещё требует descendant teardown
без закрытия global Job других workers; direct Popen/PIPE owners требуют отдельной
проверки. Actual selected GPU1 compute release, live voice/task continuity,
whole-profile/device/art acceptance OPEN. Модели, defaults и active avatar не менялись.
Следующий независимый шаг — per-worker restart descendant ownership, не CPU reload.

Срез: **2026-10-12 (Москва)**. После docs-only консолидации владелец разрешил реализацию
по TODO и новый goal. Первый code slice — B0 manifest/defaults/preflight;
12Oct добавлены controlled actual Tera CPU cancel/follow-up, native admission
hardening и isolated pinned SDK cancellation probe. Физические устройства
и protected upstream не запускались;
active avatar не менялся. Тестовое evidence отдельно от live/provider/device.

**Статус продукта: интеграционная версия, не RC и не production-ready.**
[Замысел](PRODUCT.md) · [очередь](../TODO.md) · [полный остаток](WORK_REMAINING.md) ·
[карта документов](README.md) · [матрица приёмки](TECHNICAL_AUDIT.md).

## Что является текущей платформой

| Граница | Выбор / владелец | Ограничение |
| --- | --- | --- |
| Агентное ядро | Owned JAWL: persona/SOUL, context, memory, goals, Heartbeat, native tools/policy | Не отдельный direct LLM в Companion |
| Сенсорная инфраструктура | VoiceMem, capture/ASR/triage/fusion adapters | Не вторая личность или authority |
| Клиент | Electron + three-vrm, основной `/app` | Старые web/console поверхности ещё сосуществуют |
| Главная LLM | Bonsai-2 27B Hikari PQ2_0, GPU1 | Текущая доступность в этом аудите не проверялась |
| ASR | GigaAM v3 / crispasr, final + streaming bridge | Desktop partial UX не завершён; Qwen/whisper fallback удалён |
| TTS | TeraTTSv2 ru_f1 default; OmniVoice выбираемый; VoxCPM optional | Клон/эмоции/latency зависят от реально выбранного worker |
| Vision | Bonsai8986 / screen-watch / PerceptionFusion | Configured capability не гарантирует RU OCR/grounding/action loop |
| Порты продукта | control2367 / presentation8766, JAWL console8770 / brain8990 / Tera9889 | Общий manifest Python/PS/Electron; FoxMCP8765 не трогать |

Canonical + optional local manifest deep-merged/validated; оба PS launchers,
Python worker factory/holder и Electron используют согласованные настройки.
RunSeconds0 — до остановки, 60s smoke только явно. Hikari alias local-bonsai2,
ctx65536/output2048/CUDA1; vision8986 alias bonsai остаётся opt-in.
Brain readiness требует /health и exact /v1/models id; missing worker и port
conflict не приводят к silent skip/чужому kill. Ошибки без raw credential values.
Legacy Qwen/mmproj files отсутствуют; optional vision не запускался/не скачивался.
`run_coding_server.ps1` остаётся old Bonsai Q1, не Hikari brain.
Rust получил bounded/duplicate-key-safe loader local overlay, schema/ports/
profile validation, discovery от cwd/executable/--repo-root. Это ещё не полная
cross-language differential parity; default dev fallback остаётся только при
отсутствии обоих manifest файлов.
OPEN B0: whole current profile outside cwd, actual effective UI readback,
cross-client parity, полный перенос machine paths и clean install.
Подробности запуска: [RELEASE](RELEASE.md).

### 12Oct — actual selected-LLM CPU probe (последний срез)

Два controlled actual CPU runs — **FAIL**, не LLM compute/slot-release PASS.
Тот же выбранный Hikari PQ2_0/selected prism binary, threads12, test ctx4096/
slot1, GPU offload0; canonical GPU1/65536 не менялся. r1 load19.416s, за35s
не наблюдались≥2 generated tokens. r2 batch16/ubatch1 load21.654s, за35s
last slot active task2/prompt processed0/decoded0; native work/cancel measurement
не достигнуто. Это telemetry, не доказанная причина/zero CPU work/оценка GPU.
Оба reports retained: `runtime/llm-model-cancel-cpu-20261012{,-r2}.json`, child/
parent exit1, own listener+Job gone, RAM guard не tripped (minimum~15GiB).
Протокол/границы/логи — [LLM_MODEL_CANCEL_BENCHMARK](LLM_MODEL_CANCEL_BENCHMARK.md).

Добавлен только opt-in diagnostic harness +9 helper/CLI tests/12subtests PASS;
8 тестов Luna,1 coordinator. Luna завершена/закрыта. В final harness добавлены
source/version/stage metadata и запрет child-route обхода model opt-in; эти
добавления проверены cheap tests, без третьего model load. Новый baseline
`runtime/baseline-b1-llm-cpu-probe-20261012.json`:345 sources,
SHA256 `201311341d1ed6f32dd5c262f2b2fdc63618b3872c480523ff9c29d117383dd4`.
Все345 hashes matched, прежние343 тоже unchanged. Last fullgate ниже всё ещё
779/66/16/86/6/8; новый полный gate НЕ запускался: application runtime не менялся,
новые2 diagnostic sources покрыты focused tests, не приписывать им fullgate scope.
Snapshot повторно verified348 unchanged. Heavy CPU runs прекращены; selected
GPU1 release остаётся OPEN при занятой GPU. Следом независимый B1 early Popen→Job
ownership gap, затем current voice/task continuity. Whole goal active, не RC.
Final helper9 также PASS pinned Python3.11. Read-only readiness повторно:8990 и
1234 URLError; GPU0 used15873MiB/GPU1 used15453MiB из16303MiB, free RAM22.23GiB.
CodeSee checkpoint modified1/total27, new0/deleted0/planned→implemented0,
validator0 с прежними style warnings.10 changed docs UTF8/local links PASS,
broken0, standard diff-check0;345 hashes unchanged. Новых open agents/worker
sessions нет;62959/78322 terminal exit1 сохранены как FAIL, не lost-exit/PASS.

### 12Oct — client POST scoped abort и абсолютный deadline (предыдущий срез)

`http_lifecycle.read_scoped` владеет default loopback HTTP(S) socket до connect
и TLS handshake. Scoped Stop закрывает только этот socket; absolute configured
deadline охватывает connect/headers/body, не продлевается trickling. Loopback
числовой connect без DNS; system proxy/redirect отключены, TLS verify сохранён.
ACK body128KiB, один POST/no replay. Cancel forwarding имеет независимый scope,
не наследует уже выставленный old turn event. Watchdog join до возврата, native
producer держит admission через cleanup. Injected opaque/non-cooperative opener
не объявляется forcibly reaped; remote compute release не следует из socket EOF.

13 HTTP/TLS loopback tests +3 real-socket native-adapter cases: preheader abort,
peer EOF, exact-ID cancel once, replacement B через old A deadline, header/body
trickle, ACK total timeout, cancel deadline, no redirects/token forwarding,
bounded read/error cleanup, A/B isolation, TLS untrusted reject/trusted test CA/
handshake cancellation. PASS3.14 и pinned Python3.11, без native agent/model/device.
Combined chat/admission/diagnostics+new tests:65 PASS +11 subtests. TLS cert/key
генерируются ephemeral в TemporaryDirectory; `cryptography==48.0.1` добавлен
только в requirements-dev, runtime dependencies не расширены. Luna изменяла
только tests/test_http_lifecycle.py; агент завершён и закрыт.

Baseline `runtime/baseline-b1-client-post-20261012.json`:343 sources,
SHA256 `58dd2840a4e49d872bde4afddaae97ad0e4b7966162b4a24a4d30608b1abbda4`,
HEAD0e53329… dirty/not release. Fullgate `runtime/gate-client-post-20261012.{log,json}`:
observed direct child exit0, receipt passed; runner2892/child8828/session96137
терминальны. UTC12Oct00:23:34.399649–00:28:20.140501 (12OctMoscow).
779 unit180.865s /66 pytest0.82s /16 HTTP61.200s /86 Node fail0 /6 legacy browser /
8 desktop composite PASS. Snapshot/secret/PS parse/diff PASS. Browser scope:
real app/capture/worklet/playback +mock ASR/JAWL/tone TTS, не actual-model/device/art.
94 ResourceWarning markers — прежний pinned config_io fixture debt, не clean stderr.
Все343 source hashes совпали; snapshot повторно verified348 files,
SHA256 `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.
CodeSee checkpoint: modified1/total27, new0/deleted0/planned→implemented0;
validator exit0 (старые style warnings).13 актуальных docs UTF8/local links PASS,
broken0; final standard git diff --check0 и343 frozen hashes unchanged. Отдельная
диагностика с core.autocrlf=false ошибочно трактовала existing CRLF как whitespace;
рабочую tree/настройки не меняли, standard gate/check PASS, массовой нормализации нет.

Следом B1 actual selected-LLM compute/slot release и current voice/task continuity.
Read-only probe этого среза:8990/health и1234/v1/models URLError; GPU0 used15785MiB,
GPU1 used15453MiB из16303MiB каждая. Чужие processes не закрывались, heavy модели/
active avatar не менялись. Whole-profile, acoustic duplex, task continuity,
early Popen→Job race и durable/cross-transport dedup остаются OPEN. Goal active,
не RC и не принят весь B1. Старые native-owner gates ниже — historical checkpoints.

### 12Oct — owned native HTTP admission и owner-fenced diagnostics (предыдущий срез)

Оба owned launchers выбирают `scripts/run_owned_jawl_console.py`, не прямой
`-m src.web.server`. Entry проверяет instance + registry isolation, snapshot,
ставит explicit owned middleware после native auth, не патчит protected файлы.
Native make_app/ChatBridge/Heartbeat/memory/tools остаются единственными owners;
extension грузится напрямую без полного Companion import graph. Startup tokens
редактируются в stdout/stderr, split writes/oversized lines bounded, UTF8.

Native HTTP guard:1024 IDs/TTL300s после HTTP cleanup, pending не expires/evicts.
Capacity503, duplicate/cancelled409, no replay. Tombstone до await forward;
readiness waiter/disconnected client/scheduled task не могут поздно dispatch.
Body128KiB/1s absolute/strict duplicate-key JSON, text≤8000, ready5s/send2s/
cancel-forward1s. Acquire/release balanced. Cap endpoint auth + actual process_id;
integrated readiness требует http-turn-admission-v1. Client diagnostics теперь
per-admission owner; stale A не перезаписывает B, waiter не захватывает status.

Важный regression: первоначально unknown/expired ID отменялся только локально,
хотя native turn мог продолжать работу. Новый TTL test сначала FAIL (нет forward),
затем PASS после ALWAYS best-effort exact-ID native cancel. Local tombstone ACK
назван `local_dispatch_prevented`, не утверждает, что native работа не начиналась.
`forwarded` — лишь bridge ACK. Process-local/TTL bounded, не durable/exactly-once.
5 boundary tests PASS на обоих Python3.14 и pinned3.11;14 loopback и11 entry
focused PASS.7 diagnostics добавлены явно в pytest full gate (unittest не запускает
function-based cases). Constructor diagnostic-claim exception также fenced.

Actual launcher + pinned native console probe final:
`runtime/native-owned-console-probe-20261012-r5.json`, observed tool exit0/PASS,
UTC11Oct23:55:46.894653–23:55:47.789170 (=12OctMoscow), startup0.726s.
Own launcher31332/listener24204, ephemeral50603, exact own Job proof до POST.
Native auth401/cancel200/tombstone turn409; own listener ушёл, root reaped с
observed exit1 (ожидаемый supervisor Stop), не путать с probe exit0.
No agent/model/device started. R1–R4 — предыдущие checkpoints; r1 startup log
показал fake token в native URL, r2+ filter убрал его. R3/R5 stdout UTF8/редакция
проверяются отдельно; ни один probe не доказывает остановку native inference.
Первый inline probe command дал SyntaxError до процесса/report; заменён явным
reusable script. Первый scheduling test неверно предполагал Python3.11 wait_for
на3.14: fixture теперь явно воспроизводит3.11 task interleave, оба интерпретатора PASS.

Первый fullgate `gate-native-owner-20261012.{log,json}` PASS/observed child0,
UTC23:49:02.450892–23:53:43.557659, baseline340 SHA bdec9166…; он НЕ содержит
последующий TTL fix. Final baseline `baseline-b1-native-owner-20261012-r2.json`:
340 sources, SHA256 `c3ba1688ce293ef1d1877ff240c71a1642cf5e1f9eb90e677203b36c5deaf01e`,
HEAD0e53329… dirty/not release. Final fullgate
`runtime/gate-native-owner-20261012-r2.{log,json}`: direct child exit0/terminal
receipt passed, UTC11Oct23:56:02.174519–12Oct00:00:47.973667 (12OctMoscow).
763 unit181.005s /66 pytest /16 HTTP60.465s /86 Node fail0 /6 legacy browser /
8 desktop checks PASS; snapshot/secret/PS parse (включая daily)/diff PASS.
После gate все340 source hashes сверены, mismatched0. Browser scope всё ещё
mock ASR/JAWL/tone TTS, не actual-model/device/art acceptance.94 ResourceWarning
markers как в предыдущих gates, pinned config_io debt не скрыт. R5 startup log
strict UTF8: raw fake console token отсутствует, ?token=<redacted> присутствует.
CodeSee синхронизирован: modified2 (transport/supervisor), new0/deleted0/
planned→implemented0; validator exit0,61 style warnings.13 актуальных docs:
UTF8/local Markdown links PASS, broken0; final diff-check0,340 hashes unchanged.
Snapshot после полного gate повторно read-only verified,348 files unchanged.

На конец предыдущего среза OPEN B1: absolute client POST/body abort (закрыт в default
transport выше), actual selected-model compute/
slot release, current voice/task continuity, early Popen→Job descendant race;
cross-transport/restart/durable dedup отдельно. Read-only resource probe в этом
срезе:8990/health и1234/v1/models URLError; GPU0 used15867MiB/GPU1 used15453MiB из16303MiB каждая.
Не приписывать эти процессы профилю/не kill чужие. Новые heavy модели не запускались.
Целый профиль, device/acoustic duplex, арт и весь goal не приняты.

### 12Oct — native admission и отмена установленного SDK (предыдущий срез)

Sync/stream теперь используют один admission owner. Producer независимо от
паузы consumer держит lease до transport cleanup; queue32, ожидание cancel-aware.
Исключения Queue/Event/Thread construction/start не оставляют lock. Outgoing
turn_id строго проверяется без truncate/coerce. POST ровно один: HTTP409/offline/
lost ACK не доказывают non-admission, поэтому blind replay удалён. Scoped cancel
касается только этого ID; read-only SSE reconnect не повторяет mutation.

Focused53 PASS/observed exit0:29 existing chat+7 SSE+12 admission+5 SDK harness.
Первая серия новых admission tests:10 PASS/2 FAIL — Queue/Thread constructor
leaks; исправлено до итогового53. Loopback lost-ACK подтверждает один submit и
scoped cancel. Отдельный первоначальный shell invocation не нашёл `.venv`;
тесты затем выполнены доступным `python` (тот же fallback полного gate).

`runtime/llm-cancel-sdk-20261012-r2.json`: PASS, actual parent/child exit0,
UTC23:20:12–23:20:14 11Oct. Native pinned OpenAICompatibleProvider, Python3.11.15,
SDK3.8.0/httpx0.28.1, fake owned loopback, без модели/API/device. Cancel request →
server EOF: preheaders0.14ms /midstream0.29ms /concurrent-A0.48ms (perf_counter).
Все5 requests по одному, B после отмены A и same-client follow-up успешны.
Own Win Job закрыт; ephemeral58956 независимо не слушает. Первый agent probe
в Temp прошёл, но monotonic округлял timings до0.00ms; текущий receipt — r2,
не переносить нулевые значения как точный latency. Timeout fault injection1ms:
`runtime/llm-cancel-sdk-timeout-20261012.json` expected FAIL/parent1, own Job
closed, root reaped (observed exit0 у Job termination); это не отмена inference.

OPEN B1: native cancel-before-start race (`ready_chat_bridge` может dispatch
после раннего cancel), authority-owned bounded tombstones/dedup; absolute
POST/body deadline и abort; server-side selected-model compute/slot release,
current voice/task continuity. SDK EOF не означает остановку GPU. Popen→Job
assignment не атомарен: descendant containment на очень раннем spawn ещё
требует отдельной проверки. Snapshot/protected upstream не патчились.

Baseline `runtime/baseline-b1-native-admission-20261012.json`:333 sources,
SHA256 `c1849f633b5f5f8da3e61d135a2cdf4ea14a264f07db622c1ee42777e11c0570`,
HEAD0e53329… dirty, не release. Fullgate `gate-native-admission-20261012.{log,json}`:
direct child exit0/terminal receipt passed, UTC11Oct23:20:40.989797–23:25:21.238573
(12OctMoscow).732 unit179.528s /59 pytest0.81s /16 HTTP61.628s /86 Node /
6 legacy browser /8 desktop checks PASS. Все333 source hashes сверены после gate,
расхождений0. Snapshot/secret scan/PS parse/diff PASS. Browser — actual app/
capture/worklet/WebAudio с mock ASR/JAWL/tone TTS, не actual model/device/art.
ResourceWarning markers94, как в прежнем715 gate: pinned config_io unclosed
fixture files, не clean-stderr claim; debt не патчить в immutable snapshot.
Отдельно OPEN: old paused consumer может перезаписать global last_chat_status
после нового owner; нужны owner-fenced diagnostics, не только side-effect fence.
CodeSee: modified1 (`f-chat-transport`), new0/deleted0/planned→implemented0;
validator exit0,61 style warnings (Russian name lengths, включая новый step).
9 front docs UTF8/local Markdown links проверены, broken0; diff-check exit0.

### 12Oct — ограниченный real Tera probe: SKIP до загрузки (история)

Добавлен opt-in `scripts/run_tera_cancel_acceptance.py`: отдельный CPU24/ru_f1/
distilled worker через checked Win Job supervisor, ephemeral loopback порт с
проверкой PID владельца до inference, без GPU/микрофона/проигрывания. Порог старта
4GiB available RAM, watchdog50ms/floor1.5GiB/total120s, no restart; cleanup только
own worker. План прогона — service.stream/cancel → idle worker+speech lease →
3 коротких RU WAV. WAV/RTF не доказывают речь без ошибок, live duplex или p95 SLA.

`runtime/tera-cancel-actual-20261012.json`: **SKIP**, UTC22:44:14 11Oct (=12OctMoscow),
до чтения manifest/создания supervisor/загрузки весов. До подготовки RAM была
~6.5GiB; к запуску оказалась ниже4GiB. Независимый read-only probe сразу после
показал2,188,402,688 bytes available (~2.04GiB); не подставлять его как точное
значение на момент SKIP. Receipt содержит intended exit2; PowerShell tool wrapper
вернул1, поэтому actual child exit отдельно не утверждается. Повторного live
старта ради SKIP не делали. Tera9889 не объявляется ready; B1-03 не закрыт.
Harness final12 cheap safety tests PASS (0.550s, observed exit0), без моделей:
RAM/deadline/accounting, re-signal Stop при startup race, owner mismatch до
inference, startup/cleanup failures. Ошибка одного cleanup не пропускает другие;
ошибки stop фиксируются и повторяются до guard.close, не превращаются в PASS.
Runtime source остаётся тем же, что в fullgate693; новые harness/tests не покрыты
тем старым gate. Baseline `runtime/baseline-b1-tera-probe-20261012.json`:
328 sources, SHA256 `38bd4ea56ac30cf6b7200890d9ed195ba2ba1f6f9875a8329988cf6d9291dbc8`,
HEAD0e53329… dirty; metadata-only, не release. Записанный SKIP — до последних
hardening изменений harness; его source SHA сохраняется как исторический.
Следующий шаг — live probe лишь при достаточной RAM либо независимый B1 native
turn/LLM cancel. Не kill чужие процессы ради освобождения памяти.

### 12Oct — SSE lifecycle, Job ownership и actual Tera CPU

`_SseReader`: interrupt только own HTTP socket до buffered close; join1.25s
возвращает фактический thread exit. Start/Stop согласованы lock. Header timeout≤1s,
после headers полный idle budget восстанавливается. readline128KiB+1, cumulative
data packet128KiB, queue64; invalid JSON/overflow — explicit error. Stop очищает
очередь и запрещает late opener publication.36 focused SSE/chat tests PASS
(29existing+7new), включая реальные stalled body/preheaders и изоляцию A/B.
Не-cooperative custom opener может пережить join (false), затем закрывается.
Это не доказательство остановки remote LLM compute или удаления durable goal.

Supervisor owns_pid read-only проверяет **конкретный own Windows Job**, включая
venv descendants; ошибки fail closed, non-Windows только live tracked roots.
3 ownership tests (actual venv child/foreign process) +16 supervisor tests PASS.
Failure ledger: premature chat run29 до адаптации fake readline(limit) дал
failures2/errors9; signatures исправлены без изменения assertions. Descendant
test сначала требовал синхронного listener close (FAIL/ResourceWarning); Windows
Job termination asynchronous, теперь проверяется реальное закрытие≤1s, sockets
закрываются. Отдельный command без PYTHONPATH дал import error; правильный src
env подтверждён без изменения prod imports.

После RAM~20GiB available — actual Tera повтор:

- `runtime/tera-cancel-actual-20261012-r2.json` FAIL/observed exit1 до inference.
  Startup29.331s; proof требовал listenerPID==launcherPID. Tiny read-only Python
  probe подтвердил redirector: launcher20576/child13000/exit0. Прежний port50959
  после cleanup отдельно проверен:0listeners. FAIL сохранён, proof не ослаблен.
- `runtime/tera-cancel-actual-20261012-r3.json` PASS/observed child exit0,
  UTC11Oct22:56:32.606691–22:56:52.700798 (=12OctMoscow). CPU24/distilled/ru_f1,
  44.1kHz; startup11.028s; launcher8660/listener30144 в own Job, ephemeral55594.
  scoped_onnx_run_options; stream TTSCancelled/0chunks, client100.954ms,
  worker pending0 + speech lease idle102.800ms. Не точный native-kernel timing.
-3 non-silent PCM16 WAV: complete1.695/1.465/1.859s, durations3.513/3.517/4.661s,
  RTF0.482/0.416/0.399. `runtime/tera-cancel-actual-20261012-r3-samples/ru-{1,2,3}.wav`;
  hashes в receipt. Не transcript/acoustic quality/first-audible/p95/full RU Q&A.
- Consumer joined, own root+доказанный listener закрыты, guard не сработал;
  minimum available RAM19,394,433,024bytes — global OS, не model peak RSS.
  Daily9889 не запускался; ephemeral PASS не доказывает readiness UI-профиля.

Read-only pinned native source review: exact turn_id→Heartbeat task.cancel→
awaited provider request/CancelledError; cancellation сохраняет durable goal
active/continue. Remote provider compute release и turn admission OPEN;
protected upstream/snapshot не менялись. Следом provider disconnect/whole-profile
synthetic RU; physical duplex и arts отдельно OPEN.

Frozen baseline `runtime/baseline-b1-sse-job-20261012.json`:330 sources,
SHA256 `e393a08b94135f56236bc99312965e2fc23800c7649ea1991307f0176780ee24`,
HEAD0e53329… dirty/not release. Fullgate `gate-sse-job-20261012.{log,json}`:
observed child exit0/terminal receipt passed, UTC11Oct22:58:16.894335–23:03:03.364733
(12OctMoscow),715unit/59pytest/16HTTP/86Node/6legacy browser/8desktop checks PASS.
Unit178.854s/pytest0.96s/HTTP60.742s; stale logger FileNotFoundError=0.
Все330 frozen source hashes после gate совпадают. Browser actual app/capture/
worklet/playback, но ASR/JAWL mock и tone TTS; не full RU/live/device/art acceptance.

### B0 второй срез — изоляция профиля

Local wrapper передаёт ProfileName/NoBrowser/temperature; hardcoded daily
pre-write удалён, native configure пишет выбранную instance после подготовки.
FileShare.None берётся до prepare/configure; отказ подготовки освобождает lock.
Manifest profile ограничен safe basename и не допускает Windows device names.
Real PS invocation из постороннего cwd обнаружил Contains-overload crash на
PSBoundParameters (hashtable fixture его пропускал); исправлено в обоих launchers.
Busy-port/colliding overrides теперь дают ожидаемый отказ без загрузки весов.
Focused tests: 10 launcher +3 native-profile unit,59 manifest/worker pytest PASS.
Первый полный regression этого среза:
`runtime/gate-profile-isolation-20261010.log`, exit1,567 unit/errors1. Отказ на
unauthenticated preface POST дал WinError10053 вместо ожидаемого403; traceback
сервера отсутствует, loopback proxy bypass=true. Не считать это PASS/retry шумом.
В раннем HTTP error обнаружено непрочитанное POST-тело перед закрытием сокета.
Добавлен bounded drain ≤64KiB/200ms total без parse/execute; consumed body не
читается снова, oversized/chunked не drain.6 focused transport tests и6 preface
tests PASS. Это подтверждённое hardening, не доказанный root cause WinError10053.
Полный gate после code change: `runtime/gate-profile-http-drain-20261010.log`.
Журнал дошёл до всех финальных PASS:573 unit/59 pytest/16 HTTP/79 Node,
6 legacy browser/8 desktop composite. Финальный native exit не retrieved:
tool-handle исчез к продолжению, runner-процесса уже нет; одного retry ради
потерянного handle не делали. Следующий gate сохраняет durable exit receipt.
Новый live model/RU/voice PASS не заявляется: при проверке ресурсов обе GPU
занимали ~15GB, RAM free ~2GB. Чужие процессы не трогали. До live проверить
VoiceMem storage/cache isolation выбранной instance и physical GPU1 mapping.

### B0/B1 срез — 2026-10-11

VoiceMem получает explicit `--memory-root` через Companion CLI и выбранную
instance `data/sensory/voicemem`. Inherited VOICEMEM_MEMORY_ROOT не redirect-ит
эти записи; standalone default сохранён.3 mocked CLI/forwarding tests PASS;
модели и прочие HF/torch cache locations не приняты этой проверкой.

Supervisor restart раньше обходил Windows Job assignment; API failures могли
молча оставить процесс вне containment и при этом дать healthy. Start/restart
сведены к checked spawn, failed assignment reap-ит child. Stop закрывает Job
handle, следующий start создаёт новый.13 focused tests PASS с real subprocesses,
WinAPI fault injection и actual Windows parent-kill до/после restart.
Real ASR/TTS/LLM cancel, per-worker descendants и повторный start во время работы
не закрыты. Это не замена B1 voice acceptance.

Rust:22 unit +1 CLI process test PASS. Bounded --check-config не запускает
устройства/воркеры; config errors exit2. В main.rs остался formatting-only churn
агента; точной pre-format копии не было, dirty semantics не откатывали.

Полный gate 11OctMoscow завершён: direct child exit0; durable receipt
`runtime/gate-isolation-ownership-20261011.json` — `status=passed`, `exit_code=0`.
UTC interval `2026-10-10T23:47:55.149590Z`–`2026-10-10T23:52:26.288124Z`;
журнал `runtime/gate-isolation-ownership-20261011.log`. Подтверждённые counts:
581 Python unit /59 manifest-worker pytest /16 HTTP E2E /79 Node /6 legacy
browser /8 desktop composite checks. Snapshot, secret scan, PowerShell parse и
`git diff --check` также PASS. Это synthetic/mock regression: модели,
физические устройства и production/live acceptance не приняты.

### B1 final-ASR cancel — 2026-10-11

`CrispASRFileTranscriber` теперь владеет per-call Popen: проверяет cancel каждые
≤50ms, timeout/exit code, bounded JSON256KiB. Отмена/timeout останавливает и
reap-ит только собственный child перед очисткой временного WAV. Stdout/stderr
не копятся. Fixture с actual Python child доказывает reap, не inference модели.

UtteranceBuffer учитывает in-flight в лимите8, не позволяет подменить активную
реплику, разделяет capture scopes. Release/expiry lease отменяет только его ASR,
в том числе поздний upload после release. Ambient Stop(false) сигналит своей
generation, flush(true) сохраняет drain; close отменяет все owned final-ASR.
Поздний transcript возвращает cancelled без VOICE_TURN/responses. Это не отмена
уже принятого JAWL turn/durable goal и не TTS worker cancellation.

Focused:29 buffer +9 GigaAM child +20 capture HTTP/lease +18 ambient =76 PASS.
При добавлении cancel keyword старые ambient test doubles сначала дали6 FAIL;
их контракт обновлён, assertions сохранены, повтор17 и финальные18 PASS.
Supervisor:16 PASS, включая idempotent start/concurrent Stop/startup retry cancel.
Фокусный запуск без PYTHONPATH сначала не импортировал supervisor; с штатным
src-path PASS. Приёмка не опирается на этот import error. Custom health probes
должны быть bounded: произвольную зависшую Python callback принудительно не прервать.

Новый full regression: `runtime/gate-asr-cancel-20261011.log` и durable
receipt `runtime/gate-asr-cancel-20261011.json`; начат после code freeze среза.
Фактический exit1:603 unit/59 pytest/16 HTTP/6 legacy browser PASS,
desktop E2E timeout на первом голосовом ходе, TTS не вызван. Причина выявлена:
SyntheticFinalTranscriber в browser harness не принимал обязательный новый
cancel_event keyword. Контракт fixture исправлен; добавлен focused тест через
настоящий UtteranceBuffer (5 diagnostics tests PASS). Assertions/timeouts E2E
не ослаблялись. Это другой failure, не прежний network fetch root cause.
Полным PASS остаётся предыдущий gate до terminal результата повтора.
Standalone после исправления fixture: `runtime/desktop-voice-asr-cancel-20261011.json`,
actual tool exit0,8 composite checks PASS. В этом harness TTS tone fixture
проходит реальный HTTP NDJSON serializer/WebAudio, но не заменяет отдельную
приёмку lifecycle самого TTSService или model worker.
Real models/device/barge-in, TTS/LLM compute cancellation, streaming partials
ownership и descendant tree на индивидуальном restart остаются OPEN.

Read-only TTSService fixture дополнительно выявила ownership defect: после
старта stream B закрытие уже superseded stream A вызывает общий provider.cancel
и задевает B (`new_generation_cancelled_before_old_close=false`, after=true).
Это воспроизведённая гонка с synthetic native-stream provider, не доказанная
причина прежних пользовательских обрывов звука. Следующий B1 slice должен
добавить formal regression и generation-scoped transport/provider cancellation.
Этот defect затем исправлен:21 TTS tests PASS (native, whole-WAV, planner,
legacy owner, targeted response/Vox cancellation). Операции старой generation
не отменяют новый transport; explicit cancel остаётся global. HTTP socket
shutdown перед close прерывает actual local incomplete-body read без ожидания
provider timeout. Check после opener перенесён внутрь finally cleanup: late
cancel не оставляет response в tracking map. Vox targeted cancel не отправляет
глобальный worker `/cancel`; compute может продолжаться — это OPEN, не скрытый PASS.

После B1 code freeze запущен `runtime/gate-voice-ownership-20261011.{log,json}`.
Фактический exit1:612 unit,1 FAIL в actual incomplete-body cancellation —3.003s
вместо fixture bound1.5s. Standalone PASS недостаточен: полный gate не принят.
Уточнено закрытие owned socket: после shutdown вызывается native close этого же
socket object, а не копии числового fd; SocketIO refs не должны откладывать
OS close до выхода blocked reader.12 повторов focused actual HTTP PASS и все
21 TTS tests PASS после изменения. Новый полный run:
`runtime/gate-voice-ownership-20261011-r2.{log,json}`; до terminal receipt не PASS.
Governor admission до
supersede, disconnect до first chunk и actual inference release требуют следующего
среза; desktop tone harness не проверяет сам TTSService, он проверяется отдельно.

Post-code-freeze baseline до terminal gate/финальной записи ledger:
`runtime/baseline-b1-voice-ownership-20261011.json`, HEAD `0e53329`,
317 source files, source SHA
`d9c6498bdd48f7b80a0f819644098d9d19972e21ac87f3a0a58e93bca02b36a6`.
Это dirty working-tree metadata, не release commit или принятие моделей/аватара.
После уточнения native socket close сохранён новый baseline
`runtime/baseline-b1-voice-ownership-20261011-r2.json`:317 sources, SHA
`ae7d90eca2df2cfba8da82cae58a803f05187d05c93617b50d83154863c46365`.
Snapshot348 files с SHA `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`
не изменён. Baseline снят до terminal gate/final ledger, не как release commit.

**Terminal результата B1 repeat:** `gate-voice-ownership-20261011-r2` — actual
child exit0, durable receipt `status=passed`, UTC
`2026-10-11T00:23:06.900347Z`–`00:27:26.156229Z`.612 unit/59 pytest/16 HTTP/
79 Node/6 legacy browser/8 desktop composite PASS, плюс snapshot/secret scan/
PowerShell parse/diff-check. Previous603 harness failure и612 latency failure
сохранены выше. Новый PASS не закрывает B1 real inference или hardware acceptance.

### B1 следующий срез — адресная отмена речи до первого аудио

`TTSService` и HTTP synthesis/stream принимают optional `request_id`.
Scoped `/api/tts/cancel` сигналит только его Event; `{}` сохраняет global
speech Stop, не JAWL goal cancel. Strict ID≤128, transient registry≤128;
closed/cancel-before-start tombstones60s, active не вытесняются. Invalid/null
ID не становится global; saturation503; клиент обязан использовать новый UUID.
Desktop abort/stops локально немедленно и отправляет независимый authenticated
keepalive scoped cancel≤1.5s. Done/неотправленный запрос не посылают cancel.
13 новых Python registry/service/actual HTTP tests и7 новых Node tests PASS;
проверены early cancel, cooperative first-chunk cancel, auth, replay, поздний
старый cancel и гонка регистрации с admission без утечки service slot.
21 прежний TTS provider/HTTP test также PASS. Это не real-model CPU release.

Focused старый Node fixture сначала дал4 FAIL `crypto is not defined`, после
добавления browser globals завис: его единый fetch resolver перезаписался cancel
запросом. Остановлен только собственный Node fixture PID31932, exit1. Fixture
разделяет stream/cancel responses; прежние playback assertions сохранены,
объединённый23-test Node run exit0. В полном browser harness tone-provider
намеренно не исполняет scoped cancel: поздний WAV проверяет реальный stale-drop;
добавлена проверка, что cancel ID совпал со старым stream, не replacement.
Full unit stage:625 PASS. В stderr4 logging FileNotFoundError для уже удалённого
temp/logs/pytest.log; те же4 есть в предыдущем green612 gate. Это прежний
test-logger lifecycle debt, не новый request-cancel failure и не исправленный
runtime defect; не менять pinned upstream ради подавления stderr.

Worker review read-only: Tera вызывает whole `_generate` под lock до отправки
headers. Native chunk iterator тоже сначала строит latent; закрытие consumer
не доказывает остановку ONNX CPU. Следующий B1: связать worker request identity,
bounded cancellable queue и per-run inference cancellation в owned adapter;
проверить настоящий release timing. Не менять external Tera source/модели
неявно. Governor replacement admission, header-opener interruption, bare
disconnect, real TTS/LLM compute, native upload и hardware остаются OPEN.

Новый fullgate: `runtime/gate-speech-request-20261011.{log,json}` — actual child
exit0, terminal receipt passed. UTC00:40:44.100256–00:45:04.243042 11Oct:
625 unit/59 pytest/16 HTTP/86 Node/6 legacy browser/8 desktop composite PASS,
snapshot/secret scan/PS parse/diff-check PASS. Browser acceptance подтвердил
scoped old cancel ID и stale-drop при намеренно uncooperative tone-provider.
Real worker/device/art этим не приняты. Pre-gate baseline после code freeze:
`runtime/baseline-b1-speech-request-20261011-r2.json`, HEAD `0e53329`,320 sources,
SHA `765360a6b5d3ccf156dbbbb6f911301b50e2982e2e05538110331073ced21000`.
Это working-tree metadata до финального ledger, не release commit.

### B1 Tera: scoped worker API и native ONNX cancellation

Tera adapter регистрирует UUID per sentence до opener (≤16 requests), передаёт
только owning IDs в `/cancel` batch≤8 с1s socket timeout; failed request тоже
отменяет свой ID, normal success не шлёт cancel. Cozy/Qwen payload contracts
сохранены.28 TTS tests PASS; pending-header cancellation подтверждена.
Worker получил≤8 admitted requests, queue10s, request cancel signal120s и
cancel-before-start tombstones. Pending job пропускается без model entry;
active capacity отпускается после фактического возврата synthesis. Loopback-only,
browser Origin POST reject; LAN — через authenticated Companion gateway.

Owned proxies поверх frozen LoadedTTS и shallow copies четырёх RUAccent
holders дают отдельный ONNX RunOptions на run; Event выставляет terminate
только своим active options. ContextVar изолирует потоки; external Tera source,
shared native sessions/dictionaries и модели не меняются. Unknown layouts/
alternate run API fail closed.8 proxy +9 worker tests PASS (включая service /
governor /Tera adapter /actual worker HTTP с fake native stage до headers).
13 прежних request-registry/HTTP tests PASS. Не модифицирован protected upstream.

Отдельно выполнен `scripts/run_onnx_cancel_acceptance.py --allow-native-onnx`
через `G:\AI\tts_env\Scripts\python.exe`. Report
`runtime/onnx-cancel-acceptance-20261011.json`, actual exit0: ORT1.29.0,
Python3.11.15, CPUExecutionProvider, generated graph372 bytes. Два настоящих
native Loop calls: cancel A4.494ms, B продолжал до своего cancel; follow-up
той же session PASS, native termination status действительно наблюдался.
Owned child ограничен15s timeout/reap, без скачивания/весов Tera. Adapter SHA
`64b8cc196559cbb2470b7eb0ab3c59f33fef8d876065f60b13835addaffca8ba`.
Это один tiny-native fixture run, не Tera quality/RTF/p95/release SLA.
Source baseline `runtime/baseline-b1-tera-onnx-20261011.json`: HEAD0e53329,
324 sources SHA `242b4f5df23bd55bb564d6222ca8af6331eb3d6e1b3611b542fd6539e18faa73`,
до final ledger; dirty metadata, не release commit.

Read-only RAM check: free2,164,720KiB из98,210,360KiB. Heavy Tera weights не
загружались, существующие workers/модели/active avatar не переключались.
Следующий срез: доказать ownership текущего Tera процесса перед controlled
restart, effective cancel capability и real RU model release timing. Bare
disconnect, governor replacement admission, native upload/LLM/Vox cancel,
WORLD mid-call и physical duplex остаются OPEN.120s timer — signal, не hard
kill monolithic C++/postprocessing. Не считать код активированным в старом
живом worker автоматически.
Read-only listener probe после этого среза: на9889 listener отсутствует;
не подтверждён ни старый, ни новый Tera runtime. Следующий live шаг — controlled
owned start при достаточной RAM (или доказанный restart, если внешний state
успеет измениться), а не blind kill порта. Native fixture не исправляет offline
daily profile автоматически.

Fullgate `runtime/gate-tera-onnx-20261011.{log,json}` после code freeze завершён:
actual child exit0, terminal receipt passed. UTC11Oct00:59:24.460403–01:03:48.552238;
649 unit/59 pytest/16 HTTP/86 Node/6 legacy browser/8 desktop composite PASS,
snapshot/secret scan/PS parse/diff-check PASS. Synthetic +tiny native fixture
не закрывают Tera weights, daily/device/art acceptance; очередь B1 остаётся partial.

### B1 speech admission/lease и Tera shutdown — 2026-10-11

Новая реплика резервирует latest intent до governor admission, отменяет previous
и ждёт слот≤2s default, cancellation poll≤50ms. При A→B→C ожидающая B не
публикуется после C. Early-cancel/replay не отменяет текущую речь. Lease держит
captured governor до возврата всех local provider calls: отмена consumer не
имитирует освобождение uncooperative compute. Paused native iterator закрывается
перед передачей слота; old cleanup не повторяет close/не освобождает B. Factory,
next и reentrant close тоже проверены. Setup/submit errors не теряют leases.
Service.close идемпотентен, будит waiters/rejects new work; смена governor при
live lease запрещена. Planner≤1 per service; cancelled stream не ждёт его
network timeout, но сам request пока завершается по bounded timeout.

Tera runtime.close под admission lock запрещает новую работу и сигналит только
owned active/queued tokens; repeated/concurrent close safe. Standalone закрывает
runtime до HTTP server, daemon handlers не заставляют ждать arbitrary native
completion. Это cooperative ONNX cancellation, не forced WORLD kill.

71 focused tests PASS:17 admission +28 provider +13 registry/HTTP +13 worker,
14 subtests. Fixtures/cheap local HTTP, без Tera weights. Luna review выявил
native iterator lifetime и unbounded planner fan-out; исправлено и перепроверено.
Новый fullgate `runtime/gate-speech-lease-20261011.{log,json}` после source
freeze завершён: actual child exit0, terminal receipt passed; UTC11Oct
01:22:32.871314–01:26:53.684570.670 unit/59 pytest/16 HTTP/86 Node/6 legacy
browser/8 desktop composite, snapshot/secret scan/PS parse/diff-check PASS.
Baseline325 sources SHA
`683637a0859dc82d09057006d7b721f76bc847713a46888d928d962447c015f8`, HEAD0e53329,
`runtime/baseline-b1-speech-lease-20261011.json`, до final ledger/not release.
Слот честно отражает local calls, не неизвестное время remote compute. Actual
model/RU/device/LLM/Vox/bare disconnect и B1 acceptance остаются OPEN.
Новые weights/process switches/device capture/UAC не выполнялись; active avatar
и protected upstream сохранены. Tera9889 offline по последнему probe.
Новый read-only resource probe во время gate: RAM free1,684,576KiB,
GPU0 used15,746MiB/free232MiB, GPU1 used15,496MiB/free482MiB;9889 listeners0.
Не загружать Tera вслепую и не считать прежнее разрешение GPU1 её доступностью.

Четыре прежние logger FileNotFoundError повторились. Read-only Luna review
связал stack с test_jawl_goal_recovery.py: logging.shutdown закрывает, но не
отцепляет созданные handlers перед temp-directory cleanup. Следующий
test_jawl_goal_voice_continuity сохраняет их как preexisting; native cancel
провоцирует reopen удалённого logs/pytest.log. Следующий owned fixture fix —
identity snapshot до import, detach+close только новых handlers до temp delete,
сохранить чужие. Две records×две handlers — inference, не точное измерение.
Изменений logger/source для этого исследования не было.

### B0/B1 streaming capture и fixture cleanup — 11Oct, подтверждение 12Oct

Streaming ASR теперь имеет одного process owner `(scope_id, session_id)` и
capture cancel token. Новый capture/utterance reaps прежний child до нового
spawn; old readers/watchers не публикуют state новой generation. Raw PCM≤48KiB,
resampled mono≤96KiB, queue≤8 chunks (+1 writer), максимум864KiB PCM в этих
слотах. JSON line≤64KiB/text≤4000, invalid schema/numbers не отравляют snapshot.
Pipe writer отдельный: HTTP feed не ждёт блокирующий stdin.write. Overflow
отключает partial lane без подмены final ASR; retry только после reset.
Expiry/release watcher50ms завершает только own child; process pointer очищается
после reap, не при одном detach reader. Failed reap сохраняет tracked child и
не разрешает replacement. Public close terminal/idempotent; scoped reset не
затрагивает чужую реплику. Descendant tree и real-model latency этим не приняты.

HTTP: feed после canonical PCM acceptance; draft/preface/WS reset авторизуют
capture и фильтруют scope/session; late cancellation после snapshot даёт пустой
cancelled result. Release discards только свой scope, old final/reset не трогают
replacement. Final GigaAM остаётся canonical; draft сам не создаёт USER_FINAL.
17 bridge +9 scoped HTTP tests PASS, включая actual gateway/buffer/bridge/cheap
Python child. New-utterance restart обязателен для текущего raw stream protocol
без acknowledged reset; стоимость reload/warm latency измерить на GigaAM.
Desktop partial UX этим не завершён; provider/model не переключался.

Первые focused проверки выявили premature `_process=None` до reap; код исправлен,
assertion фактического child exit сохранён. Новый HTTP harness сначала не прошёл
строгий VoiceMemProcessClient type-check; fixture исправлена без ослабления
production boundary. Итог29 focused PASS (17+9+3 recovery/continuity),2 subtests,
1 nonfatal Python3.14 Kuzu-unavailable warning; отдельный broad107 PASS.

Luna исправил test_jawl_goal_recovery: snapshot identities до native import,
detach+close только новых handlers до temp cleanup, preexisting сохранены.
Recovery/continuity/cleanup3 PASS, stderr empty. В fullgate прежних четырёх
FileNotFoundError больше нет (count0); pinned logger не изменялся.

Native Rust повторно проверен без source rewrite: cargo test --offline,
22 unit (16 capture/mock-HTTP+6 config/manifest) и1 CLI PASS, exit0.
Stalled upload/final Stop+join<1s, stale ACK drop/queue clear/no replay — fixtures,
не hardware/model latency.10s — uncancelled upload deadline, не текущий Stop wait.
main.rs SHA `346ccc6952cd06317e6c70b5b6c6644ca9b68888a82b033d7ff3fc5de30e1859`
совпал с baseline до среза.3 unused-code warnings сохранены, не скрывались.

Fullgate `runtime/gate-stream-capture-20261011.{log,json}`: actual child exit0,
terminal receipt passed, UTC11Oct01:43:01.340165–01:47:29.336006.
693 unit/59 pytest/16 HTTP/86 Node/6 legacy browser/8 desktop composite PASS;
snapshot/secret scan/PS parse/diff-check PASS. Baseline326 sources SHA
`5c8c8d88fd6b16c03f40df5786e0f50791f90d3bef18d22109bed639d76fa22d`, HEAD0e53329,
`runtime/baseline-b1-stream-capture-20261011.json`, до final ledger/not release.
12OctMoscow tool handle17573 уже отсутствовал; terminal receipt/log проверены,
все326 записанных source hashes совпадают. Gate ради потери handle не повторялся.
Fresh RAM free4,754,504KiB,9889 listeners0; heavy weights/device capture не
запускались. Protected upstream/selected models/active avatar не изменены.
Далее controlled owned Tera start/actual RU cancel при RAM guard, либо независимые
B1 turn/LLM cancellation и B2 partial UX; full B1/daily/device/art остаются OPEN.

## B0 evidence — 2026-10-10

Baseline `runtime/baseline-b0-manifest-20261010.json`: HEAD `0e53329`,
313 source hashes, source SHA `dc6741634a1bd7db4b2709a8d61bf3ee0f6467683991679c869a5caa522c5d7d`.
Snapshot348 files, SHA `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`, PASS.
Это working-tree baseline до дополнительной harness-диагностики, не release commit.

Первый fullgate `runtime/gate-runtime-manifest-20261010.log`, exit1:
558 unit /48 manifest+worker pytest /16 HTTP /6 legacy browser PASS;
desktop voice FAIL `busy_owner_rejected_before_media_permission` — немедленный
`Failed to fetch`, media permission не запрашивался. Node79 и PS parse3
пройдены отдельно. Полный gate этим прогоном не принят.

Добавлена bounded/redacted fetch/UI/console диагностика,4 focused tests PASS.
Standalone `runtime/desktop-voice-e2e-diagnostic-20261010.json`, exit0,
8 composite checks PASS, включая busy-owner/no getUserMedia. Причина исходного
network failure не доказана; результат не замалчивается и не заменяется retry PASS.
Повтор `runtime/gate-runtime-manifest-20261010-r2.log`: все этапы PASS,
562 unit /48 pytest /16 HTTP /79 Node /6 legacy browser /8 desktop composite
checks. Внешний PowerShell redirect сообщил1 несмотря на все stage PASS.
На маленькой stderr-only fixture доказан runner artifact: redirect-only shell
даёт1, а сохранённый native child exit —0. Не приписывать это сбою приложения.
Контроль через subprocess: `runtime/gate-runtime-manifest-20261010-direct.log`,
actual child exit0, все этапы PASS. Приложение после диагностики не менялось.
Актуальный source/dirty/artifact baseline после harness-изменений:
`runtime/baseline-b0-manifest-20261010-final.json` (до финальной записи ledger).

## Последний полный regression gate

2026-10-12 Moscow, direct child exit0,
`runtime/gate-sse-job-20261012.{log,json}` (UTC11Oct22:58:16–23:03:03):

- 715 Python unit +59 manifest/worker pytest;
- 16 HTTP E2E,86 Node, synthetic mic gate;
- 6 legacy browser checks,8 desktop composite checks;
- pinned snapshot/secret scan/PS parse/diff-check PASS.

ASR/JAWL mock, TTS tone WAV; production/live/device/art acceptance NOT
accepted. Исторический gate `runtime/gate-profile-isolation-20261010.log`
сохраняет fail 567 tests и WinError10053; subsequent
`runtime/gate-profile-http-drain-20261010.log` дошёл до 573 stage PASS, но
его direct final exit был потерян вместе с tool handle. Initial fetch/network
root cause остаётся OPEN и не объявляется исправленным новым regression.
Предупреждения immutable config_io/Node module type не устранены этим срезом.

### Предыдущий regression — 2026-10-05

`runtime/gate-hair-v8-scene-lifecycle-20261005.log`, exit 0:

- 551 Python unit;
- 16 HTTP E2E;
- 75 Node;
- 6 legacy browser checks;
- 26 desktop synthetic acceptance условий, run
  `233599d5c19d46da8d6263fba3aa7c8d`;
- snapshot verification, secret scan и diff checks PASS.

Границы: реальные `/app`, HTTP NDJSON serializer, capture route,
AudioWorklet/WebAudio; ASR/JAWL — mocks, TTS — tone WAV, mic — synthetic
MediaStream. Не real provider/device, не измерение RU-качества или echo.
47 config_io ResourceWarnings immutable snapshot остаются диагностическим
долгом; защищённую/пинованную копию ради suppress не редактировать.

## Голос и lifecycle

Реализованы выбор/сохранение входного устройства, gate/hysteresis/pre-roll,
endpoint по тишине, capture lease, bounded PCM/upload и stale generation
drop. Endpoint default1200ms настраивается; рабочее значение принимает
физический тест, не только сохранение slider.

Playback: NDJSON-аудио, slices≤0.4s, scheduled horizon≤0.8s, audio budget
32MiB/300s, wire budget64MiB до decode/split. Бюджет transport не равен
проверенному peak RAM. Cancel убирает scheduled звук и поздние chunks.
Закрытие HTTP не доказывает остановку inference worker.

Rust path имеет16 capture/mock-HTTP +6 config/manifest unit и1 CLI PASS.
Upload/final wait cancellable, stalled Stop+join<1s в mock HTTP;10s — deadline
без cancel. Native hardware duplex/real provider latency не приняты.
Desktop ASR partials ещё не показаны в основном разговорном UX.
Рот аватара реагирует на playback RMS — это не фонемный lip-sync.

OPEN: текущий real GigaAM/JAWL/TTS connected route, cold/warm p50/p95,
физический микрофон/echo/duplex, worker cancellation, сохранение durable goal
после voice Stop. Старые сентябрьские live timings не переносить на этот срез.

## Ядро, память, инструменты

Отдельные ранее сохранённые срезы подтверждают native levels0–3 и
DebugBroker representative acceptance, remember→revise→restart→recall,
provider failure после native effect и action-reconciliation, supervisor
startup/stop и ROOT lease revoke/recovery.

Это не приёмка всех инструментов на любых целях, arbitrary syscall crash,
8h unattended или текущего voice-task сценария.
`BrowserAdapter` открывает URL/делегирует UIA; полноценный изолированный
CDP browser остаётся открытым.

Ambient T1/T2 и consent preferences process-local; triage/scheduler и manual
promote есть. Автоматическая durable консолидация, полное erasure индексов/
сводок и restart continuity этих слоёв OPEN. System loopback/vision имеют
код и отдельные проверки, не полную текущую аппаратную приёмку.
Принятой модели music/non-speech/voice-affect analysis нет.
Состав канонической памяти и VoiceMem: [SECONDARY_MEMORY](SECONDARY_MEMORY.md).

## Интерфейс, LAN и OBS

ConfigHub уже имеет revisions/conflicts, backup, masking, readback и restart
semantics. Полная field/action parity, object-list round-trip и показываемое
effective состояние ещё не приняты.

Основной desktop chat — text+mic. UI восстановления истории, вложения,
emoji picker, slash menu, полноценная библиотека памяти и экран целей/действий
OPEN. Backend adapters не равны готовому desktop UX.

LAN HTTPS/auth/origin основа есть, реальный tablet/mobile touch/mic не принят.
Presentation security boundary есть; актуальная VRM-сцена в настоящем OBS,
общий state, DPI/multimonitor и длительная работа OPEN.
Старый Live2D OBS evidence не переносится на VRM.

## Персонаж: последний отдельный кандидат

`runtime/vrm-models/JawlieInterfaceV9.vrm`, 14,327,276 bytes.
SHA256 `b0396e670a86a873c0932489735b7bf19e045dfc8ba9912804b47341530c8ba6`.

Geometry run `41520a7b54ac4b25bcbe28951e209abc`, actual-scene run
`74b2ce657f914801972a7d349c0380fd`, seam run
`bd56a8c597794266b197d1b8c11188a2`: PASS, одинаковый SHA.
34 wrist +34 ankle checks, rest+16 isolated poses; max outward hit
3.613/3.319mm при порогах5/6mm. Closed sole, connected bomber и cargo
clearance проверены в ограниченных позах.

Это подогнанное перекрытие и согласованный skinning, не единый сваренный
skin/clothes mesh и не full collision acceptance.
Active avatar не переключён. Волосы/лицо/посадка одежды/края манжет/
шнуровка требуют художественной доработки; ≥90 likeness не измерено/не принято.
39 weighted hair bones и6 colliders,6 weighted soft helpers — не полная
cloth/body physics. Пять VRMA экспортированы, product playback ещё OPEN.

[Review V9](CHARACTER_INTERFACE_V9_REVIEW.md) ·
[art direction](CHARACTER_ART_DIRECTION.md) · [animation plan](AVATAR_ANIMATION_PLAN.md).

## Поставка и следующий шаг

Wheel/build smoke существуют; полный clean install, manifests/assets/licenses,
upgrade/backup/restore/rollback, общие RAM/VRAM/frame-time бюджеты OPEN.
`main` при аудите ahead41; рабочее дерево содержит много прежних dirty changes.
Никакого commit/push или авторства по timestamps этот документ не утверждает.

Следовать B0→B1→B2→B3, затем U/P/A и B4 по [TODO](../TODO.md).
Старый delivery goal не COMPLETE; текст плана не доказывает активную задачу.
Полная прежняя STATE сохранена в
[архиве](history/2026-10-10-before-docs-consolidation/INDEX.md).
