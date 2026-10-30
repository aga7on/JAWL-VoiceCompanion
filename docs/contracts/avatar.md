# Avatar contract: Electron VRM

Reviewed 2026-10-10 (source inspection only; latest saved runtime evidence is
2026-10-05). The current desktop avatar is a 3D VRM model rendered in the
Electron shell with three-vrm (`desktop/app-scene.js`). Live2D/Mocari are not
the current renderer. The old Live2D asset/runtime `/avatar` surface was
removed; residual deprecated routes/markers do not define a supported avatar
API. See [README.md](../README.md), [STATE.md](../STATE.md), and
[TODO.md](../../TODO.md).

## Current behavior

- The desktop scene loads VRM assets from the app's configured VRM model
  directory and supports model swap/wardrobe operations through the desktop
  scene code.
- Expression state maps to VRM expressions. Speech amplitude maps to the VRM
  `aa` expression where available; the signal is amplitude-based, not phoneme
  lip sync.
- Motion and spring-bone/secondary motion are renderer behavior. Their
  presence does not establish complete cloth/body physics or avatar-art
  acceptance.
- The backend serves the app and bounded model assets; asset endpoint presence
  alone does not establish a complete desktop attachment or avatar UX.

## Evidence boundary

The documented code path is not a claim of current runtime/visual acceptance.
Do not describe phoneme lip sync, full duplex voice, or an eight-hour avatar
soak as accepted. Use the current [STATE.md](../STATE.md) snapshot for saved
evidence and its limits.

## Removed Live2D interface

Old versions of this document specified `model3.json`, a user-provided
`live2d-runtime.js`, `window.Live2DCompanionRuntime`, `/api/avatar/config`,
`/api/avatar/audio`, `/api/presentation/state`, and an OBS `/avatar` page.
That specification is historical and is not the current desktop VRM contract.
Do not add or infer new routes from those old examples. Any future isolated
presentation/OBS interface requires a separately reviewed contract and must
remain read-only, bounded, and separate from control credentials/actions.
