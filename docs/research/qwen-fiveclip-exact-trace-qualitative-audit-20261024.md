# Qwen five-clip exact-trace qualitative audit

Date: 2026-10-24
Scope: read-only comparison of the exact Qwen visual replay with the 50-frame manual visual ledger and the clip manifest. No model or service was run for this audit.

## Method and limits

The replay's `source_frame` maps directly to the montage index (`frame-001.jpg` = montage second 0, `frame-050.jpg` = second 49). The manifest assigns seconds 0–9 to the Russian trailer, 10–19 to anime, 20–29 to gameplay, 30–39 to coding UI, and 40–49 to the Aqua video. For each caption, I matched `source_frame` and `clip_local_t_s` to the ledger row with the same montage second, then interpreted the clip-local second by subtracting that clip's manifest start.

This is a qualitative score of sampled frames, not full video accuracy: the ledger marks visible pixels at 1 fps and deliberately leaves audio, motion between samples, identity, and uncertain text unlabeled. The replay is a fixture-frame replay through `QwenVisualSensor → QwenEventDescriber → PerceptionFusion`, not physical screen capture. “Supported” means the caption's directly visible claim agrees with the ledger; “uncertain” means the ledger cannot verify it; “contradiction” means a concrete claim conflicts with the ledger; “omission” records a salient ledger fact absent from the caption.

`describer.count=10` records completed inference work, not the number of HTTP/transport attempts. `transport_trace` has 13 entries because three source frames have both a 64-token truncated attempt and a 128-token fallback. Those pairs count as one source-frame result each. They are not extra coverage.

## Coverage and runtime evidence

| Clip | Submitted frames accepted by queue | Unique source frames with completed captions | Caption coverage of 10 ledger frames | Completed-caption latency, p50/p95 |
|---|---:|---:|---:|---:|
| Russian live-action trailer | 8 | 3 | 30% | 3.859 / 4.641 s |
| Anime | 10 | 2 | 20% | 4.305 / 4.531 s |
| Gameplay | 6 | 1 | 10% | 4.109 / 4.109 s |
| Coding UI | 9 | 2 | 20% | 4.368 / 4.469 s |
| Aqua music video | 10 | 2 | 20% | 3.906 / 4.031 s |
| **Total** | **43** | **10** | **20%** | **4.094 / 4.641 s** |

The sensor records 539 adapter calls over a 50-second source interval, 43 submits, 33 describer queue drops (older pending work replaced by newer frames), 5 scene-change drops, 3 stale-result drops, and 0 capture errors. The accepted submission counts above are the queue's accepted 1-fps fixture frames; they do not mean every frame produced a caption. Only 10 unique source frames completed inference. The sensor's last delivered caption had age 4.828 s against a 5 s caption TTL; at the end of the drain, `latest_age_ms` was about 10.14 s and `caption_fresh=false`. This is evidence of expected short-lived freshness under a queue that cannot keep up with 1 fps, not evidence of a continuously fresh 1-fps description stream.

## Caption-by-caption comparison

| Exact source frame → ledger row | Caption assessment | Ledger-based result |
|---|---|---|
| `frame-001.jpg`, montage 0 → `01_ru_trailer@00` | Supported: pale sky/clouds. Contradiction/unsupported specificity: says Russian overlay indicates a film and June 19th, while the ledger marks the small title/age graphics unreadable. | Main scene is right; text claim is not grounded by the reference. This is a clear screen-text hallucination. |
| `frame-004.jpg`, montage 3 → `01_ru_trailer@03` | Supported: man, woman, trees, overlay are present. Uncertain: “embrace” is stronger than ledger's cautious shoulder/upper-body hold. Contradiction/unsupported specificity: claims Russian text overlay, but the ledger cannot read it. | Broad entities are right; action direction and overlay content should have been hedged. |
| `frame-007.jpg`, montage 6 → `01_ru_trailer@06` | Supported: woman in profile, dark background, title/age overlay. Uncertain: “young girl,” expression/skin texture, cinema/quiet-room setting, and film title/date are not established. | Good coarse frame description; narrative/age/setting embellishments are unsupported. First attempt truncated at 64; the 128-token retry finished. |
| `frame-017.jpg`, montage 16 → `02_anime@06` | Supported: dark red title card and visible Cyrillic word. Text correctness uncertain: replay emits mojibake-like Cyrillic (`РќРђ…`), while the ledger stores a similarly garbled-looking excerpt; this pair cannot establish faithful OCR against the rendered source. | Do not score the phrase as correct from the JSON strings alone. The ledger needs a verified Unicode transcription or image-level check for an OCR claim. |
| `frame-020.jpg`, montage 19 → `02_anime@09` | Supported: school hallway and multiple animated students. Uncertain: lab coats, notebook, exact arrangement and fluorescent lighting are more specific than ledger evidence. | Main scene category is right. The 64-token response truncated and the 128-token retry completed. |
| `frame-030.jpg`, montage 29 → `03_gameplay@09` | Supported: futuristic-looking battlefield/structures is broadly consistent with gameplay context. Contradiction/unsupported specificity: “hostile alien-like creatures” is not supported by the ledger's conservative “units/structures”; it does not identify the units as aliens or hostile. Omission: HUD panels and minimap-like circular panel. | Clear semantic overreach plus omission of the distinguishing RTS interface context. This is the clearest gameplay error. |
| `frame-034.jpg`, montage 33 → `04_coding_ui@03` | Supported: desktop app, model/chat interface, pointer, dark UI. Uncertain: “Alibaba cloud services” and names are not verified; ledger says model list is unreadable and no selected model name is reliable. | Correct broad interface category; unsupported naming is a text hallucination risk. |
| `frame-038.jpg`, montage 37 → `04_coding_ui@07` | Supported: dark UI with white text, software/development context. Uncertain: quoted English fragments “development tasks step-by-step,” “terminal commands,” and “MCP” are not independently transcribed in the ledger. Omission: coding assistant/chat and sidebar. | General category is right; exact OCR claims need separate verification. The 64-token response truncated and the 128-token retry completed. |
| `frame-047.jpg`, montage 46 → `05_aqua_song@06` | Supported: woman, red/dark clothing, upper-arm tattoo. Uncertain: two buns, red top, chest-up crop and gaze direction exceed the ledger's conservative labels. | Mostly grounded visual description; no audio or identity claim can be scored here. |
| `frame-050.jpg`, montage 49 → `05_aqua_song@09` | Supported: woman's face and microphone. Uncertain: “singing” is an audio/action inference not established by a still, and “vintage” is not labeled in the ledger. Omission: no mention that the ledger only confirms proximity to a microphone. | Plausible, but the caption overstates what a still proves. |

## Findings

1. **Coverage, not raw caption fluency, is the central limitation in this replay.** Ten completed captions cover 10 of 50 reference seconds, with only one caption in gameplay and 20% total source-frame coverage. Queue replacement is doing its job of preferring recent frames, but at this measured latency the system is not generating a description for every 1-fps sample.
2. **The model can recognize broad scene categories across diverse clips.** It identifies a trailer/profile shot, anime school hallway, coding interface, and performance close-up. Those high-level descriptions are useful as hypotheses for a conversational brain.
3. **Text and fine detail remain unsafe as facts without verification.** The trailer's unreadable overlay is turned into a specific date claim; the coding caption invents a service attribution where the ledger marks text unreadable; gameplay adds alien/hostile semantics and misses HUD/minimap cues. Exact text accuracy cannot be quantified for anime from the current ledger because its saved excerpt is itself mojibake-like.
4. **Freshness is transient.** Completed work takes about 3.6–4.6 seconds per caption and the final observation is already beyond the 5-second freshness TTL after drain. The capture/replay path stayed error-free, but the report does not establish continuous present-tense availability.

## Recommended next discriminator

Use the existing 50-frame ledger to evaluate a fixed subset with the current one-pending/latest-frame policy, and report (a) scene-category accuracy, (b) unsupported entity/action claims, (c) text claims scored only where the reference has verified readable text, (d) omission of salient UI/HUD elements, and (e) age at the moment the brain would consume the caption. Keep fallback attempts grouped by source frame. A useful acceptance target is not “all 50 captions”; it is a fresh, correct coarse scene summary at each hard-cut boundary and after a salient in-scene change, with no confident invented text/entities. The present trace is a baseline for that test, not a pass: it has no completed caption at several boundaries, including the 40-second transition into Aqua.

## Sources

- Exact replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-20261024-r2/qwen-visual-replay.json`
- Manual ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip mapping and evaluation intent: `runtime/multimodal-realclips-20261024/manifest.json`
