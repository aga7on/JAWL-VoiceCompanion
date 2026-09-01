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

## Optional external final ASR

An OpenAI-compatible audio provider may be configured with `--asr-url` and
`--asr-model`. This mode is intended for Qwen3-ASR-0.6B and similar providers
that expose `/v1/audio/transcriptions` but do not guarantee streaming partial
results. While a browser microphone is active, `/api/voice/audio` appends
bounded PCM16 data to one in-memory session and returns `buffered`; it does
not call VoiceMem or JAWL for every chunk. On `/api/voice/end`, the provider
receives one transient WAV, its normalized transcript is passed to
`VoiceMem.stream.feed_partial(text, ended=True)`, and only the resulting
`VOICE_TURN` reaches JAWL. The raw WAV is discarded immediately after the
provider call, including on failure. The multipart request includes the
bounded provider prompt `Transcribe the audio exactly as spoken.` so the local
Qwen profile follows the same instruction as the CPU benchmark.

The external buffer is limited to eight sessions and 4 MiB per utterance, with
a 120-second idle TTL. Audio format cannot change within a session. Health
reports the explicit `final_utterance` mode; it must not be presented as
real-time partial ASR until a provider with a streaming contract is added.

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
An `end_audio` request for a session that has received no audio is a no-op; it
must not initialize the VoiceMem model. If an existing stream fails, the
sidecar evicts that session so the next request can attempt a fresh stream.

The process client reports a bounded local lifecycle state alongside health:
`not_started`, `running`, `degraded` or `stopped`, plus only `running` and the
child PID. It never exposes the executable path, arguments or environment.

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
- a dead or failed sidecar can be observed as degraded and recovered by the
  next request without replaying stale events;
- the JAWL process must not import VoiceMem's audio/model dependency tree.

The repository contains the runner in `services/voicemem_sidecar.py`, the
stdlib client in `src/jawl_voicecompanion/voicemem_client.py` and the web
bridges at `/api/voice/partial`, `/api/voice/audio` and `/api/voice/end`.
The optional external client is in
`src/jawl_voicecompanion/asr.py`; the current microphone path remains an
input adapter. Russian ASR quality, AEC, real-device capture and production
model warmup remain validation work. The browser has a bounded RMS activity
trigger that requests TTS cancellation once while speech is active; it does
not promote that signal to `BARGE_IN` or `USER_FINAL`. VoiceMem still decides
whether the subsequent audio is a valid conversational turn.

The control page also exposes an opt-in `hands-free` mode. It uses a bounded
local RMS silence gate only to call `/api/voice/end` after roughly 800 ms of
silence (with a short minimum speech guard), then keeps the microphone open
under a fresh session ID. The gate does not transcribe, create a user turn or
replace VoiceMem's own VAD; the checkbox is off by default and the manual
microphone stop path remains available.

The optional system-audio lifecycle is exposed separately at
`GET /api/ambient-audio`, `POST /api/ambient-audio/start` and
`POST /api/ambient-audio/stop`. It requires the browser session/CSRF pair and
ambient memory to be enabled before start. Capture is configured but never
started automatically.
