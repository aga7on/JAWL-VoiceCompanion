# Qwen matched-resolution A/B audit

Date: 2026-10-24
Artifact: `runtime/instances/goal-trailer-visual-replay-20261024/matched-resolution-ab-20261024-r4/results.json`
Reference: the 50-frame visual ledger and five-clip manifest.

## Method

The artifact contains both 1280×720 and 480×270 results for the same nine source frames (001, 007, 017, 020, 030, 034, 038, 047, 050), same recorded default prompt, CPU-only execution, and no truncation in the final captions. Where `budgets` lists `[64,128]`, I treat that as one caption for that source frame using the final 128-token result—not two observations. The test metadata records the prompt and CPU-only mode; reasoning-off is part of the run setup, not an independently measured outcome here.

The ledger is intentionally conservative about unreadable text and still-frame actions. I use “grounded” for visually supported claims, “uncertain” for claims the frame cannot resolve, and “regression” for claims visibly wrong or salient facts newly omitted.

## Latency

| Resolution | Matched frames | Caption latency p50 | p95 |
|---|---:|---:|---:|
| 1280×720 | 9/9 | 3.911 s | 8.490 s |
| 480×270 | 9/9 | 0.799 s | 3.372 s |

On this small fixed set, 480×270 is about 4.9× faster at p50 and 2.5× at p95. Two 480 results and one full-resolution result used 64→128 fallback; each is counted once. The fallback delays explain much of each resolution's p95.

## Matched-frame quality

| Frame / reference | A/B result |
|---|---|
| `frame-001` — pale sky, tiny unreadable title/age graphics | Both captions hallucinate birds in an otherwise empty sky. Full resolution says a flock; 480 says a few birds and additionally claims Russian and English overlays. The text is not reliably readable in the ledger. **No safe win; 480 adds an unsupported text claim.** |
| `frame-007` — woman in profile, dark background, unreadable title/age overlay | Full resolution gives a restrained profile description and omits the visible `18+` marker. 480 identifies `18+`, a useful grounded gain, but invents a calm/contemplative mood and returns mojibake for the small title/date. **Mixed: improved marker detection, still unsafe OCR and affect inference.** |
| `frame-017` — red anime title card with readable Russian word | Both return the same mojibake-like Cyrillic instead of the displayed word. Background and title-card detection are correct; OCR fails at both sizes. |
| `frame-020` — group of animated students in a school hallway | Both identify the hallway/group/uniform context. They disagree on individual poses and objects (tablet versus notebook; conversation versus embrace). These fine details are not established by the ledger, so neither shows a defensible quality advantage. |
| `frame-030` — RTS battlefield, units/structures, HUD and minimap | Both add unsupported alien-enemy interpretation. 480 additionally narrates a cannon firing and explosion from a still image. The ledger cannot establish that event and both omit HUD/minimap. **480 is a clear action-grounding regression for gameplay.** |
| `frame-034` — dark model-list/chat interface and cursor | Both recognize the interface and Alibaba labels. Full resolution captures specific visible service/model names; 480 only says “a service like Alibaba.” **Full resolution has better text/detail fidelity.** |
| `frame-038` — coding assistant text pane/sidebar | Full resolution stays with the visible dark screen and development/MCP text. 480 says “a person is speaking,” but no person appears in the frame, and converts displayed text into an action (“using terminal commands”). **Clear object/action hallucination at 480.** |
| `frame-047` — woman, red/black clothing, upper-arm tattoo | Both identify the woman and red clothing; full resolution also catches the visible tattoo and ponytail. 480 omits the salient tattoo. **Full-resolution detail gain.** |
| `frame-050` — woman's face and microphone | Both identify the face/microphone and call it singing into a vintage microphone. The ledger verifies only proximity to a microphone; singing/vintage are uncertain from a still. The brighter-background description at 480 is compatible with the frame. No meaningful quality win. |

## Recommendation

480×270 is a strong **coarse, always-on scene-presence tier**: it cuts median latency substantially and recognizes broad settings. It is **not an acceptable sole default for fact-grade gameplay or screen-text understanding**: this paired test has a fabricated firing event and a person hallucination at 480, while full resolution extracts more interface detail and the tattoo. Keep the low-resolution tier for cadence and broad scene context; escalate to a high-resolution ROI and/or OCR when the agent needs readable UI text, game state, or a specific action. Continue to mark temporal events and affect as uncertain unless confirmed over time or through another sensor.

This conclusion is limited to nine frames and one prompt. It supports an operating-point decision, not a general claim that resolution alone causes each quality difference.

## Sources

- Paired A/B: `runtime/instances/goal-trailer-visual-replay-20261024/matched-resolution-ab-20261024-r4/results.json`
- Manual visual reference: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip/time mapping: `runtime/multimodal-realclips-20261024/manifest.json`
