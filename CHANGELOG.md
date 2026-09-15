# Changelog

## 2026-09-15 - U5 slice three: live reconnect drill and the rail transport fix

- Live reconnect scenario verified end-to-end: agent stop → the gateway
  reports `offline` (reconnect loop) → agent start → `connected` again in
  ~5s, with the plan journal showing the last plan completed.
- Found and fixed a shell bug on the way: CompanionGateway never exposed
  `chat_status`, so the rail's transport field always fell back to
  "starting" even while connected; the gateway now delegates to the
  responder status. Verified live before and after the drill.
- Terminal port file (62000) and the persistent socket survived both
  transitions; no companion restart was needed.

## 2026-09-15 - U5 slice one: background activity surfaces in the companion

- The terminal gateway now captures the agent's autonomous legacy broadcast
  lines (heartbeat-cycle messages that never come as typed events) into a
  bounded 20-item window, exposed through the responder/gateway chain and
  `GET /api/shell/status` as `background` (count/last_text/last_ts).
- The shell rail surfaces each new broadcast once in the chat as a «Фон»
  message, deduplicated by the broadcast timestamp; the tick rail keeps its
  phase display. Tests: legacy capture/bound, event-line isolation, the
  gateway chain; 79/79 in web+gateway, 11/11 terminal.

## 2026-09-15 - U4 slice six: integrations and secrets card

- The «Настройки» tab gains an «Интеграции и секреты» card rendering all 16
  env fields dynamically: secrets as password inputs with a "сохранено —
  введите новое" placeholder and an «установлен» badge, URL/ID fields as
  text. The hub's keep-semantics hold: an empty input for a masked secret
  never clears a stored credential (HTTP-tested: keep → replace).
- Saves merge into the same revision-guarded write; values apply after the
  agent restart, and a note documents that the launcher env may override
  them for the current launch.

## 2026-09-15 - U4 slice five: evidence lines and archive in the memory editor

- The Память tab's memory rows now show the canonical contract's provenance
  fields as an evidence line: source, confidence, revision, created_at and
  provenance (actor/day) — bounded display, skips empty parts.
- The rows gain an «В архив» action next to «Забыть» (native memory.archive
  operation); live-verified against the real memory (50 records, the
  emerald record carries confidence/revision).
- The editor itself (list/filter/search/revise/forget through the native
  JAWL memory API) already existed; this slice closes the evidence gap.

## 2026-09-15 - U4 slice four: motivation (drives) card

- The config hub now also maps the 14 drive settings keys
  (`system.db.sql.drives.*` — outside the snapshot schema, normally managed
  by the console's /api/drives form); the values live in settings.yaml, so
  the unified settings edit them with the same in-place semantics.
- The settings tab gains a «Мотивация» card: drives toggle, dynamic
  reduction, offline pause, custom-drives/reflections maxima and the
  curiosity/mastery/social triple (enabled + decay rate + interval each).
- Drive STATES (satisfaction) stay with /api/drives (SQLite). 37 settings
  scalars migrated so far. 67 tests green (hub + web).

## 2026-09-15 - U4 slice three: memory and subconscious card

- The settings tab gains a «Память и подсознание» card: vector similarity
  threshold, graph node cap, tasks/notes maxima, the hypotheses toggle,
  Tree of Thoughts (enabled/branches/simulations) and the subconscious
  switch — the same revision-guarded hub write with readback and the
  restart hint. 23 scalars migrated so far.

## 2026-09-15 - U4 slice two: tact and context card in settings

- The «Настройки» tab gains a second card («Такт и контекст»): continuous
  cycle toggle, heartbeat interval, timezone, the critical-event
  acceleration multiplier, RAG depth/vector-block caps and swarm worker
  concurrency — all through the same revision-guarded hub write with the
  readback and restart hint.
- Bounded scope: 13 core+context scalars migrated so far; the remaining
  settings groups (memory caps, ToT, subconscious, drives) follow.

## 2026-09-15 - U4 slice one: native settings tab over the config hub

- New «Настройки» tab (first unified-navigation section): edits the core
  agent scalars (agent name, main model, temperature, min call interval,
  max ReAct steps, language) through the config hub with the full U1
  semantics — revision guard, conflict UX (auto-reload on conflict),
  unknown-key notes, post-write readback and the restart-required hint.
- Settings load on tab open; reload button re-reads the revision.
- HTTP round-trip tests through a real hub (write → readback → revision
  change → conflict path). 59/59 web tests.

## 2026-09-15 - U3 slice two: redacted agent log tail in the panel

- `GET /api/logs/agent?tail=N` (session-gated): the tail of the agent's
  main.log, read from the end within a 512KB window; line-count pagination
  with a 10-line/500-line clamp; every line is secret-redacted
  (bearer tokens, api_key/token/password/secret assignments, sk-/rk-
  literals) and capped at 3000 chars.
- The Система tab gains a "Логи агента" card (refresh button, loads on tab
  open) with empty/truncated states. Launcher passes JAWL_LOG_DIR.
- 2 new tests; 57/57 green.

## 2026-09-15 - U3 slice one: light shell telemetry and the status rail

- `GET /api/shell/status` aggregates in-memory state only (agent chat
  status, attention DND/quiet hours, proactive muted/queued, resource
  profile, sensory counts, screen watcher cadence, voice lanes) — no
  network probes on the timer; heavy checks stay in the on-demand doctor.
- The topbar gains a status rail (#shell-rail): bounded 10s poll (15s while
  the tab is hidden, instant refresh on visibility), stale state shown when
  the poll fails. Missing methods on test gateways are tolerated.
- 2 new web tests; 55/55 green.

## 2026-09-15 - U2 slice one: design token layer, keyboard tabs, back/forward

- The token layer lands in the companion UI: status colors (success/warning/
  focus-ring), spacing scale, radius scale, motion durations and control
  height, with the hot rules (buttons, inputs, tab panels, focus rings)
  mapped to the variables. The mint Aero palette itself is frozen.
- Navigation core: browser back/forward now switches tabs (hashchange),
  and Alt+1..7 jumps between tabs in sidebar order.
- Docs-only per-panel changes were kept minimal; existing styles render
  unchanged (tokens mirror the current literals).

## 2026-09-15 - U1 slice one: unified config hub with revisions and secret masking

- `config_hub.py` wraps the pinned snapshot's `config_io` (the same in-place
  YAML writer, no reimplementation) and adds the U1 layer: content-hash
  revisions with conflict rejection, rotated `*.pre-save-N.bak` backups (5
  slots), secret masking on read (`__SET__` round-trips without touching
  stored values), unknown-key reporting and post-write readback.
- Endpoints: `GET /api/config-hub` and `POST /api/config-hub/save`
  (browser session + CSRF). The launcher passes `JAWL_CONFIG_DIR` /
  `JAWL_ENV_FILE` to the companion; without a config dir the hub stays off.
- Config contracts documented the same day (CONFIG_CONTRACTS.md); the hub
  implements exactly those U1 gaps. 6 hub tests + web 53/53.

## 2026-09-15 - U0 closed: live baseline and config contracts

- Live baseline captured: `docs/ui-registry/baseline/` — 11 screenshots
  (7 companion tabs + 5 console screens through the embedded iframe) with a
  manifest; the stack was restarted (the agent recovered from the morning
  `agent.stop` and is cycling again).
- `docs/ui-registry/CONFIG_CONTRACTS.md` documents the actual config
  semantics: three owners (settings.yaml / interfaces.yaml / .env), in-place
  YAML editing with exact CRLF/LF preservation, env prefix renumbering,
  drives living in SQLite via `/api/drives`, and the U1 gaps — no revision
  (last-write-wins), secrets served in plaintext, `restartRequired` always
  empty, no writer-side backups (rollback today = git + manual .bak).

## 2026-09-15 - U0 registry: machine inventory of both panels

- `docs/ui-registry/registry.json`: 213 DOM data-cfg controls of the JAWL
  console by group (system 63, host 33, web 24, telegram 17, voice 14...),
  206 schema-mapped keys, 14 unmapped (all `system.db.sql.drives.*` — the
  separate `/api/drives` writer), all 31 console endpoints with handlers,
  42 API calls in the companion UI, and the coverage diff (console.js calls
  all stay within registered routes).
- `docs/ui-registry/UI_REGISTRY.md`: human-readable registry with owners,
  verdicts (keep/merge/migrate), CRITICAL endpoint notes, the companion
  native-vs-wrapper analysis (`/api/emergency-stop*`, `/api/jawl/*`), and
  the open U0 questions (secrets readback, chat write owner, drives
  revision, list-editor contracts).
- Extraction scripts landed under `scripts/ui-registry/` for regeneration;
  docs-only change, no runtime or UI code touched.

## 2026-09-15 - Unified panel integration roadmap (docs only)

- Added U0–U6 migration plan and grouped JAWL panel parity/ownership map.
- Prioritized canonical config writes, effective state, native capabilities,
  reversible section migration and full browser/accessibility regression.
- Updated TODO/STATE; installed 19 external UX/UI skills with shared references.
- No application, protected upstream or live configuration changes.

## 2026-09-14 - Barge-in keeps the spoken beginning; the backchannel goes quiet

- The barge-in handler no longer drops the phrase start (the pre-roll and
  the pending buffer are kept) and uploads resume immediately after the
  duck fade, so a short interruption is not erased down to two words.
- The microphone gate now holds speech through clause-level dips: the
  release window grows from ~8ms to ~350ms, so quiet word tails survive.
- The backchannel («угу» after 7s of speech) is off by default and never
  fires while the answer is playing or being prepared. Live incident: the
  synthesized «угу» leaked into the open microphone and became the whole
  transcript («То есть у тебя зрение на два экрана» arrived as «Угу»).

## 2026-09-14 - Voice capture: continuous audio and session rotation at finalize

- Root cause of "said a lot, sent two words": the audio pipeline dropped
  every chunk while an answer was being prepared (the `!active.finalizing`
  gate in the worklet handler), so the continuation never reached the ASR
  buffer and only the first short phrase could be sent.
- Finalize now captures the turn ids and immediately rotates the session;
  the request carries the captured ids and audio keeps uploading into the
  fresh session (complete continuation), while the request's buffer stays
  isolated from late discards.
- The response finally no longer rotates the session and no longer resets
  the VAD while the user is mid-flow; the endpoint countdown and live
  transcript keep updating during that window.
- Known limit: the live HUD transcript comes from the streaming partial
  (rolling window, may lose the head of a long monologue); the SENT text is
  the full batch transcription of the buffered utterance.

## 2026-09-14 - Voice HUD: live transcript, send countdown and safe interjections

- The mic panel now shows the live transcript while the user speaks (draft
  poll at 300ms during speech) and an endpoint countdown ("Отправка через
  1.2 с") in the silence window, so the send timing is visible; the status
  line narrates the states (Распознаю…, Думаю…, Слушаю…).
- Interjection is now guarded: only a fresh, meaningful draft phrase may
  redirect a pending turn; noise-level re-triggers just disarm the VAD. A
  superseded request is no longer aborted — its answer still lands in the
  chat (displayed silently). Live incident fixed: a noise trigger dropped a
  prepared answer that later appeared only in the console window.

## 2026-09-14 - Sensory journal: persistent read offset

- The sensory NDJSON ingestor now persists its byte offset next to the
  journal and resumes from it after a companion restart instead of
  re-reading the whole file (36 MB after three days of events). A shrunk or
  rotated journal safely restarts from zero. Applies from the next
  companion start.

## 2026-09-14 - Turn-taking: breath-proof endpointing and live interjections

- Hands-free endpointing no longer ends a turn on the first breath: the base
  silence threshold rises to 1.4s (1.8s after a barge-in) and the semantic
  hold extends to 2.6s, engaging earlier (0.6s) so an unfinished draft keeps
  the turn open. The live draft poll runs at 600ms while streaming.
- The user can now speak while the previous answer is still being prepared:
  the pending /api/voice/end request is aborted and marked stale, and the
  resumed speech becomes the live turn (the shared ASR buffer keeps the whole
  sentence). Superseded answers settle silently.
- The server frees the utterance buffer right after capturing the WAV, before
  the (possibly slow) batch transcription, so an interjection can never lose
  its opening words to a late discard.
- Prompt rule ZZ_MEMORY_WRITES: memory facts must call
  SQLStructuredMemory.remember with its real fields (kind/subject/predicate/
  value), the skill catalog is searched at most once per cycle, and a
  "запомни" request finishes in 2-3 actions. Live acceptance had the model
  inventing `memory_key`, tripping the type guard and burning all 15 steps
  without an answer.

## 2026-09-14 - WS protocol hardening with frame-level tests

- read_frame now rejects reserved bits and validates control frames (FIN
  required, payload <= 125 bytes); a data frame while a fragmented message
  is in progress is rejected; any protocol violation closes the connection
  cleanly instead of escaping the handler thread.
- New protocol tests: fragmentation assembly, ping payload echo, close
  handshake, unmasked frames, reserved bits, fragmented and oversized
  control frames, interleaved data frames, oversized frame claims and
  invalid UTF-8 (13 WS tests total). The WS lane stays opt-in until a live
  session runs over it.

## 2026-09-14 - Voice preface follow-up: stricter gate and background level

- First voiced live test: barge-in and answer latency work, no
  self-hearing, but the preface could fire on non-screen turns and played
  like a full reply. The spoken preface now uses a dedicated narrow gate
  (explicit screen nouns only: экран/скрин/монитор/дисплей/кадр) plus a
  freshness guard (a partial older than 4.5s of silence is ignored), and
  every spoken preface is logged to voice-events.ndjson (kind
  voice_preface) for live debugging.
- The provisional phrase plays at half volume as background colour and
  never competes with the authoritative answer; barge-in still cancels it.

## 2026-09-14 - Vision back-off, VoiceMem passthrough, ASR warm-up

- ScreenDeltaWatcher: consecutive unchanged screens slow the poll cadence
  up to 4x (reset on a published change or a deferred user turn); state()
  reports idle_polls and next_wait_seconds. VLM calls were already skipped
  on an unchanged digest by VisionLookService, and the arbiter already
  defers SCREEN_DELTA polls while a user turn is active.
- VoiceMem enrichment is no longer dropped: a VOICE_TURN's memory_context
  becomes a bounded, clearly-marked background block for the responder
  (voice_memory_block, non-quotable). Finding: the canonical GigaAM path
  builds its own events, so the sidecar remains a write-only memory sink
  there; the context only flows on the VoiceMem-driven lane.
- GigaAM batch warm-up: the crispasr file mode spawns one process per final
  phrase; measured wall time swings 1.0-4.7s at ~0.6s CPU (I/O and
  scheduling bound, not compute). The companion now reads the model file
  once per session on the first audio chunk, while the user is speaking.

## 2026-09-14 - Voice preface: first audible reaction before the model answers

- `/api/voice/preface` returns a short speakable provisional line built
  without an LLM from the live ASR partial and the freshest PerceptionFusion
  observation; only screen-shaped questions qualify and the line is capped
  ("Смотрю: ..."). Verified constraint: the pinned JAWL snapshot emits one
  `assistant.final` per turn and has no delta emitters, so phrase-ready
  streaming cannot come from JAWL itself.
- The browser voice lane speaks the preface immediately after finalizing
  the utterance, in parallel with the JAWL turn; the authoritative answer
  waits (bounded at 6s) only when the preface is actually audible, then
  takes over. Barge-in cancels the preface like any speech.
- Tests: `/api/voice/preface` covers the screen-question template, the
  non-screen no-op, soft fusion failures and the browser-session gate.

## 2026-09-14 - Unified shell (JAWL tab) + faster voice lane + cold-start fixes

- Companion UI now embeds the JAWL console as a first-class "Пульт JAWL"
  tab (`/console/` reverse-proxied iframe); verified live inside the shell
  (ReAct step, wake/sleep countdown, core L3 controls reachable without a
  second window). 8770 stays the console's own port for API/config.
- WebSocket transport is ON by default (opt-out via
  `localStorage['jawl-ws']='0'`).
- Voice-lane speed: dynamic context budget trimmed 22000 -> 12000 chars
  (live agent: prompt 10506 tokens vs 15.8k before; trims sql_ticks/skills).
  Provider bench on a real 48k-char RU prompt: deepseek-v4-flash p50 2.4s /
  max 3.8s / 100% JSON-envelope compliance; glm-5.3-flash 5.1s at 67%;
  gpt-5.4-mini, gemini-3.5-flash, nemotron-3.5-lightning-free and
  mimo-v2.5-free fail on the GO plan (provider 500s / free-tier session
  required). deepseek-v4-flash confirmed as the canonical brain.
- Cold-start resilience after log/memory cleanup: VoiceMem warmup retries
  once (5s apart) and uses a 120s request timeout from the launcher;
  companion health window raised 30 -> 120 polls; companion runs with `-u`;
  launcher dumps exact companion args/env to
  `logs/integrated/companion-debug.txt`; the app appends boot markers to
  `%TEMP%\companion-boot.log` (module/main/serving).
- Live E2E after restart: "Integrated profile ready: control=2367
  presentation=8766 jawl_console=8770"; doctor: jawl connected, voicemem
  ready, asr=gigaam, tts ok, hostos live, sensory_ingest online
  (visual=8 music=7 speech=1), helper_coding/relay online; helper_planner
  intentionally offline (prosody degrades gracefully, one less dependency).
  First live turn with screen perception answered in 9.06s.
- Operational note: start the Bonsai helper (`scripts\run_coding_server.ps1`,
  8986) before the profile; with 8986 down the vision/screen-watch lane
  slows companion startup significantly. Also kill stale `voicemem_sidecar`
  leftovers and `run.lock` before relaunching after a hard stop.

## 2026-09-13 — ASR quality benchmark (GigaAM vs Qwen3-ASR) with Omni judge

- Built a 10-phrase Russian benchmark (names, numbers, dates, units,
  punctuation; TTS reference with known transcripts) and measured both
  engines plus an independent audio judge.
- Against the intent transcript, raw WER favoured Qwen (0.06 vs 0.22) only
  because GigaAM writes numbers as digits/symbols ("31", "11:45", "403",
  "5 000 ₽", "-12°C"); after number normalisation GigaAM leads
  (WER 0.079 vs 0.099, CER 0.039 vs 0.024) and has ZERO word-level
  recognition errors while Qwen produced real errors ("пизцу", "Петер",
  "всем вечером") and no punctuation/case.
- Qwen2.5-Omni-3B (local, GPU1, transformers) acted as the listening judge:
  its own ear transcriptions matched the clips (similarity 0.98-1.00 on the
  clean cases) and focused arbitration confirmed «пиццу» (Qwen error) and
  that the TTS pronounces «в семь» slurred as «всем» (Qwen transcribed the
  acoustic form, GigaAM the intent).
- Speed on the same clips: GigaAM ~0.5 s vs Qwen ~1.2 s. Verdict: GigaAM
  stays the canonical final; Qwen remains an optional word-formatter lane.

## 2026-09-13 — Qwen ASR retired; GigaAM is the only ASR backend

- Launcher `-AsrBackend gigaam` is now the default: the Qwen3-ASR
  llama-server is no longer started (its 1.4 GB RAM and CPU load are gone),
  the audio buffer for the GigaAM batch final stays; Qwen remains an
  optional fallback if its server is started manually.
- Doctor reports `asr=gigaam`; the fallback `finish()` is wrapped so a
  missing fallback server cannot break a voice turn.
- Restart hygiene lesson (recorded): a sidecar left over from a crashed
  launch holds the VoiceMem memory lock and makes every subsequent warmup
  fail with the generic `voicemem_warmup_failed`; kill `voicemem_sidecar`
  processes in the cleanup pass. (The VoiceMem mode-alias error seen during
  diagnosis was a probe artifact; mode `normal` works.)
- Verified live: no process on 8984, doctor `asr=gigaam`, end-to-end voice
  turn 8.41 s (GigaAM transcript ~0.5 s + deepseek answer) with the
  transcript `«в лукошке… «Встречаемся в полдень у Старого Дуба»»`.

## 2026-09-13 — Sber GigaAM canonical final + replay guard

- Final ASR switched to Sber GigaAM (crispasr file mode): a head-to-head on
  the same 9.6 s clip measured GigaAM at 0.58 s vs Qwen3-ASR at 1.19 s and
  more accurate Russian (correct case forms, sentence punctuation, quotes).
  The streaming bridge turned out to emit no `final` on silence and its
  partials roll (losing the head of long utterances), so finals use the
  buffered utterance via `CrispASRFileTranscriber` (`giga_final.py`);
  Qwen3-ASR stays as the fallback and its buffer is discarded without a
  second call. Live end-to-end voice turn: 5.17 s total (transcript ~0.5 s
  + agent answer ~4.5 s) versus 16-33 s before.
- Fixed a stale-replay hazard: the console journal replays on reconnect and
  a reused turn id could inherit an old `assistant.final`; the terminal
  gateway now clears the pending bucket before submitting a turn.

## 2026-09-13 — deepseek brain, fast perception draft, mid-turn context note

- Brain switched from big-pickle to `deepseek-v4-flash` (OpenCode GO
  catalog via the same relay): 15k-token cycles measured at ~2-3 s at the
  provider (big-pickle was 8-15 s); profile baseline stays
  `thinking_policy: first_step`. Live heartbeats: 3.0 s per cycle, no tool
  protocol errors.
- Fast perception draft ("VL-склейка") while the brain is busy:
  `GET /api/perception/now` returns the freshest fusion line; the UI shows
  it as a dim italic provisional message on every voice final and chat send
  and auto-replaces it when the real answer arrives (30 s safety timeout).
- Mid-turn context note: when a user message arrives while a previous
  USER_FINAL turn is still in flight, the companion prefixes the turn text
  with a bounded note so the agent knows both messages share one context
  (matches JAWL's defer/steer semantics).
- Brevity latency rule in `ZZ_COMPANION_DELIVERY.md`: inner
  observation/reasoning/reflection fields together under ~40 words per step
  (hosted completion was 300-600 tokens per turn and dominated latency).
- Load snapshot of the whole framework: ~20.3 GB RAM (Bonsai server
  ~12.5 GB, Tera 2.4 GB, Qwen-ASR 1.4 GB, JAWL agent 1.1 GB, VoiceMem
  ~1.3 GB, rest <1 GB), GPU1 7.3/16.3 GB, idle CPU ~25% of one core.

## 2026-09-13 — screen questions grounded in perception

- Fixed the "JAWL fell" screen-question path: the agent used to spend ~75 s
  hunting for a non-existent desktop-observation skill and then deny having
  screen data. Now `CompanionServer.enrich_turn_text` appends the freshest
  fused perception observation (VLM caption + window + music + speech) to
  turns that ask about the screen (chat, streaming, voice and WS paths);
  `PerceptionFusion.observe_screen` stores the latest caption for that.
- Prompt rule `ZZ_SCREEN_COMMENTARY.md`: answer screen questions only from
  perception observations, never search for observation tools, never claim a
  module is disabled; state plainly when no fresh data exists.
- Profile baseline `thinking_policy: first_step -> never` (hosted reasoning
  tokens dropped from 2419 to ~250-440 per step, cycle latency down).
- Live check: "Что сейчас происходит на экране?" answered in 33 s with a
  grounded description of the focused window and the anime frame.

## 2026-09-13 — P2 single-connection WebSocket transport

- Added `ws_server.py` (stdlib RFC 6455 server: handshake, masked client
  frames, fragmentation bounds, ping/pong/close) and the `/api/ws` endpoint
  on the control server. Actions: `chat` (deltas + final streamed over one
  socket), `voice_chunk` / `voice_end` / `voice_reset` (shared helpers with
  the HTTP voice handlers), `ping`. Auth: session cookie + origin allow-list
  at handshake. Frontend transport is opt-in via
  `localStorage['jawl-ws'] = '1'` (voice chunks + finalization switch to the
  socket; HTTP remains default). Tests: `tests/test_ws.py` 3/3; live probe
  verified handshake, pong, chat stream and voice_reset.
- Refactor: `/api/voice/audio` and `/api/voice/end` now share
  `_feed_voice_chunk` / `_finish_voice_turn` with the WS transport.

## 2026-09-13 — permanent vision, perception fusion, P1-lite/P3/P4

- Permanent perception loop: launcher `-EnableScreenWatch` (VLM watcher via
  Bonsai, companion access level 1 auto-set, correct JAWL event intake path
  auto-derived) and `-EnableSensoryWorker` (sensory worker autostart);
  `-AmbientTriageSeconds` enables the triage scheduler.
- `PerceptionFusion` (`perception_fusion.py`): screen caption + window +
  music + speech merged into one observation before the attention gate;
  `AttentionPresence.summary_composer` wires it; prompt rule
  `ZZ_SCREEN_COMMENTARY.md` asks for occasional one-sentence comments.
- `event_log.py`: bounded live operator log `runtime/voice-events.ndjson`
  (asr_final, screen_change, screen_delta, system_music/speech).
- P1-lite: `TurnArbiter` queue bounded to 8 (overflow cancels the least
  important waiter); `JawlTerminalGateway` circuit breaker (4 failures ->
  30 s cooldown) and eager connect (doctor green from startup). Tests:
  arbiter 2/2, terminal 5/5.
- P3: proactive queue persisted in `runtime/proactive-state.json` and
  replayed after restart (test in proactive 12/12).
- P4: `ZZ_ANTI_REPEAT.md` prompt rule against repeated readiness replies.
- Full regression gate after all changes: 12/12 PASS.

## 2026-09-12 — P0 terminal gateway transport (direct Companion <-> JAWL agent socket)

- Added `jawl_terminal.py`: `JawlTerminalGateway` keeps ONE persistent TCP
  connection to the JAWL agent terminal (`JAWL_GATEWAY <seq>` handshake
  with replay-from-cursor, correlated `turn_id` turns, cancel control
  line, reconnect with backoff) and `JawlChatRouter` delegates non-chat
  APIs to the console adapter. Chat turns no longer pass through the
  console HTTP bridge (kills the idle/connecting race, gap cursors and
  stuck-input failure class). Composition wires the router when both
  `--jawl-web-url` and `--jawl-port-file` are present; `server_close`
  closes the transport. Tests: `tests/test_jawl_terminal.py` 4/4.
- Profile baseline `config/jawl/settings.yaml`:
  `event_acceleration.active_cycle_policy: interrupt -> defer` so
  autonomous events queue instead of cancelling an active user turn.
- Live evidence: profile mode `jawl_terminal_gateway`, turns answered via
  the socket ("Готов.", "На связи.", 8.5–10.5 s on big-pickle). The local
  Bonsai brain experiment was rejected: its Q1 quant breaks the strict
  JSON tool protocol (`Tool protocol error`).

## 2026-09-12 — EOPA-lite proactive gating

- Proactive feed gained deterministic initiative gates: learned active
  hours from the conversation history (an hour counts when turns happened
  there on at least two distinct days, 10-minute cache), explicit
  useful/noise feedback buttons on delivered items with an exponential
  quiet window (30 min doubling up to 4 h, persisted in
  `runtime/proactive-state.json`), and 24-hour duplicate-text suppression.
  API: `POST /api/proactive/feedback`; tests proactive 11/11, test_web
  42/42.

## 2026-09-12 — single-origin console proxy

- Ф3 phase 2: the Companion reverse-proxies the JAWL console under its own
  origin (`/console/` files, `/console-api/*` -> console `/api/*`) with
  server-side token injection, on-the-fly console.js rewrite
  (`"/api/` -> `"/console-api/`), unbuffered SSE relay and session-cookie
  gating (POSTs honour the origin allow-list). UI card "Консоль JAWL"
  opens the console on the Companion origin; test_web 42/42; live console
  verified end to end through 127.0.0.1:2367.

## 2026-09-12 — sensory bridge live, phases gate, CodeSee adoption

- Ф4 closed: `SensoryIngestor` (`src/jawl_voicecompanion/sensory_ingest.py`)
  tails the sensory worker NDJSON with a persistent offset, maps changed
  screen frames / music / gated speech into bounded ambient observations
  (music dedupe, privacy filters in AmbientMemoryBuffer), and is wired
  through `--sensory-file` (launcher `-SensoryFile`, enables
  `--ambient-memory`), `/api/ambient-memory` state and the doctor
  (`sensory_ingest`). Tests 8/8; live worker run produced 7 observations
  (visual 2, music 4, speech 1, errors 0).
- Full regression gate after all phases: 12/12 steps PASS.
- CodeSee adopted (semantic feature graph): `.codesee/features.json`
  (7 epics / 18 features, validator passed), AGENTS.md integration section,
  `.agents/skills/codesee` entry; local viewer at http://localhost:5173/.

## 2026-09-12 — proactive channel v0, service visibility, coding lane, restart hygiene

- Added the Ф2 v0 proactive channel (`src/jawl_voicecompanion/proactive.py`):
  polls the JAWL chat history through the native client, seeds a baseline so
  old history never bursts, filters Companion turn echoes, gates delivery by
  conversation idle (45 s), rate limits (5 min gap, 6/hour) and a bounded
  queue; `/api/proactive` (poll + state) and `/api/proactive/settings`
  (CSRF) with a "Инициатива JAWL" UI card (silence + speak switches).
  Auto-speak is deferred until barge-in tuning. Tests: 7/7 proactive,
  test_web 41/41.
- Extended `/api/doctor` (Ф3 phase 1): streaming ASR lane state plus bounded
  fail-soft probes of the local helpers (planner 8987, coding 8986, relay
  8891) - the Doctor panel now shows every service without port juggling.
- Ф5 coding lane: `scripts/run_coding_server.ps1` (Bonsai-27B Q1 on 8986)
  and the `bonsai-local` provider registered in the operator's opencode
  config; verified online through doctor.
- Diagnosed the phantom heartbeat failures: orphaned JAWL agents
  (`jawl-sources\...\src\main.py`) survive console kills and starve the new
  launcher's heartbeat wait; the restart procedure now cleans stray agents
  and duplicate relays first. zen-session7 launched clean (READY).

## 2026-09-10 — sensory bundle gate pass, MusicState/CLAP/SER/DSP-prosody benches

- Modular sensory bundle passed the multimodal gate at integration level
  (Round 4 in `docs/MULTIMODAL_MODEL_GATE.md`): RU screen OCR ×2 exact
  (0.2–1.7 s warm on GPU1 vs 83.8 s CPU), audio→ASR→VLM binding ×2 with
  exact on-screen references (0.4 s), honest negative controls. Engine:
  Qwen3-VL-2B Q4 via llama.cpp CUDA b10883 (server load 0.18 s).
- Live sensory benches recorded in `docs/SENSORY_STACK_DESIGN.md`:
  MusicState (librosa BPM/key/energy + Basic Pitch notes, 5.1 s per 60 s),
  CLAP zero-shot tags 30 ms/chunk on GPU ("energetic dance music" + "upbeat
  male pop vocals" — correct on a live YouTube capture), MobileCLIP2-S0
  36 ms/frame CPU, DUSHA wav2vec2 RU speech emotion (neutral 0.869 on
  neutral speech, `other` 0.982 on music), Gemma composer turning structured
  facts into a natural RU description without hallucination.
- Added DSP prosody engine to `scripts/voxcpm_server.py` (additive
  `pitch`/`energy` params with speed; skipped when neutral): whisper
  roundtrip is text-identical across neutral/angry/sad envelopes.
- Added `scripts/sensory_worker.py` prototype (loopback ring + screen pHash
  + window title + music state + VAD-gated speech events as NDJSON); first
  soak found and fixed a missing `stream_callback` in the audio capture
  thread; soak verification is in progress.

## 2026-09-10 — VoxCPM launcher support, connected voice pass, clean-install slice

- Added `-TtsProvider voxcpm` (plus `-VoxCPMPort`/`-VoxCPMReferenceWav`) to
  `scripts/run_integrated_profile.ps1`: the launcher starts the VoxCPM2
  worker on GPU1 with `CUDA_VISIBLE_DEVICES=1`, reuses a healthy leftover
  worker, health-checks it next to the ASR worker and passes
  `--tts-provider voxcpm --tts-url` to the Companion. TeraTTSv2 remains the
  default provider.
- Live disposable profile (VoxCPM2 + whisper-turbo ASR + Gemma on Ollama):
  real-browser voice E2E passed 3/3 turns
  (`runtime/browser-voice-e2e-20260909-voxcpm-whisper.json`; `voice_end →
  tts_headers` 14–34 ms, `turn_to_first_audio` 15.4–26.9 s dominated by the
  JAWL/LLM route) and the real-browser barge-in passed at `gap_seconds=20`
  (`runtime/browser-barge-in-voxcpm-whisper-gap20-20260909.json`): two voice
  turns, TTS cancel during first speech, two TTS streams, 21 audio buffers,
  both transcripts matched. `gap=9` fails with whisper-turbo because the
  serial voice pipeline pauses uploads while `/api/voice/end` processes
  (~16 s); the qwen-ASR gap=9 slice remains the tighter interrupt evidence.
- Hardened `scripts/run_browser_barge_in_e2e.py` with phase tracking and a
  pre-teardown failure snapshot (`failure_phase`, `browser_state_on_failure`,
  failure screenshot) so timeouts are debuggable.
- Clean-install slice: wheel rebuilt and hash-verified against
  `dist/SHA256SUMS.txt`; release secret scan 0 findings (1198 files); fresh
  isolated venv install passed import and untruncated CLI help outside the
  source cwd; rollback-reinstall from the same wheel verified. Added
  `runtime/workers-manifest-20260909.json` with SHA-256 and licence notes for
  whisper-turbo, Qwen3-ASR, TeraTTSv2, VoxCPM2 and the Live2D Mao Pro bundle.
- Full repository gate passed after the changes: 394 non-E2E tests, 16 HTTP
  E2E tests, browser interaction at six viewports, synthetic microphone
  gate, Node mic check, PowerShell parsing (including the edited launcher)
  and `git diff --check` (exit 0). Evidence:
  `runtime/full-gate-20260910-voxcpm.log`.

## 2026-09-09 — 30-minute unattended soak pass and voice worker measurements

- Ran the corrected unattended soak harness for 30 minutes at
  `temperature=0.0`: 34/34 cycles passed with exactly one real native write
  per cycle, zero forbidden Goal actions, zero unexpected tools, zero
  idempotent no-op retries, 34/34 SHA postconditions, 34/34 native cleanups
  and unattended lease revocation. Evidence:
  `runtime/qwen-ollama-unattended-30m-v4-20260909.json`. The eight-hour
  duration claim remains open; the earlier eight-hour v4 attempt was manually
  aborted by the operator after ~12 clean minutes.
- Re-benched the VoxCPM2 native streaming worker: first-audio warm
  `0.152-0.175 s` (cold `1.5 s`), RTF `0.87`, `/cancel` stops within ~0.5 s
  with normal recovery; worker holds ~6-7 GiB of GPU1 VRAM and was stopped
  before the soak. Updated `docs/VOXCPM_INTEGRATION_20260909.md`.
- Verified the whisper-turbo ASR worker path (`-AsrBackend whisper`): RTF
  ~0.385 on an 8.8 s RU clip with an exact transcript; recorded in
  `docs/STATE.md`.

## 2026-09-09 — connected VoiceMem endpoint and barge-in acceptance

- Verified the refactor slice with the full gate: 394 non-E2E tests, 16 HTTP
  E2E tests, browser interaction, microphone gate, Node check, PowerShell
  parsing and `git diff --check` all passed (exit code 0).
- Moved CLI component construction into the explicit `composition.py` root;
  `CompanionRuntime` remains the lifecycle owner and `create_server` stays
  compatible for embedded/test callers.
- Made presentation shutdown bounded and idempotent: the runtime closes the
  server and joins its presentation thread before releasing the control plane.
- The latest eight-hour Qwen unattended run remains a negative result: it
  stopped at cycle 39 after a forbidden `GoalSkills.update_goal` call and an
  idempotent writer retry. The orchestrator cleaned the profile, ports and
  lease; no production soak pass is claimed.
- Corrected the unattended evidence gate to distinguish non-idempotent writes
  from safe retries and to reject forbidden legacy Goal actions in durable
  evidence. Focused harness tests pass; a fresh eight-hour run is required.

- Added the first unified-runtime seam, `CompanionRuntime`, for control and
  presentation lifecycle ownership with idempotent shutdown. It preserves
  JAWL as the only identity/goal/memory/native authority and leaves existing
  ASR, TTS, VoiceMem and ambient adapters replaceable.
- Fixed local VoiceMem sidecar integration: it now reuses the profile's local
  OpenAI-compatible endpoint/key and bypasses proxy variables only for
  loopback, preventing cognitive-graph memory ingest from degrading.
- Added a truthful generic provider display name for profile-selected models
  and kept JAWL context budgets below the local 16k model limit.
- Re-ran the connected Qwen profile: 3/3 browser voice turns, canonical
  memory/native/restart daily acceptance and VoiceMem `6/6` ingest completion
  passed. Real browser barge-in passed with cancellation and two playback
  buffers at gap=9.
- Bounded the barge-in harness's post-second-turn playback wait; gap=2 remains
  negative latency evidence rather than a hidden pass.
- Rebuilt the release wheel and verified its hash manifest plus a fresh target
  install/import/CLI smoke; the complete worker/model clean-install gate stays
  open.
- Added live Qwen r3 Memory-tab acceptance evidence for create/revise,
  native restart, recall and cleanup.
- Hardened the unattended soak harness to clean failed/blocked fixtures via
  native HostOS delete; the fixed Qwen rerun passed three cycles while the
  earlier missing-terminal-ledger run remains negative evidence.
- Confirmed the same three-cycle unattended acceptance through the persistent
  Ollama endpoint on `11434` with `qwen3.8-27b-abliterated:latest`; native
  postconditions, cleanup and unattended lease revocation passed.
- Added `scripts/run_long_unattended_acceptance.ps1`: an isolated,
  cleanup-verifying orchestrator for the production-duration unattended soak;
  its 90-second smoke completed 3/3. The first requested eight-hour attempt
  stopped fail-closed at cycle 11 after ten passes because the provider
  contradicted the direct Goal-v2 terminal protocol; cleanup and lease revoke
  passed, so the full-duration acceptance remains open.
- Clarified the unattended Goal-v2 objective's protocol precedence and added
  independent terminal-ledger validation; `GoalSkills.update_goal` and
  `set_current_goal` remain forbidden native paths for that disposable task.
- Added a bounded `-JawlTemperatureOverride` for disposable profiles and set
  the long-run acceptance default to `0.2`; v3 smoke passed 2/2 while keeping
  fail-closed terminal-ledger validation intact. The fresh eight-hour v3 run
  remains open; the previous v2 run stopped at cycle 5 on a nonexistent
  `GoalSkills.complete_goal` provider action and cleaned up successfully.
- Added the value-redacting `scripts/release_secret_scan.py`; the full gate now
  includes it, and the release scan passed with zero findings across 1192
  source/config/docs files. A fresh isolated venv wheel import/CLI smoke also
  passed outside the source cwd.
- Real Windows WASAPI loopback smoke passed through `pyaudiowpatch` with 93
  chunks, zero drops and no raw-media persistence; physical mic/AEC remains
  an external acceptance gate.
- Implemented the promised chat slash-command surface: local help/status/stop/
  clear/tab commands no longer create unnecessary model turns, while goal and
  unknown commands remain routed through canonical JAWL. Browser E2E now
  exercises `/help` and `/tab voice`.

## 2026-09-09 — unattended provider recovery acceptance

- Live31 passed the complete disposable provider/JAWL recovery gate after a
  durable native write: exact relay outage, same-endpoint restore, active Goal
  after JAWL restart, native SHA readback, safe reconciliation, exactly one
  non-idempotent write, cleanup and unattended lease revocation.
- The subsequent authoritative full gate passed 383 non-E2E tests, 16 HTTP
  E2E tests, six browser viewports, synthetic microphone checks, the Node mic
  check and `git diff --check`.
- Added the opt-in exact-process `--auto-stop-provider` path and the detached
  `scripts/run_provider_recovery_live.ps1` launcher. Live30-r2/r3 remain
  recorded negative safety runs where false completion was blocked.

## 2026-09-09 — operator-driven unattended provider recovery harness

- Added `scripts/run_unattended_provider_recovery.py` for the remaining P0
  provider-outage boundary. It follows the real native Goal/Heartbeat path,
  requires a durable write before the operator outage, restarts JAWL after the
  provider is restored, verifies native readback, reconciles by `(action_id,
  tool)`, proves exactly one real write, cleans up natively and revokes the
  unattended lease.
- Added regression coverage for idempotent-write evidence and ambiguous
  action-id matching. The live recovery gate was subsequently closed by
  `runtime/unattended-provider-recovery-live31-20260909.json`.

## 2026-09-09 — isolated LAN presentation authorization

- Added a separate read-only presentation token for remote avatar/OBS binds.
- Remote presentation state/config/page requests fail closed without the token;
  loopback OBS remains tokenless.
- Added regression coverage for unauthorized and authorized presentation reads.

## 2026-09-09 — streaming relay framing correction

- Fixed the disposable OpenAI-compatible relay so upstream chunked streaming
  is re-framed as downstream HTTP/1.1 chunked data. A direct loopback probe
  completed all 7 SSE events, including `[DONE]`.
- Recorded the unattended provider-recovery attempts as negative diagnostics;
  they do not change the open restart/checkpoint acceptance gate.
- Hardened the recovery harness to abort and persist a negative report when no
  durable native write is observed before the outage boundary.

## 2026-09-09 — communication-only Goal completion guard and mobile gate

- Completion evidence now excludes terminal send/read communication tools. A
  provider cannot turn a message containing `state=done` into a completed Goal
  without a successful non-communication native action.
- Added the focused regression for this false-completion path. The pinned
  snapshot digest is now
  `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.
- Fixed the mobile chat layout so the composer actions remain inside the
  viewport at 320x740 while the message list remains scrollable.
- Full gate passed: 377 Python tests, 16 HTTP E2E tests, six viewport browser
  checks, synthetic microphone, Node mic gate and diff check. At the time of
  this gate the multi-cycle live acceptance was still pending after the
  negative live21 diagnostic; it was closed by live22 below.
- Live22 then passed the first real two-cycle unattended soak after the guard:
  both cycles proved native write/read, terminal ledger, independent
  postcondition/SHA, exactly one target write, native cleanup and unattended
  lease revocation with no unexpected tools. Provider restart/failure recovery
  remains open.

## 2026-09-09 — explicit Goal `state=done` safety gate

- JAWL now treats provider-emitted Goal Protocol v2 `state=done` as an
  assertion, not proof. An active Goal must have a terminal durable ledger and
  a successful recorded action batch; otherwise it becomes `blocked`.
- The live14 disposable run verified the negative path after real native
  write/read: the local provider omitted the ledger patch and no false
  completion was accepted.
- Updated the unattended acceptance objective to require the terminal ledger
  patch and refreshed the pinned snapshot digest to the later verified
  `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.
- Fresh live15 passed one complete cycle with local Ollama: exactly one native
  write, readback, terminal ledger, direct `state=done`, postcondition and
  cleanup; the unattended lease was revoked. Multi-cycle soak remains open.
- Live16 exposed an autonomous-liveness gap: an empty non-wait provider
  response could leave an active Goal waiting until timeout. The pinned loop
  now requests at most three bounded repairs and then blocks; explicit
  `state=wait` remains the only indefinite-wait path. Eight focused policy
  tests pass. Live16 remains negative evidence, not a production pass.
- Full regression gate after the liveness fix passed 374 Python tests, 16 HTTP
  E2E tests, six browser viewports, synthetic microphone, Node mic and diff
  checks.
- Live18 passed the bounded-repair acceptance with the real local provider:
  native write/read, rejected premature completion, continuation, terminal
  ledger, postcondition and cleanup all passed; no unexpected tools were used.
- Live17 separately recorded a startup-latency negative: the provider exceeded
  the 180-second heartbeat budget, so the Companion was never exposed.

## 2026-09-09 — Live2D presentation acceptance slice

- Verified the real isolated Mao Pro renderer in a disposable Companion
  instance: asset validation, browser Live2D expression/motion/lip-sync smoke,
  presentation release profile and read-only POST boundary all passed.
- Recorded the remaining external dependency explicitly: OBS capture,
  transparent compositing, click-through, DPI/multi-monitor behavior and
  extended presentation soak are still open because OBS is not installed on
  the current target machine.

## 2026-09-09 — fail-closed Goal completion compatibility

- Added a narrow pinned-JAWL fallback for legacy empty provider envelopes after
  verified native work. It requires a terminal durable ledger, no pending
  work/next action/blocker, and successful outcomes for the complete last action
  batch; it never treats one completed tool call as `done`.
- Added three focused policy tests (6 total in the focused module) and updated
  the snapshot manifest to digest
  `89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d`.
- The live GPU1 unattended rerun remains negative because Gemma timed out after
  native write/read while the durable ledger was still `initial`; no production
  readiness claim was made.

## 2026-09-09 — native delta seam with final reconciliation

- Companion now consumes correlated `assistant.delta` events when a compatible
  JAWL build emits them, bounds/checks fragments and requires their joined
  text to match the authoritative `assistant.final` before completion.
- Provider failure or delta/final mismatch discards provisional browser text;
  provisional fragments never become speakable until the final envelope passes.
- The pinned JAWL snapshot still emits only `assistant.final`, so this is a
  forward-compatible protocol seam, not a token-level realtime acceptance.
- Full gate passed: 369 non-E2E tests, 16 HTTP E2E tests, six-view browser
  interaction, synthetic microphone, Node and diff checks.

## 2026-09-09 — gate integrity and unattended provider finding

- Full gate now passes 366 non-E2E tests, 16 HTTP E2E tests, six-view browser
  interaction, synthetic microphone, Node and diff checks.
- The unattended harness now treats a provider-reported `failed` Goal as a
  terminal observation instead of waiting through the whole timeout.
- The disposable unattended objective explicitly requires Goal Protocol v2
  `state=done` and forbids `GoalSkills.update_goal` for that acceptance task;
  the native JAWL skill remains unchanged and supported for normal goals.
- The two-cycle live6 run remains a genuine negative result: the local model
  attempted `GoalSkills.update_goal` while an action was unresolved. It is not
  counted as an unattended pass; the rerun must prove both cycles and native
  cleanup.
- A subsequent live8 disposable launch also failed closed at strict startup
  readiness because the local Gemma repeated greeting actions; no Companion
  endpoint was exposed as ready and no working profile was changed.

## 2026-09-09 — explicit disposable model override and provider gate

- Added `-JawlModelOverride` to the integrated launcher. It changes only the
  selected disposable JAWL profile through native profile configuration;
  unmanaged model edits remain fail-closed.
- Added regression coverage for the override and included the profile scripts
  in the full gate compile step.
- A live 12B-coder probe was rejected because Ollama advertised the model in
  its listing but returned `model not found` for both chat endpoints; no false
  unattended readiness was recorded.

## 2026-09-09 — bounded empty-action Goal recovery

- Pinned JAWL no longer turns an empty provider response into indefinite
  `waiting` when the active Task Ledger contains a concrete `next_action`.
  It requests at most three bounded repair cycles and then records `blocked`.
- Added regression coverage; snapshot digest is now
  `c56180641668b5cf7da70ce6d34c6f5a19ea3653399fb5fdf5a1e77d4be9fb69`.
- The earlier unattended report remains a negative pre-fix diagnostic; the
  current live functional rerun is recorded separately below.

## 2026-09-09 — unattended functional acceptance

- Fixed parsing of terminal Goal Protocol v2 metadata nested in a legacy
  `execute_skill` action; the wrapper cannot become a native tool alias.
- Live disposable acceptance passed on the current local Gemma: native ROOT
  lease, write/read, canonical Goal completion, independent marker/SHA check,
  and native cleanup. Evidence:
  `runtime/unattended-goal-soak-live4-20260909.json`.
- The 8-hour soak and crash/provider reconciliation remain open.

## 2026-09-09 — unattended Goal harness and provider finding

- Added `scripts/run_unattended_goal_soak.py` to exercise a real native ROOT
  autonomy lease, bounded heartbeat Goal cycles, journal evidence,
  postcondition verification, resource samples and cleanup. Added its compile
  and unit coverage to the full gate.
- Hardened the pinned JAWL duplicate-success guard: a repeated successful
  action batch is not treated as Goal completion or left until a long sleep;
  it records a bounded continuation and requests a fresh Goal Protocol decision.
- Full regression passed: 360 tests, 16 HTTP E2E, browser interaction,
  synthetic microphone and diff check.
- Live unattended acceptance remains open: the lease issued/revoked correctly,
  but the temporary local Gemma emitted no native action and left the Goal in
  `waiting`. Evidence: `runtime/unattended-goal-soak-live2-20260909-r2.json`.
- Pinned snapshot digest:
  `ff4efcf3cb8c9bf3f7e329aff3d939c2d83c5ba99f7378d31b07455fbdd90d05`.

## 2026-09-09 — durable native action intent before dispatch

- Pinned JAWL Goal Ledger now records native action identity as `in_flight`
  immediately before dispatch. If the process restarts before a result arrives,
  recovery marks the batch `needs_reconciliation`, stores a bounded blocker and
  exact postcondition-first next action, and never replays it automatically.
- Added explicit bounded `ledger.reconcile_actions` with `confirmed`,
  `not_applied`, and `unknown` outcomes. A Goal cannot transition to `done`
  while an uncertain native action remains, and a later postcondition probe no
  longer silently replaces the recovery obligation.
- Added regression coverage in `tests/test_jawl_goal_recovery.py`; snapshot
  verifier remains green at digest `ec765835d627431d…`.
- Recovery actions with reused local ids are now preserved by `(tool, action_id)`;
  replay of the same unresolved identity is rejected, and ambiguous
  reconciliation patches cannot update the wrong tool.
- Fresh live Goal Ledger crash-boundary acceptance passed on the updated pinned
  snapshot: `runtime/goal-reconciliation-live-20260909T024434Z.json`.
- This closes the missing checkpoint signal, not arbitrary syscall exactly-once
  semantics; live task-ledger/provider-failure reconciliation remains gated.
- Fresh live restart acceptance on the real local JAWL/Ollama route passed after
  this snapshot change: restart landed mid-flight, the native file postcondition
  survived, SHA matched, and the journal recorded exactly one actual write.
  Evidence: `runtime/restart-inference-acceptance-2026013829Z.json`.

## 2026-09-09 — lease-gated supervisor crash recovery

- Added `scripts/run_supervised_recovery_acceptance.py` as a disposable live
  proof of the native recovery boundary. With a valid ROOT autonomy lease the
  pinned supervisor restarted one killed child; after lease revocation the
  next crash became `crashed` and no third child appeared.
- Evidence: `runtime/supervised-recovery-acceptance-20260909.json`.
- This intentionally does not claim task-ledger/checkpoint reconciliation or
  arbitrary syscall exactly-once semantics; those remain the next recovery gate.

## 2026-09-09 — native supervisor lifecycle boundary

- Added opt-in `-EnableSupervisor` to the integrated launcher. The native JAWL
  `InstanceManager` and `src.instances.supervisor` own the process lifecycle;
  Companion web control only requests native desired-state transitions.
- Fixed the pinned snapshot supervisor to honor launcher-provided
  `JAWL_INSTANCES_ROOT` and `JAWL_SANDBOX_DIR`, and made supervised stop revoke
  desired running state before checking a possibly-racing PID file.
- Added bounded startup polling and exact stale `supervisor.pid/lock` cleanup,
  plus `scripts/run_supervised_profile_acceptance.py`.
- Live evidence passed startup/heartbeat readiness, intentional stop, cleanup,
  port release and registry/profile cleanup:
  `runtime/supervised-profile-acceptance-20260909-r3.json`.
- This does not yet claim active-lease crash reconciliation or long unattended
  soak.

## 2026-09-09 — integrated native profile switches

- Added `-NativeAccessLevel 0..3` and `-EnableDebugBroker` to the integrated
  launcher. The baseline remains sandbox/Debug Broker-off; explicit switches
  affect only the disposable profile and keep JAWL as the sole native executor.
- Added managed-profile override validation and regression coverage so relaunch
  does not mistake these two approved switches for an uncontrolled config edit.
- Live level-3 launcher acceptance passed the complete 93-skill 0→3 catalog
  matrix and eight native namespace probes.
- Evidence: `runtime/native-catalog-full-access-launcher-20260909-r2.json` and
  `runtime/native-namespace-full-access-launcher-20260909-r2.json`.
- Bounded browser WebAudio context resume so autoplay/headless browser quirks
  cannot hang the voice/avatar monitor; browser interaction and the complete
  full gate passed afterwards.

## 2026-09-09 — connected daily production slice

- Added `scripts/run_connected_daily_acceptance.py` as one bounded live
  acceptance across canonical JAWL memory, browser voice, native write/read,
  JAWL restart and recoverable cleanup.
- Corrected the restart readiness contract: aggregated Companion health may be
  `degraded` while optional VoiceMem/TTS adapters are disconnected; acceptance
  now requires the JAWL control plane and waits for the durable memory
  projection instead of treating normal startup races as persistence loss.
- Live pass: `runtime/connected-daily-acceptance-20260909-r3.json` with the
  linked voice evidence `runtime/connected-daily-voice-20260909-r3.json`.

## 2026-09-09 — native Full Access matrix

- Accepted the representative JAWL policy matrix for levels 0–3 using native
  HostOS routes, including level-3 write, emergency-stop/reset and bounded
  ROOT autonomy lease issue/revoke.
- Enabled Debug Broker only in the disposable acceptance profile and verified
  the native 93-skill catalog plus read-only HostOS/HostTerminal/DebugBroker
  probes. The production/default profile remains explicit about optional RE
  provider enablement.
- Evidence: `runtime/native-policy-levels-0-2-20260909.json`,
  `runtime/native-policy-level-3-20260909.json`,
  `runtime/native-catalog-matrix-full-access-20260909-r2.json` and
  `runtime/native-namespace-full-access-20260909-r2.json`.

## 2026-09-09 — local provider compatibility and GPU1 live gate

- Added bounded normalization for the legacy `execute_skill` wrapper when a
  local model places a valid Goal-v2 envelope inside `actions[]`. It unwraps
  only an unambiguous payload; unknown names such as `SQLTasks.*` still go
  through the normal registry/policy rejection path.
- Updated the owned snapshot manifest to digest
  `54648188b51153c9bb3e9e60b572026e152a4f08c199c0015a39cdff4b879ef6` and
  added regression coverage for both accepted and rejected forms.
- Repeated the real integrated profile on physical GPU1 with Qwen ASR,
  TeraTTS and VoiceMem: browser voice 3/3 passed; no stale `execute_skill`
  warning appeared. This does not close the broader production gates.

## 2026-09-09 — connected voice owner correction and VoxCPM2 opt-in

- Fixed a real browser voice defect where `stopMicrophone()` invoked the
  speech owner twice for one final response. The second invocation cancelled
  the first TTS stream and could leave playback silent or abruptly cut.
- Re-ran the integrated local profile through ASR → JAWL → TeraTTS → browser
  playback/avatar: 3/3 Russian turns passed after the fix. Evidence:
  `runtime/browser-voice-e2e-20260909-r2.json`.
- Changed the integrated launcher default ASR from the slower local Whisper
  wrapper to the accepted Qwen3-ASR-0.6B CPU llama-server profile. Whisper
  remains an explicit `-AsrBackend whisper` fallback. The fresh 3/3 browser
  run reduced first-buffer wall time to 9.7–24.9 s; this is still not a
  realtime SLO because JAWL/LLM completion dominates the tail.
- Added optional VoxCPM2 native streaming/cancel backend; TeraTTSv2 remains
  the default. See `docs/VOXCPM_INTEGRATION_20260909.md`.

## 2026-09-07 — restart-during-inference gate and duplicate-success ReAct guard

- Added the strict restart-during-active-native-inference harness
  (`scripts/run_restart_inference_acceptance.py`): turn A native
  write+read, managed `/api/jawl/restart` landed mid-flight, turn B must
  report unforgeable on-disk evidence (SHA-256 compared against the file).
- Fixed a reproduced ReAct budget-exhaustion defect in the owned snapshot:
  a provider that re-sends the same successful terminal-delivery batch now
  triggers a duplicate-success guard that concludes the cycle without
  re-execution (`l3_agent/react/loop.py`, snapshot digest `403420ad…`).
- Updated the integrated launcher readiness marker to accept the guard's
  legitimate cycle conclusion alongside the empty-actions conclusion.
- Restored `jawl-gemma4-it` as `main_model` in `config/jawl/settings.yaml`
  after the coder model failed honest post-restart inspection twice
  (fabricated SHA-256 and history-derived answers against a real on-disk
  postcondition probe).
- Established live facts: the uncertain native side effect is durable across
  a mid-flight managed restart (on-disk marker verified twice); restart
  readiness reports `agent_ready` after memory projections; the strict gate
  remains open pending a provider/model that verifies resources instead of
  trusting conversation history.

## 2026-09-07 — browser barge-in gate correction

- Unified browser barge-in detection with the calibrated microphone gate and
  added E2E observability for the interruption timestamp.
- Strict live synthetic acceptance remains open: the prior run cancelled only
  after the first playback window, so it is not represented as a production
  pass. No JAWL-Coding, VoiceMem, or RE files were modified.
- A fresh integrated-profile run now passes the strict browser barge-in gate:
  playback had started before cancellation, the replacement voice turn
  completed, and transcript markers matched. Evidence:
  `runtime/browser-barge-in-20260907-strict-retry3-gap9.json`.
- Companion restart soak passed 3/3 graceful cycles with no forced stop or port
  leak; managed JAWL/provider recovery remains a separate gate.
- Durable JAWL action journal now records the existing bounded
  `companion_turn_id`; a fresh browser voice→native run proved correlation,
  native write/read/postcondition and recoverable native cleanup.

## 2026-09-07 — bounded speech playback buffer

- Added a small bounded WebAudio jitter-buffer to the simulated JSON-response
  speech path. It absorbs TTS timing jitter while keeping the unsaid playback
  tail below roughly 850 ms and remains cancellable by barge-in.
- Mic gate and web/gateway regression: 50 tests plus 4 subtests passed;
  synthetic gate check passed. Clean live acceptance is still needed for
  first-audio and interruption timing.

- Managed profiles now provision the verified ONNX embedding asset into their
  own `data/vector/embeddings` tree; fresh profile preflight no longer fails
  because only the legacy daily profile had the model cache.
- Launcher optional environment variables are now skipped when unset instead
  of aborting startup. Fresh integrated profile with JAWL, Companion, Qwen
  ASR, TeraTTS and VoiceMem reached readiness and exited cleanly.

## 2026-09-06 — native cancellation and SQLite live correction

- Added WAL and a bounded SQLite busy timeout to the owned pinned JAWL runtime;
  refreshed its source manifest and verified the reproducible snapshot.
- Serialized Companion native turns so cancellation cleanup completes before a
  replacement native cycle begins.
- A fresh live concurrent-turn acceptance now proves barge-in cancellation and
  normal completion of the replacement turn without a new SQLite lock. Evidence:
  `runtime/interrupt-acceptance-20260906.json`.
- The disconnected Ollama run remains provider-failure evidence, not a product
  pass; full restart, task-recovery, voice-to-native and production acceptance
  remain open.
- Added a validated launcher `ProfileName` selector for isolated JAWL profiles.
  A clean-profile voice probe reached native write/read successfully, but its
  exact transcript/target acceptance remains open because the synthetic command
  was distorted and an older disposable file was also inspected.
- Repeated the probe in a genuinely empty profile with a short Russian command:
  connected browser voice caused native JAWL write→read of exact `готово`, and
  native cleanup quarantined the target. Evidence:
  `runtime/voice-native-strict-acceptance-20260906.json`.
- Corrected JAWL action resource locking/observability for logical
  `sandbox/...` paths so the injected profile sandbox is recorded instead of
  the pinned-source cwd; refreshed the reproducible snapshot manifest.
- Fresh isolated native acceptance confirms the journal records the profile
  sandbox and native cleanup removes the target. Evidence:
  `runtime/resource-key-acceptance-20260906.json`.
- Full regression gate now uses an isolated JAWL profile for fallback logging;
  it no longer dirties the pinned source snapshot.
- Added bounded correlation propagation across browser voice/chat transport,
  Companion gateway state, and native JAWL turn submission, with regression
  coverage. A connected journal-level acceptance remains pending.
- A live attempt with the current local Gemma baseline was rejected after an
  invalid-response retry and missing terminal voice response; no false pass or
  correlation evidence was recorded.
- Local 12B provider probes return valid JSON directly, but the clean JAWL
  startup probe stalls in its first 8.3k-token ReAct request; recorded as a
  bounded provider/startup failure, with no acceptance claim.

## 2026-09-06 — connected voice gate correction

- Integrated profile now fails fast when `-StartLocalAudio` is used without
  `-UseVoiceMem`, avoiding a silent 503 on every audio chunk.
- With both flags enabled, fresh browser acceptance passed 3/3 Russian turns
  through capture/gate, Qwen3-ASR, JAWL, TeraTTS and playback/avatar. This is
  synthetic voice evidence only; memory restart, native action and interruption
  remain open.

## 2026-09-06 — connected gateway verification

- Imported `jawl-gemma4-it` as a disposable local diagnostic baseline. Minimal text
  generation works, but direct `tool_choice=required` produced no OpenAI tool call;
  no connected native-turn acceptance was recorded. The temporary GPU1 Ollama
  probe was cleaned up; GPU1-only affinity remains unverified because the backend
  still used GPU0. Confirmed JAWL port `8770` closed; FoxMCP `8765` was not changed.
- Added the Companion delivery prompt override; a real connected local Gemma text
  turn now produced one terminal delivery and a `delta`/`final` response in ~12 s.
- Fixed named-profile logical sandbox path resolution in the owned JAWL snapshot.
  Connected native E2E then created, read, hashed, and quarantined a disposable
  `sandbox/native-proof.txt` via JAWL tools at policy level 0.
- Follow-up ASR evidence corrected the synthetic-voice status: the Tera
  reference transcribes, but all three regenerated synthetic question WAVs are
  empty to Qwen3-ASR. Peak normalization fixed level only, not intelligibility;
  browser voice remains an explicit open acceptance item. Temporary diagnostic
  port `8985` and managed ports `8770/2367/8766/8984/9889` were closed.
- Corrected Windows PowerShell UTF-8 JSON serialization in the synthetic Tera
  runner. All three Russian fixtures now transcribe (`35/55/53` chars), and a
  real browser voice E2E passed all three capture→ASR→JAWL→TTS→playback/avatar
  turns. The old empty-transcript result is retained only as historical evidence.
- Strengthened browser acceptance with semantic Russian expectations and added
  transcript text to local evidence. The fake capture tail currently repeats a
  short prefix; this is recorded as an open harness artifact, not silently
  counted as interruption/duplicate-free production proof.

- Isolated profile на `2368/8767` стартовал с pinned JAWL и `big-pickle`; OpenCode
  Zen подтвердил endpoint/model discovery, но startup и user turns получили
  HTTP 429 `FreeUsageLimitError`. Секрет не записан, live acceptance не засчитан.
- Исправлен bounded-stream cursor gap: история, вытесненная до подключения, больше не блокирует новый correlated Companion turn.
- Добавлена regression-проверка начального `gap=true`; native gateway suite: 4 passed, HostOS control E2E: passed.
- Реальный headless Live2D smoke прошёл на presentation `8766` с локальными Pixi/Cubism assets (`ready=true`, expressions/motions/lip-sync on).
- Connected UI→JAWL acceptance выявила реальный blocker: JAWL process занят старым бесконечным ReAct turn и не выпускает final event. Это записано как незавершённая интеграционная проблема, а не засчитано как успех.
- Native gateway теперь best-effort отменяет свой correlated turn при terminal timeout, чтобы Companion не оставлял stale ReAct работу после отказа UI; добавлен тест timeout→cancel.
- Integrated launcher теперь не вызывает duplicate agent start, запускает JAWL из isolated profile home и передаёт `PYTHONDONTWRITEBYTECODE`; prompt dumps направляются в profile logs. Boot→shutdown smoke сохранил snapshot verifier зелёным (`fd1bb8…`).
- После этих правок полный gate `runtime/full-gate-20260906T081224Z.*` снова завершился с exit code 0: 331 non-E2E, 16 HTTP E2E и browser responsive checks. Synthetic ASR negative fixture остаётся честно помеченным failed/accepted-empty, provider/live voice acceptance не засчитаны.
- После добавления profile tests финальный gate `runtime/full-gate-20260906T081634Z.*` также завершился с exit code 0; snapshot verifier и managed preflight после него зелёные.
- Реальные loopback-профили TeraTTSv2 и Qwen3-ASR-0.6B прошли на синтетических русских данных: TTS 3/3 (median RTF 0.215), ASR 3/3 (median RTF 0.124; cold 1.997 s). Отчёты: `runtime/live-teratts-20260906.json`, `runtime/live-asr-20260906.json`.
- Исправлен production-ошибочный маршрут AudioWorklet: `/mic-processor.js` теперь безопасно обслуживается Companion HTTP server. Реальный Edge smoke подтвердил `Microphone listening`; web suite: 36 passed.
- Обязательный полный gate после web-изменения `runtime/full-gate-20260906T082927Z.*` завершился с exit code 0.
- Новый полный mock/regression gate `runtime/full-gate-20260906T075243Z.*` прошёл с exit code 0: 16 HTTP E2E, browser interaction E2E и responsive viewport checks.
- Полный gate после ScreenDelta IPC race и честного TXT/MD attachment filter
  прошёл: `runtime/full-gate-20260906T084311Z.*`, exit code 0.
- Повторный полный gate после provider-config update на `big-pickle` прошёл:
  `runtime/full-gate-20260906T085413Z.*`, exit code 0.
- После connected/diagnostic runs verifier обнаружил и удалил только generated
  `logs/*.log` и `__pycache__/*.pyc` из pinned snapshot; manifest/digest снова
  валидны. Это зафиксировано как immutable-source incident, не как изменение JAWL.
- Исправлен integrated browser-voice launcher: он теперь передаёт обязательные
  `--expected` для каждого WAV; пустой default проверяет только непустую ASR,
  а семантический transcript acceptance задаётся явно.
- Исправлена гонка ScreenDeltaWatcher: IPC-файл записывается до публикации события
  в наблюдаемую очередь; targeted screen/event regression — 8 passed.
- До выбора Vision/multimodal handlers attachment picker честно ограничен TXT/MD;
  UI больше не заявляет неподдерживаемые PDF/изображения/аудио/видео.

## 2026-09-06 — R1: воспроизводимость owned JAWL runtime

- Убран искусственный глобальный HostOS blocklist из owned JAWL snapshot;
  доступ по-прежнему определяется штатной JAWL policy 0–3.
- Удалён повреждённый context patch; восстановлены канонические adaptive
  context rules и `SkillCatalog` discovery.
- Создан pinned snapshot `jawl-20260906-daily-v2` (348 файлов), добавлена
  проверка отсутствия лишних файлов в manifest.
- `prepare_daily_profile.py` различает managed/user overrides, делает sync с
  backup и создаёт отдельные `data/logs/cache/sandbox`.
- Live voice, semantic memory recall, реальное native поручение и Live2D
  остаются открытыми P0/P1; зелёный unit/mock gate их не закрывает.
- После исправления запуска full gate повторно прошёл:
  `runtime/full-gate-20260906T071915Z.*`, exit code 0; полный e2e отдельно
  также прошёл 16/16 за 65 с. Предыдущий 071414Z был флейком HTTP fixture
  (503 при полном порядке), что зафиксировано как отдельный риск.
- Внешний `mao_pro.model3.json` прошёл проверку ссылок (8 expressions,
  motions, physics/pose/display info), но рядом нет совместимого
  `Live2DCompanionRuntime` adapter; поэтому production Live2D пока честно
  остаётся pending, CSS fallback не переименован в готовый персонаж.
- Добавлена атомарная запись managed-профиля и проверка, что в pinned snapshot
  не появляются файлы вне manifest; отдельный regression test это подтверждает.
- В presentation-контур добавлены локальные PixiJS/Cubism 4 runtime assets и
  небольшой `Live2DCompanionRuntime` adapter. Реальный headless browser smoke
  подтвердил загрузку Mao, центрирование и capabilities `e/m/l`; evidence —
  `runtime/live2d-smoke.png`. Полный OBS/DPI/soak и финальный лицензированный
  персонаж ещё не приняты.
- Добавлен воспроизводимый `scripts/run_live2d_smoke.py`; отдельный прогон с
  временным presentation server прошёл (`Live2D e:on m:on l:on`).

## 2026-09-06 — корректировка пути после текущего аудита (historical)

- Добавлен `docs/RECOVERY_PLAN.md`: подтверждённые регрессии, очередь R1–R4,
  доказательства приёмки и готовая формулировка goal.
- STATE, TODO и HANDOFF приведены к текущему состоянию: один gateway turn
  остаётся частичным evidence; пять recall attempts failed, voice/поручение
  как один сценарий ещё не приняты. Прежняя хронология сохранена в Git.
- Зафиксировано обязательное восстановление native discovery/HostOS через
  JAWL policy, исправление corrupt patch и доставки managed config/prompt.
- Исправлена трактовка исторического 503: ошибка level=3 не объясняется
  отдельным intentional emergency-stop fixture.
- Историческая запись о незарегистрированном goal относится к предыдущему
  проходу и не описывает текущий активный goal.

Записи ниже описывают исторические срезы и прежние оценки; текущий статус
задают STATE и RECOVERY_PLAN. «Accepted turn» не означает приёмку приложения.

## 2026-09-06 (night: first accepted live user turn)

- **Accepted connected-turn milestone:** one `--turns 1` run against owned JAWL
  (LM Studio `ea07de5...:2`, 64k context) reports `pass:true`, `completed_turns:1`,
  `assistant.final:1` in ~48 s; the agent answered via the terminal interface and
  saved a `SQLNotes.update_note` before requesting cycle termination.
  Evidence: `runtime/daily-live-64k.json` (plus failing probes
  `daily-live-one-turn.json`, `daily-live-greeting.json`,
  `daily-live-bounded.json`, `daily-live-budget*.json`).
- Root blocker found and fixed: LM Studio loaded the model with `n_ctx 15872`,
  while JAWL prompts inflate to 16–35k → HTTP 400 `exceed_context_size_error`
  (then `provider returned an empty final answer`). Fix: reload via
  `lms load ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d --context-length 65536 --yes`;
  the served identifier became `ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d:2` and
  `config/jawl/settings.yaml` now targets it.
- Companion hardening (owned profile): `system.context_depth.budget` on with
  `skill_policy: adaptive`, `max_react_steps: 8`, `goal_mode: false`, new owned
  directive `config/jawl/prompts/custom/RESPOND_DIRECTLY.md` (seeded by
  `scripts/prepare_daily_profile.py`), and snapshot patch
  `scripts/patches/jawl-context-budget-companion.patch` stopping self-discovery
  of the host tool catalog (no omitted namespace index; `SkillCatalog` not in
  adaptive base prefixes). Combined with the earlier
  `scripts/patches/llm-openai-compatible-response-format.patch`
  (`LLM_RESPONSE_FORMAT=text`), owned JAWL now reaches the local LLM correctly.
- Keep-away helper created then removed (owner at the PC); no power/display
  settings are modified by project tooling (screen offs were Windows display
  idle timeouts during long waits).

- Owner provided an LM Studio API key for `http://127.0.0.1:1235/v1`; the server
  accepts it and serves one loaded model (id `ea07de5ddbf7bac67aee9db5d525e9ea830e9e0d`,
  listed via `/v1/models`, minimal chat completion verified). The key is used
  only through the process environment (`LLM_API_KEY_1`) and never committed.
- Owned daily baseline now points at the local provider: `config/jawl/settings.yaml`
  sets `llm.main_model` to the LM Studio model id; prepared profile and preflight
  pass (`embedding_cache=ready`).
- LM Studio rejects JAWL's `response_format={"type":"json_object"}` with HTTP 400
  (only `json_schema`/`text` are accepted). Recorded the guarded provider patch
  `scripts/patches/llm-openai-compatible-response-format.patch`: `_request_kwargs`
  now honours `LLM_RESPONSE_FORMAT` (default `json_object` for cloud; set `text`
  for LM Studio), applied to the owned snapshot
  `runtime/jawl-sources/jawl-20260905-daily-v1`.
- With the patch, owned JAWL reaches LM Studio and executes real native tool
  calls (read terminal history, list notes, sandbox search). It still fails the
  connected daily scenario acceptance: the model enters a prolonged ReAct tool
  loop and no turn produced a final answer within 180–420 s (18 tool completed
  events on a single `--turns 1` run). Live evidence:
  `runtime/daily-live-one-turn.json`, `runtime/daily-live-greeting.json`.
- Two P0 follow-ups identified: (1) bound/simplify the tool catalog so a single
  user turn cannot stall in a tool loop (the documented P0 contract issue), and
  (2) the daily launcher runs with the pinned-source cwd, so `sandbox/` relative
  tool paths resolve to the source sandbox instead of `runtime/instances/daily/sandbox`
  and the model's repeated sandbox searches fail; switch the launcher working
  directory to the instance home (or canonicalize sandbox paths).
- Ollama `127.0.0.1:11434` (no auth, `gemma-4-12b-obliterated:latest`) remains a
  fallback endpoint candidate, not yet tried for a user turn.

- Synthetic voice robustness slice (P0-C foundation): `ASRNoSpeech` now
  distinguishes "no speech" from transport failure in the final-utterance ASR
  worker, produced as a benign `no_speech` finish outcome and a neutral
  `transcript: ""` at `/api/voice/end`. `ExternalASRService` gained an injectable
  `clock` so TTL/disconnect behavior is testable offline.
- Added `scripts/make_synthetic_audio_cases.py`: deterministic stdlib generator
  that derives tempo-slow, paused, quiet/faint, noisy, phrase-end and
  consecutive-phrase variants from one clean PCM16 WAV plus a `cases.json`
  manifest with per-file `must_transcribe`/`min_chars` expectations. Unit tests
  in `tests/test_synthetic_audio_cases.py` (12 cases, bit-identical across
  seeds).
- `scripts/run_asr_profile.py` gained `--expects`: it now loads the generated
  manifest and fails only when required speech is missing, while tolerated
  no-speech inputs (noise floor, faint speech, 0 dB SNR) still count as covered.
  Profile schema bumped to v2; report schema expanded with per-sample
  `accepted`/`accepted_empty`.
- `scripts/check_mic_gate.mjs` now also verifies browser upload backpressure:
  `queueVoiceChunk` refuses chunks beyond `MAX_PENDING_AUDIO_CHUNKS` (8),
  reserves slots only on accept and surfaces drops in the mic status line.
- Added `scripts/run_synthetic_cases_live.ps1`: synthesizes one Russian utterance
  through TeraTTSv2, builds the synthetic case matrix and profiles it against the
  local Qwen3-ASR-0.6B llama-server.
- Full regression: 345 ordinary pytest tests + 28 subtests pass; synthetic Mic
  gate (Node) and diff check pass. Live ASR acceptance of the generated matrix
  remains pending an ASR worker run.
- Provider reality check: local LM Studio server on `127.0.0.1:1235` requires an
  API key (401 on Bearer probe) and is not usable without an owner-provided key;
  Ollama on `127.0.0.1:11434` is reachable without auth with
  `gemma-4-12b-obliterated:latest` available. No provider run is claimed.

- Clarified canonical JAWL memory versus VoiceMem layers and marked live voice
  parity as half-duplex until interruption E2E passes.
- Browser voice E2E obtains CSRF inside its async turn and permits 180 seconds
  for slow local CPU turns. The latest run still failed at Selenium's
  120-second HTTP read boundary while OpenCode was timing out; no three-turn
  pass is claimed.
- Full regression capture `runtime/full-gate-20260905T212025Z.json` passed:
  308 ordinary tests, 16 HTTP E2E tests, browser interaction, synthetic mic,
  Node checks and diff check.

## Unreleased

Added a six-point UI acceptance audit in `docs/UI_ACCEPTANCE.md`; corrected
the distinction between implemented controls and accepted user workflows.
Responsive navigation and a compact mobile companion keep chat usable from
320px through desktop widths. Browser checks cover six tabs at six sizes.
Speech lamps now follow audio amplitude/gate, not text arrival; browser
synthetic tone/silence check passed. Physical tablet/keyboard/microphone
acceptance remains pending.

Added explicit LAN access documentation and tests: opt-in private-network bind,
HTTPS certificate/key, Basic Auth, session/CSRF/origin checks, and read-only
presentation separation. The post-change full gate is
`runtime/full-gate-20260905T201952Z.json` (308 non-E2E and 16 HTTP E2E tests,
exit code 0).

Expanded the memory surface into a library with fact/trait/evidence/episode
filters, search, edit and forget actions through the JAWL memory API. The
follow-up full gate is `runtime/full-gate-20260905T202641Z.json` (308 non-E2E
and 16 HTTP E2E tests, exit code 0); live recall after restart is still open.

Added the guarded browser voice E2E driver `scripts/run_browser_voice_e2e.py`.
It is ready to exercise three synthetic WAVs through browser-origin ASR,
Companion/JAWL, TTS and actual browser playback once a live profile is
configured; it refuses without `--live` and does not start a mock server.

Wired the browser voice driver into the local integrated launcher through
`-RunBrowserVoiceE2E`; the separate owned local lifecycle was verified with a
startup-only report. The follow-up full gate is
`runtime/full-gate-20260905T204225Z.json` (308 non-E2E and 16 HTTP E2E tests,
exit code 0). The real three-question local model run remains pending.

Added a live synthetic Russian audio chain check: TeraTTSv2 generates three
utterances and local Qwen3-ASR-0.6B transcribes them on CPU. Evidence is
`runtime/synthetic-questions-profile.json` (passed, median RTF 0.111). This is
not full browser/JAWL/LLM/playback acceptance.

The audio pipeline profile now records a correlation ID and per-stage timing
fields for session bootstrap, ASR upload, final response, and TTS completion.

Refreshed the full gate after the current UI changes; the accepted artifact is
`runtime/full-gate-20260905T195638Z.json` with exit code 0 (303 non-E2E tests
and 16 HTTP E2E tests, plus auxiliary checks).

Verified the owned JAWL runtime preflight: embedding cache is ready and no
runtime components are missing. Live-provider acceptance remains pending
because `LLM_API_KEY_1` is not configured; no credential was persisted.

Probed the configured OpenCode Zen catalog successfully (HTTP 200); recorded
`big-pickle` and `deepseek-v4-flash-free` as available candidates. No
authenticated request was made without the process-local credential.

Refined the web panel around a chat-first overview: removed duplicate avatar
actions, added attachment/emoji/slash/microphone controls, persisted the
microphone selector, and moved vision/initiative controls into System. TXT/MD
attachments now enter the actual text request; unsupported binary media is
reported explicitly. Browser render smoke evidence is saved under
`runtime/browser-evidence/20260905T195242Z/`; browser interaction E2E passed
in explicit mock-brain mode with screenshot evidence under
`runtime/browser-evidence/interaction/`. These checks do not claim live
provider acceptance.

Added a Selenium-based browser interaction E2E harness with screenshot
evidence; it exercises gate persistence and chat rendering in explicit
mock-brain mode and does not claim live-provider acceptance.

Refreshed the full gate after Qwen/local VoiceMem integration changes; saved
accepted evidence at `runtime/full-gate-20260905T170157Z.json` with exit code 0.

Fixed the integrated launcher so the JAWL provider credential crosses the
process boundary only via environment and is never included in arguments or
logs.

Added local integrated profile support for Gemma GGUF, VoiceMem and local audio
workers; captured the first real local ASR -> JAWL -> TTS response and recorded
the interrupted slow-turn limitation.

Tested Qwen3-VL-2B in text-only mode; its real JAWL heartbeat produced valid
terminal JSON. Documented Gemma tool-JSON incompatibility and unsupported
ternary Bonsai GGUF format.

Web and local E2E regression after the loopback token change passed 52 tests;
the full gate refresh remains pending.

Loopback JAWL integration now avoids generating tokens that could enter console
logs; Companion accepts an empty token only for loopback URLs and retains token
requirements for non-loopback control.

Ran the real local TeraTTSv2 CPU worker against three Russian texts; saved
`runtime/tera-live-profile.json` with median RTF 0.162 and p95 complete
response time 0.589 s. Streaming and full-pipeline acceptance remain open.

Browser render smoke now persists control and avatar PNG evidence under
`runtime/browser-evidence/`; the latest Edge evidence is `20260905T154359Z`.

The integrated launcher now checks for `LLM_API_KEY_1` before JAWL process
creation, preventing a half-started profile when live provider configuration is
incomplete. No credentials are persisted.

The integrated launcher now checks JAWL agent status during startup and reports
provider initialization failure directly. Current live configuration stops at
the explicit missing `LLM_API_KEY_1` requirement; no secrets are persisted.

The compatible capture wrapper now publishes accepted full-gate evidence at
`runtime/full-gate-20260905T183500Z.json` with exit code 0.

### 2026-09-05 — reproducible daily JAWL profile

- Added an idempotent profile preparer for pinned prompt assets, owned SOUL,
  config, and isolated runtime directories; it does not overwrite user state.
- Added `scripts/run_daily_profile.ps1` for the separate JAWL console on 8770;
  Companion control remains 2367. It inherits provider credentials only; no
  secrets are stored or printed.
- Verified profile preparation and the owned runtime import graph. Live
  provider, browser E2E, and full daily-scenario acceptance remain open.
- A process-level startup smoke reached SQL/vector initialization but required
  a longer first-run embedding download; this is tracked as a readiness and
  warm-cache task, not counted as live acceptance.
- Warm-cache process smoke subsequently reached full JAWL startup and graceful
  shutdown/PID cleanup. Added fail-fast embedding-cache preflight and coverage
  for missing/ready cache states.
- The latest full gate passed 301 non-E2E and 16 HTTP E2E tests. A wrapper
  timestamp incompatibility prevented publishing a new metadata artifact; the
  existing saved gate remains unchanged until the capture command is corrected.

### 2026-09-05 — owned JAWL source snapshot

- Added opt-in source staging with per-file hashes, no-overwrite behavior,
  working state/persona exclusions and bounded source selection. Staged 348
  files under owned runtime; all hashes and copied Python syntax verified.
- Two packaging fixture tests passed. Runtime config/environment, dependency
  lock and launcher integration remain pending; no native agent was started.

### 2026-09-05 — native runtime dependency inventory

- Mapped required native routes to JAWL modules, recorded reference HEAD,
  root MIT license and selected source hashes. Identified shared dotenv and
  working-config/prompt bootstrap behavior that separate data paths do not isolate.
- Independent source packaging and launcher integration remain pending.

### 2026-09-05 — JAWL dependency profile correction

- Added an owned runtime requirements profile resolving the upstream aiogram
  3.17/Pydantic 2.11 incompatibility while preserving optional adapters.
- Installed the owned Python 3.11 environment with Kuzu and an exact readable
  version lock; `pip check` passes. Import/readiness validation remains pending.

### 2026-09-05 — connected daily scenario as the next goal

- Prioritized one launch profile and browser voice → JAWL → memory → native
  task → verified result → restart/recall, with explicit acceptance criteria.
- Removed duplicate pending ambient segmentation work, separated saved gate
  success from unresolved HTTP 503 investigation, and corrected stale STATE
  claims about delegation and ambient implementation. Runtime unchanged.

### 2026-09-05 — reproducible runtime manifest and full gate

- Added a secret-free versioned runtime profile example and bounded validator
  for owned paths, control/presentation/reserved ports, component metadata and
  consent flags. Validation does not start services or write credentials.
- Kept launcher/installer integration explicitly open; the manifest is not yet
  a production bootstrap contract.
- Full gate `20260905T101615Z` passed 299 non-E2E and 16 HTTP E2E tests plus
  compile/syntax, synthetic mic, Node and diff checks. Evidence remains local
  fake/synthetic coverage, not live JAWL, physical audio, OBS or production
  readiness.

### 2026-09-05 — native Companion E2E and SSE EOF handling

- Added typed native HTTP E2E coverage through the same Companion for complete
  response-envelope preservation, cursor reconnect, terminal `turn.error` and
  cancellation forwarding.
- Fixed SSE reader handling so an EOF cannot hide packets already queued before
  the connection closed; terminal turn errors are no longer treated as
  reconnectable stream loss.
- Full gate `20260905T100007Z` passed 295 non-E2E and 16 HTTP E2E tests plus
  compile/syntax, synthetic mic, Node and diff checks. Live JAWL remains the
  required next integration boundary.

### 2026-09-05 — JAWL prompt contract, native envelope and stream-chat slice

- Documented the JAWL prompt assembly model: `SOUL`/instructions/protocol are
  versioned behavior modules, while provider sessions and cache are only
  reconstruction optimizations. Added explicit ownership rules for the single
  JAWL/Companion/VoiceMem organism.
- Preserved the complete native response envelope across the Companion gateway,
  added terminal provider-error semantics, bounded SSE reconnect/cursor handling
  and explicit stream-chat observation ingestion/event-sink plumbing.
- Fresh full gate `20260905T094740Z` passed 295 non-E2E and 14 HTTP E2E tests,
  compile/syntax, synthetic mic, Node and diff checks. Live JAWL/provider,
  stream-platform accounts, physical devices, OBS and production acceptance
  remain open.

### 2026-09-05 — ambient lifecycle and full-gate evidence

- Added bounded ambient PCM rotation with idle/audio limits, byte backpressure,
  generation fencing, cancellation and cleanup; serialized concurrent Start/Stop
  transitions and updated system-audio E2E to use the public service lifecycle.
- Targeted ambient suite passed 33 tests. Full gate
  `20260905T115735Z` passed 281 non-E2E and 14 HTTP E2E tests plus compile,
  synthetic mic, Node and diff checks. Evidence is saved in `runtime`; live
  device/provider/OBS and production acceptance remain open.

### 2026-09-05 — launcher partial safety slice

- Main accepted the third launcher revision as an offline PARTIAL slice: 8
  unittest checks, PS AST and diff passed, with extracted helper checks for
  non-overwrite/containment/junction refusal. LIVE remains prohibited pending
  owner-approved runtime/loader and isolated lifecycle review; A3 is not closed.

### 2026-09-05 — embodied product defaults and partial readiness correction

- Specified normal-profile perception after first-run source permissions,
  automatic attributed memory, useful sandbox/CDP work, scoped social accounts,
  capability awareness and private/public OBS separation. Design only: no
  device capture or account actions started; runtime capture defaults unchanged.
- Tightened doctor configured/readiness semantics and target dependency/policy
  validation, with focused regression tests. Full-gate terminal result was not
  retained; no integrated live or production readiness claim (see STATE).

### 2026-09-05 — product/documentation audit

- Re-established one agent-companion product: JAWL cognition/native tools,
  VoiceMem perception, voice, memory, Full Access/unattended and mint Aero 2D UX.
- Clarified evolution toward one perception/decision/verified-feedback cycle,
  overlapping-mechanism review and coherence E2E; biological analogies do not
  require literal brain subsystems or runtime self-modification.
- Added PRODUCT.md, reordered TODO around connected daily scenarios, replaced
  repeated status narratives with a bounded current-state/evidence summary.
- Corrected premature RC/full-gate claims, independent smoke versus integrated
  acceptance, Qwen-primary/Tera-fallback, async final-ASR, automatic-memory
  direction, logical forgetting, and actual media/streaming capability limits.
- Documented protected-upstream/runtime ownership and unsafe target harness
  defaults; deprecated its launch instructions pending code fixes.
- Preserved earlier main docs in docs/history/2026-09-05-before-product-audit.
  This slice changes documents only, not runtime code or upstream repositories.

### Earlier implementation entries — historical claims

These entries describe earlier work, not fresh acceptance or permission to
modify upstream. Current readiness/limits override them in docs/STATE.md and
TECHNICAL_AUDIT.md; old aggregate pass counts must not be reused unqualified.


- Rebuilt the browser control plane as a mint Windows-Aero cockpit: the main
  view now combines the dialogue and an inline 2D companion preview, while
  voice, perception, memory, access and diagnostics live in focused tabs.
  Existing API element IDs and control actions were retained; the separate
  presentation origin remains the OBS mirror.

- Removed external final-ASR/VoiceMem latency from the response path. The
  authoritative ASR text is adapted into a transport-only final event for
  JAWL immediately, while identical VoiceMem enrichment runs through a
  bounded, observable background queue. A live profile reduced `/api/voice/end`
  from the previous 65.7 s observation to 0.409 s with no dropped memory task.

- Added a loopback Qwen3-TTS 12Hz 0.6B Base voice-clone worker and explicit
  `--tts-provider qwen` selection. The local Mita clone returned a valid 24 kHz
  WAV in the integrated profile; CPU generation remains a quality path at
  about 19.3 s, with TeraTTSv2 retained for low-latency live speech.

- Added a guarded live Qwen3-ASR final-utterance profile. The moved CPU
  GGUF/mmproj server transcribed two Russian TeraTTSv2 fixtures with median
  RTF 0.077; the report is in
  `runtime/asr-live-profile-20260904.json`. Streaming partial ASR and device
  microphone behavior remain explicitly outside this result.

- Re-ran the guarded real VoiceMem sidecar profile on the bundled PCM fixture:
  audio warmup, 272 chunks, three partials and one final turn completed with
  health `ready`. Evidence is in
  `runtime/voicemem-live-profile-20260904.json`; the bundled acoustic profile
  is still not accepted as a Russian microphone recognizer.

- Added a guarded live TeraTTSv2 worker profile. Five Russian requests returned
  valid mono PCM16 WAV; the 2026-09-04 run measured complete-response p50
  0.429 s, p95 0.487 s and median RTF 0.149. The report explicitly excludes
  provider-native streaming and real microphone/echo claims.

- Added a guarded target-machine release smoke for the two loopback surfaces,
  with explicit hard requirements for JAWL, external providers and Live2D.
  Its default degraded-mode run passed against control `2367` and presentation
  `8766`; required external services remain correctly unaccepted when absent.

- Added and passed a guarded native JAWL HostOS action slice: disposable
  child-directory creation, file write/metadata, monitoring lifecycle and
  native cleanup all succeeded with no leftover marker or directory. The
  current live rerun is in `runtime/native-jawl-action-parity-20260905.json`.

- Added and passed a guarded native JAWL catalog access matrix. Disposable
  levels 0, 1, 2, and 3 returned all 114 registered entries, with availability
  matching every declared minimum level; the initial policy level was restored.
  Evidence is in `runtime/native-jawl-catalog-matrix-20260905.json`.

- Added and passed a direct read-only native JAWL namespace profile: the live
  catalog exposed 114 HostOS/HostTerminal/Debug Broker entries and eight
  representative probes returned HTTP 200 with `native=true` and
  `is_success=true`. Evidence is in
  `runtime/native-jawl-namespace-parity-20260905.json`; the profile performs
  no writes, process starts, or debug session starts.

- Added a corrected guarded native JAWL policy profile. Its live disposable run
  passed levels 0–3, representative native write/delete/metadata/monitoring,
  fail-closed emergency-stop/reset and bounded ROOT autonomy issue/revoke.
  The profile now restores the initial level and temporary safety state during
  cleanup, waits for native readiness after startup and covers early assertion
  failures with regression tests. Evidence is in
  `runtime/native-jawl-policy-20260905-fixed.json`.

- Rebuilt the wheel twice with the same SHA-256 and force-reinstalled the fresh
  artifact into an isolated Python 3.14 environment. Package import, bundled
  frontend discovery and the installed CLI `--help` smoke all passed; external
  models and services remain outside this packaging check.

- Added a guarded target smoke wrapper for a disposable native JAWL launch. The
  2026-09-05 run passed Companion control/presentation checks, JAWL running
  status and native policy authority, while isolating the provider behind a
  loopback sink and cleaning detached descendants/port `8773`.

- Added and passed a disposable native JAWL + Big Pickle live profile:
  100/100 correlated turns, reconnect/resume, exact cancellation, final
  envelopes, cursor continuity and native HostTerminal tool lifecycle. The
  redacted evidence report is
  `runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`. The profile
  harness now supports direct invocation from the repository, requires the
  tool lifecycle by default, and handles JAWL's final-before-lifecycle event
  ordering. A loopback OpenCode header relay is test-only and stores no key in
  the repository.

- Added a provider-neutral bounded audio-description contract. A configured
  captioner can analyze the same transient ambient clip as final Qwen3-ASR and
  produce a strict music/sound description; only text metadata enters delayed
  ambient memory, never raw PCM, a user turn or a tool request. No captioning
  model is selected yet, so this is an integration boundary rather than a
  production model claim.
- Hardened the bridge emergency-stop boundary: native policy/agent failures
  now return `ok:false` with HTTP 503 while the local latch remains active;
  reset starts the native agent before clearing the native emergency latch.
- Added the Russian ambient final-ASR path: when Qwen3-ASR (or another
  configured external final recognizer) is present, system-output loopback is
  buffered through the bounded external ASR service instead of the bundled
  VoiceMem sherpa recognizer. A real synthetic WASAPI playback smoke captured
  Russian text with `0` dropped chunks, created one delayed ambient candidate,
  and left the conversational `last_turn` empty. The normal VoiceMem path is
  retained as a compatibility fallback and is not treated as Russian ASR.
- Added regression coverage for the external ambient ASR branch and made the
  missing-`PyAudioWPatch` system-audio test deterministic after installing the
  optional Windows backend.
- Installed the optional `PyAudioWPatch==0.2.12.8` package in the current
  Python user environment for WASAPI loopback testing; it is not vendored into
  the repository.
- The temporary OpenCode Zen `deepseek-v4-flash` provider passed JAWL's two
  live provider contract smokes when the key was mapped to
  `JAWL_LIVE_PROVIDER_KEY`. Later requests returned provider HTTP 403, so this
  provider remains a test profile and is not accepted for release soak.

- Re-ran the complete local gate, deterministic wheel build check, browser
  render smoke and three-cycle restart/soak profile on 2026-09-03. A real
  JAWL+Ollama one-turn native Gateway smoke passed reconnect/resume, exact
  cancellation, typed tool lifecycle and final-envelope validation. The
  100-turn soak reached 23/100 before the configured Ollama model returned an
  empty final answer and timed out; it remains a provider reliability blocker,
  not an accepted release result.
- Fixed native JAWL one-turn termination metadata and action lifecycle status:
  `terminate_loop` is preserved through tool-output normalization and default
  `action_1` IDs no longer appear as false failures. Successful cancellation
  no longer replays the cancelled wake payload as a late turn.
- Verified the authenticated Companion → JAWL bridge live: native policy
  authority, one HostOS read-only skill and one Debug Broker read-only skill
  all crossed the JAWL control boundary successfully. Full mutating and
  level-matrix parity remains a release validation item.
- Added a bounded native `skills.catalog` discovery route so Companion and
  parity tooling can inspect the live JAWL HostOS/HostTerminal/Debug Broker
  registry without duplicating it or gaining execution authority.
- Added the opt-in native HostOS policy profile: it waits for the native
  control socket, checks levels 0–3 with disposable filesystem probes,
  validates emergency-stop fail-closed behavior and ROOT lease revocation,
  and records a bounded JSON report.
- Added a bridge-mode regression test proving `/api/hostos/execute` forwards
  native skills and never calls the compatibility `HostOSExecutor`.
- Added a live Qwen3-ASR HTTP smoke through `OpenAICompatibleASRClient` on
  Russian TeraTTSv2 samples; the temporary loopback server was stopped after
  the measured final-utterance checks.
- Native JAWL's correlated SSE stream now emits bounded empty keepalive
  packets every five seconds, below normal client read timeouts while a local
  model is thinking.
- Moved the Companion control-plane default from `8765` (occupied by FoxMCP
  on this machine) to `2367`; avatar/OBS remains isolated on `8766`, while
  the JAWL console profile uses its own default `8770`.
- Hardened `run_web.ps1` to preflight both control and presentation ports,
  preventing a second confusing startup failure when either loopback port is
  occupied or both ports are accidentally set to the same value.

- Added a local TeraTTSv2 live-smoke record (real Russian WAV, latency and
  cancellation measurements) and improved native Gateway profile diagnostics
  to distinguish an established-SSE read timeout from an unreachable server.
- Added a documented real VoiceMem sidecar text smoke, exposed the offline
  `--voicemem-local-memory` Companion option, and raised the default sidecar
  timeout so cold local model loading is not misreported as a dead service.
- Added explicit `warmup text|audio` lifecycle support with `VOICE_READY`, so
  real deployments can preload VoiceMem before opening the microphone.
- Added a guarded, redacted `run_voicemem_profile` live runner and recorded a
  real VoiceMem PCM/VAD process profile on the bundled fixture.
- Fixed wheel reproducibility by pinning `SOURCE_DATE_EPOCH`; consecutive
  release builds now produce the same artifact hash.
- Verified clean wheel installation and the installed CLI entry point in an
  isolated smoke environment.
- Added a dependency-light headless Edge/Chrome browser-render smoke for the
  control plane and isolated avatar/OBS DOM; it does not add Playwright to the
  core package.
- Added optional transient OCR grounding and opaque pixel redaction for screen
  capture, with CLI rectangle configuration and no new mandatory dependency.
- Added an explicit `TeraTTSHttpClient` name for the selected TeraTTSv2 REST
  worker while preserving the compatible `CozyVoiceHttpClient` import.
- Fixed JAWL MCP SDK compatibility across camelCase protocol aliases and
  snake_case Python model attributes; the broad JAWL unit/web gate is green.

- Added a bounded read-only native JAWL action-journal projection and a
  Companion inspection panel for autonomous plan states and outcomes. Original
  action parameters and execution authority stay inside JAWL.
- Added an explicit confirmed Vision plan route with signed-token/frame-digest
  matching and a thin native JAWL HostOSDesktop execution adapter; unsupported
  mappings fail closed and no VLM is invoked by the route.

- Reconciled release documentation with the implemented VisionPlanExecutor and
  supervised-recovery boundaries; refreshed the full local gate counts and
  rebuilt the wheel/hash manifest.

- Synced the documented recovery contract with native JAWL: automatic restart
  requires an active per-instance ROOT lease and current HostOS level 3;
  unfinished JAWL coding approvals are invalidated at runtime startup.

- JAWL structured memory now carries UTC validity intervals and explicit
  retention tiers, with an idempotent migration for existing SQLite stores;
  expired active rows no longer enter prompt context.
- TTS sentence streaming now invokes provider cancellation on generator close
  and classifies a cancellation-closed HTTP body as cancellation, preventing
  a stale synthesis from being misreported as a provider failure.

- Added a persistent bounded native JAWL Gateway event journal with cursor
  replay, duplicate suppression and explicit replay-gap reporting. Gateway
  clients no longer impersonate an operator terminal session, so Heartbeat
  does not receive false user-presence events.
- Added wheel packaging for the browser frontend, a reproducible build script,
  SHA-256 manifest and clean-install/rollback documentation. Live signing and
  target-machine acceptance remain intentionally external release steps.
- Added avatar capability metadata/runtime diagnostics and deterministic
  sensitive-source suppression before ambient triage. Presentation boundary
  regression tests now assert that control credentials, history and mutation
  routes are absent from the OBS origin.
- Rebaselined the documentation after a full architecture/security/reliability
  audit. The project is explicitly classified as a development prototype;
  release blockers now cover the native structured JAWL gateway, one unified
  JAWL HostOS/Debug Broker policy, control/presentation isolation, voice/TTS
  lifecycle defects, reproducible packaging and live acceptance profiles.
- Corrected earlier overclaims: the HTTP E2E suite uses fake providers, the
  isolated presentation server still needs live OBS validation, Tera
  cancellation is not provider cancellation, ambient retention is not durable,
  and live native JAWL envelope preservation still needs evidence.
- Fixed Russian fallback/cancellation text in the streaming gateway and added
  exact UTF-8 regression coverage. Added a strict client-side parser for the
  planned correlated JAWL event stream; the existing uncorrelated web/terminal
  compatibility transports remain and are not promoted to production.

- Added an optional OpenAI-compatible chat adapter for temporary model tests;
  API keys stay in environment variables and JAWL remains the canonical
  persona, memory, Heartbeat and JSON action owner.
- Added a Qwen3-ASR-0.6B-compatible CPU server launcher and bounded
  final-utterance bridge. PCM16 chunks stay in RAM until explicit end, then
  one transcript enters VoiceMem's final event path; the default VoiceMem
  streaming path is unchanged.
- The ASR bridge now sends the bounded transcription prompt used by the CPU
  benchmark. A live adapter smoke with the benchmark WAV returned the expected
  transcript; Vision also forwards bounded transient UI Automation context
  and includes that context in change detection.
- Added the policy-gated `desktop.pointer` fallback for canvas/custom apps;
  image coordinates are recalibrated against fresh foreground bounds and the
  result distinguishes pointer dispatch from application acceptance.
- Revalidated the live Qwen3-ASR adapter against the three VoiceMem PCM16
  samples; all three expected multilingual transcripts were returned, while
  the absence of a Russian reference recording remains explicit.
- Added a policy-gated `desktop.keyboard` fallback for bounded Unicode text and
  one-to-four-key hotkeys, with foreground-window binding and a separate
  dispatch postcondition.
- Upgraded the transparent avatar fallback from static geometry to a lightweight
  reactive 2D face with expression, blink and speaking states; external Live2D
  still takes precedence when a valid bundle is configured.
- Added an ephemeral browser-audio amplitude bridge for fallback and Live2D
  lip-sync, with BroadcastChannel fast-path and backend polling fallback.
- Added an opt-in bounded half-duplex hands-free mode: local RMS silence ends
  each utterance, rotates the VoiceMem session and keeps capture open. The
  benchmarked VLM/ASR launchers now point to the transferred
  `G:\\AI\\VLM-RealTime-Bench` runtime and model files.

- Screen capture now defaults to a benchmark-oriented 960×720 / 1 MB
  transient JPEG profile, exposes bounded coordinate-scale metadata and makes
  the profile visible through `/api/vision/status`.
- Added an opt-in Windows activity signal for Attention/Presence; recent user
  input suppresses proactive screen speech, while only bounded idle time and
  foreground class metadata are exposed.
- Recorded the CPU/RAM Vision benchmark candidates: Qwen3-VL-2B leads the
  supplied UI/quality comparison, SmolVLM2-500M leads latency, Bonsai-1.7B is
  the text-only CPU profile and Qwen3-ASR-0.6B is the leading audio candidate.
- Added a `run_web.ps1` port preflight so a port occupied by another service
  fails with an actionable message before the Companion starts.
- Hardened VoiceMem lifecycle handling: empty flushes stay lazy, failed stream
  sessions are evicted for retry, and `/api/voice/status` now includes bounded
  sidecar process state without exposing launch details.
- Added bounded model-neutral parallel sentence synthesis to the CozyVoice
  adapter while preserving source-order WAV output; TTS model selection and
  first-audio streaming remain separate follow-up work.
- Added an authenticated TTS cancel route and browser request abort so a new
  turn can stop both playback and active server-side synthesis.
- Added bounded file snapshots with SHA-256 conditional workspace writes;
  changed files now fail with `stale_file` instead of being silently replaced.
- Added a browser review/execution path for one-shot HostOS proposals; reviews
  are bounded/redacted and the in-memory request is dropped after execution.
- Added provider-neutral browser controls for TTS voice identifier and speech
  speed; no model or provider is selected by these controls.
- Added a bounded browser barge-in trigger: clear microphone activity cancels
  active TTS playback/request once, while VoiceMem remains the final turn and
  interruption classifier.
- Added an optional Windows avatar-window launcher that opens the isolated
  read-only `/avatar` presentation surface as a bounded always-on-top
  Edge/Chrome app window; OBS uses the same printed presentation URL.

- Added an opt-in authenticated JAWL HostOS control bridge: level 0–3 now
  writes the native JAWL fields, restarts the JAWL agent and changes the local
  companion policy only after successful restart; full ROOT means current
  Windows-user capability.
- Bridge-mode emergency stop now also requests JAWL's native agent stop while
  always cancelling Companion-owned processes locally; per-tool native
  cancellation and native approval synchronization remain pending.
- Added an explicit browser recovery action that starts native JAWL before
  clearing the Companion emergency-stop latch.
- Added bounded optional JSONL persistence for metadata-only HostOS audit and
  lifecycle events; command arguments, credentials and hidden reasoning are
  excluded.
- Documented the verified JAWL native HostOS ownership boundary: the current
  companion executor is explicitly labelled as a separate control-plane path
  for controls that are not covered by the authenticated level/stop bridge,
  especially native unattended and approval state.
- Added bounded read-only native JAWL HostOS status to the browser overview so
  companion policy and JAWL's configured level cannot be confused.
- Emergency stop now terminates tracked managed and shell processes and marks
  an interrupted shell request as `cancelled` instead of leaving it running.
- Added an HTTP E2E restart/recovery check for owned-process cleanup, fresh
  safe policy defaults and non-persistent approval state.
- Added explicit ROOT-only unattended execution for background/heartbeat work:
  level 3 grants current-user capability, while the separate switch disables
  per-action prompts only after operator confirmation; emergency stop and
  deny-list checks remain authoritative.
- Added bounded Attention/Presence handling for screen deltas, DND/cooldown
  and explicit atomic delivery of salient `SPEAK_INTENT` events to JAWL's
  existing `.jawl_events` IPC boundary.
- Documented ambient secondary memory as separate, opt-in evidence with
  transient raw capture, delayed CPU/RAM triage and JAWL-owned promotion.
- Verified the companion event sink against JAWL's actual poller, EventBus and
  EventBridge in an isolated smoke; final model broadcast remains explicit
  `no_broadcast` when the active profile does not call the terminal skill.
- Added the first default-off ambient-memory runtime slice: bounded normalized
  audio/visual observations, privacy/TTL/byte limits, deterministic delayed
  coalescing, authenticated browser inspection and explicit enable/disable.
- Added a lazy, default-stopped `SystemAudioLoopback` boundary for an optional
  PyAudioWPatch-compatible Windows WASAPI backend with bounded in-memory PCM16
  delivery and degraded behavior when the backend is unavailable.
- Added a strict delayed ambient-triage provider contract and optional
  CPU-first Ollama JSON adapter; no audio model is selected or loaded by
  default, and Vision/VLM selection is explicitly deferred.
- Added an isolated `AmbientAudioASRBridge` with PCM16 downmix/resampling,
  sidecar chunk bounds and final-only ambient ingestion; the loopback-to-HTTP
  path is covered by E2E without creating a user turn.
- Added browser consent/status controls for ambient memory and explicit
  system-audio start/stop lifecycle.
- Added an optional Windows `system-audio` package extra and ambient readiness
  entries to the doctor report; installation and capture remain explicit.
- Added browser actions for explicit ambient triage and buffer clearing.
- Added local-time quiet-hours gating for proactive Attention/Presence and a
  browser setting for its `HH:MM-HH:MM` window.
- Created the isolated `JAWL-VoiceCompanion` development repository.
- Documented the JAWL/VoiceMem ownership boundary.
- Restricted the current avatar scope to 2D Live2D.
- Added initial architecture, contracts, research, decisions and state files.
- Accepted HostOS access levels 0–3, including an explicitly enabled full-user
  mode with backend policy enforcement.
- Selected a loopback browser application as the canonical control plane.
- Added the initial HostOS request/result contract and risk classes.
- Added a dependency-free Phase 1 text gateway, response validation, dry-run
  HostOS policy gate, audit metadata and loopback browser control surface.
- Added a JAWL loopback terminal adapter with mock fallback when the JAWL
  process is offline.
- Added the priority-aware `TurnArbiter` base for one active turn, stale work
  cancellation and queue promotion.
- Added the initial HostOS tool registry plus bounded filesystem/process/argv
  adapters, with dry-run as the default and path traversal protection.
- Added optional Windows UI Automation observation/control with bounded trees,
  opaque element references and stale-target rejection.
- Added a dependency-free browser adapter for bounded HTTP(S) navigation and
  UIA delegation, still protected by HostOS policy and approval.
- Exposed HostOS tool discovery and policy-checked dry-run execution through
  the local browser API.
- Added a server-side, session-bound, one-shot approval queue with TTL,
  fingerprints and redacted previews.
- Connected turn cancellation to the JAWL adapter through per-turn
  cancellation events and bounded socket reads.
- Added a read-only transparent `/avatar` presentation surface for desktop
  capture and OBS, plus a copyable URL in the control panel.
- Added an explicit, opt-in focused-window `screen.observe` adapter with
  bounded transient JPEG output and sensitive/companion window blocking.
- Added an OpenAI-compatible vision bridge, `/api/vision/look`, duplicate-frame
  suppression and a cooldown-aware browser vision control.
- Added an opt-in, arbiter-aware `SCREEN_DELTA` watcher with a bounded event
  endpoint and a real local-HTTP E2E suite covering chat, avatar, approvals,
  execution, emergency stop, screen vision and deduplication.
- Extended the E2E path through a local JAWL-compatible TCP terminal, covering
  the handshake and JSON-lines response before the result reaches HTTP state.
- Recorded the concrete VoiceMem `stream.feed_partial` sidecar contract and
  kept its heavyweight runtime outside the JAWL/web process boundary.
- Added the minimal VoiceMem JSON-lines runner, lazy subprocess client and
  authenticated `/api/voice/partial` bridge with UTF-8 transport framing.
- Added bounded browser microphone capture, mono PCM16 `/api/voice/audio`,
  `/api/voice/end` flushing and an E2E path proving audio → VoiceMem → JAWL →
  visible state; raw audio remains transient.
- Added a provider-neutral cancellable TTS service, bounded CozyVoice REST
  client, WAV sentence merge, `/api/tts/status`, `/api/tts/synthesize` and
  optional browser playback with a local-HTTP E2E check.
- Added an optional user-supplied Live2D asset root, read-only
  `/avatar-assets/` serving, `/api/avatar/config`, runtime adapter loading and
  placeholder fallback without committing SDK/model assets.
- Added a loopback-only, read-only JAWL web adapter for Heartbeat, persona,
  drive and memory counters; filtered config prevents secrets and no parallel
  durable memory store is created.
- Bounded JAWL drive summaries to an explicit field allow-list after validating
  the payload against the real local JAWL console.
- Added a session-protected HostOS audit view showing bounded metadata events;
  the browser never receives command arguments or raw execution output.
- Added backend Live2D model-reference validation for fatal Moc/texture files,
  explicit `ready`/warning diagnostics and a documented tiny renderer plugin
  contract, keeping Pixi/Cubism and character assets out of the core repo.
- Documented that JAWL's current terminal channel is broadcast-only, exposed
  the `no_broadcast` degraded status, and added a full-gate command requiring
  compile, unit, local HTTP E2E and diff verification for major changes.
- Added the correlated JAWL web-chat adapter: it holds the local SSE stream,
  acknowledges a user sequence through `/api/chat`, filters old messages and
  propagates cancellation/no-broadcast states through the visible HTTP health
  contract. The web adapter is now preferred over the legacy terminal path.
- Hardened the correlated SSE reader against the `http.client` close race and
  added a regression test. A live isolated JAWL/Ollama probe confirmed terminal
  input and model completion, while preserving `no_broadcast` when the model
  emits no user-facing terminal message.
- Added fail-closed hidden-thought/control-markup filtering to both JAWL chat
  transports, with HTTP E2E coverage for sanitization and upstream recovery.
- Added a bounded `/api/doctor` readiness report and browser panel for the
  text-only/degraded startup path, with unit and cross-layer E2E coverage.
- Added an explicit bounded LLM `User-Agent` override so the temporary
  OpenCode Zen `big-pickle` profile can reproduce the same provider routing as
  the installed OpenCode CLI without storing credentials in the repository.
- Verified the temporary `big-pickle` profile through disposable Companion
  `/api/chat` and `/api/chat/stream` HTTP sessions; the model remains a test
  provider and is not promoted to native JAWL release evidence.
# Unreleased

- Added a reproducible live synthetic Russian audio check: TeraTTSv2 generates
  three utterances and local Qwen3-ASR-0.6B transcribes them on CPU; evidence is
  saved in `runtime/synthetic-questions-profile.json` (median RTF 0.111).
## Unreleased — live validation correction

- Recorded the failed extended Qwen live run instead of counting it as a
  three-question acceptance: q1 passed; q2 exceeded the bounded response
  budget and emitted unavailable JAWL skill names; q3 was not started.
- Kept the issue open for authoritative tool catalog enforcement and bounded
  invalid-plan recovery.
- Added two narrow JAWL registry aliases for the observed historical terminal
  skill prefix and refreshed `SOURCE_MANIFEST.json`; full gate
  `runtime/full-gate-20260905T171633Z.json` passes.
- Captured `runtime/alias-live-q2.json` as supporting single-turn evidence;
  kept it explicitly non-acceptance because the alias invocation was not
  observed in the JAWL log.
- Added correlation IDs to the disposable native-action profile and captured a
  live owned-JAWL HostOS write/metadata/monitoring run with verified cleanup at
  `runtime/native-action-live-20260905202420.json`. Full gate refreshed at
  `runtime/full-gate-20260905T172607Z.json` with exit code 0.
- Recorded an unaccepted model-task attempt: startup heartbeat caused two
  honest HTTP 409 chat conflicts and the local Qwen request later hit its
  provider timeout boundary. This remains a P0 scheduling issue.
- Fixed JAWL web chat delivery to acquire and await the asynchronous terminal
  bridge before sending; a live owned-profile probe returned HTTP 200/sequence
  1. Full gate `runtime/full-gate-20260905T174510Z.json` passes.
- Added the native UI `/api/jawl/restart` contract and recorded partial live
  memory persistence evidence; post-restart recall was not accepted because
  the JAWL console became unreachable. Full gate
  `runtime/full-gate-20260905T180113Z.json` passes.
- Completed live UI memory → native restart → recall verification in
  `runtime/live-ui-memory-restart-20260905.json`; the acceptance waits for
  `agent_ready=true` before reading memory again.
- Added bounded post-restart readiness verification to the native JAWL web
  adapter; restart now fails closed if the agent does not become ready. Full
  gate `runtime/full-gate-20260905T180606Z.json` passes.
- Extended only native lifecycle request timeouts to a bounded 120 seconds
  after observing JAWL's ~60-second restart startup; ordinary requests remain
  short. Full gate `runtime/full-gate-20260905T181140Z.json` passes.
- Re-ran the full gate after a transient fixture race; authoritative passing
  artifact is `runtime/full-gate-20260905T181942Z.json` (exit code 0), while
  the failed `181650Z` run remains documented for diagnosis.
# 2026-09-06

- Clarified the memory contract: an ambient episode is a transient T1/T2
  candidate, not canonical JAWL episodic memory. Documented the native JAWL
  memory/state surfaces and VoiceMem emotional/audio layers separately.
- Browser voice E2E now obtains CSRF inside its async turn and permits 180
  seconds for slow local CPU turns; the latest run remains failed until a full
  three-turn result passes.

### 2026-09-06 — runtime audit

- Re-ran the full regression: 353 tests and 28 subtests passed.
- Recorded the failed connected Ollama acceptance (startup/HTTP compatibility, but no final correlated native turn due to model tool behavior).
- Recorded that JAWL 8770 was closed and FoxMCP 8765 remained untouched.
- Changed the temporary local profile to explicit canonical `json_envelope` tool transport; verified effective startup configuration, with connected final-response acceptance still open.
- Added bounded no-tool completion delivery for correlated Companion turns in the pinned owned JAWL snapshot; full regression remains green (`353 passed, 28 subtests passed`).
- Recorded bounded TokenRouter GLM free/flash timeouts; no credential was persisted.
- Blocked internal-thought leakage in correlated no-tool completion delivery; unsafe completions now terminate as explicit errors.
- Live-verified that unsafe local-model completions fail closed with a bounded correlated error and do not leak internal reasoning.
## 2026-09-07

- Added exclusive per-profile launcher locking to prevent duplicate
  `coder-live` process trees after interrupted runs.
- Verified pinned JAWL snapshot integrity and 14 gateway tests after recovery.
- Added loopback `reasoning_effort=none` propagation for Ollama thinking models;
  verified a Russian response through JAWL/Companion and reran the full local
  gate successfully.
- Added cancellable simulated phrase streaming for JSON-envelope speech and
  removed per-audio-chunk TTS restarts.
# 2026-09-07

- Fixed the memory panel to consume canonical structured records from the
  dedicated JAWL memory endpoint; made dashboard refresh resilient to degraded
  secondary endpoints.
- Added a real-browser memory acceptance harness with preference selection,
  revise, native restart and canonical cleanup. Post-restart live DOM recall
  remains an explicit open acceptance item.
# 2026-09-07 (continued)

- Native restart from the Companion UI now waits for canonical structured-memory
  readiness in the managed profile, avoiding a false-ready race after restart.
# 2026-09-07 (refresh concurrency)

- Serialized dashboard refreshes and coalesced follow-up requests to avoid
  overlapping JAWL/memory calls during restart and filtering.
# 2026-09-07 (restart readiness)

- Require two consecutive full native memory probes before managed UI restart
  reports readiness, covering the startup control-queue race.

# 2026-09-07 (memory persistence acceptance)

- Split the browser memory harness into `write`, `verify`, and legacy `all`
  phases. Verified real UI create/revise, full managed-profile stop/start,
  Russian revised-value recall, and native cleanup.
- Kept the native-agent restart issue explicitly open; the full-process result
  does not overwrite or overclaim that JAWL lifecycle path.

# 2026-09-07 (native restart race correction)

- Fixed the memory acceptance harness to await the asynchronous dashboard
  refresh after native JAWL agent restart.
- Verified the complete UI create/revise → native restart → UI recall path:
  `runtime/memory-ui-all-20260907.json`.

# 2026-09-07 (connected voice acceptance)

- Fresh isolated profile passed three real browser capture turns through
  Qwen3-ASR, the same JAWL/local LLM, TeraTTS streaming, the single playback
  owner and avatar audio state. Evidence: `runtime/voice-connected-e2e-20260907.json`.
- Kept barge-in, voice-to-native action and recovery as separate unclosed gates.

# 2026-09-07 (voice timing baseline)

- Added browser-side timing evidence for voice-end, first TTS response and first
  audio buffer. Connected run measured ~124 s cold and ~11.6–12.9 s warm to
  first audio; this remains a performance blocker for realtime UX.
- Full local regression gate remains green: 336 tests, 16 HTTP E2E, browser,
  mic-gate and snapshot checks.

# 2026-09-07 (restart-safe speech guard)

- Added a process-scoped `runtime_instance_id` to Companion health.
- Browser health probes now stop stale local WebAudio/TTS immediately after a
  Companion restart, without requiring the old backend to answer cancellation.
- Verified stable identity and frontend behavior with `tests/test_web.py`:
  36 passed. JAWL task checkpoint recovery and duplicate native side-effect
  prevention across restart remain separate production gates.

# 2026-09-07 (native identical-write idempotency)

- A real managed profile exposed repeated identical `HostOSWriter.write_file`
  calls after a successful result.
- Native JAWL now treats an exact UTF-8 content match as an explicit idempotent
  no-op, preserving the existing file without replaying the filesystem write.
- Direct runtime probe passed; snapshot verifier passed with digest
  `3a15a6b057f56eaa28a186e0b46525a909220004f7a5e5c4e6ba8f6fa457a8f2`.
- This is not a blanket exactly-once guarantee for all tools or restart
  recovery; those acceptance tests remain open.

# 2026-09-07 (native Goal checkpoint recovery evidence)

- Exercised the pinned JAWL `GoalManager` through a durable ledger checkpoint,
  provider-failure cycle and fresh-instance restart.
- Confirmed active goal, pending work, checkpoint phase/next action and lane
  epoch recovery. Evidence:
  `runtime/native-goal-provider-failure-recovery-20260907.json`.
- Live process-death recovery with an uncertain native effect remains open.

# 2026-09-07 (managed native restart probe)

- Verified the normal Companion `/api/jawl/restart` route against a live
  managed profile: native JAWL stopped, restarted, and passed readiness before
  the route returned.
- Verified a post-restart native `HostOSWriter` → `HostOSReader` operation and
  SHA-256 postcondition. This is not a claim of crash-safe exactly-once side
  effects; interruption during an uncertain native action remains open.

# 2026-09-07 (GoalSkills compatibility finding)

- A fresh managed profile showed that the selected local Gemma provider can
  answer an explicit durable-goal request with a terminal-message confirmation
  without emitting canonical `GoalSkills.create_goal` or persisting a goal.
- Recorded this as a provider/model compatibility failure. No parallel
  Companion task owner or goal shim was introduced; live checkpoint recovery
  must be rerun with a provider that honors JAWL's native tool contract.

# 2026-09-07 (live GoalSkills restart acceptance)

- Restored GoalSkills, SQLStructuredMemory and core native file/terminal
  namespaces to the adaptive JAWL context instead of hiding them behind the
  omitted namespace index.
- Live managed acceptance now creates a native goal, performs a native file
  side effect, survives the owned JAWL restart with a new lane epoch, reads the
  postcondition and completes through `GoalSkills.update_goal`.
- Evidence: `runtime/goal-restart-live-acceptance-20260907.json`. Uncertain
  side-effect crash recovery and blanket exactly-once behavior remain open.

# 2026-09-07 (post-context three-turn voice gate)

- Re-ran the real browser capture gate after restoring canonical adaptive
  namespaces: 3/3 Russian turns passed capture/gate → Qwen3-ASR → JAWL/local
  LLM → TeraTTS → shared playback/avatar with consistent correlation IDs.
- First-audio timings were 13,883 ms, 22,507 ms and 49,427 ms. The path is
  accepted for correctness, while realtime latency remains an open quality
  gate. Evidence: `runtime/browser-voice-e2e.json`.

# 2026-09-07 (context-budget latency experiment reverted)

- Tested a tighter dynamic context budget. The voice gate stayed correct, but
  first-audio remained 24.8 s / 24.8 s / 43.1 s and invalid invented skill
  names increased. Reverted the experiment; future latency work must target
  provider/request-path behavior rather than blind context truncation.

# 2026-09-07 (stale terminal namespace compatibility)

- Added one guarded alias from the stale model spelling
  `HostOSJournalMessages.send_message_to_terminal` to the canonical
  `HostTerminalMessages.send_message_to_terminal` skill. No new capability or
  policy path was introduced; ambiguous invented skills remain rejected.

# 2026-09-07 (startup readiness provider failure)

- Recorded a fresh managed profile where local Gemma repeated terminal actions
  during `SYSTEM_CORE_START` until the native 15-step ReAct bound was reached.
- Launcher failed closed instead of exposing an incompletely ready Companion;
  this remains a provider/model compatibility blocker, not a timeout to hide.
## 2026-09-09 — gate integrity and Live2D presentation smoke

- Fixed the regression gate's invalid leading-underscore JAWL instance ID;
  the full gate now completes with exit code 0 and 365 non-E2E tests.
- Snapshot verification ignores only generated `__pycache__/*.pyc` artifacts;
  source files and their manifest hashes remain strict.
- Passed a real browser Live2D smoke with the staged Mao Pro model, including
  visible canvas plus expression, motion and lip-sync capabilities. Desktop
  transparency, OBS, DPI/multi-monitor and long-run checks are still required.
