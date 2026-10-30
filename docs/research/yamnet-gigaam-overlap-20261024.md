# Speech + music overlap and music-tagging candidate — 24 Oct 2026

## Goal

Test whether external-media ASR can continue while music is independently detected, and identify a credible next model for style/instrument/mood tags. This is a local, CPU-only controlled probe. It did not start the companion, microphone, TTS, or alter the daily profile.

## Controlled overlap

`scripts/probe_yamnet_gigaam_overlap.py` evaluated 25 cases: three short Russian speech fixtures, two music clips (Bach Toccata and saxophone), 18 mixtures at speech-over-music SNR +10/0/-10 dB, plus noise and silence. YAMNet used ONNX Runtime CPU with one intra/inter-op thread and 2-second windows at 1-second hops. GigaAM was the existing CPU daily ASR model. Audio stayed in memory/temporary files; the JSON stores class scores and ASR quality indicators, not PCM or transcript text. No transcript hash is retained.

- ASR found the expected phrase in **17/18** mixtures: 6/6 at +10 dB, 6/6 at 0 dB, 5/6 at -10 dB.
- YAMNet produced at least one window with Music ≥0.3 in **18/18** mixtures; at least two windows crossed that mark in 16/18. At a fixed ≥2-window rule, thresholds .2/.3/.35/.4/.45/.5 found 17/18, 16/18, 15/18, 14/18, 13/18, 12/18 respectively. None of the five speech-only/noise/silence controls crossed the ≥2-window rule at these thresholds.
- YAMNet also emitted broad instrumental tags (keyboard/harpsichord on Bach, sax/wind on sax), but these are labels, not reliable free-form musical descriptions.

This supports independent ASR and soundscape tracks: speech should not erase music evidence, and music evidence should not erase speech. It does **not** calibrate a production threshold. The sample is tiny, uses only two music sources and three synthetic mixes derived from recorded speech, and contains no real game/video soundtrack, compression, reverberation, music transitions, or independently annotated negatives. The current `AudioFrame` production suppression policy should remain conservative until the same-frame overlap is validated on source-disjoint media.

Artifact: `runtime/audio-path-replay/out/yamnet-gigaam-overlap-20261024.json`.

## Genre and richer descriptors

The current local HuBERT ten-genre classifier is rejected for always-on use: it assigns confident genres to speech, silence, and noise. MERT valence/arousal is plausible only behind a persistent music detector, and describes the soundtrack rather than the listener.

A promising research candidate is the MERT-based Music-Descriptor head family. The published demo exposes separate heads for genre, instruments, mood/theme, vocals, and related music tags, so it is a better match for “what style/instruments/quality is playing?” than a single ten-class GTZAN label. However, both the demo and MTG-Jamendo dataset declare CC-BY-NC-4.0, and the demo notes errors with long files on its 2-CPU/16-GB host. This is **not approved for shipping or commercial use** without a license review, and its CPU cost is unmeasured here. If the project's use is noncommercial, the next research gate is to export only selected descriptor heads, quantize/test CPU inference, and compare on source-disjoint music/speech/noise controls with abstention and latency/RSS measurements. Otherwise, prefer a permissively licensed model/data route or train a small project-owned classifier from properly licensed labeled clips.

## Direction

Keep the sensory design modular:

1. GigaAM ASR emits timestamped speech segments and confidence/quality metadata.
2. YAMNet emits a parallel rolling soundscape stream (music, instruments, speech, effects/noise) with persistence and event-change evidence.
3. A slower genre/instrument/mood head runs only after sustained music is established; uncertain labels are omitted, never inferred from ASR text alone.
4. The brain receives concise, provenance-bearing observations such as “speech detected” and “steady instrumental music; keyboard-like tones,” with timestamps and uncertainty. Avoid pretending the current detectors can narrate melody, lyrics, key, tempo, or a complete soundtrack story.

This remains a research result, not a production wiring or 24/7 acceptance.
## Live playback capture on the confirmed output

During a user-authorized short playback window, the production WASAPI loopback selected `DigitalOutput (NVIDIA High Definition Audio) [Loopback]` (device 39, 48 kHz stereo). The 15-second in-memory capture delivered 699 chunks with zero drops/errors and 14.91 seconds of audio. Raw PCM and transcript text were not persisted.

YAMNet ran CPU-only with one thread at 2.8 ms mean per 2-second window. Music scores ranged 0.243–0.867 (median 0.683); 13 rolling 1-second-hop windows (12 above 0.3) were evaluated, with all but the first exceeding 0.3. Speech scores stayed below 0.004. GigaAM returned no transcript in 545 ms. This is direct evidence that a real loopback music stream can be detected independently from speech ASR. The source/content was not independently labeled, so it does not measure music-vs-nonmusic accuracy for this exact playback.

The secondary labels (electronic/new-age/tender/percussion/flute, etc.) scored only about 0.001–0.006 and varied from window to window. They are not strong enough to surface as genre or instrument claims. The gated MERT valence/arousal head ran on CPU in 1.94 s and returned `[0.324, 0.293]`; treat these only as coarse soundtrack coordinates, not a definitive “sad”/“calm” description or the listener's emotion. This illustrates a practical two-speed split: fast stable presence detection, then slower conditional affect estimation. Rich, reliable style remains unresolved.

Artifact: `runtime/audio-path-replay/out/live-music-loopback-probe-20261024.json`; reusable probe: `scripts/probe_live_music_loopback.py`.

## QA video fixture audit

The local `runtime/vlm-cpu-bench/qa/segA.mp4`, `segC.mp4`, and `segD.mp4` have AAC streams but each is effectively digital silence (`mean_volume=max_volume=-91 dBFS`); `segB.mp4` has no audio stream. YAMNet consequently reported Music=0 and GigaAM no transcript on all decoded segments. These are visual QA assets with silent audio tracks, not valid game/video audio positives. The paired pipeline should use a separately labeled real playback capture for audio acceptance.

Artifact: `runtime/audio-path-replay/out/yamnet-qa-video-segments-20261024.json`.
## Production bridge update

Added `YamnetSoundscapeDetector` as an optional independent CPU lane in the ambient bridge. It analyzes the same bounded PCM segment as GigaAM, requires sustained music evidence (at least two 2-second windows over a 0.30 score gate; longer segments also require at least 25% of windows), and emits only stable strong non-generic tags. It does not produce mood or free-form captions. ASR transcript retention and privacy gates remain separate; a matching music result is stored as its own ambient observation and fused independently with source/segment provenance. Music is removed on pause and expires from the live context after 20 seconds. If ONNX/model loading fails, ASR continues and status reports the missing/failed soundscape lane.

Standalone production-venv measurement: YAMNet ONNX CPU, one intra/inter thread, process RSS increased 22.7 MiB after model load and 31.5 MiB after an 8-second sax clip; model load 33.9 ms; complete 8-second segment inference 29.7 ms across seven rolling windows. The live 15-second playback probe measured 2.8 ms per window. These are isolated-process measurements, not the full companion's combined CPU/RSS budget.

Verification: detector unit tests cover CPU-only provider enforcement, short-clip abstention, silence/speech rejection, and stable-tag emission. Ambient bridge tests prove independent Music and ASR observations coexist and reach Fusion with provenance. Focused Python suites: **129 tests passed**; desktop sensory-health UI: **7 passed**; Python compilation passed. Local real-fixture replay: Bach→music, sax→music with stable Saxophone/instrument tags, Russian speech→unknown, speech+synthetic chord→music, noise/silence→unknown. This does not replace a source-labeled game/video acceptance run or the 30–60-minute live companion test.

Bridge smoke follow-up: sent the local speech+synthetic-chord fixture through the actual YAMNet ONNX detector and the production `AmbientAudioASRBridge`, with a stub final-ASR result. The bridge retained separate transcript and Music events and composed both into Fusion; detector status reported retained and `raw_audio_persisted=false`. This validates bridge wiring on one synthetic mixed clip, not GigaAM's transcript quality or a real game/video source. The paired GigaAM results remain in the earlier section.