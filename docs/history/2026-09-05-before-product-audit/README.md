> Исторический снимок до аудита 2026-09-05. Может содержать неверные статусы и небезопасные команды; не инструкция к выполнению. Актуальны docs/PRODUCT.md, docs/STATE.md и TODO.md в корне проекта.

# JAWL VoiceCompanion

Local-first Russian-speaking AI companion with a 2D Live2D avatar.

The project combines:

- JAWL for personality, memory, Heartbeat and autonomous reasoning;
- VoiceMem for streaming voice perception and voice-native recall;
- local ASR and TTS providers through replaceable adapters;
- a separate Live2D frontend;
- optional, privacy-gated screen vision and desktop tools.

## Current status

Architecture-stabilization release candidate in validation. The repository has
a native correlated JAWL Gateway, isolated control/presentation servers,
JAWL-owned HostOS policy and structured memory, AudioWorklet capture, TeraTTS
transport and signed Vision observation tokens. It is not production-ready
until live JAWL/model/device/OBS acceptance, native tool parity, supervised
lease recovery and soak tests pass.

Read [the technical audit](docs/TECHNICAL_AUDIT.md) before adding features.
[docs/STATE.md](docs/STATE.md) records the current checkout and
[TODO.md](TODO.md) is ordered by remediation priority.

## Run the local slice

```powershell
cd G:\AI\JAWL-VoiceCompanion
.\scripts\run_tests.ps1
.\scripts\run_e2e.ps1
.\scripts\run_web.ps1
```

Open `http://127.0.0.1:2367/`. The browser UI starts in HostOS level 0 and
the default executor is dry-run. In the production-shaped launcher the
avatar/OBS surface is isolated at the printed presentation URL and receives
only minimal avatar state. To explicitly construct a live executor,
provide `--hostos-live` and configure the roots/managed executables; the
approval queue remains available for attended operation. For unattended work,
select ROOT and explicitly enable the browser's autonomous mode; this lets
Heartbeat/background tasks run without a prompt for every action while the
emergency stop and deny-list remain active.

This is a local development profile. Both control and presentation binds are
loopback-only; the presentation origin has no control token or mutation API.
User-supplied Live2D JavaScript is still untrusted code and belongs only in a
reviewed/licensed asset bundle.

If the default port is occupied by another local service (for example a
WebSocket-only MCP service), start the Companion on another loopback port and
use the separately printed presentation URL for the avatar:

```powershell
.\scripts\run_web.ps1 --port 2368
.\scripts\run_avatar_window.ps1 -Url "http://127.0.0.1:8766/avatar?source=pet"
```

`run_web.ps1` checks both the selected control and presentation ports before
starting, rejects equal non-zero ports, and reports the owning process if
either is already occupied.

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

Screen capture defaults to a 960×720 image and a 1 MB transient JPEG. Use
`--screen-max-width`, `--screen-max-height` and `--screen-max-bytes` to tune
the CPU/quality tradeoff; the observation includes bounded coordinate-scale
metadata. Native controls use UIA fingerprints; canvas/custom surfaces can use
the approval-gated `desktop.pointer` fallback, which recalibrates image
coordinates against fresh foreground-window bounds. The matching
`desktop.keyboard` fallback supports bounded Unicode text and hotkeys.

Add `--user-activity` to suppress proactive screen speech while Windows has
recent user input. The signal is limited to idle time and foreground window
class; it does not capture keystrokes, window titles or clipboard contents.

The current Vision benchmark candidates are Qwen3-VL-2B and SmolVLM2-500M;
no permanent VLM dependency is selected yet. This is a benchmark/provider
profile, not a completed autonomous UI grounding loop. The model files remain
outside this repository; the local `llama-server` endpoint can be started with
the repository wrapper:

```powershell
.\scripts\run_vision_server.ps1
```

It binds Qwen to `http://127.0.0.1:8983/v1` using the benchmarked external
files from `G:\AI\VLM-RealTime-Bench\models` and keeps inference on CPU. The
full screen integration command is in
[docs/OBS.md](docs/OBS.md).

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
rights of the Windows account running JAWL. In bridge mode native HostOS skill
and memory requests are sent through JAWL's authenticated control socket; the
Companion fallback executor is used only in explicit standalone/mock mode.
The emergency-stop button also stops native JAWL in bridge mode; the adjacent
resume button starts it again before clearing the local stop.

The same authenticated bridge exposes `POST /api/debug/skill` for JAWL's
stable Debug Broker skills. Provider operations, including the reverse-
engineering tools under `G:\RE`, remain dynamically discovered and executed
inside JAWL; the Companion does not copy or sandbox them a second time.

Canonical structured memory is available through JAWL's `/api/memory` route
and its `memory.remember/revise/forget/archive` control actions. Revisions are
append-only and carry source/confidence/provenance; ambient promotion is an
explicit, consented action and automatic promotion remains disabled.

The CLI keeps a bounded metadata-only HostOS audit at
`runtime/audit.ndjson` by default. It contains policy and lifecycle events,
never command arguments, screenshots, credentials or hidden reasoning. Library
users can pass `--audit-file` or `audit_file` to `create_server` to choose the
path.

The web chat adapter keeps JAWL's typed `/api/companion/stream` SSE open and
sends a correlated `/api/companion/turn` POST. If the web console is omitted,
the companion can use the legacy loopback terminal bridge instead:

```powershell
.\scripts\run_web.ps1 --jawl-port-file "G:\AI\JAWL-Coding\src\utils\local\data\interfaces\host\terminal\terminal.port"
```

The inspection bridge is intended for loopback-only use, filters secrets from
JAWL config and does not duplicate JAWL's durable memory. A missing native
event produces a visible degraded fallback rather than an invented reply.
The public loopback `GET /api/doctor` endpoint provides a bounded first-run
readiness report for JAWL, VoiceMem, TTS, vision, Live2D and HostOS; missing
optional services are reported as degraded while text-only chat remains usable.

For temporary main-model experiments, an OpenAI-compatible chat provider can
be selected without changing the JAWL bridge:

```powershell
$env:TOKENROUTER_API_KEY = "set-this-only-in-your-shell"
.\scripts\run_web.ps1 --port 2367 `
  --llm-url "https://api.tokenrouter.com/v1" `
  --llm-model "z-ai/glm-5.3-free" `
  --llm-api-key-env TOKENROUTER_API_KEY
```

This is a temporary non-agentic brain for model/provider tests. It does not claim
JAWL's persona, durable memory or Heartbeat; use `--jawl-web-url` for the
canonical JAWL conversation path. OpenAI-compatible providers with SSE are
consumed through `/api/chat/stream`; the browser displays deltas immediately
and receives the same final response envelope. QWB-JAWL, GPT Luna and local
providers can replace the JAWL provider without changing the Companion schema.

To enable the external-ASR text bridge through the VoiceMem sidecar, point
the web process at VoiceMem's Python environment:

```powershell
.\scripts\run_web.ps1 --voicemem-python "G:\AI\VoiceMem\.venv\Scripts\python.exe"
```

Если VoiceMem должен работать без сетевого LLM для классификации и embedding,
добавьте `--voicemem-local-memory`. Для удаления cold-start из первого запроса
можно явно прогреть текстовый путь:

```powershell
.\scripts\run_web.ps1 `
  --voicemem-python "G:\AI\VoiceMem\.venv\Scripts\python.exe" `
  --voicemem-local-memory --voicemem-warmup text
```

Для внутреннего VoiceMem audio-VAD используется `--voicemem-warmup audio`;
это может занять заметное время и требует подходящего акустического профиля.
Штатный timeout sidecar по умолчанию составляет 30 секунд и ограничен 120
секундами. Bundled sherpa-профиль VoiceMem не принят как русский recognizer.

The sidecar starts lazily. `POST /api/voice/partial` accepts cumulative ASR
text; only a final `VOICE_TURN` produces a JAWL turn. The control panel also
has an opt-in microphone button: it sends bounded mono PCM16 chunks to
`/api/voice/audio`, and `/api/voice/end` flushes an active phrase. VoiceMem's
own streaming ASR/VAD runs in its separate environment. The browser applies a
configurable local noise gate before that network boundary: closed-gate blocks
are not sent to ASR, a short pre-roll preserves word onsets, and hysteresis
plus release avoids chopping syllables. The control page shows RMS/peak levels
and offers a 1.5-second noise-floor calibration; the setting is kept locally
in the browser. `getUserMedia` also receives AEC/noise-suppression hints, but
this is a pre-ASR software gate, not a guaranteed hardware/driver DSP gate.
Russian ASR quality, AEC and barge-in still require a real-device benchmark.

The selected Qwen3-ASR-0.6B profile can be tested through the optional
final-utterance bridge. The default launcher uses the copied benchmark files
under `G:\AI\VLM-RealTime-Bench\models\qwen3-asr`. Start its CPU server with
`.\scripts\run_asr_server.ps1`, then add `--asr-url
"http://127.0.0.1:8984/v1" --asr-model "Qwen3-ASR-0.6B"` to `run_web.ps1`.
The browser keeps sending small PCM16 chunks, but the Companion buffers one
bounded utterance in RAM and sends it to `/v1/audio/transcriptions` only on
`/api/voice/end`; the resulting text then enters VoiceMem as one final
`feed_partial`. This is deliberately a final-utterance mode, not yet
streaming Qwen partial ASR. Without `--asr-url`, the existing VoiceMem
streaming path remains active.

System-audio capture is separately opt-in. Configure it with
`--ambient-audio --voicemem-python <path>`; enable `--ambient-memory` or the
browser toggle first, then start/stop it explicitly from the browser. The
loopback backend is lazy and missing PyAudioWPatch is reported as degraded;
the browser shows the consent/running state, and system audio never becomes a
user microphone turn.

When `--asr-url` and `--asr-model` are supplied, the ambient bridge reuses the
same bounded `ExternalASRService` for Russian final-utterance transcription.
Ambient PCM remains in memory until the explicit loopback stop, then one
`AMBIENT_AUDIO_OBSERVATION` is created. This avoids using the bundled VoiceMem
sherpa profile as a Russian recognizer. The ambient route is still delayed,
not a partial-ASR or conversational turn path.

Speech transcription and non-speech understanding are separate optional
branches. The `AudioDescriptionService` accepts one bounded transient PCM
clip and can emit a validated `music`, `sound`, `mixed` or `unknown`
description alongside the ASR transcript. No audio-captioning model is
selected in the current installation; configuring one is a later benchmark
step. A description is text-only ambient evidence and cannot create a user
turn or invoke HostOS.

Install the optional Windows backend only when this feature is needed:
`python -m pip install -e ".[system-audio]"`.

Delayed ambient triage is also opt-in. For a local `llama-server` worker, start
the companion with `--ambient-memory`, `--ambient-triage-url` and
`--ambient-triage-model`; for example:

```powershell
.\scripts\run_web.ps1 --ambient-memory `
  --ambient-triage-url "http://127.0.0.1:8991/v1" `
  --ambient-triage-model "Ternary-Bonsai-1.7B"
```

The worker is called by the explicit `/api/ambient-memory/triage` action, or by
an opt-in `--ambient-triage-interval` background scheduler. It receives bounded
text metadata rather than raw media or tools, and must return the validated JSON
schema. Bonsai 1.7B is the first tested profile for this delayed role; it is
not part of the real-time chat loop. Scheduler status is included in the
authenticated `/api/ambient-memory` response.

To enable local CozyVoice REST TTS (start `G:\AI\CozyVoice\rest_api.py`
separately), add its base URL:

```powershell
.\scripts\run_web.ps1 --tts-url "http://127.0.0.1:9888"
```

The panel then requests transient WAV audio after a successful response. TTS
is optional; when unavailable the text path remains usable. The browser uses
sentence-level `/api/tts/stream` first-audio when WebAudio is available and
keeps the whole-WAV endpoint as a fallback.

The selected current TeraTTSv2 worker uses the same `/health` + `/tts` contract:

```powershell
.\scripts\run_teratts_server.ps1 -Port 9889 -Voice ru_f1
.\scripts\run_web.ps1 --tts-url "http://127.0.0.1:9889"
```

Its model release stays outside this repository. The wrapper adds the default
`<ru>...</ru>` language tag, bounds text/voice/speed, and serializes inference
against the loaded CPU model. Tera is the current CPU/Russian quality choice;
voice cloning is intentionally deferred. Companion sentence streaming is
available now, while Tera's lower-level native chunk generator remains a
future optimization.

Qwen3-TTS 12Hz 0.6B Base is available as the explicit local voice-clone
provider. The weights are kept outside this repository at
`G:\AI\tts_models\Qwen__Qwen3-TTS-12Hz-0.6B-Base`; the current reference voice
is `G:\AI\tts_inference\mita_ref_24k.wav` with its transcript. Start the worker
from the dedicated TTS environment, then select it in Companion:

```powershell
.\scripts\run_qwen3_tts_server.ps1 -Port 9890 -Threads 24
.\scripts\run_web.ps1 --tts-url "http://127.0.0.1:9890" `
  --tts-provider qwen
```

The Base clone route is intentionally marked non-emotional until a model
profile proves controllable Russian prosody. The current CPU benchmark is
roughly 19–44 seconds per generated utterance, so TeraTTSv2 remains the
low-latency fallback for live conversation.

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
- [docs/TECHNICAL_AUDIT.md](docs/TECHNICAL_AUDIT.md) — canonical risk audit,
  recovery order and release matrix;
- [docs/RESEARCH.md](docs/RESEARCH.md) — repository study and findings;
- [docs/DECISIONS.md](docs/DECISIONS.md) — accepted architectural decisions;
- [docs/contracts/events.md](docs/contracts/events.md) — event contract;
- [docs/contracts/voice.md](docs/contracts/voice.md) — VoiceMem sidecar contract;
- [docs/contracts/tts.md](docs/contracts/tts.md) — TTS provider and cancellation contract;
- [docs/contracts/llm.md](docs/contracts/llm.md) — temporary chat-provider and JAWL/QWB boundary;
- [docs/contracts/jawl.md](docs/contracts/jawl.md) — native JAWL Gateway and control contract;
- [docs/contracts/response-envelope.md](docs/contracts/response-envelope.md) — response contract.
- [docs/AMBIENT_TRIAGE_BENCHMARK.md](docs/AMBIENT_TRIAGE_BENCHMARK.md) — delayed audio-triage benchmark protocol.

The Live2D bundle contract is specified in [docs/contracts/avatar.md](docs/contracts/avatar.md).
The HostOS boundary is specified in [docs/contracts/hostos.md](docs/contracts/hostos.md).
The JAWL/HostOS ownership boundary is specified in
[docs/contracts/jawl-hostos.md](docs/contracts/jawl-hostos.md).
OBS setup is documented in [docs/OBS.md](docs/OBS.md).

For a dependency-light browser rendering check (installed Edge/Chrome, no
Playwright in the core package), run:

```powershell
.\scripts\run_browser_render_smoke.ps1
```

It checks both the control page and the isolated avatar/OBS DOM, then removes
its temporary browser profile. It does not replace physical OBS/Live2D or
multi-monitor acceptance.
Release build, clean installation and rollback are documented in
[docs/RELEASE.md](docs/RELEASE.md).
Major cross-layer changes must pass the full gate via
`scripts/run_full_gate.ps1`. It runs compilation, all unit tests, the complete
local HTTP E2E suite and a whitespace check. The E2E suite checks the public
HTTP contracts and visible state across chat, voice, TTS, JAWL inspection,
HostOS approvals/audit, screen vision and the avatar asset surface.
Those providers are deterministic fakes. A release or production-integration
claim must also pass the applicable live profiles in the technical audit,
including real browser rendering and target hardware/services.

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
