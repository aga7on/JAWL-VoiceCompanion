# Qwen2.5-Omni on selected Russian trailer excerpt — 24 Oct 2026

## Scope

The selected `Project Hail Mary` trailer excerpt is 10 seconds from source
00:30–00:40. The already-running local Qwen2.5-Omni endpoint received the same
audio and video interval in four cache-disabled calls: video-only, audio-only,
joint A/V with video first, and joint A/V with audio first. Video was sampled at
1 fps (10 frames, 640×360). Audio was a temporary mono 16kHz PCM WAV. The server
was not reconfigured or restarted.

The request used llama.cpp's documented typed image and audio content parts in
the Chat Completions API ([server multimodal input documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)).

## Results

| Lane | Latency | Prompt/completion tokens | Result |
|---|---:|---:|---|
| Video-only | 1.864s | 3,187 / 187 | Identified the Sony logo, sun, man in yellow coat/lab, woman, then teacher and students. Two adjacent sampled frames produced a repeated classroom claim. |
| Audio-only | 0.459s | 843 / 66 | Recognized Russian dialogue and noted music/effects. It reversed speaker attribution: it said the teacher considers himself the only scientist, while the dialogue addresses him as the only scientist who can solve the problem. |
| Joint, video first | 1.205s | 4,000 / 41 | Returned only three visual bullets; omitted speech and music despite both being present in the input. |
| Joint, audio first | 1.354s | 4,000 / 76 | Mentioned sun, teacher/students, music and conversation, but did not establish meaningful temporal audio/video alignment; “link” just repeated that both music and conversation were present. |

No request hit its generation limit in the accepted run. Prompt cache was zero
for each request. In a separate local modular probe, GigaAM transcribed the 16
subtitle words through the exact clip boundary; YAMNet marked Music in 2/9
overlapping windows. Those are separate lanes and do not validate Qwen's A/V
fusion.

## Assessment

**Not a pass for a sole live sensory model.** Qwen2.5-Omni gives a useful coarse
visual shot list and fast standalone audio summaries. However, the interpretation
of who said what is wrong, and changing only the ordering of image and audio
parts changes whether audio is surfaced at all. The joint response does not
show grounded synchronization. Keep the modular ASR and soundscape lanes
independently inspectable; use the Omni output as a fallible extra observer,
not as a replacement for provenance-aware sensor lanes.

## Parallel companion roles

The intended design is three long-lived concurrent roles, not one multimodal
request waiting for the other modalities to finish:

1. **Brain:** Hikari/JAWL owns dialogue, memory, tools, attention, and whether
   to speak. It receives compact observations rather than raw sensor payloads.
2. **Visual observer:** Qwen's bounded asynchronous worker describes current
   scene changes and keeps a short timestamped visual event history.
3. **Audio observer:** GigaAM supplies timestamped speech; YAMNet independently
   supplies sound/music presence and recurrent event tags. A conditional music
   describer may add style/timbre later, but should abstain until its labels are
   validated.

Each observation should preserve modality, source, start/end/capture time,
confidence or abstention, and a short fact list. A fusion layer may relate
observations only when their time intervals overlap; the brain can then
describe the shared scene. The workers continue independently while the brain
is busy or DND is active, using bounded latest-only queues and freshness TTLs.
The repository already contains most of these separate lanes, but 24/7
integrated delivery and accepted music-style description remain open.

Hikari could not be compared through the current 8990 process: it is a
text-only launch (`--ctx-size 8192`, no `--mmproj`) and its live server
metadata reports typed content unsupported. I loaded the available Q8
projector in a separate loopback CPU-only Hikari server and sent the same 10
sampled frames. The request timed out at 120s with no completion; server logs
showed 2,394 prompt tokens and 52s of prompt processing before generation.
The isolated server was stopped and port 8996 is free. The user-owned Hikari
8990 and Qwen 8995 processes were left running. This is a CPU latency failure,
not evidence about GPU1 projector quality.

## Limits

This is one short excerpt and one call per condition, so it cannot estimate
accuracy or variance. Sparse 1fps sampling misses brief actions. The probe is a
direct model endpoint test, not a live companion capture→fusion→brain turn and
does not measure continuous CPU/RAM/GPU load or 24/7 stability.

Artifacts:

- Inputs and responses: [`project-hail-mary-qwen25-omni-20261024.json`](../../runtime/audio-path-replay/out/project-hail-mary-qwen25-omni-20261024.json)
- Hikari CPU timeout telemetry: [`project-hail-mary-hikari-mmproj-cpu-20261024.json`](../../runtime/audio-path-replay/out/project-hail-mary-hikari-mmproj-cpu-20261024.json)
- Reproducer: [`probe_selected_trailer_omni.py`](../../scripts/probe_selected_trailer_omni.py)
- Audio lane evidence: [`project-hail-mary-russian-trailer-asr-20261024.json`](../../runtime/audio-path-replay/out/project-hail-mary-russian-trailer-asr-20261024.json)
