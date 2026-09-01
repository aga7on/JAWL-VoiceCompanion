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
5. If the 2D fallback is too small or too large, adjust the Browser Source
   dimensions; the surface scales to its source viewport.

The page is read-only. It polls `/api/state`, displays the latest bounded
response subtitle and maps the response envelope's avatar state/expression to
the presentation. It does not contain a control token and cannot change the
HostOS level, approve tools or trigger desktop actions.

When the control page is open in parallel, its TTS playback sends only a
short-lived amplitude signal to the `avatar_audio` property. This drives the
fallback mouth and the optional runtime's `setLipSync` hook even when OBS uses
a separate browser context; no audio bytes are sent to or stored by this
bridge.

Add `?debug=1` temporarily to show state diagnostics in the upper-left corner:

```text
http://127.0.0.1:8765/avatar?debug=1
```

The current visual is a dependency-free reactive 2D fallback used to verify the
transparent surface, lifecycle and envelope-driven expressions. The next avatar milestone replaces it
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

The model JSON must also reference an existing Moc and at least one texture.
The backend validates those fatal references relative to the model file and
reports the result through `/api/avatar/config`; missing optional motion or
expression files are warnings. The `/avatar` page loads this adapter only
when the bundle is `ready`. Any missing or incompatible runtime keeps the
the reactive 2D fallback active; add `?debug=1` to see the fallback reason. Model files are
served read-only from the explicit asset root and are not copied into this
repository. The complete contract is in [contracts/avatar.md](contracts/avatar.md).

## Explicit screen look

### Local Qwen3-VL-2B endpoint

The supplied CPU/RAM benchmark selected Qwen3-VL-2B Q4_K_M with its matching
F16 mmproj. Start the provider in a separate terminal; the wrapper binds it
to loopback, keeps the model on CPU and validates the external model files:

```powershell
cd G:\AI\JAWL-VoiceCompanion
.\scripts\run_vision_server.ps1
```

The default paths target `C:\Users\ARTEM\vlm-bench`; override `-ServerPath`,
`-ModelPath` and `-MmprojPath` for another installation. The endpoint is
`http://127.0.0.1:8983/v1`, and the model alias is `Qwen3-VL-2B`.

Then start the companion in a second terminal:

```powershell
.\scripts\run_web.ps1 --port 8766 --hostos-live --screen-enabled `
  --screen-max-width 960 --screen-max-height 720 `
  --vision-url "http://127.0.0.1:8983/v1" --vision-model "Qwen3-VL-2B"
```

The endpoint was smoke-tested with `/health`, `/v1/models` and the existing
`OpenAICompatibleVisionClient` against `assets/ui_test.png`. Full-resolution
screen capture remains bounded: the benchmark showed materially higher
latency. The default profile is 960×720 and 1 MB; `screen.observe` also
reports bounded `coordinate_scale` metadata so a later UI action can map
model-image coordinates back to the focused-window rectangle.

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

The watcher emits bounded events at `/api/vision/events`. Attention/Presence
applies salience, DND, cooldown and a bounded budget, exposing proposals at
`/api/vision/intents`. To wake JAWL, pass `--jawl-event-dir` for the active
instance's `.jawl_events` directory. JAWL still decides final wording and
whether to speak; omit the option to keep the sensor local-only.
