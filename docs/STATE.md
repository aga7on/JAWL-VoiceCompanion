# Project State

Last updated: 2026-08-31

## Current phase

Phase 1 — contracts and text vertical slice (in progress).

Repository state: architecture baseline committed. A dependency-free mock
text/control slice is implemented; real JAWL, VoiceMem, audio, TTS, Live2D
and OS adapters are not connected.

## Git state

- Branch: `main`;
- Baseline commits: `abce27d` (initial workspace), `1820eec` (HostOS/web
  architecture), `81534b2` (Phase 1 mock vertical slice);
- Working tree: clean at the last verification.

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

## Current blockers / decisions needed later

- Choose and benchmark Russian streaming ASR;
- confirm the OmniVoice model/API location;
- select the first redistributable or user-supplied Live2D model;
- decide the first web stack and local session-token mechanism;
- define the initial HostOS tool registry and risk policy defaults.
- choose the initial JAWL LLM endpoint/profile;
- decide whether local VLM runs through the existing QWB endpoint or a new
  local service;
- measure actual GPU contention and model residency on the target machine.

## Latest work session

Changed `pyproject.toml`, `src/jawl_voicecompanion/`, `frontend/index.html`,
`tests/` and `scripts/run_tests.ps1`/`scripts/run_web.ps1`.

Verification: `scripts/run_tests.ps1` passed 14 tests; `git diff --check`
reported no whitespace errors.

Known limitation: the web surface is intentionally local and the HostOS
executor is dry-run only. It does not yet launch applications, send input,
execute commands or connect to JAWL.

## Next action

Connect the text gateway to the real JAWL process behind an adapter, preserve
the existing envelope and add cancellation/priority behavior. Do not download
model weights or implement passive screen monitoring yet.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
