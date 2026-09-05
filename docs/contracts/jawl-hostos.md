# JAWL ↔ HostOS ownership contract

JAWL is the only production authority for model-originated computer actions.
Its native runtime owns ReAct/Heartbeat, the SkillRegistry, HostOS policy,
approvals, audit, cancellation and the emergency stop:

```text
JAWL ReAct / Heartbeat
        ↓ native SkillRegistry
JAWL HostOS / HostTerminal / Debug Broker skills
        ↓ native policy and access level 0..3
Windows, filesystem, processes, desktop and debug providers
```

`ROOT` (level 3) means the capability of the Windows account that launched
JAWL. It does not bypass UAC, the secure desktop, OS ACLs, provider failures,
TTD EULA requirements or external permissions.

## Deployment and product scope

This is one framework's internal boundary, not removal of the agent from the
Companion product. Native additions currently depend on a dirty external JAWL
checkout; a pinned compatible version and owned runtime are not yet accepted.
Do not write or launch state-producing tests in `G:\AI\JAWL-Coding`.

Full Access/unattended is required for the owner's overnight work. A configured
lease must cover and display the requested interval; exact duration/renewal UX
is unfinished. Authorized unattended actions do not need per-action prompts.
A browser closing must not stop backend tasks; browser-owned microphone/audio
is a separate capability. See [PRODUCT.md](../PRODUCT.md).

## Companion bridge

With `--jawl-hostos-control` and a local JAWL console token, the Companion is
the browser/control surface for that native authority:

- level changes are written to JAWL and take effect only after native
  stop/start succeeds;
- unattended mode is represented by JAWL's expiring ROOT autonomy lease;
- emergency stop affects JAWL and Companion-owned work; recovery starts JAWL
  before clearing the local latch;
- `POST /api/hostos/skill` forwards registered `HostOS*` and `HostTerminal*`
  skills to JAWL without copying their wrappers;
- `POST /api/debug/skill` forwards the seven stable Debug Broker skills while
  leaving provider discovery and operation execution in JAWL;
- `GET /api/skills/catalog` reads the current native registry for the HostOS,
  HostTerminal and Debug Broker namespaces without copying or executing it;
- structured memory mutations use JAWL's allowlisted `memory.*` actions;
- Debug Broker remains native and keeps its dynamic provider catalog and
  operation metadata.

Native desktop annotations follow the same matrix: `HostOSDesktop` observation
and bounded waits require `OBSERVER` (1), while pointer, keyboard, UIA action,
window and system-effect methods require `OPERATOR` (2). `ROOT` (3) retains
the full configured native capability set. Native Windows pointer primitives
return bounded cursor-position verification when available; this proves only
that the pointer reached the requested coordinates, not that the foreground
application accepted the input. Vision plans still need an app-level fresh
postcondition for that stronger claim.

The Companion's local executor exists only for explicit standalone/mock or
control-plane-owned compatibility paths. In bridge mode a model-originated
operation must not silently fall back to it. A failed native request is a
visible degraded/error result.

## Native action requirements

Every native side effect must pass the JAWL registry and its decorators. The
effective policy revision, risk/minimum-level metadata, approval decision,
idempotency where applicable and bounded redacted audit result stay in JAWL.
The Companion never receives raw credentials, hidden reasoning, TTD memory or
unbounded tool arguments.

Vision is only an evidence source. The current Companion Vision executor
revalidates the signed token and its frame digest before each action, then
submits one policy-gated desktop request at a time and requires a verified
postcondition. The native JAWL adapter is the intended execution path when
JAWL control mode is enabled; coordinates never authorize an operation.

Automatic process recovery follows the same native boundary: the JAWL
supervisor may restart a crashed instance only while that instance has a
currently valid, bounded ROOT autonomy lease and its current HostOS policy is
enabled at level 3. Manual operator start is a separate explicit transition.
At runtime startup, unfinished one-shot coding approvals are invalidated and
cannot be consumed after the restart; the approval CLI does not perform this
invalidation when merely inspecting the registry.

## External tools

The repository's JAWL reverse-engineering toolchain remains native to JAWL's
Debug Broker. `G:\RE` is an external workspace with sensitive TTD traces;
the Companion does not copy it, accept EULAs, request elevation or invent
replacement wrappers. Provider availability, permissions and licensing are
reported as explicit runtime conditions.

The current exposed catalog covers HostOS/HostTerminal/Debug Broker only.
MCP/browser and other JAWL tools remain in the native agent, but complete
product compatibility needs their own discovery/execution acceptance. Catalog
counts and provider readiness are not proof of every operation executing.
