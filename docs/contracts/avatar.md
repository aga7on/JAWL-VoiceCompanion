# Avatar bundle contract

The companion keeps the avatar renderer optional and small. The backend does
not import Pixi, Cubism or torch; it serves a user-owned asset directory
read-only and the `/avatar` page consumes only bounded presentation state.

The production CLI starts `/avatar` on a separate loopback presentation
origin. It receives only bounded avatar state, subtitle, short-lived lip-sync
values, runtime capability metadata and read-only user-supplied assets; it
cannot fetch control tokens, approvals, HostOS routes, memory or full
conversation state. User-supplied runtime JavaScript is treated as untrusted.
The legacy same-origin presentation option remains a library/development
compatibility mode and is not the production launcher profile.

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

## Lip-sync signal

The control page analyses the currently playing TTS element with a browser
`AnalyserNode` and publishes only a bounded presentation event:

```json
{
  "schema_version": 1,
  "type": "avatar.audio",
  "amplitude": 0.42,
  "speaking": true,
  "timestamp_ms": 1750000000000
}
```

The event is sent through `BroadcastChannel` for low latency and through the
authenticated `POST /api/avatar/audio` route so an OBS/desktop-pet browser
context can recover it from the `avatar_audio` property in `GET /api/state`.
The backend keeps only this short-lived scalar signal, expires it after a
bounded interval and never stores audio. Invalid, out-of-order or stale
signals are ignored by the avatar. A renderer receives the resulting `0..1`
value through `setLipSync(amplitude)`; the dependency-free fallback maps it to
mouth motion.

`GET /api/state` polling is the legacy compatibility path. The isolated
production surface polls only `/api/presentation/state`, a bounded read-only
endpoint; it never polls broad control state. Audio ownership must also be
explicit so OBS/pet remains animated and audible when the control page is
closed.

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
reactive 2D fallback. Add `?debug=1` to see the reason. This makes an incomplete model
an explicit degraded state instead of a blank OBS source.

## Desktop pet launcher

On Windows, `scripts/run_avatar_window.ps1` opens the local presentation
`/avatar` route as an app window and applies a bounded size/position plus
`TOPMOST`. The window has no visible control UI and receives no credential.
Before opening a browser process, the launcher verifies that the URL returns
the Companion's HTML page. If the port belongs to a WebSocket-only service,
it fails with a port-conflict message instead of showing that service's
`Connection: keep-alive` upgrade error. Run the Companion on another loopback
port and pass the matching `/avatar` URL when necessary.
OBS should use the same URL as a Browser Source when transparent compositing is
required; the launcher does not claim that Chromium app windows provide alpha
compositing on every Windows configuration.

## Licensing

The repository does not vendor a model, character art, Cubism Core or a
third-party runtime. Live2D Core is proprietary/redistributable under Live2D
terms; sample characters found in reference repositories have their own
material-license and attribution requirements. Bring a model and runtime
whose terms cover your intended personal, streaming or commercial use.
