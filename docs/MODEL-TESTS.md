# Local model test record

Last updated: 2026-09-02

These tests use files already present on the workstation. No model weights are
copied into this repository.

## Selected baseline

| Role | Profile | Decision |
| --- | --- | --- |
| Vision and UI grounding | Qwen3-VL-2B Q4_K_M + F16 mmproj | Primary CPU profile |
| Final ASR bridge | Qwen3-ASR-0.6B Q8_0 + mmproj | Primary audio profile |
| Streaming ASR/VAD | VoiceMem sidecar | Remains the default streaming owner |
| Fast text fallback | Bonsai-1.7B | Retained from the benchmark; text-only |
| TTS | TeraTTSv2 (provisional) | Best current CPU/clarity candidate; prosody and adapter validation pending |

## Qwen3-VL-2B from the moved benchmark directory

Paths:

```text
G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-Q4_K_M.gguf
G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-mmproj-F16.gguf
G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe
```

The full suite was rerun after the move. It loaded in 1.78 s and reached a
peak of 4.36 GB RSS:

| Case | Wall time | Image TTFT | Generation |
| --- | ---: | ---: | ---: |
| Image | 7.72 s | 1.84 s | 37.5 tok/s |
| 4-frame Nyan sequence | 9.82 s | 4.45 s | 35.1 tok/s |
| UI screenshot | 17.04 s | 8.68 s | 32.1 tok/s |
| Text-only control | 4.51 s | 0.04 s | 40.0 tok/s |

The model identified the illustration and Nyan Cat correctly and returned all
8 expected UI elements as JSON. Coordinate score: 8/8 found, 2/8 raw hits,
4/8 hits after affine calibration, calibrated mean error 45.7 px. The model
therefore remains suitable for explicit look and bounded watcher work, but
calibration and HostOS postconditions are still mandatory for actions.

## Qwen3-ASR-0.6B from the moved benchmark directory

Paths:

```text
G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf
G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf
```

The benchmark passed on the moved files with 1.48 GB RSS:

| Input | Wall time | RTF |
| --- | ---: | ---: |
| 12 s clean English speech | 1.75 s | 0.15 |
| 30 s Nyan audio | 4.68 s | 0.16 |

The clean speech transcript was exact. The music sample was not treated as
speech; the model produced humming-like output, which is acceptable for the
ambient triage boundary but not a music-description model.

The same ASR was tested on local Russian TTS-generated samples. Short welcome
phrases from Qwen3-TTS and Chatterbox were transcribed correctly. Pushkin
poem samples were broadly recognized but had word and ending errors, so this
is evidence for a usable first Russian path, not a real-microphone quality
claim.

| Source | Audio length | Wall time | Result |
| --- | ---: | ---: | --- |
| Qwen3-TTS welcome | 4.72 s | 1.55 s | Correct short phrase |
| Qwen3-TTS poem | 11.28 s | 2.16 s | Several word errors |
| Chatterbox welcome | 6.04 s | 1.42 s | Correct short phrase |
| Chatterbox poem | 10.40 s | 2.30 s | Several word/ending errors |

Additional installed TTS candidates were checked with the same local Qwen3-ASR
recognizer. TeraTTSv2 generated 4.9 s/11.3 s samples at RTF 0.06/0.05 with
2.56 GB reported RAM; its welcome transcript was exact and the poem was
essentially exact apart from a small lexical ending error. XTTS-v2 produced an
exact welcome transcript and a mostly correct poem at RTF about 1.25–1.27 with
3.27 GB RAM. Pocket-TTS was fast (RTF about 0.2) but its Russian samples were
not intelligible to the Russian ASR check. These are acoustic intelligibility
checks, not a subjective prosody or first-audio benchmark.

Decision: treat TeraTTSv2 as the provisional TTS candidate for the next adapter
experiment. Keep Qwen3-TTS/Chatterbox/XTTS-v2 available until prosody, startup,
first-audio latency, cancellation and avatar lip-sync are measured through the
actual Companion path. No TTS model is hard-coded as final yet.

The installed TeraTTSv2 implementation also exposes a streaming generator. A
warm CPU run with the distilled model and `chunk_frames=16` produced the first
audio chunk in about 1.04 s, then four chunks for 3.84 s of audio (overall RTF
about 0.33). Its input requires an explicit `<ru>...</ru>` or `<en>...</en>`
language tag. This makes it viable for a future adapter. The Companion now
exposes `/api/tts/stream`, which provides sentence-level first-audio through a
bounded NDJSON/WebAudio queue. The installed Tera worker is still used through
its whole-WAV REST wrapper; its native chunk generator is not yet wired into
the provider boundary.

## VoiceMem bundled streaming ASR/VAD

The VoiceMem environment was also exercised in its own local environment with
`VOICEMEM_ASR=sherpa`, the bundled Silero VAD and local embedding/slot models.
The test fed `G:\AI\VoiceMem\assets\speech.wav` as 32 ms PCM16 chunks through
the real `VoiceMem.stream(...).feed(...)` boundary, with no network service and
with an isolated temporary memory root:

| Fixture | Warmup | Partial updates | Final result |
| --- | ---: | ---: | --- |
| VoiceMem `speech.wav` (zh-en sherpa profile) | 5.61 s | 66 | `我喜欢吃马卡龙` |
| Russian Qwen3-TTS welcome WAV (zh-en sherpa profile) | 7.55 s | 96 | no completed turn; last partial was an English hallucination |

This confirms that the native VoiceMem streaming/VAD/memory boundary is
operational, but its bundled sherpa model is not a Russian acoustic model. It
must not be selected as the Russian microphone recognizer. The architecture
therefore keeps VoiceMem as the streaming lifecycle, VAD and memory sidecar,
while Qwen3-ASR remains the Russian recognizer until a true streaming Russian
provider is validated.

## Ternary Bonsai text workers

The installed Ternary Bonsai family was checked for the deferred ambient-memory
compression role. These are text-only workers, so they do not compete with the
VLM path for image/video work:

| Profile | Load | Peak RAM | Plain completion | Chat smoke |
| --- | ---: | ---: | ---: | --- |
| Bonsai 1.7B PQ2 | 3.0 s | 1.29 GB | 50.7 tok/s | 4/4 basic checks passed |
| Bonsai 4B PQ2 | 1.4 s | 2.54 GB | 25.2 tok/s | 4/4 basic checks passed |
| Bonsai 8B PQ2 | 1.8 s | 4.24 GB | 14.5 tok/s | 4/4 checks, but verbose/repetitive in plain completion |

The chat smoke covered a fact, arithmetic, exact-list instruction and a
context question. Decision: use Bonsai 1.7B as the first optional RAM-resident
worker for delayed ambient summarization and topic extraction; deterministic
local policy owns importance. It must remain asynchronous and bounded by a TTL;
it is not the canonical chat model, not the Russian ASR and not the Vision
model. Bonsai 4B/8B stay available for later quality comparisons, but their
extra memory and lower throughput do not justify placing them in the real-time
loop now.

The new OpenAI-compatible triage adapter was then tested against a live local
Bonsai 1.7B `llama-server`. It returned schema-valid JSON with the expected
`source_event_ids`, and the server was stopped after the request. The semantic
decision was `ignore` for all four synthetic cases, including an explicit error
and an explicit “remember this important decision”. This is a valid transport
result but an unsafe importance policy for a small worker.

The production-shaped guarded path was then rerun with the same live endpoint:
the deterministic memory guard produced `promote_candidate` for the error and
explicit remember cases, and `retain` for the explicit plan and ordinary game
background. Bonsai's generated summary/topics are retained, while its
importance field is advisory only. Calibration of the salience regex and
eventual JAWL promotion still remain separate tasks.

## Additional installed VLM candidate: Qwen3.8-27B

The workstation also has a Qwen3.8-27B Q4_K_M plus F16 mmproj in the local
Hugging Face/LM Studio inventory. The mainline b10738 runtime can load it, but
the CPU profile is not suitable for continuous autonomy:

- approximately 27.15 GB RSS;
- image TTFT about 15.5 s and generation about 2.8 tok/s;
- four-frame video took about 53.6 s with 36.95 s image prefill;
- the UI request took about 165.7 s and reached the token limit before a
  reliable grounded JSON result.

The server's automatic reasoning mode also returned an empty
`message.content` for one request while generated reasoning tokens were
present. Explicit `reasoning=off` produced normal text. This is an important
provider/parser compatibility trap, but not a reason to make this model the
baseline.

Decision: keep Qwen3.8 as an optional future on-demand high-quality profile;
do not use it for the continuous screen watcher, real-time UI control or the
default autonomous loop.

## Reproduction

The moved benchmark scripts now use the moved ASR directory and the local
`scripts/prompts.json` path. The relevant checks are:

```powershell
cd G:\AI\VLM-RealTime-Bench
python .\scripts\asr_bench.py
python .\scripts\ui_score.py .\results\qwen3vl-moved_suite.json .\results\qwen3vl-moved_ui_score.json
```

The Qwen3-VL suite used the repository's `bench2` helper on port 8987. The
experimental Qwen3.8 runs used ports 8988–8990 and were stopped after each
test; no model server is intentionally left running by this record.
