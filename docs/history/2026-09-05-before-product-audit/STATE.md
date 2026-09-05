> Исторический снимок до аудита 2026-09-05. Утверждения и команды не являются актуальными инструкциями. Содержит в том числе неподтверждённые pass/RC claims. Текущие решения — docs/PRODUCT.md, TODO.md, docs/STATE.md.

# Состояние разработки

Актуально на 2026-09-05. Рабочие изменения намеренно не коммитились: в
checkout присутствуют изменения пользователя и агента. Ничего не
reset/checkout/delete не выполнялось. Полный список ближайших действий — в
`TODO.md`, архитектурная критика — в `docs/TECHNICAL_AUDIT.md`.

## Текущий статус

Статус: **release candidate in validation**, не production-ready.

Рабочая схема уже разделяет JAWL и Companion по ответственности:

- JAWL — единственный cognitive runtime, native tools, HostOS policy,
  Heartbeat, persona и durable structured memory.
- Companion — loopback transport/UI, voice/audio sensors, TTS/ASR provider
  adapters, transient ambient buffer, optional Vision capture и 2D/OBS
  presentation.
- Presentation server отделён от control server и получает только ephemeral
  avatar state. Control token не передаётся в avatar/OBS origin.

## Последний implementation slice

1. Добавлен JAWL native correlated Companion Gateway с typed lifecycle events,
   strict `ResponseEnvelope` v1, exact `turn_id` cancellation и legacy
   compatibility path.
2. Native terminal transport получил bounded persistent gateway-event journal,
   cursor handshake/replay после reconnect и явный `gap` при слишком старом
   cursor или повреждённом journal; legacy CLI handshake не изменён, а
   Gateway-клиент не выдаёт ложное присутствие оператора.
3. Добавлен JAWL native policy/control API: `hostos.policy.get`, expiring ROOT
   autonomy lease, emergency stop/reset, native `hostos.skill` и memory proxy.
   Native emergency stop останавливает managed sessions и tracked execution
   subprocess trees.
4. Debug Broker оставлен динамическим native registry; catalog содержит 35
   операций с risk/minimum-level metadata. Companion не содержит их копий.
5. Native/fallback filesystem writes атомарны, default delete recoverable через
   quarantine; fallback mutations имеют bounded idempotency/conflict guard.
6. Microphone capture работает через AudioWorklet, с noise gate hysteresis,
   pre-roll, calibration, RMS/peak meters, bounded queue и tail flush.
7. Self-TTS playback span подавляется в ambient loopback; TTS имеет sentence
   streaming, provider cancellation boundary, emotion rate mapping и
   ResourceGovernor (`low/standard/high`, gaming backoff).
8. JAWL получил append-only `structured_memories` с revisions/supersedes,
   provenance/source/confidence, UTC valid-time interval and retention tier;
   correction, forget/archive and bounded context remain canonical.
9. Screen observation выдаёт transient bounded JPEG, digest и signed short-lived
   token, связанный с HWND/class/bounds/frame. Добавлен строгий
   `VisionActionPlan` v1 с finite coordinate bounds и deterministic idempotency
   keys; последовательный executor rechecks fresh tokens and verified
   postconditions; the explicit confirmed route can use a thin native
   JAWL HostOSDesktop adapter, while VLM selection remains pending.
10. Presence-настройки DND, quiet hours, salience, cooldown и hourly budget
    сохраняются атомарно в `runtime/presence.json` в production launcher.
11. Добавлена pinned dev environment/build backend, wheel build и release
    documentation; gate предпочитает local
   `.venv`.
12. Presentation config exposes bounded static avatar capabilities and the
   browser reports runtime method availability; sensitive ambient source
   applications are suppressed before triage.
13. Native JAWL now exposes a bounded read-only action-journal projection;
    Companion renders recent autonomous plan states, outcomes and unresolved
    actions without receiving original parameters or execution authority.
14. Vision plan execution now binds the plan digest to the signed observation
    token and can forward supported actions to native JAWL HostOSDesktop skills
    through an explicit session/CSRF-confirmed route.
15. Native JAWL desktop access annotations now match the shared 0–3 contract:
    observation is `OBSERVER`, interactive/system GUI actions are `OPERATOR`,
    and only level 3 provides the full configured capability set.
16. Native Vision pointer parity now covers `move`, `click`, `double_click`,
    `right_click` and `middle_click`; each operation maps to a registered
    `HostOSDesktop` skill and is covered by backend/translation tests.
17. Canonical daily journal support now reuses JAWL `structured_memories`:
    consolidation can revise `journal:YYYY-MM-DD` idempotently, while
    commitments remain native TaskTable records referenced by bounded IDs.
18. Native forgetting now exposes bounded `archive_expired_memories`; expired
    structured revisions are appended as `archived` without erasing history.
19. Screen capture now supports optional transient OCR grounding and opaque
    pixel redaction before JPEG/VLM upload. Explicit rectangles are configured
    with `--screen-redact-rect`; no OCR dependency is mandatory.
20. A dependency-free restart/soak harness now checks Companion startup,
    health/resources/vision probes, graceful shutdown and release of both
    loopback ports. Local three-cycle validation passed with zero leaks.
21. Native JAWL now exposes a bounded `skills.catalog` projection for the
    HostOS, HostTerminal and Debug Broker namespaces. Companion can discover
    the live registry and minimum levels without maintaining a second copy or
    receiving an execution authority.
22. Disposable live JAWL acceptance now covers the current 114-skill catalog,
    all four access levels, representative native mutations, emergency-stop and
    ROOT autonomy issue/revoke. The policy profile restores the initial level
    and temporary safety state during cleanup, including early failures.

## Native JAWL live status — 2026-09-03

- The clean JAWL + local Ollama smoke passed **1/1** native turn with
  reconnect/resume, exact cancellation, typed tool lifecycle, final envelope,
  cursor continuity and no duplicate events. This is recorded in
  `runtime/native-gateway-live-fixed-2026-09-03.json`.
- The required 100-turn soak is deliberately still open: it reached **23/100**
  and stopped on a 180-second turn timeout after the configured Ollama model
  produced an empty final answer despite JAWL's bounded retry. The model is
  therefore unsuitable as a release-soak provider until replaced or repaired.
- The isolated retry reached the real JAWL provider and executed the native
  terminal skill; the previous corrupted ONNX embedding-cache blocker is
  resolved in the disposable runtime at
  `G:\AI\JAWL-Coding\runtime\ollama-smoke-retry`.
- Upstream hardening covered the lost `terminate_loop` metadata, false
  `action_1` lifecycle failures, cancelled-wake replay and five-second SSE
  keepalives. The latest reproducible focused native bridge/control run passes
  **73 tests**; optional live-target checks remain outside that run.
- Authenticated Companion → JAWL control was verified live with status online,
  native policy authority `jawl` at level 3, and successful native HostOS plus
  Debug Broker calls. Read-only parity is partial; mutating/approval/session
  actions and level 0–3 matrix evidence remain open.

## Проверки текущего среза

Последние результаты:

- Companion full gate: **252 non-E2E tests + 14 HTTP E2E passed**; the official
  `run_full_gate.ps1` completed compile, both discovery lanes, synthetic mic,
  Node and diff checks.
- Companion synthetic microphone gate and Node check: **pass**.
- JAWL broad full gate: **1679 passed, 13 skipped**. The skips are optional
  live provider/browser/debug dependencies and the import-only Kuzu stub;
  graph tests now skip honestly and native graph writes fail closed.
- Companion wheel build and SHA-256 manifest verification: **pass**;
  current wheel hash is `2140c4f6b74f0a4ff3800921ab5eaae2450d813ef5d60c0ebb2242f24f793bda`.
- The freshly rebuilt wheel was force-reinstalled into an isolated temporary
  Python 3.14 environment. Package import, installed `frontend/index.html` and
  `jawl-voicecompanion --help` all passed. This is clean-install/CLI evidence,
  not provider, JAWL, model, microphone or OBS acceptance.
- `git diff --check` и Python `compileall`: **pass**. The Qwen worker also
  passes the repository Python syntax gate.
- Extended Companion restart/soak: **5/5 cycles**, **30 health samples**,
  **0 forced stops** and **0 port leaks**; every temporary control and
  presentation listener was released.
- Direct disposable JAWL native namespace profile: **114** skills discovered
  (`HostOS 105`, `HostTerminal 2`, `DebugBroker 7`), eight representative
  native read-only probes passed, and the 0–3 catalog availability matrix
  matched each declared minimum level. Evidence:
  `runtime/native-jawl-namespace-parity-20260905.json` and
  `runtime/native-jawl-catalog-matrix-20260905.json`.
- Direct disposable JAWL policy profile: levels **0..3**, representative
  native write/delete/metadata/monitoring actions, fail-closed emergency-stop
  and bounded ROOT autonomy issue/revoke passed. The profile restored its
  initial access level. Evidence:
  `runtime/native-jawl-policy-20260905-fixed.json`.
- Guarded target smoke with a disposable native JAWL launch passed Companion
  control/presentation checks plus JAWL `running=true`, native policy authority
  `jawl` and access level `1`. The provider was isolated behind a loopback sink
  and placeholder key; descendant cleanup released `8773`. Evidence:
  `runtime/target-release-profile-20260905-jawl.json`.

Проверки выше доказывают контракты и mock/fake provider paths. Они не доказывают
качество живого микрофона, TTS, JAWL модели, VLM, WASAPI, Live2D, OBS или
внешних Windows permissions.

## Что ещё блокирует релиз

- live JAWL Gateway: 100 turns, reconnect/resume, model actions and cancel;
- native parity всех JAWL HostOS/Terminal/Debug/MCP/browser/desktop skills;
  текущая live-проверка закрывает каталог, policy и representative slice, но
  не все mutation/approval/cancellation/recovery paths;
- supervised restart только при действующем autonomy lease;
- real microphone/WASAPI/VoiceMem acoustic path, Qwen ASR device path,
  TeraTTS echo, barge-in и end-to-end latency;
- live ambient promotion с consent в JAWL memory и retention evidence;
- native Vision plan execution с fresh token и verified postcondition;
- user-owned/licensed Live2D bundle, transparency/OBS/desktop-pet soak;
- target-machine packaging install/upgrade/rollback and long-running restart/soak.

Vision модель намеренно не фиксируется до завершения пользовательского
CPU/RAM real-time теста. TeraTTSv2 — текущий быстрый русский CPU TTS, а
Qwen3-TTS Base — отдельный медленный voice-clone профиль; OmniVoice ждёт
подтверждённого API/model path.

## Правило следующей итерации

Не добавлять новые крупные функции до закрытия live native gateway и native
policy parity. Любой новый side effect должен иметь один JAWL owner, typed
JSON contract, bounded input/result, audit metadata, cancellation и test
matrix. Для major update обязательно запускать `scripts/run_full_gate.ps1`,
а live claim помечать отдельным evidence.
## Native Gateway profile tooling

Added `scripts/run_native_gateway_profile.ps1` and a dependency-free Python
harness for the real JAWL Gateway. It checks cursor/resume, reconnect, exact
cancellation, strict typed events, final envelopes, duplicate/sequence gaps,
and 100 turns. It requires `--allow-live-turns`; the 2026-09-03 clean smoke
passed 1/1 turn, while the same provider's 100-turn soak reached 23/100 and
failed on an empty Ollama final answer. The soak therefore remains open.

## Supervised recovery and approval boundary

The native JAWL instance supervisor now fails closed for automatic crash
recovery unless the specific instance has an active, bounded ROOT autonomy
lease and its current HostOS configuration is enabled at level 3. Explicit
operator start is still allowed without that lease. The native coding approval
store invalidates unfinished `pending` and `approved` requests when the JAWL
runtime starts; the local approval CLI only reviews or decides records and does
not perform this startup invalidation.

Native Gateway lifecycle summaries now carry the actual bounded per-action
success/failure state without arguments or result payloads. They are emitted
after the action batch through the existing EventBus boundary; live
pre-dispatch timing remains a separate acceptance item.

Automated unit/integration evidence is present. Target-machine live restart,
lease-expiry and approval-restart evidence remains a release-owner task.

## Последняя локальная итерация — 2026-09-03

- `scripts/run_browser_render_smoke.ps1` прошёл на Microsoft Edge: headless
  браузер реально отрендерил control DOM и изолированную avatar/OBS surface,
  включая gate/health/OBS markers; временный browser profile и Companion
  процесс удалены.
- Корректный restart/soak wrapper запускался с Python-style аргументами:
  **3/3** cycles, **15** health samples, **0** forced stops, **0** port leaks.
- Default-port smoke подтвердил HTTP 200 на control `2367` и presentation
  `8766`; отдельный preflight корректно отказал при намеренном конфликте
  presentation с FoxMCP на `8765`, не запуская Python.
- Отдельный equal-port probe также отказал до запуска и оставил `2367` без
  частичного listener.
- Полный gate после изменений: **226 non-E2E + 14 HTTP E2E**, synthetic mic,
  Node и `git diff --check` — зелёные. Две сборки wheel снова дали один
  SHA-256 `8c5ac5e7...182e338`.
- Native JAWL+Ollama clean retry устранил прежний corrupt ONNX cache, достиг
  provider и выполнил native terminal skill. Последующий clean 1-turn profile
  принят; 100-turn profile отклонён на пустом final ответе модели.
- Companion default ports were moved away from FoxMCP: control `2367`,
  presentation/OBS `8766`, JAWL console profile `8770`. A live default-port
  smoke returned HTTP 200 for control and avatar, then released both ports
  after graceful stop.
- A real Qwen3-ASR `llama-server` smoke through the moved benchmark files also
  passed via `OpenAICompatibleASRClient`: Russian TeraTTSv2 `welcome.wav` took
  **0.431 s** and `poem.wav` **1.473 s**, with Russian text returned for both.
  The temporary server was stopped and port `8984` released. This is a final
  HTTP utterance result, not microphone/WASAPI, echo/barge-in or partial-ASR
  evidence.
- The attempted disposable native policy probe was not accepted: JAWL could
  not start because `OSError: [Errno 28] No space left on device` occurred
  while writing the PID on `G:` (only 8 KiB was free). The probe process was
  stopped and `8773` released; no FoxMCP process or `8765` listener was
  changed. The level 0–3 live matrix therefore remains open and needs a
  runtime volume with at least 2 GiB free before retry.
- The retry ran on a disposable C: runtime through
  scripts/run_native_policy_profile.py: levels 0–3 passed the safe native
  filesystem matrix, emergency stop blocked a native read until explicit
  reset, and the bounded ROOT lease issued and revoked cleanly. Report:
  runtime/native-policy-live-2026-09-03.json. Full namespace, Debug Broker,
  approval and supervised-recovery parity remain release work.

## Предыдущая локальная итерация — 2026-09-02

- Для выбранного TeraTTSv2 добавлен явный `TeraTTSHttpClient`; совместимый
  `CozyVoiceHttpClient` сохранён для старых локальных workers.
- После изменения повторно пройдены TTS-тесты **7/7**, полный gate **213
  non-E2E + 14 HTTP E2E**, restart/soak **3/3 цикла**, hash/ZIP wheel и
  `compileall`.
- Live acceptance не подменяется этими проверками: внешний JAWL/model,
  микрофон/WASAPI, Tera runtime, OBS/Live2D, VLM и Windows permissions всё ещё
  требуют target-machine evidence.
- Две последовательные сборки wheel через `build_release.ps1` дали один и тот
  же SHA-256 `9794350a...f003c8bc`; `SOURCE_DATE_EPOCH` теперь фиксирует ZIP
  metadata и устраняет ложную воспроизводимость от файловых timestamps.
- Текущий wheel установлен в чистое изолированное venv из `dist/wheel`, а
  entry point `jawl-voicecompanion --help` показал новые VoiceMem flags.
- Локальный Ollama `gemma-4-12b-coder-fable5-composer2.5-v1:latest` доступен
  через Companion OpenAI-compatible adapter: health `online`, один непустой
  ответ за **1.085 s**. Это ещё не live JAWL Gateway evidence.
- Изолированный запуск JAWL с тем же Ollama не дошёл до provider: Vector DB
  обнаружил повреждённый ONNX embedding cache (`model_optimized.onnx`) и
  перешёл в re-download. Чистый retry data-dir убрал corruption, но загрузка
  embedding не завершилась в bounded test window. Профили остановлены без
  принятия результата; cache/download setup остаётся upstream blocker.
- `scripts/run_browser_render_smoke.ps1` прошёл на Edge: control DOM и
  изолированная avatar/OBS DOM проверены headless-браузером, временный профиль
  и Companion-процесс корректно завершены. OBS/Live2D физическая приёмка не
  подменяется этим smoke.

## Live smoke — 2026-09-02

- Реальный локальный TeraTTSv2 worker был поднят из `G:\AI\tts_models\TeraSpace__TeraTTSv2`.
  `/health` вернул `ok`; пять запросов через `TeraTTSHttpClient` дали first
  complete WAV p50 **1.223 s**, p95 **1.313 s**, median RTF **0.344**.
  Отдельный concurrent cancellation через `TTSService` вернул `TTSCancelled`
  за **1.164 s**. Worker использует whole-WAV генерацию, поэтому это не
  доказательство provider-native остановки inference.
- JAWL был штатно запущен на loopback с текущим QWB-профилем. Инициализация
  прошла с HostOS level 3 и Debug Broker **7/7**, но native Gateway profile
  остановился на reconnect probe: QWB upstream вернул HTTP 503
  `upstream_waf_challenge`. 100-turn/reconnect/cancel acceptance не закрыта;
  ключи в вывод не попадали, агент после smoke остановлен штатно.
- `run_native_gateway_profile.py` теперь различает timeout чтения уже
  установленного SSE от ошибки соединения; добавлен regression test.

## VoiceMem sidecar smoke — 2026-09-02

- Реальный VoiceMem sidecar из `G:\AI\VoiceMem\.venv` с флагом
  `--local-memory` обработал текстовый final path через `feed_partial` и
  вернул коррелированные `USER_PARTIAL` + `VOICE_TURN` за **7.405 s** на
  холодном локальном E5 пути. Диагностический stdout VoiceMem не повредил
  JSON-lines канал.
- Для `end_audio` sidecar теперь подаёт ограниченные 32 ms silence frames до
  0.8 s и останавливается после подтверждения turn; поведение покрыто тестом.
- Добавлен явный `warmup text|audio` lifecycle request и CLI-флаг
  `--voicemem-warmup`. Реальный text/audio prewarm в VoiceMem sidecar вернул
  `VOICE_READY`; audio prewarm занял **9.578 s**, а health теперь отражает
  загрузку audio path.
- Это не закрывает русский streaming audio acceptance: bundled VoiceMem sherpa
  профиль не является проверенным русским acoustic ASR. Русский production
  путь остаётся `Qwen3-ASR final utterance -> VoiceMem feed_partial(ended=True)`
  либо другой отдельно подтверждённый streaming provider.

## VoiceMem live profile — 2026-09-02

- `scripts/run_voicemem_profile.ps1` прошёл на реальном
  `G:\AI\VoiceMem\assets\speech.wav` с `--warmup audio --local-memory`:
  272 chunks, 3 `USER_PARTIAL`, 1 `VOICE_TURN`, first turn **14.317 s**,
  audio prewarm **8.618 s**, health `ready`, `audio_models_loaded=true`.
- Отчёт: `runtime/voicemem-profile-2026-09-02.json`. Тестовый WAV имеет
  bundled VoiceMem zh-en профиль; это подтверждение process/VAD lifecycle, но
  не доказательство качества русского microphone ASR.

## Current provider smoke — 2026-09-03

- This section records the earlier adapter-only smoke. The superseding native
  JAWL + Big Pickle acceptance result is documented below.
- OpenCode CLI successfully listed and called `opencode/big-pickle`. The
  Companion OpenAI-compatible adapter also passed health, bounded completion
  and SSE streaming when supplied the explicit CLI-compatible
  `OpenCode/1.18.11` User-Agent; no credential was written to the repository
  or report.
- This is temporary provider evidence only. The model is not yet accepted as
  the native JAWL provider and has not passed JAWL's tool, reconnect or
  100-correlated-turn profile.
- Companion full gate after the adapter change: **227 non-E2E tests + 14 HTTP
  E2E**, compile, synthetic mic, Node and `git diff --check` all passed.
- Disposable live Companion instances also passed browser-session `/api/chat`
  and `/api/chat/stream` with `big-pickle`: complete envelope, one streaming
  delta and exactly one final envelope; ports `2391/8791` and `2392/8792` were
  released after shutdown.

Temporary invocation is documented in `TODO.md`: the API key stays in an
environment variable and `--llm-user-agent OpenCode/1.18.11` reproduces the
routing used by the installed OpenCode CLI. This is a provider transport
smoke, not a native JAWL provider or release-soak acceptance.

## Superseding native JAWL + Big Pickle acceptance — 2026-09-03

- A disposable isolated JAWL instance was started on `127.0.0.1:8773` with
  `big-pickle` as its main model. The provider path was exercised through the
  loopback-only `scripts/opencode_header_relay.py`, which adds the explicit
  `OpenCode/1.18.11` User-Agent required by the current OpenCode Zen route.
- `scripts/run_native_gateway_profile.ps1` passed the complete live profile:
  **100/100 correlated normal turns**, reconnect/resume, exact cancellation,
  `assistant.final` envelopes, and cursor continuity.
- The native JAWL `HostTerminalMessages.send_message_to_terminal` lifecycle
  was observed as `tool.requested` -> `tool.started` -> `tool.completed`.
  The bounded journal contained **103 complete lifecycle groups**, one
  cancellation, **5 replay duplicate frames** suppressed by event sequence,
  and **no sequence gaps**. JAWL can emit `assistant.final` before the tool
  lifecycle broadcast, so the profile drains the bounded post-final window.
- Report: `runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`.
  This closes native gateway/provider startup evidence for the disposable
  profile. It is not direct-provider acceptance, because the compatibility
  relay is temporary, and it does not close the HostOS level 0-3 matrix,
  full native namespace/Debug Broker parity, real microphone/WASAPI, or
  production provider selection.
- The Companion profile harness now imports the project source for direct
  invocation and requires a complete tool lifecycle by default. Use
  `--allow-missing-tool-lifecycle` only for diagnostics.

## Superseding native namespace evidence - 2026-09-04

- A direct isolated JAWL console with the complete `jawl-4` environment loaded
  the native HostOS, Host Terminal, and Debug Broker interfaces successfully.
- The live bounded catalog contained **93** entries: `HostOS 84`,
  `HostTerminal 2`, and `DebugBroker 7`. At disposable access level 1,
  `79/84`, `2/2`, and `4/7` entries were available respectively.
- Eight representative read-only calls passed through the native JAWL routes:
  file read, directory listing, file search, port check, monitoring state,
  terminal history, provider listing, and debug session snapshot. Each returned
  HTTP 200 with `native=true` and `is_success=true`.
- Evidence: `runtime/native-jawl-namespace-parity-20260904.json`.
  This proves catalog/route reachability, not all 93 skill implementations;
  mutating namespaces, level 0-3 policy, approval/recovery, and target-machine
  packaging still require their own disposable live matrices.

## Native catalog access matrix - 2026-09-04

The disposable JAWL instance was restarted through native policy control at
levels 0, 1, 2, and 3. All four catalogs contained the same 93 entries and
every `available` flag matched the entry's `required_access_level`: HostOS
availability was 63, 79, 82, and 84 of 84; HostTerminal stayed 2 of 2; Debug
Broker was 0, 4, 7, and 7 of 7. The profile restored its initial disposable
level 0. Evidence: `runtime/native-jawl-catalog-matrix-20260904.json`.
This validates policy projection only; it does not execute mutating skills.

## Target-machine release smoke - 2026-09-04

The new dependency-free target profile passed against a real Companion launch
on control `2367` and presentation `8766`: health/doctor/resources, control
HTML, read-only presentation state and avatar HTML all responded correctly.
The run used default degraded mode, so it intentionally did not claim JAWL,
ASR/TTS or Live2D readiness. `--require-jawl-url`, repeated
`--require-dependency` and `--require-live2d` turn those into hard acceptance
requirements. Evidence: `runtime/target-release-profile-20260904.json`.

## Native action representative evidence - 2026-09-04

The disposable native action profile passed a real HostOS mutation slice:
JAWL created a sandbox child directory, wrote a marker, set file metadata,
tracked/read/untracked the child directory, then deleted the marker and child
directory through native JAWL. All action calls returned HTTP 200 with
`native=true` and `is_success=true`; marker and directory cleanup were
confirmed absent. Evidence: `runtime/native-jawl-action-parity-20260904.json`.
The protected root sandbox was not untracked. This is representative action
evidence, not full coding/deploy/desktop/process or approval parity.

## Current TeraTTSv2 worker result - 2026-09-04

The guarded profile ran five Russian requests against the local TeraTTSv2 CPU
worker. Every response was a valid mono PCM16 WAV; complete-response latency
was p50 **0.429 s**, p95 **0.487 s**, with median RTF **0.149**. Evidence:
`runtime/teratts-live-profile-20260904.json`. This does not prove provider-
native streaming, real microphone latency, echo cancellation or barge-in.

## Current VoiceMem sidecar result - 2026-09-04

The guarded real-process profile passed on `G:\AI\VoiceMem\assets\speech.wav`
with audio warmup and local-memory mode: 272 PCM chunks, 3 bounded partials,
1 final `VOICE_TURN`, audio warmup **22.326 s**, and first turn **28.280 s**.
Health ended `ready` with `audio_models_loaded=true`. Evidence:
`runtime/voicemem-live-profile-20260904.json`. This proves the sidecar/VAD
lifecycle on the bundled fixture, not Russian acoustic accuracy or real
microphone/WASAPI acceptance.

## Current Qwen3-ASR final-utterance result - 2026-09-04

The guarded profile passed against the moved CPU `llama-server` and
Qwen3-ASR-0.6B GGUF/mmproj: `welcome.wav` and `poem.wav` returned non-empty
Russian transcripts with median RTF **0.077**. Evidence:
`runtime/asr-live-profile-20260904.json`. This validates the final-utterance
multipart path only; streaming partial ASR, microphone capture,
echo-cancellation and barge-in remain open.

## Current Qwen3-TTS and integrated audio result - 2026-09-04

The local `Qwen3-TTS-12Hz-0.6B-Base` release is present under
`G:\AI\tts_models\Qwen__Qwen3-TTS-12Hz-0.6B-Base`, with `qwen_tts` installed
in `G:\AI\tts_env`. The new loopback worker uses a fixed Mita reference audio
and transcript, so callers cannot select arbitrary local files. A direct CPU
request returned valid 24 kHz mono PCM16 WAV in **19.276 s** for 3.92 s of
audio. The Base clone path is therefore a quality/voice-identity option, not a
real-time CPU option; TeraTTSv2 remains the low-latency fallback. The worker
explicitly reports `voice_clone=true` and `emotion_control=false`.

The integrated external-ASR run now adapts authoritative final ASR text into a
transport-only `VOICE_TURN` for JAWL and enqueues identical VoiceMem enrichment
on a bounded serialized worker. The live Tera profile passed with
`end_seconds=0.409`, queue status `queued`, one response and valid WAV; the
Qwen worker profile passed with `end_seconds=0.391` and a valid 24 kHz WAV.
The previous 65.7 s VoiceMem wait is no longer on the user-response path.
Queue depth, completed/failed/dropped counts are visible in
`/api/voice/status`; shutdown interrupts a slow sidecar worker.

## Current control-plane UI - 2026-09-04

The browser control plane was rebuilt as a mint Windows-Aero cockpit. The
overview combines the dialogue with an inline fallback 2D companion preview;
voice, perception, memory, access and diagnostics are separate focused tabs.
Existing control element IDs and API actions were retained, while the
separate presentation origin remains the unprivileged OBS mirror. Headless
Edge rendering passed the control/avatar DOM smoke after the redesign.

## Latest operational validation - 2026-09-05

The extended restart/soak profile passed **5/5** temporary process cycles with
**30** health samples, no forced stops and no leaked control/presentation
listeners. The local demo remains available on control `2367` and presentation
`8766`; FoxMCP continues to own `8765`.

The attached target-machine release smoke also passed against those live
surfaces: control health/doctor/resources and HTML, plus presentation state
and avatar HTML isolation. Optional JAWL/provider/Live2D requirements were
not asserted in this degraded smoke and remain release-owner gates.

A guarded Qwen3-ASR probe was also run against the existing
`G:\AI\VLM-RealTime-Bench\assets\nyan_audio_30s.wav` with an explicit Russian
non-speech description prompt. The endpoint returned empty text, so Qwen3-ASR
remains final speech ASR only; no audio-captioning fallback was inferred from
the failed probe.
