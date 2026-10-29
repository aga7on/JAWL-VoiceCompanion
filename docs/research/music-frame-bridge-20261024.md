# MusicFrame production bridge replay — 24 Oct 2026

## Change

Ambient audio now has two independent bounded segmenters. ASR keeps its
existing 15-second default segment; YAMNet receives its own 4-second segments
on a separate queue and worker. This reduces the classifier's capture-window
wait without forcing the ASR path to finalize short utterances. `MusicFrame`
adds timestamped `music|unknown`, YAMNet score/window measurements, RMS and a
conservative energy trend. Unknown replaces the live music claim with an
explicit non-confirmation; it is not stored in ambient memory and is not
rendered as proof that no music is playing. Genre, mood and style are not
inferred from RMS or uncalibrated model scores.

## Local replay

Command: `python scripts/probe_music_frame_bridge.py`

The replay loaded the existing one-thread CPU YAMNet ONNX model and processed
the five existing 10-second mono 16 kHz audio fixtures through the production
`AmbientAudioASRBridge` segmenters, soundscape worker, `MusicFrame` builder and
`PerceptionFusion`. Fixture audio was paced at its source duration: 50.95 seconds
wall time for 50.05 seconds of audio. Each clip produced three music-lane windows of
4.0, 4.0 and 2.005 seconds. The ASR segmenter remained configured at 15 seconds.

| Fixture | YAMNet music windows | Music-positive segments | Last frame |
| --- | ---: | ---: | --- |
| Russian trailer | 1/3, 2/3, 0/2 | 1/3 | unknown |
| Anime | 0/3, 0/3, 0/2 | 0/3 | unknown |
| Gameplay | 3/3, 3/3, 2/2 | 3/3 | music |
| Coding UI | 3/3, 3/3, 2/2 | 3/3 | music |
| Aqua song | 3/3, 3/3, 2/2 | 3/3 | music |

All 15 segment inferences completed with zero queue drops and zero worker errors. The
artifact stores scalar detector results and frame telemetry only; it contains
no PCM or transcript text:
`runtime/audio-path-replay/out/music-frame-bridge-five-case-20261024.json`.
The ASR worker used a no-op stub, so these results say nothing about transcript
quality. This paced local WAV replay cannot establish hardware loopback capture
age, CPU load under the desktop, or uninterrupted live operation. The source is
explicitly recorded as `local_fixture_replay`; reported frame age is local
processing delay after segment end, not device capture latency.

## Verification and remaining acceptance

The focused gate passed: 43 tests across MusicFrame, ambient segmentation and
workers, YAMNet, and brain-context provenance; Python compilation and
`git diff --check` also passed. Tests cover music/unknown state, the
music-to-unknown overwrite, source timestamps, independent segmenters, bounded
latest-wins queue behavior and stale generations.

Still open: run a supervised live loopback test on the selected output device
and measure capture-to-frame age, CPU/private bytes, drops and recovery. Then
run the integrated 30–60-minute companion acceptance and 8-hour full-stack
soak. This fixture replay is not a 24/7 pass. Music style, instruments,
vocals, tempo, transitions and human-grounded captions remain unaccepted.

The current build-vs-train choice remains a deterministic measurement layer
over YAMNet. This replay supports music-presence evidence in several mixed
clips, but it cannot justify a new model for style or mood. First collect
source-disjoint listener labels for those specific capabilities; only compare
a ready-made classifier or micro-model after a blind held-out test shows a
repeatable gap in coverage or precision that matters to the companion.
