# Decision memo: music style and event lane — 24 Oct 2026

## Recommendation

Keep YAMNet + MusicFrame as the always-on CPU foundation. Improve its temporal state logic only for **presence, uncertainty, freshness and audible-change timing**. Do not present its raw genre/event scores as music-vibe facts. Do not add a caption model or train a custom style classifier yet. The next discriminator should compare the baseline with one conditional semantic candidate and a tiny supervised head on identical, listener-labeled, source-disjoint clips.

## Three paths

| Path | Pros | Cons and current evidence | Best role |
| --- | --- | --- | --- |
| **1. Improve YAMNet + MusicFrame thresholds/temporal logic** | Already installed, CPU-only, ~16 MB weights; two-second window inference around 2.65/2.95 ms p50/p95 in the isolated one-thread probe. No new model/RAM. Persistence, hysteresis, per-window uncertainty and transition timestamps can reduce flicker and make music-on/off, speech/music overlap and broad events more useful. | It only stabilizes evidence the model already has. It cannot repair missing genre semantics. On five real excerpts the music gate yielded trailer 1/3 and anime 0/3, while gameplay/coding/Aqua were 3/3; no listener labels tell whether those abstentions are misses. On 18 FMA tracks, top AudioSet genre matched proxy labels 12/18, only three artists per class. Lowering the threshold could increase false positives; there is no labeled set to choose the tradeoff. | **Always-on baseline** for music/event presence, independent ASR, unknown/abstain and energy measurements. |
| **2. Train a small task-specific classifier** | For a narrow ontology, a linear/compact head can be tiny and fast, calibrated to explicit labels, and potentially simpler to deploy than a second large model. Candidate outputs: broad style family, instrumental/sung vocal, or a few audible instrument families. It need not generate prose; the brain can compose a concise description from accepted tags plus MusicFrame energy/trend. | No listener-labeled JAWL set exists. Current FMA has only 18 tracks, three artists per style, and catalog labels are proxy labels. Training on it would overfit; evaluation would be weak. It also creates dataset licensing/provenance, split, calibration, versioning, and retraining work. A classifier trained from CLAP embeddings still pays CLAP inference/RAM; a head on YAMNet scores is cheap but may lack enough style information. It cannot responsibly predict mood or natural-language scene captions from these labels. | **Possible second-stage model** only after narrow labels are defined and enough source-disjoint examples exist. Prefer a head over YAMNet outputs if it passes; compare CLAP embeddings only if YAMNet features lack signal. |
| **3. Use a larger conditional model** | Can compare rich text concepts without training a new task head; can be triggered only after persistent music or an explicit user question. CLAP HTSAT ONNX is already available as a CPU retrieval candidate; text prototypes can be precomputed. | CLAP is similarity retrieval, not caption generation. On 18 FMA proxy labels, top-1 was 12/18; Electronic 0/3 and Jazz 1/3. It confused a Bach organ excerpt with saxophone/jazz; prompt averaging did not fix the error. Audio encoder is ~90-100 ms per 8s and the isolated Python process was ~0.93 GiB with both encoders (~0.48 GiB audio-only probe). This is a substantial always-on budget and incremental companion cost is unknown. Larger music captioners (for example MOSS-Music 8B) are not viable always-on CPU candidates. | **Conditional research comparator**, only if human-labeled results demonstrate enough quality to justify memory and latency. |

## Is a small custom model simpler than another pretrained model?

**At inference and product integration, it can be simpler. At this project stage, it is not simpler overall.** A compact, explicit classifier can avoid a generative model and return a small set of calibrated tags. But it still needs labeled source-disjoint data, annotation rules, calibration, held-out evaluation, artifact/version management and drift checks. With no trusted labels, training is just a faster way to encode the current guesses. A pretrained model is quicker to probe; it is not automatically more accurate or cheaper in RAM. The rational sequence is: first stabilize the low-cost evidence layer, then run one paired test of CLAP retrieval versus a small head, and keep whichever earns its claims on held-out human labels.

## Next discriminating CPU-only experiment

Use the existing licensed 18-track subset (`runtime/audio-path-replay/data/fma-medium-selected/`) and the five local media WAVs. Human listeners must first verify broad style, vocal/instrumental status, a short list of audible instrument families, speech/music/effect spans and confidence. Keep FMA catalog tags as metadata only until confirmed. Split by parent recording/artist; the present three-per-class subset is an **exploratory screen**, not an acceptance set. Add more labeled source recordings before a deployment decision.

Then replay the same fixed 8-second crops on CPU, one thread, in three arms:

1. Existing YAMNet style scores plus current MusicFrame persistence; include a small dev-only threshold/hysteresis grid for presence and transition stability.
2. Frozen CLAP text prototypes over the same narrow style/timbre/vocal ontology; use existing pinned ONNX model and precomputed prompt embeddings.
3. A tiny regularized linear head using frozen YAMNet scores first; if those features cannot separate the human labels, compare a head on CLAP embeddings. Fit only on training artists, select thresholds on dev, and report one untouched artist-disjoint test split. Do not train a free-form captioner.

Report per-capability counts, precision/recall/F1, macro-F1, emitted-label precision and abstention coverage; do not collapse presence, style, vocal status and instruments into one score. Add music false-positive rate on speech-only/effects/noise/silence controls, speech+music overlap recall, top-1/top-3 and runner-up margin for style, transition delay, p50/p95 CPU time and process-tree private bytes. For energy, compare measured trend with annotator trend; do not call energy a mood label. Because the current set is too small, this pass can reject bad options and expose feature gaps, but cannot certify production thresholds.

For the five video/game excerpts, preserve the existing provisional annotation JSON as a checklist only. Do not score against it until humans verify it. If the listening pass cannot be done now, run only a deterministic replay/stability check and report it as such. Do not use audio model scores as their own ground truth.

## Decision gates

- **Temporal-logic change:** require the human-labeled clips to show a measurable presence/transition improvement without increasing false music claims on negative controls. Keep ASR independent in every arm.
- **Custom head:** require a clear held-out precision/coverage improvement over YAMNet and fixed-prompt CLAP, with enough independent labeled sources; otherwise the label/data maintenance is not justified.
- **Conditional CLAP:** require held-out style/timbre/vocal precision with abstention, and a matched full-companion CPU/RAM/voice-latency budget before wiring it into any profile.
- **Mood/free-form description:** none of the three paths is accepted for factual mood narration by current evidence. Keep it out until a separate human-rated validation supports it.

## Evidence reviewed

- `docs/research/music-vibe-build-vs-train-20261024.md`
- `docs/research/audio-music-coverage-audit-20261024.md`
- `docs/research/music-perception-roadmap-20261024.md`
- `docs/research/music-sensory-candidate-evaluation-20261024.md`
- `docs/research/music-frame-bridge-20261024.md`
- `docs/research/yamnet-gigaam-overlap-20261024.md`
- `docs/research/audio-ground-truth-provisional-20261024.md` (scaffold only, not truth)

No model, service, profile or TTS process was started or modified for this memo.
