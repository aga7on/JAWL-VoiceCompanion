# Offline visual-change detector sweep (corrected baseline)

Date: 2026-10-24
Scope: diagnostic, no-inference comparison of the production grayscale change signature with an exploratory color/edge hysteresis candidate on the existing 50-frame sequence and visual ledger. No production code or services were changed or run.

## Labels and scoring

The ledger contains 23 hard-change labels (clip starts plus `visible_shot_change`) and four separate coding `ui_state_change` labels. Each event is matched one-to-one to the nearest same-clip label within plus or minus 1 second. Clip starts are treated as new initial-scene events. UI-state recall is scored separately; ordinary scene-change events in the coding clip count as false positives for the UI-specific metric.

**Corrected baseline** now matches the production sensor operation: `image.convert("L").resize((32, 32))` using Pillow's default resampler (BICUBIC), then normalized mean absolute pixel delta with threshold `>=0.08`. The first frame of each clip initializes a new scene. This replaces the earlier report's incorrect Lanczos-resized grayscale baseline.

**Exploratory candidate** remains separate from production: per-pair RGB 16-bin/channel half-L1 histogram distance `H` plus a 64-by-36 Lanczos-resized PIL edge-map XOR fraction `E`; score `(H+E)/2`. Score `>=0.30` emits immediately. Scores `0.15` to `<0.30` emit at the onset after two consecutive medium transitions; `<0.15` resets pending state. This candidate is exploratory and tuned/evaluated on this same small fixture, not held-out data.

## Hard-change results

| Detector | Predicted events | Matched hard changes | False positives | Missed hard changes | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Production-equivalent BICUBIC grayscale `0.08` | 28 | 22 | 6 | 1 | 78.6% | 95.7% |
| Exploratory color/edge hysteresis | 23 | 18 | 5 | 5 | 78.3% | 78.3% |

The correction removes the previously claimed coding UI threshold hits. On coding frames, production-equivalent grayscale transition scores at montage t31 through t39 are `.0023, .0678, .0786, .0366, .0764, .0696, .0281, .0589, .0432`; none crosses `.08`. Hence baseline coding UI detection is **0/4**, not 2/4. The earlier Lanczos-resized pair scores `.0836/.0809` at two transitions were not representative of the production BICUBIC operation.

| Clip | Corrected baseline hard false / missed | Candidate hard false / missed | Coding UI changes detected |
|---|---|---|---|
| Trailer | false `t2,t3`; missed `t8` | false `t2`; missed `t6,t8` | n/a |
| Anime | none | none | n/a |
| Gameplay | none | false `t23` | n/a |
| Coding UI | none as hard cuts | false `t32,t35` as hard cuts | baseline `0/4`; candidate `2/4` (`t32,t35`; misses `t38,t39`) |
| Aqua | false `t42,t44,t45,t49` | false `t44`; missed `t47,t48,t49` | n/a |

The candidate's two coding hits are only a UI-state signal in hindsight; the candidate itself cannot classify them as UI updates, so they remain hard-cut false positives. It gains precision relative to the older baseline comparison but has materially lower hard-change recall and does not detect the two final subtle coding changes. Neither global image-change detector identifies the semantic type of a transition.

## Interpretation and next step

The production-equivalent detector has high recall on this sparse 1-fps labeled sequence, but flags extra adjacent frames in the trailer and Aqua clip and detects none of the four coding UI state changes. The candidate does not justify replacing it: hard-cut precision is effectively unchanged (78.6% vs 78.3%), recall is lower (95.7% vs 78.3%), and its apparent UI benefit comes with no built-in event-type classification. A UIA/OCR or targeted-region signal is a more direct path for coding changes; scene-cut and motion signals should remain distinct.

Next discriminator: freeze both formulas and run them on a source-disjoint sequence containing labeled hard cuts, within-shot motion, stable gameplay animation, and known UI updates. Separately, a coding-ROI signature sweep can test `t32,t35,t38,t39`, but must report UI-state recall/false alarms independently from hard-cut metrics. Consider a small learned detector only if deterministic color/edge/ROI signals fail on source-disjoint examples and the labeled data volume supports it.

## Artifacts

- Per-frame features, predictions, and scoring: `runtime/instances/goal-trailer-visual-replay-20261024/detector-sweep-20261024.json`
- Unchanged source JPEGs: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-20261024-r2/frame-001.jpg` through `frame-050.jpg`
- Reference labels: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip manifest: `runtime/multimodal-realclips-20261024/manifest.json`
