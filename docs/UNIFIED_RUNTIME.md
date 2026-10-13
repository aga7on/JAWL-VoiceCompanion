# Unified JAWL Companion runtime

Documentation reconciled 2026-10-12. The original10Oct audit was read-only;
new isolated Tera/SDK/owned-console probes are recorded separately, not
whole-profile acceptance. See
[README.md](README.md) for the doc map, [TODO.md](../TODO.md) for the current
queue, and [STATE.md](STATE.md) for evidence and limits.

## Decision

Owned daily/integrated console uses `run_owned_jawl_console.py`: verified
immutable snapshot + explicit process-local HTTP admission extension after
native authentication. It delegates actual send/cancel to the same native
ChatBridge; no second agent loop, storage authority or model owner is created.
ID tombstones/dedup are bounded/ephemeral transport state, not canonical memory
or exactly-once effects. Integrated startup reads back the versioned capability.
Details and remaining cancel limits: [native contract](contracts/jawl.md).

Companion owns each default loopback turn/cancel HTTP socket through connect,
TLS, headers and bounded body. Stop and the absolute deadline abort only that
operation; cancel forwarding has an independent scope. This is adapter transport
ownership, not native model/task authority. Opaque injected openers and actual
selected-model compute release remain separately unaccepted.

The product is one `JAWL Companion` runtime and one user-facing control UI.
JAWL remains the only owner of persona, goals, reasoning, native policy and
canonical memory. VoiceMem is infrastructure behind a bounded sensory and
working-memory adapter, not a second companion or a second memory authority.

VoiceMem may stay in an isolated sidecar because that boundary protects the
JAWL process from heavy model dependencies, crashes and memory pressure. The
logical product boundary is still one runtime: one launcher, one session,
one event correlation path and one lifecycle owner.

## One UI

The product includes an Electron desktop shell with a 3D VRM scene rendered
through three-vrm, alongside the Companion web panel. They are surfaces of one
product, not separate agents. Responsive tablet/phone and LAN access are
product targets; track their implementation and acceptance separately.

The target is one navigation, one chat/history, one avatar scene and one
settings/control area. Voice, ambient audio, memory, access, system and
presence are capabilities of that surface, not separate agents. Backend
attachment support alone does not establish integrated desktop attachment UX.

The current avatar implementation is the Electron VRM scene using three-vrm.
The former Live2D/OBS surface is removed; stale compatibility markers do not
describe an available renderer. Any future isolated presentation surface must
remain read-only and must not receive control-plane credentials/actions or
become a second audio owner.

```text
one launcher/runtime
  -> one control plane and one user UI
  -> one JAWL cognition/policy/memory authority
  -> replaceable sensory, voice and model workers
  -> Electron desktop VRM scene (three-vrm) and Companion web panel
```

## Refactoring rule

Keep modules physically separate when that buys failure isolation, model
replacement or testability. Refactoring means removing duplicate ownership and
manual lifecycle wiring, not flattening every module into one file or process.
The first composition slice is now implemented in
`src/jawl_voicecompanion/composition.py`: component construction moved out of
`__main__.py` while the public `create_server` factory and all adapter
contracts remain compatible. This refactor does not establish whole-product
lifecycle, desktop UX or production-profile acceptance.
