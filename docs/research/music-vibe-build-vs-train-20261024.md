# Music-vibe lane: build vs. train decision (2026-10-24)

## Decision

**Build a deterministic, abstaining `MusicFrame` layer first. Do not train a micro-model yet, and stop broad model hunting for now.** The evidence already supports a cheap CPU foundation for music presence, speech/music coexistence, broad acoustic changes and time-bounded observations: YAMNet plus the independent GigaAM lane. It does not support dependable genre, mood, or free-form music description. A deterministic layer can report observable properties now—music/speech/effects scores, loudness and energy trend, brightness, onset density, estimated pulse range and transitions—without pretending those are genre or emotion. It cannot infer musical meaning or trustworthy style by itself.

If users still need named styles after that baseline is useful, the next experiment should be **one conditional semantic scorer over a human-labeled set**, first comparing frozen CLAP embeddings with a small head. Training a micro-model before obtaining those labels would fit noise and source quirks; the current probe set is evaluation evidence, not training data.

## Evidence from the local probes

| Candidate | Evidence | Decision for 24/7 |
| --- | --- | --- |
| **YAMNet ONNX** | Small 16.1 MB model, CPU-only. Two-second windows measured 2.65/2.95 ms p50/p95 at one thread. It separates known music from speech/noise/silence controls and provides event/instrument-family scores. On the 18 artist-disjoint FMA tracks, broad-style top-1 matched catalog labels on 12/18 (66.7%); only three artists per style, labels are catalog proxies, and median top-style margin was 0.02098. On the five real excerpts, music presence repeated well for four; style/instrument scores stayed weak. | Keep as the presence/event baseline. Do not verbalize its genre, mood or one-off sound tags as facts. |
| **CLAP HTSAT ONNX** | Useful conditional text-audio retrieval; CPU audio-encoder p50/p95 about 93.7/97.2 ms per 8 s crop. It also matched 12/18 FMA catalog styles, but Electronic was 0/3; it confused the known Bach organ with saxophone/jazz, and the prompt-bank run still preferred jazz over classical. It separated three of four short controls, but put a speech-only case slightly above speech-over-music. The full isolated pair/process was ~0.96 GiB RSS; an audio-only probe was ~482 MiB, not a measured incremental companion cost. The examined export declares BSD-3-Clause. | Best candidate for a later on-demand comparison, not a current always-on dependency. Precomputed prompt embeddings save the text encoder; resource and factuality gates remain. |
| **MERT-v1-95M affect** | 15 s inference about 1.9 s; emitted valence/arousal for music, speech, silence and noise, so it has no validated music-only gate or mood accuracy here. The quantized card claims Apache-2.0, while the base model declares CC-BY-NC-4.0. | Do not use for live mood or user emotion. Licensing and human-label validation both remain unresolved. |
| **MusicNN** | Only 3.18 MB weights, but the PyTorch process reached ~770 MiB RSS. It tagged clean speech as female/guitar/singing, noise as techno/harpsichord, and silence as guitar/classical/opera; it missed saxophone and made conflicting Bach instrument claims. | Reject this checkpoint for the always-on lane. Small weights do not make the deployment small or reliable. |
| **Whisper Tiny audio captioner** | 0.69–0.79 s per 12 s crop, ~830 MiB RSS. Similar generic Bach/sax captions, missed music under speech and hallucinated a male voice on digital silence. Training audio terms are unclear. The separate Whisper-small multitask candidate has no completed weight fetch/inference and inconsistent CC-BY vs. CC-BY-NC statements. | Reject Tiny for current-context claims. Keep Small unevaluated and do not count it as evidence. |

The matched 66.7% YAMNet/CLAP FMA score is not a tie-break: each result is based on 18 tracks, three artists per style, and uploader/catalog labels not verified by listeners. Neither is accepted as a genre classifier. The 50-second real-media replay likewise proves stable repeated scores, not semantic correctness; its ASR artifact stores only presence/length, not words or references.

## Smallest useful labeled benchmark

Use parent-recording identity as the split unit; all excerpts from one song, video, game capture or artist/session must stay in the same split. Annotate source, license, start/end time, annotator confidence and disagreement. The minimum label set for choosing a lane is:

1. **Sound state by time window:** music-only, speech-only, speech+music, nonmusic effects/noise, silence, and ambiguous/unknown.
2. **Broad style, only when music is present:** classical/orchestral, electronic/synth, pop, rock/metal, jazz, hip-hop, acoustic/folk, and mixed/unknown.
3. **Audible properties:** instrumental vs. sung vocal; broad instrument family only when clearly audible; low/medium/high energy and rising/stable/falling trend; slow/medium/fast pulse with an estimated BPM interval; salient music/effect onset, offset and transition.
4. **Speech track:** transcript reference and word/phrase times, including speech over music. Score ASR separately; a nonempty string is not an accuracy result.

For a **model-selection screen**, target at least 30 independent parent recordings per broad-style class and 30 per sound-state control, with at least three unrelated artists/sources per style represented in every split. Use a separate development set to choose thresholds and a blind test split for reported scores. This is an engineering floor for exposing large failures, not a statistical guarantee. For a learned head, collect at least 100 independent labeled source clips per trained class plus separate 30-source calibration and 30-source blind-test groups; otherwise prefer rules and abstention.

## Proposed gates before choosing a semantic model

- Music presence: on blind sources, precision ≥99% on speech-only, effects/noise and silence controls; recall ≥90% on music-only and ≥80% on speech+music at tested SNRs. Report class-wise counts and intervals. A literal zero false positives in a small set does not prove a 1% error rate; about 300 independent negative cases with zero errors are needed even for the simple “rule of three” upper bound near 1%.
- Style: emitted-label precision ≥90%, macro-F1 ≥0.75, and coverage ≥50% on the blind music-only set. Calibrate a score/margin threshold on development data; otherwise return `unknown`. Count abstentions as coverage, not as errors hidden from the report.
- Instrument families and vocal/instrumental status: precision ≥90% among emitted tags, with independent scoring per class. Do not add named instruments or lyrics based on a broad family score.
- Dynamics: tempo estimate within ±10 BPM on ≥80% of labeled steady-tempo excerpts; transition boundaries within ±1 second on ≥80%. Human listening labels are required. Keep “energy increased” distinct from “music became tense/sad.”
- Mood or natural-language vibe: keep out of the 24/7 contract until human ratings show at least Spearman ρ≥0.6 for coarse valence/arousal and generated factual statements reach ≥95% supported claims with no unsupported mood/scene claims on negative controls.
- Runtime: no queue growth or stale delivery; freshness p95 ≤3 seconds for current-context claims; any optional semantic worker must stay latest-only, with no voice-latency regression above the existing 500 ms/10% gate and whole-process PrivateBytes plateau within the documented +512 MiB provisional budget.

These thresholds are proposed acceptance gates, not results from the current artifacts. If CLAP or a trained head misses style thresholds, the correct product behavior is a factual acoustic description plus `style=unknown`, not a more confident generator.

## Local evidence referenced

- `docs/research/music-sensory-candidate-evaluation-20261024.md`
- `docs/research/music-perception-roadmap-20261024.md`
- `docs/research/yamnet-audio-event-probe-20261024.md`
- `docs/research/realclip-audio-five-case-recheck-20261024.md`
- `runtime/audio-path-replay/out/yamnet-fma-style-probe-20261024.json`
- `runtime/audio-path-replay/out/fma-medium-clap-style-probe-20261024.json`
- `runtime/audio-path-replay/out/musicnn-candidate-probe-20261024.json`
- `runtime/audio-path-replay/out/music-model-candidate-probe-20261024.json`
- `runtime/audio-path-replay/out/whisper-tiny-caption-probe-20261024.json`
