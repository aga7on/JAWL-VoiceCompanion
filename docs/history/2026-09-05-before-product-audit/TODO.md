> Исторический снимок до аудита 2026-09-05. Утверждения и команды не являются актуальными инструкциями. Содержит в том числе неподтверждённые pass/RC claims. Текущие решения — docs/PRODUCT.md, TODO.md, docs/STATE.md.

# TODO — JAWL VoiceCompanion

`[x]` verified in automated tests, `[~]` implemented but needs live or
integration evidence, `[ ]` pending, `[!]` external decision/action.
Порядок ниже важнее старых фаз: сначала release blockers, затем расширение
функций.

## Release blockers

### Superseding live result — 2026-09-03

The native JAWL + Big Pickle acceptance profile is now passed in an isolated
disposable JAWL instance through the loopback OpenCode compatibility relay:
100/100 correlated normal turns, reconnect/resume, exact cancellation, final
envelopes, cursor continuity, and complete native HostTerminal tool lifecycle.
The redacted report is
`runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`.

The profile observed 103 complete tool lifecycle groups in the bounded event
journal, one cancellation, five replay duplicate frames (suppressed by event
sequence), and no sequence gaps. This closes the native gateway/provider
startup blocker for this disposable Big Pickle profile. It does not yet close
full HostOS level 0-3 namespace parity, Debug Broker/MCP/browser parity, real
microphone acceptance, Live2D/OBS acceptance, or production provider choice.
The relay is a temporary test harness and is not a second model or production
gateway.

### Superseding native namespace result - 2026-09-05

The direct JAWL native console was also validated in an isolated instance with
HostOS and Debug Broker enabled. The current live catalog returned **114**
entries: `HostOS 105`, `HostTerminal 2`, and `DebugBroker 7`. Eight
representative read-only probes passed through the native JAWL routes with HTTP
200,
`native=true`, and `is_success=true` (file read, directory/search, network,
monitoring, terminal history, provider listing, and debug session snapshot).
Evidence: `runtime/native-jawl-namespace-parity-20260905.json`.

This is representative namespace evidence, not proof that every mutating skill
or every access level has been exercised. The level 0-3 policy matrix,
mutating/approval/recovery/idempotency/cancellation checks, and target-machine
release profile remain separate acceptance gates.

- [!] Отозвать опубликованный в чате TokenRouter key и выпустить новый.
  В tracked-файлах ключ не найден; агент не имеет права отзывать его за
  владельца.
- [~] Прогнать native JAWL Companion Gateway: 100 correlated turns,
  reconnect/resume, typed tool lifecycle, cancellation и final envelope.
  Изолированный Big Pickle/OpenCode relay profile уже прошёл 100/100; прямой
  постоянный provider path и acceptance на выбранном production provider ещё
  открыты. Ollama profile ранее остановился на пустом final answer.
- [~] Проверить локальный provider startup внутри JAWL, а не только через
  Companion adapter. Изолированный JAWL retry достиг provider и выполнил
  native terminal skill; валидный FastEmbed ONNX-кэш восстановлен в
  disposable runtime. Требуется повторить 100-turn profile на стабильной
  модели/provider.
- [~] Проверить, что все model-originated side effects идут через JAWL:
  HostOS/Terminal native skill proxy, Debug Broker, MCP, browser, desktop,
  approvals, audit, idempotency, cancellation и emergency stop. В bridge
  режиме Companion не исполняет `/api/hostos/execute` локально; live parity
  каждого native namespace ещё требуется.
- Emergency-stop bridge semantics are now fail-closed and covered by an HTTP
  regression: native outage returns `ok:false`/503 and leaves the local latch
  active; native reset ordering is agent-start then latch-clear.
- [~] Довести supervised recovery: перезапуск JAWL/worker разрешён только при
  действующем expiring ROOT lease; pending one-shot approvals не переживают
  restart.
- [~] Выполнить live voice/TTS matrix: dynamic microphone gate, Qwen3-ASR,
  VoiceMem, TeraTTSv2, self-TTS suppression, barge-in, first-audio p50/p95.
  Для TeraTTSv2 уже есть локальный worker smoke: health, русский WAV,
  p50/p95 и cancellation Companion; Qwen3-ASR имеет отдельный локальный
  WAV smoke, а microphone/VoiceMem acoustic path/WASAPI, echo и barge-in
  остаются открыты.
- [~] Добавить target-machine live release profile для JAWL, providers, model
  startup, permissions, OBS и restart/soak. Mock gate не является live proof.

### Superseding native catalog access matrix - 2026-09-05

The disposable JAWL catalog was checked after native policy restart at all four
levels. Each level returned the same 114 registered entries and the availability
flags matched every skill's declared `required_access_level`: level 0 exposed
`63/105` HostOS, `2/2` HostTerminal and `0/7` Debug Broker skills; level 1
`84/105`, `2/2`, `4/7`; level 2 `103/105`, `2/2`, `7/7`; level 3 `105/105`,
`2/2`, `7/7`. The profile restored the initial disposable level (`3`).
Evidence: `runtime/native-jawl-catalog-matrix-20260905.json`.

This validates catalog policy projection, not execution of mutating skills.

### Superseding native action result - 2026-09-05

The disposable native action profile passed a real HostOS mutation slice:
JAWL created a new sandbox child directory, wrote a marker, set file metadata,
tracked/read/untracked the child directory, then deleted the marker and child
directory through native JAWL. Every action returned HTTP 200 with
`native=true` and `is_success=true`; cleanup reported marker and directory
absent. Evidence: `runtime/native-jawl-action-parity-20260905.json`.

The root sandbox was deliberately not untracked because JAWL correctly forbids
disabling monitoring of that protected root. Coding/deploy/desktop/process
mutations, approvals, recovery and provider operations remain separate live
action gates.

### Current native policy result - 2026-09-05

The corrected disposable policy profile passed the live JAWL levels `0..3`
matrix with sandbox read, framework read and disposable write expectations,
then passed fail-closed emergency-stop/reset and bounded ROOT autonomy
issue/revoke. It restored the original access level after the run even though
the profile traversed all four levels. Evidence:
`runtime/native-jawl-policy-20260905-fixed.json`.

- The freshly rebuilt wheel was force-reinstalled into an isolated temporary
  Python 3.14 environment. Package import, bundled `frontend/index.html` and
  `jawl-voicecompanion --help` all passed. This validates install layout and the
  CLI entry point only; it does not include model weights or external services.
- The guarded `scripts/run_target_jawl_smoke.ps1` also passed against the live
  Companion control/presentation surfaces and a disposable native JAWL launch:
  JAWL `running=true`, native policy `authority=jawl`, access level `1`, and
  clean descendant/port teardown. Its provider URL is a loopback sink with a
  placeholder key, so this is JAWL startup/policy evidence, not provider quality
  or external-service acceptance. Evidence:
  `runtime/target-release-profile-20260905-jawl.json`.

The profile now also restores the access level and temporary safety state in its
`finally` cleanup on early assertion failure. This hardens the test harness; it
does not expand JAWL's authority. Level 1 remains framework-root read, level 2
framework-root write subject to deploy/data/log rules, and level 3 is bounded by
the Windows account, UAC, ACLs, provider availability and explicit JAWL policy.

### Current TeraTTSv2 worker result - 2026-09-04

The guarded live profile ran five Russian requests against the local
TeraTTSv2 CPU worker. All responses were valid mono PCM16 WAV files;
complete-response latency was p50 **0.429 s**, p95 **0.487 s**, and median RTF
**0.149**. Evidence: `runtime/teratts-live-profile-20260904.json`. This is
warm whole-WAV REST evidence, not provider-native streaming first audio,
microphone latency, echo cancellation or barge-in acceptance.

### Current VoiceMem sidecar result - 2026-09-04

The guarded real-process profile passed on `G:\AI\VoiceMem\assets\speech.wav`
with audio warmup and local-memory mode: 272 PCM chunks, 3 bounded partials,
1 final `VOICE_TURN`, audio warmup **22.326 s**, and first turn **28.280 s**.
Health ended `ready` with `audio_models_loaded=true`. Evidence:
`runtime/voicemem-live-profile-20260904.json`. This validates the sidecar
protocol/VAD lifecycle on the bundled fixture; it is not Russian acoustic
accuracy or real microphone/WASAPI acceptance.

### Current Qwen3-ASR final-utterance result - 2026-09-04

The guarded profile passed against the moved CPU `llama-server` and
Qwen3-ASR-0.6B GGUF/mmproj: `welcome.wav` and `poem.wav` returned non-empty
Russian transcripts with median RTF **0.077**. Evidence:
`runtime/asr-live-profile-20260904.json`. This is the final-utterance
multipart path only; true streaming partial ASR, microphone capture,
echo-cancellation and barge-in remain open.

### Current Qwen3-TTS and integrated audio result - 2026-09-04

The local `Qwen3-TTS-12Hz-0.6B-Base` release is already present under
`G:\AI\tts_models\Qwen__Qwen3-TTS-12Hz-0.6B-Base`; its `qwen_tts` package is
installed in `G:\AI\tts_env`. A Mita ICL clone returned valid Russian WAV
audio through the new loopback worker. Direct CPU generation took **19.276 s**
for a 3.92 s utterance; the existing offline benchmark measured RTF **7.94**
for welcome and **3.93** for poem, with peak RAM **5.45 GB**. This is a
voice-clone quality path, not a real-time CPU path; TeraTTSv2 remains the
low-latency fallback. Evidence: `runtime/audio-pipeline-qwen-20260904.json`.

The external-ASR audio response path is now non-blocking for VoiceMem. The
same final text is enqueued to a bounded serialized memory worker while JAWL
receives its transport-only `VOICE_TURN` immediately. A live Tera run passed
with `end_seconds=0.409`, `memory_sync.status=queued`; the Qwen TTS integrated
run passed with `end_seconds=0.391` and a valid 24 kHz WAV. The previous
65.7-second VoiceMem wait is no longer on the response path. This does not
prove microphone acoustics, true partial streaming, echo cancellation,
barge-in or provider-native emotion control.

## Verified foundation

- [~] Temporary OpenCode Zen `deepseek-v4-flash` provider: two JAWL provider
  contract smokes passed after mapping the secret to
  `JAWL_LIVE_PROVIDER_KEY`, but later requests returned HTTP 403. It is not a
  stable release provider until health/JSON/100-turn acceptance is repeated.

- [x] Isolated repository, Git, `AGENTS.md`, architecture/decision/state docs.
- [x] 2D-only avatar scope, dependency-light browser control plane and
  separate presentation/OBS loopback server.
- [x] Versioned event/response contracts, strict Unicode/ID/bounds validation,
  hidden-thought filtering and metadata-only audit events.
- [x] TurnArbiter, correlated turn IDs, exact cancellation propagation and
  reconnect-safe typed native event parsing.
- [x] JAWL HostOS levels 0–3, versioned native policy snapshot, emergency stop,
  atomic expiring ROOT autonomy lease and native control socket proxy.
- [x] HostOS process-tree stop, atomic/recoverable file mutations and fallback
  idempotency/conflict detection.
- [x] Debug Broker dynamic catalog with 35 operations and canonical
  risk/minimum-level metadata; native provider wrappers stay in JAWL.
- [x] AudioWorklet capture, hysteresis/pre-roll/calibration gate, RMS/peak
  meters, bounded upload queue and final-tail flush (synthetic verified).
- [x] TeraTTSv2 REST worker contract, sentence streaming, emotion→rate mapping,
  resource priority and HTTP body cancellation boundary.
- [x] Lightweight resource governor (`low/standard/high`, gaming backoff),
  `/api/resources` and doctor/health exposure.
- [x] Native JAWL append-only `structured_memories` with fact/trait/
  preference/summary, provenance/source/confidence, revision/supersedes,
  remember/revise/forget/archive and bounded context projection.
- [x] Screen observation is opt-in, bounded and non-persistent; signed short
  observation token is bound to HWND/class/bounds/frame digest.
- [x] Strict `VisionActionPlan` v1 parser and normal HostOS request translation.

## Phase 1 — JAWL/text contract

- [x] Native JAWL typed Gateway endpoint and Companion adapter.
- [x] Final `ResponseEnvelope` with emotion, avatar, voice and action fields.
- [~] Live final envelope preservation from the configured JAWL model; test
  QWB-JAWL proxy and future GPT Luna/local provider without changing schema.
- [x] JSON control/event path for concurrent models and providers.
- [x] Add native event cursor/resume contract, bounded persistent replay journal
  and duplicate suppression; live exactly-once soak evidence remains a release
  validation task.

## Phase 2 — Russian voice

- [x] Bounded Qwen3-ASR final-utterance adapter and VoiceMem sidecar contract.
- [x] Browser gate with visible levels and calibration.
- [~] VoiceMem streaming partials and lazy Windows WASAPI loopback; the sidecar
  now exposes an offline `--local-memory` path, a bounded background memory
  enqueue for external final ASR, and uses a startup-safe 30 s default timeout,
  but install, permissions, real device and Russian acoustic streaming
  acceptance remain.
- [~] TeraTTSv2 remains the current low-latency CPU/Russian provider while
  Qwen3-TTS 12Hz 0.6B Base is available as the explicit voice-clone provider.
  Both use the same bounded REST contract and the CLI selects them via
  `--tts-provider`. Qwen clone CPU latency and cloned prosody/emotion limits
  are measured; provider-native cancellation and target-device latency remain
  to be measured.
- [!] OmniVoice adapter waits for a confirmed model/API location.
- [ ] Prove true streaming Qwen partial ASR before replacing final mode.
- [ ] Tune Russian prosody, echo cancellation and interruption classification.

## Phase 3 — memory and ambient perception

- [x] JAWL structured memory write/read/correction/forget/archive proxy.
- [~] Ambient audio/video observations have bounded TTL, salience, coalescing,
  source/confidence/provenance and no raw persistence by default.
  With `--asr-url/--asr-model`, the real synthetic WASAPI loopback used Qwen3-ASR:
  1350 chunks, 0 dropped, exact Russian final text, one observation and a
  delayed `promote_candidate`; no conversational `last_turn` was created.
- [~] Add non-speech audio understanding beside ASR. The bounded
  `AudioDescriptionService` contract now accepts validated text metadata for
  `music/sound/mixed/unknown` and the bridge can retain it as ambient evidence
  alongside a transcript. No audio-captioning model is installed or accepted;
  a guarded Qwen3-ASR prompt trial on `nyan_audio_30s.wav` returned empty text,
  so Qwen3-ASR is explicitly not accepted as the captioning provider.
  Benchmark a suitable local provider (Qwen2-Audio is only a candidate) before
  wiring a production launcher flag.
- [~] Implement explicit consent-aware ambient promotion to JAWL structured
  memory; automatic promotion remains disabled, raw observations stay
  transient and never become `USER_FINAL`.
- [x] Add UTC valid-time fields and retention tiers to canonical structured
  memory; old SQLite files migrate in place and expired rows leave prompt
  context while append-only history remains.
- [~] Add Vector/Graph archival recall, daily journal and
  Sleep/Reflection/Consolidation jobs. JAWL's existing hybrid RAG provides
  bounded vector/graph recall, tick thresholds dispatch the existing
  Sleep/Reflection/Consolidation patterns, and daily summaries now use the
  append-only `structured_memories` key `journal:YYYY-MM-DD`; task IDs are
  references only and task state remains in `TaskTable`. The current Python
  3.14 environment has an import-only Kuzu stub, so graph acceptance is
  explicitly skipped and the native graph skills fail closed until a real
  Kuzu runtime is installed.
- [x] Define `disable` versus `disable_and_erase`; the latter requires explicit
  confirmation and clears the transient buffer.
- [x] Add structured redaction for sensitive windows/credentials; sensitive
  source applications and credential-bearing text are dropped before triage,
  while screen capture keeps its independent deny-list.
- [x] Add browser controls for reviewing and explicitly promoting ambient
  candidates plus JAWL structured-memory remember/revise/forget/archive
  operations; native live acceptance remains required.

## Phase 4 — 2D avatar, desktop pet and OBS

- [~] Isolated transparent-capable presentation surface, reactive fallback,
  avatar audio/lip-sync signal and copyable OBS URL.
- [~] Optional Live2D asset/runtime validation and bounded desktop launcher.
- [!] Supply a licensed/user-owned Live2D bundle and verify runtime license.
- [ ] Test transparency, click-through/drag, DPI, multi-monitor, OBS capture,
  audio ownership and 8-hour presentation soak.
- [~] Add runtime capability discovery and expression fallback matrix; static
  bundle capabilities and fallback names are exposed, but runtime-specific
  rendering still needs a real asset acceptance run.
- [x] Keep presentation API free of control credentials, chat history and tool
  endpoints; automated HTTP boundary regression covers this on every gate.

## Phase 5 — Vision and desktop interaction

- [x] Focused-window capture, bounded JPEG profile and UIA semantic observation.
- [x] Calibrated pointer/keyboard fallback with stale foreground checks.
- [x] Signed fresh observation token and strict structured plan contract.
- [ ] Connect selected VLM output to `VisionActionPlan`; no VLM is selected as
  permanent dependency yet.
- [~] Execute plans one action at a time through JAWL policy and verify a fresh
  postcondition after every action; the local seam, explicit confirmed route
  and native JAWL HostOSDesktop mapping for all declared pointer primitives,
  keyboard operations and UIA actions are implemented. VLM and live Windows
  evidence remain pending.
- [x] Add canvas/OCR fallback and pixel-level redaction. `--screen-ocr` uses an
  optional transient OCR provider (or pytesseract when installed), while
  `--screen-redact-rect L,T,R,B` applies opaque redaction before JPEG/VLM
  upload; OCR coordinates remain bounded transient grounding data.
- [~] Screen change detection, cooldown, salience and `SPEAK_INTENT` IPC;
  validate final JAWL wording in live profile.

## Phase 6 — presence and autonomy

- [x] TurnArbiter, salience/coalescing, proactivity budget, DND/quiet-hours
  controls and bounded attention state.
- [~] User idle/focus adapter and proactive suppression; fatigue classification
  and richer focus signals remain.
- [x] Resource governor gaming mode/backoff in Companion.
- [x] Add durable presence preferences for DND, quiet hours, salience, cooldown
  and proactive budget; supervised lease recovery is implemented and awaits
  target-machine live evidence.
- [~] Expose JAWL's bounded action-journal projection for inspectable
  autonomous decisions; daily journal/commitments still need a canonical
  JAWL data model instead of a second Companion store.

## Phase 7 — native tools and hardening

- [x] All current JAWL HostOS filesystem/process/coding/desktop namespaces stay
  native and are exposed through JAWL registry; Companion has no copied wrappers.
- [~] Native web `hostos.skill` and `debug.skill` bridges are implemented;
  the read-only `skills.catalog` route now enumerates the live registry, but
  representative native route probes and the catalog availability matrix now
  pass at levels 0-3; mutating skill execution and approval/recovery contracts
  remain separate live action gates. Every registered HostOS/HostTerminal skill
  and all seven Debug Broker skills still require live tests at levels 0–3.
- [x] Debug Broker operation metadata and native provider capability preserved.
- [~] Native audit/idempotency/approval parity and bounded result compression.
- [x] Port conflict check, loopback-only binds, HTTP security headers and
  restart cleanup.
- [~] Package/install/upgrade/rollback documentation and reproducible wheel
  plus SHA-256 manifest; deterministic two-build hash is now verified, while
  artifact signing/provenance and target-machine acceptance remain
  release-owner tasks.
- [~] Run full restart/soak with no leaked subprocess, audio stream or token.
  Dependency-free `scripts/run_restart_soak.ps1` now repeats startup, health,
  resource/vision probes, graceful shutdown and control/presentation port
  release; the latest local 5-cycle run passed with 30 health samples, no
  forced stops and no port leaks. Target-machine long-duration and live
  sidecar/audio evidence remain open.

## Quality gate

- [x] `.\scripts\run_full_gate.ps1` runs compile, all non-E2E tests, full HTTP
  E2E, synthetic mic gate and `git diff --check`.
- [x] Gate prefers `.venv\Scripts\python.exe` and pinned `requirements-dev.txt`.
- [x] Native JAWL focused web/control tests and Companion focused tests pass.
- [x] Add dependency-light headless Edge/Chrome browser-rendering lane; it
  checks the control DOM, gate/health/OBS markers and isolated avatar DOM.
- [x] Add a guarded target-machine loopback release smoke for control and
  presentation surfaces, with explicit required checks for JAWL, ASR/TTS,
  dependencies and Live2D readiness. The default degraded smoke passed;
  target hardware/provider/asset acceptance remains external.
- [x] Do not call the product production-ready until every applicable row in
  `docs/TECHNICAL_AUDIT.md` release matrix has live evidence.

## Current live decision — 2026-09-03

- Native JAWL + local Ollama now has a clean **1-turn release smoke**: the
  real JAWL web/terminal stack passed correlated `turn.started`, reconnect /
  resume, exact cancellation, typed tool lifecycle, final envelope and
  monotonic cursor checks. The report is
  `runtime/native-gateway-live-fixed-2026-09-03.json`.
- The mandatory **100-turn soak is not accepted**. It completed 23/100 turns
  and then timed out on `profile-cffb078d9614466d9e2395035545b29a` after the
  configured Ollama model returned an empty final answer through its bounded
  retry path. This is provider/model reliability evidence, not a Gateway
  transport failure; the release blocker remains open until a stable provider
  (QWB-JAWL, GPT Luna or a verified local model) passes the same profile.
- The live retry no longer has the old ONNX-cache blocker: JAWL reached the
  provider, reported `native_tools=True`, and executed the real terminal skill.
  The disposable runtime lives under `G:\AI\JAWL-Coding\runtime\ollama-smoke-retry`.
- The disposable live policy probe did not produce acceptance evidence: JAWL
  startup failed with `OSError: [Errno 28] No space left on device` while
  writing its PID because `G:` had only 8 KiB free. The probe web process was
  stopped and `8773` released; the Qwen3-ASR smoke had already released
  `8984`, and FoxMCP `8765` was not touched. Retry only after a runtime volume
  has sufficient free space (target: at least 2 GiB) and keep the 0–3 matrix
  explicitly open until the live run passes.
- Authenticated Companion → JAWL control was also verified live: Companion
  received `status=online`, native policy `authority=jawl` at level 3, and
  successful native HostOS plus Debug Broker results. The read-only parity
  sample covered coding context, file/read/search, network, desktop/UIA,
  monitoring, LSP/workspace discovery, HostTerminal history and Debug Broker
  discovery. This is partial parity evidence; mutating tools, approval flows,
  all levels 0–3 and provider-session actions remain unaccepted.
- The retry used a disposable runtime on C: and the new
  scripts/run_native_policy_profile.py: all four native levels passed safe
  sandbox/external read-write assertions, ROOT emergency stop blocked a native
  read until explicit reset, and the bounded ROOT lease issued/revoked cleanly.
  Report: runtime/native-policy-live-2026-09-03.json. This is filesystem
  policy evidence; full namespace, Debug Broker, approval and recovery parity
  remain open.

## Deferred by design

- [ ] 3D/VRM, mobile/multi-device sync, cloud deployment and complex swarm.
- [ ] Continuous raw audio/video recording; only bounded opt-in observations.
- [ ] Select a permanent VLM only after CPU/RAM live benchmark and explicit
  user choice.

## Live profile tooling

- [x] Add a dependency-free native Gateway profile runner with explicit
  live-turn opt-in, loopback guard, bounded SSE parsing, strict event/cursor
  validation, duplicate/sequence-gap detection, reconnect probe, cancellation
  probe, 100-turn run and redacted JSON report. It never executes a Companion
  local fallback tool.
- [~] Add the Vision plan execution seam: every action is translated to a
  normal HostOS request, fresh observation tokens are rechecked, and the
  sequence stops unless the adapter or an explicit verifier proves the
  postcondition. VLM wiring and live Windows acceptance remain pending.
- [x] Add a read-only native action-journal projection; Companion can inspect
  bounded autonomous plans without receiving parameters or gaining execution
  authority.
- [x] Add a bounded native skill-catalog projection; it reports current
  registered names/signatures/minimum levels without duplicating JAWL registry
  state or executing a skill.
- [x] Add dependency-free native namespace tooling: eight representative
  read-only route probes and a guarded level 0-3 catalog availability matrix;
  both restore no secrets and never execute mutating skills.
- [x] Add an opt-in native HostOS policy profile with loopback-only guard,
  native readiness polling, level 0–3 assertions, emergency-stop and lease
  checks, disposable write-marker cleanup and a JSON report. Cleanup restores
  the initial level/safety state on success and early assertion failure.

## Live evidence — 2026-09-02

- TeraTTSv2 local worker: `/health` returned `ok`; five real Russian requests
  through `TeraTTSHttpClient` measured first complete WAV p50 **1.223 s**,
  p95 **1.313 s**, median RTF **0.344**. A concurrent `TTSService.cancel()`
  produced `TTSCancelled` in **1.164 s**. This is whole-WAV REST evidence, not
  provider-native inference interruption or microphone/echo evidence.
- Native JAWL was started on loopback with QWB configured and all **7/7**
  Debug Broker providers reported ready. The live gateway profile then stopped
  on the first reconnect probe because QWB returned HTTP 503
  `upstream_waf_challenge`; therefore the required 100-turn result is **not
  accepted** and must be rerun after QWB/CDP cookies are refreshed or a
  verified local provider is selected.
- The profile harness now distinguishes an SSE read timeout after connection
  from an unreachable endpoint, so a future failure report identifies the
  actual boundary.
- Real VoiceMem sidecar text smoke with `--local-memory` returned correlated
  `USER_PARTIAL` + `VOICE_TURN` in **7.405 s** on a cold local E5 path. The
  process JSON-lines channel remained valid despite VoiceMem diagnostics. This
  validates the final-text integration only; the bundled sherpa audio path is
  not a Russian recognizer and its cold audio-model load must be warmed or
  replaced before microphone acceptance.
- The same real sidecar accepted explicit `warmup text` and `warmup audio`
  lifecycle requests and returned `VOICE_READY` (audio prewarm: **9.578 s**).
  This removes the first-request model-load ambiguity; it does not turn the
  bundled sherpa profile into a Russian ASR.
- Reproducible `run_voicemem_profile.ps1` now passes on the real
  `G:\AI\VoiceMem\assets\speech.wav`: audio prewarm **8.618 s**, 272 bounded
  PCM chunks, 3 partials, 1 final turn, first turn **14.317 s**, no process
  degradation. This is VoiceMem process/VAD evidence on its bundled zh-en
  fixture, not Russian microphone acceptance.
- Local Ollama `gemma-4-12b-coder-fable5-composer2.5-v1:latest` is reachable
  through the Companion OpenAI-compatible adapter: health online and one
  non-empty response in **1.085 s**. This is provider fallback evidence only;
  it has not yet passed the native JAWL 100-turn Gateway profile.
- An isolated JAWL+Ollama startup attempt did not reach the provider. JAWL
  detected a corrupted local ONNX embedding cache (`model_optimized.onnx`)
  and entered re-download; a clean retry data-dir removed that corruption but
  the embedding download still did not finish in the bounded test window.
  Both runs were stopped without accepting Gateway evidence. This is an
  upstream JAWL runtime/cache setup blocker, not proof that Ollama is
  incompatible.

## Live evidence — 2026-09-05

- Full gate after the native policy-profile hardening passed **252** non-E2E
  tests and **14** HTTP E2E tests, plus compileall, Qwen worker syntax,
  synthetic microphone gate, Node check and `git diff --check`.
- Direct disposable JAWL policy evidence passed levels `0..3`, representative
  native mutations, emergency-stop/reset and ROOT autonomy issue/revoke. The
  corrected harness restores its initial level and safety state on both success
  and early assertion failure. Evidence:
  `runtime/native-jawl-policy-20260905-fixed.json`.

## Live evidence — 2026-09-04

- The mint Windows-Aero control-plane redesign passed installed Edge headless
  rendering after keeping all existing API control IDs. Overview now includes
  an inline 2D companion preview; voice, perception, memory, access and
  diagnostics are focused tabs. The separate presentation origin remains the
  OBS mirror.
- The external-ASR response path no longer waits for VoiceMem enrichment. The
  same final text is queued to a bounded serialized memory worker and queue
  health is exposed in `/api/voice/status`. The live Tera integrated profile
  passed with `end_seconds=0.409`, `memory_sync.status=queued`; the previous
  65.7-second wait is no longer user-visible.
- Qwen3-TTS 12Hz 0.6B Base was found already downloaded and importable in the
  dedicated TTS environment. Its new loopback worker passed an integrated
  clone request with a valid 24 kHz WAV; CPU generation was about 19.3 s for
  one short reply. Qwen is accepted as the clone/quality route, while Tera
  remains the live CPU fallback until Qwen streaming/performance changes.
- The full gate passed **250** non-E2E tests, **14** HTTP E2E tests, compileall,
  Qwen worker syntax, synthetic microphone gate, Node check and `git diff
  --check`.
- The extended restart/soak profile passed **5/5** cycles with **30** health
  samples, **0** forced stops and **0** port leaks.
- The live target-release smoke passed control `2367` and presentation `8766`
  health/HTML/isolation checks; optional JAWL/provider/Live2D requirements
  were intentionally not asserted in this degraded profile.
- A guarded Qwen3-ASR audio-description probe on the existing
  `nyan_audio_30s.wav` fixture returned empty text for a non-speech description
  prompt. No captioning model was promoted from this negative result.

## Live evidence — 2026-09-03

- `scripts/run_browser_render_smoke.ps1` passed on installed Microsoft Edge:
  control DOM, microphone gate, health, OBS URL and isolated avatar surface
  markers were rendered; its temporary browser profile and Companion process
  were removed.
- The corrected wrapper invocation
  `run_restart_soak.ps1 --cycles 3 --probes 3` passed **3/3** cycles with
  **15** health samples, **0** forced stops and **0** port leaks.
- The Companion default-port smoke passed control `2367` and presentation
  `8766` with HTTP 200; the launcher also rejected an intentional presentation
  conflict with FoxMCP on `8765` before starting Python.
- The launcher rejects equal non-zero control/presentation ports before
  Python starts, with no partial listener left behind.
- The prior full gate passed: **243** non-E2E tests, **14** HTTP E2E tests,
  synthetic microphone gate, Node check and `git diff --check`. Two release
  builds remain byte-reproducible with SHA-256
  `2140c4f6...f793bda`.
- The clean JAWL+Ollama retry was stopped after bounded startup observation:
  it reached the provider (`native_tools=True`) and executed a real native
  terminal skill. The one-turn reconnect/cancel smoke passed; the 100-turn
  profile remains open because the model returned an empty final answer at
  turn 23.
- The authenticated Companion bridge read JAWL's live `skills.catalog`: 114
  native HostOS/HostTerminal/Debug Broker skills across 25 namespaces were
  returned with no unavailable entries at level 3. This closes discovery
  evidence, not the level 0–3 side-effect matrix.
- A real Qwen3-ASR `llama-server` was started from the moved benchmark files
  on loopback `8984` and exercised through `OpenAICompatibleASRClient`: the
  Russian TeraTTSv2 `welcome.wav` completed in **0.431 s** and `poem.wav` in
  **1.473 s**, both returning Russian text. The server was stopped and the
  port released. This proves the HTTP final-utterance bridge only; it does
  not close microphone/WASAPI, echo/barge-in or true partial-ASR acceptance.

## Current implementation update — 2026-09-02

- Native JAWL supervised recovery now fails closed without a valid per-instance
  ROOT lease. The lease validator enforces schema, ROOT level, expiry and the
  one-day maximum TTL; current HostOS configuration must also be enabled at
  level 3. Manual operator start remains available without a lease.
- Native JAWL runtime startup now invalidates unfinished one-shot coding
  approvals (`pending` and `approved`) from an older process session. The
  operator CLI remains read-only and does not invalidate requests merely by
  opening the registry.
- Native Gateway tool lifecycle summaries now preserve per-action success or
  failure status; the event remains metadata-only and does not expose tool
  arguments. The lifecycle is still emitted after the action batch by the
  current EventBus boundary, so live pre-dispatch timing remains open.
- Native JAWL action-journal inspection now has a bounded read-only web
  projection obtained through the native control socket, so the active JAWL
  runtime remains the only session classifier.
- Canonical daily journal support now reuses JAWL `structured_memories`: the
  consolidation pattern can idempotently revise `journal:YYYY-MM-DD`, while
  commitments remain native task records and are referenced by bounded IDs.
- Graph capability probing now rejects import-only Kuzu stubs instead of
  reporting successful writes; RAG and graph integration tests skip honestly
  when the real backend is unavailable.
- Vision execution now verifies the signed token's frame digest as well as its
  signature/expiry. The explicit confirmed plan route can use a thin native
  JAWL HostOSDesktop adapter in control mode; pointer `move`, `click`,
  `double_click`, `right_click` and `middle_click` now map to native skills,
  while unknown mappings still fail closed.
- Native JAWL `HostOSDesktop` decorators now enforce the documented access
  contract: observation at level 1 and interactive/system GUI actions at
  level 2; level 0 input is covered by a regression test.
- The related rows remain `[~]` until target-machine live crash/restart and
  approval-restart evidence is attached. This is implementation progress, not
  a production-readiness claim.
- Added `scripts/run_browser_render_smoke.ps1`: when Edge/Chrome is installed,
  it starts both loopback servers, renders the control and avatar pages in a
  headless browser, checks DOM markers and tears down the temporary profile.

- Screen observation now has an optional OCR grounding path and opaque pixel
  redaction for configured rectangles plus sensitive OCR regions. The VLM
  client receives only bounded non-sensitive OCR entries as untrusted data;
  raw frames remain transient.
- JAWL MCP projection now tolerates both protocol camelCase and Python SDK
  snake_case field names, including tool schemas, structured results, errors,
  pagination and MIME metadata. The broad unit/web gate is green again.
- Added a dependency-free Companion restart/soak profile; local three-cycle
  startup/health/shutdown/port-release validation passed with zero forced stops
  and zero port leaks.

## Latest synthetic voice and ambient evidence — 2026-09-03

- Three generated Russian TeraTTSv2 questions were sent as small PCM16 chunks
  through `/api/voice/audio` and `/api/voice/end`. Qwen3-ASR returned the exact
  Russian text for all three; each produced `USER_PARTIAL` + `VOICE_TURN`.
- With a local deterministic responder, all three voice turns reached the chat
  gateway and produced valid Russian TTS WAV responses. This is a synthetic
  pipeline acceptance, not proof of the external DeepSeek provider.
- The real Windows WASAPI loopback opened the default
  `Динамики (fifine Microphone) [Loopback]` device at 48 kHz stereo. Synthetic
  Tera audio produced 1350 captured chunks, 0 dropped chunks, one exact Qwen
  ambient transcript and one delayed candidate; the conversational last turn
  remained empty.
- `PyAudioWPatch==0.2.12.8` is installed in the user Python environment for
  this machine-level check. It remains an optional runtime dependency.

## Current provider smoke — 2026-09-03

- This section records the earlier adapter-only smoke. The superseding native
  JAWL + Big Pickle acceptance result is documented at the top of this file.
- OpenCode CLI lists `opencode/big-pickle` and returned a successful zero-cost
  JSON smoke response. The temporary profile is suitable for provider tests;
  OpenCode Zen's free models remain time-limited and are not a permanent
  provider decision.
- Companion's `OpenAICompatibleChatClient` now accepts a bounded explicit
  `--llm-user-agent`. With the locally installed CLI-compatible
  `OpenCode/1.18.11` value, `big-pickle` passed Companion health, non-streaming
  completion and SSE streaming checks without exposing the API key.
- A disposable Companion instance on ports `2391/8791` then passed the real
  browser-session `/api/chat` path, producing a complete envelope, and a
  second instance on `2392/8792` passed `/api/chat/stream` with one delta and
  exactly one final envelope. Both instances were stopped and their ports
  released.
- This proves the temporary HTTP adapter only. It does not close native JAWL
  provider-contract, tool-policy, reconnect or 100-turn acceptance; those
  still require the configured JAWL runtime to use the same provider.
- The full Companion gate after this change passed **227 non-E2E tests + 14
  HTTP E2E tests**, synthetic microphone, Node and `git diff --check`.

Example temporary test profile (keep the key outside the command history):

```powershell
$env:LLM_API_KEY = '<OpenCode Zen key from the local credential store>'
python -m jawl_voicecompanion --llm-url https://opencode.ai/zen/v1 `
  --llm-model big-pickle --llm-api-key-env LLM_API_KEY `
  --llm-user-agent OpenCode/1.18.11
```
