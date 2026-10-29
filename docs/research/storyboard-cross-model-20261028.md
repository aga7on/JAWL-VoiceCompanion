# Cross-model storyline probe: sparse and dense frames

Date: 2026-10-28

## Objective

Compare fast candidate VLMs on the same real 50-second five-clip montage. Clips are a Russian live-action trailer, anime trailer, RTS gameplay, coding UI, and music video. This tests visual sequence summaries only; no audio was passed. The montage clips are unrelated, so the target is an ordered scene synopsis, not a fabricated plot tying the clips together.

## Five-image run

One middle frame from each 10-second section was resized to 480x270, JPEG quality 90. The same five separate images and exact prompt were sent to each model. Cache was disabled and temperature was zero.

| Model/runtime | Warm p50 | Warm max | Content result |
|---|---:|---:|---|
| LiquidAI LFM2.5-VL-1.6B Q4_K_M, llama.cpp CUDA | **269 ms** | 269 ms | Preserved five-section order; broadly identified trailer, animated action, gameplay, model-list UI, and close-up. It called the trailer pose a hug and described an uncertain anime figure as a creature with a glowing chest. |
| Qwen3.5-2B Q4_K_M, llama.cpp CUDA | **473 ms** | 477 ms | Preserved order and gave more game/UI detail. It reversed the visible carrying/support relation in the trailer, over-read a red glow in the anime frame, and inferred shooting at plants. |
| Qwen3.5-2B BF16, Transformers | **3,047 ms** | 3,085 ms | Slightly over the 3-second target on this input. It assigned the close-up face to the coding section and described the music frame as an abstract dark shape; it also attempted to transcribe unreadable trailer text. |

The two Q4 models are both very fast. LFM is a promising coarse scene-sequence sensor; Qwen Q4 gives more detail but its unsupported and reversed action claims are material. Neither is accepted as a factually reliable plot describer from one still per scene.

## Dense one-image storyline run

The labeled contact sheet contains 15 frames (three per 10-second section). Compared with the BF16 reference:

| Model/runtime | Warm p50 | Warm max | Result |
|---|---:|---:|---|
| Qwen3.5-2B BF16, five concise lines | 2.435 s | 2.450 s | Complete five-line sequence; useful game/UI details, but some unsupported action/relationship claims. |
| Qwen3.5-2B Q4_K_M, five concise lines | **0.788 s** | 0.793 s | Output all five lines, but repeated generic phrases for the game and UI rows. |
| Qwen3.5-2B Q4_K_M, one paragraph | **0.769 s** | 0.779 s | Covered the sequence and the model-list/performance scenes, but invented a horse with red eyes, tanks, an emotional arc, a couple relationship, and smoking. |
| Qwen3.5-2B BF16, one paragraph | 2.458 s | 2.488 s | Preserved the broad scene order, but used the full 80-token budget and ended mid-sentence before finishing the last section. It called the coding interface a chat. |

Quantization substantially improves request latency here, but it does not preserve the BF16 result quality with the tested prompts. The Q4 paragraph is fast enough but too speculative; the BF16 paragraph stays inside 3 seconds but is truncated. The BF16 compact five-line contact-sheet mode remains the most useful complete dense summary so far, and still needs fact-grounding improvements.

## Fifteen-image checks

Three frames per 10-second section (source times 0, 4, and 8 seconds) were sent as 15 separate images to LFM2.5-VL-1.6B Q4 and Qwen3.5-2B Q4. Both repeatedly summarized early images rather than respecting the five groups: LFM shifted the trailer people/smoking into later sections; Qwen assigned the trailer and anime frames to sections that should have been gameplay, coding, and music video. This input format is therefore rejected for these runtimes.

Qwen3.5-2B BF16 was also tested with those 15 sampled frames encoded as one native video with source timestamps. Warm p50 was **2,834 ms**, max **2,903 ms**. Despite meeting the latency target, it carried a man from the trailer into the game and coding sections and called the music-video sections gameplay. This is a temporal grounding failure, not a pass.

For reference, the earlier labeled 15-frame contact sheet gave Qwen3.5-2B BF16 a **2,435 ms** warm p50 and all five section labels, with useful game and coding details but unsupported claims about trailer/anime actions. That remains the best tested dense-storyboard candidate for richer detail under the target, though not factually reliable enough for unverified narration.

## Contiguous trailer story test

The montage's first 10 seconds are one continuous Russian live-action trailer. Five frames at t=0,2,4,6,8 seconds were sent in chronological order. The reference ledger confirms: opening sky; a man supports a woman across his shoulder/back; then a woman's profile; finally a man's profile with a small bright point whose identity is explicitly uncertain.

| Model/runtime and prompt | Warm p50 | Warm max | Result against reference |
|---|---:|---:|---|
| LFM2.5-VL-1.6B Q4_K_M, neutral 96-token prompt | **267 ms** | 284 ms | Truncated at the token cap while listing frame-by-frame guesses, including “possibly running or jumping”; did not finish the sequence. |
| Qwen3.5-2B Q4_K_M, neutral chronology prompt | **409 ms** | 416 ms | Complete opening → outdoor carry/support pose → woman close-up → man close-up. It called the ambiguous bright point a lit cigarette and added a mood change. |
| Qwen3.5-2B BF16, same neutral prompt | 2,347 ms | 2,371 ms | Hit the 96-token cap before finishing. It added a clothing change and an embrace not established by the ledger. |
| Qwen3.5-2B Q4_K_M, cautious 40-word prompt | **273 ms** | 292 ms | Complete, concise opening/transition/ending sequence, but still called the pose an embrace and the bright point a cigarette despite explicit abstention instructions. |
| Qwen3.5-2B BF16, same cautious prompt | 1,454 ms | 1,463 ms | Complete in time, but repeated the embrace/hug and cigarette claims. More weight did not improve grounding on this clip. |

For this single coherent clip, Qwen3.5-2B Q4_K_M is the fastest complete story candidate and preserves the broad shot progression. It fails the uncertainty requirement on the ending object. This does not overturn the full-montage result: on five unrelated sections, its Q4 contact-sheet story was more speculative than BF16. Treat Q4 as a candidate for further grounded-video tests, not as an accepted narrator.

## Resolution correction: native 1280x720 trailer frames

The earlier t=8 assessment treated the small bright point as unresolved, based partly on the 480x270 test frames. Reinspection of the original 1280x720 frame clearly shows a lit cigarette in the man's mouth. The t=4 original-resolution frame likewise supports the man carrying/supporting the woman and visible physical contact. Therefore, Qwen and d1 cigarette/smoking detections, and carry/contact detections, must not be counted as fabrications. A romantic/personal relationship remains unestablished by these frames.

On the original five 1280x720 frames, Qwen3.5-2B Q4_K_M produced the same complete chronological summary on four repeats in **856-924 ms** (warm p50 873 ms), with 4,485 prompt tokens and 85 output tokens. It described the opening sky and birds, outdoor carry/contact, then the profile shots and cigarette. This is materially better evidence than the downscaled run: native resolution improves detail recognition while this Q4 configuration remains fast. It inferred a mood shift and a particular expression; those subjective details should be treated cautiously.

The BF16 native-resolution run took about **3.78 s** and hit its 128-token cap before completing. This is useful as a higher-detail mode if its extra latency and incomplete output are acceptable; it is not excluded merely for exceeding a 3-second target.

The d1 verifier was repeated on original-resolution frames (three repeats, deterministic outputs): at t=4 P(carry)=0.906, P(physical contact)=0.917, P(romantic relation)=0.625; at t=8 P(bright point)=0.737, P(cigarette)=0.919, P(smoking)=0.930. Median latency was 107-113 ms (individual requests 95-138 ms). The cigarette and contact predictions are correct at this resolution. The relationship score still illustrates that a verifier can assign probability to a relation not established by a still.

### Ten-frame native-resolution story comparison

To test denser temporal sampling, all ten original 1280x720 frames from t=0 through t=9 (1 fps) were sent as separate images with the same chronology and grounding prompt to Qwen3.5-2B Q4_K_M and LFM2.5-VL-1.6B Q4_K_M. Two warm repeats per model, temperature 0, cache disabled, 192 output tokens.

| Model | Warm latency | Tokens | Story/grounding result |
|---|---:|---:|---|
| Qwen3.5-2B Q4_K_M | 1,570-1,624 ms (p50 1,597 ms) | 9,302 prompt / 109 output | Preserved opening sky → outdoor pair → dark interior → woman profile → man smoking. The cigarette is visible and correctly identified. It nevertheless inferred a couple/joyful moment, invented quiet conversation, called the ending cigarette a hand-held object (it is in the man's mouth), and added a somber mood. |
| LFM2.5-VL-1.6B Q4_K_M | 1,658-1,702 ms (p50 1,680 ms) | 7,770 prompt / capped at 192 output | Truncated while repeatedly describing a woman in a red shirt and profile shots. It failed to preserve the carry/support scene and did not finish the sequence. |

A concise-prompt ablation on Qwen Q4 (three repeats) completed at **1,680-1,732 ms**, 115 output tokens. It covered opening, outdoor carry, dark room, and the final man's profile, but omitted the intervening woman's profile. It still described the action as playful/warm and said the man lights the cigarette, which the sampled frames do not establish as an action. A stricter four-clause prompt took **1,485-1,546 ms** and avoided emotional language, but omitted the final man shot. The “no more than five bullets” prompt still generated six bullets and truncated at 128 tokens (1,696-1,764 ms). Prompting shifts detail recall and speculation; it has not made the model consistently obey uncertainty and coverage constraints.

On the same five original frames, LFM took 798-858 ms but described one person in a red shirt across the sequence, with unsupported expressions (surprised/laughing/neutral), missing the clearly visible man supporting a woman. Qwen's five-frame native-resolution summary took 856-924 ms and retained the main progression and carry/support, though it still inferred emotion/relationship and mood. Thus LFM's lower latency does not compensate for its missed scene structure here. Qwen is the stronger tested narrative candidate on this particular clip, but its ungrounded social/emotional claims and final-hand error mean the output should be treated as a draft observation, not verified fact.

The reference for these results was rechecked against the original frames, not just the lower-resolution contact sheet. The earlier ledger's t=8 “uncertain bright point” note remains appropriate for the contact-sheet scale but is too cautious for native 1280x720: frame t=9 plainly shows the cigarette in the man's mouth. At t=5 the original frame shows three people (the ledger undercounted them); a conversation is not established by the still.

### Five-clip, native-resolution replay

For a broader paired comparison, Qwen3.5-2B Q4_K_M and LFM2.5-VL-1.6B Q4_K_M each received the same ten original 1280x720 frames from each of the five 10-second montage segments (1 fps), with audio excluded, cache disabled, and the same visual-only chronological-summary prompt. Two repeats per segment produced deterministic outputs. All Qwen requests finished in 1.72-1.95 s except gameplay, which hit the 192-token cap at 1.95 s; a 320-token follow-up completed that gameplay answer in 2.06-2.12 s. LFM requests took 1.56-1.70 s; several also hit the cap.

| Segment | Qwen3.5-2B Q4, p50 and result | LFM2.5-VL-1.6B Q4, p50 and result |
|---|---|---|
| Russian trailer | 1.91 s; preserved the broad cut sequence and cigarette, but invented tender/serious conversation and emotional interpretations. | 1.66 s; collapsed the sequence into repeated descriptions of a face/blur and did not reach the ending. |
| Anime trailer | 1.72 s; broadly preserved title/action/hallway order, but inferred restraint, a laboratory, a strike, and garbled Russian title text. | 1.65 s; described repeated facial-expression changes and omitted the title cards, fight, and hallway. |
| RTS gameplay | 1.95 s at 192 tokens (truncated); described an RTS battle and a plant-like unit, but added unverified combat/intent. At 320 tokens, p50 2.09 s and complete, with more repetition and the same unverified strategy narration. | 1.57 s; invented a plant consuming and destroying turrets; the visual ledger supports battlefield/units/structures but does not identify those entities or actions. |
| Coding interface | 1.90 s; identified model menus, recent-task text, terminal, and settings in sequence; this was the most text-specific and grounded result in this pair. | 1.61 s; misread the coding interface as a smartphone/message exchange. |
| Aqua music video, visuals only | 1.75 s; followed the performer, keyboard close-up, cutaways, and return to microphone. It inferred singing and performance sound from images despite receiving no audio. | 1.62 s; repeated face-angle descriptions, missed the keyboard and microphone sequence, and truncated. |

Across these five clip types, Qwen is the clear narrative-quality winner among this paired Q4 comparison, with each segment's answer latency under 2.1 s after the gameplay token increase. It is not fact-safe: anime semantics, gameplay events, and inferred feelings/vocals need corroboration or uncertainty handling. LFM is about 0.3 s faster at the median but repeatedly loses shot order or scene category, so that speed advantage is not useful for the requested story context. This paired replay strengthens Qwen's candidacy but does not establish production reliability; the manual ledger is coarse and contains at least one corrected person-count miss at trailer t=5.

## d1-Omni fact-verifier check

To test whether a separate fast classifier could filter the Qwen claims, d1-Omni-2B Q8_0 was asked three typed questions per image on the same trailer frames. It returned the same probabilities on every repeat, with 63–66 ms warm p50:

- At t=4, manual reference supports a carry/support pose and does not establish a relationship. d1 returned P(carry/support)=0.925, but also P(embrace)=0.812 and P(relationship established)=0.846.
- At t=8, manual reference marks the bright point as unresolved. d1 returned P(point visible)=0.826, P(cigarette)=0.953, and P(smoking)=0.951.

d1 is fast, but its earlier low-resolution “false positive” interpretation is invalidated by the original-resolution check. It still should not be used as an unquestioned verifier for inferred relationships: a model probability is not proof that a social relation is visible.

## Current decision

- **Fastest useful coarse sequence:** LFM2.5-VL-1.6B Q4_K_M, five representative frames, approximately 0.27 s. It is not detailed or grounded enough to act as the only describer.
- **Benchmark selection for the visual story describer:** Qwen3.5-2B Q4_K_M. In the paired five-clip replay, it followed scene order and produced useful detail for trailer, anime, RTS, coding UI, and music-video visuals at 1.72-1.95 s per 10-frame window. The RTS answer completed at 2.09 s with a larger token budget. LFM2.5-VL-1.6B Q4 is about 0.3 s faster at the median but repeatedly loses the actual scene/story and misreads coding and music frames. Qwen's Q4 weights are 1.22 GiB and its vision projector 0.62 GiB on disk (1.84 GiB combined; runtime memory was not captured in this replay).
- **Grounding limit:** Qwen is the most correct tested model for this task, not a fact-safe narrator. It invents or overstates social/emotional interpretations, anime actions, gameplay strategy, and vocal activity inferred from silent images. Keep its observations provisional; use OCR/UIA for text and audio sensors for sound. Do not convert inferred claims directly into agent speech.
- **Dense multi-clip summary:** Qwen3.5-2B BF16 on a labeled 15-frame contact sheet, approximately 2.44 s, has more useful game/UI detail but makes unsupported claims. Q4 on that same sheet is faster (~0.78 s) but generic/speculative. This differs from summarizing a continuous trailer and should not be conflated with it.
- The 3-second figure is a provisional latency budget from the task, not a hard rejection rule. Warm Qwen Q4 requests met it on these five windows; the full-resolution BF16 run at ~3.78 s was truncated and did not outperform the Q4 story here.
- This is a benchmark selection, not an integration or always-on acceptance claim. The replay used a warmed GPU1 server, two repeats per segment, and no audio; continuous-load memory, cold-start behavior, and long-duration observation freshness were not measured here.

## Artifacts

- LFM 1.6B on the same five images: `runtime/lfm-detail-probe-20261028/lfm16b-5frames-results.json`
- LFM 1.6B on a 15-frame contact sheet: `runtime/lfm-detail-probe-20261028/lfm16b-storyboard-results.json`
- LFM 1.6B on 15 individual images: `runtime/lfm-detail-probe-20261028/lfm16b-15individual-results.json`
- Qwen3.5-2B BF16 on the same five images: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-five-individual-frames-results.json`
- Qwen3.5-2B Q4 on the same five images: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-q4-five-individual-results.json`
- Qwen3.5-2B Q4 on 15 individual images: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-q4-15individual-results.json`
- Qwen3.5-2B Q4 five-line contact-sheet run: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-q4-storyboard15-results.json`
- Qwen3.5-2B Q4 one-paragraph run: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-q4-storyline-paragraph-results.json`
- Qwen3.5-2B BF16 one-paragraph run: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-bf16-storyline-paragraph-results.json`
- Qwen3.5-2B BF16 native-video 15-frame run: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-native15-video-results.json`
- Contiguous trailer, neutral Q4 comparison: `runtime/qwen35-2b-story-20261028/results/consecutive-trailer-q4-results.json`
- Contiguous trailer, Q4/BF16 cautious prompt comparison: `runtime/qwen35-2b-story-20261028/results/consecutive-trailer-q4-grounded-results.json` and `consecutive-trailer-bf16-grounded-results.json`
- Contiguous trailer, BF16 neutral prompt: `runtime/qwen35-2b-story-20261028/results/consecutive-trailer-bf16-results.json`
- d1-Omni verification probabilities: `runtime/d1-omni-test-20261028/realclip-reasoning-bench/trailer-ambiguity-verifier.json`
- d1-Omni native-resolution verification probabilities: `runtime/d1-omni-test-20261028/realclip-reasoning-bench/trailer-ambiguity-native-resolution.json`
- Contiguous trailer, native-resolution Q4: `runtime/qwen35-2b-story-20261028/results/consecutive-trailer-native-resolution-q4.json`
- Contiguous trailer, native-resolution BF16: `runtime/qwen35-2b-story-20261028/results/consecutive-trailer-native-resolution-bf16.json`
- Contiguous trailer, native-resolution LFM 1.6B Q4: `runtime/lfm-detail-probe-20261028/lfm16b-native-trailer-results.json`
- Contiguous trailer, 10-frame native-resolution Qwen/LFM comparison: `runtime/qwen35-2b-story-20261028/results/native-10frame-trailer-ab.json`
- Contiguous trailer, 10-frame Qwen prompt coverage/grounding ablations: `runtime/qwen35-2b-story-20261028/results/native-10frame-trailer-grounded-prompt.json`, `native-10frame-trailer-coverage-prompt.json`, `native-10frame-trailer-compact-prompt.json`, and `native-10frame-trailer-compact128-prompt.json`
- Five-clip 10-frame native-resolution Qwen Q4 replay: `runtime/qwen35-2b-story-20261028/results/qwen-q4-fiveclip-10frame-results.json`
- Five-clip 10-frame native-resolution LFM 1.6B Q4 replay: `runtime/qwen35-2b-story-20261028/results/lfm16-q4-fiveclip-10frame-results.json`
- Gameplay expanded-budget Qwen follow-up: `runtime/qwen35-2b-story-20261028/results/qwen-q4-gameplay320-results.json`
- Prior dense storyboard results: `runtime/qwen35-2b-story-20261028/results/qwen35-2b-storyboard-15frames-compact-results.json`
- Manual frame ledger: `runtime/multimodal-realclips-20261024/visual-ground-truth-1fps-20261024.json`
