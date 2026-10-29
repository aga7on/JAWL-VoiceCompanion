# YAMNet and GigaAM on the five real QA audio segments

## Protocol

Replayed the existing five 10-second WAV cuts from `runtime/multimodal-realclips-20261024/probes/lowrate/` through the local YAMNet ONNX model and GigaAM v3 q8 CLI. YAMNet used only `CPUExecutionProvider`, one intra-op and one inter-op thread, and nine 2-second windows at 1-second hops per clip. GigaAM ran once per 10-second segment. No capture devices, companion services, TTS, or daily-profile configuration were changed.

The report persists class scores and timing only. Raw PCM and transcript text are not persisted; GigaAM wrote to short-lived temporary files that were deleted after each segment.

## Results

| Segment | YAMNet Music windows ≥0.30 | ASR output | YAMNet, 9 windows | GigaAM, 10 s |
| --- | ---: | --- | ---: | ---: |
| Russian live-action trailer | 4/9 | nonempty | 28.4 ms | 383.7 ms |
| Russian anime trailer | 1/9 | empty | 26.4 ms | 395.4 ms |
| RTS gameplay | 9/9 | empty | 25.8 ms | 376.4 ms |
| Coding UI video | 9/9 | empty | 25.4 ms | 386.5 ms |
| Aqua music video | 9/9 | nonempty | 26.2 ms | 388.4 ms |

At the current two-window ≥0.30 music gate, YAMNet emits presence for four of five segments and abstains on the anime segment. This is useful evidence that the production gate may miss quiet or changing music. It does not justify lowering the threshold: the clip is one source, not an independently labeled negative/positive set.

GigaAM returned text for the Russian trailer and song, and no text for the anime, gameplay, or coding segments. Only nonempty/character-count metadata is retained; there is no word-error score because this probe has no human-verified transcript reference.

YAMNet's scene-specific genre and instrument scores were weak. The strongest non-generic example was Synthesizer at 0.0802 in the coding segment; Aqua's Dance music score was 0.0382. These are not reliable genre or instrumentation claims. YAMNet supports a fast music-presence lane; rich music-vibe descriptions still need a separate evaluated model or grounded captioning path.

## Limits and decision

The clips retain media compression and edits, but this was offline WAV replay, not the live loopback/capture/fusion path. Speech quality is unscored, ASR transcript text was intentionally not retained, and all five segments are too few and too source-correlated to set production thresholds. The probe leaves the daily thresholds and model wiring unchanged.

Artifact: `runtime/audio-path-replay/out/realclip-audio-lanes-20261024.json`
Reproducible runner: `scripts/probe_realclip_audio_lanes.py`
