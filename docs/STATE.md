# Project State

Last updated: 2026-09-01

## Current phase

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
storage.

## Git state

- Branch: `main`;
- Baseline commits: `abce27d` (initial workspace), `1820eec` (HostOS/web
  architecture), `81534b2` (Phase 1 mock vertical slice), `f33b417` (JAWL
  terminal adapter), `bc2f775` (TurnArbiter), `ad7e97f` (HostOS tools),
  `5fdd373` (web API), `bad96dc` (state baseline);
- Working tree: clean after the current verification.
- Latest feature commit: `ba7d165` (`feat: add read-only JAWL web memory bridge`).

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
- The optional JAWL web bridge reads existing `/api/agent/status`, `/api/tick`,
  `/api/db/stats`, `/api/drives` and `/api/config` routes, filters config
  secrets and exposes session-protected inspection routes to the browser.

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
- No Live2D model or runtime is present locally; the asset bridge is ready for
  a licensed user-supplied bundle but cannot prove real rendering yet.
- JAWL and VoiceMem use different Python environments and should remain
  separate services initially.
- JAWL's existing web console provides the stable read-only memory/heartbeat
  surface; no companion-side SQLite access or second durable memory store is
  warranted.
- A real JAWL web console smoke-test with its agent stopped answered all five
  upstream routes; the companion bridge then exposed the live Heartbeat,
  database counters, drives and filtered persona through its own API.
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
- add semantic screen significance scoring and connect `SCREEN_DELTA` to
  Attention/Presence and JAWL's final wording path;
- validate production VoiceMem audio model startup in its own environment and
  benchmark Russian ASR on a real microphone;
- validate CozyVoice model startup/latency and decide whether an actual
  streaming TTS worker is needed;
- choose the initial JAWL LLM endpoint/profile;
- decide whether local VLM runs through the existing QWB endpoint or a new
  local service;
- measure actual GPU contention and model residency on the target machine.

## Latest work session

Changed the passive watcher, web API/CLI wiring, vision deduplication,
E2E runner/tests and the related architecture/contracts/documentation in
`307da25`; extended the JAWL adapter path in `1f1717d`; recorded the
VoiceMem sidecar boundary in `91ffc50`; implemented the sidecar runner,
client and HTTP bridge in `a33f7b9`; added browser PCM16 microphone ingress
and final-turn routing in `36a808c`.
The current work session adds the TTS boundary and CozyVoice REST path plus
the optional Live2D asset/runtime bridge, then adds the read-only JAWL web
memory/persona bridge and its browser view. The follow-up validates real JAWL
payloads and applies a drive-field allow-list.

Verification for the current work session:
`scripts/run_e2e.ps1` passed 4 tests; `scripts/run_tests.ps1` passed 66 tests;
the stale-port degraded probe returned `status=offline`;
`git diff --check` reported no whitespace errors and no Python warnings; the
real JAWL web → adapter → companion API smoke-test also passed.
The working tree is clean after commit `751123f`; the preceding microphone
slice is preserved in `36a808c` and the TTS slice in `a217cec`.

Known limitation: no licensed Live2D model/runtime is installed yet; the
placeholder remains the default. The web server's default executor remains dry-run and no VLM
endpoint is configured by default; semantic significance scoring,
pixel-level redaction, JAWL/Attention consumption, ASR quality benchmarking,
AEC/barge-in, streaming TTS playback cancellation, OmniVoice and production
model warmup are still pending. The native always-on-top desktop-pet shell is
also deferred.

## Next action

Exercise the JAWL adapter against the actual local process, then benchmark
the installed VoiceMem ASR modes on a real Russian microphone and validate
production model warmup. Then benchmark CozyVoice latency and choose the
first user-supplied Live2D model. The bounded `SCREEN_DELTA` stream still
needs Attention/Presence consumption.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
