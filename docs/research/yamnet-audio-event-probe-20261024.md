# YAMNet ONNX as a broad audio-event sensor — exploratory probe (2026-10-24)

## Why this candidate

The current EG2 audio labels repeatedly confuse speech/noise/silence with music and detailed moods. The new ambient claim guard correctly prevents those labels from reaching memory as facts, but then intentionally abstains on most sound events. YAMNet is worth testing as a separate broad event detector, not as an audio captioner or emotion model.

The pinned Hugging Face export is [audiomagic/yamnet-onnx at revision `f25b741c2f0bdc6d7e6db24b5fddda23347dbafd`](https://huggingface.co/audiomagic/yamnet-onnx/tree/f25b741c2f0bdc6d7e6db24b5fddda23347dbafd). Its model card describes a format-only ONNX conversion of Google's original YAMNet with unchanged weights, a 16 kHz mono float waveform input, 521 AudioSet class scores and 1,024-dimensional embeddings. The original TensorFlow model documentation describes 521 classes, mono 16 kHz input, and approximately 0.96-second analysis patches at 0.48-second hops. [Hugging Face export/model card](https://huggingface.co/audiomagic/yamnet-onnx), [Google TensorFlow tutorial](https://www.tensorflow.org/hub/tutorials/yamnet), [Google model source](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet). License: Apache-2.0; AudioSet class ontology is CC BY 4.0 as stated by the export card.

Weights and source metadata are in `runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd/`. ONNX SHA-256 verified against the pinned Hugging Face blob: `d3835ffbbd4a1bb3e777f0ca217b5007907f5171dd5d17c4236b95b2af8f908e`. The model is 16,093,355 bytes.

## Local CPU results

`runtime/audio-path-replay/out/yamnet-existing-audio-cases-20261024.json` runs the actual model once on every existing audio/audio-visual fixture. ONNX Runtime reported only `CPUExecutionProvider`. On the current fixtures:

| Input | YAMNet output | Interpretation |
|---|---|---|
| Three Russian speech prompts | `Speech` 0.959–0.993; `Music` <0.0002 | No music false positive on these clips |
| Pauses appended to speech | `Speech` 0.666–0.804; `Silence` 0.167–0.277 | Speech remains top class; pause is visible as a secondary class |
| Quiet speech (-18 dB) | `Speech` 0.924 | Detected on this one transformed utterance |
| Speech + synthetic noise, 10 dB SNR | `Speech` 0.515; `Music` 0.003 | Speech still leads; noise description is weak on this synthetic mixture |
| Generated white noise | `White noise` 0.595, `Noise` 0.545 | Correct broad negative control |
| Digital silence | `Silence` 1.000 | Correct silence control |
| Bach/Toccata audio fixture, 48 s | `Music` 0.959; `Keyboard` 0.168; `Harpsichord` 0.159 | Broad music and instrument family recovered; not a mood/tempo narrative |

The cases share a few synthetic source recordings and do not estimate generalization. A paired local `world.mp4` segment at 8–16 s was classified as `Silence` by YAMNet, matching GigaAM's empty transcript and EG2's abstention, but that model agreement is not an independently human-labeled audio truth.

For two-second windows, the 1-thread session measured p50/p95 2.65/2.95 ms; two threads measured 1.38/1.47 ms; four threads measured 0.79/1.16 ms. Process CPU time per inference was about 2.6/2.9/3.1 core-ms respectively, so one thread minimizes total CPU and is already far below a one-second update cadence. Loading ONNX Runtime plus this model raised the isolated probe process RSS from 56.6 MB to 110.9 MB in the first probe; the later thread comparison process sat around 92 MB after load. These are isolated process measurements, not incremental full-companion memory or total process-tree latency. A 2-second/1-second-hop sweep over the Bach fixture crossed a descriptive `Music >= 0.5` threshold at its first observed hit at 1 s and exceeded it in 46/47 windows; the same threshold produced no hits in the speech, noise, or silence controls. Threshold 0.5 is exploratory and must not be promoted as a calibrated confidence gate.

Timing reports: `yamnet-cpu-probe-20261024.json`, `yamnet-existing-audio-cases-20261024.json`, `yamnet-2s-window-bench-20261024.json`, `yamnet-temporal-window-probe-20261024.json`, and `yamnet-thread-bench-20261024.json` under `runtime/audio-path-replay/out/`.

## Decision and next gate

Keep YAMNet as an **experimental, optional broad event sensor** candidate. Do not switch the daily profile or remove the current abstention guard yet. Its output supports broad labels such as music, speech, silence, noise, and instrument families. It does not establish genre, mood, tension, emotional intent, lyrics, or what an event means in the scene. It cannot independently recognize speech-plus-music overlap with enough evidence from this probe.

Next, validate it on new parent-recording-disjoint film/game audio: speech-only, music-only, speech+music, nonmusic effects/noise, near-silence, plus visually synchronized transitions. Preserve raw scores and source/time/age internally, apply conservative event persistence/hysteresis, and compare against EG2 on the same PCM. Require zero false music claims on speech/noise/silence controls and report positive coverage separately. Only then wire a one-thread streaming window into the ambient event path behind a flag; verify pause/stop clears its pending windows and cannot publish late results. Keep all mood and voice-affect claims out of scope until separately validated. No code in the production profile or TTS was changed for this probe.

## Additional source-disjoint local asset probe

Two more Gradio package assets were evaluated once with the same pinned YAMNet ONNX and CPUExecutionProvider, using one intra/inter-op thread. `sax.wav` (16.0 s; SHA-256 `12ee32c66257e1c98ed0f2f7b708a1eab638ec09f4c69dda3ec1d78047a7be4d`) scored Music 0.750, wind instrument 0.426, and Saxophone 0.381; inference took 27.5 ms. `recording1.wav` (3.328 s; SHA-256 `1d087876795ff2bc8b6e1a872eb9a9b2cca44db1866e9c9fa00df5a2556919ff`) scored Music 0.224, Singing bowl 0.174, Dial tone 0.127, and Telephone 0.096; inference took 4.3 ms. Gradio's AudioGallery lists `recording1.wav` as “Recording”; neither asset has independent semantic ground truth in this probe, and no listening-based labels were assigned. Therefore these results demonstrate output diversity and CPU feasibility, not accuracy or a verified false positive. In particular, they reinforce that a low single-window Music score must not be surfaced as a confirmed music fact without temporal and source-aware validation. Raw output and file hashes: `runtime/audio-path-replay/out/yamnet-gradio-assets-20261024.json`.
