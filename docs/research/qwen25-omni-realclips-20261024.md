# Qwen2.5-Omni exploratory replay on five real clips ? 24 Oct 2026

## Protocol

The 50-second local QA montage was split at its five 10-second boundaries. To fit the active Qwen2.5-Omni server's 12,288-token context, video inputs were sampled at 1 frame/s and scaled to 640?360; the paired audio was separately exported as MP3. Each segment received one video-only and one audio-only call with `cache_prompt=false`. The valid trace has 10/10 requests completed, zero cached prompt tokens, and per-call latency of 2.18?2.63 s for video and 0.40?0.55 s for audio. Those are direct endpoint timings, not continuous capture-to-brain latency.

The unmodified 720p/25fps 10-second videos exceeded context (25,411 prompt tokens vs 12,288) and returned HTTP 400. A first reduced-resolution run was invalid because prompt caching reused the previous multimodal prefix and later calls repeated the trailer. Those two artifacts are marked invalid in their JSON. The accepted run explicitly disabled prompt caching; llama.cpp documents that chat prompt caching is enabled by default and can be disabled per request with `cache_prompt=false` ([server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)).

## Qualitative observations

| Segment | Video-only result | Audio-only result |
| --- | --- | --- |
| Russian film trailer | Broad shot sequence and title/context recognized, but the model reversed who lifts whom in the shoulder-carry action. | Detected Russian dialogue followed by music; quoted speech has no independent transcript reference and is unscored. |
| Anime trailer | Recognized animated scene changes and Russian title cards; some mood language is interpretive. | Detected a rhythmic electronic score, with no vocal/lyric claim. |
| RTS gameplay | Best visual case: strategy-game battle, units, resource UI and minimap. Some action claims may exceed 1-fps samples. | Reduced the track to generic electronic music and omitted distinct game effects. |
| Coding-assistant UI | Recognized model/version list, cursor and settings; this sample tests tool UI, not source-code comprehension. | Described gentle electronic music but speculated about relaxation intent. |
| Aqua ? ?Roses Are Red? | Recognized performer and stage elements but falsely called a visibly color clip black-and-white. | Detected a female vocal and energetic electronic beat; lyrical theme/mood is unverified. |

A separate same-interval joint A/V probe was accepted with no cached tokens, but the response leaked a visible microphone into its audio-only description and asserted piano/synthesizer without independent evidence. It is not a passing cross-modal fusion result. Full per-call responses and metadata are in [`qwen25-omni-5x10s-no-cache-separated.json`](../../runtime/multimodal-realclips-20261024/qwen25-omni-5x10s-no-cache-separated.json); sampled-frame contact sheet: [`all-frames-1fps.jpg`](../../runtime/multimodal-realclips-20261024/probes/all-frames-1fps.jpg).

## Decision and limits

Qwen2.5-Omni is useful as a coarse scene and speech/music observer, but this five-clip pilot does not support replacing the modular sensory path. Concrete visual mistakes, speculative music attributes, cross-modal leakage, and English responses despite Russian prompts remain. The direct endpoint test does not use the companion capture/fusion/brain-bound path, is not a source-disjoint benchmark, does not measure CPU-only always-on cost, and does not compare Qwen3 Omni or Hikari with its projector. No model change is justified; keep provenance, freshness, ASR and music presence as independently inspectable lanes.

Next: run a frozen, parent-recording-disjoint set through the actual capture adapters and score visual facts, transcript WER, music/event tags, source/time alignment, abstention and false claims; then perform the post-fix timestamp canary and integrated 30?60-minute continuity gate. A micro-model is premature; first see whether deterministic source/time/TTL gates and existing specialized models leave a repeatable held-out error.
