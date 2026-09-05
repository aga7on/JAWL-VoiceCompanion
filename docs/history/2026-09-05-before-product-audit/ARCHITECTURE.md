> Исторический снимок до аудита 2026-09-05. Может содержать неверные статусы и небезопасные команды; не инструкция к выполнению. Актуальны docs/PRODUCT.md, docs/STATE.md и TODO.md в корне проекта.

# Архитектура JAWL VoiceCompanion

## Цель и границы

Продукт — локальный русскоязычный AI-компаньон с 2D-аватаром, голосом,
Heartbeat и опциональным наблюдением за экраном/системным аудио. Трёхмерный
аватар, mobile sync, cloud deployment и непрерывная запись raw audio/video
сейчас не входят в scope.

Главный принцип: **JAWL — единственный cognitive/tool/policy/memory owner**.
Companion не запускает второй агентский цикл и не выбирает между двумя
исполнителями side effects.

## Runtime topology

```text
Microphone ──> AudioWorklet gate/pre-roll ──> ASR/VoiceMem sidecar
                                              │ partial/final evidence
System audio ─> isolated loopback + TTS suppression ─> ambient buffer/triage
Screen ───────> opt-in bounded capture/UIA ─────────> Vision/Attention
                                                        │
                                                        v
Companion control plane ── typed loopback ──> JAWL Gateway
  arbiter · ASR/TTS · sensors · governor             │
                                                     v
                  JAWL Heartbeat/ReAct/persona/memory/native tools
                                                     │
                          policy 0..3 · lease · approval · audit · stop
                                                     │
                                  ResponseEnvelope + typed events
                                                     v
                     Companion control UI ──> isolated presentation/OBS
```

## Service ownership

### JAWL

JAWL owns the model provider (cloud/local/QWB-JAWL/GPT Luna), persona, traits,
drives, Heartbeat, ReAct, goals, native SkillRegistry, HostOS levels,
approvals, Debug Broker and durable memory. The user-facing Companion Gateway
is served by native JAWL over loopback.

Native event stream:

```text
turn.started
assistant.delta
tool.requested / tool.started / tool.completed
assistant.final
turn.cancelled | turn.error
```

Every event has `schema_version`, monotonic `event_seq`, bounded `turn_id` and
typed payload. `assistant.final` contains exactly one strict
`ResponseEnvelope`. A client reconnects from a cursor; a broadcast message is
not evidence of a completed correlated turn.

Native control actions include `react.cancel`, `hostos.policy.get`,
`hostos.autonomy.issue/revoke`, `hostos.emergency_stop`,
`hostos.emergency_stop.reset`, `hostos.skill`, `debug.skill`,
`skills.catalog` and structured memory actions. `skills.catalog` is a bounded
read-only projection of the live native registry; it is discovery only and
does not create a Companion-side tool registry.
The native web console proxies these through its own control socket, so a
separate browser process never constructs a second HostOS client.
For observability it also exposes a bounded, read-only projection of JAWL's
append-only action journal; this projection contains plan state and outcomes,
not original parameters or an execution path.

### Companion

Companion owns transport/UI, TurnArbiter, AudioWorklet input, provider-neutral
ASR/TTS adapters, transient ambient evidence, optional Vision capture and
2D/OBS presentation. It may show degraded text mode, but it must not invent a
native JAWL answer or persist a parallel personality/memory database.

When `--jawl-hostos-control` is enabled, `/api/hostos/execute` forwards native
skill requests to JAWL. Local `HostOSExecutor` remains available only for
explicit standalone/mock/development profiles and local sensor compatibility;
it is not a competing model authority in bridge mode.

### VoiceMem and ASR

VoiceMem runs in its own environment and receives bounded PCM16/partial text.
Its outputs are observations. Only an explicit final transcript becomes a
JAWL user turn. Qwen3-ASR-0.6B is the current final Russian benchmark choice;
true streaming Qwen partial API is not assumed. In external final-ASR mode,
the authoritative ASR text is adapted into a transport-only `VOICE_TURN`
immediately; identical VoiceMem enrichment is queued on one bounded serialized
worker and never blocks the response. Queue state is observable and shutdown
interrupts a slow sidecar. VoiceMem's bundled profile is not treated as proven
Russian final ASR without a live benchmark.

The browser gate uses AudioWorklet, hysteresis, local noise-floor calibration,
pre-roll, RMS/peak visualization and a bounded upload queue. It flushes the
last partial chunk before ending. Gate filtering is software-side, not a claim
of hardware DSP.

System audio is a separate ambient stream. It can never produce `USER_FINAL`.
TTS playback opens a short suppression span; loopback ASR drops frames in that
span. Real AEC/echo and dynamic microphone acceptance are still live work.

### TTS

`TTSService` is provider-neutral and latest-request-wins. It splits text into
bounded sentences, starts up to three provider requests where supported,
returns source order and propagates cancellation. CozyVoice-compatible/Tera wrappers
return transient WAV; active HTTP bodies are closed on cancellation. This is a
transport cancellation guarantee, not yet a guarantee that a provider has
stopped inference before returning a body.

TeraTTSv2 is the current low-latency CPU/Russian profile. Qwen3-TTS
12Hz-0.6B-Base is an explicit voice-clone profile behind the same REST
contract; its reference files are fixed at worker startup and are never
selected from an HTTP request. Emotion is mapped to a bounded portable rate
bias where supported and unknown styles fall back to neutral. The Qwen Base
worker explicitly reports no cloned-voice emotion control until measured.
OmniVoice remains an optional future adapter after its model/API path is
confirmed.

### Ambient memory

Raw audio/video is not durable by default. `AmbientMemoryBuffer` keeps bounded
observations/episodes with TTL, source, confidence, salience and provenance.
Delayed Bonsai triage is optional and cannot call tools or create user turns.
Selected `promote_candidate` episodes can now be sent to JAWL
`structured_memories` through an explicit, confirmed browser operation. The
default remains no automatic promotion; raw observations never become a
`USER_FINAL` turn.

### Durable structured memory

JAWL's `structured_memories` table is append-only by logical `memory_key`:

```text
memory_key -> revision 1 -> revision 2 -> ... -> forgotten/archived revision
```

Supported kinds: `fact`, `trait`, `preference`, `summary`. Each row includes
source, confidence, provenance and `supersedes_id`. Only the latest active
revision enters the prompt projection. Browser routes `/api/memory` and
control actions `memory.remember/revise/forget/archive` never bypass JAWL.
Valid-time fields are implemented. Vector/Graph archival recall remains
JAWL-owned by the existing hybrid RAG path when the real Kuzu backend is
available; backend capability is probed and import-only stubs fail closed.
Tick thresholds run the native
Sleep/Reflection/Consolidation patterns. Daily summaries use the same
append-only table under `journal:YYYY-MM-DD`; commitments are existing JAWL
tasks referenced by ID, never copied into a second journal store. The UI
and native Forgetting pattern can archive expired structured revisions without
deleting history. The UI distinguishes `disable` (stop new capture, retain bounded items until TTL)
from confirmed `disable_and_erase` (stop capture and clear the transient
buffer).

### Vision and desktop interaction

Vision is explicit/opt-in; default focused capture is bounded to 960×720 and
1 MB JPEG, raw frames are discarded. UIA semantic observations are preferred.
Canvas fallback uses calibrated pointer coordinates and stale foreground checks.

Screen capture issues a signed short-lived observation token bound to HWND,
class, bounds and frame digest. `VisionActionPlan` v1 requires that token,
identity/coordinates and a declared postcondition. `VisionPlanExecutor` is now
the sequential backend seam: it translates into normal `ToolRequest` objects,
rechecks the token and frame digest before every action, routes through HostOS
policy and stops unless a verified postcondition is returned. In JAWL control
mode, `JawlNativeVisionExecutor` maps the supported plan operations to native
`HostOSDesktop` skills. Pointer plans cover `move`, `click`, `double_click`,
`right_click` and `middle_click`; keyboard and UIA actions remain native as
well. The explicit `/api/vision/execute` route requires session/CSRF and
confirmation. Screen capture can optionally run transient OCR grounding and
opaque pixel redaction before JPEG/VLM upload; no OCR or VLM dependency is
enabled by default.

### HostOS and Debug Broker

| Level | Name | Boundary |
|---:|---|---|
| 0 | `SANDBOX` | sandbox-only read/write |
| 1 | `OBSERVER` | observation/read and sandbox write |
| 2 | `OPERATOR` | approved workspace/managed process/interactive work |
| 3 | `ROOT` | all operations available to the current Windows account |

ROOT is full user capability, not UAC/secure-desktop bypass. OS ACLs, provider
failures, TTD EULA and external permissions remain real limits. Unattended is a
separate explicit expiring ROOT lease. Emergency stop revokes it and stops
owned sessions/process trees.

JAWL's Debug Broker keeps native x64dbg/Ghidra/radare2/Frida/WinDbg/Qiling/
Triton providers and dynamically discovered operations. Its 35 catalog entries
carry risk/minimum-level metadata; Companion does not duplicate this registry.

### Web and presentation

The control server is loopback-only, session/CSRF protected and owns policy,
chat, memory and approvals. The presentation server is also loopback-only and
exposes only `/api/presentation/state`, presentation config and safe asset
files. It has no control token, chat history or mutation route. `/avatar` is
the OBS Browser Source/desktop-pet surface; `/` is the operator panel.

User-supplied Live2D runtime/model files remain untrusted and must be under an
explicit validated/licensed asset root. The dependency-free reactive 2D face
is the fallback until a bundle is supplied and live-tested.

`/api/doctor` is the aggregated readiness report. It separates configured,
degraded and live-ready components; it never claims live model/OBS readiness
from a mock test. `ResourceGovernor` exposes low/standard/high profiles and
gaming backoff while keeping speech higher priority than ambient triage.

## Failure and recovery rules

- Invalid JSON, unknown fields, malformed IDs and unbounded payloads fail closed.
- Newer turn cancels the exact older turn; stale tool/vision targets are rejected.
- TTS/ASR/Vision/provider failures degrade to text/observation state, not a
  fabricated success.
- Emergency stop is a native JAWL latch and includes owned subprocess cleanup.
- Autonomy survives restart only through a still-valid bounded lease; pending
  one-shot approvals never survive restart.
- No raw screenshot/audio enters durable memory unless a future explicit
  consent/retention policy says so.

## Release evidence

The mandatory mock gate is `scripts/run_full_gate.ps1`. The live release gate
also needs JAWL 100-turn correlation, native tool parity, real audio/TTS/Vision,
lease recovery, memory restart behavior, licensed 2D asset and OBS/desktop-pet
soak. See `docs/TECHNICAL_AUDIT.md`.
