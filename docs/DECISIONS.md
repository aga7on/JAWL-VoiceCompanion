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

## ADR-011 — Separate read-only avatar surface for desktop and OBS

Status: Accepted
Date: 2026-09-01

The companion exposes `/avatar` as a dedicated transparent browser surface.
The operator panel remains at `/`; both surfaces consume the same backend
state, while only the operator panel exposes state-changing controls. This
keeps OBS and desktop-pet presentation independent from the control-plane
layout and prevents an OBS source from becoming an authorization boundary.

The first implementation is a dependency-free placeholder that polls the
bounded `/api/state` endpoint at a short interval. It is intentionally not a
Live2D runtime yet. A later Live2D renderer will replace the placeholder in
the same route and will use response-envelope avatar state, expression and
subtitle fields. Native always-on-top window chrome is deferred until the web
surface and Live2D lifecycle are stable.

## ADR-012 — Provider-neutral explicit vision bridge

Status: Accepted
Date: 2026-09-01

Screen descriptions use a small provider-neutral bridge rather than importing
JAWL's internal multimodality implementation. The bridge accepts an
OpenAI-compatible chat-completions endpoint and sends a bounded transient
`image_url` payload. This matches the multimodal contract already used by the
local JAWL/QWB path while keeping credentials, model selection and failure
handling local to the companion adapter.

The bridge is reachable through an explicit web request and through the
opt-in `ScreenDeltaWatcher`. Both paths deduplicate identical frames and
apply a cooldown before a new description. The watcher is arbiter-aware and
publishes only bounded `SCREEN_DELTA` events; it does not speak or call JAWL.
No image, title or raw provider response is stored; only a short in-memory
digest, bounded last description and bounded event ring are retained. Future
salience and speech decisions must still pass the same HostOS permission,
deny-list and resource-budget gates.

## ADR-013 — User-supplied Live2D assets behind a read-only asset root

Status: Accepted
Date: 2026-09-01

The repository does not include a Cubism runtime, Core binary, model, texture
or character asset. The operator may provide a directory containing a bundled
runtime and a `model3.json` tree through `--live2d-assets`. The backend serves
only files resolved below that root through `/avatar-assets/`, with traversal,
symlink escape and size checks.

`/avatar` loads the optional runtime only when both runtime and model are
present and the runtime exposes the small `Live2DCompanionRuntime.create`
adapter. The adapter receives `{canvas, modelUrl}` and may implement
`setExpression`, `setMotion`, `setLipSync` and `destroy`. If loading fails,
the existing dependency-free placeholder remains visible. This preserves the
OBS URL, keeps the web process free of heavy SDK dependencies and avoids
redistributing assets with unclear terms.
