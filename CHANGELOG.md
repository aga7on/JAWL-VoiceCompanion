# Changelog

## 2026-09-06

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
