# Loopback ASR status visibility (2026-10-29)

## Change

The system-sensor card now shows the ambient ASR lane separately from loopback
PCM, YAMNet, and the audio captioner. It reports the configured ASR mode,
accepted transcript count, obvious-artifact filter count, and age/freshness of
the last accepted transcript. It does not expose transcript text in this status
surface.

`AmbientAudioASRBridge.state()` derives freshness from the source segment's
monotonic end timestamp, so queue delay does not make an old transcript appear
new. The web capture status forwards only these bounded counters and timestamps.

## Limits

This proves status plumbing in source only. It does not prove loopback speech was
transcribed, the transcript was accurate, or VA delivered it to the live brain.
No live audio or regression test was run for this UI follow-up.
