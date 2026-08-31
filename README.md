# JAWL VoiceCompanion

Local-first Russian-speaking AI companion with a 2D Live2D avatar.

The project combines:

- JAWL for personality, memory, Heartbeat and autonomous reasoning;
- VoiceMem for streaming voice perception and voice-native recall;
- local ASR and TTS providers through replaceable adapters;
- a separate Live2D frontend;
- optional, privacy-gated screen vision and desktop tools.

## Current status

Phase 0 — repository and architecture setup. No runtime integration has been
implemented yet. See [docs/STATE.md](docs/STATE.md) and [TODO.md](TODO.md).

The current Phase 1 slice includes a dependency-free text gateway, local
browser control plane and initial HostOS tool registry. Real JAWL, voice,
Live2D and non-dry-run web actions are still being integrated.

## Run the local slice

```powershell
cd G:\AI\JAWL-VoiceCompanion
.\scripts\run_tests.ps1
.\scripts\run_web.ps1
```

Open `http://127.0.0.1:8765/`. The browser UI starts in HostOS level 0 and
the default executor is dry-run. To explicitly construct a live executor,
provide `--hostos-live` and configure the roots/managed executables; the
approval queue and full production policy are still under development.

To connect the text surface to the local JAWL terminal bridge, pass its
`terminal.port` file:

```powershell
.\scripts\run_web.ps1 --jawl-port-file "G:\AI\JAWL-Coding\src\utils\local\data\interfaces\host\terminal\terminal.port"
```

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
- [docs/contracts/response-envelope.md](docs/contracts/response-envelope.md) — response contract.

The HostOS boundary is specified in [docs/contracts/hostos.md](docs/contracts/hostos.md).

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
