# OBS and desktop-pet presentation

The CLI starts two loopback servers:

- control UI: `http://127.0.0.1:2367/`;
- isolated presentation/OBS surface: `http://127.0.0.1:8766/avatar`.

Port ownership is intentional: `2367` belongs to the Companion control plane,
`8766` to its unprivileged presentation surface, and JAWL's own web console
normally uses `8770`. A WebSocket-only service on another port must not be
opened as a browser URL. The launcher checks both Companion ports before
starting.

The exact presentation URL is printed at startup and copied into the control
panel. The presentation server has no session token, CSRF route, HostOS route,
approval store, chat history or POST endpoint. It exposes only bounded avatar
state, presentation configuration and read-only user-supplied assets.

## OBS setup

1. Start the service with `scripts/run_web.ps1`.
2. In OBS add a `Browser` source.
3. Use the printed `/avatar` URL.
4. Enable a transparent background and set the required canvas size, for
   example 800x800.

OBS is a presentation client, not an authorization boundary. Keep both
servers on loopback and load only trusted local runtime assets. Remote binding
is rejected by default.

The current page is a dependency-free reactive 2D fallback. It displays the
latest bounded subtitle, expression, motion and speaking state. It also uses a
short-lived audio-amplitude signal for mouth movement; no audio bytes are sent
to or stored by the presentation server. Add `?debug=1` to show diagnostics.

## Optional Live2D bundle

The repository does not ship Cubism Core, a model, textures or a runtime. A
licensed user-owned bundle can be supplied below one directory:

```powershell
.\scripts\run_web.ps1 --live2d-assets "G:\AI\Live2D\companion"
```

The bundle must include `model3.json` and a `live2d-runtime.js` exposing:

```javascript
window.Live2DCompanionRuntime = {
  create: async ({canvas, modelUrl}) => ({
    setExpression(name, intensity) {},
    setMotion(name) {},
    setLipSync(amplitude) {}
  })
};
```

`--live2d-model` and `--live2d-runtime` can override the default names. The
backend validates fatal model references (Moc and textures), prevents path
escape and serves the asset tree read-only. Missing optional motions or an
incompatible runtime leave the reactive fallback active. The full asset
contract is in [contracts/avatar.md](contracts/avatar.md).

## Integrated scene and audio ownership

The product requires the same 2D character in the mint Aero control panel,
an optional separate window and OBS. The existing inline CSS figure is a
fallback, not yet a mirror of any installed Live2D model. Load third-party
renderer code only through the isolated presentation boundary, never directly
into the privileged control origin.

Only one selected client plays TTS. OBS/avatar consumes state/amplitude, not
a second audio copy; audio capture in OBS is configured separately. Closing
the panel must not stop backend JAWL tasks, but the current browser microphone
and playback require an open client. A headless audio owner is not implemented.

The window launcher can be inspected independently of a model:

```powershell
.\scripts\run_avatar_window.ps1 -Url 'http://127.0.0.1:8766/avatar?source=pet'
```

This is a browser presentation shell, not proof of native transparency,
click-through or multi-monitor behavior. See [PRODUCT.md](PRODUCT.md).

## Acceptance still required

The isolated server boundary is covered by automated HTTP tests, but release
still requires a real target-machine check for transparent compositing,
click-through/drag behavior, DPI and multi-monitor scaling, OBS capture,
audio ownership and an extended presentation soak. A supplied Live2D bundle
also requires license and runtime compatibility review.
