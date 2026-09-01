# TODO — JAWL VoiceCompanion

Legend: `[ ]` pending, `[~]` in progress, `[x]` verified complete, `[!]`
blocked or requiring a decision.

## Phase 0 — foundation

- [x] Create an isolated development repository.
- [x] Write agent/contributor rules in `AGENTS.md`.
- [x] Record repository research and license constraints.
- [x] Define the initial architecture and ownership boundaries.
- [x] Limit the avatar target to 2D Live2D.
- [x] Add the first implementation branch and test runner.
- [x] Decide the project Python package name and service entry points.

## Phase 1 — contracts and text vertical slice

- [x] Define versioned event schemas.
- [x] Define `ResponseEnvelope` validation.
- [~] Implement a local JAWL gateway with health and graceful failure; the web
  POST+SSE correlation bridge is implemented, while live production-model
  validation and reconnect/recovery hardening remain.
- [x] Implement `TurnArbiter` with user/proactive/background priority lanes.
- [~] Add generation IDs and cancellation propagation (JAWL transport is
  covered; TTS/audio cancellation remains).
- [x] Connect a minimal text chat to a mock avatar frontend.
- [x] Serve the first local browser control plane for chat, status and
  reconnect recovery.
- [x] Add a first adapter for JAWL's loopback HostTerminalClient protocol.
- [~] Render `idle`, `listening`, `thinking`, `speaking` and emotion states;
  the response contract and OBS surface currently cover the basic state path.
- [x] Add structured metadata-only JSONL logs without secrets, tool arguments
  or hidden chain-of-thought; the CLI stores bounded events in runtime.

Acceptance criteria:

- A text turn reaches JAWL and returns a validated envelope.
- A newer user turn cancels the older response.
- The frontend can reconnect and recover visible state.
- No audio, model weights or credentials are required to run tests.

## Phase 2 — Russian voice loop

- [x] Implement the bounded browser microphone input adapter and PCM16 sidecar path.
- [x] Benchmark Russian ASR candidates; the external CPU/RAM comparison
  selected Qwen3-ASR-0.6B, while live microphone integration remains.
- [x] Add the bounded Qwen3-ASR final-utterance adapter through the local
  `/v1/audio/transcriptions` contract; streaming Qwen partial ASR remains a
  separate task.
- [x] Connect external streaming ASR partials to the VoiceMem sidecar
  `feed_partial` contract.
- [x] Deliver the VoiceMem final transcript through the JAWL user-turn gateway.
- [x] Implement the bounded CozyVoice 2 REST adapter.
- [~] Inspect and fix the local CozyVoice wrapper's non-streaming behavior;
  the companion calls one sentence per request and merges compatible WAV
  chunks, while upstream wrapper streaming remains unverified.
- [!] Add OmniVoice adapter when its model/API location is confirmed; the local
  `G:\AI\OmniVoice` directory currently contains only a virtual environment.
- [x] Implement bounded sentence chunking for TTS.
- [x] Add hidden-thought filtering before user text reaches the envelope,
  subtitle or TTS boundary.
- [~] Implement ordered parallel TTS queue; the model-neutral CozyVoice REST
  adapter now runs up to three sentence requests concurrently and merges WAV
  chunks in source order. First-audio streaming remains pending.
- [~] Implement latest-request-wins synthesis cancellation; the browser now
  aborts playback/request and calls the explicit cancel route, while barge-in
  integration remains.
- [ ] Add half-duplex hands-free mode.
- [ ] Add a true streaming Qwen3-ASR partial provider if a stable streaming
  contract is confirmed; do not infer it from the batch transcription API.
- [~] Add barge-in capture and interruption classification; browser RMS
  activity now cancels active speech/generation once, while VoiceMem-based
  classification and full half-duplex behavior remain.
- [ ] Benchmark first-audio latency and Russian prosody.

Acceptance criteria:

- Russian speech is transcribed reliably in a quiet room and normal desktop
  conditions.
- The first sentence starts playing before the entire reply is synthesized.
- Talking over the character stops playback and does not lose the new turn.
- TTS failure leaves a usable text-only mode.

## Phase 3 — VoiceMem sidecar and memory

- [x] Define a transport-neutral VoiceMem sidecar contract.
- [~] Run VoiceMem as a separate local service; the stdio runner, process
  client and `/api/voice/partial` bridge are present, while real model startup
  remains opt-in.
- [x] Add request/session correlation IDs to the sidecar protocol.
- [x] Add the bounded JSON-lines runner and degraded-mode responses.
- [x] Harden sidecar lifecycle: empty audio flushes do not initialize VoiceMem,
  failed streams are evicted for recovery, and bounded process state is exposed.
- [ ] Add speculative recall and final recall events.
- [ ] Map VoiceMem affect to JAWL observations, not personality overrides.
- [~] Add opt-in Windows system-audio loopback as a separate ambient stream;
  the lazy PyAudioWPatch-compatible adapter and bounded PCM callback are
  implemented, and the isolated ASR consumer/downmix path is covered by E2E;
  installation, permission wiring and live startup remain. Never mix it with
  microphone `USER_FINAL` turns.
- [~] Add a bounded ambient working buffer with configurable TTL (initial
  target: about 30 minutes) and no durable raw audio/video by default; the
  normalized buffer and authenticated browser controls are implemented, while
  real capture wiring remains.
- [~] Define the deferred CPU/RAM triage contract for ambient audio text;
  strict provider validation, an opt-in Ollama adapter and the benchmark
  protocol are present. Worker scheduling and model selection remain pending.
- [~] Add deterministic importance filtering and coalescing into bounded
  ambient episodes; model-based triage remains separate.
- [~] Add provenance, source-app, confidence and retention metadata to ambient
  observations and episode candidates.
- [ ] Define bounded core memory.
- [x] Add a read-only JAWL bridge for bounded memory/persona inspection.
- [!] Add JAWL trait/fact write bridge only after upstream exposes a versioned
  HTTP/event contract; the current web console has no trait/fact CRUD route.
- [ ] Define archival recall through JAWL Vector/Graph.
- [ ] Add fact provenance, confidence and epistemic type.
- [ ] Add `insert`, `patch`, `remove`, `archive` and `supersedes` operations.
- [ ] Preserve correction history and valid-time fields.
- [ ] Add background Sleep/Reflection/Consolidation jobs.
- [ ] Add memory editor and forget controls.
- [ ] Add tests against hallucinated or unattributed memory writes.

Acceptance criteria:

- The same fact does not create uncontrolled duplicates.
- A correction invalidates the old value without destroying its history.
- Core prompt memory stays under a configured hard limit.
- VoiceMem outage degrades to JAWL text memory without crashing chat.

## Phase 4 — 2D Live2D product UI

- [~] Select a redistributable Live2D model or document user-supplied assets;
  the asset-root contract and fatal Moc/texture validation are implemented,
  while a model/license choice is still pending.
- [x] Add a transparent browser avatar surface and a copyable OBS URL.
- [~] Replace the dependency-free avatar placeholder with the Live2D runtime;
  optional runtime/model loading, validation and fallback are implemented, but
  no licensed model/runtime is installed yet.
- [~] Add a native always-on-top desktop-pet window around the shared surface;
  `scripts/run_avatar_window.ps1` provides a bounded Edge/Chrome `--app`
  launcher, while true transparent compositing remains pending.
- [ ] Implement transparent desktop-pet mode.
- [~] Add settings for persona, voice, memory, proactivity and privacy;
  provider-neutral TTS voice/speed controls are now present, while durable
  persona/memory/privacy settings remain tied to their owning services.
- [~] Add visible listening/screen-observation indicators; the browser now
  exposes ambient-memory consent and system-audio loopback state, while the
  native pet indicator and full screen-capture status remain.
- [ ] Add lip-sync from audio amplitude.
- [~] Add expression capability mapping and fallbacks; bounded semantic
  mapping and neutral fallback are implemented, while runtime capability
  discovery remains.
- [x] Add first-run setup and component health/doctor panel; the bounded
  `/api/doctor` report and browser rendering are present.
- [ ] Add performance profiles for low/standard/high modes.
- [~] Render browser control-plane pages for settings, approvals, memory and
  audit state; chat, approvals, level, emergency stop and a read-only JAWL
  memory/persona summary are present, while editing views remain.
- [x] Add visible HostOS access-level indicator and emergency stop.

Acceptance criteria:

- The avatar stays responsive while backend work is running.
- Every model emotion maps to a valid 2D expression or neutral fallback.
- The app explains missing services and offers text-only degraded mode.

## Phase 5 — screen vision

- [~] Implement focused-window capture on Windows; the explicit one-shot
  `screen.observe` adapter is present and disabled by default, with a
  benchmark-oriented 960×720/1 MB profile and coordinate-scale metadata.
- [ ] Prefer UI Automation for native app structure.
- [ ] Add screenshot/OCR fallback for canvas and custom applications.
- [x] Add explicit `vision__look` model tool; the HostOS `screen.observe`
  capture seam and Qwen3-VL-2B local `llama-server` path are smoke-tested.
  SmolVLM2-500M remains the speed fallback; continuous watcher tuning remains.
- [ ] Add capture request/response bridge when frontend owns capture.
- [~] Add change detection, significance and cooldown; digest deduplication,
  explicit-look cooldown, bounded `SCREEN_DELTA` production and an
  Attention/Presence `SPEAK_INTENT` gate are implemented. Explicit JAWL event
  IPC is available, while production Heartbeat/final-wording validation remains.
- [~] Add app deny-list and sensitive-window redaction policy; title/class
  blocking is present, while pixel-level redaction remains pending.
- [x] Discard raw screenshots after analysis by default.
- [~] Store only bounded textual observations and metadata; the explicit bridge
  and passive producer keep only an in-memory digest, event ring and bounded
  last description.
- [~] Add opt-in ambient video/keyframe observations for secondary memory; the
  normalized visual event/buffer path is present, while real keyframe capture
  remains separate from explicit `vision__look` and proactive speech.

Acceptance criteria:

- Screen observation is opt-in and visibly indicated.
- No VLM request occurs for an unchanged screen unless explicitly requested.
- The avatar does not capture its own window.
- Raw screenshots are not stored in durable memory by default.

## Phase 6 — presence and autonomy

- [~] Implement Attention/Presence Engine; bounded screen events now pass
  through salience, privacy, DND, cooldown and budget gates.
- [x] Add salience levels and coalescing.
- [~] Add proactive cooldowns and quiet hours; manual DND, cooldown and a
  validated local-time window are implemented, while user activity/focus
  signals remain.
- [~] Add `SPEAK_INTENT` and JAWL final wording path; explicit `.jawl_events`
  IPC is implemented, while production Heartbeat/final-wording validation
  remains.
- [~] Add user activity/focus/fatigue signals; the opt-in Windows idle/focus
  adapter and proactive suppression path are implemented, while fatigue and
  richer focus classification remain.
- [ ] Add optional daily journal and commitments.
- [ ] Add gaming mode and resource backoff.
- [x] Add a user-adjustable proactivity budget.

Quality gate:

- [x] Add a real local-HTTP E2E suite for cross-layer user paths and make it
  mandatory for major updates.
- [x] Add one full-gate command that runs compile, unit, E2E and diff checks.
- [x] Add a launch-time port conflict check with an actionable alternate-port
  message for local WebSocket/HTTP collisions.

Acceptance criteria:

- The character can remain silent when the user is focused.
- Proactive speech never bypasses DND or the Turn Arbiter.
- Repeated screen frames cannot produce repeated interruptions.
- All proactive decisions are inspectable in the event log.

## Phase 7 — tools and hardening

- [x] Add HostOS access levels 0 `SANDBOX`, 1 `OBSERVER`, 2 `OPERATOR`, 3
  `ROOT`.
- [x] Route initial filesystem/process/shell tool descriptors through one
  backend policy gate.
- [x] Implement initial Windows UI Automation observation with stale element
  checks.
- [~] Implement bounded keyboard/mouse/window control and browser actions;
  initial UIA control and browser navigation adapters are present.
- [x] Add bounded browser URL actions and UIA delegation behind `browser.act`.
- [~] Add level-change events, session tokens and emergency stop; the loopback
  path now cancels tracked managed/shell processes, while broader session
  lifecycle hardening remains.
- [x] Add risk classes and per-class confirmation/deny-list policy, including
  an explicit ROOT-only unattended mode for heartbeat/background work.
- [x] Add exact approval fingerprints for commands and high-risk actions.
- [~] Create one tool policy for JAWL, MCP, desktop and browser tools; the
  level and whole-agent emergency-stop bridge are implemented; native
  unattended and per-tool approval state remain separate.
- [x] Native JAWL level bridge: browser level 0-3 writes the allowlisted
  config, restarts the agent and updates the companion policy after success.
- [~] Add native JAWL contracts for unattended/approval state and emergency
  stop; bridge stop/reset now controls the native whole-agent lifecycle, while
  per-tool cancellation and native approval state still need an upstream
  contract.
- [x] Add server-side one-shot approval queue with exact request/policy
  fingerprints and allow-once/deny decisions.
- [x] Add browser review and one-click execution for approved in-memory
  proposals; reviews are bounded/redacted and the exact request is discarded
  after one execution.
- [~] Add unified tool-call audit log with secret redaction; metadata-only
  policy events are now visible in the browser and optionally persistent,
  while native JAWL event coverage remains separate.
- [ ] Add bounded tool-result compression.
- [~] Add workspace-scoped edit proposals with stale-file checks; conditional
  writes now reject a changed file; a broader diff/transaction editor remains.
- [x] Add restart/recovery tests to the full E2E gate; server shutdown now
  cleans owned processes and a fresh server starts at safe defaults.
- [ ] Add packaging and installation documentation.

## Deferred

- [ ] 3D/VRM avatar — deliberately excluded from current scope.
- [ ] Mobile clients and multi-device sync.
- [ ] Full continuous raw system-audio/video recording — deliberately deferred;
  only bounded, opt-in ambient observations are planned in Phases 3 and 5.
- [ ] Complex swarm behavior.
- [ ] Cloud deployment.
