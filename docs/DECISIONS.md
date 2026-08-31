# Architecture Decisions

## ADR-001 — JAWL is the canonical cognitive core

Status: Accepted
Date: 2026-08-31

JAWL owns personality, traits, mental states, drives, Heartbeat, ReAct,
structured memory, goals and tool decisions. It already provides the closest
match to the desired autonomous lifecycle.

VoiceMem observations may influence JAWL but do not independently define the
character.

## ADR-002 — VoiceMem runs as a sidecar

Status: Accepted
Date: 2026-08-31

VoiceMem is isolated behind a local API because it owns streaming audio and
may require different Python/PyTorch dependencies. This also allows ASR and
voice models to be replaced without rewriting JAWL.

## ADR-003 — 2D Live2D only for the current product

Status: Accepted
Date: 2026-08-31

The first avatar target is 2D Live2D. VRM/3D is deferred indefinitely until
the text, voice, memory and presence contracts are stable. This reduces
rendering, asset, animation and integration risk.

## ADR-004 — Attention is separate from deep reasoning

Status: Accepted
Date: 2026-08-31

A lightweight Attention/Presence Engine handles salience, coalescing and
cooldowns. JAWL Heartbeat/ReAct handles durable thought and final wording.
This prevents screen sensors and timers from launching expensive full-agent
cycles.

## ADR-005 — Separate service processes initially

Status: Accepted
Date: 2026-08-31

JAWL, VoiceMem, TTS and the avatar frontend communicate over loopback APIs.
This limits dependency conflicts, isolates model crashes and allows later
replacement of components. A monolithic process may be considered only after
the contracts are tested.

## ADR-006 — Bounded, auditable memory

Status: Accepted
Date: 2026-08-31

Memory is split into a small always-in-context layer and larger retrieved
archives. Facts have lifecycle, provenance, confidence and correction
history. Users can inspect, edit and forget them.

## ADR-007 — Privacy-first screen awareness

Status: Accepted
Date: 2026-08-31

Screen vision is opt-in, focused-window-first and rate-limited. Raw frames are
discarded by default. Descriptions are treated as untrusted input and pass
through prompt-injection-safe context formatting.

## ADR-008 — Reference projects are patterns, not a second runtime

Status: Accepted
Date: 2026-08-31

Open-LLM-VTuber, Warashi, Miru, Mana, AniCompanion and Soul of Waifu are used
for design and implementation patterns. Their complete runtimes are not
combined with JAWL. Direct Soul of Waifu code reuse is excluded until GPL-3.0
compatibility is deliberately accepted and reviewed.

## ADR-009 — HostOS levels are a first-class product capability

Status: Accepted
Date: 2026-08-31

The companion supports the same four conceptual HostOS levels as the local
JAWL fork: `SANDBOX` (0), `OBSERVER` (1), `OPERATOR` (2) and `ROOT` (3).
Full access is therefore a supported expert mode, not an accidental loophole
or a promise that the agent is always unrestricted.

The backend enforces the level on every tool call. The browser UI can select a
level and display its status but cannot authorize an operation by itself. A
level change creates an auditable policy event and updates the visible mode
indicator. Risk-specific confirmations, deny-lists, emergency stop and
bounded results remain available at every level.

Level 3 grants the rights available to the current Windows user, including
filesystem, GUI and shell operations; it does not bypass Windows elevation or
the secure desktop. The implementation must preserve the HostOS properties of
path-bound checks, stale-target rejection for UI controls, bounded output,
process-tree cancellation and approval fingerprints where applicable.

## ADR-010 — Browser is the canonical control plane

Status: Accepted
Date: 2026-08-31

The main settings, chat, approval, memory, health and audit experience is a
local web application served by the companion backend. This reduces frontend
duplication and makes the operator state inspectable in one place. The Live2D
renderer can run in that web UI or in a transparent desktop-pet presentation
mode while consuming the same backend events.

The service binds to loopback by default. WebSocket origin checks, session
tokens, CSRF protection for state-changing HTTP requests and a backend policy
gate are required before exposing any control operation. Remote access is
deferred and must be designed as a separate authenticated deployment.
