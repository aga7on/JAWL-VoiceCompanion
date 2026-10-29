# Audio lanes: repeat check on the five 10-second clips (2026-10-24)

## What was replayed

Re-ran the existing local, CPU-only YAMNet ONNX + GigaAM v3 q8 probe over the five WAVs used in the 50-second montage. No loopback, microphone, companion server, or TTS was started. The runner writes only scalar YAMNet scores and ASR nonempty/character-count metadata; transcript text and PCM are not persisted.

Command:

```powershell
python scripts/probe_realclip_audio_lanes.py --output runtime/audio-path-replay/out/realclip-audio-lanes-audio-agent-20261024.json
```

Each clip is analyzed independently as a 10.01-second mono 16 kHz segment. YAMNet scores nine overlapping 2-second windows at 1-second hops. Times below are relative to each case; add the case's montage start (0, 10, 20, 30, or 40 seconds) for 50-second-montage coordinates. GigaAM receives one full clip per call and exposes no retained word-level timestamps in this probe.

## Repeatability and observations

The original artifact, its recheck, and this new run produced identical per-window YAMNet scores and identical ASR nonempty decisions for all five clips. In this third run, YAMNet inference took 25.5–27.4 ms per 10-second case; GigaAM took 373.5–399.6 ms. Those are offline model timings, not end-to-end live age.

| Montage time | Clip | YAMNet Music ≥ 0.30 | ASR output | Main evidence |
| --- | --- | ---: | --- | --- |
| 00–10 s | Russian live-action trailer | 4/9 windows | nonempty, 42 normalized characters | Speech dominates 1–5 s windows (0.475–0.775); Music crosses gate at 0–2 s and 5–9 s. Mixed Speech+Music appears in the 5–7 s window. |
| 10–20 s | Anime trailer | 1/9 | empty | Effects dominate 2–9 s: Explosion peaks at 0.165, Whoosh at 0.149, Arrow at 0.131. Music crosses gate only in 0–2 s (0.382); no persistent music claim. |
| 20–30 s | RTS gameplay | 9/9 | empty | Music score ranges 0.413–0.855. Other top labels vary and remain weak (e.g. Splash 0.103, Liquid 0.092, Pigeon 0.053); no stable specific sound tag is supported. |
| 30–40 s | Coding UI | 9/9 | empty | Music score 0.825–0.983. Synthesizer peaks at 0.341 and Keyboard at 0.339 in 4–6 s, but neither repeats strongly enough to meet the detector's stable-tag gate. |
| 40–50 s | Aqua — “Roses Are Red” | 9/9 | nonempty, 46 normalized characters | Music score 0.907–0.985. Dance music peaks at 0.176; Electronic music peaks at 0.081. These are weak class scores, not a validated style label. |

The gate result is stable on this exact set: four clips produce persistent music (trailer, gameplay, coding, Aqua), while the anime clip abstains. This does not establish whether that anime excerpt has a quiet/changed soundtrack: the manifest specifies expected checks but has no listener-verified audio labels. Do not tune the gate from this set alone.

## What the evidence proves — and what it does not

- **Proved:** the local CPU path reproducibly detects music presence on four clips and emits time-local YAMNet scores; it can show Speech and Music scores together; GigaAM returns nonempty text for the Russian trailer and Aqua excerpt, and empty output for anime, gameplay, and coding.
- **Not proved:** transcript correctness, recognized words/lyrics, speaker attribution, word or phrase timestamps, music onset/offset ground truth, sound-event precision, or scene/audio synchronization. The artifact intentionally omits transcript text and there is no human transcript/WER reference. Each inference is a batch over the complete 10-second clip.
- **Style and description remain unsolved:** YAMNet's genre/instrument candidates on Aqua and coding are low or nonpersistent. The detector safely emits music presence without a specific style; this is not a grounded music-vibe description. Sparse effect labels in anime are candidate events, not verified event captions.
- **24/7 behavior remains unproven:** this is a three-repeat offline replay of five source-correlated clips, not a continuous mixed-media soak. It does not measure queue age, source loss/recovery, false-claim rate on labeled negatives, audio-memory/fusion timing, or real-time ASR age. Existing five-second rolling ASR evidence has a p50 age around 5.2 s because the window itself is five seconds; production's 15-second segment cap can yield roughly 14–15 s observation age.

## What blocks higher quality

1. The five cases lack independent audio ground truth. In particular, no human labels mark speech/music/effect boundaries or what the soundtrack actually contains.
2. The ASR probe discards transcript text and timestamps. A nonempty result is only a signal that something was decoded; it cannot establish Russian speech accuracy or English lyric recognition.
3. Current YAMNet is an event/presence classifier. It has no calibrated genre/mood confidence and no free-form grounded description; repeated top labels on these five excerpts are too weak for those claims.
4. Existing report-level timestamps refer to overlapping analysis windows. The production event contract is largely segment-end time; word-level alignment and onset/offset remain unavailable.
5. Offline replay does not test the live pipeline under load. The separate soundscape worker was added after prior reports; it still needs integrated live queue/freshness/CPU/RSS acceptance, followed by a 30–60-minute labeled mixed-media run.

## Artifacts

- New repeated-run output: `runtime/audio-path-replay/out/realclip-audio-lanes-audio-agent-20261024.json`
- Original output: `runtime/audio-path-replay/out/realclip-audio-lanes-20261024.json`
- Prior recheck: `runtime/audio-path-replay/out/realclip-audio-lanes-recheck-20261024.json`
- Reproducer: `scripts/probe_realclip_audio_lanes.py`
- Case timing/source manifest: `runtime/multimodal-realclips-20261024/manifest.json`
