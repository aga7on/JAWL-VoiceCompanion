# VoiceMem Sidecar Contract

This contract keeps the heavy VoiceMem runtime outside the JAWL/web process.
The current transport is a loopback JSON-lines process adapter; the payload
contract stays transport-neutral.

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

For microphone input, the same sidecar accepts bounded mono PCM16 chunks:

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "type": "feed_audio",
  "session_id": "voice-session",
  "sample_rate": 16000,
  "channels": 1,
  "pcm16_base64": "..."
}
```

The browser downsamples microphone data to 16 kHz before sending it. The
sidecar forwards bytes to VoiceMem `stream.feed`, so VoiceMem owns the
streaming ASR and VAD choice. A `type=end_audio` request sends bounded silence
to finish an active phrase when capture is stopped. Audio is not persisted or
included in output events; chunks are limited to 48 KiB.

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

For the process transport, every request is followed by an ASCII-safe
completion marker after all events:

```json
{"type": "request_complete", "request_id": "uuid", "events": 2}
```

Clients must wait for this marker and decode all event lines as UTF-8.

If the sidecar cannot initialize or process a request, it returns a normal
`VOICE_DEGRADED` event instead of exposing an exception or leaking details.

## Ambient system-audio session

The system-output loopback uses the same sidecar transport only through a
separate session ID prefixed with `ambient-audio:`. `AmbientAudioASRBridge`
downmixes/resamples bounded PCM16 and accepts only final `VOICE_TURN` events as
`AMBIENT_AUDIO_OBSERVATION`. `USER_PARTIAL` never enters ambient memory and no
ambient event is converted into JAWL `USER_FINAL`, speech or a tool call.

## Runtime rules

- one VoiceMem stream is isolated per `session_id`;
- a newer user generation cancels or supersedes stale finalization;
- partial events are droppable, final events are not silently dropped;
- VoiceMem failure returns a bounded degraded event and leaves text chat alive;
- health reports whether the sidecar, ASR and memory engine are ready;
- the JAWL process must not import VoiceMem's audio/model dependency tree.

The repository contains the runner in `services/voicemem_sidecar.py`, the
stdlib client in `src/jawl_voicecompanion/voicemem_client.py` and the web
bridges at `/api/voice/partial`, `/api/voice/audio` and `/api/voice/end`.
The current microphone path is an input adapter; Russian ASR benchmarking,
AEC/barge-in and production model warmup remain Phase 2 work.
