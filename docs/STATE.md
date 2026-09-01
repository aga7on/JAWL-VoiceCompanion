# Project State

Last updated: 2026-09-01

## Current phase

Phase 1 — contracts and text vertical slice (in progress).

Repository state: architecture baseline committed. A dependency-free mock
text/control slice is implemented; real JAWL, VoiceMem, audio, TTS, Live2D
and OS adapters are not connected.

## Git state

- Branch: `main`;
- Baseline commits: `abce27d` (initial workspace), `1820eec` (HostOS/web
  architecture), `81534b2` (Phase 1 mock vertical slice), `f33b417` (JAWL
  terminal adapter), `bc2f775` (TurnArbiter), `ad7e97f` (HostOS tools),
  `5fdd373` (web API), `bad96dc` (state baseline);
- Working tree: clean at the last verification.
- Latest feature commit: `0847a8f` (`feat: add transparent OBS avatar
  surface`).

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

## Reference inventory

- JAWL fork: `G:\AI\JAWL-Coding`;
- VoiceMem: `G:\AI\VoiceMem`;
- CozyVoice: `G:\AI\CozyVoice`;
- OmniVoice: `G:\AI\OmniVoice`;
- reference clones: `G:\AI\_tmp\companion-repos`.

## Known local observations

- VoiceMem has an external-ASR integration point through `feed_partial`.
- VoiceMem's current default streaming ASR should not be assumed to be the
  final Russian ASR choice; a benchmark is required.
- CozyVoice has a local REST wrapper, but its current `stream` path should be
  validated and likely corrected before latency-sensitive integration.
- The local OmniVoice directory currently does not expose a ready project/API
  layer; model and integration details must be confirmed before adapter work.
- JAWL and VoiceMem use different Python environments and should remain
  separate services initially.
- The JAWL `terminal.port` file currently exists, but its recorded port has no
  listening loopback socket; the new adapter therefore correctly uses its
  offline fallback until JAWL is started.

## Current blockers / decisions needed later

- Choose and benchmark Russian streaming ASR;
- confirm the OmniVoice model/API location;
- select the first redistributable or user-supplied Live2D model;
- finish the browser settings, memory and audit views;
- harden the initial HostOS session lifecycle and broaden audit coverage.
- choose the initial JAWL LLM endpoint/profile;
- decide whether local VLM runs through the existing QWB endpoint or a new
  local service;
- measure actual GPU contention and model residency on the target machine.

## Latest work session

Changed `frontend/index.html`, `frontend/avatar.html`, `src/jawl_voicecompanion/web.py`,
`tests/test_web.py`, `README.md`, `TODO.md`, `docs/OBS.md`, the architecture
ADRs and `CHANGELOG.md`.

Verification: `scripts/run_tests.ps1` passed 36 tests; `git diff --check`
reported no whitespace errors.

Known limitation: the avatar is a dependency-free placeholder, not a Live2D
model yet. The web server's default executor remains dry-run; coordinate/
canvas fallback, screen capture and TTS/audio cancellation are still pending.
The native always-on-top desktop-pet shell is also deferred.

## Next action

Exercise the JAWL adapter against the actual local process. Then implement the
bounded screen-capture/vision bridge and select the first Live2D asset/runtime.
TTS/audio cancellation remains required before the voice loop.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
