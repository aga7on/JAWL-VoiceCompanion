# JAWL VoiceCompanion

Local-first Russian-speaking AI companion with a 2D Live2D avatar.

The project combines:

- JAWL for personality, memory, Heartbeat and autonomous reasoning;
- VoiceMem for streaming voice perception and voice-native recall;
- local ASR and TTS providers through replaceable adapters;
- a separate Live2D frontend;
- optional, privacy-gated screen vision and desktop tools.

## Current status

Phase 4 — 2D Live2D product UI and integration bridges. See
[docs/STATE.md](docs/STATE.md) and [TODO.md](TODO.md).

The current slice includes a dependency-free text gateway, local browser
control plane, initial HostOS tool registry, browser microphone ingress,
optional CozyVoice REST TTS and a transparent avatar surface for OBS. Real
JAWL, production model warmup, Live2D and non-dry-run web actions are still
being integrated.

## Run the local slice

```powershell
cd G:\AI\JAWL-VoiceCompanion
.\scripts\run_tests.ps1
.\scripts\run_e2e.ps1
.\scripts\run_web.ps1
```

Open `http://127.0.0.1:8765/`. The browser UI starts in HostOS level 0 and
the default executor is dry-run. The transparent avatar/OBS surface is at
`http://127.0.0.1:8765/avatar`; the control panel also provides a copyable
same-origin URL. To explicitly construct a live executor,
provide `--hostos-live` and configure the roots/managed executables; the
approval queue remains available for attended operation. For unattended work,
select ROOT and explicitly enable the browser's autonomous mode; this lets
Heartbeat/background tasks run without a prompt for every action while the
emergency stop and deny-list remain active.

If the default port is occupied by another local service (for example a
WebSocket-only MCP service), start the Companion on another loopback port and
use that same port for the avatar:

```powershell
.\scripts\run_web.ps1 --port 8766
.\scripts\run_avatar_window.ps1 -Url "http://127.0.0.1:8766/avatar?source=pet"
```

`run_web.ps1` checks the selected port before starting and reports the owning
process if it is already occupied.

Do not open a `/ws` endpoint directly in a browser. WebSocket routes are
opened by the matching web client; the Companion avatar and control panel use
ordinary HTTP URLs.

Focused-window snapshots stay disabled unless `--screen-enabled` is supplied
alongside `--hostos-live`. The snapshot path is explicit and bounded; it does
not start a passive capture loop. The optional `--screen-watch` flag starts a
bounded `SCREEN_DELTA` sensor only when a live screen adapter and VLM provider
are configured. Attention/Presence then applies salience, DND, cooldown and
budget gates. Add `--jawl-event-dir` with the active JAWL `.jawl_events`
directory to deliver accepted `SPEAK_INTENT` events through JAWL's existing
IPC; without it, intents remain local and inspectable.

To connect the text surface and the read-only inspection panel to JAWL's local
web console, pass its URL:

```powershell
.\scripts\run_web.ps1 --jawl-web-url "http://127.0.0.1:8770"
```

To let the browser's HostOS level selector apply the same level to native JAWL,
provide the JAWL console token and explicitly enable the control bridge:

```powershell
$env:JAWL_WEB_TOKEN = "your-local-console-token"
.\scripts\run_web.ps1 --jawl-web-url "http://127.0.0.1:8770" --jawl-hostos-control
```

Changing the level writes only JAWL's HostOS fields and restarts its agent;
the Companion reports success only after the restart succeeds. ROOT means the
rights of the Windows account running JAWL. The Companion's separate
unattended checkbox does not claim to alter JAWL's native approval policy.
The emergency-stop button also stops native JAWL in bridge mode; the adjacent
resume button starts it again before clearing the local stop.

The CLI keeps a bounded metadata-only HostOS audit at
`runtime/audit.ndjson` by default. It contains policy and lifecycle events,
never command arguments, screenshots, credentials or hidden reasoning. Library
users can pass `--audit-file` or `audit_file` to `create_server` to choose the
path.

The web chat adapter keeps JAWL's `/api/chat/stream` SSE open, sends a
correlated `/api/chat` POST and waits for an agent message with a newer
sequence. If the web console is omitted, the companion can use the legacy
loopback terminal bridge instead:

```powershell
.\scripts\run_web.ps1 --jawl-port-file "G:\AI\JAWL-Coding\src\utils\local\data\interfaces\host\terminal\terminal.port"
```

The inspection bridge remains loopback-only and read-only, filters secrets
from JAWL config and does not duplicate JAWL's durable memory. A missing agent
broadcast produces a visible degraded fallback rather than an invented reply.
The public loopback `GET /api/doctor` endpoint provides a bounded first-run
readiness report for JAWL, VoiceMem, TTS, vision, Live2D and HostOS; missing
optional services are reported as degraded while text-only chat remains usable.

To enable the external-ASR text bridge through the VoiceMem sidecar, point
the web process at VoiceMem's Python environment:

```powershell
.\scripts\run_web.ps1 --voicemem-python "G:\AI\VoiceMem\.venv\Scripts\python.exe"
```

The sidecar starts lazily. `POST /api/voice/partial` accepts cumulative ASR
text; only a final `VOICE_TURN` produces a JAWL turn. The control panel also
has an opt-in microphone button: it sends bounded mono PCM16 chunks to
`/api/voice/audio`, and `/api/voice/end` flushes an active phrase. VoiceMem's
own streaming ASR/VAD runs in its separate environment. Russian ASR quality,
AEC and barge-in still require a real-device benchmark.

System-audio capture is separately opt-in. Configure it with
`--ambient-audio --voicemem-python <path>`; enable `--ambient-memory` or the
browser toggle first, then start/stop it explicitly from the browser. The
loopback backend is lazy and missing PyAudioWPatch is reported as degraded;
the browser shows the consent/running state, and system audio never becomes a
user microphone turn.

Install the optional Windows backend only when this feature is needed:
`python -m pip install -e ".[system-audio]"`.

To enable local CozyVoice REST TTS (start `G:\AI\CozyVoice\rest_api.py`
separately), add its base URL:

```powershell
.\scripts\run_web.ps1 --tts-url "http://127.0.0.1:9888"
```

The panel then requests transient WAV audio after a successful response. TTS
is optional; when unavailable the text path remains usable.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The critical boundary is that JAWL remains the one canonical personality and
VoiceMem remains a sensory/memory sidecar. The project uses a separate
Attention/Presence layer for inexpensive timing decisions and a Turn Arbiter
for cancellation and priority.

## Development documents

- [AGENTS.md](AGENTS.md) — rules for agents and contributors;
- [TODO.md](TODO.md) — active work and acceptance criteria;
- [docs/STATE.md](docs/STATE.md) — current state and blockers;
- [docs/RESEARCH.md](docs/RESEARCH.md) — repository study and findings;
- [docs/DECISIONS.md](docs/DECISIONS.md) — accepted architectural decisions;
- [docs/contracts/events.md](docs/contracts/events.md) — event contract;
- [docs/contracts/voice.md](docs/contracts/voice.md) — VoiceMem sidecar contract;
- [docs/contracts/tts.md](docs/contracts/tts.md) — TTS provider and cancellation contract;
- [docs/contracts/jawl.md](docs/contracts/jawl.md) — read-only JAWL bridge contract;
- [docs/contracts/response-envelope.md](docs/contracts/response-envelope.md) — response contract.
- [docs/AMBIENT_TRIAGE_BENCHMARK.md](docs/AMBIENT_TRIAGE_BENCHMARK.md) — delayed audio-triage benchmark protocol.

The Live2D bundle contract is specified in [docs/contracts/avatar.md](docs/contracts/avatar.md).
The HostOS boundary is specified in [docs/contracts/hostos.md](docs/contracts/hostos.md).
The JAWL/HostOS ownership boundary is specified in
[docs/contracts/jawl-hostos.md](docs/contracts/jawl-hostos.md).
OBS setup is documented in [docs/OBS.md](docs/OBS.md).
Major cross-layer changes must pass the full gate via
`scripts/run_full_gate.ps1`. It runs compilation, all unit tests, the complete
local HTTP E2E suite and a whitespace check. The E2E suite checks the public
HTTP contracts and visible state across chat, voice, TTS, JAWL inspection,
HostOS approvals/audit, screen vision and the avatar asset surface.

## Planned runtime layout

```text
services/
  jawl_gateway/       JAWL adapter and local API
  voicemem_gateway/   VoiceMem adapter and streaming events
  voice_gateway/      microphone, VAD, ASR, playback and barge-in
  tts_worker/         CozyVoice 2 / OmniVoice providers
  screen_sensor/      UIA, screenshot policy and VLM bridge
src/
  attention/          Presence and salience decisions
  orchestration/      Turn Arbiter and response lifecycle
frontend/
  live2d/             2D avatar and desktop UI
tests/
docs/
```

## License note

This repository contains project documentation and new code only. JAWL and
VoiceMem remain separate upstream projects. Soul of Waifu is used as a design
reference; its GPL-3.0 code and third-party character assets are not copied.
