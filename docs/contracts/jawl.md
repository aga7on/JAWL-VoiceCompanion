# JAWL bridge contract

JAWL is the only owner of persona, Heartbeat, ReAct, HostOS side effects and
durable memory. Companion never opens JAWL SQLite/Vector/Graph storage and
never runs a second model/tool loop.

## Deployment prerequisite

This contract describes the intended native counterpart and the code inspected
in the local dirty JAWL checkout, not universal upstream support. Deployment
requires a pinned compatible version/capability check and an owned runtime.
`G:\AI\JAWL-Coding` remains read-only, including state/log directories. See
[architecture](../ARCHITECTURE.md) and [audit](../TECHNICAL_AUDIT.md).

## Native Companion Gateway v1

JAWL emits a correlated SSE stream at `GET /api/companion/stream` and accepts a
turn at `POST /api/companion/turn`:

```json
{"text":"Привет","turn_id":"turn-123"}
```

Each event has this shape:

```json
{
  "schema_version": 1,
  "event_seq": 42,
  "turn_id": "turn-123",
  "type": "assistant.final",
  "payload": {"response": {"schema_version": 1}}
}
```

Supported types are `turn.started`, `assistant.delta`, `tool.requested`,
`tool.started`, `tool.completed`, `assistant.final`, `turn.cancelled` and
`turn.error`. `assistant.final` is emitted once and carries one strict
`ResponseEnvelope`. `POST /api/companion/cancel` addresses exactly one
`turn_id`; it cannot cancel another turn by text or sequence guess.

The Companion parser rejects unknown fields, malformed IDs, oversized payloads,
model-supplied access levels and final events for another turn. JAWL keeps a
bounded persistent native event journal and accepts `JAWL_GATEWAY <event_seq>`
on its terminal transport; the web stream returns cursor metadata and sets
`gap: true` instead of silently claiming an unavailable replay. Corrupt or
unreadable journal state also fails closed as a gap. A native Gateway client
is not an operator CLI session and does not emit terminal-open/close presence
events. This supports replay and duplicate suppression, not exactly-once
native side effects. Mutations need authority-owned idempotency and recovery
reconciliation; a crash after dispatch can leave an uncertain outcome.

Provider selection stays inside JAWL. QWB-JAWL, GPT Luna, TokenRouter or a
local model must satisfy JAWL's own provider/tool contract; Companion receives
only the native event/envelope.

## Native control routes

JAWL's web console proxies these authenticated actions through the native
localhost control socket:

| HTTP route | Native action |
|---|---|
| `GET /api/hostos/policy` | `hostos.policy.get` |
| `POST /api/hostos/autonomy` | `hostos.autonomy.issue/revoke` |
| `POST /api/hostos/emergency-stop` | `hostos.emergency_stop` |
| `POST /api/hostos/emergency-stop/reset` | `hostos.emergency_stop.reset` |
| `POST /api/hostos/skill` | `hostos.skill` |
| `POST /api/debug/skill` | `debug.skill` |
| `GET /api/skills/catalog` | `skills.catalog` |
| `GET /api/memory` | `memory.list` |
| `POST /api/memory` | allowlisted memory operation |
| `GET /api/agent/journal` | bounded read-only action-plan projection |

`hostos.skill` accepts only registered `HostOS*` or `HostTerminal*` skills;
their native `require_access` decorators and JAWL policy remain authoritative.
It does not copy wrappers into Companion. At ROOT the available capabilities
are those of the current Windows account, subject to OS/provider/EULA limits.
`debug.skill` similarly accepts only JAWL's seven stable Debug Broker skills;
the provider operation catalog remains dynamic and native to the broker.

`GET /api/skills/catalog` is a bounded read-only discovery route. It returns
the currently registered native HostOS, HostTerminal and Debug Broker skill
names, signatures, minimum HostOS level and current availability. It is not a
second registry: execution still goes through `hostos.skill`/`debug.skill` and
the native JAWL SkillRegistry.

`GET /api/agent/journal?limit=20&state=failed` exposes only the public summary
of recent native action plans: plan state, timing, action identities, bounded
outcomes and unresolved actions. The web console obtains it through the native
`agent.journal` control action and returns it under `journal`. It never
enables execution and does not include the original action parameters or full
lifecycle event stream. The Companion displays this as an inspection surface;
JAWL's append-only journal remains the only source of truth.

## Canonical structured memory

`structured_memories` is append-only per `memory_key`. A record has:

```json
{
  "memory_key":"user.language",
  "revision":2,
  "kind":"fact",
  "subject":"user",
  "predicate":"speaks",
  "value":"Russian",
  "source":"conversation",
  "confidence":0.9,
  "provenance":{"turn_id":"turn-123"},
  "supersedes_id":"...",
  "valid_from":"2026-09-02T12:00:00+00:00",
  "valid_until":null,
  "retention_tier":"long"
}
```

`memory.remember` creates a key; `memory.revise` appends a new active revision;
`memory.forget` and `memory.archive` append terminal revisions without
destroying history. This is logical forgetting, not physical erasure of old
values, embeddings or backups. A separate erasure policy/path is still required.
Only the latest active revision is projected into JAWL
context. A row is projected only while its UTC validity interval contains the
current time. `retention_tier` is one of `short`, `standard`, `long` or
`permanent`; it is policy metadata for the native retention maintenance job and
does not erase append-only history. Ambient promotion uses `standard` and keeps
the observed start time as `valid_from`. Ambient promotion is not automatic in the current manual route and must carry
consent/source metadata. Future JAWL-controlled automatic consolidation after
opt-in is planned; this is not a permanent manual-only product boundary.

Daily consolidation uses the same native table through
`record_daily_journal(day, summary, commitment_ids)`. The deterministic key is
`journal:YYYY-MM-DD`; repeated consolidation revises that row. `commitment_ids`
are bounded references to existing JAWL tasks, not a copied task database.
`list_daily_journal` returns a bounded read-only projection.

## Compatibility transports

`GET/POST /api/chat` and the `HostTerminalClient` remain compatibility paths.
They may be used by legacy clients, but a missing broadcast is not proof of a
completed native turn. New Companion deployments use the correlated Gateway.

The optional VoiceMem/JAWL event directory accepts bounded `SPEAK_INTENT`; JAWL
still decides final wording, DND and tool policy. Raw frames, credentials and
hidden reasoning never cross the public bridge.

For action-bearing ReAct ticks, native JAWL emits ordered safe lifecycle
summaries (`tool.requested`, `tool.started`, `tool.completed`) containing only
bounded action identity and result summary; arguments remain inside JAWL. These summaries may arrive after dispatch or even after the final answer;
their order does not prove pre-dispatch timing. The current loop does not
fabricate `assistant.delta` events: that type is reserved
for a provider-backed streaming implementation.

## Vision execution boundary

`VisionActionPlan` is a proposal, not authority. The Companion execution seam
revalidates its signed observation token and frame digest before each action,
sends each action through the normal HostOS policy executor, and stops on
denied/failed/stale results. Dispatch is not success: a native adapter result
or explicit bounded postcondition verifier must prove the declared condition.
`POST /api/vision/execute` is a session/CSRF-protected explicit bridge for an
already-produced plan and requires `confirm:true`; it does not call a VLM.
When JAWL control mode is enabled, the bridge maps supported actions to native
`HostOSDesktop` skills, so policy and side effects remain in JAWL. Pointer
operations `move`, `click`, `double_click`, `right_click` and `middle_click`,
keyboard `type`/`hotkey` and UIA `click`/`focus`/`set_value` are mapped
explicitly. Unsupported operations fail closed.
