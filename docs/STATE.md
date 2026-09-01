# Project State

Last updated: 2026-09-02

## Current phase

Active workstream: Phase 6 — Presence and autonomy; the screen Attention/Presence
slice and Phase 3 ambient-memory foundation are in progress.

Phase 4 — 2D Live2D product UI (asset/runtime slice in progress).

Repository state: architecture baseline committed. A dependency-free mock
text/control slice is implemented. The real VoiceMem sidecar boundary now
accepts external ASR partials and browser PCM16 microphone chunks, and the
selected TeraTTSv2 provider is available through a local REST wrapper, and the
`/avatar` surface can load a user-supplied Live2D bundle behind a read-only
asset root. Real JAWL,
production VoiceMem model startup, OmniVoice and an actual licensed Live2D
 model remain opt-in/integration work. Optional UIA, focused-window OS and VLM
 adapters remain explicit. The companion now has a loopback bridge for JAWL
 Heartbeat, persona and memory counters plus an opt-in authenticated native
 HostOS level control path; it does not duplicate JAWL storage or its tool
 registry. The screen path now has a bounded Attention/Presence gate and an
optional explicit JAWL event-IPC sink; final production JAWL validation is
still pending. The ambient secondary-memory design is documented separately:
optional system-audio loopback and visual observations use bounded transient
tiers and delayed CPU/RAM triage, while JAWL remains the only owner of
promoted memory. The first normalized ambient buffer and authenticated
browser inspection/configuration path are now implemented. A strict,
model-neutral delayed audio-triage contract and optional CPU-first Ollama
adapter are now present; no model is selected or loaded by default. The
operator's CPU/RAM benchmark selected Qwen3-VL-2B as the primary Vision
candidate, with SmolVLM2-500M as a speed fallback. The local endpoint and
explicit screen look are now smoke-tested, and the optimized screen watcher
has produced bounded `SCREEN_DELTA` events; bounded UIA context and the
calibrated `desktop.pointer` fallback are now attached to explicit Vision
workflows, while semantic watcher tuning remains.

## Git state

- Branch: `main`;
- Baseline commits: `abce27d` (initial workspace), `1820eec` (HostOS/web
  architecture), `81534b2` (Phase 1 mock vertical slice), `f33b417` (JAWL
  terminal adapter), `bc2f775` (TurnArbiter), `ad7e97f` (HostOS tools),
  `5fdd373` (web API), `bad96dc` (state baseline);
- Working tree: clean after the microphone gate and HostOS hardening slices.
- Latest feature commits: `7ae1ab1` (microphone gate) and `3cac12e`
  (closed TTS stream cancellation); the current HostOS status/allow-list slice
  is pending commit.

## Completed in this repository

- Isolated development directory created at `G:\AI\JAWL-VoiceCompanion`.
- Documentation policy created in `AGENTS.md`.
- Initial work breakdown created in `TODO.md`.
- Architecture and event/response contracts drafted.
- 2D Live2D selected as the only current avatar target.
- JAWL selected as canonical cognitive core.
- VoiceMem selected as a separate voice/sensory sidecar.
- HostOS access levels 0–3 accepted, with level 3 available as an explicit
  full-current-user mode.
- Browser selected as the canonical local control plane.
- Python package `jawl-voicecompanion` and stdlib-only test runner created.
- Deterministic mock text gateway returns and validates `ResponseEnvelope`.
- HostOS policy gate supports access checks, approval-required decisions,
  emergency stop, ROOT-only unattended execution, deny-list checks and
  redacted metadata-only audit entries.
- HostOS now tracks managed and shell subprocesses; emergency stop terminates
  them and an interrupted shell request returns `cancelled`.
- HostOS shell execution now reports non-zero exit codes as `failed` and kills
  an owned process on timeout before returning `timeout`; the unit and HTTP
  E2E paths assert these postconditions.
- HTTP E2E now covers shutdown cleanup and safe restart defaults: owned
  processes are stopped, unattended is off, and approvals are in-memory only.
- Loopback browser surface supports chat, health/state display and policy-level
  selection using local session/CSRF headers.
- Dedicated read-only `/avatar` surface renders a transparent OBS-ready
  reactive 2D fallback, bounded subtitle and response-envelope avatar state.
- Explicit `screen.observe` adapter provides an opt-in focused-window JPEG
  snapshot with size bounds, deny-list checks and no disk persistence.
- JAWL terminal adapter understands the local `terminal.port` plus
  `JAWL_HANDSHAKE` JSON-lines protocol and falls back when JAWL is offline.
- VoiceMem sidecar lifecycle is bounded and observable: an empty audio flush
  does not initialize the model, failed sessions are evicted for recovery, and
  `/api/voice/status` reports process state without launch paths or arguments.
- `TurnArbiter` now models one active turn, priority lanes, stale-work
  cancellation and queue promotion; transport cancellation is still pending.
- HostOS tool registry now contains bounded filesystem, process and argv
  adapters. Real execution is explicit; default executor mode is dry-run.
  Complete bounded reads expose a SHA-256 snapshot and workspace writes can
  require that digest, returning `stale_file` instead of overwriting a changed
  file.
- Optional Windows UIA adapter now provides bounded foreground-tree
  observation, semantic fingerprints and stale-target checks for control.
- The custom-surface path now includes a policy-gated `desktop.pointer`
  adapter. It recalibrates image coordinates against fresh foreground-window
  bounds and reports cursor placement as a postcondition without claiming
  that the target application accepted the input.
- The same path now includes `desktop.keyboard` for bounded Unicode text and
  one-to-four-key hotkeys, bound to the observed foreground window and covered
  by injected-backend unit/E2E tests.
- The transparent avatar fallback now renders a lightweight reactive 2D face
  with expression, blink and speaking animation. A valid user-supplied Live2D
  bundle still replaces it; no third-party character asset was copied.
- The TTS browser path now derives a bounded amplitude signal with
  `AnalyserNode`, sends it through a BroadcastChannel and ephemeral backend
  state, and drives fallback/runtime lip-sync without storing audio.
- Browser adapter now supports bounded HTTP(S) navigation and delegates
  semantic actions to UIA; no browser automation runtime is installed yet.
- Browser API exposes the tool registry and routes execution requests through
  the same server-side HostOS policy; browser approval authority is not
  accepted from request payloads.
- ApprovalStore now supports session-bound one-shot decisions, expiration,
  exact request/policy fingerprints and redacted previews.
- Gateway user turns now receive arbiter generations; a newer user turn signals
  the JAWL adapter to cancel its pending socket read.
- `ScreenDeltaWatcher` provides an explicit opt-in, arbiter-aware passive
  producer. It stores a bounded in-memory event ring and publishes only
  `SCREEN_DELTA` summaries through the local API; it never speaks or stores a
  raw frame.
- `AttentionPresence` consumes screen deltas with bounded salience/privacy,
  manual DND, cooldown and hourly-budget gates, exposing inspectable
  `SPEAK_INTENT` proposals through `/api/vision/intents`.
- Ambient secondary memory is documented as a separate, opt-in evidence path:
  system audio stays separate from microphone turns, raw audio/frames are
  transient, and delayed triage must produce attributable candidates before
  any JAWL promotion.
- `AmbientMemoryBuffer` now provides default-off bounded audio/visual event
  ingestion, private-text suppression, duplicate/TTL/byte limits, deterministic
  coalescing and `AMBIENT_EPISODE_CANDIDATE` output; `/api/ambient-memory`
  exposes authenticated inspection, triage, clear and explicit enable/disable.
- `SystemAudioLoopback` now defines the optional Windows WASAPI loopback
  boundary: lazy PyAudioWPatch-compatible loading, default-device selection,
  bounded in-memory PCM16 queue and explicit degraded behavior when the backend
  is absent. It is not auto-started and is not wired to live capture startup.
- `AmbientAudioASRBridge` now downmixes/resamples loopback PCM16 into an
  isolated `ambient-audio:` VoiceMem session and ingests only final
  `VOICE_TURN` events into the bounded ambient buffer; partials never become
  user turns.
- `AmbientAudioService` and the browser lifecycle routes now require explicit
  ambient-memory consent before start, flush the isolated ASR session on stop
  and report missing loopback backends as degraded.
- The browser control plane now displays ambient-memory consent, observation
  counts, loopback backend state and running/stopped status, with start/stop
  controls disabled until consent is active. It also exposes explicit triage
  and clear actions for the bounded buffer.
- Attention/Presence now supports a validated local-time quiet-hours window
  (`HH:MM-HH:MM`) with midnight crossing, persisted in runtime state and
  editable from the browser.
- Attention/Presence can now use an explicit `--user-activity` Windows
  adapter. It suppresses proactive screen speech after recent input and
  exposes only bounded idle/class metadata; it is disabled by default.
- `AmbientTriageProvider` now defines a bounded delayed-provider contract with
  strict provenance/schema validation. `OllamaTriageProvider` is an optional
  stdlib HTTP adapter configured CPU-first (`num_gpu=0`); it does not select,
  download or keep a model resident by default.
- `JawlEventFileSink` atomically writes accepted screen intents to an
  explicitly configured JAWL `.jawl_events` directory in the existing
  `{message, payload}` IPC shape; raw frames and local paths are excluded.
- The cross-layer E2E suite drives the real loopback HTTP server and covers a
  complete visible path from chat/state through HostOS approval/execution and
  emergency stop, plus screen capture, VLM deduplication, screen events and
  the JAWL-compatible terminal handshake/JSON-lines path.
- The browser microphone path converts input to bounded mono PCM16, VoiceMem
  owns streaming ASR/VAD in its separate environment, and only final
  `VOICE_TURN` events reach JAWL. `/api/voice/end` flushes active capture.
- The browser microphone path now has a configurable pre-ASR noise gate with
  hysteresis, 120 ms bounded pre-roll, three-block release, local noise-floor
  calibration and RMS/peak visualization. Closed-gate blocks never enter the
  HTTP audio queue; hardware-level filtering remains dependent on the browser,
  driver and microphone interface.
- The browser now has an opt-in half-duplex hands-free boundary: a bounded
  local RMS silence gate finalizes an utterance through `/api/voice/end`,
  rotates the session ID and keeps capture open; model VAD and final-turn
  ownership remain in VoiceMem/Qwen.
- `TTSService` provides latest-request-wins cancellation; the CozyVoice REST
  adapter splits bounded text into sentences, merges WAV chunks and exposes
  transient audio through `/api/tts/synthesize`. The browser plays it only
  when the provider is configured, with provider-neutral voice and speed
  controls.
- The optional Live2D asset bridge serves only an explicitly configured root,
  exposes `/api/avatar/config`, loads a user-provided runtime/model pair and
  falls back to the reactive 2D face when the bundle is absent or incompatible.
- The avatar bridge validates model `FileReferences` relative to the model
  JSON, reports fatal Moc/texture gaps separately from optional warnings and
  exposes `ready` without leaking local paths.
- The Windows desktop-pet launcher now validates the Companion HTTP `/avatar`
  page before opening Edge/Chrome, so an occupied port serving a WebSocket-only
  service fails with a clear conflict instead of a misleading upgrade error.
- `scripts/run_web.ps1` now performs the same occupied-port preflight before
  starting Python and reports the owning process with an alternate-port hint.
- The optional JAWL web bridge reads existing `/api/agent/status`, `/api/tick`,
  `/api/db/stats`, `/api/drives` and `/api/config` routes, filters config
  secrets and exposes session-protected inspection routes to the browser.
- The upstream API audit confirms there is no stable HTTP CRUD surface for
  JAWL personality traits or facts; those remain JAWL-internal SQL skills/UI.
  The companion will not access the databases directly or create a duplicate
  durable memory store.
- The browser now renders the last bounded HostOS audit events; `/api/audit`
  requires the browser session and policy audit entries exclude arguments and
  raw command output. The CLI now persists allowlisted metadata to bounded
 JSONL and the browser can recover those events after restart.
- The approval queue now exposes bounded/redacted proposal reviews and a
  browser-only one-shot execution route; approved requests are removed from
  memory after execution, while policy rechecks and stale-file protection stay
  active.
- `JawlWebChatAdapter` now treats an HTTP reader exception caused by concurrent
  response close as normal cancellation; a regression test protects the
  daemon reader from leaking a traceback.
- Both JAWL transports now fail closed on internal reasoning/tool markup and
  remove paired hidden blocks before text reaches the envelope, subtitle or
  TTS path. The local HTTP E2E also covers upstream outage and recovery.
- A bounded `/api/doctor` report and browser panel now expose component
  readiness, remediation hints and continued text-only availability. The
  report is bounded, does not expose paths or secrets, and does not change
  runtime configuration.

## Reference inventory

- JAWL fork: `G:\AI\JAWL-Coding`;
- VoiceMem: `G:\AI\VoiceMem`;
- CozyVoice: `G:\AI\CozyVoice`;
- OmniVoice: `G:\AI\OmniVoice`;
- reference clones: `G:\AI\_tmp\companion-repos`.

## Known local observations

- VoiceMem has an external-ASR integration point through `feed_partial`.
- VoiceMem `0.2.3` returns a `StreamState` from `feed_partial`; `ended=True`
  yields a completed `Turn`, while partial text avoids loading audio models.
- VoiceMem's bundled `web/run.py` is a demo WebSocket and not a stable
  correlated sidecar API; the transport-neutral contract is now recorded in
  `docs/contracts/voice.md`.
- The minimal sidecar runner/client and `/api/voice/partial`,
  `/api/voice/audio`, `/api/voice/end` bridges are implemented. The
  production runner is lazy and returns `VOICE_DEGRADED` if VoiceMem is not
  installed or cannot initialize.
- The external CPU/RAM audio benchmark selected Qwen3-ASR-0.6B for Russian
  speech experiments (RTF 0.13–0.15, about 1.48 GB peak RAM on the supplied
  samples). The exact benchmark file and transcription prompt return the
  expected text from local `llama-server`; the bounded adapter now sends that
  prompt and forwards its final transcript to the VoiceMem
  `feed_partial(..., ended=True)` boundary. True streaming Qwen partials and
  live Russian microphone quality remain pending.
- A follow-up live run sent VoiceMem's three known PCM16 samples through the
  same Companion adapter and matched their README transcripts in Chinese.
  This validates the multilingual request/response path, not Russian acoustic
  quality; no Russian reference recording is present in the inspected assets.
- The temporary OpenAI-compatible chat adapter accepts a configurable URL,
  model and environment-held key for provider experiments. TokenRouter with
  `z-ai/glm-5.3-free` reached HTTP 200 during the smoke, but one short request
  returned an empty `message.content`; this profile is not treated as a
  JAWL/QWB compatibility proof. The canonical path remains the JAWL web or
  terminal bridge, where JAWL owns JSON tool/action envelopes, persona,
  memory and Heartbeat.
- The operator's 2026-09-01 CPU/RAM benchmark selected
  `Qwen3-VL-2B-Q4_K_M.gguf` with `Qwen3-VL-2B-mmproj-F16.gguf` as the primary
  VLM profile: approximately 28–36 tok/s, 4.1 GB peak RAM, strong image/video
  quality and usable UI grounding after calibration. `SmolVLM2-500M` is the
  low-latency fallback; `Bonsai-1.7B` is text-only and `Qwen3-ASR-0.6B` is
  the leading audio candidate. The VLM files live outside this repository
  under `G:\AI\VLM-RealTime-Bench\models`; the matching b10738 CPU runtime is
  under its `runtime` directory, and no weights are copied into source.
- The moved-file rerun is recorded in `docs/MODEL-TESTS.md`: Qwen3-VL-2B
  remains the practical Vision baseline (32–40 tok/s, 4.36 GB peak RSS and
  45.7 px calibrated UI mean error), while Qwen3.8-27B reaches good image/video
  descriptions only at roughly 27 GB RSS and 2.8 tok/s. Qwen3.8 is therefore
  optional on-demand, not a continuous watcher model.
- The installed Ternary Bonsai text family was checked for the deferred
  ambient-memory worker. Bonsai 1.7B PQ2 measured 1.29 GB peak RSS and
  50.7 tok/s in the plain completion smoke; its chat smoke passed the four
  basic fact/math/instruction/context checks. Bonsai 4B and 8B use 2.54 GB/
  4.24 GB and are slower, so 1.7B is the first candidate for asynchronous
  TTL-bounded summary/topic compression, not for importance decisions,
  canonical chat or ASR.
- The delayed ambient triage path now has an OpenAI-compatible JSON-schema
  provider for local `llama-server` and similar endpoints. A live Bonsai 1.7B
  request returned valid provenance but classified all four synthetic triage
  cases as `ignore`. The memory layer now applies deterministic importance
  guarding over provider output; a guarded live rerun promoted the explicit
  error/remember cases and retained the plan/ordinary-background cases.
  Salience calibration and JAWL promotion rules remain required before durable
  writes.
- The triage scheduler is now an opt-in daemon with bounded interval, duplicate
  start protection and server-shutdown handling; `/api/ambient-memory` exposes
  its last status. It performs no triage until the configured interval elapses.
- Qwen3-ASR-0.6B was rerun from the moved `models/qwen3-asr` directory at
  RTF 0.15–0.16. It transcribed local Russian TTS welcome phrases correctly;
  synthetic poem samples still contain word/ending errors, and real Russian
  microphone validation remains pending.
- The native VoiceMem stream was exercised offline with its bundled sherpa
  streaming recognizer, Silero VAD and local memory components. The shipped
  zh-en fixture completed a real `turn_over` after 66 partial updates; the
  Russian Qwen3-TTS WAV did not complete a turn and produced an English
  hallucination. VoiceMem's streaming lifecycle/VAD boundary is therefore
  usable, but its bundled recognizer is not a Russian model; Qwen3-ASR stays
  the Russian acoustic candidate until true streaming Russian ASR is tested.
- New external TTS samples were checked through Qwen3-ASR: TeraTTSv2 produced
  the strongest current CPU/clarity profile (RTF 0.05–0.06, about 2.56 GB RAM,
  exact welcome and nearly exact poem), while XTTS-v2 was slower and Pocket-TTS
was not intelligible in Russian. TeraTTSv2 is the current selected provider;
voice cloning is deferred, while prosody, first-audio latency, cancellation
and actual avatar-path integration remain validation work.
  A direct warm streaming call produced its first chunk in about 1.04 s and
  requires `<ru>...</ru>` input. The Companion now exposes a sentence-level
  `/api/tts/stream` NDJSON/WebAudio path, while the native Tera chunk generator
  remains outside the provider boundary.
- An optional `scripts/teratts_server.py` wrapper now exposes TeraTTSv2 through
  the existing local TTS contract. A real smoke through `CozyVoiceHttpClient`
  and `TTSService` returned valid mono 44.1 kHz WAV audio; the model release
  remains external; the browser can now receive sentence audio incrementally
  through `/api/tts/stream` and drives lip-sync from the playback nodes.
- A live 2026-09-01 smoke started the Qwen endpoint on loopback, raised the
  Companion to HostOS OBSERVER level 1 and completed `/api/vision/look` through
  the real Windows focused-window capture. It returned a bounded Russian
  description in about 10.9 seconds; the raw frame was not persisted. This
  validates the explicit path, not yet a low-latency continuous watcher.
- The optimized 2026-09-01 watcher smoke used a 960×720/1 MB profile and
  captured a 960×520 frame (71.7 KB; coordinate scale about 2.02 on both
  axes). It produced 3 bounded `SCREEN_DELTA` events in 12 seconds through
  the live Qwen endpoint; raw frames remained absent from the event path.
- The model-neutral REST TTS adapter now uses at most three concurrent
  sentence requests, merges compatible WAV chunks in source order, and
  exposes explicit cancellation. The browser aborts stale playback requests
  and uses a bounded RMS activity trigger for basic barge-in; the upstream
  `stream` path, selected model startup, latency and first-audio playback still
  require validation.
- The local OmniVoice directory currently does not expose a ready project/API
  layer; model and integration details must be confirmed before adapter work.
- The 2026-09-01 local model inventory exposed only two Ollama profiles:
  `gemma-4-12b-obliterated:latest` and
  `gemma-4-12b-coder-fable5-composer2.5-v1:latest`; Prism-ML and
  Ternary-Bonsai-8B were not found locally. A hardware snapshot reported
  about 93.7 GB physical RAM (about 55.2 GB free) and two RTX 5080 devices
  with 16 GB each; this is an inventory, not a triage suitability benchmark.
- No Live2D model or runtime is installed in the companion repository. The
  reference clones contain sample assets and Pixi/Cubism patterns, but the
  asset bridge cannot claim real rendering until a licensed bundle is supplied
  and opened in a browser.
- JAWL and VoiceMem use different Python environments and should remain
  separate services initially.
- JAWL's existing web console provides the stable read-only memory/heartbeat
  surface; no companion-side SQLite access or second durable memory store is
  warranted.
- A real JAWL web console smoke-test with its agent stopped answered all five
  upstream routes; the companion bridge then exposed the live Heartbeat,
  database counters, drives and filtered persona through its own API.
- A named isolated JAWL turn-smoke was started against local Ollama using a
  copied embedding cache; the LLM request completed without changing
  canonical JAWL data/config. Direct terminal handshake produced
  `HOST_TERMINAL_MESSAGE` and a model response, but the native cycle emitted
  no `send_message_to_terminal` broadcast, so the companion correctly returned
  degraded fallback. The web POST+SSE path reached the same terminal bridge;
  its user-facing success remains unverified for this model profile because
  JAWL emitted no correlated agent message.
- JAWL's web helper currently resolves its `chat.py` port/history paths from
  its repository root rather than `JAWL_DATA_DIR`; a multi-instance launch
  therefore needs a per-instance code root (or an upstream path fix). The
  companion accepts only the loopback web URL and does not silently weaken this
  boundary.
- JAWL owns a native `HostOSClient`/SkillRegistry. An opt-in
  `--jawl-hostos-control` bridge now writes only its allowlisted HostOS level
  fields and restarts the JAWL agent before changing the companion policy.
  The companion still does not create a second JAWL tool registry.
- The `/api/jawl/hostos` bridge reports bounded native JAWL HostOS values and
  whether control is enabled. JAWL's native Heartbeat remains autonomous;
  companion unattended and approvals are not falsely reported as native JAWL
  state; bridge emergency-stop also requests native `/api/agent/stop` while
  retaining the local process cancellation path. The browser recovery route
  starts native JAWL before clearing the local emergency latch.
- `G:\AI\OmniVoice` was inspected and contains only a virtual environment; its
  model/API location is an external blocker.
- The configured JAWL `terminal.port` is currently stale and has no listening
  socket; the read-only probe returned `status=offline`, so live process
  verification remains pending.

## Current blockers / decisions needed later

- integrate and validate Qwen3-ASR-0.6B with the streaming VoiceMem boundary
  or document a lower-latency replacement;
- confirm the OmniVoice model/API location;
- select and manually validate the first redistributable or user-supplied
  Live2D model/runtime bundle;
- finish editable browser settings, memory and audit views; the current JAWL
  memory/persona surface is intentionally read-only;
- harden the initial HostOS session lifecycle and broaden audit coverage.
- add native JAWL contracts for approval state and emergency stop so those
  controls can eventually be synchronized instead of remaining companion-only.
- improve and benchmark semantic screen significance scoring; the current
  heuristic gate connects `SCREEN_DELTA` to Attention/Presence and optional
  JAWL event IPC, while production final-wording validation remains;
- validate production VoiceMem/Qwen3-ASR audio startup in its own environment
  and measure Russian ASR on a real microphone;
- recheck TeraTTSv2 startup/latency and browser audio on the target machine;
  sentence-level first-audio is implemented, while native Tera chunking is an
  optional optimization;
- choose the initial JAWL LLM endpoint/profile;
- tune bounded screen resizing and coordinate calibration for the selected
  Qwen3-VL-2B endpoint, then validate pointer actions against a real
  custom-rendered application;
- measure actual GPU contention and model residency on the target machine.
- validate the correlated web bridge against a production JAWL model/tool
  profile that emits user-facing broadcasts and add restart/reconnect recovery
  coverage; no-broadcast remains an explicit degraded state.

## Latest work session

Changed the passive watcher, web API/CLI wiring, vision deduplication,
E2E runner/tests and the related architecture/contracts/documentation in
`307da25`; extended the JAWL adapter path in `1f1717d`; recorded the
VoiceMem sidecar boundary in `91ffc50`; implemented the sidecar runner,
client and HTTP bridge in `a33f7b9`; added browser PCM16 microphone ingress
and final-turn routing in `36a808c`.
The current work session adds the TTS boundary and CozyVoice REST path plus
the optional Live2D asset/runtime bridge, then adds the read-only JAWL web
memory/persona bridge and its browser view, validates real JAWL payloads and
applies a drive-field allow-list. The audit view was then added and covered
end-to-end. The Live2D bridge now validates fatal model references and
documents the minimal renderer plugin contract. A safe local-Ollama JAWL
turn-smoke completed an LLM request but exposed the broadcast-only terminal
boundary; the companion returned degraded fallback as designed.
The correlated web POST+SSE adapter is now implemented and preferred when a
JAWL web URL is supplied; sequence correlation, cancellation and degraded
no-broadcast behavior are covered by tests. The isolated production probe then
confirmed terminal input and local Ollama completion, but also confirmed the
no-broadcast model behavior and the upstream root-bound web path. The SSE
reader close race was fixed with a focused regression test. Hidden-thought
filtering and HTTP error-body cleanup were added with recovery coverage.
The doctor slice now covers mock/degraded, fully configured and required-JAWL
offline states and is preserved in `c66f088`. The current screen-attention
slice is preserved in `a832b67` and `d631a12` and includes unit, browser and
cross-layer HTTP coverage for intent creation, DND, correlation and
JAWL-compatible atomic event delivery.

The latest documentation update records the ambient secondary-memory decision
in `docs/SECONDARY_MEMORY.md`, with TODO items for separated system-audio
capture, bounded retention, delayed triage, visual keyframes and provenance.
An isolated 2026-09-01 smoke using JAWL's actual `DaemonsPoller`, `EventBus`
and `EventBridge` accepted one `JawlEventFileSink` file, consumed it and
delivered one `HOST_OS_SANDBOX_EVENT` to `Heartbeat.answer_to_event`; the
spoken final response remains model-dependent and the known `no_broadcast`
production-profile result is preserved.
The current implementation adds `AmbientMemoryBuffer` and authenticated
`/api/ambient-memory` inspection, configuration, triage and clear routes;
fake audio/visual input and the loopback-to-ambient HTTP path are covered
end-to-end while live Windows permission/startup remains unconnected. Audio
triage now has a strict provider contract, optional CPU-first Ollama adapter
and benchmark protocol with unit coverage. The operator's model benchmark
now names Qwen3-VL-2B as the primary VLM candidate and leaves model loading
outside the repository until the local server contract is verified.

The current TTS follow-up adds bounded parallel sentence requests with
source-order merge, explicit server cancellation, browser request abort,
provider-neutral voice/speed controls and focused concurrency/cancellation
regression tests. It also exposes `/api/tts/stream`: sentence WAVs are emitted
in source order as NDJSON and scheduled by WebAudio before the full reply is
ready; this is sentence-level, not native token streaming.

The current model follow-up adds OpenAI-compatible SSE text streaming and an
authenticated `/api/chat/stream` surface. Reasoning blocks stay buffered and
only safe deltas are shown; the stream ends with one canonical response
envelope. JAWL's current web adapter remains completion-oriented and uses the
same endpoint's compatibility path.

The real Tera worker was then exercised synthetically through the Companion
HTTP stream: first audio arrived in 0.87 s for a short two-sentence reply; a
warmed four-sentence reply produced first audio in 0.39 s and finished in
1.74 s. No microphone hardware was used. These numbers are warm local
benchmarks and must be rechecked after the final browser/audio setup.

The current VoiceMem follow-up hardens lazy sidecar startup and recovery:
empty `/api/voice/end` calls do not initialize VoiceMem, a failed stream is
evicted so the next request can recreate it, and the process lifecycle is
included in the bounded health response. The full gate covers these paths.

The current Presence follow-up adds the opt-in Windows activity signal and
tests the public attention state through the HTTP E2E watcher path. It does
not inspect keystrokes, titles or clipboard contents, and it does not select
or load a VLM itself; explicit Vision now uses the separately benchmarked
Qwen3-VL-2B endpoint when configured.

The Vision follow-up adds a small PowerShell launcher for the benchmarked
Qwen3-VL-2B Q4_K_M plus F16 mmproj. The launcher validates external model
paths, binds `llama-server` to loopback, selects one CPU slot and disables
GPU offload. A real smoke test passed `/health`, `/v1/models`, the existing
`OpenAICompatibleVisionClient` against `ui_test.png` and the live optimized
screen watcher; the server was stopped after validation.

The launch follow-up adds a PowerShell preflight for the selected web port;
the observed `426 Upgrade Required` on port `8765` is now diagnosed before the
Companion starts, while the existing WebSocket-only process remains untouched.

The current HostOS follow-up adds bounded file snapshots and conditional
workspace writes with stale-file rejection, plus a browser proposal/review and
one-shot execution surface. A broader diff/transaction editor remains pending.

The JAWL write-surface audit is intentionally conservative: configuration and
drive endpoints exist upstream, but trait/fact CRUD is not exposed as a
versioned web/event contract. Keep the companion bridge read-only for those
records until that contract exists.

The current voice follow-up adds an authenticated TTS cancel route, browser
request abort and a one-shot RMS barge-in trigger. VoiceMem classification,
AEC quality and full half-duplex behavior remain pending.

The latest HostOS hardening separates level 3 current-user capability from an
explicit ROOT-only `unattended` switch. Background/Heartbeat tool calls can
therefore run while the operator is away without per-action prompts; emergency
stop and deny-tools/deny-risk policy checks remain authoritative. The browser
control plane exposes these settings and the policy fingerprint includes them.

The latest desktop-control follow-up adds `desktop.pointer` and
`desktop.keyboard` for custom/canvas
surfaces. Image coordinates are recalibrated against fresh foreground bounds,
stale windows are rejected, and pointer/keyboard dispatch is reported
separately from application acceptance. Unit and HTTP E2E coverage use injected
backends, so no real click or keystroke was performed during automated
verification.

The latest ASR validation re-ran the live Qwen endpoint through the Companion
adapter against the three known VoiceMem samples and matched all expected
transcripts. A Russian reference WAV and a real microphone run are still
required before making a Russian-quality claim.

The emergency-stop slice tracks live `process.managed` and `shell.exec`
children, terminates them through the same executor, and covers the race with
a background shell request in unit tests. Server shutdown also cleans up
tracked children so a recovery/restart does not leave companion-owned work
running.

Verification for the current work session:
`scripts/run_full_gate.ps1` passed 150 unit tests and 13 complete HTTP E2E tests;
the full cross-layer gate is green;
the stale-port degraded probe returned `status=offline`;
`git diff --check` reported no whitespace errors and no Python warnings; the
real JAWL web -> adapter -> companion API inspection smoke-test also passed.
The native HostOS level bridge is preserved in `36cd034`, and native emergency
stop in `5988861`; the SSE fix and its focused regression test are preserved in
`9363de3`; hidden
output filtering, HTTP error cleanup and recovery coverage are preserved in
`91342b7`; the
preceding microphone slice is preserved in `36a808c` and the TTS slice in
`a217cec`.

Known limitation: no licensed Live2D model/runtime is installed yet; the
reactive 2D fallback remains the default. The web server's default executor remains dry-run and no VLM
endpoint is configured by default; production semantic scoring and JAWL
final-wording delivery, real custom-app pointer acceptance and pixel-level redaction,
real-microphone ASR quality and final Live2D lip-sync tuning,
AEC/barge-in, native provider-level TTS chunking, OmniVoice and production
model warmup are still pending. The desktop-pet launcher is available as a
bounded always-on-top presentation shell; native transparent compositing is
still deferred. The system-audio loopback adapter, permission/API wiring and
isolated ASR consumer are implemented; backend installation and real-device
capture/ASR quality validation remain pending. The CPU/RAM benchmark and
opt-in triage-worker scheduling are complete; the Qwen3-VL-2B local endpoint
integration is verified; watcher tuning, triage calibration and production
model warmup remain.

The current follow-up added an opt-in half-duplex hands-free boundary to the
browser microphone path. It uses local RMS silence only for phrase finalization,
keeps VoiceMem/Qwen as the ASR and final-turn owner, and rotates the session ID
after each utterance. The moved benchmark directory was revalidated for both
Qwen3-VL-2B and Qwen3-ASR-0.6B; the installed Qwen3.8-27B experiment is recorded
as on-demand only because its CPU latency and memory footprint are too high.
An additional read-only Windows foreground-window smoke returned real bounds,
a bounded 960x562 JPEG snapshot and five UIA elements; mapping the captured
image center back to screen coordinates returned `[569,331]` with no disk
persistence. A real custom-app dispatch/postcondition test is still pending.
The full gate remains green after the feature changes.

## Next action

Validate the calibrated UIA/pointer path against a real custom application and
the bounded Qwen3-VL-2B screen path. In parallel, validate Qwen3-ASR/VoiceMem on real
Russian microphone audio, benchmark the selected TTS provider, and connect
the resulting final voice path to avatar lip-sync without weakening the
HostOS approval and emergency-stop gates.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
