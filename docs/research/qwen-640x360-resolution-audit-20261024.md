# Qwen 640×360 matched-frame resolution audit

Date: 2026-10-24
Scope: qualitative read-only comparison of the 640×360 run with the matched 480×270 and 1280×720 results, against the manual ledger and manifest. The nine frames are identical in all three artifacts: 001, 007, 017, 020, 030, 034, 038, 047, 050. Each 64→128 fallback is one final caption for its source frame.

## Latency and fallback

The run-reported latency is **p50 1.18 s / p95 1.62 s**, with one fallback. The fallback is at `frame-020`; the result artifact gives 3.627 s for that final response. The other eight per-frame latency values range from 1.043 to 1.623 s. These measurements are per caption/frame, not extra samples for the fallback.

| Size | Run-reported p50/p95 | Paired-set quality profile |
|---|---|---|
| 480×270 | 0.799 / 3.372 s | Fastest; broad scene context, but misses UI detail and has unsupported person/action claims. |
| 640×360 | **1.18 / 1.62 s** | Still fast, improves readable UI detail; retains a significant coding-frame hallucination and unsupported gameplay action. |
| 1280×720 | 3.911 / 8.490 s | Slowest; best detail on coding labels and tattoo, but still makes unsupported gameplay/sky claims. |

The 640 p95 excludes the fallback outlier in the run-reported statistic; the raw result records its 3.627 s completion. This matters when sizing tail latency.

## 640 caption checks against the ledger

| Frame / time | Supported | Unsupported, uncertain, or omitted |
|---|---|---|
| `frame-001` / trailer t=0 | Pale blue sky and graphics are present. | Two birds are claimed but none is visible in the reference; Russian overlay is not reliably readable. This repeats the bird hallucination from both 480 and full resolution. |
| `frame-007` / trailer t=6 | Woman in profile, dark background, visible title/age graphics. | “Introspection or contemplation” is an inferred mood. The caption omits the visible 18+ marker captured by 480; title/date are not read. |
| `frame-017` / anime t=16 | Red smoky title card and metallic letters. | Text is the same garbled Cyrillic string as both other sizes, rather than the rendered word. OCR still fails. |
| `frame-020` / anime t=19 | School hallway and group of uniformed students. | Tablet claims and exact person interactions (“surprised”, “concerned”, “hugging”) exceed the still-frame reference. Similar fine-detail uncertainty appears in both 480 and full. |
| `frame-030` / gameplay t=29 | Battlefield/cannon and ground units are plausible visible objects. | “Firing” and “moves across the ground” assert motion from one still; not established by the ledger. HUD/minimap are omitted. Full resolution instead adds alien-combat semantics; 480 says firing/explosion. None is safe for event facts. |
| `frame-034` / coding t=33 | Cursor, chat/model list, Alibaba association; model names are visible. | This is the strongest 640 result: it preserves specific model names like full resolution and is more informative than 480's generic “service like Alibaba.” The ledger alone declines exact OCR, so treat names as plausible pending OCR verification. |
| `frame-038` / coding t=37 | Text concerns development tasks and terminal commands. | **Clear hallucination:** “a person is standing” although the frame is a text pane with no person. It turns displayed text into an event. Both 480 and 640 make this error; full resolution avoids it. |
| `frame-047` / Aqua t=46 | Woman, ponytail, red top, tattoo, bright background. | Broadly matches the ledger; mood/action is not asserted. This preserves the detail lost at 480 and resembles full resolution. |
| `frame-050` / Aqua t=49 | Woman's face and microphone; bright overexposure. | “Singing” and “vintage” remain uncertain from a still. Same limitation at all sizes. |

## Practical recommendation

**640×360 is the best general always-on operating point among these three for coarse visual context.** It is close to 480's latency range while retaining substantially more useful interface text on the matched coding frame, and it preserves the tattoo detail at frame 047. It is not a fact-grade gameplay/action or UI-text solution: the gaming caption narrates motion without temporal proof, and the coding caption invents a person. Use 640 for ongoing scene context; invoke verified OCR or a larger targeted crop when text or exact game state matters. Keep temporal actions, emotion, and uncertain small text hedged.

If strict CPU budget dominates, 480 remains a valid coarser fallback. Full resolution is best reserved for targeted escalation because its latency is much higher and it does not eliminate hallucinations. This recommendation is based on nine fixed frames, one prompt, and a single run; it is an operating-point choice, not a general quality guarantee.

## Sources

- 640 run: `runtime/instances/goal-trailer-visual-replay-20261024/matched-resolution-640-20261024-r5/results.json`
- Paired 480/full run: `runtime/instances/goal-trailer-visual-replay-20261024/matched-resolution-ab-20261024-r4/results.json`
- Manual visual ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
- Clip mapping: `runtime/multimodal-realclips-20261024/manifest.json`
