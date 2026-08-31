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
