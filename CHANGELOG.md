# Changelog

## Unreleased

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
