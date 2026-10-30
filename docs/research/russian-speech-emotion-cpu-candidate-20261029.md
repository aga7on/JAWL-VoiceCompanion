# Russian speech prosody and emotion lane: CPU candidate review (2026-10-29)

## Gap

The current sensor stack exposes ASR, music presence, sound-event hypotheses,
and EmbeddingGemma audio candidates. It has no accepted lane for a speaker's
vocal prosody or emotion. Music mood tags do not describe the user's voice, and
ASR text cannot establish tone.

## Candidate

Hugging Face's
[`Aniemore/wav2vec2-xlsr-53-russian-emotion-recognition-quantized`](https://huggingface.co/Aniemore/wav2vec2-xlsr-53-russian-emotion-recognition-quantized)
is a Russian seven-class speech-emotion classifier (anger, disgust, enthusiasm,
fear, happiness, neutral, sadness), MIT licensed. Its `int4` weight file is
216,086,596 bytes (about 206 MiB); it expects mono audio resampled to 16 kHz.
The quantization is W4A16 on linear layers only, not an ONNX artifact. The card
reports macro-F1 0.7249 on 280 acted/balanced RESD clips, but only 0.0954 on a
12,079-clip Dusha podcast test and 0.2248 on a 5,187-clip CAMEO test. These
figures are self-reported; the substantial out-of-domain drop is the relevant
warning for a live companion. The card also says ordinary Transformers loading
may unpack weights to the compute dtype, so the 206 MiB checkpoint does not
establish low resident RAM or CPU latency.

A second Aniemore Russian model (`wav2vec2-bert-base-s-emotion-russian-resd`)
has a 608 MiB int4 checkpoint and similar weak cross-corpus behavior; it is not
the first probe candidate.

## Decision

Do not activate emotion labels in the daily profile. The bounded CPU probe has
now run on the three available RU speech/media WAVs. The checkpoint's SHA-256
matched Hugging Face metadata. Runtime was the existing CPU-only
`vision-venv` (PyTorch 2.14.0+cpu, Transformers 4.57.6), eight inference threads.
The quantized model initially failed to load because `compressed-tensors` was
missing; a temporary 0.17.1 install under `%LOCALAPPDATA%\Temp` enabled the
probe without changing the existing environment.

| Input | Duration | Model inference | Top output |
| --- | ---: | ---: | --- |
| `voice-native-ru-clean-20260906.wav` | 6.52 s | 16.106 s | enthusiasm 0.999 |
| `voice-native-command-20260906.wav` | 8.87 s | 21.405 s | enthusiasm 0.992 |
| `01_ru_trailer.wav` | 10.01 s | 24.405 s | disgust 0.989 |

Model load took 3.94 s. Process RSS was 0.747 GiB after load, 1.586 GiB after
the last inference, and 1.692 GiB peak. Each inference took about 2.4× the input
duration, so it cannot classify speech in real time on this CPU path. The two
neutral instruction fixtures received near-certain `enthusiasm`; the clips lack
human emotion labels, so this is not a measured accuracy score, but it is a
strong false-confidence warning. The int4 checkpoint becomes FP16 weights in
this Transformers path and expands the process to well above its 206 MiB file
size.

Decision: reject this candidate for always-on live voice affect. Do not use its
emotion output as an observation about the user. Objective acoustic delivery
features (rate, energy, pitch range/variation) remain a separate potential lane;
any future classifier requires source-disjoint and owner-reviewed spontaneous
speech labels, confidence calibration, and an explicit `unknown`/abstain state.

No raw PCM or transcript text was persisted. The temporary inference script
printed only class scores and timing. Do not present an unvalidated classifier
output as a fact about the user.
