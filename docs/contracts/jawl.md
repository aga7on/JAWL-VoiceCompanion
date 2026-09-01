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

## Companion routes

These read-only routes require the normal browser session and CSRF headers:

- `GET /api/jawl/status`
- `GET /api/jawl/overview`
- `GET /api/jawl/memory`
- `GET /api/jawl/persona`

They are inspection surfaces, not a second memory editor. Writes to persona,
traits, drives or facts will be added only after a versioned JAWL write
contract and audit path are agreed.
