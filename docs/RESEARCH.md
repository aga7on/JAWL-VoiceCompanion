# Repository Research

Research snapshot: 2026-09-01. Reference repositories were downloaded as
shallow clones for inspection under `G:\AI\_tmp\companion-repos`.

## JAWL

Upstream/reference: [JAWL](https://github.com/th0r3nt/JAWL)

Relevant strengths:

- event-driven ReAct;
- Heartbeat with wake-up and idle backoff;
- SQL/vector/graph memory;
- traits, mental states and drives;
- subconscious consolidation and reflection;
- Windows UI Automation and guarded desktop actions;
- multimodal hooks and MCP.

Conclusion: use as the cognitive core.

Runtime validation finding: an isolated JAWL instance was started with the
local Ollama endpoint and its real Vector DB embedding cache. The LLM request
completed, but the native cycle returned a thought with no terminal broadcast.
The existing `HostTerminalClient` is therefore an event input plus broadcast
output channel, not a request/response RPC. The companion must preserve a
degraded fallback until a correlated streaming contract is implemented.

## VoiceMem

Upstream/reference: [VoiceMem](https://github.com/xzf-thu/VoiceMem)

Relevant strengths:

- streaming dual-brain design;
- left/right memory separation;
- speculative retrieval while the user is speaking;
- external ASR partial-text integration;
- audio and affect context;
- voice/session memory.

Conclusion: use as a voice and sensory sidecar. Do not allow its right-brain
profile to become a second canonical personality.

Current integration finding: VoiceMem `0.2.3` exposes the useful lightweight
boundary `VoiceMem.stream().feed_partial(text, ended=...)`; partial text does
not require its audio models, and `ended=True` returns a completed `Turn` with
retrieved memory. Its bundled `web/run.py` is a demo WebSocket application,
not a stable sidecar protocol with request correlation. The companion should
therefore put a small loopback adapter/runner around this boundary and keep
VoiceMem in its own environment.

## Open-LLM-VTuber

Repository: [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)

Relevant code patterns:

- provider factories for ASR, TTS, VAD and LLM;
- FastAPI/WebSocket transport;
- sentence-level streaming;
- ordered parallel TTS queue;
- Live2D actions and expressions;
- pluggable Agent interface;
- interruption and audio lifecycle handling.

Important limitation: it is mainly an avatar/voice runtime, not the desired
long-lived cognitive core. Its current long-term memory story is not a reason
to replace JAWL.

## Warashi

Repository: [Warashi](https://github.com/inni918/warashi)

Relevant ideas:

- hard-capped core memory;
- FTS5 deep recall;
- per-character data separation;
- proactive topic pool;
- sleep/quiet mode;
- performance presets;
- first-run setup and character management;
- natural barge-in UX.

Conclusion: borrow product UX and bounded-memory behavior. JAWL's Vector +
Graph remains the richer archival layer.

## Miru

Repository: [Miru](https://github.com/kiyotakali/Miru)

Relevant ideas:

- separate AttentionEngine that creates `speak_intent`;
- salience, deduplication and cooldown;
- screen sensor with change detection;
- VLM significance scoring;
- focused presence instead of constant interruption;
- screenshot disposal after analysis;
- auditable Markdown memory;
- slot-based domains for people, projects, topics and self;
- SleepAgent and daily journal.

Conclusion: add an Attention/Presence layer next to JAWL Heartbeat, but keep
personality and durable state in JAWL.

## Mana

Repository: [Mana](https://github.com/Yuuzulight/Mana)

Relevant ideas:

- Windows local-first voice loop;
- model profiles and health/doctor checks;
- continuous listening with Silero VAD;
- gaming/resource backoff;
- Turn Arbiter with priority lanes and TTL;
- interruption categories: backchannel, correction, amend and new question;
- bounded memory tiers;
- explicit memory tool with patch/remove/archive;
- fact provenance, epistemic kind and valid-time history;
- one tool policy and audit log;
- secret redaction;
- explicit vision tool bridge;
- stale-file checks for edit proposals.

Conclusion: this is the strongest source for implementation safeguards and
Windows product behavior.

## AniCompanion

Repository: [AniCompanion](https://github.com/catsmice/AniCompanion)

The implementation targets macOS and Swift, so its code is not directly
portable to this Windows/Python project. Its useful patterns are:

- frontend as a face in front of a pluggable agent;
- streaming sentence parser;
- emotion tags separated from spoken text;
- ordered TTS playback;
- full-duplex acoustic echo cancellation;
- focused-window screen capture;
- explicit screen consent;
- amplitude-driven lip-sync;
- 3D expression fallback mapping.

Conclusion: borrow the frontend contracts and audio UX, not the platform
runtime. We use Live2D rather than its VRM renderer.

## Soul of Waifu

Repository: [Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu)

Relevant ideas previously inspected:

- psychology and relationship layers;
- episodic topic archive and diary;
- emotional decay;
- neurohormone-like state variables;
- desktop-agent tools and approvals;
- avatar HUD and state presentation.

Conclusion: design reference only for the current project. The repository is
GPL-3.0 and its character/avatar assets have separate terms.

The local `G:\AI\OmniVoice` checkout was also inspected: it contains only a
Python virtual environment, without source, checkpoints, inference entrypoint
or service API. No OmniVoice adapter is claimed until the actual project/model
location is supplied.

## Combined findings

The most important additions to the original plan are:

1. Attention must be a lightweight timing layer separate from deep JAWL
   reasoning.
2. Voice interruption needs semantic classification, not only VAD.
3. Memory needs lifecycle and provenance, not just append-only recall.
4. Every tool needs one policy, approval path and audit record.
5. Screen vision needs passive-sensor and explicit-tool paths.
6. Model health, fallbacks and resource profiles are product features.
7. The first avatar should remain 2D Live2D.

## License and asset notes

JAWL and Open-LLM-VTuber use permissive code licenses in their repositories;
VoiceMem is Apache-2.0. Miru and Mana use Apache-2.0 code, with Mana's
artwork separately restricted. AniCompanion is MIT with third-party assets.
Warashi includes upstream and bundled terms. Soul of Waifu is GPL-3.0.

Do not copy avatar models, voices, backgrounds or sample characters merely
because they are present in a reference repository. Every asset needs its own
license check.
