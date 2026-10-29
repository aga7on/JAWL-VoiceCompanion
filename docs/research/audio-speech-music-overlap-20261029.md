# YAMNet under synthetic speech/music overlap — 29 October 2026

## Question

Does the current CPU YAMNet music gate (`MUSIC_THRESHOLD=0.35`, at least 2 of
3 windows for a 4-second segment) retain evidence of music when speech is
stronger or equally strong?

## Probe

The real `YamnetSoundscapeDetector` ran with ONNX `CPUExecutionProvider` only.
Six first-4-second snippets were decoded from the local FMA selection manifest,
one each from Classical (34312), Electronic (21855), Folk (107568), Hip-Hop
(7484), Jazz (50970), and Rock (1382). A local 2.76-second Tera TTS source was
repeated in memory to fill the 4-second mix; this is synthetic speech, not a
human recording. Speech RMS was normalized to 0.20; music was normalized to the
same RMS and scaled to music-vs-speech SNR values −12, −8, −4, and 0 dB. A
matched music-only baseline used the same per-track music RMS as the 0 dB mix.
PCM was passed directly to YAMNet and was not written to disk. Only scalar
scores/results are recorded here.

## Results

| Music RMS vs speech RMS | Music detected | Median raw Music score across six clips |
|---:|---:|---:|
| Music only, matched RMS | 4/6 | — |
| −12 dB | 2/6 | 0.1828 |
| −8 dB | 2/6 | 0.2229 |
| −4 dB | 3/6 | 0.3335 |
| 0 dB | 4/6 | 0.4773 |

Per-track detected/unknown results:

| Track class | Music only | −12 dB | −8 dB | −4 dB | 0 dB |
|---|---|---|---|---|---|
| Classical, 34312 | unknown | music | music | music | music |
| Electronic, 21855 | unknown | unknown | unknown | unknown | unknown |
| Folk, 107568 | music | music | music | music | music |
| Hip-Hop, 7484 | music | unknown | unknown | unknown | unknown |
| Jazz, 50970 | music | unknown | unknown | unknown | music |
| Rock, 1382 | music | unknown | unknown | music | music |

A separate Tera speech-only control returned `unknown`, 0/3 music windows, and
max Music score 0.0001. In the music-only baseline, only Folk, Hip-Hop, Jazz,
and Rock passed; the Classical clip had one high window but did not meet the
two-window gate. Adding speech changed the set of clips called music: at 0 dB,
Classical passed while Hip-Hop did not. The SNR sweep also shows loss of several
music-positive clips as speech gets louder.

## Current audio-lane interaction

The bridge submits soundscape segments independently from ASR, so an ASR result
does not stop YAMNet. The EG2 safe-claim adapter discards its detailed music
claim when transcript text is present; the YAMNet `music` channel remains the
independent evidence source. EG2 candidate rankings currently reach VA only when
they overlap a positive YAMNet music segment. If mixed speech/music falls below
the YAMNet gate, its separate weak Music-class candidate can now reach VA when
raw max score is at least 0.20; the brain still receives the transcript if that
candidate is absent. EG2 candidate rankings remain gated on confirmed YAMNet
music support. The new route preserves the production threshold.

## Interpretation and limits

This is a small screening probe, not a recall/precision estimate. Each class has
one artist/track and only its opening four seconds; the track labels are not
human annotations of every window. The repeated synthetic TTS waveform has a
seam and does not represent spontaneous speech, room acoustics, a game mix, or
WASAPI capture. YAMNet's raw score is not calibrated probability.

The result supports keeping ASR and soundscape as independent timestamped lanes:
ASR presence must not erase music evidence. It does **not** justify lowering
the production music threshold: earlier two-tone controls generated a false
Music/Singing-bowl cue at a lower cutoff. Retain the 0.35 confirmation gate.
The implemented 0.20 candidate-routing cutoff exposes only an explicitly
uncertain music-like-or-tonal hypothesis; it is not validated as a detector
threshold and needs source-disjoint real speech-only and mixed-content negatives.

## CPU evaluation of the candidate route

`scripts/probe_yamnet_weak_music.py` reran the production detector with
`CPUExecutionProvider`, one intra-op and one inter-op thread. It used the three
source-disjoint spoken-query WAV fixtures already used by the local ASR probes,
18 individually licensed FMA tracks (four-second openings, 18 artists), and
source-deduplicated ESC-10 folds 3–5. It also mixed each of the three speech
fixtures in memory with one track from each of six broad music classes at
speech-over-music SNR +10, 0, and −10 dB. Only labels, scalar scores, and counts
were written to `runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json`;
audio and transcripts were not persisted.

| Cohort | Cases | Confirmed music | Weak candidate | Neither |
|---|---:|---:|---:|---:|
| ESC-10 non-music classes, source-disjoint | 181 | 0 | 0 | 181 |
| Recorded speech-only fixtures | 3 | 0 | 0 | 3 |
| FMA music, four-second openings | 18 | 16 | 1 | 1 |
| Real media: trailer/anime/gameplay/coding/song | 5 | 4 | 1 | 0 |
| Speech + music, SNR +10 dB | 18 | 6 | 8 | 4 |
| Speech + music, SNR 0 dB | 18 | 14 | 2 | 2 |
| Speech + music, SNR −10 dB | 18 | 14 | 1 | 3 |
| Synthetic speech/noise controls | 4 | 0 | 0 | 4 |

This is encouraging for routing a weak clue: it did not fire on the 181 labeled
non-music clips or the three speech-only fixtures, and it recovered 11 cases
where the confirmed gate abstained in the mixed set. The 54 mixtures reuse only
three speech recordings and six music tracks, so they are correlated probes,
not 54 independent samples. ESC-10 does not contain a speech-only class; the
spoken-query set is small and shares the fixture speaker. The FMA crop test also
shows one positive opening with only a weak candidate and one with no cue.
Therefore keep the channel explicitly unverified and retain the 0.35 confirmed
gate. Human-labeled real speech-only/media mixes, game audio, tonal controls,
and physical loopback under load remain required for full sensory acceptance.
On the five previously tested real-media excerpts, four passed the confirmed
gate and the anime excerpt produced one weak candidate (Music max 0.3819 in
1/10 windows); this matches the provisional earlier YAMNet finding and is a
useful example of the candidate's intended role, not independent human ground
truth.

Reproduction inputs: `runtime/synthetic-cases/source.wav` and
`runtime/audio-path-replay/data/fma-medium-selected/manifest.json`.

## Subthreshold Music hypothesis channel — 29 October 2026

The confirmed YAMNet music decision remains unchanged: `MUSIC_THRESHOLD=0.35` and the existing multi-window gate still define `kind=music`. A separate `music_hypothesis` diagnostic is now returned when an otherwise unconfirmed segment has raw Music score max ≥0.20. This is only a routing cutoff for an explicitly unverified, uncalibrated “possible musical or tonal background” candidate; it is not a probability, does not lower the acceptance gate, and is never retained as confirmed music in ambient memory.

`AmbientAudioASRBridge` publishes that evidence to a separate short-lived
`music_candidate` channel (12 s current-context TTL), while invalidating it on a
confirmed-music result or when the next segment has no candidate. The brain
packet labels it as a hypothesis. Its text includes raw max and hit/total
windows, explicitly marked “not a probability”, so the brain can distinguish a
single spike from repeated evidence without interpreting the score as calibrated.
The existing `music=unknown` omission is preserved, and ASR remains independent.
Focused coverage exercises weak-vs-confirmed scores, silence, fusion expiry,
packet serialization, and bridge delivery. The 0.20 routing cutoff still needs
broader source-disjoint real speech-only and mixed-media negative evaluation;
until then the brain must treat it as a weak clue only.
The regression suite also replays the archived two-tone score pattern
(one 0.3822 window, median 0.3021): it stays `kind=unknown` and only emits the
unverified candidate, never a confirmed music fact.
