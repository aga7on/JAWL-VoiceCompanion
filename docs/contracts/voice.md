# VoiceMem Sidecar Contract

Reviewed 2026-10-12. The earlier whole-pipeline evidence is 2026-10-05;
12Oct adds a controlled real Tera CPU cancellation/follow-up probe, not a new
whole-pipeline or device acceptance. Current evidence is in STATE.
GigaAM v3 is the only ASR in the selected product profile. The sidecar's
`feed_audio`/bundled-recognizer interface below is a compatibility transport,
not an alternate accepted Russian ASR. ASR is not an audio captioner or affect
reader. See [README.md](../README.md), [STATE.md](../STATE.md), and
[TODO.md](../../TODO.md).

This contract keeps the heavy VoiceMem runtime outside the JAWL/web process.
The current transport is a subprocess stdin/stdout JSON-lines adapter, not a
network loopback server. The payload contract stays transport-neutral.

## Input

### Selected TTS worker evidence (12Oct)

`runtime/tera-cancel-actual-20261012-r3.json` passed with observed exit0:
CPU24/distilled/ru_f1, scoped cancellation then worker+speech lease idle102.8ms,
three non-silent PCM16 WAVs (complete response1.465–1.859s; RTF0.399–0.482).
The ephemeral listener was proven in the exact owned Windows Job, including
its venv child, and stopped afterwards. Default9889 was not started or changed.
This does not establish transcript accuracy, acoustic quality, precise ONNX
kernel cancellation timing, first-audible/p95, microphone or live duplex.
The earlier RAM SKIP and launcher/listener PID mismatch FAIL remain recorded.

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
sidecar forwards bytes to VoiceMem `stream.feed`; this compatibility surface
does not make VoiceMem a second product ASR. A `type=end_audio` request sends bounded 32 ms
silence frames for up to 0.8 seconds, stopping early when VoiceMem confirms a
turn. Audio is not persisted or included in output events; chunks are limited
to 48 KiB.

The browser microphone adapter has a software noise gate before this contract
is invoked. Shared gate-open/gate-close, silence and pre-roll settings persist
through ConfigHub/revision-checked atomic YAML writes and apply on next capture;
they are not merely browser-local preferences. A closed gate does not enqueue
or transmit PCM. An opening gate includes bounded pre-roll (120 ms default,
0–500 ms configurable); release and hysteresis reduce clipped consonants.
The page exposes instantaneous RMS, peak hold
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

### Cancellation and capture ownership

Final ASR sessions are keyed by capture scope plus utterance ID; ambient and
unleased compatibility voice have separate scopes. The eight-session bound
includes active transcriptions as well as buffered audio. A final-ASR session
cannot be replaced while its transcription is active.

`transcribe(wav_bytes, cancel_event=...)` checks cancellation through `is_set()`;
its per-call child is polled at most every 50 ms and stopped/reaped on cancel
or timeout before transient WAV cleanup. Transcript JSON is capped at 256 KiB;
nonzero process exit is failure even if a JSON file exists. These are process
fixture guarantees, not an accepted real-model cancellation latency SLA.

Successful `/api/voice/capture` release cancels only that capture's final ASR
and drops its buffered sessions. Its deadline-aware token also expires without
requiring a status poll; delayed uploads cannot resurrect a released capture.
`UtteranceBuffer.discard()` cancels one utterance and `close()` cancels all its
owned transcriptions. Ambient `Stop(flush=false)` cancels only its generation;
normal flush drains rather than aborting. Late cancelled transcripts produce
no conversation event or response. Fixture transcribers must accept the
`cancel_event` keyword, even when they do not cooperate, to test stale-drop.

15Oct process teardown correction: Job accounting `ActiveProcesses=0` alone
does not prove descendant process handles are signaled. Owned worker cleanup
retains wait handles after verifying exact Job membership before termination,
and waits for those handles plus empty accounting before closing the Job.
Failed cleanup retains both Job and process wait identities for retry. The
model-free50-run probe observed50 early returns before the fix and zero after;
this is process-lifecycle evidence, not model cancellation latency.

This does not cancel an already admitted JAWL turn or durable goal. Full
in-flight barge-in, actual-model TTS/LLM compute release and descendant-tree containment are
separate B1 acceptance items. Physical microphone and real inference still
require the live checks in TODO.

### Scoped streaming partials

15Oct desktop follow-up: `/app` consumes scoped drafts with generation fences.
Gate onset begins overlap observation instead of immediately cancelling TTS.
Explicit Russian interruption/substantive draft or550ms of voiced PCM can
cancel only the playback owner observed at onset; silence after a short sound
does not accumulate voiced duration. Without drafts this is an acoustic
fallback, not semantic full duplex. Unfinished RU tails extend the silence
window to at least2200ms; punctuation permits a380ms finish window.

`POST /api/voice/end` accepts optional boolean `suppress_backchannel`. Only
literal `true` plus a canonical GigaAM transcript matching a brief explicit
acknowledgement yields `filtered: "user_backchannel"`, empty transcript/events/
responses. Canonical PCM is consumed and scoped partials reset first. A draft
alone never drops audio or creates a durable event. Ordinary non-overlapping
acknowledgements and actual requests keep the existing final-turn path.
Physical microphone/echo and learned turn classification remain unaccepted.

The partial bridge binds one owned child to `(scope_id, session_id)` plus its
capture cancellation token. A new capture or utterance reaps the old child
before spawn; stale reader events cannot mutate the replacement. The raw-PCM
worker protocol has no acknowledged reset, so this isolation currently reloads
the child per utterance. Its real GigaAM latency cost is not yet accepted.

HTTP enqueues only canonical accepted PCM, never writes directly into a stalled
pipe. Raw chunks are48KiB maximum, resampled mono96KiB; queue8 plus one writer
is at most864KiB retained PCM (not total process RAM). Stdout lines64KiB/text4000;
invalid schema/numbers are dropped, oversize/queue overload stops the partial
lane fail-closed without changing the canonical final engine. Retry after a
partial failure requires reset; no hidden spawn loop or fallback ASR.

Capture release and a50ms deadline/token watcher terminate and reap only the
owning child. A failed reap remains tracked and blocks replacement. Terminal
close rejects future feed; scoped reset/old final cannot clear another utterance.
Draft, preface and WS reset authorize the lease and use matching scope/session;
cancellation after snapshot returns an empty cancelled result. These are
17 bridge +9 HTTP fixture tests, including actual HTTP/buffer/bridge/cheap child,
not a model or microphone SLA. Desktop streaming-partial presentation is OPEN.
13Oct code audit confirms `/app` has no draft consumer: `/api/voice/audio` in
canonical external-final mode returns no partial events, and `/api/voice/draft`
is not queried there. A future consumer must be optional, single-inflight and
bounded, bind responses to the captured lease/session/utterance generation,
clear on finalization/stop, and discard stale late results. Draft must never
become durable memory, USER_FINAL or an instruction to the brain.

The alternative Rust capture path has a cancellable upload/final socket worker,
100ms poll, captured generation checks, bounded queue and joined cleanup.
22 unit plus1 CLI test PASS; a stalled upload/final Stop+join is under1s on mock
HTTP. The10s uncancelled upload deadline is not a current Stop delay. Physical
device, real provider/duplex and the whole admitted JAWL turn remain separate.

For an offline VoiceMem cognitive path, the sidecar accepts
`--local-memory`. This injects VoiceMem's local E5 classifier and embedder and
does not make an LLM request; it does not change the selected product ASR. A
separate `warmup` request is exposed through the process client and selected
from the Companion CLI with
`--voicemem-warmup text|audio`; it returns `VOICE_READY` before capture starts.
The current bundled sherpa profile is not accepted as a Russian ASR. Russian
capture uses GigaAM v3 as the only selected ASR; runtime acceptance remains
bounded by the saved evidence cited in STATE.

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

The system-output loopback uses a separate session ID prefixed with
`ambient-audio:`. `AmbientAudioASRBridge` accepts only final transcription
results as `AMBIENT_AUDIO_OBSERVATION`. `USER_PARTIAL` never enters ambient
memory and no ambient event is converted into JAWL `USER_FINAL`, speech or a
tool call. GigaAM v3 remains the only ASR; VoiceMem's bundled acoustic
recognizer is not a production fallback.

Default-output loopback can contain the companion's own TTS. Playback spans
may carry correlation/time metadata for suppression or ducking; this does not
prove reliable per-application source attribution. Ambient Russian speech
uses the same canonical GigaAM v3 ASR behind a separate non-user session.

The ambient final-utterance buffer is bounded; `flush` performs one GigaAM
transcription and retains only returned text. This is intentionally delayed
and must not create a user turn. A VoiceMem recognizer path may remain in the
sidecar compatibility contract, but it is not an accepted ASR selection.

### Speech plus non-speech audio description

ASR is not an audio captioner. A selected bounded clip may be sent through an
optional `AudioDescriptionService` at the same time as final ASR. Its strict
result is:

```json
{
  "kind": "music|sound|speech|unknown",
  "description": "bounded text",
  "tags": ["bounded labels"],
  "mood": "optional bounded text",
  "confidence": 0.0,
  "duration_seconds": 4.2,
  "raw_audio_persisted": false
}
```

The service keeps only normalized text metadata. `mixed` is rejected until an
independent overlap detector is available. A detector-only music candidate is
stored as `sound` with an allowlisted tentative sentence and zero confidence,
never as confirmed `music`. `AmbientMemoryBuffer` stores
it as a second `AMBIENT_AUDIO_OBSERVATION`, with `audio_kind/tags/mood`
metadata and the same ambient-only policy. Invalid provider output, an
overlong clip or a provider failure is dropped/degraded closed. The result is
never `USER_FINAL`, proactive speech or a HostOS request.

The selected ASR is GigaAM v3; no accepted audio-captioning
model is documented here. Qwen2-Audio was a candidate for an isolated benchmark because its
official evaluation covers environmental sound and music analysis and its
documentation recommends short clips; it is not a dependency or production
selection yet. A historical Qwen3-ASR probe on the local `nyan_audio_30s.wav`
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
The canonical microphone ASR is GigaAM v3. The browser has a bounded RMS
activity trigger that requests TTS cancellation once while speech is active;
it does not promote that signal to `BARGE_IN` or `USER_FINAL`. Speech cancel
must preserve JAWL task/checkpoint state. It does not prove provider inference
was cancelled. Neither amplitude nor ambient audio is proof of an operator
instruction.

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

Duplex is a target, not an accepted capability. The documented behavior is
turn-based at the application boundary:

| Capability | Current state | Acceptance needed for live parity |
|---|---|---|
| Microphone capture | Browser PCM16 chunks, local gate, device selection | Real device test with paced speech, noise and recovery |
| ASR | GigaAM v3 is the only engine; final utterance and any configured partial lane are distinct capabilities | Stable partial transcript events and VAD boundaries need their own evidence |
| JAWL response | Native JAWL receives one finalized user turn | Cancellable streaming response with one terminal envelope |
| TTS | Streaming endpoint and latest-request-wins orchestration | First-audible timing and provider cancellation verified |
| Barge-in | RMS can request one TTS cancellation | Speech/backchannel/correction/new-turn classification and no stale audio |
| Conversation mode | Half-duplex turn completion is reliable path | Full-duplex overlap, interruption and restart E2E |

This is therefore not accepted as full duplex. The design remains
compatible with that direction: input, JAWL reasoning and output share a session
and correlation IDs, while the arbiter makes a newer user turn supersede stale
speech and model work. This does not prove provider inference cancellation.
Live parity is not claimed until the duplex interruption row passes on a real
browser/device profile.

## Product acceptance boundary

The complete voice path must preserve JAWL persona/memory/actions, not just
return a WAV from a deterministic responder. See [PRODUCT.md](../PRODUCT.md)
and the [acceptance matrix](../TECHNICAL_AUDIT.md#приёмочная-матрица).
Affect/speaker fields are optional capability slots, not measured mood-reading
features. Real-time quality is endpoint-to-first-audible latency, measured
under paced speech, noise, pauses, interruptions and concurrent ambient load.
