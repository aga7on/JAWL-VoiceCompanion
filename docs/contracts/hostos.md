# HostOS Contract

HostOS is the single side-effect boundary for the companion. Model output,
the browser and other services can request actions, but only HostOS may
perform them.

## Access levels

```text
0 SANDBOX  — read/write inside companion sandbox only
1 OBSERVER — bounded host/UI/screen read access; no input or side effects
2 OPERATOR — approved workspace/process/desktop operations
3 ROOT     — full access available to the current Windows user
```

The effective policy is the intersection of:

```text
selected access level
  ∩ tool capability
  ∩ target/application allowlist and deny-list
  ∩ approval policy
  ∩ current session state
```

Level 3 does not elevate the process, bypass the secure desktop or grant
rights beyond the Windows account that launched the companion.

`ROOT` is an OS capability level, not an instruction to ask the operator for
every action. An explicit `UNATTENDED` policy switch may be enabled only at
level 3 so Heartbeat/background work can execute approved tool classes while
the operator is away. Emergency stop and the configured deny-list still win
over unattended execution; downgrading below level 3 disables it.

## Tool request

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "session_id": "session-id",
  "turn_id": "uuid",
  "tool": "desktop.act",
  "risk": "interactive",
  "target": {
    "app": "Code",
    "window": "main.py",
    "element_ref": "opaque-short-lived-ref",
    "element_sha256": "fresh-fingerprint"
  },
  "arguments": {
    "operation": "click"
  },
  "requested_access_level": 2,
  "idempotency_key": "turn-or-action-key"
}
```

`requested_access_level` is informational. The backend uses the active policy
level, never a model-supplied value, to authorize the request.

## Tool result

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "status": "verified",
  "tool": "desktop.act",
  "risk": "interactive",
  "policy": {
    "effective_level": 2,
    "approval": "not_required"
  },
  "result": {
    "summary": "Кнопка нажата и диалог открылся.",
    "postcondition": "dialog_visible"
  },
  "audit_id": "uuid"
}
```

Possible statuses include `denied`, `approval_required`, `dispatched`,
`verified`, `timeout`, `cancelled`, `stale_target` and `degraded`. Emergency
stop cancels tracked managed/shell processes and returns `cancelled` for a
running shell request when its process is terminated.
`dispatched` must not be reported as `verified` unless a bounded postcondition
was observed.

## Screen observation result

The initial `screen.observe` adapter is an explicit focused-window snapshot.
When enabled, its bounded result may contain a transient JPEG for a vision
adapter:

```json
{
  "status": "verified",
  "source": "focused_window",
  "captured_at": "2026-09-01T12:00:00+00:00",
  "window": {
    "class_name": "ApplicationFrameWindow",
    "bounds": [0, 0, 1280, 720]
  },
  "image": {
    "media_type": "image/jpeg",
    "data_base64": "<bounded transient payload>",
    "width": 1280,
    "height": 720,
    "bytes": 420000
  },
  "persisted": false
}
```

The adapter omits the window title, blocks configured sensitive/companion
windows before capture, caps dimensions and encoded size, and does not write
the frame to disk. It is disabled unless the operator explicitly enables the
screen adapter. The optional passive watcher reuses this same adapter and VLM
bridge; it emits only bounded textual events and remains disabled unless
explicitly requested at startup.

## Risk classes

The initial classes are:

- `observe` — read UI state, screen metadata or bounded text;
- `workspace_write` — edit an approved project/workspace;
- `process` — start, stop or inspect a managed process;
- `interactive` — keyboard, mouse, window or browser control;
- `external_effect` — send, publish, purchase or communicate externally;
- `destructive` — delete, overwrite or change system/security state;
- `shell` — execute a command or script.

The user may require approval, deny or allow a class per access level. A
request is evaluated again immediately before execution. Approvals for risky
actions are one-shot and bind the exact tool, target, arguments, policy
fingerprint and expiration time.

The browser exposes the current `unattended`, `deny_tools` and `deny_risks`
values. The model cannot change any of them through a tool request.

## Browser/API requirements

- bind HTTP and WebSocket to `127.0.0.1` by default;
- use a local session token and reject unknown WebSocket origins;
- protect state-changing HTTP requests against CSRF;
- never accept access-level changes as authority inside a tool request;
- expose current mode, pending approvals, emergency stop and audit status;
- treat approvals and unattended state as runtime-only; a fresh server starts
  with no pending approvals and safe default policy;
- optionally persist bounded policy/lifecycle events as metadata-only JSONL;
  command arguments, screenshots, credentials and hidden reasoning are never
  written;
- return bounded, redacted tool results;
- do not persist screenshots or secrets by default.
