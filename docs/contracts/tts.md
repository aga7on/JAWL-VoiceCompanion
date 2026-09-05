# TTS Contract

The web/JAWL process uses a small provider interface and keeps TTS models in
their own process. The user's desired primary is Qwen3-TTS 0.6B; the existing
12Hz-0.6B-Base worker is a slow CPU clone/quality path. TeraTTSv2 remains the
explicit fast CPU/Russian fallback and is still the CLI default. This mismatch
is tracked in TODO, not silently accepted as a new user choice. Both are
selectable; automatic failover is not implemented. CozyVoice remains a
compatible optional provider and OmniVoice remains unconfirmed.

## HTTP API

`GET /api/tts/status` reports whether a provider is configured. It does not
load the model. `POST /api/tts/synthesize` accepts an authenticated JSON body:

```json
{"text":"Привет. Как дела?", "voice": null, "speed": 1.0}
```

The response is transient `audio/wav`; it is never written to the repository
or durable memory. Text is limited to 4,000 characters and speed to 0.5–2.0.
The adapter sends one TTS-worker request per sentence, runs at most three
sentence requests concurrently, and merges compatible WAV chunks in the
original text order. The provider boundary is model-neutral: selecting or
replacing the TTS model does not change this contract. This endpoint remains
whole-response for compatibility.
The browser may provide a bounded provider-specific `voice` identifier and a
speed from `0.5` to `2.0`; these values do not select or imply a model.

`POST /api/tts/stream` accepts the same authenticated JSON body and returns
`application/x-ndjson`. Each `audio` line contains one bounded base64-encoded
WAV sentence with its source `index`; a final `done` line contains the count.
Sentence jobs are started in parallel (up to three), but lines are emitted in
source order. The browser schedules each WAV in a WebAudio queue and drives
avatar RMS lip-sync from the same nodes, so first audio can play before the
whole reply is ready. This is sentence-level first-audio, not provider-native
token streaming; a very long sentence remains a latency boundary. The browser
falls back to `/api/tts/synthesize` when streaming WebAudio is unavailable.

`POST /api/tts/cancel` accepts the authenticated session/CSRF pair and
invalidates the active synthesis, if any. It is idempotent and returns a
bounded JSON acknowledgement; it does not unload the provider or select a
different model.

## Cancellation and failure

`TTSService` is latest-request-wins. A newer request or explicit cancel marks
the older provider call stale; providers check the cancellation event between
chunks and the service never returns stale audio. A superseded HTTP request
returns `409`. Browser playback cancellation aborts the client request and
then sends the explicit cancel operation.
Provider or malformed-audio failures return `503` and leave text chat usable.

This is currently orchestration cancellation, not guaranteed provider
cancellation. The Tera wrapper holds a lock while generating a complete WAV;
aborting the HTTP consumer can stop playback and suppress stale output but may
leave inference running and block the next request. Production readiness
requires a cancellable worker/process boundary, provider-release timing and a
test proving abandoned generation no longer consumes the synthesis slot.

The compatibility HTTP adapter accepts only the local REST base URL, sends no
API key, and bounds downloaded audio to 8 MiB. The optional
`scripts/teratts_server.py` wrapper exposes the same local `/health` + `/tts`
shape for TeraTTSv2, defaults plain text to a Russian `<ru>...</ru>` span, and
keeps the model release outside the Companion repository. The CLI uses the
explicit `TeraTTSHttpClient` name for this selected profile; the old
`CozyVoiceHttpClient` name remains supported for compatible workers. Tera is
serialized around one loaded CPU runtime;
Tera's lower-level chunk generator is not yet exposed by this whole-WAV
contract. The optional `scripts/qwen3_tts_server.py` wrapper exposes the same
shape for a local Qwen3-TTS Base model and a configured reference voice. Its
reference audio/text are fixed at worker startup; HTTP callers cannot select
arbitrary files. `--tts-provider qwen` selects the explicit
`Qwen3TTSHttpClient` adapter. Qwen Base provides ICL/x-vector voice cloning,
but this worker advertises `emotion_control=false`: emotion instructions are
not silently pretended to work on a cloned Base voice. Qwen's complete CPU
response is a quality/clone path, not a real-time CPU path. OmniVoice has no
confirmed standalone local runtime/API in the current checkout, so it remains
a future provider under the same interface.

The target request also receives a bounded semantic voice style derived from
the strict response envelope. Provider adapters map supported emotion/style
values to native controls and fall back to neutral. Current voice/speed-only
Tera calls do not satisfy the emotional-speech requirement.
