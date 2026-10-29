# Live audio canary: GigaAM + YAMNet + real clips — 24 Oct 2026

## Setup

An isolated `goal-canary-20261024` companion profile ran for approximately six
minutes. Ambient audio captured the configured NVIDIA DigitalOutput loopback;
`EnableStreamingAsr` routed ASR through the configured CPU GigaAM executable.
The local Qwen2.5-Omni endpoint was used as the JAWL brain because the running
Hikari endpoint reported an 8,192-token context while JAWL's startup request
contained 11,536 prompt tokens. OmniVoice/TTS and microphone capture were not
started. The live monitor stored only redacted observations and scalar sensor
metrics, never PCM or transcript text.

The loopback received a short Russian-trailer excerpt, a known FMA Electronic
control, then the audio from the 50-second five-case montage (Russian trailer,
anime trailer, gameplay, coding screen, Aqua music video). The montage was
played audio-only; this was an audio-path test, not a live visual capture test.

## Results

- 241.1 seconds of monitored capture; 11,242 loopback chunks, zero capture
  drops, zero monitor errors. Device: `DigitalOutput (NVIDIA High Definition
  Audio) [Loopback]`.
- GigaAM completed 16 segments and retained four speech observations. The
  privacy-safe monitor intentionally redacted transcript text, so this run
  does not score WER or verify the words against the trailer.
- YAMNet completed 16 segment classifications with zero processing drops or
  stale segments. Its inference p95 was 46.7 ms; the final queue drained to
  zero and stop reported `flushed` with the worker stopped.
- YAMNet detected music on the known Electronic FMA control and on the Aqua
  montage segment. On the Aqua segment it reported Music in 14/15 windows
  (maximum score 0.9849, median 0.9326). Stable genre/instrument tags were
  empty. Music presence is demonstrated; style, instrument, mood and musical
  description quality are not.
- Thirteen EG2 audio descriptions completed; p95 was 1,078 ms. With the
  15-second segment cap, capture-to-observation age was typically about
  14–15 seconds even though model inference itself was fast. This is too weak
  to call subsecond real-time perception and should be measured separately
  from inference latency.
- A no-GigaAM control run on the same bridge used VoiceMem streaming ASR and
  accumulated a queue of eight segments. Its first useful description arrived
  after about 120 seconds and was already stale; stopping capture left the
  worker draining. This is a failure mode when `EnableStreamingAsr` is omitted.

## Brain integration and blockers

The short Qwen-backed JAWL profile started and handled the startup ReAct turn.
However, a local Companion chat question about the current audio was returned
as an echo of the question instead of an audio-grounded answer. A direct
Qwen2.5-Omni request supplied only the observed YAMNet metadata and correctly
answered that music was detected but no specific tags were stable. This points
to an unresolved JAWL ReAct/terminal-response integration or prompt-encoding
problem; it does not prove the sensory observation reached the model correctly.

The current Hikari endpoint could not complete even its startup turn: `/props`
reported `n_ctx=8192`, while the request required 11,536 prompt tokens. The
launcher correctly refused to expose the Companion as ready and shut down its
owned processes. No Hikari, Qwen, or TTS server was stopped or reconfigured.

## Decision

The specialized CPU audio path is technically viable when the integrated
launcher keeps GigaAM enabled: signal reaches the correct loopback, ASR,
soundscape and EG2 description workers complete without queue loss, and
music-presence evidence reaches ambient memory. This is a short canary only.
The 15-second segment age, missing style tags, unscored transcript accuracy,
Qwen/JAWL echo, Hikari context mismatch, absent visual capture, and lack of
CPU/RSS time-series mean the companion is **not yet accepted for 24/7 use**.

Raw reports:

- `runtime/instances/goal-canary-20261024/data/live-sensory-gigaam-20261024.json`
- `runtime/instances/goal-canary-20261024/data/live-sensory-drain-20261024.json`
- `runtime/instances/goal-canary-20261024/data/live-sensory-canary-20261024.json`

All temporary profile processes and ports 2367/8766/8770 were stopped by the
launcher. Existing model endpoints 8990 and 8995 were left untouched.
