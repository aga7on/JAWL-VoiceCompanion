# Five-clip audio quality: evidence and next step — 24 Oct 2026

## Scope and result

This audit is audio-only. No video content was used to label a sound, and no model inference, microphone, loopback, companion service, profile change or TTS action was performed. The five existing mono 16 kHz PCM WAV files were read for an objective 1-second signal-level pass. The output is `runtime/audio-path-replay/out/realclip-audio-levels-1s-20261024.csv` (55 rows: eleven fixed buckets per nominal ten-second clip, including each WAV's short final partial bucket). It contains RMS/peak dBFS and exact-zero sample fraction only; no audio samples or transcript text are persisted. The CSV's `human_audio_label` column is blank by design.

| Clip | RMS range, 1-second buckets | Highest peak | Interpretation limit |
|---|---:|---:|---|
| Russian live-action trailer | -69.15 to -19.06 dBFS | -7.27 dBFS | Level changes only; does not locate speech, music or silence. |
| Anime trailer | -40.22 to -22.83 dBFS | -10.63 dBFS | Level changes only; no event identity. |
| RTS gameplay | -47.66 to -26.13 dBFS | -9.83 dBFS | Level changes only; no inference of game/music source. |
| Coding UI | -50.20 to -17.02 dBFS | -4.89 dBFS | Level changes only; no inference of music or UI sounds. |
| Aqua song video | -31.13 to -11.94 dBFS | -0.00 dBFS | Level changes only; cannot distinguish vocals, backing, effects or limiting. |

The last partial bucket is around 8 ms because the WAV segments are approximately 10.008 seconds. It should not be compared with a full one-second RMS bucket.

## Facts, hypotheses and open labels

**Facts from existing artifacts:** the five-clip GigaAM/YAMNet replay repeats the same YAMNet scores and ASR nonempty decisions across three runs. GigaAM returns nonempty metadata on the Russian trailer and Aqua clip (42 and 46 normalized characters) and empty metadata on anime, gameplay and coding. The 5-second window replay has text in 4/4 Russian-trailer windows and 1/4 Aqua windows; these are recognizer-output counts, not transcript accuracy. Current reports intentionally omit the transcript. YAMNet's Music scores are stable for gameplay, coding and Aqua in these fixtures, but no listener-verified time spans exist.

**Hypotheses only:** trailer intervals may contain overlapping speech and soundtrack; anime windows may contain effects; the Aqua ASR output may be sung words. These derive from model scores, source context or ASR nonemptiness and are not used as truth. Music genre, mood, instrument identity, vocal boundaries and event descriptions cannot be scored from this evidence.

**Requires human listening:** exact speech/music/vocal/effect/silence boundaries, language and intelligibility, a verified transcript (including whether the Aqua output is lyrics), audible broad style, clearly identifiable instrument families, energy/tempo change and event-level confidence. The blank worksheet is `docs/research/audio-listening-annotation-worksheet-20261024.md`. The provisional annotation JSON/CSV remains a checklist only.

## Next CPU-only quality test

The next useful test is not another blind replay; it is one independent human annotation pass followed by an offline, single-thread CPU replay. Use the existing five clips and keep speech, music, vocals and effects as overlapping tracks. For GigaAM, compute WER/CER against human speech references and report lyrics separately; for YAMNet/MusicFrame, compute event/music precision, recall, false-claim rate, abstention coverage and boundary delay. Include speech+music spans and silence/noise controls. Record CPU p50/p95, window-to-result age, queue drops/stale counts and private bytes. Do not tune thresholds on the final clips; treat five excerpts as a pilot and add parent-recording-disjoint sources before setting a 24/7 acceptance gate.

The existing `scripts/probe_music_frame_bridge.py` exercises the production 4-second music segmenter but uses no-op ASR and writes to a fixed report path. The existing `scripts/probe_realclip_audio_lanes.py` runs actual GigaAM/YAMNet but retains no transcript and does not expose the production bridge's 4-second worker. For the quality run, create a runner/output path that combines those boundaries without overwriting existing reports and retains no raw PCM. No such combined quality run was executed in this step.

## References

- `runtime/multimodal-realclips-20261024/manifest.json`
- `docs/research/realclip-audio-five-case-recheck-20261024.md`
- `docs/research/short-window-asr-realclips-20261024.md`
- `docs/research/music-frame-bridge-20261024.md`
- `docs/research/audio-listening-annotation-worksheet-20261024.md`
- `runtime/audio-path-replay/out/realclip-audio-audit-rerun-20261024.json`
- `runtime/audio-path-replay/out/realclip-audio-levels-1s-20261024.csv`
