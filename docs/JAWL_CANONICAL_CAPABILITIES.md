# Canonical JAWL capabilities

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
| Native Whisper/Edge/ElevenLabs | JAWL L2 voice interfaces | adapt local Qwen ASR/Tera/Qwen TTS where selected |
| Microphone gate, LAN UI, Live2D/OBS, playback | Companion | own browser/device orchestration |
| Screen/audio sensing and ambient memory | VoiceMem + Companion adapter | bounded sensor input; JAWL remains memory authority |

## Important distinction

JAWL's `thinking_policy` controls provider-side thinking per ReAct step. It is
not the same as the user's conversational mode. The future fast-chat/goal
policy must choose a JAWL request profile while preserving the canonical Goal
manager and context rules. A local environment override such as
`LLM_REASONING_EFFORT=none` is an operational workaround for a provider; it
must not remove Goal, Swarm, SkillCatalog, HostOS or native discovery.

## Voice rule

JAWL's native voice plugins remain available. Local Qwen/Tera services are
providers behind the Companion voice adapter, not a second agent. The adapter
owns capture/gate/playback and forwards only final/approved text to TTS; JAWL
owns identity, goal execution, tools and durable records.
