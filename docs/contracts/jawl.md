# JAWL bridge contract

Reviewed 2026-10-12 against inspected source/API descriptions; fresh evidence
includes isolated Tera CPU and native SDK/loopback probes, not whole-profile
acceptance. Route names below are version-dependent native
contracts, not a claim that every route or capability passed fresh live
acceptance. See [README.md](../README.md), [STATE.md](../STATE.md), and
[TODO.md](../../TODO.md).

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
`turn_id`; it cannot cancel another turn by text or sequence guess. Cancelling
speech/turn transport must preserve an unrelated durable JAWL task and its
checkpoint; this endpoint is not a task deletion/completion operation.

The Companion parser rejects unknown fields, malformed IDs, oversized payloads,
model-supplied access levels and final events for another turn. JAWL keeps a
bounded persistent native event journal and accepts `JAWL_GATEWAY <event_seq>`
on its terminal transport; the web stream returns cursor metadata and sets
`gap: true` instead of silently claiming an unavailable replay. Corrupt or
unreadable journal state also fails closed as a gap. A native Gateway client
is not an operator CLI session and does not emit terminal-open/close presence
events. This supports replay and duplicate suppression, not exactly-once
native side effects. Before dispatch, the native Goal Ledger records the bounded
action identity as `in_flight`; after a restart it becomes
`needs_reconciliation`, and the next cycle must verify the postcondition before
replay. The verified outcome is then recorded in bounded
`ledger.reconcile_actions` as `confirmed` or `not_applied`; `unknown` keeps the
goal active and completion is rejected. This is a recovery guard, not an
exactly-once syscall claim: mutations still need authority-owned idempotency,
and a crash after dispatch can leave an uncertain outcome.
When provider plans reuse a local id such as `action_1`, reconciliation must
also include the matching `tool`; the ledger preserves unresolved prior intents
instead of allowing a later read or completion plan to overwrite them.

Provider selection stays inside JAWL. QWB-JAWL, GPT Luna, TokenRouter or a
local model must satisfy JAWL's own provider/tool contract; Companion receives
only the native event/envelope.

## Native control routes

### Owned cycle delivery boundary (13Oct)

`scripts/run_owned_jawl_console.py` verifies isolation and the pinned snapshot
before installing `native_jawl_delivery.py` in process. Protected sources remain
immutable. A valid correlated ReAct cycle that returns without a confirmed
native terminal event emits a bounded fixed-reason `turn.error`; ending a cycle
is not itself delivery. Native exceptions propagate, cancellation is preserved,
and this boundary does not finish/delete durable goals or fabricate a reply.

The pinned no-action completion method saves private thoughts in native tick
storage. Its correlated thoughts-as-final envelope is suppressed at the owned
EventBus publication boundary; background tick publication and native status
remain. Only actual successful native terminal delivery counts as an answer.
Failed error emission is not reported as successful delivery. Installation is
process-local/idempotent, not persistent exactly-once execution.

Evidence:11 controlled/snapshot and12 launcher checks on3.14/3.11, actual isolated
console startup/import/auth/cancel probe, full regression844/66/16 plus browser
stages. This is not yet full real-model conversation/latency acceptance; see
[STATE](../STATE.md). The guard removes an indefinite wait after native cycle
termination, not the underlying provider planning failure.

### Correlated context continuation (14Oct)

Native heartbeat formatting intentionally archives the original trigger after
step1 and labels CURRENT as HEARTBEAT. The owned launcher installs
`native_jawl_turn_context.py`: a fixed-size INTERFACES provider registered through
the native registry before native build/compaction. It activates only when the
validated payload turn ID matches the native active-turn accessor. No user text,
private thoughts, permissions or memory state are interpolated into this block.
Background/mismatched contexts remain empty. Native budgets remain authoritative;
tight budgets can truncate this guidance, so retention/model compliance is not
guaranteed by the controlled tests or console import probe.

### Turn admission and cancellation (12Oct)

Synchronous and streaming clients share one admission lock per adapter. Waiters
start no producer/native request before admission. The admitted producer owns
transport cleanup and releases the lock only afterwards; a paused/closed
consumer cannot release an in-flight POST early. Its event queue is bounded
to32; waiting is cancel-aware. Queue/Event allocation precedes admission, and
thread construction/start failures release the lock. Outgoing IDs use the same
strict1–128-character grammar as incoming events: no coercion or truncation.

The turn POST is attempted once. HTTP409/offline, a lost ACK or invalid ACK
does not prove non-admission: native `ChatBridge.send` writes before awaiting
`drain`. Such outcomes are explicit errors, never blind replay. Cleanup sends
best-effort cancellation for that exact ID only. Reconnecting read-only SSE
does not re-submit the turn.

Owned daily/integrated launchers now use `scripts/run_owned_jawl_console.py`.
It validates isolated instance/registry paths, verifies the immutable snapshot,
and explicitly wraps native `make_app` inside that process. Native auth remains
outermost. Only the two Companion POST routes and the read-only capability
endpoint are intercepted; native ChatBridge/Heartbeat/persona/memory/tools remain
the owners. There is no copied brain or protected source patch. The extension
loads directly from its file, not Companion's full import graph. Startup console
tokens are redacted (including split writes); console output is bounded UTF8.

`native_jawl_admission.py` keeps at most1024 ID entries for300s after HTTP cleanup.
Pending entries never expire/evict; capacity fails503 without dispatch. Duplicate
IDs fail409 even after an uncertain ACK. Cancellation records a tombstone before
awaiting native forward, so a readiness waiter or scheduled dispatch task cannot
later send that ID. It checks client disconnect immediately before the pinned
bridge's synchronous write-before-first-await. Bridge acquisition/release is
balanced; body128KiB/1s total, readiness5s, send2s and cancel-forward1s defaults.
Strict IDs/text/unknown fields/duplicate JSON keys fail before native IO.

Cancellation ALWAYS attempts exact-ID native forward, including unknown/expired
HTTP history: missing local history is not proof that a long native turn never
started. `local_dispatch_prevented:true` describes only the local tombstone;
`forwarded` reports bridge ACK, not completed native computation. Authenticated
`GET /api/companion/admission-capabilities` reports the version, actual process
ID, bounds and `durable:false`/`exactly_once:false`. Integrated startup requires
that capability. Direct `python -m src.web.server` lacks this owned extension.

The canonical default HTTP(S) client uses `http_lifecycle.read_scoped` for turn
and cancel POSTs. Each call owns its socket before connect/TLS handshake; an
absolute configured deadline (not a resetting inactivity timeout) covers headers
and body. Turn cancellation aborts only that socket. Cancel forwarding has its
own independent deadline, not the already-set old turn event. No system proxy,
DNS, redirects or mutation replay; TLS certificate verification remains enabled.
ACK bodies remain bounded to128KiB. Cleanup joins the call's watchdog before
returning; the native producer retains its admission lease through cleanup.

OPEN: process restart/TTL/other native transports do not have durable request
idempotency. Cancel ACK or server-observed socket EOF is not compute-release
evidence. Opaque/non-cooperative injected openers may outlive local cancellation:
no forced reap is claimed, and the native producer retains admission until its
transport really settles. Default transport loopback tests do not prove remote
inference/goal/device behaviour.

Native client diagnostics are per-admission-owner fenced: stale consumers,
errors and pre-cancelled waiters cannot overwrite replacement status/error.
The7 diagnostic function tests are explicitly included in the pytest gate.

The previous53-test client/SDK slice is preserved in STATE. New HTTP/entry/
diagnostic boundary tests and actual owned-console probe are also recorded there.
`runtime/llm-cancel-sdk-20261012-r2.json` exercises the pinned native provider
with installed OpenAI SDK3.8.0/httpx0.28.1 against an owned fake loopback server:
preheader/midstream/concurrent-A cancel closes the server-observed connection,
no retry, concurrent-B and same-client follow-up succeed. This does not test
selected model computation, native HTTP admission, durable goal continuity or
acoustic barge-in. See STATE for exact measurements and cleanup evidence.

The two actual selected-Hikari CPU runs did not reach required observed
prefill/generation progress within35s; they are FAIL, not a model release proof.
Owned server cleanup succeeded. The diagnostic harness and limits are in
[LLM_MODEL_CANCEL_BENCHMARK](../LLM_MODEL_CANCEL_BENCHMARK.md). Canonical GPU1,
full JAWL context/persona/task and physical voice acceptance remain unchanged/open.

### Client stream lifecycle (12Oct)

The SSE reader bounds each line and cumulative data packet to128KiB and the
packet queue to64. Overflow/invalid JSON fails explicitly. Header establishment
is limited to1s; the full configured idle read timeout is restored afterwards.
Stop shuts down only its owned socket before buffered close, drains pending
events and joins for1.25s, returning actual thread-exit evidence. Late openers
cannot publish after Stop. A custom opener that ignores timeout can outlive
that join; this is not reported as a reaped thread.36 focused chat/SSE tests
include real loopback stalled responses; remote LLM compute release remains OPEN.

Supervisor process proof uses the exact owned Windows Job, including Python
venv redirector children, not a parent PID guess or membership in any Job.
The query is read-only and fails closed; see the
[Windows API contract](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob).
3 real cheap ownership tests and16 supervisor tests PASS; not whole-profile acceptance.

13Oct: RuntimeSupervisor Windows start/restart uses STARTUPINFOEX/JOB_LIST to
create DEVNULL workers inside the Job before execution, not Popen then assignment.
Only NUL is inherited, not the parent's KILL_ON_CLOSE Job handle. Membership
verification uses the retained creation handle. API failure rejects startup with
no unsafe fallback; POSIX remains unchanged. This is containment, not a sandbox
or policy bypass. Direct PIPE owners and per-worker restart descendant teardown
remain separate OPEN work; see [current evidence](../STATE.md).

Later13Oct: per-worker descendant teardown is now implemented for RuntimeSupervisor
Windows workers via nested global+worker JOB_LIST. TerminateJobObject targets only
the worker; ActiveProcesses0 is required before closing its handle/replacement.
Dead-root generations are cleaned too. Restart teardown errors retain ownership
and refuse replacement. Direct PIPE/POSIX/model cancellation remain separate OPEN
acceptance; latest tests/gate boundaries are in STATE.

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
their order does not prove pre-dispatch timing. The current loop does not fabricate
`assistant.delta` events: that type is reserved for a provider-backed streaming
implementation.

The Companion consumes correlated `assistant.delta` events when a compatible
JAWL build emits them. Each fragment is bounded and checked for internal
control markup, and the joined fragments must match the authoritative
`assistant.final` text before completion. On mismatch or provider failure,
provisional browser text is discarded and never sent to TTS. The pinned
`jawl-20260906-daily-v2` snapshot currently emits only `assistant.final`, so
its live path remains final-response transport followed by bounded
sentence/TTS streaming; this is not token-level realtime evidence.

For a provider that returns a legacy empty action envelope after native work,
the pinned compatibility path may finish a Goal only from durable evidence:
terminal ledger phase, no pending steps/next action/blocker, and `success` for
every outcome in the last action batch. A successful tool result by itself is
not a completion signal; otherwise the Goal remains subject to the normal
bounded repair/block policy.

The same rule applies when a provider explicitly emits Goal Protocol v2
`state=done`: that field is an assertion, not proof. While a Goal is active,
JAWL accepts completion only after a durable terminal ledger patch and a
successful recorded action batch are present. If either is missing, JAWL
rejects the assertion and transitions the Goal to `blocked`; it must never
create a false `complete` state from stale provider context.
Communication-only outcomes such as `HostTerminalMessages.send_message_to_terminal`
or terminal-history reads do not count as that action evidence; at least one
successful non-communication native action must be present.

An active Goal that returns no actions and no explicit `state=wait` is also not
allowed to sleep indefinitely. JAWL requests a bounded provider repair; after
the repair budget it records `blocked`. An explicit Goal Protocol v2
`state=wait` remains the supported way to wait for an external/user event.

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
