# Avatar bundle contract

The companion keeps the avatar renderer optional and small. The backend does
not import Pixi, Cubism or torch; it serves a user-owned asset directory
read-only and the `/avatar` page consumes the same response state as the
control panel.

## Required layout

```text
companion-avatar/
  model3.json                 # or a path passed with --live2d-model
  live2d-runtime.js           # path passed with --live2d-runtime
  companion.moc3
  textures/
    body.png
  motions/                    # optional
  expressions/                # optional
```

`FileReferences` in the model JSON are resolved relative to that JSON file.
The backend checks the model, every referenced Moc and every referenced
texture before reporting `ready: true`. Missing motion, expression, physics,
pose or display metadata is reported as a warning and does not make the model
fatal. Invalid paths, traversal and symlink escapes are rejected.

## Runtime API

The runtime JavaScript must expose a tiny global adapter:

```javascript
window.Live2DCompanionRuntime = {
  create: async ({canvas, modelUrl}) => ({
    setExpression(name, intensity) {},
    setMotion(name) {},
    setLipSync(amplitude) {},
    destroy() {}
  })
};
```

The practical reference implementation is the Pixi +
`pixi-live2d-display` path inspected in Mana and Miru. A runtime bundle may
load its local Pixi/Cubism files before creating the model. The wrapper is
deliberately an asset-level plugin: replacing the renderer does not change
JAWL, VoiceMem, HostOS or the OBS URL.

## Diagnostics and fallback

```powershell
.\scripts\run_web.ps1 --live2d-assets "G:\AI\Live2D\companion"
```

`GET /api/avatar/config` exposes only bounded validation metadata:

- `enabled` — model and runtime files exist;
- `ready` — required model files are renderable;
- `validation.missing` — bounded file/type diagnostics without local paths;
- `validation.warnings` — non-fatal setup issues.

When `ready` is false or the runtime throws, `/avatar` keeps the lightweight
placeholder. Add `?debug=1` to see the reason. This makes an incomplete model
an explicit degraded state instead of a blank OBS source.

## Licensing

The repository does not vendor a model, character art, Cubism Core or a
third-party runtime. Live2D Core is proprietary/redistributable under Live2D
terms; sample characters found in reference repositories have their own
material-license and attribution requirements. Bring a model and runtime
whose terms cover your intended personal, streaming or commercial use.
