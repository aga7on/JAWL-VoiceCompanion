# Architecture

## Goals

- Natural Russian voice conversation;
- stable character identity and long-term memory;
- responsive 2D Live2D presence;
- safe optional screen awareness;
- gradual, inspectable proactivity;
- local-first operation with replaceable model providers.

## Non-goals for the first version

- 3D avatar;
- unrestricted computer control by default;
- VLM inference on every frame;
- multiple competing personality systems;
- mobile synchronization.

## Runtime topology

```text
Microphone
   ↓
Voice Gateway: VAD + ASR + AEC + playback cancellation
   ↓
VoiceMem Gateway
   ├─ partial transcript
   ├─ speculative recall
   ├─ audio affect evidence
   └─ final VOICE_TURN
          ↓
      JAWL EventBus
          ↓
  Attention/Presence Engine
   ├─ coalesce low-value signals
   ├─ apply salience and cooldown
   └─ create SPEAK_INTENT
          ↓
      Turn Arbiter
          ↓
      JAWL Heartbeat/ReAct
   ├─ persona and traits
   ├─ structured state and drives
   ├─ Vector/Graph memory
   ├─ tools and approvals
   └─ vision__look
          ↓
     ResponseEnvelope
          ↓
  sentence parser + ordered TTS queue
          ↓
       audio + amplitude
          ↓
       Live2D frontend

Screen Sensor
   ├─ active window / UI Automation
   ├─ screenshot / OCR fallback
   └─ VLM only after policy and change detection
          ↓
       SCREEN_DELTA → JAWL
```

The default focused-window image profile is 960×720 with a 1 MB transient
JPEG cap. Resizing is part of the capture boundary, and the adapter returns a
bounded coordinate scale for future UIA actions; the scale does not itself
authorize input.

## Service boundaries

### JAWL gateway

Owns the canonical character state and exposes a local API for:

- `USER_FINAL` and text turns;
- `SPEAK_INTENT`;
- screen observations;
- memory promotion and reflection;
- tool execution;
- health and state inspection.

JAWL remains the sole authority for final wording and whether a proactive
intent becomes spoken output.

The companion's optional `JawlWebAdapter` reads JAWL's existing loopback web
console for health, Heartbeat, bounded memory counters, drives and a filtered
persona view. `JawlWebChatAdapter` uses the same console's `/api/chat` POST and
`/api/chat/stream` SSE: the POST returns the user's sequence, and the adapter
accepts only a later non-user message. It never opens JAWL storage directly
and keeps no durable copy. Inspection routes are read-only and
session-protected; chat remains loopback/token protected by JAWL.

The same browser session protects the HostOS audit view. The UI displays only
the last bounded metadata events; tool arguments and raw results remain
excluded by the policy audit layer. The CLI may persist the same metadata to a
bounded JSONL file for recovery inspection.

`GET /api/doctor` is the first-run readiness surface. It aggregates only
bounded component states and remediation hints; it does not expose paths or
secrets and does not change runtime configuration. Optional VoiceMem, TTS,
vision and Live2D failures keep text-only chat available.

The JAWL adapters also apply one user-output filter before text enters the
gateway envelope: paired hidden reasoning/tool blocks are removed, while
unclosed blocks and line-level internal markers fail closed. This keeps
subtitles, avatar state and TTS from exposing internal control text.

### VoiceMem gateway

Owns streaming voice perception and returns structured observations. It may
perform fast retrieval, but it cannot directly mutate JAWL personality traits.

The adapter supports the stable semantic boundaries:

```text
feed_partial(text, ended=False)
feed_partial(text, ended=True)
feed_audio(pcm16, sample_rate=16000)
end_audio()
```

The current VoiceMem repository provides this method on `VoiceStream`, but its
bundled WebSocket demo is not treated as the production protocol. The small
loopback sidecar runner in `services/voicemem_sidecar.py` owns the VoiceMem
environment and translates its results into `USER_PARTIAL`/`VOICE_TURN`
events. The JAWL process receives only bounded observations and final user
text through the authenticated `/api/voice/partial`, `/api/voice/audio` and
`/api/voice/end` endpoints. The browser microphone is only an input surface;
VoiceMem remains responsible for streaming ASR and VAD in its own environment.

### Voice Gateway

Owns microphone capture, VAD, ASR lifecycle, audio playback and interruption.
The gateway must be able to cancel both playback and in-flight synthesis.

### TTS worker

Provides a common interface for CozyVoice 2 and OmniVoice. The worker should
support sentence-level requests and cancellation. TTS output is not allowed
to contain internal thoughts or control markup.

The current implementation keeps that boundary small: `TTSService` applies
latest-request-wins cancellation, while `CozyVoiceHttpClient` calls the
separate local REST wrapper and returns bounded transient WAV data. The web
process never imports CozyVoice or its torch/model dependency tree. OmniVoice
will implement the same provider interface after its runtime/API is confirmed.

### Attention/Presence Engine

This is a fast timing and salience layer, inspired by Miru's AttentionEngine.
It receives observations and decides whether they are worth sending to JAWL
as a possible approach. It owns temporary cooldowns and deduplication, not
durable personality.
An optional Windows activity adapter supplies only idle time and foreground
window class; recent user input suppresses proactive speech without reading
keystrokes, titles or clipboard data.

### Live2D frontend

The frontend renders:

- avatar model;
- idle/listening/thinking/speaking states;
- expression and motion;
- lip-sync;
- subtitles and speech bubble;
- settings and approval UI.

The frontend never owns canonical memory or personality state.

### Local Web Control Plane

The browser is the main operator interface. It may be used on the same machine
to chat with the companion, inspect health, change persona and memory settings,
select HostOS access level, review approvals, stop active work and inspect the
audit trail. The first implementation may render the avatar in the browser as
well; a transparent desktop-pet window remains an optional presentation mode,
not a separate source of truth.

The web UI talks only to a loopback backend. Every action is authorized again
on the backend against the current policy, session, tool risk and access level.
The UI cannot grant itself permissions by sending a different level in a
request.

### Avatar presentation surface and OBS

The presentation layer has two browser surfaces backed by the same local
state:

- `/` is the operator control plane for chat, HostOS level, approvals and
  emergency stop;
- `/avatar` is a transparent, read-only surface intended for a desktop window
  or an OBS Browser Source.

The avatar surface polls `/api/state` and renders the last response's bounded
text, state and expression. It has no state-changing controls and does not
receive session credentials. When an explicit asset bundle passes backend
model validation, a tiny `Live2DCompanionRuntime` adapter replaces only the
placeholder canvas; otherwise the dependency-free placeholder remains visible.
JAWL, policy and memory ownership stay in the backend. `?debug=1` enables
small diagnostics for local troubleshooting.

The control plane generates the same-origin OBS URL. OBS should use a Browser
Source with a transparent background and a fixed canvas size selected for the
chosen model. A native always-on-top desktop-pet window remains a later shell
around this surface, not a second runtime or authority.

### HostOS Tool Plane

HostOS is the only layer allowed to create desktop or operating-system side
effects. JAWL can request a tool, but it cannot directly call `subprocess`,
Windows input APIs or filesystem primitives. HostOS resolves the request,
checks policy and returns a bounded, structured result.

The access levels follow the local JAWL HostOS model:

| Level | Name | Capability boundary |
|---|---|---|
| 0 | `SANDBOX` | Read/write only inside the companion sandbox; no host control. |
| 1 | `OBSERVER` | Read host/UI state and screen observations; writes remain sandbox-scoped; no desktop input. |
| 2 | `OPERATOR` | Work with approved project/workspace files and managed processes; desktop/browser actions are policy- and approval-aware. |
| 3 | `ROOT` | Full access available to the current Windows user, including host file operations, GUI input and raw shell compatibility tools. |

Level 3 does not mean Windows elevation: the process cannot cross the secure
desktop or exceed the rights of the user who launched it. It remains a
deliberate expert mode with a visible indicator, emergency stop, audit log and
deny-list. A separate explicit `unattended` switch is available only at level
3, allowing Heartbeat/background work to run without an operator prompt for
each action. Lowering the level disables that switch.

The browser, keyboard/mouse, filesystem, process and shell tools all pass
through the same policy gate. This prevents a lower-risk tool from becoming a
side door around the selected HostOS level.

JAWL already has a native `HostOSClient` and SkillRegistry. The companion
executor covers companion-side browser/control requests, and the opt-in
authenticated bridge synchronizes level 0–3 and whole-agent emergency stop
with native JAWL. Native per-tool approval/unattended state remains owned by
JAWL until it exposes a matching contract. The companion must not create a
second JAWL tool registry. See `docs/contracts/jawl-hostos.md`.

## Memory ownership

```text
Persona config       → JAWL
Traits / drives      → JAWL SQL
Facts / relations    → JAWL Vector + Graph + structured fact records
Conversation archive → JAWL + VoiceMem session layer
Audio affect         → VoiceMem evidence, then optional JAWL promotion
Daily reflection     → JAWL background jobs
```

Always-injected context must be hard-capped. Detailed memory is retrieved only
when relevant.

Canonical fact records should support:

```text
key
text
status: active | stale | archived
epistemic: fact | self_report | preference | inferred
source
confidence
occurred_at
valid_from
invalidated_at
history
```

Updates should support `insert`, `patch`, `remove`, `archive` and
`supersedes`. User-visible memory editing is a required product feature.

## Ambient secondary memory

System audio and screen observations are optional evidence, not another user
conversation. A bounded pipeline keeps raw capture transient, stores short
working observations, and later compresses related observations into an
ambient episode. Only a JAWL-owned promotion step may turn an episode into a
canonical fact or relation.

```text
system-audio loopback ─┐
                       ├─ segment/ASR ─┐
screen keyframe/delta ─┘               ├─ CPU/RAM triage ── T1/T2 episode
                                       └─ no direct USER_FINAL/tool/speech
microphone ── VoiceMem conversational path ── USER_PARTIAL/VOICE_TURN
```

The initial policy is: capture off by default, raw audio/frames RAM-only,
working observations with a bounded TTL (target about 30 minutes), and
configurable short-lived episodes (target about 7 days). Audio from the PC is
kept in a separate session from microphone ASR so game, browser or media
speech cannot impersonate the user. The same ASR implementation may be
reused behind that separate stream boundary.

The delayed triage model is a replaceable CPU/RAM profile. Candidate local
models are benchmarked for Russian quality, memory use and throughput; model
names are not hard-coded into the architecture. Triage returns importance,
bounded summary, confidence, source and provenance. It cannot directly alter
persona, speak, call HostOS or write a durable fact.

The user can pause or clear ambient buffers, set separate audio/visual
retention and disable promotion. Sensitive applications/windows are filtered
before storage. This path is distinct from explicit `vision__look` and from
the proactive `SPEAK_INTENT` path.

The first implementation is `AmbientMemoryBuffer`: it is disabled by default,
accepts only normalized audio/visual text events, applies private-text
suppression plus TTL/count/byte bounds, and forms deterministic
`AMBIENT_EPISODE_CANDIDATE` records. The browser exposes authenticated
inspection, explicit enable/disable, triage and clear operations at
`/api/ambient-memory`. Hardware capture and model-backed triage are deliberately
separate follow-up adapters.

The first hardware boundary is `SystemAudioLoopback`. It lazy-loads the
optional PyAudioWPatch-compatible backend, selects the default WASAPI loopback
device, queues bounded PCM16 chunks in RAM and sends them to a consumer with a
separate session ID. `AmbientAudioASRBridge` converts stereo/rates to bounded
mono PCM16 for an isolated VoiceMem session and ingests only final
`VOICE_TURN` observations into ambient memory. It is never started by the web
server automatically; live backend permission/startup remains pending.

## Turn priority

```text
USER_FINAL / BARGE_IN     0
TOOL_APPROVAL              1
PROACTIVE                  2
SCREEN_DELTA               3
BACKGROUND                 4
```

The Turn Arbiter guarantees one active conversational turn and expires stale
queued work. A newer user turn cancels or supersedes lower-priority work.

Attention/Presence also applies an optional local-time quiet-hours window
before creating a `SPEAK_INTENT`. It is a deterministic gate, independent of
the vision provider, and supports windows crossing midnight.

## Voice lifecycle

```text
idle → listening → partial transcript → final transcript
     → thinking → streaming response → speaking → idle
```

At any point, `BARGE_IN` can transition the system to `listening` after
cancelling output.

Interruption categories:

- backchannel — resume;
- correction — discard and listen;
- amend — revise the current answer;
- new question — start a new turn;
- unclassified — conservative fallback.

## Screen policy

Default policy:

- off until explicitly enabled;
- focused window before entire screen;
- exclude the companion's own window;
- use UI Automation for native controls;
- use screenshots/OCR/VLM for custom surfaces;
- rate-limit and deduplicate observations;
- discard raw screenshots after analysis;
- store bounded textual descriptions and metadata;
- deny-list sensitive applications and windows.

Screen observation and screen control are separate permissions. `OBSERVER`
may inspect bounded UI/screen state when enabled, but cannot click or type.
`OPERATOR` and `ROOT` may use desktop interaction tools according to the
current approval policy.

Native controls use the UIA `desktop.act` path. Custom/canvas surfaces use the
bounded `desktop.pointer` fallback: Vision supplies image coordinates plus the
frame dimensions and foreground-window bounds, and HostOS rechecks those
bounds before converting to screen coordinates. Dispatch and application
acceptance remain separate postconditions.

There are two separate paths:

1. passive sensor path for meaningful screen changes;
2. explicit `vision__look` tool when the model or user genuinely needs a
   fresh frame.

The current implementation provides the second path through
`/api/vision/look`. It invokes the HostOS `screen.observe` snapshot, hashes
the transient image in memory, suppresses identical frames and enforces a
short cooldown before a new VLM request. A provider-neutral
OpenAI-compatible client sends the image as a bounded `image_url` payload and
returns only a bounded description. An explicit `--screen-watch` option now
adds the first ambient producer: an arbiter-aware, bounded in-memory
`ScreenDeltaWatcher` publishes `SCREEN_DELTA` events through
`/api/vision/events`. Attention/Presence applies salience, privacy, DND,
coalescing and a proactive budget, exposing `SPEAK_INTENT` through
`/api/vision/intents`. With an explicit `--jawl-event-dir`, accepted intents
are atomically written to JAWL's existing event IPC; JAWL still owns final
wording and whether to speak.

## Model profiles

The runtime should distinguish:

- main chat/reasoning model;
- fast attention model;
- memory/consolidation model;
- vision model;
- Russian ASR model;
- TTS provider.

Each profile needs health, readiness, latency and fallback reporting. Missing
optional models must result in a degraded mode, not a broken startup.

The current benchmark profile is Qwen3-VL-2B for Vision/UI grounding and
Qwen3-ASR-0.6B for audio. The latter is available in the Companion as an
explicit final-utterance adapter while VoiceMem remains the default streaming
ASR path. A temporary OpenAI-compatible chat URL (currently TokenRouter/GLM
for testing) is a transport probe only; it does not replace JAWL's JSON action
envelope, persona, memory or Heartbeat.
