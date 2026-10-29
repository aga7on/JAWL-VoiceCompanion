# Provisional audio annotation for the five real clips — 24 Oct 2026

## Status

This is a practical annotation scaffold for `runtime/multimodal-realclips-20261024/real_sensory_5x10s.mp4` and its five source segments. It is **not ground truth**: I could not directly listen to the local audio in this session. The event candidates below come from the existing manifest, YAMNet window scores and GigaAM nonempty/empty metadata. Every model-derived span remains provisional and must be reviewed by a human annotator before it is used to score a model or tune a threshold.

The two artifacts are:

- `runtime/multimodal-realclips-20261024/audio-ground-truth-provisional.json` — clip metadata, overlapping event intervals, evidence, uncertainty, transitions and human review checklist.
- `runtime/multimodal-realclips-20261024/audio-ground-truth-provisional.csv` — flat interval table for spreadsheet/manual correction.

## Schema

Times use the montage timebase and half-open intervals `[start_s, end_s)`. The labels `speech`, `music`, `vocals`, `effects`, `silence` and `uncertain` are independent and may overlap. `confidence` describes only the provisional evidence quality, not a calibrated probability. `language_candidate` and `speech_intelligibility` are unresolved unless a listener confirms them. A blank model output is never converted into a negative label; in particular, ASR abstention does not mean silence or no speech.

YAMNet evidence was generated in overlapping two-second windows at one-second hops. These windows do not locate exact event boundaries. The only high-confidence transitions in this draft are the montage edit cuts at 10, 20, 30 and 40 seconds, taken from the dataset manifest; they do not claim that a listener confirmed a corresponding acoustic transition.

## Provisional findings

The reports support candidate music in the Russian trailer, gameplay, coding clip and Aqua clip. YAMNet's persistent music gate abstained on the anime segment, although one early window had a Music score of 0.382; that is unresolved, not a verified music absence. The Russian trailer has overlapping speech/music candidates in the latter portion. The anime has model candidate effects in its middle portion. GigaAM produced nonempty output for the Russian trailer and Aqua clip, but the stored artifacts omit the transcript, so neither words, language, intelligibility nor singing can be verified. Gameplay and coding ASR abstentions do not establish no speech.

The existing evidence cannot establish quiet intervals, exact speech/music boundaries, vocals, lyrics, sound-effect identity, musical style, mood or internal transitions. The CSV explicitly marks these spans uncertain to prevent downstream evaluation from treating missing evidence as a negative.

## Human pass needed

An annotator should listen to each original clip, independently mark overlapping event spans at approximately 250 ms resolution, and capture language/intelligibility and any lyrics only when clear. Distinguish silence from quiet ambience; distinguish spoken dialogue from singing; record uncertainty rather than guessing. A second annotator should adjudicate disagreements on speech/vocal boundaries and effects. Only after that review should these files be promoted from provisional to an evaluation ground-truth set.

References used: `runtime/multimodal-realclips-20261024/manifest.json`, `docs/research/realclip-audio-five-case-recheck-20261024.md`, and `runtime/audio-path-replay/out/realclip-audio-lanes-audio-agent-20261024.json`. No model inference, services, profile changes, or existing artifacts were run or modified for this annotation.
