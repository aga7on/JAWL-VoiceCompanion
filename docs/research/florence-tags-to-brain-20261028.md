# Florence tag stream → brain narrative test

Date: 2026-10-28. This follow-up tests the unresolved architecture question: can Florence-2 captions, without images or other sensor channels, support a useful chronological account from the existing brain or a small text model?

## Protocol

- Source: the local, authorized 50-second five-clip montage from `runtime/multimodal-realclips-20261024/real_sensory_5x10s.mp4`; 50 source frames sampled at 1 fps and 640×360. Reference labels are in `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`.
- Florence-2-base-ft Q8 ONNX ran on CPU and generated `<CAPTION>` for all 50 frames. Its saved result is `runtime/florence-node/tag-sequence-bench-20261028/florence-tags.json`.
- The brain received text captions only: no image, audio, OCR, or UIA. The matched Florence-vs-Qwen comparison used the same 11 frame IDs in the same five known 10-second groups. Source responses and timings are in `brain-tag-source-comparison*.json`.
- Models: current Hikari/Ternary Bonsai Q2 at 8997 on GPU1, Qwen3.5-0.8B Q4 on CPU (4 threads), and LFM2.5-VL-450M Q4 on CPU (4 threads). All were temporary loopback servers; the application profile was untouched.

## Florence tagger throughput and quality

The per-frame `model.generate()` call measured p50 **714 ms**, p95 **775 ms**, max **975 ms**; model load was 1.15 s. RSS rose from 463 MB after load to 1.54 GB during the run and settled to 1.48 GB idle. This is promising throughput for a coarse 1-fps sensor on this host, but it does not establish a long-running always-on memory bound.

The captions often identify broad categories: the RTS segment is repeatedly called a video game/battle; the coding segment is repeatedly recognized as a screen or software page. Some individual details are useful: at montage second 4, Florence says a man carries a woman on his shoulders, matching the visual ledger's support/carry pose.

The same stream has conspicuous errors. In anime it calls a character a man with a tie, a woman with a tablet, and even a man riding another man; these do not describe the corresponding ledger frames. In the music-video segment it alternates among a woman in a red dress, a person at a piano, a man in a tie, and a woman in a suit; the last ledger frame shows a woman close to a microphone. It also attempts confident text reading where no verified transcription exists. Therefore these captions cannot be treated as atomic facts or as a reliable detailed scene description.

### Timing caveat in the current benchmark script

`runtime/florence-node/content-bench.mjs` times an extra `encode_image()` probe, then separately times `model.generate()`. The saved `total_ms` is the duration of the `generate()` call; it does **not** include the earlier diagnostic encode. Its derived `generation_ms = total_ms - vision_ms` is invalid (five frames have negative values), because it subtracts a separately timed encode from the generate-call duration. The 714/775/975 ms figures above use only the recorded generate-call durations and should not be described as independently measured vision/generation stages. Loading/processor time is also excluded.

## Can Hikari reconstruct the timeline from Florence tags?

Using all 50 captions, Hikari produced a five-line coarse montage summary in **1.99 s** (1,075 prompt tokens, 91 output tokens, normal stop). It ordered the broad trailer/anime/game/coding/music-video sections and compressed the input quickly. It also introduced an unsupported piano claim in the music segment and did not recover a coherent plot progression inside the trailer or anime. A longer prompt returned only a partial answer and hit its output cap at 2.30 s.

Repeating the full-stream test with the 50 captions explicitly grouped beneath the five known clip boundaries reduced Hikari latency to **1.65 s** (1,135 prompt tokens, 72 output tokens, normal stop) and made it obey the five-line format. It still selected Florence's one-off false anime claim that a man is riding another man on his back, and reduced the live-action carry pose to “hugging.” This shows that grouping fixes output shape, but does not repair incorrect source observations or recover the action accurately.

On the matched 11-frame comparison, Hikari received the same timestamps and clip boundaries from Florence or Qwen:

| Observation source | Brain latency | Output behavior | Grounding result |
|---|---:|---|---|
| Florence tags → Hikari | 1.59 s | Seven points despite the exact five-line contract | Misclassified a live-action carry scene as animation; repeated Florence's false digital-art/tablet/tie details; omitted the microphone. |
| Qwen captions → Hikari | 1.37 s | Correct five-section sequence | More event detail, but repeated Qwen's unsupported “plane news” claim and inferred singing from a visual-only input. |

The brain can compress noisy tags into a rough sequence, but did not reliably reject isolated bad tags. Qwen's richer captions produced a more useful timeline on these selected frames; they also propagated their own hallucinations. This is a source-quality bottleneck, not a prompt-only issue.

### Timestamped event ledger with an explicit uncertainty cue

I built a disposable, deterministic ledger probe from the same 50 Florence captions. It keeps all captions and timestamps, and adds the nearest adjacent caption's RapidFuzz `token_set_ratio` inside the same 10-second clip. A value at or above 0.75 is labeled **repeated wording only**; the prompt explicitly says this is not factual confidence. This metadata does not merge or delete observations.

Hikari's concise ledger answer completed in **2.55 s** (1,854 prompt tokens, 118 output tokens, normal stop). It produced one line per clip and marked the distinctive one-frame details as “possible”: shoulder-carry at 4 s, chained man at 11 s, robots at 24 s, phone/task text at 35 s, and piano at 42 s. Against the visual ledger:

- The shoulder-carry claim at 4 s is supported, though Hikari hedged it.
- The “chained man” at 11 s is false; the reference shows an animated person lying horizontally and does not establish chains. Hikari did mark it as possible.
- The robot identification and phone/text reading are unsupported at the reference's resolution; both were hedged.
- Hands over keyboard keys at 42 s are visible, but the frame alone cannot establish the sound source; the answer cautiously hedged piano.
- Florence still failed to supply the microphone visible at 49 s, so the answer could not describe the performance accurately.

This is a useful **coarse, uncertainty-marked five-clip digest**, not a detailed plot reconstruction. Asking for 2–3 states per clip yielded a longer answer that reached the output cap at 160 tokens and 2.97 s, with the last clip cut off. Detail therefore still trades against the three-second limit. The metadata cue helps the brain signal uncertainty, but cannot turn a false caption into a correct event.

### Small-model GPU follow-up

Qwen3.5-0.8B Q4 on GPU1 processed the same 50-tag ledger in 0.71 s at a 160-token output cap, but copied the first captions frame by frame and truncated before the later clips. A simpler five-phrase prompt took 0.53 s and behaved the same way. The model is fast enough; its long-context synthesis on this input is not.

## Small text brains on the same task

| Brain | Input | CPU latency | Result |
|---|---|---:|---|
| Qwen3.5-0.8B Q4, 4 threads | All 50 Florence captions | 2.64 s | Hit the 96-token cap after listing individual early frames; no complete five-part synopsis. |
| Qwen3.5-0.8B Q4, 4 threads | All 50 Florence captions, explicitly grouped into the five clip spans | 2.76 s | Same behavior: lists individual frames and truncates before the requested sequence summary. |
| Qwen3.5-0.8B Q4, 4 threads | Matched 11 Florence captions | 1.76 s | Listed individual timestamps and hit the cap; did not group them into the requested five scenes. |
| Qwen3.5-0.8B Q4, 4 threads | Matched 11 Qwen captions | 1.83 s | Produced five chronological lines, but promoted unsupported source claims (including the plane-news interpretation and “user uploads” inference). |
| LFM2.5-VL-450M Q4, 4 threads | Matched 11 Florence captions | 0.64 s | Broad labels only; answer hit the 96-token cap before completing the last section. |
| LFM2.5-VL-450M Q4, 4 threads | Matched 11 Qwen captions | 0.75 s | Began copying a long source caption verbatim and hit the token cap before summarizing the sequence. |

All brain latencies are single requests per input source, measured end-to-end over local HTTP. They are useful candidate measurements, not repeated-run p95s.

## Decision

- **Florence-2 cannot replace the current VLM describer for grounded narrative.** It is fast enough to act as a coarse CPU tag source, but the full real-clip trace contains category/detail mistakes that a downstream brain amplified instead of filtering.
- **The current Hikari brain can produce a quick coarse scene-order summary from 50 Florence captions**, but the output is not a sufficiently accurate plot account. It is not evidence that Florence tags alone support the desired detailed, always-available sensory context.
- **Qwen3.5-0.8B is the strongest cheap text-only brain tested here**, at about 1.8 s for the short matched sequence on CPU, but its summary is only trustworthy when incoming observations are already reasonably good; it inherits hallucinations and did not summarize the full Florence stream within the tested 96-token / 3-second measurement budget. A larger output budget was not tested in this probe.
- **LFM450 wins on speed (0.6–0.75 s) but fails the narrative/detail contract.**
- No tested pipeline yet meets all requirements at once: accurate detailed event progression and robust uncertainty from Florence-only observations. The 3-second limit was a budget in this benchmark, not a universal rejection threshold; longer answers or processing could change the tradeoff and remain untested. Keep the objective active. Next useful discriminator: improve source-tag uncertainty/temporal deduplication, then rerun the same fixed ledger with the brain asked for a compact event ledger and score supported event recall, order, and false claims separately.

## Reproduction artifacts

- Florence frames and raw output: `runtime/florence-node/tag-sequence-bench-20261028/`
- Matched brain-source comparison: `runtime/florence-node/tag-sequence-bench-20261028/brain-tag-source-comparison.json`
- Small-brain comparisons: `runtime/florence-node/tag-sequence-bench-20261028/brain-tag-source-comparison-qwen35-0.8b.json`, `...-lfm450.json`
- Full Florence → Hikari test: `runtime/florence-node/tag-sequence-bench-20261028/brain-florence-tags-only-compact.json`
- Grouped 50-frame Florence → Hikari test: `runtime/florence-node/tag-sequence-bench-20261028/brain-florence-tags-only-grouped-local-bonsai2.json`
- Hikari with timestamped lexical-repeat ledger: `runtime/florence-node/tag-sequence-bench-20261028/florence-ledger-brain-local-bonsai2-max144.json`
- Detailed Hikari timeline attempt, output-cap truncation: `runtime/florence-node/tag-sequence-bench-20261028/florence-ledger-brain-local-bonsai2-max160.json`
- Qwen0.8B GPU full-ledger and short-story probes: `runtime/florence-node/tag-sequence-bench-20261028/florence-ledger-brain-qwen35-0.8b-max160.json`, `runtime/florence-node/tag-sequence-bench-20261028/short-story-qwen35-0.8b-max96.json`
- Full Florence → Qwen0.8B CPU, grouped input variant: `runtime/florence-node/tag-sequence-bench-20261028/brain-florence-tags-only-grouped-qwen35-0.8b.json`
- Earlier ungrouped Florence → Qwen0.8B run: `runtime/florence-node/tag-sequence-bench-20261028/brain-florence-tags-only-compact-qwen35-0.8b.json`

All temporary inference servers were stopped; ports 8996 and 8997 were checked free. GPU1 memory returned to its pre-run 467 MiB usage. No daily profile or TTS settings were changed.
