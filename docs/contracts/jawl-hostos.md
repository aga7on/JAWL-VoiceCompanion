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

The companion also has a separate, lightweight `HostOSPolicy` and
`HostOSExecutor` for its browser/control-plane tools. By default this remains
an independent dry-run or explicitly live path. When the companion is started
with `--jawl-hostos-control`, its level endpoint additionally controls native
JAWL through the authenticated local web console.

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

The control bridge is opt-in and performs one bounded transaction for a level
change: write only the HostOS `enabled`/`access_level` allowlisted fields,
stop the JAWL agent, then start it. A failed stop or start is reported as a
503 and the companion policy is not changed. The JAWL console token is
required even when the JAWL web server itself is configured without a token.
The bridge does not open JAWL databases or duplicate its SkillRegistry.
Model-originated tool calls remain inside JAWL and use its native policy.

`ROOT` is the full capability of the Windows account that launched JAWL. The
companion's `unattended` switch controls only companion-side approvals; JAWL
Heartbeat is already an autonomous native caller and has no equivalent
companion toggle in its current web API. Emergency stop remains local to the
companion until a native JAWL emergency-stop contract is available.

Without the opt-in bridge, companion-side HostOS execution and JAWL-native
execution are two explicitly labelled paths. The browser's
`/api/jawl/hostos` endpoint reports whether control is enabled. With control
enabled, a successful level response includes `jawl_hostos.status =
synchronized`, and the endpoint can verify the restarted native level.

Vision/VLM is unrelated to this ownership boundary and remains provider-neutral
until the operator's CPU/RAM model test selects a model.
