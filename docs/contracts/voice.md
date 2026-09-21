# VoiceMem Sidecar Contract

This contract keeps the heavy VoiceMem runtime outside the JAWL/web process.
The current transport is a subprocess stdin/stdout JSON-lines adapter, not a
network loopback server. The payload contract stays transport-neutral.

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
streaming ASR and VAD choice. A `type=end_audio` request sends bounded 32 ms
silence frames for up to 0.8 seconds, stopping early when VoiceMem confirms a
turn. Audio is not persisted or included in output events; chunks are limited
to 48 KiB.

The browser microphone adapter has a local noise gate before this contract is
invoked. Its threshold is configurable in the control page as a normalized
RMS amplitude and is stored only in browser local storage. A closed gate does
not enqueue or transmit PCM; an opening gate includes at most 120 ms of
bounded pre-roll, and a three-block release plus hysteresis prevents short
consonants from being clipped. The page exposes instantaneous RMS, peak hold
and gate state. `getUserMedia` receives browser AEC/noise-suppression hints,
but the gate cannot promise hardware-level filtering because that depends on
the browser, driver and microphone interface.

The current browser capture uses `AudioWorklet`, flushes the final sample
remainder before `/api/voice/end`, and enforces a hard queued-duration/byte
limit with visible drop/backpressure metrics. The software RMS gate must not
be described as hardware DSP; hardware/driver filtering remains outside this
contract.

## Canonical final ASR (GigaAM only)

GigaAM v3 through the `crispasr` binary in file mode is the **only** ASR engine
(owner decision 2026-09-21). There is no OpenAI-compatible provider option and no
fallback lane: `--asr-url`, `--asr-model`, the Qwen3-ASR/whisper backends and
their servers were removed, because GigaAM won the head-to-head on the same clip
(0.58 s vs 1.19 s) with more accurate Russian, and the removed fallback pointed
at a server the daily profile never started.

While a browser microphone is active, `/api/voice/audio` appends bounded PCM16
data to one in-memory `UtteranceBuffer` session and returns `buffered`; it does
not call VoiceMem or JAWL for every chunk. On `/api/voice/end`, the buffer is
handed to the GigaAM batch transcriber exactly once as a transient WAV. The
normalized final transcript is immediately adapted into a transport-only
`VOICE_TURN` for JAWL; the identical text is enqueued to bounded serialized
VoiceMem enrichment asynchronously. The response does not wait for VoiceMem.
`memory_sync=queued` is not ingestion/recall proof; queue failures, completion and
drops must remain observable. Enrichment must not produce a duplicate
conversational turn. The raw WAV is discarded immediately after the
transcription call, including on failure.

The buffer is limited to eight sessions and 4 MiB per utterance, with a
120-second idle TTL. Audio format cannot change within a session. A missing
transcriber is reported as `unavailable` and a transcriber error as `failed`;
the turn fails explicitly instead of silently borrowing a second engine.
Partials have exactly one owner — the CrispASR streaming bridge; without it
`/api/voice/draft` reports mode `unavailable` rather than silently
re-transcribing the buffer.

For an offline VoiceMem cognitive path, the sidecar accepts
`--local-memory`. This injects VoiceMem's local E5 classifier and embedder and
does not make an LLM request; the acoustic recognizer is still determined by
the configured VoiceMem audio profile. A separate `warmup` request is exposed
through the process client and selected from the Companion CLI with
`--voicemem-warmup text|audio`; it returns `VOICE_READY` before capture starts.
The current bundled sherpa profile is not accepted as a Russian ASR, so Russian
production capture uses the GigaAM final-utterance bridge described above, which
is the single validated Russian provider in this product.

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

Default-output loopback can contain the companion's own TTS. Every playback
span therefore carries a correlation ID/time range and is suppressed or
ducked before ambient ASR; an explicitly separated virtual output device is an
acceptable alternative. The bundled VoiceMem recognizer is not a validated
Russian ambient ASR. Ambient Russian speech uses Qwen3-ASR or another selected
Russian provider behind a separate non-user session.

When the optional `ExternalASRService` is configured, `AmbientAudioASRBridge`
uses it for the ambient session instead of asking VoiceMem's bundled audio
recognizer to decode Russian. PCM is downmixed/resampled and bounded in the
external final-utterance buffer; `flush` performs one ASR request and retains
only the returned text. This is intentionally delayed and must not be used to
create a user turn. Without external ASR, the VoiceMem path remains available
for compatibility and is not accepted as Russian production evidence.

### Speech plus non-speech audio description

ASR is not an audio captioner. A selected bounded clip may be sent through an
optional `AudioDescriptionService` at the same time as final ASR. Its strict
result is:

```json
{
  "kind": "music|sound|mixed|speech|unknown",
  "description": "bounded text",
  "tags": ["bounded labels"],
  "mood": "optional bounded text",
  "confidence": 0.0,
  "duration_seconds": 4.2,
  "raw_audio_persisted": false
}
```

The service keeps only normalized text metadata. `AmbientMemoryBuffer` stores
it as a second `AMBIENT_AUDIO_OBSERVATION`, with `audio_kind/tags/mood`
metadata and the same ambient-only policy. Invalid provider output, an
overlong clip or a provider failure is dropped/degraded closed. The result is
never `USER_FINAL`, proactive speech or a HostOS request.

The current local inventory has Qwen3-ASR but no accepted audio-captioning
model. Qwen2-Audio is a candidate for an isolated benchmark because its
official evaluation covers environmental sound and music analysis and its
documentation recommends short clips; it is not a dependency or production
selection yet. A guarded Qwen3-ASR probe on the local `nyan_audio_30s.wav`
fixture with a non-speech description prompt returned empty text; the ASR
model must not be treated as a captioner based on its speech benchmark.
See the [official Qwen2-Audio repository](https://github.com/QwenLM/Qwen2-Audio).

## Runtime rules

- one VoiceMem stream is isolated per `session_id`;
- a newer user generation cancels or supersedes stale finalization;
- partial events are droppable, final events are not silently dropped;
- queued audio is hard-bounded; overload is reported and starts a fresh
  utterance rather than growing memory without limit;
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
not promote that signal to `BARGE_IN` or `USER_FINAL`. In external-ASR mode,
final normalized ASR text is authoritative; in bundled mode VoiceMem finalizes.
Neither amplitude nor ambient audio is proof of an operator instruction.

The browser arms that cancellation trigger only after a real audio element or
WebAudio buffer source has started playback. A pending TTS request or an
in-flight model generation alone must not cancel speech; this prevents an AEC
leak/noise spike from truncating the first syllable. The playback queue remains
bounded to a small jitter window so an armed interruption can discard the
unsaid tail promptly.

Production barge-in also classifies backchannel, correction, amendment and new
turn before replacing conversational state. Amplitude alone may stop playback
quickly, but it is not sufficient evidence that media/nearby speech is the
operator's new instruction.

The control page also exposes an opt-in `hands-free` mode. It uses a bounded
local RMS silence gate only to call `/api/voice/end` after roughly 800 ms of
silence (with a short minimum speech guard), then keeps the microphone open
under a fresh session ID. The gate does not transcribe, create a user turn or
replace VoiceMem's own VAD; the checkbox is off by default and the manual
microphone stop path remains available.

The optional system-audio lifecycle is exposed separately at
`GET /api/ambient-audio`, `POST /api/ambient-audio/start` and
`POST /api/ambient-audio/stop`. It requires the browser session/CSRF pair and
ambient memory to be enabled before start. Capture is configured but not started automatically in the current launcher.
This is current behavior, not a permanent ban on an explicitly opted-in saved
profile. Long-running ambient capture still needs automatic bounded segment
rotation; the current external-ASR bridge flushes on stop.

## Live/Voice parity status

The architecture has the necessary seams for a duplex voice experience, but the
current reliable behavior is still turn-based at the application boundary:

| Capability | Current state | Acceptance needed for live parity |
|---|---|---|
| Microphone capture | Browser PCM16 chunks, local gate, device selection | Real device test with paced speech, noise and recovery |
| ASR | External ASR receives chunks; final text is authoritative | Partial transcript events and stable VAD boundaries |
| JAWL response | Native JAWL receives one finalized user turn | Cancellable streaming response with one terminal envelope |
| TTS | Streaming endpoint and latest-request-wins orchestration | First-audible timing and provider cancellation verified |
| Barge-in | RMS can request one TTS cancellation | Speech/backchannel/correction/new-turn classification and no stale audio |
| Conversation mode | Half-duplex turn completion is reliable path | Full-duplex overlap, interruption and restart E2E |

This is therefore not yet equivalent to ChatGPT Live/Voice. The design remains
compatible with that direction: input, JAWL reasoning and output share a session
and correlation IDs, while the arbiter makes a newer user turn supersede stale
speech and model work. Live parity is not claimed until the duplex interruption
row passes on a real browser/device profile.

## Product acceptance boundary

The complete voice path must preserve JAWL persona/memory/actions, not just
return a WAV from a deterministic responder. See [PRODUCT.md](../PRODUCT.md)
and the [acceptance matrix](../TECHNICAL_AUDIT.md#приёмочная-матрица).
Affect/speaker fields are optional capability slots, not measured mood-reading
features. Real-time quality is endpoint-to-first-audible latency, measured
under paced speech, noise, pauses, interruptions and concurrent ambient load.
