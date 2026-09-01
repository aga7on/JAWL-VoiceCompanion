# Project State

Last updated: 2026-09-01

## Current phase

Active workstream: Phase 6 — Presence and autonomy; the screen Attention/Presence
slice and Phase 3 ambient-memory foundation are in progress.

Phase 4 — 2D Live2D product UI (asset/runtime slice in progress).

Repository state: architecture baseline committed. A dependency-free mock
text/control slice is implemented. The real VoiceMem sidecar boundary now
accepts external ASR partials and browser PCM16 microphone chunks, and the
optional TTS boundary can call CozyVoice REST, and the `/avatar` surface can
load a user-supplied Live2D bundle behind a read-only asset root. Real JAWL,
production VoiceMem model startup, OmniVoice and an actual licensed Live2D
model remain opt-in/integration work. Optional UIA, focused-window OS and VLM
adapters remain explicit. The companion now has a read-only loopback bridge
for JAWL Heartbeat, persona and memory counters; it does not duplicate JAWL
storage. The screen path now has a bounded Attention/Presence gate and an
optional explicit JAWL event-IPC sink; final production JAWL validation is
still pending. The ambient secondary-memory design is documented separately:
optional system-audio loopback and visual observations use bounded transient
tiers and delayed CPU/RAM triage, while JAWL remains the only owner of
promoted memory. The first normalized ambient buffer and authenticated
browser inspection/configuration path are now implemented; real capture and
model triage remain opt-in work.

## Git state

- Branch: `main`;
- Baseline commits: `abce27d` (initial workspace), `1820eec` (HostOS/web
  architecture), `81534b2` (Phase 1 mock vertical slice), `f33b417` (JAWL
  terminal adapter), `bc2f775` (TurnArbiter), `ad7e97f` (HostOS tools),
  `5fdd373` (web API), `bad96dc` (state baseline);
- Working tree: clean after the screen-attention slice.
- Latest feature commit: `d631a12` (`fix: harden proactive event delivery`).

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
  emergency stop and redacted metadata-only audit entries.
- Loopback browser surface supports chat, health/state display and policy-level
  selection using local session/CSRF headers.
- Dedicated read-only `/avatar` surface renders a transparent OBS-ready
  placeholder, bounded subtitle and response-envelope avatar state.
- Explicit `screen.observe` adapter provides an opt-in focused-window JPEG
  snapshot with size bounds, deny-list checks and no disk persistence.
- JAWL terminal adapter understands the local `terminal.port` plus
  `JAWL_HANDSHAKE` JSON-lines protocol and falls back when JAWL is offline.
- `TurnArbiter` now models one active turn, priority lanes, stale-work
  cancellation and queue promotion; transport cancellation is still pending.
- HostOS tool registry now contains bounded filesystem, process and argv
  adapters. Real execution is explicit; default executor mode is dry-run.
- Optional Windows UIA adapter now provides bounded foreground-tree
  observation, semantic fingerprints and stale-target checks for control.
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
- `TTSService` provides latest-request-wins cancellation; the CozyVoice REST
  adapter splits bounded text into sentences, merges WAV chunks and exposes
  transient audio through `/api/tts/synthesize`. The browser plays it only
  when the provider is configured.
- The optional Live2D asset bridge serves only an explicitly configured root,
  exposes `/api/avatar/config`, loads a user-provided runtime/model pair and
  falls back to the placeholder when the bundle is absent or incompatible.
- The avatar bridge validates model `FileReferences` relative to the model
  JSON, reports fatal Moc/texture gaps separately from optional warnings and
  exposes `ready` without leaking local paths.
- The optional JAWL web bridge reads existing `/api/agent/status`, `/api/tick`,
  `/api/db/stats`, `/api/drives` and `/api/config` routes, filters config
  secrets and exposes session-protected inspection routes to the browser.
- The browser now renders the last bounded HostOS audit events; `/api/audit`
  requires the browser session and policy audit entries exclude arguments and
  raw command output.
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
- VoiceMem's current default streaming ASR should not be assumed to be the
  final Russian ASR choice; a benchmark is required.
- CozyVoice has a local REST wrapper, but its current `stream` path should be
  validated and likely corrected before latency-sensitive integration.
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
- `G:\AI\OmniVoice` was inspected and contains only a virtual environment; its
  model/API location is an external blocker.
- The configured JAWL `terminal.port` is currently stale and has no listening
  socket; the read-only probe returned `status=offline`, so live process
  verification remains pending.

## Current blockers / decisions needed later

- Choose and benchmark Russian streaming ASR;
- confirm the OmniVoice model/API location;
- select and manually validate the first redistributable or user-supplied
  Live2D model/runtime bundle;
- finish editable browser settings, memory and audit views; the current JAWL
  memory/persona surface is intentionally read-only;
- harden the initial HostOS session lifecycle and broaden audit coverage.
- improve and benchmark semantic screen significance scoring; the current
  heuristic gate connects `SCREEN_DELTA` to Attention/Presence and optional
  JAWL event IPC, while production final-wording validation remains;
- validate production VoiceMem audio model startup in its own environment and
  benchmark Russian ASR on a real microphone;
- validate CozyVoice model startup/latency and decide whether an actual
  streaming TTS worker is needed;
- choose the initial JAWL LLM endpoint/profile;
- decide whether local VLM runs through the existing QWB endpoint or a new
  local service;
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
fake audio/visual input is covered end-to-end while Windows capture and model
triage remain unconnected.

Verification for the current work session:
`scripts/run_full_gate.ps1` passed 91 unit tests and 5 complete HTTP E2E tests;
the full cross-layer gate is green;
the stale-port degraded probe returned `status=offline`;
`git diff --check` reported no whitespace errors and no Python warnings; the
real JAWL web -> adapter -> companion API inspection smoke-test also passed.
The SSE fix and its focused regression test are preserved in `9363de3`; hidden
output filtering, HTTP error cleanup and recovery coverage are preserved in
`91342b7`; the
preceding microphone slice is preserved in `36a808c` and the TTS slice in
`a217cec`.

Known limitation: no licensed Live2D model/runtime is installed yet; the
placeholder remains the default. The web server's default executor remains dry-run and no VLM
endpoint is configured by default; production semantic scoring and JAWL
final-wording delivery, pixel-level redaction, ASR quality benchmarking,
AEC/barge-in, streaming TTS playback cancellation, OmniVoice and production
model warmup are still pending. The native always-on-top desktop-pet shell is
also deferred. Ambient Windows loopback capture and CPU/RAM model triage are
not implemented yet.

## Next action

Validate the web bridge and explicit screen-event IPC against a live
production JAWL model/tool profile, including final response/broadcast
behavior. Then benchmark the installed VoiceMem ASR modes on a real Russian
microphone, validate production model warmup and CozyVoice latency, and choose
the first user-supplied Live2D model. The normalized ambient-memory contracts
and fake-source path are now in place; next implement a benchmarkable delayed
triage provider before touching Windows loopback capture.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
