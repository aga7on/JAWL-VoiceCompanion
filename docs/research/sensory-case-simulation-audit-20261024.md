# Four-hour sensory case simulation audit — 24 Oct 2026

## Result

The clean 20-case simulation completed 49 batches over 14,411.6 seconds
(4 h 00 m 11.6 s): 980 case executions, zero recorded runtime errors. Its
`passed` status means the model calls and playback-suppression contract ran
without execution errors. It does not mean that the descriptions or labels
were semantically correct.

The run used a CPU-only Qwen3.5-0.8B server (four threads), EmbeddingGemma 2
ONNX, and GigaAM CPU against local fixtures. It did not open physical capture
devices, run the companion/Hikari turn path, or exercise the production
YAMNet-to-MusicFrame path. Raw media and transcript text were not persisted.
The report stores short visual captions, categorical audio outputs, ASR
character counts and hashes.

## Reliability evidence

- Every case ran 49 times and had zero execution errors.
- Across 49 sampled batches, system CPU averaged 10.6% and peaked at 30.6%.
- Qwen RSS stayed between 1,134.8 and 1,137.2 MiB (mean 1,136.4 MiB).
- Each fixed visual fixture produced one unique caption across its 49 repeats.
- Each fixed audio fixture produced one unique top label; ASR character counts
  and hashes were stable per fixture.

These results support repeatability and bounded resource use for this isolated
fixture harness. Stable output is not proof of recognition accuracy.

## Semantic failure exposed by negative controls

The audio cases call `EmbeddingGemmaSensoryCortex.classify_audio_wav`, which
returns the highest-scoring label without an abstention threshold. It
systematically assigned non-speech labels to speech and negative controls:

| Fixture | Repeated label | Raw top score | Expected signal |
| --- | --- | ---: | --- |
| `A09-russian-speech-1` | `energetic_action_music` | 0.6764 | Russian speech |
| `A12-short-phrase-pause` | `energetic_action_music` | 0.6786 | Speech followed by pause |
| `A14-quiet-speech` | `energetic_action_music` | 0.6961 | Quiet Russian speech |
| `A16-noise-only-negative` | `dramatic_tension_sfx` | 0.7365 | Noise, no speech |
| `A17-silence-negative` | `energetic_action_music` | 0.6962 | Silence, no speech |
| `AV19-speech-over-scene` | `energetic_action_music` | 0.6764 | Russian speech with an image |

These are EmbeddingGemma prototype similarities, not calibrated
probabilities. They must not be treated as production facts or music-quality
labels. The production ambient path uses a separate YAMNet soundscape lane and
explicit unknown/abstention behavior; this simulation did not test that path.

The ASR results establish stable non-empty output and output length/hash for
the fixed speech fixtures. Since the run deliberately did not save transcript
text or compute WER/CER against references, it does not establish transcript
accuracy. The music fixture likewise does not establish genre, mood, or
instrument accuracy.

## Acceptance decision

Mark this run **PASS for isolated four-hour harness reliability only**. Keep
full sensory quality, production audio semantics, capture-to-brain fusion,
integrated 30–60-minute co-watch, and full-profile 8-hour/24/7 acceptance
open. Do not use the raw argmax labels above as current-context or memory
claims.

## Evidence and reproduction source

- Clean run: `runtime/sensory-case-simulation-20261024-clean.json`
- Harness: `scripts/run_sensory_case_simulation.py`
- Audio prototype argmax: `src/jawl_voicecompanion/eg2_sensory.py`,
  `classify_audio_wav`
- Production soundscape lane: `src/jawl_voicecompanion/yamnet_soundscape.py`,
  `src/jawl_voicecompanion/ambient_audio.py`
