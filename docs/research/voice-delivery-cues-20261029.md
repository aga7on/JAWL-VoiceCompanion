# Direct-microphone voice-delivery cues — implementation status (2026-10-29)

The Russian emotion-classifier candidate was rejected for the always-on path:
it ran slower than real time and assigned near-certain enthusiasm to neutral
fixtures. This follow-up adds a non-neural, CPU-only measurement lane instead of
making emotion claims.

`UtteranceBuffer.finish_microphone()` optionally analyzes the already buffered
PCM16 after successful ASR. It uses block averaging as a low-cost prefilter
while downsampling to about 8 kHz, and analyzes at most the most recent 30
seconds with 40 ms frames every 200 ms.
It estimates pitch percentiles when enough periodic frames are present,
signal-level p10/p90 in dBFS, periodic-frame ratio, duration, and processing
time. It returns no waveform or transcript.

Only direct browser-microphone finalization opts in, and the feature itself is
disabled by default. `--voice-delivery-cues` (or launcher switch
`-EnableVoiceDeliveryCues`) explicitly enables it. Ambient/system loopback
keeps the analysis off even when enabled, so external speakers, games, music,
and JAWL TTS are not attributed to the user. A successful meaningful
microphone turn may publish the measurements to a separate `voice_delivery` VA channel. The channel ages
from the source capture timestamp, expires after 12 seconds, is marked
unverified, and is not written to durable sensory history. Its text explicitly
says this is not emotion recognition.

## Evidence and remaining gate

This lane is experimental and not accepted. No pitch/level calibration against
independently recorded speech, human review, latency/RSS measurement,
physical-microphone run, or full-profile uptake has been performed. The
algorithm may confuse periodic noise or music with voiced frames and may miss
voices outside its 65–400 Hz search band. Do not use its output to infer
emotion, intent, health, or identity.

Acceptance needs owner-reviewed neutral and varied-delivery phrases, silence,
noise and music controls, multiple microphone gains, source-time freshness and
compute-cost measurements, and confirmation that the brain receives the channel
without unacceptable speech-end delay. Calibration and abstention gates are
required before presenting the estimates as reliable prosody.
