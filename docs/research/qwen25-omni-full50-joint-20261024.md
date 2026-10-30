# Qwen2.5-Omni: one-pass 50-second A/V control (2026-10-24)

## Result

**Fail as a unified sensory describer.** One call over the full 50-second montage took 4.065 seconds and completed without truncation, but it missed the audio in every interval and made salient visual errors. This is a comparative GPU-served Omni probe, not evidence for a CPU-only production lane.

## Setup

- Existing Qwen2.5-Omni endpoint: `127.0.0.1:8995`, model alias `qwen25-omni-sensory`; endpoint reported vision/video/audio support and 12,288 context tokens.
- The endpoint was already running and idle. No service was restarted or reconfigured.
- One request received the 50-second audio track and ten timestamped, letterboxed 640x360 frames sampled every five seconds (0, 5, ..., 45).
- Prompt requested a time-aligned account of visible scenes, audible speech/music/events, readable text, and only grounded audio/video relationships.
- 4.065-second latency; 4,974 prompt tokens; 691 completion tokens; normal stop; no prompt-cache reuse. `cpu_only=false`.
- Raw frames and PCM were not persisted by the probe. The source montage and its manifest remain local test fixtures.

## Findings against the manifest

| Montage time | Reference case | Omni response | Assessment |
| --- | --- | --- | --- |
| 00-10 s | Russian live-action trailer | People in trees, then a woman in darkness | Broad scene impression, but speech/music omitted. |
| 10-20 s | Russian anime trailer | Red squares on white, then generic animated fighters | Misses the trailer/title context and key detail. |
| 20-30 s | Electric Noosphere RTS gameplay | Calls it “StarCraft II” twice | Unsupported game identification. |
| 30-40 s | Coding screen | Generic code screenshots | Does not establish developer-tool context or read the relevant UI/text. |
| 40-50 s | Aqua, “Roses Are Red” | Says “a pianist playing piano” at 40-45 s, then a woman in a red dress on stage | The contact sheet shows the singer in several shots and hands on a keyboard around 42-43 s. The keyboard claim is grounded in one brief shot, but the response overgeneralizes it across the interval and misses the rapid visual alternation/performance context; this is weak temporal aggregation, not an invented object. |

For **all ten five-second intervals**, the model answered that no audible speech was present. It also said there was no reliable audio/video relation for all ten intervals. The latter is a safe abstention in principle, but the blanket answer provides no useful synchronized account; the audio omission is directly contradicted by the source clips and the separate audio-lane probe.

The separate, repeated CPU audio probe found persistent YAMNet music scores in four of the five 10-second cases and nonempty GigaAM output on the Russian trailer and Aqua excerpt. That does not establish ASR correctness or style accuracy, but it independently supports the finding that the Omni response omitted music evidence. A 1-fps contact sheet also shows the Aqua video intercuts singer shots with a short keyboard close-up, so the “pianist” output is a temporal overgeneralization rather than a hallucinated object.

## Decision

Do not replace the separate visual and audio lanes with this single Omni call. Keep evaluating the lanes independently and fuse their time-bounded outputs with provenance and abstention. For music, report presence and measurable acoustic change first; emit style/mood only after a source-disjoint, human-labeled evaluation supports it. For video, evaluate scene changes, text/UI, and action details separately from object presence.

This probe alone does not show whether a different prompt, denser frame sampling, or a different runtime would improve Omni. It does show that this exact full-clip request is not adequate for the target: continuous conversation context, gameplay/video understanding, and grounded audio description.

## Artifacts

- Request and response: `runtime/multimodal-realclips-20261024/qwen25-omni-full50-joint-20261024-r2.json`
- Earlier 420-token response, truncated: `runtime/multimodal-realclips-20261024/qwen25-omni-full50-joint-20261024.json`
- Source/case manifest: `runtime/multimodal-realclips-20261024/manifest.json`
- Manual 1-fps contact sheet used to adjudicate the brief keyboard shot: `runtime/multimodal-realclips-20261024/contact-sheet-1fps.jpg`
- Independent audio replay: `docs/research/realclip-audio-five-case-recheck-20261024.md`
- Reproducer: `scripts/probe_full_montage_omni.py`
