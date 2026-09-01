# Changelog

## Unreleased

- Added explicit ROOT-only unattended execution for background/heartbeat work:
  level 3 grants current-user capability, while the separate switch disables
  per-action prompts only after operator confirmation; emergency stop and
  deny-list checks remain authoritative.
- Added bounded Attention/Presence handling for screen deltas, DND/cooldown
  and explicit atomic delivery of salient `SPEAK_INTENT` events to JAWL's
  existing `.jawl_events` IPC boundary.
- Documented ambient secondary memory as separate, opt-in evidence with
  transient raw capture, delayed CPU/RAM triage and JAWL-owned promotion.
- Verified the companion event sink against JAWL's actual poller, EventBus and
  EventBridge in an isolated smoke; final model broadcast remains explicit
  `no_broadcast` when the active profile does not call the terminal skill.
- Added the first default-off ambient-memory runtime slice: bounded normalized
  audio/visual observations, privacy/TTL/byte limits, deterministic delayed
  coalescing, authenticated browser inspection and explicit enable/disable.
- Added a lazy, default-stopped `SystemAudioLoopback` boundary for an optional
  PyAudioWPatch-compatible Windows WASAPI backend with bounded in-memory PCM16
  delivery and degraded behavior when the backend is unavailable.
- Added a strict delayed ambient-triage provider contract and optional
  CPU-first Ollama JSON adapter; no audio model is selected or loaded by
  default, and Vision/VLM selection is explicitly deferred.
- Added an isolated `AmbientAudioASRBridge` with PCM16 downmix/resampling,
  sidecar chunk bounds and final-only ambient ingestion; the loopback-to-HTTP
  path is covered by E2E without creating a user turn.
- Added browser consent/status controls for ambient memory and explicit
  system-audio start/stop lifecycle.
- Added an optional Windows `system-audio` package extra and ambient readiness
  entries to the doctor report; installation and capture remain explicit.
- Added browser actions for explicit ambient triage and buffer clearing.
- Added local-time quiet-hours gating for proactive Attention/Presence and a
  browser setting for its `HH:MM-HH:MM` window.
- Created the isolated `JAWL-VoiceCompanion` development repository.
- Documented the JAWL/VoiceMem ownership boundary.
- Restricted the current avatar scope to 2D Live2D.
- Added initial architecture, contracts, research, decisions and state files.
- Accepted HostOS access levels 0–3, including an explicitly enabled full-user
  mode with backend policy enforcement.
- Selected a loopback browser application as the canonical control plane.
- Added the initial HostOS request/result contract and risk classes.
- Added a dependency-free Phase 1 text gateway, response validation, dry-run
  HostOS policy gate, audit metadata and loopback browser control surface.
- Added a JAWL loopback terminal adapter with mock fallback when the JAWL
  process is offline.
- Added the priority-aware `TurnArbiter` base for one active turn, stale work
  cancellation and queue promotion.
- Added the initial HostOS tool registry plus bounded filesystem/process/argv
  adapters, with dry-run as the default and path traversal protection.
- Added optional Windows UI Automation observation/control with bounded trees,
  opaque element references and stale-target rejection.
- Added a dependency-free browser adapter for bounded HTTP(S) navigation and
  UIA delegation, still protected by HostOS policy and approval.
- Exposed HostOS tool discovery and policy-checked dry-run execution through
  the local browser API.
- Added a server-side, session-bound, one-shot approval queue with TTL,
  fingerprints and redacted previews.
- Connected turn cancellation to the JAWL adapter through per-turn
  cancellation events and bounded socket reads.
- Added a read-only transparent `/avatar` presentation surface for desktop
  capture and OBS, plus a copyable URL in the control panel.
- Added an explicit, opt-in focused-window `screen.observe` adapter with
  bounded transient JPEG output and sensitive/companion window blocking.
- Added an OpenAI-compatible vision bridge, `/api/vision/look`, duplicate-frame
  suppression and a cooldown-aware browser vision control.
- Added an opt-in, arbiter-aware `SCREEN_DELTA` watcher with a bounded event
  endpoint and a real local-HTTP E2E suite covering chat, avatar, approvals,
  execution, emergency stop, screen vision and deduplication.
- Extended the E2E path through a local JAWL-compatible TCP terminal, covering
  the handshake and JSON-lines response before the result reaches HTTP state.
- Recorded the concrete VoiceMem `stream.feed_partial` sidecar contract and
  kept its heavyweight runtime outside the JAWL/web process boundary.
- Added the minimal VoiceMem JSON-lines runner, lazy subprocess client and
  authenticated `/api/voice/partial` bridge with UTF-8 transport framing.
- Added bounded browser microphone capture, mono PCM16 `/api/voice/audio`,
  `/api/voice/end` flushing and an E2E path proving audio → VoiceMem → JAWL →
  visible state; raw audio remains transient.
- Added a provider-neutral cancellable TTS service, bounded CozyVoice REST
  client, WAV sentence merge, `/api/tts/status`, `/api/tts/synthesize` and
  optional browser playback with a local-HTTP E2E check.
- Added an optional user-supplied Live2D asset root, read-only
  `/avatar-assets/` serving, `/api/avatar/config`, runtime adapter loading and
  placeholder fallback without committing SDK/model assets.
- Added a loopback-only, read-only JAWL web adapter for Heartbeat, persona,
  drive and memory counters; filtered config prevents secrets and no parallel
  durable memory store is created.
- Bounded JAWL drive summaries to an explicit field allow-list after validating
  the payload against the real local JAWL console.
- Added a session-protected HostOS audit view showing bounded metadata events;
  the browser never receives command arguments or raw execution output.
- Added backend Live2D model-reference validation for fatal Moc/texture files,
  explicit `ready`/warning diagnostics and a documented tiny renderer plugin
  contract, keeping Pixi/Cubism and character assets out of the core repo.
- Documented that JAWL's current terminal channel is broadcast-only, exposed
  the `no_broadcast` degraded status, and added a full-gate command requiring
  compile, unit, local HTTP E2E and diff verification for major changes.
- Added the correlated JAWL web-chat adapter: it holds the local SSE stream,
  acknowledges a user sequence through `/api/chat`, filters old messages and
  propagates cancellation/no-broadcast states through the visible HTTP health
  contract. The web adapter is now preferred over the legacy terminal path.
- Hardened the correlated SSE reader against the `http.client` close race and
  added a regression test. A live isolated JAWL/Ollama probe confirmed terminal
  input and model completion, while preserving `no_broadcast` when the model
  emits no user-facing terminal message.
- Added fail-closed hidden-thought/control-markup filtering to both JAWL chat
  transports, with HTTP E2E coverage for sanitization and upstream recovery.
- Added a bounded `/api/doctor` readiness report and browser panel for the
  text-only/degraded startup path, with unit and cross-layer E2E coverage.
