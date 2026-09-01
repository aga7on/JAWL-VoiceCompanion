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

## Current terminal response boundary

The JAWL `HostTerminalClient` channel is not a correlated RPC endpoint. A
JSON line sent by the companion queues a user message; a user-facing response
is emitted only when JAWL broadcasts a message through its terminal skill.
There is no turn ID in this protocol. The current adapter therefore consumes
the first broadcast on a short-lived loopback connection and marks a missing
one as `no_broadcast`. The companion returns a validated degraded fallback in
that case. This is intentional: a native JAWL thought with no terminal
broadcast must never be presented as an assistant reply.

A persistent correlated streaming adapter remains a separate integration task;
it requires either a JAWL response ID or a proven web-stream correlation
contract.

## Companion routes

These read-only routes require the normal browser session and CSRF headers:

- `GET /api/jawl/status`
- `GET /api/jawl/overview`
- `GET /api/jawl/memory`
- `GET /api/jawl/persona`

They are inspection surfaces, not a second memory editor. Writes to persona,
traits, drives or facts will be added only after a versioned JAWL write
contract and audit path are agreed.
