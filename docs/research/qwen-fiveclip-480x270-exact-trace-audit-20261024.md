# Qwen 480×270 five-clip exact-trace audit

Date: 2026-10-24
Scope: read-only audit of the 480×270 replay against the manual 50-frame visual ledger and clip manifest, plus same-source-frame comparisons with full-resolution run r2. No model or service was run for this audit.

## Matching and scoring rules

`frame-001.jpg` maps to montage second 0; frame number minus one is the montage time. The manifest assigns montage seconds 0–9 / 10–19 / 20–29 / 30–39 / 40–49 to trailer / anime / gameplay / coding UI / Aqua. Each caption was matched to the ledger row with that montage time. For output scoring, multiple transport entries for the same `source_frame` were collapsed to the highest `max_tokens` result (the final 128-token caption after a truncated 64-token response). A fallback retry is one covered source frame, not two.

The ledger labels sampled visible facts only; it does not verify audio, motion between samples, or identity. “Contradiction” below is reserved for visibly incompatible claims; unsupported action, intent, or text is marked uncertain/overclaim. R3 is fixture replay through the production sensor/describer/fusion path, not physical screen capture.

## Coverage, queue, and freshness

| Clip | Accepted submitted frames | Unique completed captions | Caption coverage | Delivered to fusion history |
|---|---:|---:|---:|---:|
| Russian live-action trailer | 7 | 5 | 50% | 3 |
| Anime | 10 | 8 | 80% | 1 |
| Gameplay | 6 | 6 | 60% | 6 |
| Coding UI | 9 | 8 | 80% | 6 |
| Aqua music video | 9 | 9 | 90% | 2 |
| **Total** | **41** | **36** | **72%** | **18** |

All 41 recorded submissions were accepted by the queue. The describer completed 36 unique-frame inferences, had 5 queue replacements, 0 inference errors, and 42 `transport_trace` records: 36 final captions plus 6 extra 64-token truncated attempts paired with 128-token fallbacks. The sensor separately records 18 results discarded at scene change, 0 stale-result drops, 0 capture errors, and 18 delivered observations. Completion, delivery, and fusion-history presence are distinct counts.

Final unique-frame inference latency was p50 0.821 s / p95 1.640 s. Sensor source-to-completion age was p50 0.843 s / p95 2.968 s. After drain, the last caption age was about 5.88 s against a 5 s TTL (`caption_fresh=false`). R3 therefore materially improves throughput and typical freshness over R2, but does not guarantee a fresh caption at the end of a drain or uninterrupted presence in the current-scene channel.

## Comparison with full-resolution r2

The r2 and r3 source-frame sets differ. R2 has completed captions for 10 unique frames; r3 has 36. Their exact matched set is nine frames: 001, 007, 017, 020, 030, 034, 038, 047, 050. R2 frame-004 has no R3 counterpart. Any resolution-quality conclusion is limited to these nine exact matches; the broader coverage/latency difference also reflects different queue schedules and frame sets.

| Matched source frame / ledger time | R3 (480×270) versus R2 (full resolution) | Assessment against ledger / visible contact sheet |
|---|---|---|
| `frame-001.jpg` / trailer t=0 | R2: sky/clouds, several birds, plus a specific Russian film/date text claim. R3: one bird in a blue sky; omits the text claim. | The frame is essentially pale sky with tiny age/title graphics; no bird is visible. Both resolutions hallucinate birds; R3 reduces the quantity and avoids R2's fabricated date, but still makes a false object claim and omits the visible graphic. **Mixed: text calibration gain, object error remains.** |
| `frame-007.jpg` / trailer t=6 | Both describe a woman in profile against a dark background. R3 adds a visible “18+” and says title/date text is present; R2 only says title/release overlay. Both add mood/setting language. | The contact sheet visibly shows “18+” at lower left; R3's age-rating detail is a grounded gain. The upper overlay remains too small to verify the claimed title/date. “Serious/contemplative,” “at home,” or “cinema” are not visual facts. |
| `frame-017.jpg` / anime t=6 | Both detect the red title card and emit the same mojibake-like Cyrillic string. | The rendered card shows readable Russian “НАПРАВЛЯЕТСЯ”; both transcripts fail to preserve the displayed text. This is an OCR failure, not a resolution gain. The ledger excerpt also contains garbled text, so its string alone is not a valid OCR gold label. |
| `frame-020.jpg` / anime t=9 | Both identify a school hallway and group of students. R2 specifies pairs, lab coats, notebook and lighting; R3 summarizes group/uniforms and adds notebooks or phones. | Similar scene-level result. Fine object/action claims are not consistently supported by the conservative ledger; no clear resolution advantage. |
| `frame-030.jpg` / gameplay t=9 | R2 calls it a futuristic base with hostile alien-like creatures. R3 calls a large cannon firing a projectile with an explosion. | The sampled still visibly contains a top-down battlefield, units/structures and HUD. “Hostile” is not established by the still. The R3 firing/explosion wording asserts a temporal event from a single image and is not supported by the ledger; treat as an action overclaim. Neither caption mentions the HUD/minimap context. **R3 trades speculative creature semantics for speculative action; no reliable gain.** |
| `frame-034.jpg` / coding t=3 | R2 identifies a dark chat/model-list interface and Alibaba-associated labels; R3 gives a generic cursor/chat/sidebar/profile description. | “Alibaba” labels are visibly present in the contact sheet, while the ledger conservatively declines exact transcription. R2 is more useful and appears correct here; R3 loses salient text/interface specificity. |
| `frame-038.jpg` / coding t=7 | Both recognize a dark software-development text UI. R2 gives a short generic summary. R3 captures more of the visible workflow/MCP text and says the display mentions editing files and exploring projects. | The visible text does include those workflow phrases. R3's richer extraction is a grounded detail gain at reduced resolution, though the “active use of terminal commands” phrasing still overstates what a static frame proves. |
| `frame-047.jpg` / Aqua t=6 | R2 describes dark hair in two buns, red top, tattoo and close crop. R3 describes tied-back dark hair and red top but omits tattoo. | Ledger confirms woman, red/black clothing and upper-arm tattoo. R3 is broadly right but loses a salient visible detail that R2 captured. **Detail regression.** |
| `frame-050.jpg` / Aqua t=9 | Both say the woman is singing into a vintage microphone. R3 additionally mentions overexposed background. | Face and microphone are visible. “Singing” and “vintage” cannot be established from the still alone; the background is bright/overexposed. No material quality change. |

## R3-only evidence from additional frames

These captions improve content breadth but are not matched to R2 and therefore cannot establish a resolution effect:

- Anime `frame-012` recognizes a lab-coated figure and a prone/chain-bound figure; `frame-014` describes the character and red energy; `frame-018` describes a punch. The last is an action inference from a still and should be treated cautiously.
- Gameplay `frame-021`, `024`, `025`, `027`, and `028` provide concrete battlefield object descriptions. Their broad game context is useful, but exact unit identity and events (e.g. firing, aiming, hostile/alien status) need temporal or game-state evidence before being stated as fact.
- Coding `frame-031`, `035`, `036`, and `040` extract model labels, a “snake game in python” task, and settings text. These appear to add useful readable interface context; exact OCR still needs scoring against verified text, since the manual ledger deliberately marked many small UI strings unreadable.
- Aqua `frame-041`–`044` separate the stage/microphone shots from the keyboard close-up; `frame-049` identifies a bald man in light clothing. These add coverage of within-clip shot changes. A still cannot establish that the keyboard is producing soundtrack audio.

## Overall findings

1. **480×270 is a strong throughput operating point in this fixture replay.** Completed unique-frame coverage rises from 10/50 (20%) in R2 to 36/50 (72%) in R3; inference latency and source-to-completion age fall substantially. There are no capture or inference errors. The accepted frame sets differ, so this is an end-to-end replay comparison, not a controlled pixel-resolution experiment.
2. **Lower resolution does not remove unsupported semantic claims.** R3 still invents a bird in the empty opening sky, overstates action in the gameplay still, and cannot reliably transcribe the anime title card. The matched comparisons also show losses in visible tattoo detail and coding UI labels.
3. **Coarse scene context is broadly useful; exact action/text requires a verified channel.** The model recognizes school, gameplay, coding UI, and performance contexts across the clip set. For factual use, keep screen text with OCR verification and temporal actions as uncertain until confirmed by adjacent frames or a video-level evaluator.
4. **Queue behavior is materially better but the current-scene freshness policy still has gaps.** 36 inferences produced 18 deliveries, with 18 invalidated at scene change. The final caption expired after drain. The immediate acceptance target should measure fresh correct captions after each manifest boundary and salient intra-clip change, rather than only counting inference throughput.

## Next discriminating test

Use a matched-source-frame replay where R2 and R3 receive the same immutable 50-frame sequence and the evaluation scores only identical source frames. Keep the existing one-latest-pending policy, but separately report inference, scene-change discard, fusion delivery, and age-at-consumption. Score: scene category; visible entities; action claims; verified text only; salient omissions; and unsupported specifics. The current artifacts already provide a useful operational comparison, but queue selection confounds any claim that 480×270 alone caused the quality and latency differences.

## Sources

- R3 replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-480x270-20261024-r3/qwen-visual-replay.json`
- R2 full-resolution replay: `runtime/instances/goal-trailer-visual-replay-20261024/fiveclip-visual-1fps-20261024-r2/qwen-visual-replay.json`
- Visual ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip mapping: `runtime/multimodal-realclips-20261024/manifest.json`
