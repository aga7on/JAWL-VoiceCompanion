# Qwen screen + Windows OCR CPU smoke — 2026-10-29

## Result

PASS for the standalone display-capture → Qwen caption + Windows OCR → VA packet
path. This was not a full Companion profile acceptance.

- Started the owned `llama-server` on `127.0.0.1:8994` with Qwen3.5-0.8B Q4,
  `-ngl 0`, `--no-mmproj-offload`, four CPU threads, and RAM/prompt caches off.
- Captured display 0 transiently in memory. The run made 11 captures, 2 submits,
  delivered 1 caption, and had 0 capture errors.
- The brain-bound packet contained distinct `screen` and `ocr` channels;
  Windows OCR returned text. Packet rendering produced 2,563 characters.
- At packet inspection, screen confirmation age was 31 ms and caption age was
  6,250 ms (within the smoke's 8 s max age). The result is recent but already
  approaching its expiry.
- No frame, OCR text, or caption was written to disk. The server was stopped by
  its recorded owned PID; port 8994 was free afterward.

The caption described the broad browser/document scene, but its quoted small text
was corrupted and some UI details were not independently checked. This smoke
proves transport and packet assembly, not detailed visual accuracy, live-profile
uptake, scene-change continuity, or long-run CPU/RAM stability. Reproduction:

```powershell
runtime\jawl-daily-venv\Scripts\python.exe -B scripts\live_qwen_visual_sensor_smoke.py --live --url http://127.0.0.1:8994/v1 --display-index 0 --wait-seconds 35
```

## Launcher follow-up

The daily launcher now treats `-VisualDescriber qwen` as the explicit screen
capture opt-in and supplies `--hostos-live --screen-enabled` even when the legacy
`-EnableScreenWatch` worker is not selected. `-EnableScreenOcr` adds OCR to this
Qwen path; OCR-only configuration without either visual capture path now fails
early instead of being silently ignored. The focused PowerShell-backed launcher
regression passes. OCR remains a separate explicit flag.
