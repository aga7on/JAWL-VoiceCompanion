# Full-duplex research adoption — TinyDuplex (2026-09-10)

## Update 2026-09-12 - adaptive speech system shipped (v1)

The first full-duplex milestone from FULLDUPLEX.md is now implemented in the
Companion voice lane: streaming ASR (CrispASR+GigaAM partials every ~0.5-0.8 s
with punctuation; final still Qwen3-ASR), semantic end-of-turn
(`turn_policy.py`: RU continuation cues hold one silence extension 800 -> 2000 ms),
adaptive draft cadence (800 ms streaming / 2500 ms fallback, draft carries
hold/silence_ms/required_ms), DUCK before STOP (~120 ms fade), backchannel v0
(quiet "Угу." after 7 s of user speech) and hands-free on by default.

Live acceptance: real-browser barge-in passed at gap=12 (cancel mid-speech at
15.3 s while TTS streams ran 9.5-11.9 s; two turns, both transcripts matched) -
`runtime/browser-barge-in-adaptive-gap12-20260912.json`. Live proof of the
streaming lane and semantic hold (hold=true on "...поверить. Но") in the
session log. Tests: `tests/test_turn_policy.py` (7), `tests/test_streaming_asr.py`
(4).

Source: `G:\AI\tinyduplex\FULLDUPLEX.md` (4259 lines, engineering reconstruction
of ChatGPT Voice/GPT-Live style full-duplex architectures) and
`G:\AI\tinyduplex\MVP_LOCAL_PC.md` (local-PC MVP profile). This document maps
the research to the JAWL companion stack and fixes what we adopt now, later,
or never. It does not change any accepted contract: JAWL stays the only
cognition/policy/memory owner; the Companion owns transport/voice; sensory
workers stay external capability processes.

## 1. Validated by the research (already our design)

- **Two-level architecture**: realtime voice lane + asynchronous reasoner
  (their "GPT-Live ⇄ large reasoning model") maps to Companion ⇄ JAWL. The
  rule: the voice lane must never block on the reasoner; results are injected
  into context when ready. Our current voice turn waits for the full JAWL
  turn (12–27 s measured) — this is the main violation to fix with an
  acknowledgement/backchannel lane, not by moving JAWL.
- **Do not train end-to-end speech models now**: their recommended first
  milestone is a cascade (streaming ASR → frozen LLM → streaming TTS) plus
  two tiny classifiers (5M endpoint, 5M barge-in). Our stack
  (whisper-turbo + Gemma/Ollama + VoxCPM2/Tera) matches this order.

## 2. Adopted now — cheap, no training

| Item | Research basis | Our action |
|---|---|---|
| DUCK before STOP on barge-in | duplex event policy actions `DUCK`/`STOP` | fade TTS playback before cancel; cancel contract unchanged |
| Backchannel events | `BACKCHANNEL` action inside the user turn; policy chooses the event, speech planner chooses the word | rule-based v0: pre-synthesized «угу/ага/понятно» clips through VoxCPM/Tera during long user turns; never takes the turn |
| VAD ≠ end of turn | `silence ≠ END`; P(EOT) must weigh syntax/hesitation | commit at 120 ms silence; hold ×2 when the tail is syntactically open («и…», «но…», «который…») |
| Partial ASR cadence | partials after 160 ms, updates every 80–120 ms | tighten draft polling from 2.5 s to the 80–120 ms class at the ASR draft endpoint |
| Adaptive sensory rate | `SEMANTIC_UPDATE_REQUIRED` only when representation changes | screen: capture always, VLM only on pHash change; audio: VAD/RMS always, CLAP/ASR on events |

## 3. Sensory context architecture (modular equivalent of their acoustic layers)

Their hierarchical audio representation (semantic tokens + prosody latents +
speaker style) is implemented modularly:

- semantic text — whisper-turbo (RTF 0.385 CPU);
- prosody/music/events — CLAP zero-shot tags (music genre, intonation,
  sound events) per 2–5 s loopback chunk;
- screen context — Qwen3-VL-2B Q4 on GPU1 via llama-server (short RU
  captions, 0.5–1 Hz realistic), full OCR on demand.

Memory tiers (their L0/L1/L2):

- **L0** — rolling 60–120 s ring buffer of typed sensory observations
  (`correlation_id`, timestamps, provenance) in the sensory worker;
- **L1** — compressed episodes consolidated by VoiceMem;
- **L2** — canonical memory, JAWL only.

Realtime budget is reserved for conversation; background sensory context may
lag seconds. The 2–3 Hz figure is sampling rate; captions fire on scene
change and on demand, not per frame.

## 4. Adopted SLOs (from MVP_LOCAL_PC.md gates)

| Metric | Target | Status |
|---|---|---|
| first-audio p50 (ack lane) | ≤ 1.2 s | open — needs backchannel/ack clip lane; full JAWL answer is async |
| first-audio p95 (ack lane) | ≤ 2.5 s | open |
| barge-in detection p95 | ≤ 80 ms | not yet measured browser-side |
| playback stop p95 | < 100 ms | browser stop local; worker cancel measured ~0.5 s |
| bounded queues | ≤ 200 ms | not yet measured |

## 5. Later / post-MVP (do not start yet)

- Tiny turn-taking classifier (3–6 M params) on whisper encoder latents —
  after the cascade + sensory path are stable; dataset from our own
  timestamped conversations.
- True duplex listen-during-own-speech — requires physical AEC first
  (open external gate). Without AEC it feeds self-echo into ASR.
- Voice cloning, acoustic-token generation, native speech decoder — out of
  scope for the current product slice.
- Never: two resident copies of the same LLM; one resident model per
  service (already our rule).

## 6. Boundary

Nothing here grants sensory workers access to persona, canonical memory,
native tools or JAWL policy. Sensory output stays typed observations with
provenance, delivered through the existing ambient/VoiceMem path.
