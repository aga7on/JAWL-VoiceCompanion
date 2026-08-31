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
- unrestricted computer control;
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

### VoiceMem gateway

Owns streaming voice perception and returns structured observations. It may
perform fast retrieval, but it cannot directly mutate JAWL personality traits.

The adapter must support:

```text
feed_partial(text, ended=False)
feed_partial(text, ended=True)
```

### Voice Gateway

Owns microphone capture, VAD, ASR lifecycle, audio playback and interruption.
The gateway must be able to cancel both playback and in-flight synthesis.

### TTS worker

Provides a common interface for CozyVoice 2 and OmniVoice. The worker should
support sentence-level requests and cancellation. TTS output is not allowed
to contain internal thoughts or control markup.

### Attention/Presence Engine

This is a fast timing and salience layer, inspired by Miru's AttentionEngine.
It receives observations and decides whether they are worth sending to JAWL
as a possible approach. It owns temporary cooldowns and deduplication, not
durable personality.

### Live2D frontend

The frontend renders:

- avatar model;
- idle/listening/thinking/speaking states;
- expression and motion;
- lip-sync;
- subtitles and speech bubble;
- settings and approval UI.

The frontend never owns canonical memory or personality state.

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

There are two separate paths:

1. passive sensor path for meaningful screen changes;
2. explicit `vision__look` tool when the model or user genuinely needs a
   fresh frame.

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
