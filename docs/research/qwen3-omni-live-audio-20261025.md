# Qwen3-Omni live audio probe ? 25 Oct 2026

## Result

**Partial pass: one locally controlled music segment traversed NVIDIA DigitalOutput loopback and invoked the production Qwen Omni audio-describer.** This is a path/smoke result, not a general audio-quality acceptance.

## Procedure

- Confirmed the active endpoint was `local-qwen3-omni`; `/props` advertised audio, image, and video. The profile command selected `qwen-omni` audio description at the same local Qwen server as the brain and visual sensor.
- Verified the existing Aqua positive-control WAV was mono PCM16, 16 kHz, 10.005 s, non-silent (RMS 7,851.84, peak 32,768). No media was written by the probe.
- Called the production `QwenOmniAudioDescriptionProvider` against that WAV with prompt cache disabled. It returned a schema-valid `kind=music` result in 0.903 s with dance/electronic/pop, female-vocal, energetic and synthesizer tags. The model reported confidence 1.0; this score is uncalibrated. Description text was not persisted or included here; lyric accuracy was not scored.
- Played the same local WAV once through the selected WASAPI `DigitalOutput (NVIDIA High Definition Audio)` endpoint at -12 dB, 48 kHz, for 9.93 s. Loopback PCM and generated description text were not saved.

## Live observations

At `2026-10-25T08:35:12Z`, Companion reported brain connected and TTS ready; the Qwen server `/health` was OK. Loopback was running with no queue/drop/error. Relative to the pre-playback count, Qwen audio descriptions increased from 2 to 3, errors remained 1, and the processing queue was empty; p95 description latency was 1,829 ms. GigaAM transcript count increased from 1 to 2 (one additional ASR completion, transcript text not reviewed or persisted by this probe). YAMNet soundscape count increased from 7 to 10 and its latest state was `music` in 2 windows. The latest PCM chunk had already returned to silence by the status query. During the stimulus, the 8-hour monitor remained live at sample 87 with 12,722 captures / 320 visual deliveries, no capture errors and no stale-result drops.

The legacy loaded process does not expose the last Qwen description kind/content in status. Therefore the counter increase proves a successful production-lane response but not that the captured loopback result's semantics matched the direct WAV result. The active current-context draft did not retain a fresh Qwen music claim when inspected; the speech-over-music interaction remains unresolved.

## Acceptance boundary

This probe verifies a short positive signal reaches the configured loopback and causes one successful Qwen Omni description without persisting PCM. It does not establish transcript/lyric accuracy, exact lyric accuracy, performance across speech-over-music, genre calibration, freshness continuity, long-run audio availability, user-turn latency under a shared one-slot server, or 24/7 readiness. Repeat after controlled restart with the new bounded result-kind/freshness metadata, and test speech-only, music-only, speech-over-music, silence, and recovery with source labels.
Final post-stimulus check at `2026-10-25T08:38:27Z`: live API brain connected, TTS ready, audio queue empty, Qwen description counters unchanged at 3/1. Loopback had returned to silence (last nonzero chunk 202.7 s old). Visual sensor still delivered captions with no capture/stale drops, but live caption had aged to 6.1 s; monitor sample 93 taken 22 s earlier recorded it fresh at 3.89 s. The current process remains on the old refresh parameters.

## Shared-slot concurrency smoke

A simultaneous short text call and production-format 10 s `input_audio` call were sent to the active `local-qwen3-omni` endpoint with prompt caching disabled. `/slots` exposed one server slot. Both requests succeeded: text 0.885 s (23 prompt / 17 completion tokens), audio 0.747 s (186 prompt / 94 completion tokens), total wall 0.890 s. No response content or audio bytes were persisted. Post-check at `2026-10-25T08:39:44Z`: Qwen `/health=ok`, brain connected, TTS ready, visual sensor at 348 deliveries / fresh caption, ambient audio queue empty, audio success/error counters unchanged at 3/1, and soak sample 96 had zero capture/stale-result drops.

This shows the server remained responsive for two tiny concurrent calls. It does not measure actual queue wait separately or the latency of a full JAWL brain prompt (~12k tokens), and therefore does not close shared-slot contention acceptance.
