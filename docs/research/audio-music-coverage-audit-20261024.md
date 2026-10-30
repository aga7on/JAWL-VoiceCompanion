# Audio and music coverage audit — 24 Oct 2026

## Finding

The current audio lane has useful, bounded **speech transcription** and **broad sound/music event evidence**, but it does not yet provide reliable music-vibe descriptions. GigaAM and YAMNet run as independent CPU lanes. The production YAMNet lane is configured for persistent-event evidence, especially music presence; it is not an audio captioner. MusicFrame reports timestamped `music|unknown`, score/window measurements and energy trend, with unknown kept distinct from confirmed silence. Mood, genre, lyrics and detailed scene narration are deliberately not inferred from those measurements.

No model output in the artifacts below is treated as manual truth. The companion annotation file `runtime/multimodal-realclips-20261024/audio-ground-truth-provisional.json` is explicitly provisional; it must not be used to calculate accuracy or choose thresholds until a person listens and verifies it.

## Evidence-backed coverage

| Capability | What existing evidence supports | What it does not establish |
| --- | --- | --- |
| Russian ASR | On five 10-second media clips, GigaAM produced nonempty output for the Russian live-action trailer and Aqua song clip; a separate short loopback canary retained four speech observations. | No stored transcript/reference pair or WER/CER; song output may be singing. Russian/English external-media accuracy, word timing and mixed-media recall remain unscored. |
| Music presence | YAMNet repeatedly exceeded the exploratory music threshold on gameplay, coding UI and Aqua. In the paced MusicFrame replay, these were music-positive in 3/3 segments each; trailer 1/3; anime 0/3. The six-minute live canary detected music on its known electronic control and Aqua (14/15 windows on Aqua), with no soundscape drops/stale segments. | These clips lack human-verified boundaries. Anime abstention is not verified music absence. The live canary only establishes sensor routing and candidate presence on its playback, not general precision/recall. |
| Broad sound events | YAMNet exposes 521 AudioSet classes. The anime excerpt had candidate Explosion/Whoosh/Arrow labels; some controlled Bach/sax fixtures produced instrument-family candidates. | Event identities on the anime clip were not listened to; weak or changing tags cannot be promoted to event descriptions. |
| Music genre/style | On 18 FMA tracks with artist-disjoint sampling but proxy catalog labels, YAMNet and CLAP each matched 12/18 (66.7%). CLAP was 0/3 on Electronic and 1/3 on Jazz. | FMA labels were not independently confirmed; sample is too small for acceptance and class results are uneven. Similarity is not calibrated confidence. |
| Timbre/instruments | YAMNet found saxophone/wind-family evidence on a controlled sax fixture; CLAP retrieved saxophone on that fixture. | CLAP ranked a Bach excerpt as saxophone/jazz; prompt averaging did not fix it. Specific instrument facts are unsafe outside a gated, validated case. |
| Mood/affect and free-form description | `audio_understanding.py` sanitizes claims and abstains; YAMNet MusicFrame uses RMS/energy only as telemetry. | MERT produced affect on silence/noise/speech; MusicNN and HuBERT false-tagged controls; Whisper Tiny hallucinated a voice on silence; Qwen2.5-Omni used speculative mood/instrument language and showed cross-modal leakage. None currently qualifies for always-on mood or grounded music captioning. |
| Runtime | YAMNet one-thread CPU probes are about 2.7 ms per 2-second window or about 22 ms per 8-second clip, depending on pipeline. CLAP audio inference is about 90-100 ms per 8-second clip. The integrated canary had 0 capture drops and 0 YAMNet processing drops over ~4 minutes. | No matched full-companion resource/voice-impact comparison for CLAP; no 30-60 minute labeled mixed-media acceptance or 8-hour full profile acceptance. Isolated model timings/RSS are not incremental companion cost. |

## Concrete next CPU-only test

Use the already-local five `probes/lowrate/0*.wav` media segments and the licensed 18-track subset in `runtime/audio-path-replay/data/fma-medium-selected/`, plus existing speech/noise/silence controls. Keep this offline: no mic/loopback, companion, TTS, or profile. Run YAMNet and GigaAM on CPU with one thread; preserve the existing independent lanes. First complete human labels for the five clips and adjudicate the ambiguous speech/vocal/effect spans. Until then, score only deterministic replay/stability and do not call it accuracy.

For a fresh, non-overwriting smoke of the already-repeated five-clip inference path, use a new output name:

```powershell
python scripts/probe_realclip_audio_lanes.py --output runtime/audio-path-replay/out/realclip-audio-audit-rerun-20261024.json
```

This existing runner is CPU-only and writes scalar scores plus ASR nonempty/character-count metadata, never transcript text or PCM. It does **not** report WER and is only a pipeline reproducibility check. The more informative acceptance run should use the production 4-second soundscape segmenter and real GigaAM on the same five clips, but `scripts/probe_music_frame_bridge.py` currently uses a no-op ASR and writes a fixed artifact (`music-frame-bridge-five-case-20261024.json`). Before that run, give the probe a caller-selected output path and real-ASR option, or reproduce it in a throwaway harness that writes a new artifact; do not overwrite the existing bridge report.

Report these metrics separately:

1. With human labels available: per-window YAMNet/music event precision, recall and F1; false music claims and abstention coverage; speech/music overlap recall; onset/offset and transition delay.
2. For GigaAM: WER/CER against a human transcript, speech-event recall, missed/repeated words and capture-to-final age. Treat singing/lyrics separately from dialogue.
3. For the integration: ASR and MusicFrame coexistence on mixed spans, prove music classification never gates ASR, queue max/drop/stale counts and source-time freshness.
4. CPU/resource: inference p50/p95, CPU time, process-tree private bytes/RSS, peak and end-of-run drift.

Use clip/source-disjoint splits if tuning thresholds or comparing CLAP. The 18 FMA artists are unique within the current subset, but the catalog genre is still only a proxy label. CLAP can be included as a conditional research comparator using its pinned ONNX pair and precomputed prompt prototypes; keep it out of the live path unless a listener-verified held-out set demonstrates acceptable false-claim rate and the incremental resource budget fits.

## Blocker

The real blocker for measuring music/event-description quality is **no listener-verified audio ground truth for the game/video clips**. Existing reports intentionally discard ASR text, and the provisional annotation file correctly marks all model-derived intervals as unresolved. Without a human label pass, repeated inference can show deterministic behavior and runtime stability, but cannot show whether speech, vocals, event names, silence or changes were actually understood. No code or profile defect is currently established by these artifacts; the unresolved work is labeled evaluation and longer integrated acceptance.

## Sources

- `docs/research/music-frame-bridge-20261024.md`
- `docs/research/live-audio-gigaam-canary-20261024.md`
- `docs/research/realclip-audio-five-case-recheck-20261024.md`
- `docs/research/yamnet-gigaam-overlap-20261024.md`
- `docs/research/music-perception-roadmap-20261024.md`
- `docs/research/music-sensory-candidate-evaluation-20261024.md`
- `docs/research/audio-ground-truth-provisional-20261024.md` (scaffold only; not truth)

## Additional deterministic replay (2026-10-24)

Ran the five-case CPU-only smoke with a fresh output path: `runtime/audio-path-replay/out/realclip-audio-audit-rerun-20261024.json`. It completed in 3.1 seconds with no model errors. All five YAMNet window score arrays and music-window counts exactly match the two earlier artifacts (`realclip-audio-lanes-20261024.json` and `realclip-audio-lanes-audio-agent-20261024.json`). GigaAM nonempty/empty decisions and normalized character counts also match: Russian trailer and Aqua are nonempty (42 and 46 normalized characters); anime, gameplay, and coding are empty. Per-clip inference latencies were 549.3, 380.4, 382.7, 392.8, and 393.0 ms. The artifact confirms `cpu_only=true`, `raw_audio_persisted=false`, and `transcript_text_persisted=false`.

This adds a third reproducible pass, not a quality score: the runner retains only scalar ASR metadata, so transcript correctness and lyrics remain unverified.
