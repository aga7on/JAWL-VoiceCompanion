# OBS avatar surface

The local service exposes a dedicated transparent presentation page at:

```text
http://127.0.0.1:8765/avatar
```

The main control panel at `http://127.0.0.1:8765/` also displays and copies
the same-origin URL, so a non-default port does not need to be entered by
hand.

## Initial setup

1. Start the local service with `scripts/run_web.ps1`.
2. In OBS, add a `Browser` source.
3. Set the URL to `/avatar` from the running service.
4. Enable a transparent page background and choose the canvas size for the
   future Live2D model, for example 800x800.
5. If the placeholder is too small or too large, adjust the Browser Source
   dimensions; the surface scales to its source viewport.

The page is read-only. It polls `/api/state`, displays the latest bounded
response subtitle and maps the response envelope's avatar state/expression to
the presentation. It does not contain a control token and cannot change the
HostOS level, approve tools or trigger desktop actions.

Add `?debug=1` temporarily to show state diagnostics in the upper-left corner:

```text
http://127.0.0.1:8765/avatar?debug=1
```

The current visual is a dependency-free placeholder used to verify the
transparent surface and lifecycle. The next avatar milestone replaces it
with a redistributable or user-supplied 2D Live2D model without changing the
OBS URL or backend ownership boundaries.

## Optional Live2D model

The repository deliberately does not ship a model or Cubism Core. To use a
licensed user-supplied bundle, place its files below one directory, including
`model3.json` and a bundled `live2d-runtime.js`, then start:

```powershell
.\scripts\run_web.ps1 --live2d-assets "G:\AI\Live2D\companion"
```

Custom names can be supplied with `--live2d-model` and `--live2d-runtime`.
The runtime bundle must expose:

```javascript
window.Live2DCompanionRuntime = {
  create: async ({canvas, modelUrl}) => ({
    setExpression(name, intensity) {},
    setMotion(name) {},
    setLipSync(amplitude) {}
  })
};
```

The `/avatar` page loads this adapter only when both files exist. Any missing
or incompatible runtime keeps the placeholder active; add `?debug=1` to see
the fallback reason. Model files are served read-only from the explicit asset
root and are not copied into this repository.

## Explicit screen look

The control panel also exposes an explicit, on-demand vision request. It
captures the focused window through HostOS and sends the transient JPEG to an
OpenAI-compatible endpoint only when all three options are configured:

```powershell
.\scripts\run_web.ps1 --hostos-live --screen-enabled `
  --vision-url "http://127.0.0.1:8000/v1" --vision-model "local-vlm"
```

The endpoint can use an API key from the environment named by
`--vision-api-key-env` (default: `VISION_API_KEY`). The key is never rendered
in the UI or logs. The same frame digest is not sent to the VLM twice unless
the request is explicitly forced; the bridge keeps only a digest and the
bounded last description in memory.

Change detection and cooldown are also available as an explicit opt-in sensor:

```powershell
.\scripts\run_web.ps1 --hostos-live --screen-enabled --screen-watch `
  --screen-watch-interval 10 --vision-url "http://127.0.0.1:8000/v1" `
  --vision-model "local-vlm"
```

The watcher emits bounded events at `/api/vision/events` and never speaks or
calls JAWL directly. Attention/Presence salience, quiet hours and the final
`SPEAK_INTENT` path are still pending, so this mode is a sensor preview rather
than autonomous conversation.
