# Unified JAWL Companion runtime

## Decision

The product is one `JAWL Companion` runtime and one user-facing control UI.
JAWL remains the only owner of persona, goals, reasoning, native policy and
canonical memory. VoiceMem is infrastructure behind a bounded sensory and
working-memory adapter, not a second companion or a second memory authority.

VoiceMem may stay in an isolated sidecar because that boundary protects the
JAWL process from heavy model dependencies, crashes and memory pressure. The
logical product boundary is still one runtime: one launcher, one session,
one event correlation path and one lifecycle owner.

## One UI

The browser is the preferred shell. It is lighter than Electron and already
covers desktop, tablet, phone and LAN access with the existing HTML/CSS/JS
surface. No React, Electron or second desktop application is justified unless
a measured requirement cannot be met by the current frontend.

The user sees one navigation, one chat/history, one avatar scene and one
settings/control area. Voice, ambient audio, memory, access, system and
presence are capabilities of that surface, not separate consoles.

The Live2D/OBS page is a narrow read-only presentation surface. The same
`CompanionRuntime` starts and stops it and the same event path supplies avatar
state. It never owns chat, memory, tools, policy or a second audio output.
Its separate origin is a security boundary for OBS, not a second product UI:
OBS must not receive control-plane credentials or actions.

```text
one launcher/runtime
  -> one control plane and one user UI
  -> one JAWL cognition/policy/memory authority
  -> replaceable sensory, voice and model workers
  -> optional read-only OBS/Live2D presentation surface
```

## Refactoring rule

Keep modules physically separate when that buys failure isolation, model
replacement or testability. Refactoring means removing duplicate ownership and
manual lifecycle wiring, not flattening every module into one file or process.
The first composition slice is now implemented in
`src/jawl_voicecompanion/composition.py`: component construction moved out of
`__main__.py` while the public `create_server` factory and all adapter
contracts remain compatible. The next slice is UI consolidation, not another
cognition layer.
