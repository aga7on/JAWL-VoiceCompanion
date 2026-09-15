# Companion vision review — AGA7ON (2026-09-11, night session)

Written for the morning read. Scope: reconcile the whole repository against
the operator's product idea (a living companion-waifu that sees the desktop,
reacts to consumed content, lives in realtime, helps with projects/coding/
montage/games/reverse/streaming, talks proactively with memory, character
and traits), fix the flaws found tonight, decide the open architecture
questions, and record the research that shapes the roadmap.

## 1. What the operator asked for (verbatim intent)

- A living companion, not a chatbot: sees the desktop, reacts to content
  consumed, realtime presence, proactive conversation, memory, character.
- Help with: projects, coding, montage (DaVinci), games, reverse
  engineering, possibly streaming.
- Question asked: refactor/unify all modules into one sequential system
  without external dependencies for performance — is it worth it?
- Personality: to be defined later via **natal astrology synthesis** (do NOT
  bake traits now; keep the persona slot neutral and prepared).
- UI: rework the memory pages; an idea to merge all ports into one and move
  all settings/functions into the companion interface — final decision
  delegated to this review.

## 2. Verified performance facts (measured tonight)

| Component | Measured | Note |
|---|---|---|
| JAWL core (console+agent, fresh) | **RSS 54 MB** | idle after startup heartbeat |
| Companion (control+presentation) | **RSS 30 MB** | fresh |
| Launcher + workers (Tera CPU) | ~2.5 GB | TeraTTS worker holds the model |
| Qwen3-ASR worker (CPU) | ~1.6 GB | llama-server Q8 |
| Planner-1b (GPU1) | ~0.8 GB VRAM | gemma-3-1b via llama.cpp |
| Bonsai-27B Q1 (GPU1) | 3.8 GB weights + buffers ≈ 5.4 GB VRAM | brain+eyes candidate (keep per operator) |

**Correction of a misattributed claim:** the earlier "JAWL eats 6.8–11 GB"
measurement was wrong — that process was not the JAWL console (identified
now by port: 8770 RSS 54 MB). The operator's " JAWL ≈ 250 MB" intuition is
the right order of magnitude. **The refactor-for-performance premise is
false.** The modular system is lightweight; the real bottlenecks are the
LLM route latency and TTS/ASR throughput, not process boundaries.

Decision: **do not unify into one process.** Keep JAWL as the pinned
cognition core, Companion as transport/UI, workers as replaceable
capabilities. Continue targeted optimization (below) instead.

## 3. Flaws found and fixed tonight

1. **Emoji in speech** — sanitizer added (`strip_decorations` in `tts.py`;
   emoji/pictographs/variation selectors stripped on all TTS paths) +
   prompt rule "ЗАПРЕЩЕНО использовать эмодзи" in
   `config/jawl/prompts/custom/RESPOND_DIRECTLY.md`.
2. **Voice changed per sentence (VoxCPM zero-shot)** — root cause: each
   sentence is a separate generation and zero-shot samples a new speaker.
   Fix chosen: TeraTTSv2 (baked voice pack, one speaker by construction)
   as default; VoxCPM parked by operator decision.
3. **Whisper too slow for realtime draft** — switched live lane to
   Qwen3-ASR (RTF ≈ 0.14 vs 0.385).
4. **Music halluсinated into speech events** — SER gate added to
   `scripts/sensory_worker.py` (`SpeechEmotionGate`, DUSHA wavlm): music →
   `speech_filtered`, verified on real clips (speech→keep, music→drop).
5. **Barge-in harness undebuggable timeouts** — phase tracking + pre-quit
   failure snapshot added earlier; kept.
6. **Two GPU-model launches competing (GSQ ran 4 t/s)** — duplicate
   server occupied VRAM; after killing it 24 t/s. Recorded; monitoring
   plan: one resident model per service (already the rule; now enforced by
   measurement).

## 4. Ternary model findings (for the operator's interest)

| Model | Size | RU | Coding (our test) | Speed (our hw) | Verdict |
|---|---|---:|---|---|---|
| TAARDIS-27B V2+Doctors (1.75bpw) | 5.9 GB | **FAIL** (answers EN; garbled facts) | **0/3** (broken code) | 31–38 t/s | REJECT (RU + code) |
| GSQ-RCO IQ2_S (2.75bpw dynamic) | 9.3 GB | PASS (coherent) | not fully tested | 24 t/s gen / 19 t/s prompt | engine-slow; reference only |
| **Bonsai-27B Q1_0 + mmproj** | 3.8+0.6 GB | PASS | **3/3 PASS** (HumanEval-class, executed) | **101–104 t/s gen / 2164 t/s prompt** | **brain + eyes + local coder** |

**Night addition (late):** Bonsai Q1 solved all three HumanEval-class tasks we
threw at TAARDIS (close-elements, empty-mean fix, Pascal triangle) with
executed checks passing, at ~102 t/s — the same answers took 0.7–1.1 s per
task. So the local coding lane is covered by Bonsai as well (via the
llama.cpp OpenAI-compatible endpoint; usable by opencode today). The
"excellent local coding" claims of the ternary Qwen3.8 releases did **not**
reproduce on our hardware (TAARDIS 0/3; GSQ engine-slow in mainline).

Bonsai Q1 stays the brain per operator decision; the coding help lane uses Bonsai (fast local - 3/3 HumanEval-class PASS at ~102 t/s) through the tools the operator already runs (opencode) - see section 7.

## 5. Research findings that shape the roadmap (2026-09-11 night)

### Proactive behaviour (how and when the companion speaks first)
- **Evidence-driven gating beats LLM enthusiasm.** EOPA (arXiv 2608.04416):
  time-conditioned anchors + activity prototypes; keep interaction/silence
  statistics; online-calibrated threshold; the LLM generates the *response*
  only after the *timing* decision is made separately.
- Survey (arXiv 2609.03727): proactive decisions span silent / ask / assist
  / act; "option value of waiting"; verifiable authorization; recoverable
  execution; offline classification accuracy does not predict deployed
  value.
- Human-centred principles (Scene/Context/Human Behaviour): behavioural
  alignment, contextual sensitivity, temporal appropriateness, motivational
  calibration, agency preservation.
- Practical policy for AGA7ON (calm introvert, values silence and control):
  **default proactivity level LOW**, interactions gated by evidence +
  explicit user feedback, an always-available "тишина" control, and never
  eager LLM chatter.

### Memory consolidation ("develops and learns")
- RecMem (ACL 2026): recurrence-triggered consolidation — keep interactions
  in a cheap embedding layer; invoke the LLM only when semantically similar
  interactions recur. Up to **-87 % construction tokens** with better
  accuracy than eager systems.
- LycheeMemory V2 (arXiv 2608.12990): segment-level consolidation — batch
  exchanges, detect semantic boundaries, one LLM encoding per segment into
  typed records with provenance. SOTA LoCoMo 89.22 / LongMemEval-S 92.20.
- GAM (ACL 2026): two-phase episodic buffering → semantic consolidation on
  boundaries; dual-granularity nodes + evidence links; prevents memory
  contamination/drift.
- HeLa-Mem (ACL 2026): Hebbian association graph + reflective agent that
  distils dense hubs into semantic knowledge (reference implementation
  exists).
- Synthesis for our stack: implement the VoiceMem **reflection job** as
  segment/recurrence-triggered consolidation (NOT per-turn): recent tier →
  detect completed segments → one LLM call per segment → typed records
  (episodic summary + candidate facts + persona signals) with evidence
  links → archive raw. JAWL remains the canonical memory authority for
  anything promoted.

### Companion family audit (Project-N-E-K-O)
Already recorded in `NEKO_FAMILY_AUDIT.md`; top adoptions: GPT-SoVITS clone
lane, anti-repeat machinery, reflection layer (absent in VoiceMem —
confirmed), proactive initiation, memory review UI, RN phone client.

## 6. Architecture decisions (operator delegated)

1. **No unification refactor** — see §2. Keep the modular system.
2. **Ports/UI consolidation** — recommended, phased, not big-bang:
   - Phase 1: single **Companion origin** becomes the only user-facing
     port. A small reverse proxy inside the Companion fronts: control
     (already), presentation (already), JAWL console/API (8770), TTS/ASR
     health/status endpoints, sensory worker status/stream. Everything the
     user needs lives under one URL with one token model. Ports between
     services stay internal (loopback), nothing is exposed twice.
   - Phase 2: fold the navigation: one left nav (Обзор / Голос / Память /
     Восприятие / Доступ / Настройки), capability pages become contextual
     panels (already the documented target in TODO), memory tab gets
     **review-and-correct** mode (N.E.K.O T.T.S pattern) and the
     reflection/consolidation status.
   - Phase 3 (only after 1–2 settle): retire the standalone JAWL console
     page from the default flow (kept as an advanced/debug view).
   - Rationale: fewer ports = fewer tokens/CORS/iframe headaches (we hit
     exactly these with the browser overlay and OBS origin), one security
     boundary instead of three, and a single place for settings.
3. **Personality slot** — prepared but **empty**: no traits baked now.
   A dedicated persona config (`config/jawl/prompts/persona/*.md` slot or a
   persona JSON consumed at profile prepare) will receive the natal-chart
   synthesis when the operator provides it. Delivery style notes (calm,
   dry self-irony, honest pushback, few words) are treated as *style*, not
   identity, and only after the operator confirms.

## 7. Capability roadmap (help with projects — concrete)

| Domain | Integration | Phase |
|---|---|---|
| Coding | opencode (already used) with a local OpenAI-compatible provider (Ollama qwen3.8-27b-abliterated today; Bonsai Q1 via llama.cpp as the fast local option); JAWL native tools for repo/file ops | now (config) |
| Memory | VoiceMem reflection job (segment/recurrence-triggered, §5) + review UI | next |
| Proactivity | Gated initiative lane on JAWL heartbeat + sensory events; silence control; learned thresholds from feedback | next |
| Montage | DaVinci Resolve scripting API (`D:\Davinci Projects`): markers, cuts by transcript, subtitle import — Companion offers prepared scripts; operator approves | mid |
| Games | Sensory loop already sees the screen; add per-game "awareness profiles" (Valheim first: modding Q&A from project memory, BuildWater context) | mid |
| Reverse | HostTerminal/HostOS orchestration around the operator's tools (no automation without approval; audit trail already exists) | mid |
| Streaming | OBS lane (existing plan), stream-safe proactive filter, later: live chat reading as a separate lane | later |
| Phone | RN Live2D + PCM client (N.E.K.O building blocks) | later |

## 8. What is already accepted (no rework)

- Voice: TeraTTSv2 + WORLD2 prosody + per-sentence emotion planner (1 s/plan,
  fail-soft) — live-tested, operator accepted the world2 sound.
- Sensory: modular extractor stack (MusicState/CLAP/MobileCLIP2/SER), VLM
  on-demand (Qwen3-VL-2B or Bonsai mmproj), composer (Gemma) — proven in
  Round 4.
- Memory: JAWL canonical + VoiceMem (facts, traits, evidence) + L0 sensory
  ring — validated; reflection layer missing (scheduled).
- Safety/policy: JAWL levels 0–3, audited actions, fail-closed paths — do
  not duplicate this logic anywhere.

## 9. Morning checklist (for the operator)

1. Companion is alive at http://127.0.0.1:2367 (Tera voice + planner +
   Qwen ASR). Just talk; listen for per-sentence intonation.
2. Verify the emoji rule: ask it something playful; the spoken answer must
   contain no emoji (the chat text may still show some until the prompt
   propagates to a fresh profile — it already does via prompt sync).
3. Say a phrase with music in the background — sensory worker now filters
   music out of speech events.
4. Personality: when ready, provide the natal info; the persona slot waits.
5. Decide on the phased UI/port plan (§6.2) — nothing was restructured
   without your sign-off.
