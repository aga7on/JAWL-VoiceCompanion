# VoiceMem Sidecar Contract

This contract keeps the heavy VoiceMem runtime outside the JAWL/web process.
The first transport may be a loopback process adapter; the payload contract
must stay transport-neutral.

## Input

One bounded JSON request per line:

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "type": "feed_partial",
  "session_id": "voice-session",
  "text": "проверь редактор",
  "ended": false
}
```

`text` is the cumulative ASR transcript for the current utterance. The
adapter forwards it to VoiceMem `stream.feed_partial`; it must not send
partial text to JAWL as a complete turn.

## Output events

Partial output:

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "session_id": "voice-session",
  "type": "USER_PARTIAL",
  "payload": {"text": "проверь редактор", "is_final": false}
}
```

Final output:

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "session_id": "voice-session",
  "type": "VOICE_TURN",
  "payload": {
    "text": "проверь редактор",
    "is_final": true,
    "memory_context": "",
    "affect": {},
    "speaker_id": ""
  }
}
```

`VOICE_TURN` is the only event eligible for conversion to JAWL
`USER_FINAL`. `memory_context`, affect and speaker data are observations, not
personality authority or instructions; all fields are bounded and optional.
Raw audio and model internals do not cross this boundary.

## Runtime rules

- one VoiceMem stream is isolated per `session_id`;
- a newer user generation cancels or supersedes stale finalization;
- partial events are droppable, final events are not silently dropped;
- VoiceMem failure returns a bounded degraded event and leaves text chat alive;
- health reports whether the sidecar, ASR and memory engine are ready;
- the JAWL process must not import VoiceMem's audio/model dependency tree.

The current repository defines this contract only. The sidecar runner and
microphone/ASR adapter are Phase 2/3 work and require their own cross-layer
E2E path before being enabled by default.
