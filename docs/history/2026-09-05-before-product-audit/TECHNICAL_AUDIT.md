> Исторический снимок до аудита 2026-09-05. Утверждения и команды не являются актуальными инструкциями. Содержит в том числе неподтверждённые pass/RC claims. Текущие решения — docs/PRODUCT.md, TODO.md, docs/STATE.md.

# Технический аудит и критерии готовности

Дата актуализации: 2026-09-05.

Этот документ описывает фактическое состояние текущего checkout. `TODO.md`
является очередью работ, а `docs/STATE.md` — журналом срезов и проверок.
Зелёные mock/unit/E2E тесты не означают, что подключённые внешние модели,
JAWL, микрофон, OBS или Windows UI уже прошли live-приёмку.

## Итог

Репозиторий — рабочий архитектурный прототип с несколькими готовыми
вертикальными срезами, но ещё не production release. Основные P0-риски
сейчас не в выборе TTS/VLM, а в live-подтверждении границ: JAWL должен быть
единственным исполнителем действий, а Companion — транспортом, сенсорным
слоем и UI.

## Последняя проверка checkout — 2026-09-05

- Официальный `scripts/run_full_gate.ps1`: **252 non-E2E + 14 HTTP E2E**,
  `compileall`, синтетический mic-gate, Node-проверка и `git diff --check` —
  успешно.
- `scripts/run_browser_render_smoke.ps1` на Microsoft Edge подтвердил control
  DOM, voice-gate, health/OBS markers и изолированную avatar surface.
- `scripts/build_release.ps1` выполнен дважды с одинаковым wheel SHA-256
  `2140c4f6b74f0a4ff3800921ab5eaae2450d813ef5d60c0ebb2242f24f793bda`.
- Guarded target smoke with a disposable native JAWL launch passed Companion
  control/presentation checks, JAWL `running=true`, native policy authority
  `jawl` and access level `1`. The provider used a loopback sink and placeholder
  key; owned detached descendants and port `8773` were cleaned. This validates
  startup/policy wiring only, not provider quality or physical target acceptance.
- The resulting wheel was force-reinstalled into an isolated temporary Python
  3.14 environment; package import, installed `frontend/index.html` and the
  `jawl-voicecompanion --help` entry-point smoke all passed. This closes the
  local clean-install layout check only, not target-machine acceptance.
- Расширенный `scripts/run_restart_soak.ps1 --cycles 5 --probes 4` прошёл
  **5/5** циклов, **30** health samples, без forced stop и port leak.
- Target-release smoke на живых control `2367` и presentation `8766` прошёл
  health/doctor/resources, HTML и presentation isolation checks. JAWL,
  provider и Live2D в degraded-профиле намеренно не требовались.
- Прямой disposable JAWL live namespace profile обнаружил **114** native skills:
  `HostOS 105`, `HostTerminal 2`, `DebugBroker 7`; восемь read-only probes
  прошли через native HTTP route. Catalog matrix на уровнях `0..3` сохранила
  те же 114 записей и совпала с каждым `required_access_level`.
- Прямой disposable JAWL policy profile прошёл уровни `0..3`, native
  write/delete/metadata/monitoring slice, fail-closed emergency-stop/reset и
  bounded ROOT autonomy issue/revoke. Профиль восстановил исходный уровень;
  при ранней ошибке его `finally` cleanup также восстанавливает уровень и
  временные safety state. Evidence: `runtime/native-jawl-policy-20260905-fixed.json`.
- Это обновляет automated/reproducible evidence, но не закрывает live
  microphone/WASAPI, физический OBS/Live2D, VLM, provider permanence или
  target-machine acceptance rows ниже.

## Что уже реализовано и проверено

- Нативный JAWL Companion Gateway: коррелированный `turn_id`, типизированные
  `turn.started`, `tool.completed`, `turn.cancelled`, `turn.error` и строгий
  финальный `ResponseEnvelope` v1. Старый broadcast сохранён только как
  совместимость.
- Отмена проходит по точному `turn_id` через Heartbeat и отменяет текущий
  React task; отмена не создаёт запись в истории.
- Control и presentation разделены на loopback-серверы. Presentation получает
  только минимальное состояние аватара, не получает console token и не имеет
  control POST API. Control использует HttpOnly session cookie, CSRF-сессиону
  и security headers.
- JAWL — native policy authority: уровни `SANDBOX=0`, `OBSERVER=1`,
  `OPERATOR=2`, `ROOT=3`, versioned policy snapshot, emergency stop,
  expiring ROOT autonomy lease и native `/api/hostos/skill` proxy. В bridge
  режиме Companion не выполняет `/api/hostos/execute` локально, если запрос
  должен идти в JAWL. Standalone/mock fallback остаётся намеренно доступным.
- Bridge emergency-stop is fail-closed: the local latch is set immediately,
  but the response is not successful unless native JAWL policy and agent stop
  both succeed. Reset starts the native agent while the latch is still set and
  clears it only after both native operations succeed.
- HostOS emergency stop останавливает managed script sessions и отслеживаемые
  native execution subprocess trees. Lease хранится атомарно и не
  восстанавливается при понижении уровня или emergency stop.
- Debug Broker сохраняет динамические native providers и каталог из 35
  операций. Для операций есть `risk` и `minimum_access_level`; Companion не
  копирует их wrappers.
- Native и fallback filesystem mutations используют atomic replace; удаление
  по умолчанию обратимо через quarantine, постоянное удаление требует явного
  флага. Fallback mutating tools имеют bounded idempotency cache.
- Микрофон переведён на AudioWorklet, имеет hysteresis gate, pre-roll,
  calibration, RMS/peak UI, bounded pending queue и flush последнего чанка.
  Проверен синтетический gate; реальный dynamic microphone ещё не принят.
- Системный audio loopback отделён от `USER_FINAL`; self-TTS подавляется по
  короткому playback span. Реальные WASAPI/ASR/echo условия ещё не приняты.
- TTS поддерживает sentence streaming, resource priority, emotion→rate
  mapping и закрытие активных HTTP response bodies при cancellation, включая
  досрочно закрытый sentence generator. Это останавливает транспортный
  запрос; провайдер, который уже начал inference до выдачи HTTP body, может
  потребовать отдельный worker/process boundary.
  Текущий low-latency профиль — TeraTTSv2. Qwen3-TTS 12Hz 0.6B Base добавлен
  как отдельный clone/quality worker с тем же REST-контрактом; его CPU
  генерация не считается real-time, а provider-native interruption и
  emotion-control остаются ограничениями.
- JAWL получил canonical append-only `structured_memories`: `fact`, `trait`,
  `preference`, `summary`, provenance/source/confidence, `remember`, `revise`,
  `forget`, `archive`, superseding revisions и bounded prompt projection.
  Browser/Companion memory API ходит через JAWL control socket.
- Native JAWL exposes a bounded read-only action-journal projection. Companion
  can show recent autonomous plan states, outcomes and unresolved actions
  without receiving original parameters or execution authority.
- Vision остаётся opt-in и без VLM по умолчанию. Screen capture выдаёт
  transient JPEG, SHA-256 и короткий подписанный observation token, связанный
  с HWND/class/bounds/frame; production pointer adapter может потребовать этот
  token. Добавлены строгий `VisionActionPlan` v1 и последовательный
  `VisionPlanExecutor`: он повторно проверяет token и digest кадра перед каждым
  действием, проходит через HostOS policy и требует verified postcondition.
  Explicit route/native JAWL HostOSDesktop mapping is implemented, including
  bounded Windows cursor verification for pointer actions. Optional transient
  OCR grounding and opaque pixel redaction run before JPEG/VLM upload; VLM
  selection remains intentionally deferred.
- Есть lightweight `ResourceGovernor` с профилями low/standard/high,
  gaming backoff и `/api/resources`; doctor/health показывают его состояние.
- Установлен build backend, pinned dev requirements и gate предпочитает
  `.venv`. Нативные зависимости модели/веса в репозиторий не копируются.

### Свежие live smoke-факты

Срез 2026-09-03 дополнительно подтвердил browser-render и локальный
restart/soak, но не изменил release-границы ниже:

- `scripts/run_browser_render_smoke.ps1` прошёл на Microsoft Edge: control и
  isolated avatar/OBS DOM markers отрендерены headless-браузером, временный
  browser profile и Companion process корректно завершены.
- Corrected `run_restart_soak.ps1 --cycles 3 --probes 3` прошёл **3/3**,
  `15` health samples, без forced stop и port leak.

- Локальный TeraTTSv2 worker реально запустился на loopback и отдал русский
  WAV. Пять запросов через выбранный `TeraTTSHttpClient`: first complete WAV
  p50 1.223 s, p95 1.313 s, median RTF 0.344; concurrent `TTSService.cancel`
  вернул `TTSCancelled` за 1.164 s. Это подтверждает текущий REST/transport
  boundary, но не native interruption внутри Tera inference.
- JAWL реально поднял HostOS level 3 и 7/7 Debug Broker providers. Gateway
  profile не принят: QWB upstream ответил HTTP 503 `upstream_waf_challenge`
  на reconnect probe, поэтому 100 correlated turns и final-envelope
  preservation остаются незакрытыми. Это внешний provider/session blocker,
  а не зелёный результат mock-теста.
- Реальный VoiceMem sidecar из `G:\AI\VoiceMem\.venv` с локальным E5
  режимом обработал текстовый `feed_partial(ended=True)` за 7.405 s на
  холодном запуске и вернул `USER_PARTIAL` + `VOICE_TURN`; stdout-диагностика
  не нарушила JSON-lines. Это только text/final integration evidence.
- Sidecar lifecycle получил явный bounded prewarm `text|audio`; оба режима
  реально вернули `VOICE_READY`, audio prewarm занял 9.578 s. Health больше не
  маскирует состояние audio path константным `false`.
- Новый `run_voicemem_profile.ps1` прошёл на реальном VoiceMem fixture:
  272 chunks, 3 partials, 1 final turn, first turn 14.317 s, audio prewarm
  8.618 s, без деградации процесса. Fixture zh-en; русский acoustic acceptance
  остаётся отдельным требованием.
- Ollama fallback также ответил через Companion-compatible client (health
  `online`, непустой ответ за 1.085 s). Native JAWL provider switch и его
  100-turn acceptance ещё не выполнены, поэтому QWB blocker остаётся.
- Изолированный JAWL+Ollama startup smoke не дошёл до provider: JAWL обнаружил
  повреждённый локальный ONNX-кэш embedding-модели (`model_optimized.onnx`) и
  перешёл в повторную загрузку. Чистый retry data-dir устранил corruption,
  но загрузка embedding не завершилась в ограниченном окне. Оба профиля
  остановлены без принятия Gateway evidence; это отдельный upstream
  runtime/cache/download blocker, а не доказательство несовместимости Ollama.
- `scripts/run_browser_render_smoke.ps1` реально прошёл на установленном
  Edge: headless DOM control-plane и изолированной avatar/OBS surface
  проверены, временный browser profile и Companion-процесс корректно
  завершены. Это browser-render evidence, но не физическая OBS/Live2D/
  transparency приёмка.
- Default-port smoke подтвердил control `2367` и presentation `8766`; launcher
  также отказал до запуска при занятом FoxMCP `8765`. JAWL console remains a
  separate `8770` service; equal non-zero control/presentation ports are also
  rejected before Python startup.

## Superseding native JAWL live evidence — 2026-09-03

- The real isolated JAWL + Ollama runtime reached provider initialization
  with `native_tools=True`, executed the native terminal skill and passed a
  clean one-turn Gateway smoke: reconnect/resume, exact cancellation, typed
  tool lifecycle, final envelope and cursor continuity all passed.
- The required 100-turn acceptance is **not** closed. It reached 23/100 and
  stopped when the configured Ollama model returned an empty final answer;
  JAWL's bounded retry then left the turn without a terminal envelope until
  the profile timeout. This is a model/provider reliability blocker, not
  evidence of a transport or correlation failure.
- The retry runtime used a valid FastEmbed ONNX cache, so the earlier corrupt
  cache/download blocker is superseded. Evidence report:
  `runtime/native-gateway-ollama-100turn-2026-09-03.json`.
- During this validation JAWL was hardened to preserve native one-turn
  termination, report the real default action status, avoid replaying a
  cancelled wake and keep idle SSE clients alive below common read timeouts.
- The authenticated Companion bridge was then verified against the same
  runtime: the adapter observed native policy authority `jawl` at level 3 and
  successfully forwarded one HostOS and one Debug Broker read-only call.
  Broader read-only namespace probes also succeeded. Its new live
  `skills.catalog` call returned 114 registered HostOS/HostTerminal/Debug
  Broker skills across 25 namespaces, all available at level 3. Discovery is
  now evidenced; mutating, approval, cancellation and level 0–3 parity remain
  open.
- A temporary real Qwen3-ASR `llama-server` on loopback `8984` was exercised
  through the Companion `OpenAICompatibleASRClient` using Russian TeraTTSv2
  samples: `welcome.wav` completed in **0.431 s** and `poem.wav` in
  **1.473 s**, both returning Russian text. The process was stopped and the
  port released. This validates the final HTTP utterance bridge, not live
  microphone/WASAPI, echo/barge-in or true partial-ASR behavior.
- The disposable native policy probe was not accepted as live evidence:
  JAWL startup failed with `OSError: [Errno 28] No space left on device` while
  writing its PID because `G:` had only 8 KiB free. Its process was stopped and
  `8773` released; FoxMCP `8765` was not touched. Retry requires a runtime
  volume with at least 2 GiB free, after which the level 0–3 matrix must still
  be run and reviewed as a separate release gate.
- The retry ran on a disposable C: runtime with
  scripts/run_native_policy_profile.py. The native filesystem matrix passed
  at levels 0–3; emergency stop blocked a native read until explicit reset;
  and the bounded ROOT lease issued and revoked cleanly. Report:
  runtime/native-policy-live-2026-09-03.json. This closes only the safe
  filesystem policy slice; full native namespace, Debug Broker, approval and
  supervised-recovery parity remain open.

## Оставшиеся P0-блокеры

1. **Live native gateway.** Нужно прогнать JAWL + выбранную модель минимум на
   100 correlated turns: streaming, reconnect/resume, tool lifecycle,
   cancellation и отсутствие `no_broadcast`. QWB-JAWL proxy, GPT Luna или
   локальная модель подключаются внутри JAWL, а не отдельным мозгом Companion.
   Локальный Ollama retry уже достиг provider после восстановления валидного
   FastEmbed cache; текущая причина отказа — пустой final answer модели на
   23-м из 100 turns, а не embedding startup.
2. **Native policy parity.** Native `hostos.skill` и Debug Broker уже имеют
   правильную точку входа, но нужна live-матрица каждого JAWL tool namespace:
   level 0–3, approvals, audit redaction, idempotency, cancellation и
   emergency stop. ROOT означает права Windows account, а не обход UAC,
   EULA, provider failure или файловых ACL.
   Native `HostOSDesktop` annotations now match the shared matrix: observation
   is `OBSERVER`, interactive/system GUI actions are `OPERATOR`, and level 0
   input is denied.
3. **Autonomy recovery.** Native supervised restart теперь fail-closed: при
   crash восстановление допускается только для конкретного instance с
   действующим bounded ROOT lease и HostOS level 3; pending/approved one-shot
   approvals при старте инвалидируются. Target-machine live evidence ещё
   требуется.
4. **Live voice/TTS.** TeraTTSv2 и Qwen3-ASR имеют локальные worker smokes,
   а VoiceMem подтверждён на text/final sidecar path. Всё ещё нужны реальный
   microphone gate/WASAPI, VoiceMem acoustic streaming, playback suppression,
   barge-in и device p50/p95; bundled VoiceMem sherpa не принимается как
   русский acoustic ASR.
5. **Reproducible live release.** Mock gate воспроизводим, но нет полного
   target-machine profile с внешними process startup, models, permissions,
   OBS и restart/soak evidence.

## Оставшиеся P1 и осознанные ограничения

- Ambient buffer и episodes пока transient. Ручная promotion-кнопка отправляет
  только явно подтверждённый `promote_candidate` в JAWL
  `structured_memories`; автоматическая idle-promotion и raw audio/video
  persistence не включены.
- Structured memory теперь имеет UTC valid-time поля и retention tiers.
  JAWL's existing hybrid RAG and tick-triggered subconscious patterns cover
  bounded Vector/Graph recall plus Sleep/Reflection/Consolidation when the
  real Kuzu backend is available; import-only Kuzu stubs now fail closed.
  Daily
  summaries now use the canonical append-only `journal:YYYY-MM-DD` memory key;
  commitments remain native TaskTable records referenced by bounded IDs.
  Expired structured revisions are now archived by the native bounded
  forgetting skill without erasing history; live autonomous acceptance remains
  open.
  Ambient UI уже поддерживает явные `disable`/`disable_and_erase` semantics.
- `VisionActionPlan` валидирует schema, identity, token, finite coordinate
  bounds, deterministic idempotency key и postcondition declaration.
  `VisionPlanExecutor` исполняет только последовательную цепочку через
  обычный HostOS policy gate и останавливается без verified postcondition;
  supported native JAWL HostOSDesktop mapping доступен через явный
  session/CSRF-confirmed route, а VLM остаётся незакрытым.
  Выбранная VLM модель ещё не зафиксирована пользователем.
- Live2D runtime/model bundle не поставляется репозиторием. Сейчас есть
  лицензийно нейтральный 2D fallback и изолированный OBS URL. Нужны реальный
  пользовательский bundle, прозрачность, DPI/multi-monitor, click-through,
  drag, lip-sync и browser/OBS soak.
- Passive screen/audio observation остаётся opt-in, с deny-list, TTL,
  bounded metadata и без raw persistence. Screen capture supports optional
  transient OCR grounding and opaque redaction of configured rectangles and
  sensitive OCR regions; title/class filtering remains an independent deny-list.
- Браузерный UI остаётся dependency-light single-page surface. Разделение на
  маленькие модули допустимо только после измерений; тяжёлый framework не
  добавлять автоматически.

## Каноническая архитектура

```text
LLM provider (local/cloud/QWB/Luna)
             │ только внутри JAWL
JAWL cognitive runtime
  persona · Heartbeat · ReAct · native memory · native tools
             │ typed Companion Gateway
JAWL policy/control authority
  HostOS 0..3 · lease · approvals · audit · Debug Broker · stop
             │ loopback HTTP/control socket
Companion
  ASR/TTS · gate · ambient sensors · Vision capture · arbiter · governor
  control UI ───────────────┐
  isolated presentation ───┴─> 2D Live2D/fallback + OBS
```

Companion не должен принимать решения, какой из двух executors использовать
для model-originated side effects. Если JAWL bridge включён, native skill
endpoint — единственный путь. Без bridge локальный executor разрешён лишь как
явно выбранный standalone/development profile.

## Обязательная release-матрица

| Профиль | Приёмочное доказательство |
|---|---|
| Contract | strict JSON, Unicode, malformed input fail-closed |
| Mock E2E | HTTP UI, chat, cancellation, gate, degraded providers |
| JAWL live | 100 correlated turns, tools, reconnect, cancel |
| Voice live | real mic, tail flush, gate, ASR, echo, barge-in |
| TTS live | first-audio p50/p95, provider cancellation, emotion fallback |
| Vision live | signed fresh token, UIA/canvas action, postcondition |
| HostOS | levels 0–3, idempotency, lease expiry, crash recovery, stop |
| Debug Broker | all seven providers, catalog parity, redacted audit |
| Memory | provenance, correction, forget, retention, restart |
| Avatar/OBS | isolated URL, real bundle, lip-sync and soak |

До прохождения применимых строк статус проекта остаётся `prototype` или
`release candidate in validation`, но не `production-ready`.

## Secrets and external dependencies

API key, опубликованный в переписке, не найден в tracked файлах и не должен
попасть в документацию, `.env` или тестовые fixtures. Его необходимо отозвать
и выпустить заново на стороне TokenRouter. TTD traces, process memory, UAC и
лицензии внешних инструментов не автоматизируются агентом.

## Порядок продолжения

1. Live smoke native JAWL Gateway и native HostOS skill parity.
2. Supervised lease recovery и native audit/idempotency matrix.
3. Real microphone/TTS/loopback acceptance.
4. Ambient promotion в JAWL structured memory.
5. Vision plan executor с fresh-token/postcondition tests.
6. User-provided licensed Live2D bundle, OBS/browser/desktop-pet soak.
7. Финальный target-machine packaging/release gate и подпись артефакта.
## Native Gateway profile tooling

`scripts/run_native_gateway_profile.ps1` is a dependency-free live acceptance
harness for the JAWL HTTP/SSE endpoint. It has a loopback default, reads the
console token only from the environment, validates cursor/event schemas and
sequence continuity, and runs reconnect, cancellation, and 100-turn probes.
Diagnostic `--skip-*` runs do not close release rows. The 2026-09-03 clean
smoke passed 1/1 turn; the same provider's 100-turn soak reached 23/100 and
failed on an empty Ollama final answer, so the soak remains open.

The Vision backend now also has a sequential `VisionPlanExecutor` seam. It
rechecks the signed observation token and frame digest for each action, routes
the action through HostOS policy, and requires a verified adapter result or
explicit verifier before continuing. In JAWL control mode, declared pointer
operations (`move`, `click`, `double_click`, `right_click`, `middle_click`),
keyboard operations and UIA actions cross the explicit route through native
`HostOSDesktop`; unknown mappings fail closed. It is deliberately not wired
to a permanent VLM yet.

## Supervised recovery implementation update

The instance supervisor now fails closed before an automatic restart unless
the per-instance native lease is valid, unexpired, ROOT-level and bounded, and
the current instance HostOS configuration is enabled at level 3. Manual starts
remain explicit operator actions. Native runtime startup also invalidates
unfinished coding approvals from an older session, including requests already
marked approved but not yet consumed. The live target-machine evidence row is
still open; the automated policy and lifecycle tests are green. Lifecycle
completion events preserve the bounded per-action success/failure state, but
the current EventBus integration emits the summary after the action batch;
real pre-dispatch timing remains a live contract item.

## Native JAWL + Big Pickle acceptance addendum — 2026-09-03

The earlier Ollama result is superseded for the native gateway transport
profile. A fresh disposable JAWL instance reached the provider through the
loopback OpenCode compatibility relay and passed the full live profile:

- 100/100 correlated normal turns;
- reconnect/resume and exact cancellation;
- typed final envelopes and cursor continuity;
- native `HostTerminalMessages.send_message_to_terminal` requested/started/
  completed lifecycle;
- 103 complete lifecycle groups in the bounded journal, one cancellation,
  five replay duplicate frames suppressed by event sequence, and zero cursor
  sequence gaps.

Evidence: `runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`.
The profile harness now accounts for JAWL's observed final-before-tool-event
ordering by draining a bounded post-final window and requires the lifecycle
by default. This is valid transport/provider evidence for the disposable
profile, not a production-ready claim: the temporary relay is not a second
brain, direct Zen provider access is not accepted yet, and HostOS level 0-3,
full native namespace/Debug Broker parity, real voice devices, Live2D/OBS and
target-machine packaging remain separate gates.

## Native namespace representative evidence - 2026-09-04

A fresh isolated JAWL console using the complete existing `jawl-4` environment
loaded HostOS, Host Terminal, and Debug Broker natively. The bounded catalog
contained 93 entries (`HostOS 84`, `HostTerminal 2`, `DebugBroker 7`). At
disposable access level 1, 79, 2, and 4 entries were available respectively.

The dependency-free `scripts/run_native_namespace_profile.py` then passed eight
read-only representative calls through the native web routes: file read,
directory listing, file search, port check, monitoring state, terminal history,
provider listing, and debug session snapshot. Every call returned HTTP 200 with
`native=true` and `is_success=true`. Evidence:
`runtime/native-jawl-namespace-parity-20260904.json`.

This closes only representative catalog and route reachability. It does not
claim live execution of every mutating HostOS skill, every 0-3 access level,
approval/recovery/idempotency/cancellation behavior, or target-machine release
readiness. The profile intentionally performs no writes, process starts, or
debug session starts.

## Native catalog policy matrix - 2026-09-04

The disposable JAWL native catalog was checked at all access levels with a
restart between levels and restoration of the initial level. The 93 registered
entries remained stable. Availability matched each declared minimum level:
HostOS was 63/84, 79/84, 82/84, and 84/84 at levels 0, 1, 2, and 3;
HostTerminal was 2/2 at every level; Debug Broker was 0/7, 4/7, 7/7, and 7/7.
Evidence: `runtime/native-jawl-catalog-matrix-20260904.json`.

This is stronger policy/catalog evidence than a single-level snapshot, but it
still does not prove that every mutating skill, approval, recovery, or provider
operation executes successfully at its allowed level.

## Target-machine release smoke - 2026-09-04

`scripts/run_target_release_profile.py` now provides a loopback-only target
smoke that attaches to existing services without starting or stopping them. A
real Companion launch passed the control/presentation separation, control
health/doctor/resources, HTML markers, bounded presentation state and avatar
HTML checks. External JAWL, ASR/TTS and Live2D checks are opt-in required flags;
the default degraded run is not production acceptance.

## Native action representative evidence - 2026-09-04

The disposable action profile exercised a genuine native HostOS mutation
sequence: child-directory creation, file write, file metadata, child-directory
monitoring, bounded monitoring read, untracking, file deletion and directory
deletion. Every action request was HTTP 200 with `native=true` and
`is_success=true`, and both disposable paths were absent after cleanup.
Evidence: `runtime/native-jawl-action-parity-20260904.json`.

The JAWL root sandbox was not untracked because the native policy correctly
forbids disabling its protected monitoring. This closes only a sandbox action
slice; coding/deploy/desktop/process mutations, approvals, recovery and
provider operations still need dedicated live matrices.
