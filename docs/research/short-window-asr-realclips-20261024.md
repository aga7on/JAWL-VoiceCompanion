# Short-window GigaAM replay on real sensory clips — 24 Oct 2026

## Question

Can reducing the ambient ASR window from the current 15-second cap to 5 seconds
make speech observations fresh enough for co-watching without losing too much
speech coverage?

## Method

Replayed the five existing 10-second real QA audio lanes through the local
GigaAM v3 e2e RNNT q8_0 CPU CLI. The short-window run used 5-second windows at
2-second hops (20 total windows). A paired reference run transcribed each full
10-second clip once and also ran the existing CPU YAMNet 2-second windows at
1-second hops. No capture device, live model server, companion, or TTS process
was started or changed. Audio and transcript text were not persisted; only
window timing, nonempty/normalized-length status, and normalized transcript
hashes are retained.

## Results

| Input | 5s windows with text | 10s clip with text | YAMNet windows scoring Music ≥0.30 |
|---|---:|---:|---:|
| Russian live-action trailer | 4/4 | yes | 4/9 |
| Russian anime trailer | 0/4 | no | 1/9 |
| RTS gameplay | 0/4 | no | 9/9 |
| Coding UI | 0/4 | no | 9/9 |
| Aqua music video | 1/4 | yes | 9/9 |

GigaAM inference latency on 5-second windows was p50 **224.6 ms**, p95
**236.4 ms**, max **290.8 ms**. The window-start-to-result age, including the
five seconds of required audio, was p50 **5.225 s**, p95 **5.236 s**, max
**5.291 s**. Full 10-second clip inference was p50 **379.9 ms**. These are
offline model-window measurements; they exclude the live capture cadence,
queueing, fusion, and delivery to a user turn.

## Decision

Do **not** lower the production 15-second segment cap based on this replay.
Five-second windows cut model compute by about 155 ms, while the age is still
dominated by audio accumulation and 4 of 5 lanes lose all nonempty ASR output
in at least some or all short windows. The trailer's windows remained
nonempty, but that alone does not prove transcript accuracy. A real-time
design needs speech-aware boundaries/partial results and deduplication, not
just shorter fixed final-ASR segments.

The YAMNet ≥0.30 Music count is diagnostic only. It fired on all gameplay and
coding windows; no human labels or speech/music-overlap score was collected,
so those hits are not accepted as correct music detections.

## Limits and next discriminator

This is five fixed clips, not source-disjoint accuracy evidence. Transcript
text was intentionally not retained, so WER, omissions, repeated words, and
semantic correctness remain unmeasured for the five-lane experiment. The
separately downloaded `Project Hail Mary` Russian trailer was probed afterward:
GigaAM matched the 16 words visible in deduplicated Russian auto-caption cues
through the exact 10-second cut, in 389.5 ms. This is one provisional match to
machine-generated captions, not human-grounded WER. YAMNet crossed its broad
Music threshold in 2/9 rolling windows; no genre or mood is accepted. The
separate Qwen2.5-Omni replay found order-sensitive audio omission and a
speaker-role error; see
[`selected-russian-trailer-omni-20261024.md`](selected-russian-trailer-omni-20261024.md).
The modular visual path remains untested. Details:
[`project-hail-mary-russian-trailer-asr-20261024.json`](../../runtime/audio-path-replay/out/project-hail-mary-russian-trailer-asr-20261024.json).
Before changing production, compare speech-aware/overlapping windows against the
15-second path on a locked independent set with human transcript references;
measure capture-to-delivery age and duplicate rate through the actual ambient
bridge. Preserve abstention and keep the YAMNet music lane independent from
ASR.

Artifacts:

- [`short-window-gigaam-20261024.json`](../../runtime/audio-path-replay/out/short-window-gigaam-20261024.json)
- [`realclip-audio-lanes-recheck-20261024.json`](../../runtime/audio-path-replay/out/realclip-audio-lanes-recheck-20261024.json)
- [`project-hail-mary-russian-trailer-asr-20261024.json`](../../runtime/audio-path-replay/out/project-hail-mary-russian-trailer-asr-20261024.json)
- Reproducer: [`probe_audio_freshness_windows.py`](../../scripts/probe_audio_freshness_windows.py)
- Trailer reproducer: [`probe_selected_trailer_asr.py`](../../scripts/probe_selected_trailer_asr.py)
