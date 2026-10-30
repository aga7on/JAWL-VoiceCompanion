# Three-role multimodal LLM smoke test — 24 Oct 2026

## Setup

Tested the user's proposed organization as three logical roles, not three different model families: (1) Hikari/Bonsai as the main text brain on GPU1, and (2) a visual observer plus (3) an audio observer using separate chat contexts/slots on one Qwen2.5-Omni-3B Q4_K_M server on GPU0. The Omni server was started from the locally installed llama.cpp build at `127.0.0.1:8995`, with its existing F16 multimodal projector, 24,576 total context tokens, and two parallel slots (12,288 per slot). Hikari was started directly at `127.0.0.1:8990` with its usual PQ2_0 weights and 8,192 context. The ordinary companion, GigaAM, EG2, YAMNet, local microphone, browser, and TTS were not started for this isolated test.

The selected Hikari checkpoint is the Qwen3.8-derived Ternary Bonsai 2 27B text model. Its base model card describes a separate optional vision tower/mmproj, and does not list an audio encoder. Prompt-defined roles can isolate tasks and contexts, but cannot add an audio input path to those weights. Sources: [Hikari checkpoint](https://huggingface.co/Hikari07jp/Ternary-Bonsai-2-27B-Abliterated-GGUF), [Bonsai 2 base model card](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf).

Qwen2.5-Omni was therefore used for both sensory roles, with distinct system instructions and concurrent server slots. The local server `/props` advertised `vision`, `video`, and `audio` modalities. A short MP4 input and an MP3 input were submitted in parallel with a Hikari text request. llama.cpp's multimodal docs identify Qwen2.5-Omni as accepting audio and vision; this specific locally built server also accepted the MP4 `input_video` request.

## Prompt used

Visual role: describe only visible facts; avoid inferring audio, hidden causes, or intent; separate clear observations from uncertainty. The request asked for 4–7 concise sentences covering overall scene/composition, objects/positions/appearance, temporal changes/action, readable text, and what cannot be determined.

Audio role: analyze only the supplied audio; never invent lyrics, instruments, genre, or emotion; state uncertainty. The request asked for 4–7 concise sentences covering speech/singing, music, likely instruments/timbre, rhythm/tempo/dynamics, changes/transitions, and broad style only when clear.

## Result

All three role requests completed concurrently:

| Role | Input | Latency | Result |
| --- | --- | ---: | --- |
| Hikari main brain | text status check | 0.56 s | `Online.` |
| Qwen2.5-Omni audio observer | licensed 30 s FMA Electronic MP3 | 2.54 s | Identified fast electronic/EDM music and a driving beat; repeated the same claims. It did not report instruments, vocal status, transitions, or uncertainty. |
| Qwen2.5-Omni visual observer | 12 s Earth/icon-card video | 2.70 s | Correctly described Earth rotation, city lights, space, and the cut to a dark icon card then back to Earth; imprecisely called the icon a yellow line and did not mention clouds. |

The test supports the proposed **role/context split** and proves that the local Omni endpoint accepts audio and video inputs while Hikari remains available as the main brain. It does not establish robust audio description or a continuously operating sensor loop. Audio quality is still too repetitive and incomplete for the desired companion; video is promising on this known clip but misses details. Initial MP4 submission failed because the first server configuration allocated only 4,096 context tokens per slot; restarting with 12,288 per slot fixed it. A first detailed-prompt attempt was invalid because PowerShell encoded Cyrillic prompt text as `?`; the reported successful responses came from corrected ASCII prompts.

GPU memory after both models loaded was approximately 10.3 GiB on GPU0 and 8.2 GiB on GPU1, with around 5.7/7.7 GiB free. This was a short functional smoke, not a performance or 24/7 acceptance run. Current Hikari and Omni servers were left listening on localhost ports 8990 and 8995 for continued experimentation; no capture daemon or automatic fusion into JAWL is running yet.

## Russian role prompts for the next run

**Визуальный наблюдатель**

> Ты — отдельный агент визуального наблюдения для живого компаньона. Описывай только то, что действительно видно; не додумывай звук, скрытые причины и намерения. Отделяй уверенные наблюдения от предположений. В 4–7 коротких предложениях опиши: общую сцену и композицию; главные объекты и их положение; видимое действие и изменения от начала к концу; важный читаемый текст или интерфейс; что определить нельзя. Если сцена не менялась, скажи это. Не заполняй ответ общими фразами.

**Аудионаблюдатель**

> Ты — отдельный агент аудионаблюдения для живого компаньона. Анализируй только приложенный звук; не выдумывай слова, инструменты, жанр и эмоции. В 4–7 коротких предложениях укажи: есть ли речь или пение и разборчивы ли они; есть ли музыка; какие инструменты и тембры действительно слышны; ритм, примерный темп и динамику; меняются ли голос, состав, громкость или музыка во времени; широкое стилевое направление только при ясных признаках. Если уверенности мало, явно скажи, что не уверен. Закончи одной естественной фразой о звучании. Не описывай видео и не угадывай источник.

These Russian prompts were not included in the successful measurement because the shell test harness corrupted non-ASCII input; retest them via UTF-8 file/API in the application path before adopting them.
