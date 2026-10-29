# YAMNet sound-event candidate lane — 29 October 2026

## Change

The CPU YAMNet detector now retains a separate `event_candidates` result beside
its existing music-presence result. It emits only a small allowlist of broad
sound/action classes after repeated score crossings (raw score >= 0.15 and at
least `max(2, ceil(windows * 0.25))` windows). Scores are not probabilities.
The emitted text says that these are unverified YAMNet hypotheses. Music tags,
ASR transcripts, and these sound-event candidates remain separate.

`AmbientAudioASRBridge` sends the candidate lane into `PerceptionFusion`; the
brain VA packet preserves it as a hypothesis with detector/source/interval
metadata. Empty event results invalidate the prior candidate. A non-flushing
pause/cancel invalidates all live audio channels; a deliberate final flush keeps
its source-timestamped evidence until its normal TTL expires. The event lane has
a 12-second current TTL and 30-second text-history TTL.

## Real-clip replay

Five existing local 10-second clips were replayed through the CPU ONNX model.
The probe persists only class names/scores/window counts, not PCM.

| Clip | Music gate | Recurrent event candidates |
|---|---|---|
| Russian live-action trailer | Music | None |
| Russian anime trailer | Unknown | None at current 0.15 event cutoff |
| RTS gameplay | Music | None |
| Coding UI video | Music | None |
| Aqua music video | Music | None |

An earlier experimental 0.10 cutoff surfaced an `Explosion` candidate on the
anime interval (0.1371, 4/10 windows), but it falls below the current 0.15
operating threshold and is suppressed. There is no independently annotated
per-second sound-event ground truth for these five excerpts. A prior coding clip had high `Synthesizer` and
`Keyboard (musical)` scores; neither is in the sound-effect allowlist, and
neither leaked into this lane. The result therefore stays explicitly
hypothetical and cannot be used as a confirmed event or as a spoken assertion.

## Verification and limits

- Focused suites after this follow-up: 73 passed, 10 subtests; `py_compile` and
  `git diff --check` pass.
- Python compilation succeeded for the modified modules and replay runner.
- Reproducible replay: `scripts/probe_yamnet_sound_events.py`; raw-free result:
  `runtime/audio-path-replay/out/yamnet-events-realclips-20261029.json`.
- Not proven: class precision/recall on source-disjoint SFX, silence/noise
  negatives, live NVIDIA loopback, event-to-brain uptake, or behavior under
  sustained CPU contention. Full live audio acceptance remains open.

## Small labeled ESC-10 control

To check whether the allowlist itself hid useful YAMNet classes, 12 five-second
ESC-10 clips were fetched individually from the upstream repository: two
different source recordings each for dog, crying baby, helicopter, chainsaw,
rain, and clock tick. ESC-10 is identified by the upstream README as the CC BY
subset of ESC-50; the rest of ESC-50 is CC BY-NC. The downloaded clips live only
under ignored `runtime/` and are not committed. The probe stores labels and
scores, never PCM: `scripts/probe_yamnet_esc10.py`.

The first run at score cutoff 0.10 showed that the old allowlist hid exact recurrent outputs for
`Baby cry, infant cry`, `Helicopter`, `Chainsaw`, `Rain`, and `Tick-tock`.
Those labels are now admitted as **unverified candidates**. Replaying the same
12 clips after that change produced candidates on 10/12 clips: expected sounds
were represented on both helicopter, chainsaw, and rain recordings, on one of
two baby-cry recordings, and on one of two clock recordings. Both dog controls
abstained. One baby-cry clip instead produced a weak `Laughter` candidate
(0.1122 median raw score, 2/4 windows), a concrete false cue which the current
0.15 gate suppresses. One clock clip
was classified by YAMNet as music (0.4885) but did not pass the two-window
music gate. Helicopter/engine and rain labels also overlap semantically, so the
brain should treat this list as cues and not repeat every tag as a separate
fact.

This first small subset was exploratory and led to a broader vocabulary. It is
retained as an early checkpoint; the final rule below uses a larger sample.

## Source-disjoint fold evaluation

The upstream ESC-10 metadata provides folds with the same original recording
kept within a single fold. For model selection, folds 4 and 5 were downloaded
one file per `src_file` (59 and 57 clips). Generic `Vehicle`, `Motor vehicle
(road)`, `Engine`, and `Aircraft` candidates repeatedly matched unrelated
classes; excluding those families improved exact-label precision on fold 5
from 59/88 (67.0%) to 59/67 (88.1%) while keeping 41/57 clips with an exact
category candidate. The raw-score cutoff sweep favored 0.15 as a useful
precision/coverage tradeoff over 0.10. The implementation now uses that cutoff
and the narrower class list.

Fold 3 was then run as an untouched source-disjoint validation fold (65 clips,
one recording per source). At the frozen 0.15 cutoff, 58/64 emitted labels
matched the clip's ESC-10 category (90.6% strict label precision), and 40/65
clips had at least one exact category-specific candidate. Across all three
folds: 171/189 emitted labels matched the single ESC-10 class (90.5%); 121/181
clips emitted at least one exact category tag. Per-class exact-tag coverage at
0.15 was: crying baby 8/8, dog 21/23, rain 21/24, rooster 16/19, sea waves
12/14, chainsaw 9/14, clock tick 14/24, crackling fire 9/20, helicopter
4/11, and sneeze 7/24. YAMNet's separate music gate fired on 0/181 of these
non-music clips.

These are results on one labeled corpus, not calibrated production accuracy:
ESC-10 has only ten classes, each clip is five seconds, and the tested folds do
not cover speech/music mixtures or gameplay audio. Emitted tags remain
unverified hypotheses in the brain packet. Silence/noise controls, live NVIDIA
loopback, and live brain uptake remain open. Runners:
`scripts/fetch_esc10_fold.py` and `scripts/probe_yamnet_esc10.py`. Upstream
dataset and license notes:
[ESC-50 repository](https://github.com/karolpiczak/ESC-50).
