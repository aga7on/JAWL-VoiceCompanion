# Music perception: next evaluation target (2026-10-24)

## User requirement

The ambient lane must support co-listening to games and video, not only ASR. It should keep independent, time-stamped evidence for speech/transcript, music presence, repeated instruments/sound events, musical style when supportable, and meaningful changes in the soundtrack. The brain should receive concise facts with uncertainty, not a fabricated free-form “understanding” from weak class scores. All always-on inference stays CPU-only and bounded in RAM/CPU; slow semantic captioning can be an on-demand/background lane only if it proves useful.

## What is currently implemented and verified

The integrated ambient path runs GigaAM and YAMNet as separate CPU lanes on the same bounded PCM. YAMNet detects persistent music and emits at most one stable repeated instrument/event label. It does not currently identify genres, lyrics, key, tempo, structure, mood, or a natural-language musical scene. The earlier model probe measured YAMNet at ~2.8 ms per 2-second window in isolation; production detector load added ~22.7 MiB RSS and a short inference raised the isolated process by ~31.5 MiB. These are not whole-companion budgets.

The first candidate sweep rejected `Musical-genres-Classification-Hubert-V1`: it labeled speech and silence as hiphop and noise as metal, despite high softmax values. MERT-v1-95M affect inference was ~1.9 s for 15 seconds and emitted valence/arousal on speech, silence and noise as well as music, so it stays gated research-only. Music+speech synthetic mix showed that ASR and music must remain independent; a high music threshold or blanket ASR suppression can miss background music.

## Model survey and decision

- **Microsoft CLAP / CLAPCap** is the most useful next experiment for a constrained vocabulary of styles, instruments, and scene descriptions: text-audio similarity can compare a curated set of candidate phrases, while a CLAPCap variant can generate captions. The model card describes zero-shot classification/retrieval and captioning, but the reference implementation is PyTorch/HTSAT, not a verified tiny ONNX CPU path; repository was archived in September 2026. Treat as an experimental quality/latency baseline, not an always-on deployment assumption. [Model card](https://huggingface.co/microsoft/msclap), [repository](https://github.com/microsoft/CLAP).
- **Public CLAP HTSAT ONNX export (MAGDA sample tagger)** is the most concrete accessible CPU candidate: the pinned bundle has a 111.8 MB FP32 audio encoder and 478.2 MB text encoder plus tokenizer, declared BSD-3-Clause. Text embeddings for a fixed style/instrument vocabulary can be prepared once, so the 478.2 MB text model need not stay in the live process; the audio encoder still adds about 112 MB of weights before runtime overhead and requires CPU/RSS measurement. The similarly named Earshot export was indexed but its model API returned HTTP 401 in this environment, so it was not downloaded. [Public model card and checksums](https://huggingface.co/ConceptualMachines/magda-sample-tagger).
- **MOSS-Music 8B** explicitly targets music captioning, genre/instrument/mood, lyrics, tempo/key/chords and structure, and is Apache-2.0. It is ~9.1B total parameters with a Qwen3-8B backbone; therefore unsuitable for continuous CPU inference in this profile. It can be a qualitative reference on short clips only if resources permit. [Model card](https://huggingface.co/OpenMOSS-Team/MOSS-Music-8B-Instruct).
- **Music Flamingo** is a newer music-specialized audio-language model for detailed captions and questions about harmony, structure, timbre, lyrics, and cultural context. Its model card targets NVIDIA A100/H100 systems and marks the weights non-commercial research only, so it is a possible offline research reference but not a candidate for JAWL's always-on CPU path. [Model card](https://huggingface.co/nvidia/music-flamingo-2601-hf).
- **Audio Flamingo Next Captioner 8B** can produce broad, timestamped captions spanning music, sound and speech, but the model card lists 8B BF16 and NVIDIA OneWay Noncommercial terms. Reject for the always-on local profile; research-only comparison if licensing and machine resources are acceptable. [Model card](https://huggingface.co/nvidia/audio-flamingo-next-captioner-hf).
- **MusicNN** offers a smaller 50-tag multi-label direction (Apache-2.0 on the examined HF mirror), but its class set, checkpoint provenance, and CPU latency need validation; it is a tagger, not a narrative captioner. It is worth testing beside CLAP if a reproducible ONNX export/checkpoint can be pinned. [Examined checkpoint](https://huggingface.co/oriyonay/musicnn-pytorch).
- **MuQ/MuQ-MuLan** (300M/700M) provides music-text similarity/features, but the reviewed released weights are CC-BY-NC; do not plan to ship until terms are acceptable. [Model overview](https://maruaudio.com/models/muq).

## Recommended architecture

1. **Always on:** YAMNet persistence gate plus GigaAM ASR independently, both with capture-time/source provenance. Add low-cost deterministic features only when useful (tempo/energy/onset changes) and label them as measurements, not inferred emotions.
2. **Conditional tagging:** after persistent music, compare candidate labels using a small CPU tagger or CLAP-style text-audio embeddings. Use a curated hierarchy (broad family → substyle; instruments; vocal/instrumental; energy/tempo descriptors). Require separation from the runner-up and temporal agreement; otherwise abstain. Do not treat softmax/similarity as calibrated probability.
3. **Caption/QA:** produce one short grounded description from stable evidence, either deterministic composition in the brain prompt or a slower on-demand captioner. Never claim key, lyrics, exact genre, emotional story, or source identity without a dedicated validated head.
4. **Micro-model option:** if off-the-shelf tags fail on the actual game/video domain, train a tiny classifier over frozen audio embeddings/features only after building source-disjoint labeled examples. Compare it to deterministic/CLAP baselines on held-out parent recordings. Keep it only if it improves accuracy and abstention at lower CPU/RSS; first confirm labels/data licensing.

## Next benchmark

Use at least 20 parent-recording-disjoint, source-labeled cases from game/video playback. Cover: (1) orchestral/cinematic score, (2) ambient/drone, (3) electronic/synth, (4) rock/metal, (5) pop, (6) jazz, (7) acoustic/folk, (8) game score with layered effects, (9) instrumental versus sung vocals, (10) speech over loud music, (11) speech over quiet music, (12) speech-only narration, (13) dialogue plus score, (14) music-to-silence, (15) silence-to-music, (16) style/track transition, (17) sudden intensity change, (18) effects/noise without music, (19) low-quality/compressed playback, and (20) ambiguous or mixed style where abstention is correct. Use more than one source recording per style; keep all excerpts from a parent recording in one split. Annotate audible facts and time spans: presence, speech transcript, broad style, vocal/instrumental status, audible instrument families, tempo/energy trend, salient changes, and a short factual caption. Compare YAMNet, CLAP similarity, deterministic rhythm/energy/onset features, and any pinned lightweight tagger. Score music event F1 and false-claim rate; style top-1/top-3 and abstention; instrument precision; speech/music overlap recall and ASR WER; caption factuality; change detection delay; per-window CPU time, process-tree RSS, freshness, and queue behavior. Report each capability separately: a correct transcript does not count as music understanding, and a music-presence hit does not count as style/caption success. Do not add a candidate to the daily profile before this gate.

## Current status

YAMNet+GigaAM integration is useful and validated as an event/transcription foundation. **Music style, mood, and free-form musical description remain open capabilities.** YAMNet exposes AudioSet genre classes, but on this probe it assigned Bach only `Classical music` 0.0032 and Saxophone Jazz 0.0636 (raw scores); those are too weak and uncalibrated to publish as styles. Its general music detection and event/instrument scores are much stronger on these two sources. MusicNN weights were downloaded only to ignored research storage; no new model was activated in the daily profile. The next useful candidate comparison is the pinned public MAGDA CLAP ONNX export vs another lightweight tagger or locally trained head over frozen embeddings, with YAMNet as the stable baseline. Music Flamingo 8B is a possible rich-caption research reference, but its card lists A100/H100-oriented use and non-commercial terms, placing it outside the always-on CPU lane.

### Live playback check and broader capability target — 24 Oct 2026

The latest 14.81-second NVIDIA DigitalOutput capture produced 694 loopback chunks, zero drops/errors, and no saved PCM/transcript. YAMNet detected Music in all 13 rolling windows (median 0.8925, max 0.9531; 2.76 ms mean CPU inference per window); GigaAM abstained on speech. This confirms routing and music presence for this playback sample. Specific Electronic music/Techno scores stayed below 0.03, so this run does not identify its style. Conditional MERT returned 0.4711/0.4583 in 1.91 seconds, but without human-labeled soundtrack affect this is not a validated mood description. See [candidate evaluation](music-sensory-candidate-evaluation-20261024.md) and `runtime/audio-path-replay/out/live-music-style-loopback-probe-20261024.json`.

The Hugging Face survey also surfaced `DionTimmer/whisper-small-multitask-analyzer`: a 0.2B Whisper-small captioner with task prefixes for tags/genre/mood/movement/theme and clips up to 30 seconds. It is a potentially useful conditional caption baseline, not an always-on candidate: the published usage is PyTorch/Transformers, no inference provider is listed, and the model card is inconsistent about CC-BY-4.0 versus CC-BY-NC-4.0. Resolve licensing and benchmark latency, RSS, factuality, and abstention before considering any integration. [Model card](https://huggingface.co/DionTimmer/whisper-small-multitask-analyzer).

Evaluation must cover separate facets instead of treating “audio understanding” as transcript text: presence/absence and transitions; stable instrument/timbre families; broad style with abstention; soundtrack energy/affect only after gated human-label validation; vocal/instrumental changes and singing lyrics as a separate ASR task; tempo/rhythm and structure; and a short scene-aware caption grounded jointly in audio and synchronized screen evidence. Keep provenance, time span, confidence/uncertainty and TTL for every track. Prefer cheap deterministic rhythm/energy features and event tags continuously; run any caption model only on a persistent new music segment or explicit question, with a bounded clip and latest-only work queue.

### Latest live-signal check — 24 Oct 2026

A follow-up 15-second NVIDIA DigitalOutput loopback opened successfully and collected 699 chunks with no drops/errors, but measured -101.5 dBFS and YAMNet classified every window as silence. This run cannot be used as evidence about music style; it indicates that the sound was not reaching this endpoint during that interval. PCM and transcript were not persisted. The probe exposed a NumPy boolean JSON serialization bug, now fixed by coercing the signal flag to a Python `bool`; reproducer: `scripts/probe_live_music_loopback.py`, scalar artifact: `runtime/audio-path-replay/out/live-music-loopback-user-check-20261024-followup.json`.

### MusicNN preflight and control probe — 24 Oct 2026

Pinned the examined HF checkpoint at revision `394be17` in ignored research storage (`runtime/models/audio/musicnn-pytorch-394be17`, 3.18 MB weights). Its first load attempt in the parity environment lacked `librosa` and `soundfile`; a temporary dependency install was stopped when it made no progress. Found those dependencies in the existing `runtime/vision-venv`, then ran a CPU-only probe with one Torch thread. Reproducer: `scripts/probe_musicnn_candidate.py`; scalar/tag artifact: `runtime/audio-path-replay/out/musicnn-candidate-probe-20261024.json`.

The model loaded in 3.24s and process RSS rose from 422 MiB before model loading to 770 MiB after load (this includes Python/Torch/Transformers, not just weights). On 4-second clips, median inference was 22–24 ms. It emitted music-like tags on clean Russian speech (`female`, `guitar`, `singing`), noise (`techno`, `harpsichord`, `rock`), and silence (`guitar`, `classical`, `opera`). On a speech+music fixture it guessed `electronic`/`techno`/`ambient`; those style tags are not independently grounded. For a 48-second Bach Toccata excerpt it included the correct broad `classical` tag but also conflicting/unfounded `piano` and `guitar`; p50 was 415 ms, max 1340 ms across three repetitions. On a saxophone fixture, the top tags were `classical`, `violin`, `guitar`, and voice labels; it failed to name the prominent saxophone.

Decision: reject this checkpoint for an always-on music-style lane. Its speed per short window is attractive, but false style/instrument claims on negative controls and a ~769 MiB process RSS make it a poor fit. A YAMNet gate could suppress clean speech/noise/silence, but it does not validate MusicNN's style labels on mixed or ambiguous audio. The result is limited to this small fixture set and is not a benchmark of the full MusicNN family. No dependency was added to the JAWL environment and no model was activated in the daily profile.

### Whisper Tiny audio-caption preflight — 24 Oct 2026

`cahya/whisper-tiny-audio-captioning-v2.0` was fetched at pinned revision and
tested on CPU with one thread. It generated 12-second captions in 0.69–0.79s,
but produced generic near-identical Bach/sax captions, missed background music
under speech, and hallucinated a male voice on exact silence. Its process RSS
reached 829.9 MiB with the PyTorch/Transformers runtime. Reject it for always-on
or current-context audio claims. The model card declares Apache-2.0, but its
1M-sample training dataset's audio terms remain unclear, so research only pending
provenance review. Full method, weight hash, and outputs are in the
[candidate evaluation](music-sensory-candidate-evaluation-20261024.md). The
source model card documents its 37.8M parameter size and training dataset:
[Whisper Tiny captioner](https://huggingface.co/cahya/whisper-tiny-audio-captioning-v2.0),
[AudioSnippets dataset](https://huggingface.co/datasets/mitermix/audiosnippets).

### YAMNet genre-head probe — 24 Oct 2026

YAMNet's existing 521-class AudioSet map includes genre-like classes, so the already-loaded small ONNX model is a zero-additional-model-cost candidate for broad style cues. The CPU-only probe used the same clips and one-thread model. Its process RSS after load was 71.4 MiB; total inference for each 30-second-truncated fixture was 38–154 ms, including FFmpeg decode. Music scores were robust on Bach (median 0.972) and sax (0.730), weak on an unverified music fixture (0.242), and below the current gate on speech (0), noise (0.007), and silence (0). However, the mean `Classical music` score on Bach was only 0.0032, and mean `Jazz` on the sax sample was 0.0636; other genre scores were near zero. The speech+synthetic-music fixture had Music 0.354 but its strongest genre score was Electronic music 0.0102, not evidence of electronic genre. This confirms that the current YAMNet outputs are useful for music presence and some broad sound/instrument tags, but its genre classes do not support reliable genre narration on these examples. Raw scores are uncalibrated and this small fixture set cannot establish genre accuracy.

Reproducer: `scripts/probe_yamnet_music_styles.py`; scalar/tag artifact: `runtime/audio-path-replay/out/yamnet-music-style-probe-20261024.json`. Do not surface genre labels from these class scores yet.


### CLAP export fetch preflight ? 24 Oct 2026

Pinned MAGDA export revision `f24970352f239768aaad48cc8734fb298441a763` and verified the public README, license declaration, checksums, and published file sizes. An isolated `huggingface_hub.snapshot_download` attempt did not materialize either ONNX file after several minutes; the downloader process reached ~450 MiB working set while the `.incomplete` files remained zero bytes. The transfer was stopped. This is a failed artifact-fetch preflight, not model inference RSS or CPU latency evidence. No ONNX model was activated or added to the runtime profile; a resumable/manual transfer is needed before candidate inference and quality evaluation.

### CLAP audio encoder contract check - 24 Oct 2026

The pinned `clap_audio.onnx` was subsequently fetched through the official HF
CDN and verified at 117,275,256 bytes with the published SHA-256
`3f42f71e555b62709910b6efa66fa5879f00d9571874b12b0fa674f82dbfe332`. Static
ONNX inspection shows one CPU input `input_features` (`float`,
`[batch, 1, 1001, 64]`) and output `embedding` (`float`, `[batch, 512]`). This
does not match the README sentence that says the graph accepts raw waveform;
the pinned graph requires log-mel features. `ClapFeatureExtractor` at 48 kHz
with a single crop produced the expected shape from an 8-second Bach clip, and
CPU inference returned a finite, L2-normalized 512-d embedding (norm 0.9999998).
No style classification has been evaluated from this vector. A six-run
one-thread CPU timing on that same 8-second window measured 100.7 ms first
inference, then p50 89.1 ms / p95 92.7 ms; feature extraction was 11.3 ms and
session load 1.22 s. Process RSS was 280.5 MiB before model load, 427.9 MiB
after load, and 482.4 MiB after inference. These isolated Python/Transformers/
ONNX process numbers are not the added RSS in the companion.

The matching text encoder is 501,425,065 bytes with expected SHA-256
`c07b27204836877d5b615c103685b66ea8f21bc6b5b70a572be356125423a8bf`. The
initial direct-CDN transfer stopped at an 85,307,392-byte partial file; that
partial was unusable. A later parallel byte-range fetch completed and passed
the expected SHA check; see the retrieval results below.
`scripts/probe_clap_candidate.py` has now completed CPU retrieval against the
pinned, hash-checked text encoder. Neither CLAP graph has been wired into the
daily profile.

### Follow-up DigitalOutput check — 24 Oct 2026

After the owner reported playback enabled, an 11.9-second probe opened the
configured NVIDIA loopback and collected 558 chunks with zero drops, but the
signal was effectively silent (RMS `8e-6`, `-101.9 dBFS`, peak `3.1e-5`).
YAMNet returned Silence for all ten rolling windows and GigaAM abstained. No
PCM or transcript was saved. This confirms the capture endpoint remains
reachable; it does not provide another music/style sample. The live probe now
distinguishes an opened stream with no audible signal (`no_audio`) from a
successful audible capture, rather than labeling any nonempty zero-filled
buffer as captured. Artifact: `runtime/audio-path-replay/out/live-music-loopback-user-check-20261024.json`.

### CLAP text-audio retrieval result — 24 Oct 2026

One-thread CPU probes completed on the pinned audio and text ONNX graphs. CLAP
retrieved the saxophone sample correctly, but mis-ranked the known Bach Toccata
as saxophone/jazz even after averaging three paraphrases per label. It
identified the synthetic chord's synthesizer-like timbre while giving its broad
style an ambiguous classical/electronic ranking. On Russian speech, the scene
prompt for speech-over-music narrowly beat the speech-only prompt. The result is
promising for conditional semantic retrieval, but not reliable enough for
published genre or instrument facts on this tiny set. Isolated process RSS was
about 929 MiB with both encoders and the Python stack; an audio-only worker with
offline precomputed text prototypes has not been measured in the companion
tree. Reproducers and scalar outputs are in `scripts/probe_clap_candidate.py`,
`scripts/probe_clap_prompt_bank.py`,
`runtime/audio-path-replay/out/clap-candidate-probe-20261024.json`, and
`runtime/audio-path-replay/out/clap-prompt-bank-probe-20261024.json`.

### Conditional deployment gate (proposed, not yet measured)

If CLAP is evaluated again, keep the text encoder unloaded at runtime by
precomputing and hashing the normalized prompt prototypes. YAMNet must first
confirm persistent music; then allow at most one active 8-second CLAP request
and one newest pending window. Drop an answer if it is over 2 seconds old at
delivery. The audio-only isolated Python probe was about 482 MiB RSS, but that
is not the incremental daily process-tree cost; measure matched full-profile
CLAP-off/on runs using per-process PrivateBytes and WorkingSet, and exclude the
first CPU-delta sample. A 250 ms tree sampler can miss a short-lived process.

Suggested first-stage gates are no queue growth, pending depth at most one, no
stale delivery, CLAP p95 under 150 ms per window, mean added system CPU under 5
percentage points and p95 under 10, no voice-latency regression above 500 ms or
10% (whichever is larger), and process-tree PrivateBytes plateau within +512
MiB of matched baseline with under 5% drift during the last seven hours. These
are provisional engineering limits, not validated capacity targets. Run a
30–60-minute matched comparison first; only consider an 8-hour CLAP-on soak if
it passes both the parent-recording-disjoint factuality gate and the shorter
resource/continuity gate. The active YAMNet+GigaAM profile's own full-stack
acceptance remains open independently of CLAP.

### FMA artist-disjoint probe — 24 Oct 2026

An 18-track FMA Medium probe covers three distinct artists in each of six
catalog families (Classical, Electronic, Folk, Hip-Hop, Jazz, Rock). Tracks
were selected from per-track Attribution/CC0 entries, excluding noncommercial
and no-derivatives terms, and their unchanged MP3 files were fetched
individually and ZIP-CRC checked. CLAP top-1 matched weak catalog labels on
12/18 (66.7%): Electronic 0/3 and Jazz 1/3. Four controls (speech,
speech-over-music, noise, silence) ranked as expected; no music style led on
speech/noise/silence. CPU audio-encoder p50/p95 was 93.65/97.15 ms; isolated
RSS with both encoders and Python was ~0.96 GiB. This is proxy-label research,
not human-annotated validation; CLAP stays out of the daily profile.

The next set must add human labels for instruments/timbre, vocal/instrumental
status, tempo/energy, soundtrack transitions and a grounded short caption.
Eighteen tracks are too few to train a useful micro-model. Once the licensed
set is larger, compare fixed-prompt CLAP, a small head over frozen embeddings
and deterministic signal features using source-disjoint train/test groups;
score abstention and false claims as well as top-1 accuracy.
