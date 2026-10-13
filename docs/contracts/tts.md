# TTS Contract

Reviewed 2026-10-11. Latest saved real-model runtime evidence is 2026-10-05;
current synthetic/HTTP ownership evidence is in STATE. Selected default:
TeraTTSv2 `ru_f1` at port 9889. OmniVoice is a
selectable provider option; that selection is not evidence of a distinct
validated runtime, quality, or cancellation capability. See [README.md](../README.md),
[STATE.md](../STATE.md), and the active queue in [TODO.md](../../TODO.md).

The web/JAWL process uses a provider interface; worker/model deployment is
profile-specific. Tera is the selected default. OmniVoice is selectable, while
its runtime capabilities and provider quality remain unaccepted. Do not
reintroduce Qwen as a selected default based on old plans. Automatic failover
is not implemented unless a current source contract explicitly says otherwise.

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
legacy web client can fall back to `/api/tts/synthesize`; desktop `/app` uses
the stream path and reports failure instead of silently switching to whole-WAV.

Both synthesis endpoints accept an optional `request_id`: 1–128 ASCII letters,
digits, underscores or hyphens, starting with a letter/digit. Clients MUST use
a unique ID per playback (desktop uses `crypto.randomUUID()`), not reuse it.
`POST /api/tts/cancel` requires the usual session/CSRF pair. With
`{"request_id":"speech-unique-id"}` it signals only that request, even if the
cancel POST arrives before the stream POST. `{}` preserves explicit global
speech Stop for compatibility; invalid, empty or null IDs return `400`, never
fall through to global Stop. Cancellation does not cancel a durable JAWL goal,
unload a provider or change models.

The transient registry stores at most128 events/IDs, no text/audio. Active
entries cannot be evicted; completed/cancel-before-start tombstones last60s.
Replaying a completed ID within that window does not start synthesis; a
duplicate active ID is rejected. Saturation returns `503`, without discarding
another request's cancellation token. This is bounded replay protection, not
durable exactly-once or a guarantee for arbitrarily delayed requests.

## Cancellation and failure

Before waiting for governor admission, a new `TTSService` request reserves the
latest intent and cancels the previous one. A superseded waiter cannot publish
later. Admission waits at most2s by default (configurable0.05–10s), checking
cancellation at least every50ms; an unrelated governor owner is never stolen.
A pre-cancelled/replayed ID does not supersede the current response. Explicit cancel
also invalidates active synthesis. Whole-response cancellation returns `409`;
an already-started NDJSON stream reports cancellation in-band while its HTTP
status remains `200`. Desktop `/app` stops local sources/aborts its fetch and
sends an independent authenticated, keepalive scoped cancel (timeout1.5s),
without awaiting it. Successful `done` sends no cancel; a request not yet
dispatched sends none. Old cleanup cannot target a replacement UUID. The
request-ID path works before the first audio chunk with a cooperative provider;
bare disconnect detection without this POST is still OPEN. Cancellation while
an HTTP opener awaits provider headers depends on the worker: selected Tera now
has a correlated worker endpoint; legacy/uncooperative workers do not.
Provider or malformed-audio failures return `503` and leave text chat usable.

Service cleanup targets the owning generation. HTTP adapters expose
`cancel_generation(cancel_event)`, tracking responses by event identity and
shutting down only the matching connection before closing its body. This
unblocks an actual local incomplete-body read without waiting for the provider
timeout. Responses that return from the opener after cancellation are closed
and untracked in finally. Stale finalizers never cancel a replacement stream.
For a legacy no-argument provider cancel hook, ownership publication and the
global hook are serialized; that hook must itself be bounded. Explicit
`TTSService.cancel()` remains global for its speech service, not for JAWL goals.

Vox generation cancellation closes only its transport and does not send the
worker's unscoped `/cancel`, which could hit another generation. Actual worker
compute cancellation needs a correlated worker request API. A generation lease
holds its captured governor slot until all local provider calls actually return,
even if its consumer has already cancelled. A paused audio consumer with no
active computation is superseded without retaining that slot; its native
iterator is closed before transfer. Late cleanup cannot close that iterator
twice or release the replacement's slot. Native factory/next calls are counted
too. Service close is idempotent, rejects new work and wakes admission waiters;
replacing the governor while leases exist is rejected. This tracks local calls
and transports, not a remote worker's unknown compute lifetime.

Optional prosody planning has at most one in-flight planner thread per service.
A busy planner degrades the next reply to neutral; cancelled streams stop
waiting without awaiting its network timeout. The planner's actual request
still relies on its bounded timeout: remote compute cancellation is OPEN.
17 focused admission tests plus28 provider/service,13 registry/service/HTTP
and7 desktop Node cases are fixture evidence, not a
real-model release-time SLA. Actual TTSService + governor + HTTP tests prove
scoped first-chunk cancel, early cancel, replay drop, authorization and a late
old cancel not stopping its replacement. The browser tone fixture intentionally
ignores scoped cancel to emit stale data and verify client rejection; it is not
evidence of worker cancellation.

## Selected Tera worker cancellation

`TeraTTSHttpClient` allocates a unique worker UUID per sentence before opening
`/tts`; a service generation can own several sentence IDs. At most16 requests
are registered in this adapter. `cancel_generation(event)` targets only IDs
belonging to that event, via `POST /cancel {"request_ids":["uuid"]}` in batches
of at most8. Control POST uses a1s socket timeout and does not wait for a body;
it is best-effort, not a wall-clock release guarantee. Failed requests also
cancel their own ID; successful cleanup sends none. Cozy/Qwen payloads remain
unchanged, and Vox does not inherit this Tera-specific worker protocol.

The owned `scripts/teratts_server.py` now supports scoped cancel-before-start
and queued cancellation. Its transient ID registry is128 entries/60s; at most8
requests are admitted (running + waiting), queue wait is10s, and a120s timer
signals the request's cancellation. Active capacity is released only when the
owning synthesis actually leaves its function, not just when a browser aborts.
Runtime close atomically rejects new admission and signals every owned active
and queued token. Repeated/concurrent close is safe. Standalone shutdown calls
runtime close before server close; daemon handlers do not keep shutdown waiting
indefinitely for uninterruptible native work. It is not a forced mid-WORLD kill.
The standalone worker binds loopback only and rejects browser Origin POSTs;
LAN clients use the authenticated Companion gateway, not an exposed TTS port.

Owned `CancellableSession` proxies attach a fresh `RunOptions` to every current
Tera/RUAccent synchronous ONNX run. A request Event sets `terminate` only on
its active options; ContextVar isolates concurrent request threads. Native
termination becomes `InferenceCancelled`, while unrelated model failures remain
failures. The API basis is [ONNX Runtime RunOptions](https://onnxruntime.ai/docs/api/python/api_summary.html#onnxruntime.RunOptions.terminate).
Frozen LoadedTTS and the four RUAccent neural holders are shallow-copied;
shared native sessions, dictionaries, model selection and external source are
not patched. Unknown accent layouts/alternate run interfaces fail closed.
External release imports disable bytecode writes.

8 proxy and13 worker tests exercise these paths, including real service +
governor + adapter + worker HTTP before headers, with fake native computation.
Separate native acceptance uses a generated372-byte CPU ONNX Loop graph on
ORT1.29.0/Python3.11.15: A stopped4.494ms after cancellation, B continued until
its own cancel, and a follow-up on the same native session succeeded. Report:
`runtime/onnx-cancel-acceptance-20261011.json`. This is native-kernel fixture
evidence, NOT Tera weights, RU voice quality, p95, or a model release-time SLA.

Tera still returns a complete WAV per sentence. ONNX termination is cooperative
at runtime/kernel boundaries; monolithic WORLD/postprocessing calls cannot be
interrupted mid-call by this token, only before/after their stage. A120s signal
therefore is not a hard process-kill deadline. Existing running workers need
controlled owned restart and capability readback (`cancel_capability` =
`scoped_onnx_run_options`); a code patch does not activate it in an old process.
Real Tera release timing, actual-model replacement latency, bare disconnect and
other providers' compute cancellation remain required before B1 acceptance.

The compatibility HTTP adapter accepts only the local REST base URL, sends no
API key, and bounds downloaded audio to 8 MiB. The optional
`scripts/teratts_server.py` wrapper exposes the same local `/health` + `/tts`
shape for TeraTTSv2, defaults plain text to a Russian `<ru>...</ru>` span, and
keeps the model release outside the Companion repository. The CLI uses the
explicit `TeraTTSHttpClient` name for this selected profile; the old
`CozyVoiceHttpClient` name remains supported for compatible workers. Tera is
serialized around one loaded CPU runtime;
Tera's lower-level chunk generator is not yet exposed by this whole-WAV
contract. The Qwen3-TTS wrapper/adapter remains an explicit source-level,
non-default option; it is not the selected product TTS profile or evidence of
accepted provider quality. The optional `scripts/qwen3_tts_server.py` wrapper
exposes the same shape for a local Qwen3-TTS Base model and a configured reference voice. Its
reference audio/text are fixed at worker startup; HTTP callers cannot select
arbitrary files. `--tts-provider qwen` selects the explicit
`Qwen3TTSHttpClient` adapter. Qwen Base provides ICL/x-vector voice cloning,
but this worker advertises `emotion_control=false`: emotion instructions are
not silently pretended to work on a cloned Base voice. Qwen's complete CPU
response is a quality/clone path, not a real-time CPU path. OmniVoice is a
selectable option; selection alone does not establish its standalone runtime,
provider quality, or production behavior.

The target request also receives a bounded semantic voice style derived from
the strict response envelope. Provider adapters map supported emotion/style
values to native controls and fall back to neutral. Current voice/speed-only
Tera calls do not satisfy the emotional-speech requirement.
