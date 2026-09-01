# JAWL ↔ HostOS ownership contract

JAWL already contains a native HostOS implementation:

```text
JAWL ReAct / Heartbeat
        ↓ native SkillRegistry
JAWL HostOS skills
        ↓
JAWL HostOSClient / access_level 0..3
        ↓
Windows, filesystem, processes and desktop
```

Its `HostOSClient` loads the configured level at JAWL startup and guards the
native skills. Level 3 is full access available to the Windows account that
launched JAWL; it is not elevation beyond that account.

The companion currently has a separate, lightweight `HostOSPolicy` and
`HostOSExecutor`. That executor is valid for the companion browser/control
plane and its own explicit tools, but `/api/hostos/level` does not yet change
the access level of a running JAWL process. The project must not claim that
these two runtime policies are synchronized today.

## Production target

JAWL remains the canonical executor for JAWL-native model skills. The browser
control plane becomes a session-protected controller for the same authority:

```text
browser / companion UI
        ↓ authenticated local control bridge
JAWL HostOS policy + approval/audit state
        ↓
JAWL HostOSClient and registered skills
```

The current companion bridge exposes only bounded, read-only native HostOS
status. The future control bridge must expose bounded status, level/unattended controls,
approval decisions, emergency stop and structured tool results. It must not
open JAWL databases or duplicate its SkillRegistry. Model-originated tool
calls remain inside JAWL and use the same policy. A single request must be
authorized immediately before execution.

Until that bridge exists, companion-side HostOS execution and JAWL-native
HostOS execution are treated as two explicitly labelled paths. Tests and UI
must not present a companion policy change as proof that JAWL's native policy
changed. The browser's `/api/jawl/hostos` endpoint makes the native status
visible without pretending to synchronize it.

Vision/VLM is unrelated to this ownership boundary and remains provider-neutral
until the operator's CPU/RAM model test selects a model.
