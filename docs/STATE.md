# Project State

Last updated: 2026-08-31

## Current phase

Phase 0 — foundation and architecture.

Repository state: initial scaffold committed. Runtime code has not been
integrated. HostOS access policy and browser control-plane design are now
documented; implementation has not started.

## Git state

- Branch: `main`;
- Initial commit: `abce27d` (`chore: initialize companion development
  workspace`);
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

## Next action

Create the Phase 1 project contracts, browser chat/status surface and a
minimal health-check/test harness. Do not download model weights or implement
passive screen monitoring yet.

## State update protocol

Every work session must update this file with:

1. active phase;
2. files or services changed;
3. verification performed;
4. known failures or blockers;
5. next concrete action;
6. git commit or uncommitted status.
