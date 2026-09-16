# Architecture Decisions

Product clarification: 2026-09-05. These decisions describe intent, not live
readiness. [PRODUCT.md](PRODUCT.md) is the current product specification;
[STATE.md](STATE.md) records implemented/verified limits. Later clarifications
below supersede older conflicting descriptions, not the user's original goal.


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

The companion exposes `/avatar` on a dedicated loopback presentation server.
The operator panel remains at `/`; both surfaces consume the same bounded
state, while only the operator panel exposes state-changing controls. This
keeps OBS and desktop-pet presentation independent from the control-plane
layout and prevents an OBS source from becoming an authorization boundary.

The first implementation is a dependency-free placeholder that polls only
`/api/presentation/state`. An optional user-owned Live2D renderer replaces the
placeholder behind the same tiny adapter. The configuration reports runtime
capabilities and the browser maps unsupported expressions/motions to a
neutral fallback. Native always-on-top window chrome is available through the
bounded launcher; transparency, click-through and long soak remain live
acceptance items.

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

Canonical structured-memory reads and mutations now use JAWL's versioned
`/api/memory` route and allowlisted `memory.*` control actions. Records carry
provenance, source, confidence and append-only correction semantics. The
Companion may present and request an edit, but JAWL remains the only writer.

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

## ADR-017 - Opt-in native JAWL HostOS and skill bridge

Status: Accepted
Date: 2026-09-01

The companion does not duplicate JAWL's native HostOS SkillRegistry. When
`--jawl-hostos-control` is explicitly enabled with a JAWL console token, the
browser level selector writes only the allowlisted native `enabled` and
`access_level` fields, then calls JAWL's authenticated agent stop/start
routes. Native HostOS/HostTerminal skills and structured-memory mutations are
also proxied through JAWL's authenticated control routes. The local companion
fallback executor is not used for those model-originated operations in bridge
mode.

The local policy changes only after the native operation succeeds. Emergency
stop also calls JAWL's authenticated stop route while cancelling
Companion-owned work locally; this is a whole-agent native stop, not a claim
of per-tool cancellation. The browser recovery action starts native JAWL
before clearing the local emergency-stop latch, so a failed native start
leaves local execution blocked.

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

The compatibility synthesize endpoint returns a bounded WAV. Companion now
also offers sentence-level NDJSON/WebAudio streaming, but its Tera/Qwen workers
still generate whole-WAV requests. Transport cancellation is not guaranteed
inference cancellation; first audible and worker release require acceptance.
Model preference is clarified by ADR-032.

## ADR-020 - Keep the desktop pet as a presentation shell

Status: Accepted
Date: 2026-09-01

The optional desktop pet is a small Windows launcher around the existing
read-only `/avatar` browser surface. It may pin the app window above other
windows, but it does not own state, credentials, policy or Live2D rendering.
OBS uses the same surface directly for transparency. This keeps the core
lightweight and avoids introducing a second native UI runtime before a real
Live2D bundle and compositing requirements are validated.

## ADR-021 - Benchmark Qwen3-VL-2B as a Vision candidate

Status: Superseded by explicit deferral
Date: 2026-09-01

The operator's CPU/RAM benchmark identified Qwen3-VL-2B Q4_K_M with the
matching F16 mmproj as the strongest current candidate for overall/UI quality,
with SmolVLM2-500M as a low-latency candidate. The operator explicitly
deferred selecting a permanent VLM until the remaining CPU/RAM and integration
testing is complete.

The model weights are user-owned files outside this repository and are not
copied or redistributed by the project. If a candidate is selected later, the integration target is a local
loopback `llama-server` OpenAI-compatible endpoint. Full-resolution screen
capture must remain bounded because the benchmark showed materially higher
latency; resizing, UIA structure and calibrated coordinates remain part of
the screen tool contract. This decision does not select a TTS or ASR model.

## ADR-022 - Bound screen frames before Vision inference

Status: Accepted
Date: 2026-09-01

The default focused-window capture is limited to 960×720 and a 1 MB JPEG.
This matches the supplied CPU benchmark's practical 640–960px range and
prevents the screen watcher from repeatedly spending the full-resolution
latency budget. Operators may widen or tighten the profile explicitly through
CLI flags.

Because a resized image is not in the same coordinate system as the original
window, `screen.observe` returns only bounded `coordinate_scale` metadata.
Any future UI action must map coordinates back to the original window and then
pass the normal stale-target, risk and approval gates; the metadata is never
an authorization signal.

## ADR-023 - Keep provider experiments outside the JAWL ownership boundary

Status: Accepted
Date: 2026-09-01

JAWL remains the canonical conversation brain: persona, durable memory,
Heartbeat and native autonomy are not duplicated in the Companion. A direct
OpenAI-compatible chat adapter is allowed only as a temporary model/provider
test path selected through CLI arguments and an environment-held API key. It
does not claim JAWL state and is mutually exclusive with the JAWL transport
adapters.

This keeps TokenRouter, a future local LLM, or another provider replaceable.
Once a model is selected for regular operation, it should be configured in
JAWL's own provider path rather than making the Companion a second brain.

## ADR-024 - Add Qwen3-ASR as an explicit final-utterance option

Status: Accepted
Date: 2026-09-01

The supplied CPU/RAM benchmark selects Qwen3-ASR-0.6B as the current audio
candidate. The local `llama-server` endpoint was verified with multipart
`/v1/audio/transcriptions`, but that endpoint does not establish a streaming
partial-ASR contract. Therefore the Companion keeps VoiceMem's streaming path
as the default and adds Qwen only as an opt-in, bounded final-utterance
adapter. Audio is held in RAM for one short session, transcribed once on
explicit end and discarded after ASR. Companion adapts the final text into
one immediate JAWL VOICE_TURN and asynchronously queues the same text for
VoiceMem enrichment, without waiting for the sidecar or emitting a second turn.

## ADR-025 - Keep pixel actions separate from semantic UIA actions

Status: Accepted
Date: 2026-09-01

Native controls continue to use UI Automation references and fingerprints.
Canvas, games and custom-rendered surfaces use a separate `desktop.pointer`
tool whose image-space coordinates must carry frame dimensions and exact
foreground bounds. HostOS rechecks the foreground window before conversion,
uses the normal interactive approval/unattended policy, and reports pointer
dispatch separately from application acceptance. This avoids pretending that
a cursor event proves a UI state transition.

## ADR-026 - Make JAWL the single model-action policy authority

Status: Accepted
Date: 2026-09-02

The existing Companion `HostOSPolicy`/`HostOSExecutor` and JAWL native HostOS
cannot remain independent production authorities. JAWL owns every
model-originated tool decision and exposes versioned policy, approval, audit,
cancellation and emergency-stop state to Companion. Companion becomes the
operator/control UI and may retain only bounded operations intrinsically owned
by that control plane.

This authority includes Debug Broker. Its seven stable skills and all dynamic
provider operations remain native to JAWL and receive canonical risk/minimum-
level metadata. Companion must not reimplement, filter or bypass the catalog.
At ROOT, every operation available to the launched Windows account remains
reachable subject to the same policy and real OS/provider/EULA constraints.

## ADR-027 - Isolate control and avatar presentation capabilities

Status: Accepted
Date: 2026-09-02

A page is not read-only merely because it has no controls. Same-origin
JavaScript can call the origin's APIs, and the current public session bootstrap
means user-supplied Live2D code cannot share the privileged control origin.

The production UI therefore separates a session/CSRF-protected control origin
from a minimal presentation origin or capability channel. Avatar/OBS receives
only expression, motion, subtitle and short-lived audio-amplitude events. It
does not receive session material, approvals, HostOS state or conversation
history. Non-loopback binding is rejected until a separately designed remote
authentication mode exists.

## ADR-028 - Explicit unattended authorization and crash recovery

Status: Clarified 2026-09-05 (implementation uses a bounded ROOT lease)
Date: 2026-09-02

The required outcome is overnight unattended work, including recovery from a
worker crash within the user's authorized period. ROOT capability and unattended
authorization are distinct; neither means asking for every allowed action.
Emergency stop, explicit exclusions and OS constraints stay authoritative.

The current implementation persists an expiring, revocable lease atomically.
Recovery is allowed only while the lease and level-3 policy remain valid;
pending one-shot approvals do not survive restart. Exact duration, renewal UX
and chosen profile are implementation decisions still to be accepted. A lease
must visibly cover the requested work period, not unexpectedly end overnight.
The model cannot authorize its own renewal; any unattended renewal policy would
need separate operator configuration.

Task checkpoints/outcomes must survive independently of one-shot approvals.
After a crash, reconcile uncertain effects before resuming; event replay is not
permission to repeat mutations. Target-machine recovery evidence remains open.

## ADR-029 - Name the evidence level of every quality claim

Status: Accepted
Date: 2026-09-02

The project distinguishes unit, fake-provider HTTP E2E, synthetic media, live
provider and live target-hardware evidence. `scripts/run_full_gate.ps1` is a
required regression gate but currently uses fake providers and is not a release
certification. A production claim requires the applicable browser, JAWL,
voice, TTS, Vision, HostOS, Debug Broker, memory and soak profiles listed in
`TECHNICAL_AUDIT.md`.

## ADR-030 - Grant remote-provider consent per data class

Status: Accepted
Date: 2026-09-02

An explicitly configured remote text LLM inside JAWL does not imply consent to
send microphone audio, system audio, screenshots or ambient observations to a
remote service. ASR, TTS, Vision and ambient processing remain local by
default, each with a separate future opt-in if remote processing is desired.

## ADR-031 - One companion product, protected reference repositories

Status: Accepted clarification
Date: 2026-09-05

JAWL, Companion and VoiceMem are one user's application with one persona,
memory and agentic task lifecycle. Process boundaries isolate dependencies,
not product ownership or separate "brains". The main experience is a mint Aero
2D scene, dialogue and tasks, with clear settings; diagnostic pages are secondary.

Existing external JAWL changes must be inventoried, not silently edited,
reset or treated as a shipped dependency. A compatible pinned runtime needs
its own configuration/data/logs/cache. Selecting/copying an owned fork is still
pending agreement; the protected JAWL-Coding tree remains read-only even for
test-produced state. See TODO P0-A.

## ADR-032 - Preserve the user's model preference and memory direction

Status: Accepted clarification; integration incomplete
Date: 2026-09-05

Qwen3-TTS 0.6B is the desired primary, with TeraTTSv2 alongside as the explicit
fast CPU fallback. Current CLI default Tera and slow Qwen Base clone are facts,
not a change to the user's preference. Capability reporting, emotional speech,
cancellation and automatic failover require separate evidence.

Qwen3-ASR is final speech ASR, not music/sound/affect analysis. Vision remains
deferred pending the owner's model decision. Big Pickle is a temporary JAWL
test provider; later local/QWB replacement preserves JAWL JSON/tool contracts.

Ambient observations are lower-priority evidence. Manual promotion is current
behavior; JAWL-controlled automatic consolidation after opt-in is planned.
The suggested 30-minute/one-week tiers are configurable examples. Logical
forget/archive is not physical erasure; do not imply deletion of revision
history, derived indexes or backups.

## ADR-033 - Prove connected user scenarios, not independent surfaces

Status: Accepted
Date: 2026-09-05

RC requires a complete daily conversation/task/voice/UI scenario on a known
runtime. A release claim requires the applicable matrix in TECHNICAL_AUDIT.
HTTP 200, configured=true, catalog counts, queued memory and DOM markers prove
only their narrow boundaries. Keep profile/version/run ID and failures.

A docs-only audit checks documents and links without launching external agents.
Do not repeat unchanged wheel builds or passing smoke loops in lieu of
implementing the next incomplete product slice.

## ADR-034 - Evolve a coherent behavioral core, not a framework collection

Status: Accepted product clarification
Date: 2026-09-05

Biology/psychology inform a simple perception-attention-decision-action-feedback
cycle, not a literal brain simulation. Reuse JAWL state/EventBus/Heartbeat/
memory and only the necessary VoiceMem perception/recall mechanisms.
One authority is necessary but not sufficient: bounded shared context,
correlated outcomes and coherent text/voice/avatar expression must be tested.

Framework origins do not freeze module boundaries. Audit overlapping cognitive
loops before adapting/replacing them in the owned version. No duplicate persona,
motivational scheduler or memory writer; no new "brain region" service without
an observable behavior, resource budget and acceptance test. Protected upstream
remains read-only. This does not authorize runtime self-modification of code
or access policy.

## ADR-035 - Perception and experience as normal-profile behavior

Status: Accepted product requirement; implementation pending
Date: 2026-09-05

Clarifies ADR-032: after explicit first-run source selection and OS/browser
permissions, normal operation enables microphone/system audio/screen perception
and automatic attributed observations plus JAWL-controlled consolidation.
Manual promotion remains optional, not the ultimate memory architecture.
No raw media archive or remote media transfer is implicitly authorized.
Missing VLM/device remains visibly unavailable; no final VLM is selected here.

Default level 0 must support useful isolated workspace/browser CDP work under
native policy, not unrestricted host control disguised as sandbox. A browser
profile is not by itself an OS isolation boundary. Social read/draft/publish
capabilities belong to explicitly connected accounts and scoped policy;
authorized unattended work must reconcile outcomes before retrying mutations.

One capability/focus/task state informs cognition and UI. A separate Live2D OBS
page presents the same character without private chat/memory/control tokens.
Biological metaphors guide coherence, not claims of sentience or artificial
distress to retain user engagement. This decision does not start capture or
external account actions during development.

## ADR-036 — Native Rust client as audio owner and Live2D host

Status: Accepted
Date: 2026-10-05

The browser tab must not own the character's hearing or body. A thin native
client (Rust + native Cubism SDK, not a game engine) owns the audio devices
(WASAPI capture with hardware-level gate, playback), renders Live2D, hosts the
standalone character window and the OBS surface. The web panel stays as a
control/pult surface and the LAN/tablet URL, but the character no longer
depends on any tab being open. Godot/Unity are rejected as heavy engines; the
game-engine path was discussed and superseded by this decision. The browser
voice pipeline is not removed until the native pipeline duplicates it and
passes the same live acceptance.

## ADR-037 — OpenCode GO deepseek-v4-flash is the baseline brain

Status: Accepted
Date: 2026-10-05

The brain is the already-working deepseek-v4-flash via the OpenCode GO relay
(:8891), covering fast speech, swarm workers and deep thinking. No local LLM
is kept as the default. The provider remains pluggable: the runtime may select
any compatible model, including a user-chosen local model from disk, through
the same JAWL provider contract without breaking the JSON protocol.

## ADR-038 — Episodic timeline as the shared TimeService

Status: Accepted
Date: 2026-10-05

Time is modeled as machine process-time (event log, timestamps) projected
into one episodic timeline — episodes cut on activity boundaries (conversation
start/end, focus change, silence, owner sleep). This timeline is the single
source of "now / recently / long ago" for Heartbeat, memory, attention and
the avatar, replacing per-module clocks, TTLs and cooldowns. Real-time SLOs
apply to the interactive loop (voice/answer/barge-in/avatar); background
processes (memory consolidation, ambient triage) are best-effort and yield to
user turns. Acceptance is a lived 24h scenario, not a test suite pass.

## ADR-039 — Resource budget: Bonsai to GPU1, on-demand unload

Status: Accepted
Date: 2026-10-05

Bonsai moves from CPU RAM to GPU1 (same weights, no quality loss), freeing
~12.5 GB RAM. Screen-watching models unload after an idle window and reload
on the first screen delta with an honest "waking" state, not a masked one.
Quantization is allowed only through the MULTIMODAL_MODEL_GATE mini-bench
(IQ2/IQ1 need the F16+imatrix path); the earlier Q1 Bonsai failure stands.
Target profile: <= 8 GB RAM, ~14 GB VRAM. 20 GB is a ceiling, not the norm.