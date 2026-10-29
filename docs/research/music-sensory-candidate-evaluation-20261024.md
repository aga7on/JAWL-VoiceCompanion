# CPU music perception candidates: first local probe (2026-10-24)

## Goal

Evaluate audio understanding beyond ASR: music presence, broad sound/instrument description, genre, and musical affect. This is an offline CPU-only probe. It did not change the active profile, open a microphone, or alter TTS.

## Candidates

- **YAMNet ONNX** (16.1 MB, pinned existing local export): broad AudioSet event scores. The existing 2-second sliding-window probe measured 1-thread p50/p95 2.65/2.95 ms and supported event families such as music, speech, silence, noise and instruments. It is a detector/tagger, not an open-ended captioner, genre classifier, or mood model. Prior results and limitations are in [the YAMNet probe](yamnet-audio-event-probe-20261024.md).
- **Musical-genres-Classification-Hubert-V1 ONNX INT8** (local file 23,950,982 bytes; SHA-256 `0723d21a59c42083dfa1621b5b48ed72e94afac29bfd17fb08110326ea1c9156`). It predicts ten GTZAN genres. The base card reports 0.84 evaluation accuracy but has little information about evaluation conditions or limitations; the export is [onnx-community](https://huggingface.co/onnx-community/Musical-genres-Classification-Hubert-V1-ONNX/tree/main), based on [the original HuBERT genre model](https://huggingface.co/SeyedAli/Musical-genres-Classification-Hubert-V1).
- **MERT-v1-95M music emotion INT8 ONNX** (95,552,890 bytes; SHA-256 `b05ef3fbe904f1121b32632da9ad4907afb676a11e348fe01484a71412c42e01`). It accepts mono 24 kHz, fixed 15-second audio and returns valence/arousal. The quantized card claims Apache-2.0 and reports held-out results on 386 DEAM/PMEmo songs; these are model-author claims, not independently reproduced here. The underlying [MERT-v1-95M card](https://huggingface.co/m-a-p/MERT-v1-95M) declares CC-BY-NC-4.0. Since this is a fine-tune/derivative, resolve the license compatibility before redistribution or commercial use. [Quantized model card](https://huggingface.co/huyleit/mert-v1-95m-music-emotion-int8/blob/main/README.md).

## Method

`scripts/probe_music_models.py` ran the local ONNX models with ONNX Runtime's `CPUExecutionProvider`, one intra-op and one inter-op thread. Inputs were two music assets (Bach Toccata and saxophone), three Russian speech prompts, English speech, a synthetic harmonic chord, the project's Russian-speech-over-chord mixture, synthetic noise and silence, plus in-memory digital-silence / seeded-white-noise controls. HuBERT received normalized non-overlapping 5-second crops at 16 kHz; MERT received 15 seconds at 24 kHz (start slice, padded when shorter); YAMNet received each clip at 16 kHz (4 to 16 seconds). The probe records raw scores and latency in `runtime/audio-path-replay/out/music-model-candidate-probe-20261024.json`.

The music fixtures are useful positive probes but are not a representative, independently annotated validation set. The speech prompts and synthetic controls are useful negative controls. Do not treat any reported score as a calibrated confidence threshold.

## Results

| Input | YAMNet top mean tags | HuBERT genre top 1 | MERT valence/arousal |
|---|---|---|---|
| Bach Toccata | Music 0.914; Keyboard 0.116; Piano 0.089 | classical 0.695 | 0.686 / 0.692 |
| Saxophone clip | Music 0.755; woodwind 0.428; instrument 0.416; saxophone 0.383 | jazz 0.569 | 0.547 / 0.549 |
| Synthetic harmonic chord | Chirp tone 0.293; sine wave 0.202; Music 0.197; Synthesizer 0.180 | hiphop 0.427 | 0.341 / 0.319 |
| Russian speech over synthetic chord | Music 0.334; chirp tone 0.137; Singing bowl 0.100; Speech not in top 5 | hiphop 0.617 | 0.305 / 0.275 |
| Russian speech 1 | Speech 0.951 | hiphop 0.935 | 0.302 / 0.271 |
| Russian speech 2 | Speech 0.950 | hiphop 0.923 | 0.246 / 0.217 |
| Russian speech 3 | Speech 0.994 | hiphop 0.935 | 0.316 / 0.287 |
| English speech | Speech 0.876; Silence 0.032 | hiphop 0.900 | 0.305 / 0.275 |
| Synthetic noise | White noise 0.426; Static 0.423; Waterfall 0.292; Music 0.009 | metal 0.963 | 0.440 / 0.452 |
| Synthetic silence | Silence 1.000 | hiphop 0.867 | 0.245 / 0.216 |
| Digital silence | Silence 1.000 | hiphop 0.867 | 0.245 / 0.216 |
| Seeded white noise | White noise 0.407; Static 0.338; Waterfall 0.453 | metal 0.963 | 0.326 / 0.303 |

With one thread and the two detector models plus MERT loaded, YAMNet per-input p50/p95 was 6.7/24.1 ms for inputs up to 16 seconds (the prior 2-second streaming-window timing is more useful for cadence comparison). MERT's 15-second inference p50/p95 was 1.888/1.910 seconds. HuBERT's 5-second crop inference p50/p95 was 2.054/2.072 seconds across 18 crops. Its resident set rose from 86 MiB after session load to 235-279 MiB after its first few inferences; all three model sessions together reached 386 MiB after load. These are isolated-process values, not full companion measurements. The complete observed dataset is the JSON artifact above.

The overlapping 2-second / 1-second-hop sweep kept Bach music scores at 0.90-0.99 after its initial partial window and sax scores at 0.52-0.90. On the synthetic speech-over-chord case, Music was only 0.24-0.38 and Speech 0.003-0.018. A fixed Music threshold of 0.5 would miss this mix, while lowering it globally needs more real negative controls. This is enough to reject a simplistic single-threshold gate, not enough to set a production threshold.

## Decision

1. Keep **YAMNet as the fast broad event/instrument layer**. It separated the two real-music fixtures from clean speech, silence and noise. On the speech-over-chord mix it returned Music 0.334 while Speech dropped out of the top five. Keep GigaAM and the music/event detector as independent tracks: ASR presence must not suppress all soundtrack tags, and a Music tag must not suppress ASR. Use persistence and source/time provenance before publishing either.
2. Keep **MERT as a conditional slow affect layer**, invoked only after music has persisted. It produced plausible coordinates on the two music clips, but also emitted coordinates for synthetic tones, speech, silence and noise (noise reached 0.440/0.452). It must never run as an ungated ambient mood oracle. Describe its output as an approximate quality of the music, never the user's emotional state.
3. **Do not use this HuBERT genre model in an always-on path.** It recognized the two positive clips, but confidently assigned hiphop to all speech and silence, and metal to noise; even a strong softmax score is not evidence of music. It also costs about two seconds per five-second crop on this CPU. Do not surface genre from one result.
4. The current tested modules do not produce reliable free-form musical narration, lyrics, key, tempo, or scene meaning. A small structured `MusicFrame` should carry independent ASR and soundscape tracks, event tags, optional genre candidates, optional valence/arousal, timestamps, duration, source and uncertainty. Deterministic wording can express those facts, and the brain can combine them with visual context.

## Live NVIDIA DigitalOutput check and caption candidate

A fresh 14.81-second capture from `DigitalOutput (NVIDIA High Definition Audio) [Loopback]` collected 694 chunks with zero dropped chunks or capture errors. Raw PCM and transcript text were not persisted. YAMNet ran on CPU with one intra/inter-op thread: all 13 rolling 2-second windows crossed the exploratory Music 0.30 threshold (median 0.8925, max 0.9531; mean inference 2.76 ms/window). GigaAM returned no transcript (544 ms). This confirms live routing and stable music-presence detection on this sample, not general music accuracy.

Style evidence was weak: the strongest specific candidates were Electronic music 0.0299 and Techno 0.0281; low unrelated tags also appeared in individual windows. Do not describe the clip as electronic/techno based on these scores. Conditional MERT ran once on CPU in 1.91 s and returned `[0.4711, 0.4583]`; this unannotated sample does not validate an affect label. The values must not be phrased as the listener's emotion. Reproducer: `scripts/probe_live_music_loopback.py`; scalar artifact: `runtime/audio-path-replay/out/live-music-style-loopback-probe-20261024.json`.

The current Hugging Face survey found **DionTimmer/whisper-small-multitask-analyzer** as a possible clip-level caption baseline. Its card documents task prefixes for tags, genre, mood, movement, and theme on clips up to 30 seconds, with a 0.2B Whisper-small backbone. It is Transformers/PyTorch-oriented, has no hosted inference provider, and the model card gives inconsistent license statements (CC-BY-4.0 in metadata versus CC-BY-NC-4.0 in its license section/search metadata); resolve that before any redistribution or shipping. It is a bounded, on-demand research candidate only, not a new real-time/ONNX result. [Model card](https://huggingface.co/DionTimmer/whisper-small-multitask-analyzer).

Pinned repository revision `8680be5f539f0a7145d59a9e49b6149486a57db1` and inspected the small custom generation class before considering local execution; it only adapts Whisper generation to accept the task prefix. The model weight is 966,995,080 bytes (FP32). A local `snapshot_download` preflight fetched tokenizer/config/code files but stalled on the model weight for over 75 seconds, leaving no usable checkpoint; the transfer was stopped. This is a failed fetch preflight, not inference RSS, latency, or quality evidence. Do not count the captioner as evaluated until weights are available and a CPU benchmark runs.

The capability target is broader than ASR: separately report music presence and transitions; persistent instrument/timbre families; style only when evidence is strong and stable; approximate soundtrack energy/valence only after music gating and calibration; vocal versus instrumental passages and lyrics as a distinct singing-ASR task; and scene-level descriptions grounded in synchronized screen observations. Tempo/rhythm and structural changes can first be tested with deterministic signal features. Every lane needs its own source, time span, freshness, uncertainty, and abstention behavior. Continuous inference remains the fast YAMNet/event + ASR foundation; expensive captioning should run only on a new persistent segment or explicit user question, with a latest-only queue and bounded clip duration.

## Next test before wiring

Use new parent-recording-disjoint game/video clips with music-only, speech-only, speech-over-music at several SNRs, music transitions, effects/noise and silence. Compare YAMNet and current ASR on the same loopback PCM; measure music coverage and false claims, genre abstention, change latency, CPU and process-tree RSS. CLAP and the Whisper Tiny candidate now have small exploratory probes; next compare them on short, labeled segments with the same source-disjoint set, scoring factuality, abstention, latency and RSS. Add MERT only for sustained music segments and check whether its coarse mood tracks human labels. In parallel, compare deterministic tempo/energy/onset features and a small local classifier trained on permissively licensed labels. No candidate enters the daily profile until it beats the current safe baseline on source-disjoint clips.

## Whisper Tiny audio-caption candidate — CPU preflight

The HF search found `cahya/whisper-tiny-audio-captioning-v2.0`, a 37.8M-parameter
caption model whose card says it was fine-tuned on 1M samples from
`mitermix/audiosnippets`. The model card declares Apache-2.0, but the dataset
card does not make the training-audio terms clear; keep this as local research
until provenance/licensing is resolved. The model is a generic audio captioner,
not a validated music-style classifier. [Model card](https://huggingface.co/cahya/whisper-tiny-audio-captioning-v2.0),
[training dataset](https://huggingface.co/datasets/mitermix/audiosnippets).

Pinned revision `a8219d270ff91d8a671c7ff1e760ca6175ffd311`. The HF Python/Xet
snapshot downloader left a zero-byte incomplete weight file; the same pinned
official resolve URL worked through the HF CDN. The downloaded weight is
151,061,672 bytes with SHA-256
`f79a53a7402c103cc072697b3284ee2a780a2b44a203fb048cf1a726525c00a4`.
The reproducible CPU-only probe is `scripts/probe_whisper_tiny_caption.py`; it
uses one PyTorch thread, 12-second bounded crops, and the model's required
`clotho > caption:` decoder prefix from the upstream Whisper-captioning method.
The output is `runtime/audio-path-replay/out/whisper-tiny-caption-probe-20261024.json`.

Model load took 0.53 s; isolated process RSS after inference was 829.9 MiB
(PyTorch/Transformers included). On these short samples, inference took
0.69–0.79 s. The captions are not grounded enough for the live lane: the Bach
Toccata was called slow, simple, and melancholic; saxophone received nearly the
same generic caption and was not identified; the synthetic chord was called a
mechanical hum; speech-over-music was described as speech only; and exact digital
silence (RMS 0) produced a male-voice hallucination. Reject this checkpoint for
always-on or current-context music description. It may be useful as a candidate
for a larger, properly labeled offline comparison, but not as evidence that
music style/mood/description is solved. This is a small, fixed probe, not a
general model benchmark.

## CLAP HTSAT ONNX retrieval probe — 24 Oct 2026

Fetched the pinned `ConceptualMachines/magda-sample-tagger` text encoder with
validated HTTP range responses, assembled it at the declared size, and verified
the published SHA-256 (`c07b2720…423a8bf`). Both text and audio encoders ran
through ONNX Runtime `CPUExecutionProvider`, one intra-op/inter-op thread. The
fixed-prompt probe is reproducible with `scripts/probe_clap_candidate.py`; its
scalar-only artifact is `runtime/audio-path-replay/out/clap-candidate-probe-20261024.json`.

On the seven existing clips, single-prompt retrieval ranked saxophone above
classical organ for the Bach Toccata excerpt (0.310 vs 0.161), while the sax
sample ranked saxophone/jazz correctly (0.687/0.651). Speech+music, speech,
noise, and silence ranked their corresponding scene prompts first. These are
cosine similarities, not calibrated scores. A follow-up paraphrase bank
(`scripts/probe_clap_prompt_bank.py`) did not fix the Bach error: broad style
ranked jazz 0.249 above classical 0.151, and timbre ranked piano 0.402 above
saxophone 0.296. It did rank the sax sample as jazz (0.705) and saxophone
(0.732), and the synthetic chord as synthesizer timbre (0.367), but called its
broad style classical (0.335) above electronic/ambient (0.277). On a Russian
speech-only clip, `speech_over_music` narrowly outranked `speech_only` (0.268
vs 0.258). Thus prompt averaging gives useful semantic clues but does not
provide safe style/instrument claims across the current controls; presenting
music tags still requires a separate reliable music-presence gate.

The fixed-prompt run measured audio-encoder p50/p95 92.5/109.6 ms for one
8-second window and 928.9 MiB isolated RSS after loading both encoders and the
Python/ONNX stack. The prompt-bank run measured 92.5/95.4 ms, 3.34 s to encode
its phrase prototypes, and 929.6 MiB isolated RSS. Precomputing phrase
prototypes would remove the text encoder from a future runtime, but the audio
encoder and its process still need an incremental whole-companion resource
measurement. CLAP does not generate a caption. Keep it out of the daily path
until a parent-recording-disjoint, human-labeled set shows style, timbre,
speech/music overlap, abstention, and false-claim behavior worth the memory.

## FMA artist-disjoint style probe — 24 Oct 2026

To widen style evidence beyond Bach and one saxophone file, I selected 18 FMA
Medium recordings: three distinct artists each from Classical, Electronic,
Folk, Hip-Hop, Jazz and Rock. All 18 artist IDs are unique across this set.
Per-track license metadata was checked; the subset contains only Attribution or
CC0 entries, excluding noncommercial and no-derivatives tracks. The unchanged
MP3 files total 17,332,714 bytes and were fetched as individual ZIP ranges, then
checked against each ZIP entry's size and CRC. The manifest, track attribution
and file hashes are in
`runtime/audio-path-replay/data/fma-medium-selected/manifest.json`. FMA states
that its metadata is CC-BY-4.0 and its Medium archive contains 25,000 30-second
tracks ([official repository](https://github.com/mdeff/fma)).

The pinned CLAP ONNX pair ran on CPU at one thread with a frozen prompt bank.
One fixed eight-second crop starting at second eight was scored per recording.
Top-1 matched the FMA catalog genre for 12/18 (66.7%): Classical 3/3,
Electronic 0/3, Folk 3/3, Hip-Hop 2/3, Jazz 1/3 and Rock 3/3. All four short
controls ranked first as speech-only, speech-over-music, noise or silence; the
speech-only, noise and silence controls were not top-ranked as a music style.
One music-only Electronic sample was ranked as speech-over-music. The overlap
control result is promising, but the style results do not support genre claims.

Audio-encoder latency was p50/p95 93.65/97.15 ms per eight-second crop. The
isolated process RSS after both encoders and feature-extractor load was
1,032,605,696 bytes (~0.96 GiB), not incremental companion RSS. The report
stores scalar scores and track metadata only; it does not write decoded PCM or
transcripts. Reproducer: `scripts/probe_music_fma_clap.py`; result:
`runtime/audio-path-replay/out/fma-medium-clap-style-probe-20261024.json`.

This is an exploratory proxy-label result, not acceptance: three artists per
style, FMA catalog labels were not independently confirmed by listening, and
the probe did not measure instruments, vocal/instrumental status, tempo/energy,
transitions or natural-language description. CLAP stays research-only and is
not wired into daily sensing. Do not train a micro-model from these 18 clips;
first build a larger human-checked, source-disjoint licensed set, then compare
CLAP with a small head over frozen embeddings and deterministic rhythm/energy
features on a held-out artist split.

## YAMNet music, instrument and overlap check — 24 Oct 2026

Re-ran `scripts/probe_yamnet_music_styles.py` on the local licensed/control clips. The detector uses ONNX Runtime CPUExecutionProvider with one intra-op and one inter-op thread; process RSS after model load was 78.9 MB. Bach Toccata produced median Music score 0.972 across 29 windows, with Keyboard, Piano and Harpsichord among leading event tags. The saxophone recording produced median Music 0.730 in all 15 windows, with Wind instrument / woodwind 0.394 and Saxophone 0.350. Russian speech scored Music 0 and Speech 0.657; noise scored Music 0.007, and silence scored Music 0.

This supports using YAMNet for bounded event and instrument-family evidence alongside GigaAM speech transcription. It does not establish robust style recognition: the synthetic electronic-music fixture had median Music 0.242, below the detector's 0.30 persistence threshold, despite Electronic music being its highest genre score (0.011). The speech-plus-music fixture crossed the music threshold in only 2 of 15 windows. These are small known controls, not a held-out acceptance set; YAMNet scores remain uncalibrated and its top genre ranking must not be phrased as confident style or mood. Full acceptance must separately score external-media ASR, music presence, audible instrument/timbre, broad style, vocal/instrumental changes, energy/tempo, transitions, and grounded short description, with music-only, narration-over-music, speech-only, noise and silence controls. Artifact: `runtime/audio-path-replay/out/yamnet-music-style-probe-20261024.json`.

## YAMNet artist-disjoint FMA style probe — 24 Oct 2026

Ran the same 18 individually licensed, artist-disjoint FMA tracks through YAMNet ONNX CPU using a fixed eight-second crop at second eight. Its top broad genre class matched the FMA catalog label on 12/18 (66.7%), the same aggregate accuracy as CLAP on this small proxy-labeled set: Classical 3/3, Electronic 2/3, Folk 1/3, Hip-Hop 1/3, Jazz 2/3, Rock 3/3. Results are not interchangeable: YAMNet confused an Electronic track for Rock and two Folk tracks for Jazz/Rock; its median top-style margin was only 0.02098 and six predictions were wrong. Scores are uncalibrated AudioSet outputs, and the FMA labels were not human-verified.

YAMNet took p50/p95 21.80/23.16 ms for the eight-second crop in this one-thread run; process RSS after load was 78,897,152 bytes (~75.2 MiB). This is suitable evidence for a cheap experimental tagger, not proof of robust genre recognition or captioning. Keep its style tags tentative/abstaining in the live path; validate across more artists, source recordings, mixed speech/music and listener-verified labels before allowing it to state genre or mood as fact. Reproducer: `scripts/probe_yamnet_fma_styles.py`; scalar-only result: `runtime/audio-path-replay/out/yamnet-fma-style-probe-20261024.json`.

## Integrated known-music loopback smoke — 24 Oct 2026

Started an isolated 30-minute companion profile with ambient loopback and GigaAM enabled, microphone/TTS/browser disabled, using the configured NVIDIA DigitalOutput. After the stream initially produced unknown segments, played 15 seconds from the individually licensed FMA Electronic track `022443.mp3` at -18 dB attenuation. The companion emitted a fresh `audio_kind=music` observation on the next segment; GigaAM did not emit a transcript for this music-only stimulus, and the capture reported no drops or soundscape errors. It emitted no stable style/instrument tag, so this confirms delivery and music presence only, not genre or descriptive quality. The monitor report redacts prose and persists category/telemetry only; PCM and transcript text are absent.

The captured observation exposed a timestamp bug: `AmbientSegment.ended_at` is monotonic time, but YAMNet passed it into `AmbientMemoryBuffer` as wall-clock `now`, producing a 1970 timestamp. Updated the bridge to translate monotonic capture time to wall time before memory ingestion and added a regression assertion for creation/retention timestamps. Thirty focused ambient-audio/YAMNet tests pass. The isolated monitor ran 1,741 seconds (29 minutes) with 174 samples, zero monitor errors, zero capture drops, zero soundscape errors, and 115 processed audio segments; it ended cleanly. Exactly one music observation came from the known 15-second Electronic FMA control; the remaining live segments do not establish music recognition quality, and this profile produced no external-media transcript. The run loaded the pre-fix code, so post-fix live timestamp revalidation remains open. This was a bounded integration run, not the requested longer unattended soak.
