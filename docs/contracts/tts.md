# TTS Contract

The web/JAWL process uses a small provider interface and keeps CozyVoice
models in their own process. The current provider is an HTTP client for the
local `CozyVoice/rest_api.py` wrapper.

## HTTP API

`GET /api/tts/status` reports whether a provider is configured. It does not
load the model. `POST /api/tts/synthesize` accepts an authenticated JSON body:

```json
{"text":"Привет. Как дела?", "voice": null, "speed": 1.0}
```

The response is transient `audio/wav`; it is never written to the repository
or durable memory. Text is limited to 4,000 characters and speed to 0.5–2.0.
The adapter sends one CozyVoice request per sentence, runs at most three
sentence requests concurrently, and merges compatible WAV chunks in the
original text order. The provider boundary is model-neutral: selecting or
replacing the TTS model does not change this contract. The current endpoint is
still whole-response, so playback begins only after the merged WAV is ready;
first-audio streaming remains a separate latency task.

## Cancellation and failure

`TTSService` is latest-request-wins. A newer request marks the older provider
call stale; providers check the cancellation event between chunks and the
service never returns stale audio. A superseded HTTP request returns `409`.
Provider or malformed-audio failures return `503` and leave text chat usable.

The CozyVoice adapter accepts only the local REST base URL, sends no API key,
and bounds downloaded audio to 8 MiB. OmniVoice has no confirmed local
runtime/API in the current checkout, so it remains a future provider under
this same interface.
