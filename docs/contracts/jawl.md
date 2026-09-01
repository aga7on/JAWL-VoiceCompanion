# JAWL bridge contract

The companion treats JAWL as the only owner of persona, traits, drives,
Heartbeat and durable memory. The companion never opens JAWL's SQLite,
Vector or Graph stores directly.

## Optional connection

The web bridge is enabled with:

```powershell
.\scripts\run_web.ps1 --jawl-web-url "http://127.0.0.1:8770"
```

The optional JAWL console token is read from `JAWL_WEB_TOKEN` (or the
variable named by `--jawl-web-token-env`). Only loopback URLs are accepted.

## Read-only upstream routes

The adapter consumes these existing JAWL routes:

| Route | Use |
|---|---|
| `GET /api/agent/status` | process health |
| `GET /api/tick` | Heartbeat phase and current step |
| `GET /api/db/stats` | bounded SQL/vector/graph counters |
| `GET /api/drives` | bounded drive summary |
| `GET /api/config` | selected persona/Heartbeat settings |

`/api/config` is filtered to a small allow-list. Environment values, API
keys, provider URLs and unknown fields never cross into the companion API.
Drive objects are also reduced to a fixed field allow-list and bounded
description before reaching the browser.
The bridge keeps no durable copy and returns `offline`/`degraded` when JAWL
is unavailable.

## Correlated web chat

When `--jawl-web-url` is configured, the companion uses these existing JAWL
routes for user turns:

| Route | Use |
|---|---|
| `GET /api/chat/stream` | SSE status and bounded message events |
| `POST /api/chat` | enqueue one user message and return its `message.seq` |

The adapter opens the SSE first, waits for the bridge to report `online`, then
sends the POST. It returns the first non-`User` message whose `seq` is greater
than the acknowledged user sequence. This filters history and other earlier
turns without opening JAWL's `history.json` or databases. A stream failure,
missing acknowledgement or missing agent message becomes a validated
degraded fallback; the observable chat status is `connected`, `offline`,
`cancelled` or `no_broadcast`.

## Legacy terminal response boundary

The JAWL `HostTerminalClient` channel remains an uncorrelated compatibility
transport. A JSON line sent by the companion queues a user message; a
user-facing response is emitted only when JAWL broadcasts a message through
its terminal skill. The legacy adapter consumes the first broadcast on a
short-lived loopback connection and marks a missing one as `no_broadcast`.
This path must never present a native JAWL thought with no terminal broadcast
as an assistant reply.

The web adapter is preferred when its URL is supplied because its sequence
acknowledgement provides the stronger correlation boundary.

Before either JAWL transport returns text, the companion removes paired
`<think>`, `<analysis>`, `<reasoning>`, `<reflection>` and tool-control blocks.
An unclosed block or line-level internal marker is rejected as
`invalid_response` and becomes the normal degraded fallback; internal text is
never forwarded to the response envelope or TTS.

## Companion routes

These read-only routes require the normal browser session and CSRF headers:

- `GET /api/jawl/status`
- `GET /api/jawl/overview`
- `GET /api/jawl/memory`
- `GET /api/jawl/persona`

They are inspection surfaces, not a second memory editor. Writes to persona,
traits, drives or facts will be added only after a versioned JAWL write
contract and audit path are agreed.

The unauthenticated loopback `GET /api/doctor` surface is separate from JAWL
inspection. It reports bounded readiness states for all configured components,
with `text_mode_available=true` whenever the companion gateway can still serve
the deterministic text path.

## Proactive event IPC

The optional screen watcher can deliver accepted `SPEAK_INTENT` events to an
explicit JAWL `.jawl_events` directory with `--jawl-event-dir`. The companion
writes the same `{message, payload}` shape used by JAWL's `framework_api.py`
and performs an atomic rename. The payload is bounded to a screen summary,
significance and correlation metadata; it contains no image or local path.
Omitting the option keeps Attention/Presence local-only. This wakes JAWL's
existing event/Heartbeat path but does not bypass JAWL's final wording, DND or
tool policy.

The file shape and downstream routing were verified on 2026-09-01 in an
isolated temporary directory using JAWL's actual `DaemonsPoller`, `EventBus`
and `EventBridge` classes: one sink file was consumed, one
`HOST_OS_SANDBOX_EVENT` reached `Heartbeat.answer_to_event`, and the bounded
payload contained no image or local path. This proves IPC acceptance, not a
spoken reply. A final user-facing message still depends on the active JAWL
ReAct model calling its terminal-message skill; a local production-profile
smoke previously completed the LLM request without such a broadcast and is
therefore reported as `no_broadcast`.
