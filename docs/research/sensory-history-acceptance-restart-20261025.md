# Sensory history live acceptance after profile restart

Date: 2026-10-25. Profile: `jawl-qwen3-omni-sensors`; Qwen3-Omni-30B-A3B-Instruct Q4_K_M at `127.0.0.1:8990`, screen capture from display 0, NVIDIA DigitalOutput loopback, OmniVoice TTS.

## Run

The integrated launcher was stopped and restarted. The Qwen server needed a separate restart because the launcher does not own its process; OmniVoice and the JAWL profile were also restarted. The initial JAWL startup heartbeat raced ahead of Qwen readiness and got one transport error. The next cycle succeeded, the Companion came up on port 2367, and the measured run then started.

The live run lasted 605.2 s (12:14:56–12:25:01 UTC). The acceptance harness sampled the live APIs every 3 s and made no manual insertion of event text into model prompts. Historical questions used the Companion's automatic sensory-history enrichment. The current-state test used the normal chat route.

## Results

- 196 samples, 215 newly observed text events, 0 monitor/API errors.
- Visual sensor: 2,437 captures, 347 requests, 303 caption deliveries, 0 capture errors. Caption age across 120 samples with an age value: p50 2.41 s, p95 11.75 s, max 23.47 s; final run sample age 1.66 s. Later live status remained fresh, with 0 capture errors.
- Audio loopback remained active on `DigitalOutput (NVIDIA High Definition Audio) [Loopback]`: 28,009 chunks, 39 transcript events, 37 speech events, 20 music events. Qwen audio description was invoked 38 times without a reported error. YAMNet produced 150 soundscape updates; its final state was `music` with no tags.
- The persistent sensory journal ended with 230 recent entries, 10 compact moments, and no storage error. Both raw-audio and raw-video persistence flags were false. File: `runtime/instances/jawl-qwen3-omni-sensors/data/sensory/weekly-history.json`.

## Model checks

- At run start, the ordinary request to describe the current screen and system audio got a greeting rather than a description (3.20 s). A second current-screen request after the run also got a greeting (2.04 s; retry 1.62 s). **Current-state conversation acceptance failed**, even though fresh Qwen captions were present in the sensor API.
- The automatic-history request about roughly two minutes earlier returned a YouTube scene with a person holding a rainbow Slinky, plus music/system audio, in 8.45 s. The request about roughly two minutes before the end returned a YouTube close-up of a wooden slatted object in 8.05 s. These are unverified model summaries; the captions varied and should not be treated as ground truth.
- The automatic whole-session summary completed in 5.16 s and mentioned music followed by speech, a YouTube scene with a heated metal spring, then browser recommendations. It omitted most of the visual sequence. A follow-up constrained by UTC timestamps returned “I can't determine what exactly you wanted to ask”; the natural-language retry also greeted instead of summarizing.

## Outcome

**PARTIAL.** Capture, audio ingestion, text-history persistence, and two approximate look-back questions worked. The evidence does not show that the main conversational turn reliably uses fresh visual context, and the ten-minute history summary is too lossy to reconstruct the visual storyline. The timestamps, source captions, and audio text are in `runtime/sensory-history-acceptance-restart-20261025.json` for review.