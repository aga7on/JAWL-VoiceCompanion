# Audit: Project-N-E-K-O family (2026-09-10)

Source: https://github.com/Project-N-E-K-O — a mature open companion family
(2824 stars on the core repo, Steam-distributed, CN/EN/RU docs). This is the
closest public relative to our product: a real-time companion with proactive
behaviour, screen understanding, voice, avatars and memory. Apache-2.0/MIT
code; artistic assets are proprietary.

## 1. Repository-by-repository audit

### N.E.K.O (core, Python 3.11, 513 MB, 2824 stars)
Product: "Networked Emotional Knowing Organism" — catgirl companion that
reaches out first, shares media, executes tasks. Steam version exists.

Structure (top): `brain/` (agent tooling), `memory/` (5-tier memory), `main_logic/`
(dialogue core, proactive chat, realtime voice clients), `main_routers/`
(FastAPI routers incl. live2d/memory/jukebox/pngtuber/mmd), `local_server/`,
`frontend/`, `knowledge/`, `plugin/` (SDK + plugin store), `launcher_core/`,
`steamworks/`, `specs/`.

Key subsystems (file-level, sizes are battle-tested production code):

- **memory/** — five-tier memory: working / recent / fact / reflection /
  persona. Notables: `facts.py` (293 KB), `anti_repeat.py` +
  `anti_repeat_effects.py` (~120 KB anti-repetition machinery — treats LLM
  repetition loops as a first-class failure mode), `fact_dedup.py` (70 KB),
  `hybrid_recall.py` (64 KB), `recall.py` + `recall_render.py`,
  `recent.py` (88 KB rolling), `identity.py`, `event_log.py`, `evidence*.py`,
  `outbox.py` (durable delivery), `archive_shards.py`, `embedding_worker.py`,
  `_embeddings/`, `_reflection/`, `persona/`.
- **main_logic/** — `proactive_chat/` + `proactive_delivery.py` (43 KB): the
  companion initiates contact on its own (screen events, hot topics, music,
  memes); `omni_realtime_client/` + `omni_offline_client/`: OpenAI Realtime
  (full-duplex) and offline fallback clients; `music_playback/requests`,
  `session_state.py` (34 KB), `cross_server.py` (78 KB), `agent_event_bus.py`.
- **brain/** — agent execution: `task_executor.py` (132 KB), `computer_use.py`
  (49 KB), `browser_use_adapter.py` (48 KB), `openclaw_adapter.py` (78 KB),
  `cua/`, `deduper.py`.
- **main_routers/** — `live2d_router.py` (74 KB), `memory_router.py` (87 KB),
  `jukebox_router.py` (72 KB), `pngtuber_router.py`, `mmd_router.py`,
  `galgame_router.py`, `capture_router.py`, `icebreaker_router.py`.

Verdict: reference architecture for everything we are building. Nothing to
import wholesale (Python service tied to their provider stack), but patterns
are directly reusable.

### N.E.K.O-GSV-Bridge (0.4 MB, docs-only repo)
A FastAPI wrapper for **GPT-SoVITS** TTS ("api_neko") designed to live inside
a GPT-SoVITS install: voice-config management (one .toml per character +
reference audio), **queued inference with a single worker**, **hot model
switching**, **v2 REST** and **v3 queue/WebSocket streaming** APIs, Nuxt SPA
frontend, plus an optional **Genie-TTS ONNX** backend. Both backends behind
one config switch.

Verdict: this is the missing **RU voice-cloning lane**. GPT-SoVITS does
5-second-reference RU cloning natively (our exact requirement), and the
bridge already solves queueing/streaming/voice-swap the way our worker
contract expects. Candidate to adapt as a `teratts`-style worker
(`/health` + `/tts` + streaming), giving the companion a clonable RU voice
with prosody consistent across phrases (baked per-voice model, like Tera).

### T.T.S — Talking Twin Simulator (Python, MIT, 46.8 MB)
Avatar narration without LLM: text in → Live2D avatar reads it. Custom voice
by uploading a ~5 s clean recording. Memory browser (`/memory_browser`) to
review and correct recent memories/summaries (mitigates repetition and
cognition errors), chara manager UI, Realtime-API key config.

Verdict: two reusable ideas — the **memory browser/review UI pattern** (our
Memory tab gets a review-and-correct mode) and the **5-second-reference
voice setup flow** for the companion's owner.

### N.E.K.O.-Browser (JS, MV3 extension)
Chrome/Edge extension hosting the N.E.K.O WebUI as floating window / full
transparent overlay / side panel, plus Tencent **BrowserSkill** daemon
(`ws://127.0.0.1:52800`) for browser control, cookie extraction, recording
commands. Overlay uses event pass-through on transparent areas.

Verdict: the browser-lane pattern (companion overlay on any page + a
browser-control daemon) is a good reference for our future "BrowserSkill"
lane; the overlay pass-through technique matches our OBS/desktop avatar
needs.

### N.E.K.O.-RN (TypeScript, Expo 54) + react-native-live2d + react-native-pcm-stream
React Native mobile client: Live2D Cubism 5 rendering (native OpenGL ES
module, Android+iOS), PCM audio streaming, WebSocket chat, **audio-driven
lip-sync** service. `react-native-live2d` and `react-native-pcm-stream` are
standalone npm modules (our phone-LAN presentation could embed them).

Verdict: ready building blocks for the **phone companion client** (our LAN
presentation + avatar on the phone), including lip-sync — a capability we
have only on desktop today.

### N.E.K.O.-Tauri (Rust)
Experimental desktop shell: window management, mouse click-through, native
screen capture, backend process supervision; connects to an already-running
backend on `127.0.0.1:48911` instead of owning it.

Verdict: same supervision/discovery pattern as our integrated launcher;
their "connect, don't own an external backend" rule is a nice launch
hygiene detail. Low urgency for us.

### K.U.R.O (Godot + C#, MIT code / proprietary assets)
AI-native game built FOR the companion (User&AI-friendly interfaces, NPC
dialogue, battle systems). An "activity" the companion can play/run.

Verdict: far-future idea — a playbuddy/game lane for the companion. Their
Godot AI-interfaces docs may be useful much later.

### nekodemy (docs) / neko-auth-client / patch-electron-wayland
Developer tutorials, an OAuth2+PKCE browser SDK mirror, a Wayland
shape-patch. No direct value for our stack (OAuth only matters if we ever
add accounts; Wayland is not our platform).

## 2. What we should actually take (ranked)

1. **GPT-SoVITS via the GSV-Bridge pattern** — the cheap RU voice-clone lane
   the operator asked for: 5 s reference → clonable RU voice, queued single
   worker, v3 WebSocket streaming, hot voice swap. Fits our worker contract;
   emotions stay in our WORLD2/DSP layer, timbre comes from the clone.
2. **Anti-repeat machinery** — treat LLM repetition loops as a system
   failure mode with dedicated detection/decorrelation (their ~120 KB of
   production code proves the scale of the problem; our soak harness saw the
   same failure class in the unattended runs).
3. **Memory architecture validation** — their five tiers (working / recent /
   fact / reflection / persona) match and extend our L0 sensory ring →
   L1 VoiceMem → L2 JAWL plan: add a **reflection layer** (periodic
   consolidation) and a **persona memory** (identity facts), plus an
   **outbox** pattern for durable delivery.
4. **Proactive initiation** — `proactive_chat` + bounded delivery: the
   companion starts conversations from sensory events (our sensory worker
   already produces the events; the missing piece is a bounded proactive
   policy — which is exactly JAWL heartbeat territory).
5. **Memory review UI** (from T.T.S) — review-and-correct mode for recent
   memories/summaries in the existing Memory tab.
6. **Phone client** — react-native-live2d + react-native-pcm-stream give the
   LAN phone companion (Live2D + PCM + lip-sync over WebSocket) without
   inventing mobile plumbing.
7. **Omni Realtime client** — reference implementation of an OpenAI
   Realtime-API client with an offline fallback; relevant when we choose a
   realtime-S2S provider for the duplex lane.
8. **Overlay desktop avatar** (Browser full-screen overlay with event
   pass-through) — the click-through technique for our transparent desktop
   avatar before/instead of OBS.

Not taken: brain/ agent execution (JAWL native policy/tools are stronger),
Tauri shell (we have a launcher), K.U.R.O game (far future), auth (no
accounts), Wayland patch (wrong platform).

## 3. Boundary

All borrowed patterns stay behind our existing contracts: JAWL remains the
only cognition/policy/canonical-memory owner; voice workers speak our
`/health` + `/tts` (+streaming) contract; sensory output stays typed
observations with provenance. Nothing here grants workers access to persona,
canonical memory, native tools or JAWL policy.

## 4. Operator decision + VoiceMem verification (2026-09-10)

Operator approved taking the whole take-list. VoiceMem verification before
adopting the memory items:

- **Persona memory: already present.** `voicemem/rightbrain/traits_store.py`
  v2 maintains the personality-trait cluster (claim → slot → embedding,
  5–15 claims per slot, evidence records with quote/emotion/cause) plus
  `experience_repository` and `attribution_manager`. Nothing to import.
- **Reflection layer: absent.** No periodic consolidation, compression or
  reflection pass exists (ingest → retrieve only). **We adopt the N.E.K.O
  reflection pattern**: a bounded periodic pass that compresses the recent
  sensory/conversation tier into summaries, updates facts/persona traits and
  archives the raw tier — wired as a VoiceMem-side job, with JAWL staying
  the canonical authority for anything it chooses to persist.

Adoption order (approved): (1) GPT-SoVITS worker per the GSV-Bridge pattern;
(2) VoiceMem reflection/consolidation job; (3) anti-repeat machinery;
(4) proactive initiation policy; (5) memory review UI; (6) RN phone client.
Items 4–6 wait behind 1–3 and the realtime-brain (TAARDIS) evaluation.
