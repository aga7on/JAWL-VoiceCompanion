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

This is not yet a passive real-time watcher. Change detection, cooldown and
the `SCREEN_DELTA` event are the foundation for that later Attention/Presence
loop; the user must still request each look from the panel in this slice.
