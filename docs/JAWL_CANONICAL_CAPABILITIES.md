# Canonical JAWL capabilities

Status reviewed 2026-10-10 (read-only). Latest saved runtime evidence is
2026-10-05. This table describes ownership and configured selections, not
acceptance of every capability. See [README.md](README.md), [STATE.md](STATE.md),
and the current work queue in [TODO.md](../TODO.md).

## Boundary

`G:\AI\JAWL-Coding` is read-only reference/upstream. The pinned snapshot
under `runtime/jawl-sources/` is the reproducible runtime copy used by managed
profiles. Companion must not reimplement JAWL cognition when a native module
already provides it.

This is an ownership rule, not a blanket overwrite rule. Before adopting an
upstream behavior, compare the two contracts and keep the implementation that
is safer, more complete, or more suitable for the companion. Use an adapter
when both surfaces must remain available; never delete a superior Companion
capability merely to make the code look like JAWL. Every such decision needs a
regression test and a short rationale in the audit or CHANGELOG.

| Capability | Canonical owner | Companion responsibility |
|---|---|---|
| Persona, SOUL, drives and mental state | JAWL L0/L1/context | select profile and render state |
| Goals, task ledger, checkpoints, recovery | JAWL `GoalManager`/`GoalSkills` | expose chat/voice/UI commands |
| ReAct, thinking policy, context compaction | JAWL `ReactLoop`/`ContextBuilder` | pass transport metadata; never leak reasoning to TTS |
| Heartbeat/EventBus | JAWL `Heartbeat` | feed bounded sensor events and display status |
| SkillCatalog, HostOS, native discovery | JAWL | preserve the complete registry and policy 0–3 |
| Swarm, ToT, subconscious | JAWL | expose configuration and lifecycle status |
| Native Whisper/Edge/ElevenLabs | JAWL L2 voice interfaces | adapt the selected local TTS provider; GigaAM v3 is the only Companion ASR |
| Microphone gate, LAN UI, Electron/three-vrm avatar, playback | Companion | own browser/device orchestration |
| Screen/audio sensing and ambient memory | VoiceMem + Companion adapter | bounded sensor input; JAWL remains memory authority |

## Important distinction

JAWL's `thinking_policy` controls provider-side thinking per ReAct step. It is
not the same as the user's conversational mode. The future fast-chat/goal
policy must choose a JAWL request profile while preserving the canonical Goal
manager and context rules. A local environment override such as
`LLM_REASONING_EFFORT=none` is an operational workaround for a provider; it
must not remove Goal, Swarm, SkillCatalog, HostOS or native discovery.

## Voice rule

JAWL's native voice plugins remain available. TeraTTSv2 (`ru_f1`, port 9889)
is the selected default; OmniVoice is selectable, without an accepted provider
quality/capability claim. GigaAM v3 is the sole ASR. The adapter owns
capture/gate/playback and forwards final text to JAWL; ASR is not a captioner
or affect classifier. JAWL owns identity, goal execution, tools and durable
records. Speech cancellation must preserve the task checkpoint; it does not
assert real provider-worker cancellation.
