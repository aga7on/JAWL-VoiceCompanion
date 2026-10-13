# Core ownership map

Status: code map refreshed 2026-10-12. The original10Oct audit was read-only;
fresh isolated transport/console probes are in STATE, not whole-core acceptance.
`Observed` means present in
inspected source; `Proposed` means target boundary, not accepted behavior. See
[README.md](README.md), [STATE.md](STATE.md), and [TODO.md](../TODO.md).

## Boundary in one view

Owned console entry verifies the pinned source and installs an explicit HTTP
admission middleware after native auth, inside that same console process.
It owns bounded ID tombstones/dedup and transport cleanup only; ChatBridge,
Heartbeat, persona, memory, tasks and tools remain native JAWL-owned. No protected
source files are patched. Process-local/TTL state is not durable task storage or
exactly-once authority. See [contract](contracts/jawl.md) and [release](RELEASE.md).

Default turn/cancel POST sockets and their absolute-deadline watchdogs are owned
by the Companion HTTP adapter (`http_lifecycle.py`). Cancellation cannot close a
replacement call's socket. The producer retains admission through cleanup;
opaque injected openers are not forcibly reaped. Local socket EOF is not proof
that the native goal was deleted or model compute was released.

```text
sensor/model output -> Companion normalization -> JAWL decision/authority
                                                      |
                         verified outcome <- action/task/memory lifecycle
                                                      |
                              one ResponseEnvelope -> text / TTS / avatar
```

| Area | Observed JAWL owner | Observed Companion owner | Observed VoiceMem owner | Proposed platform rule |
|---|---|---|---|---|
| State | `src/l0_state/agent/state.py` holds ReAct metadata, `current_goal`, short-term state and heartbeat settings; `src/utils/event/bus.py:EventBus` is shared through `src/system/container.py`. | `TextGateway.state()`, `TurnArbiter.state()`, `AttentionPresence.state()`, `CompanionServer` composition, and in-memory turn/ambient projections. | `VoiceMem` session/stream state; `utils/common/session_tracker.py:SessionTracker` persists turn/session references. | JAWL owns durable persona, facts, tasks and decision state. Companion owns only bounded transport/UI/sensor projections. VoiceMem state is sidecar-local and never a second persona DB. |
| Heartbeat / wake | `src/l3_agent/heartbeat.py:Heartbeat` schedules ReAct and consumes EventBus events; `src/l3_agent/react/loop.py:ReactLoop` executes the cycle. | `src/jawl_voicecompanion/attention.py:AttentionPresence` scores/queues local events; `__main__.py` starts ambient schedulers. | No platform wake owner; VoiceMem stream/perception workers process supplied input. | One JAWL wake/decision loop. Companion attention may rank observations or emit a bounded `SPEAK_INTENT`; it must not invoke a second ReAct loop. Disable independent VoiceMem/Companion proactive reply paths. |
| Attention / context | `src/l3_agent/context/builder.py` and `context/registry.py` assemble bounded prompt context from state, tasks and RAG; Heartbeat decides whether to wake. | `AttentionPresence.consume()`, `intents()`, quiet-hours configuration and `ResourceGovernor` are local admission/resource controls. | `utils/fusion/reply_memory.py:build_reply_memory()` and `rightbrain/brain.py:RightBrain.search()` rank/retrieve VoiceMem context. | JAWL owns priority among user turn, task and background work. Companion supplies timestamped, attributed observations; VoiceMem recall is optional evidence, not authority or instruction. |
| Turns / cancellation | `src/l3_agent/companion_gateway.py` is the native Companion gateway; `Heartbeat`/`ReactLoop` bind and cancel the native turn. | `jawl_web.py:JawlWebChatAdapter._respond_native()`, `_post_native()`, `_post_native_cancel()`, `_wait_for_native()`; `gateway.py:TextGateway.handle_text()`/`stream_text()` and `arbiter.py:TurnArbiter.begin/complete/cancel`. | `core.py:VoiceMem.stream()` handles stream input; it is not eligible to create a JAWL user turn except through the sidecar contract. | Preserve correlation and task state when speech/turn transport is cancelled. A new conversational turn may cancel stale speech, but does not imply durable task execution or provider work was cancelled. Bridge mode must not fall back to `TextGateway`’s local mock responder. |
| Memory ingest | Native `src/l1_databases/sql/management/structured_memory.py:SQLStructuredMemory` exposes `read_active`, `remember`, `revise_memory`, `forget_memory`, `archive_memory` through `src/system/operator_control.py` `memory.*` actions. JAWL also owns Tasks, Notes, Personality Traits, Mental States, Drives, Hypotheses, Ticks/Timelines and Daily Journal; JAWL RAG is under `src/l3_agent/context/rag/`. | `voicemem_client.py:VoiceMemAsyncIngest.enqueue_partial()` queues identical text; `ambient_memory.py:AmbientMemoryBuffer` stores bounded observations/ambient episodes; `web.py` exposes manual promotion through `JawlWebAdapter.remember_memory()`. | `core.py:VoiceMem.ingest()` and VoiceMem's independent memory/affect subsystems. | T1/T2 are process-local; manual promotion into JAWL is implemented. Durable automatic consolidation is OPEN. VoiceMem evidence is not canonical memory. ASR is speech transcription, not audio captioning or a validated affect reader. |
| Consolidation / recall | `src/l3_agent/subconscious/` contains consolidation/forgetting prompts and poller/orchestrator; `context/rag/` supplies JAWL retrieval. Actual end-to-end consolidation from Companion is not proven by this read. | `AmbientTriageScheduler` and local `AmbientMemoryBuffer.triage()` are bounded triage, not canonical consolidation. | `leftbrain/memory_repository.py:search/search_combined()`, `rightbrain/brain.py:RightBrain.search/write()`, `utils/fusion/reply_memory.py` and `cognitive_graph/store.py` form an independent memory/graph path. | Keep one durable memory authority. In the approved profile, disable VoiceMem durable promotion/`reply()` and use it for observations/optional recall only; route accepted revisions, contradiction handling, retention and erasure through JAWL. |
| Tool authority | Native HostOS/Terminal/Debug/MCP/browser registry and policy: `src/l2_interfaces/host/os/decorators.py:require_access`, `host/os/client.py:HostOSClient`, `src/l3_agent/skills/registry.py`, and `src/system/operator_control.py`. | `hostos_policy.py:HostOSPolicy.authorize()` and `hostos_tools.py` provide a local compatibility executor/catalog; `jawl_web.py` proxies native policy/skills. | No tool authority. Audio/perception code must not execute tools. | JAWL is the only side-effect authority, including level 0–3, unattended lease, approvals, audit, MCP and browser. In bridge mode local `HostOSPolicy`/executor is not a fallback. Model fields never set access level. |
| Tasks / commitments | `src/l3_agent/goals/ledger.py:TaskLedger`, `TaskLedgerPatch`, `apply_ledger_patch`; `goals/manager.py`; SQL task management under `src/l1_databases/sql/management/tasks/`. | UI/HTTP may display or submit a task request, but `web.py` must not own a durable task ledger. `TurnArbiter` owns response priority only. | No task authority; VoiceMem may provide context about a spoken request. | A task is created, checkpointed, resumed, reconciled and completed by JAWL. Interruption cancels speech/turn transport, not the task. Uncertain external effects require verification, not replay. |
| Expression | Native gateway/response contract carries selected response state; JAWL chooses semantic response. | `gateway.py:TextGateway._build_envelope()` validates/creates local fallback emotion/avatar; Electron desktop scene projects expression and speech amplitude to VRM. | VoiceMem affect fields, where present, are observations, not a command to change persona. | One response state is projected to text, TTS and the current Electron VRM surface. Amplitude-driven mouth movement is not phoneme lip sync or evidence of ASR affect capability. |
| Lifecycle / recovery | `src/system/orchestrator.py` orders system start/stop; `src/l3_agent/hooks/lifecycle.py:LifecycleHooks`; `src/instances/supervisor.py` handles instance supervision; native autonomy is `host/os/autonomy.py:validate_root_autonomy_lease`. | `__main__.py` composes `CompanionServer`; `VoiceMemProcessClient.close/abort`, `AmbientTriageScheduler.start`, and presentation server lifecycle manage adapters. | `services/voicemem_sidecar.py:VoiceMemSidecar` isolates per-session streams and reports degraded state; `VoiceMemProcessClient` owns child-process transport. | JAWL owns agent/task/autonomy lifecycle. Companion owns adapter lifecycle and reports health; it must not restart or mutate protected JAWL implicitly. Recovery resumes from native checkpoints and verifies prior effects. |

## Concrete overlaps to resolve

1. **Two response paths (observed):** `TextGateway` has a local responder and
   envelope builder while `JawlWebChatAdapter` has the native SSE path. The
   normal platform profile must select the latter exclusively; local mode is
   explicit mock/standalone only.
2. **Two attention paths (observed):** `AttentionPresence` can score and emit
   intents while JAWL `Heartbeat` consumes events and starts ReAct. Proposed:
   keep the former as bounded sensor admission and make JAWL the only wake and
   decision owner.
3. **Two durable-memory families (observed):** JAWL structured/RAG memory and
   VoiceMem left/right/graph stores can both retain extracted experience.
   Proposed: VoiceMem returns attributed evidence/recall; JAWL alone promotes,
   revises, forgets, consolidates and supplies canonical recall.
4. **Two authority surfaces (observed):** Companion has `HostOSPolicy` and
   `hostos_tools`, while native JAWL has registry/policy/approval paths.
   Proposed: local executor remains only for explicit standalone/mock; native
   rejection is visible and terminal in bridge mode.
5. **Ambient promotion overlap (observed):** `AmbientMemoryBuffer` owns a
   transient episode and the manual route can write a confirmed candidate to
   JAWL. Durable automatic consolidation remains OPEN. Preserve provenance,
   source, time and confidence; never convert ambient audio into `USER_FINAL`
   or a tool request.

## Minimum protected JAWL addition set

This is the smallest *candidate* set implied by the current Companion routes,
not an approval to copy or merge the dirty checkout. It must be reviewed against
the owner’s clean baseline and licenses.

| Required capability | Current protected paths observed | Minimum disposition |
|---|---|---|
| Correlated native turn/SSE/cancel | Untracked `src/l3_agent/companion_gateway.py`; dirty `src/l3_agent/heartbeat.py`, `src/l3_agent/react/loop.py`, `src/web/chat.py`, `src/web/agent.py`, `src/web/server.py` | Own/pin the gateway plus only the call-chain changes needed for turn binding, `assistant.final`, event sequence, and exact cancellation. |
| Canonical structured memory | Untracked `src/l1_databases/sql/management/structured_memory.py`; dirty `src/system/operator_control.py`, `src/web/database.py`, `src/web/server.py` | Own/pin the structured-memory module and its allowlisted `memory.*` dispatch/read routes. No Companion direct DB access. |
| Native policy/authority and unattended lease | Untracked `src/l2_interfaces/host/os/autonomy.py`; dirty `src/l2_interfaces/host/os/client.py`, `decorators.py`, `plugin.py`, `src/l3_agent/skills/registry.py`, `src/system/operator_control.py` | Keep only the native policy/lease/approval/audit changes required by the Companion contract. Do not carry a second Companion allowlist into level 3. |
| Stable identity/readiness | Dirty native web/agent/config/status paths referenced above | Add a version/capability/instance handshake and fail closed on missing native identity. Existing independent HTTP/status probes are not proof of this path. |

Everything else in the JAWL dirty status is out of scope for the Companion
minimum until a concrete route/symbol and acceptance test depends on it. In
particular, do not treat timestamps, dirty status, catalog counts or untracked
files as authorship, clean compatibility, or permission to modify upstream.

## Minimal owned dependency/fork recommendation

1. Owner approves a clean JAWL baseline, then an owned fork or packaged
   dependency containing only the gateway, structured-memory and native
   authority slices above. Pin commit/version, Python/dependency lock and a
   capability manifest; retain upstream provenance and licenses.
2. Run the owned JAWL runtime from a separate deployment directory with its own
   config/data/log/cache. The current dirty `G:\AI\JAWL-Coding` checkout remains
   a read-only reference; never use it as Companion runtime state.
3. Companion depends on the versioned HTTP/SSE contract and handshake, not on
   JAWL internal SQLite/Vector/Graph files. A contract-compatible release is
   preferable to vendoring unrelated JAWL sources. If the owner declines a
   fork, stop at a read-only adapter contract; do not recreate Heartbeat,
   memory, tasks or tools locally.
4. Keep VoiceMem as a separately pinned sidecar dependency. Its `feed_*`/
   `VOICE_TURN` path may be replaced independently, but `VoiceMem.reply()` and
   durable left/right memory writes are not part of the Companion agent loop.

## Bounded actions and acceptance tests

Priority order:

- **P0 owner decision:** classify the candidate native diff by path/symbol,
  choose owned fork/package and baseline, and publish the capability manifest.
- **P0 contract slice:** prove one Companion-originated correlated turn through
  native JAWL, one exact cancel, native identity, and native policy authority;
  remove any bridge-mode local fallback.
- **P1 coherence:** add synthetic/fake-transport tests for observation → JAWL
  decision → native action → verified result → JAWL task/memory update. Add
  restart/reconnect and stale-event cases; do not use live devices or models for
  this docs task.
- **P1 memory/attention:** test ambient/VoiceMem input is attributed evidence,
  never `USER_FINAL`; test one JAWL consolidation/revision changes later recall
  and survives restart. Separate logical forget from physical erasure.
- **P1 expression/lifecycle:** assert the same `ResponseEnvelope` drives text,
  TTS and avatar; playback cancellation removes stale audio without removing a
  durable task; stop/start does not duplicate events or replay uncertain effects.

Acceptance evidence must record: profile/run ID, pinned version or dirty-diff
identifier, input, expected/observed result, pass/fail/skip and exit code. The
current audit’s unit/fake HTTP/static evidence does not prove live readiness,
physical audio, real provider behavior, visual/OBS acceptance, eight-hour
autonomy, or exactly-once external side effects. BrowserAdapter `open_url`
opens an HTTP(S) URL through the system browser; UIA delegation is not a full
CDP session. Attachment backend presence does not establish desktop UX.
`run_target_jawl_smoke.ps1` remains excluded by instruction, and this document
does not change runtime.
