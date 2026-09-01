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

## ADR-004a — User activity is a low-privacy attention signal

Status: Accepted
Date: 2026-09-01

The optional Windows activity adapter reads only the time since the last user
input and the foreground window class. It does not capture keystrokes, window
titles, clipboard contents or input payloads. When enabled, recent activity
suppresses proactive screen speech; a sensor failure degrades to the existing
salience gate rather than disabling the companion.

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
## ADR-014 - JAWL remains the sole durable memory owner

Status: Accepted
Date: 2026-09-01

The companion reads JAWL's existing local web routes for process state,
Heartbeat, database counters, drives and a filtered persona configuration.
It does not open JAWL's SQLite/Vector/Graph stores and does not create a
parallel durable memory database. This keeps corrections, reflection and
forgetting in one authority and makes JAWL outages an explicit degraded mode.

The first bridge is read-only. Memory and persona writes require a versioned
JAWL API with provenance, audit and correction semantics before they can be
exposed in the companion UI.

## ADR-015 - Keep the Live2D renderer behind a tiny asset plugin

Status: Accepted
Date: 2026-09-01

The inspected Mana and Miru implementations converge on Pixi plus
`pixi-live2d-display` for browser rendering, while Warashi bundles a larger
application-specific Cubism frontend. We will not copy either frontend into
the companion. The avatar page accepts one small
`Live2DCompanionRuntime.create({canvas, modelUrl})` adapter, and the selected
runtime may load its own licensed Pixi/Cubism files from the explicit asset
root. Backend validation checks the model's fatal Moc/texture references and
the browser falls back to the dependency-free placeholder on failure.

This keeps the Python service lightweight, preserves the OBS URL and allows a
future renderer replacement without moving personality, memory, voice or
HostOS logic into the frontend.

## ADR-016 - Separate full-user capability from unattended operation

Status: Accepted
Date: 2026-09-01

`ROOT` (level 3) grants the tools the launched Windows account can perform;
it does not imply that the browser must confirm every action. A separate,
explicit `unattended` policy switch is enabled only after ROOT is selected.
This is the mode required for JAWL Heartbeat and background work while the
operator is away.

Unattended execution still passes through the same HostOS registry and policy
gate. Emergency stop, deny-tools, deny-risk classes and OS errors remain
authoritative. Downgrading below ROOT turns unattended mode off, and every
change is included in the bounded audit and approval policy fingerprint.

## ADR-017 - Opt-in native JAWL HostOS level bridge

Status: Accepted
Date: 2026-09-01

The companion does not duplicate JAWL's native HostOS SkillRegistry. When
`--jawl-hostos-control` is explicitly enabled with a JAWL console token, the
browser level selector writes only the allowlisted native `enabled` and
`access_level` fields, then calls JAWL's authenticated agent stop/start
routes. The local companion policy changes only after all three operations
succeed. In bridge mode, emergency stop also calls JAWL's authenticated agent
stop route, but this is explicitly a whole-agent stop rather than per-tool
cancellation. JAWL's native Heartbeat remains the autonomous caller;
companion unattended and approval state are not reported as native JAWL state
until JAWL exposes matching contracts.
The browser recovery action starts native JAWL before clearing the local
emergency-stop latch, so a failed native start leaves local execution blocked.

## ADR-018 - Bounded metadata-only audit persistence

Status: Accepted
Date: 2026-09-01

Companion policy and lifecycle events may be persisted as JSONL so autonomous
work remains inspectable after a process restart. The audit writer applies a
fixed size limit and an allow-list of metadata fields; command arguments, raw
tool results, screenshots, credentials and hidden reasoning are excluded at
the persistence boundary. This is an operational audit, not a second memory
store for the character.

## ADR-019 - Keep TTS orchestration model-neutral

Status: Accepted
Date: 2026-09-01

The companion keeps TTS models behind the existing provider interface so the
operator can benchmark and replace OmniVoice, CozyVoice or another local
provider without changing chat, cancellation, avatar or browser contracts.
The current REST adapter may synthesize up to three sentence chunks in
parallel, then merges them in source order. This reduces total synthesis time
without exposing provider-specific state or committing to a model before the
external benchmark is complete.

The HTTP endpoint still returns one bounded WAV, so this decision does not
claim first-audio streaming. Streaming playback, barge-in and the final model
choice remain separate validation work.

## ADR-020 - Keep the desktop pet as a presentation shell

Status: Accepted
Date: 2026-09-01

The optional desktop pet is a small Windows launcher around the existing
read-only `/avatar` browser surface. It may pin the app window above other
windows, but it does not own state, credentials, policy or Live2D rendering.
OBS uses the same surface directly for transparency. This keeps the core
lightweight and avoids introducing a second native UI runtime before a real
Live2D bundle and compositing requirements are validated.

## ADR-021 - Use Qwen3-VL-2B as the primary local Vision profile

Status: Accepted
Date: 2026-09-01

The operator's CPU/RAM benchmark selected Qwen3-VL-2B Q4_K_M with the
matching F16 mmproj as the first Vision profile. It produced the best overall
and UI-automation results in the supplied comparison while remaining within
the target CPU/RAM envelope. SmolVLM2-500M remains the low-latency fallback
when response time matters more than video/UI quality.

The model weights are user-owned files outside this repository and are not
copied or redistributed by the project. The integration target is a local
loopback `llama-server` OpenAI-compatible endpoint. Full-resolution screen
capture must remain bounded because the benchmark showed materially higher
latency; resizing, UIA structure and calibrated coordinates remain part of
the screen tool contract. This decision does not select a TTS or ASR model.
