# Production status — 2026-09-09

## Current verification correction — 2026-09-09

The authoritative full gate completed with exit code 0 after the regression
instance-id fix, native-delta adapter, Goal compatibility slice, mobile
composer correction, unified runtime seam and release scanner: 394 non-E2E tests, 16 HTTP E2E tests, browser interaction
at six viewports, synthetic microphone gate, Node check and `git diff --check`.
The pinned JAWL verifier also passes: 348 manifest files,
snapshot SHA-256 `fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.

The first unified-runtime refactor slice is now present: `CompanionRuntime`
owns the control/presentation lifecycle and idempotent shutdown order, while
`src/jawl_voicecompanion/composition.py` owns component construction. This is
an orchestration boundary only; it does not duplicate JAWL cognition or move
canonical memory/native authority into the Companion. Existing adapter
factories remain compatible.

The release-input secret scan passed with zero findings across 1192 text files;
the report redacts match values by construction. A fresh isolated venv then
installed the rebuilt wheel and ran import plus CLI help outside the source
cwd. This is stronger package evidence, but worker/model/assets installation
and rollback acceptance remain open.

The real Windows loopback boundary was also exercised for two seconds through
`pyaudiowpatch`: the default Game-Audeze Maxwell loopback yielded 93 chunks at
48 kHz/2 channels, zero drops and no raw-media persistence. Evidence is in
`runtime/system-audio-loopback-20260909.json`. This does not close physical
microphone/AEC, speech attribution or long ambient-capture acceptance.

## Unattended long-run correction — 2026-09-09

The latest `qwen-ollama-unattended-8h-v3-20260909` run is negative, not a
production pass: it stopped fail-closed at cycle 39. Qwen completed the native
write/read, then attempted forbidden `GoalSkills.update_goal` and repeated the
writer as an idempotent no-op. The native file postcondition was valid and the
orchestrator revoked the unattended lease and closed owned ports, but the
provider violated the direct Goal-v2 contract. Evidence:
`runtime/unattended-qwen-ollama-8h-v3-20260909.json`.

The harness now reports real non-idempotent writes separately from idempotent
retries and rejects forbidden legacy Goal calls recorded in durable evidence.
Focused harness tests pass; the eight-hour gate must be rerun after this
correction.

## Connected local Qwen + VoiceMem correction — 2026-09-09

The local Qwen OpenAI-compatible endpoint on `53092` is now accepted as a
real connected profile baseline with reasoning disabled. The bounded context
fix keeps the JAWL provider prompt below the model's 16k context limit; the
previous `16694 > 16384` failure is retained as negative diagnostic evidence.

The VoiceMem sidecar had a real integration defect: local-memory mode created
its cognitive annotator without the profile's local `base_url`, inherited a
machine SOCKS proxy and returned `voicemem_stream_failed` on memory ingest.
The adapter now reuses the profile's `LLM_API_URL`/key for local VoiceMem and
removes proxy variables only for loopback endpoints. A direct sidecar probe
and the live profile both now return `VOICE_TURN`; after six browser turns the
sidecar remained `ready` with `accepted=6`, `completed=6`, `failed=0`.

Fresh real-browser evidence on profile `qwen-local-voice-bounded-20260909-r2`:

- `runtime/browser-voice-qwen-bounded-r2-3turn-20260909.json` — 3/3 RU voice
  turns through capture, Qwen ASR, JAWL, TeraTTS stream and WebAudio.
- `runtime/connected-daily-qwen-local-bounded-r2-20260909.json` — canonical
  memory revise, 3 voice turns, native write/read SHA verification, JAWL
  restart, memory recall and recoverable cleanup all passed.
- `runtime/browser-barge-in-qwen-bounded-r2-gap9-rerun-20260909.json` — two
  voice turns, cancellation during first speech, two TTS streams and two
  scheduled audio buffers passed. The earlier gap=2 run is a valid negative
  latency diagnostic, not a product regression.

The browser barge-in harness now waits up to 30 seconds for the second audio
buffer after the second voice end, so a slow but valid TTS stream is not
misclassified as a single-buffer failure; it still fails if the second buffer
does not start within that bound.

The release wheel was rebuilt after this correction and its SHA-256 manifest
was written to `dist/SHA256SUMS.txt`. A fresh target-directory install passed
package import and untruncated CLI help. This does not yet accept a complete
worker/model/assets clean install or rollback.

The real browser Memory tab also passed on disposable connected Qwen r3:
create, revise, native JAWL restart, revised-value recall and cleanup are
recorded in `runtime/memory-ui-qwen-r3-20260909.json`.

The first fresh 3-cycle unattended probe is retained as negative provider
compliance evidence: cycle 1 passed, then Qwen omitted the required terminal
Goal ledger and JAWL correctly returned `blocked`. The harness was corrected
to clean failed fixtures through the native route; the rerun passed 3/3 with
unattended lease revocation in
`runtime/unattended-qwen-local-3cycle-rerun-20260909.json`. This closes only
the short soak/harness safety slice; eight-hour duration and provider variance
remain open.

The same short acceptance was also run through the persistent Ollama
OpenAI-compatible endpoint on `11434` with
`qwen3.8-27b-abliterated:latest`, rather than the disposable `llama-server`
endpoint on `53092`. It passed 3/3 with native write/read, durable
postconditions, recoverable cleanup and unattended lease revocation:
`runtime/unattended-qwen-ollama-3cycle-20260909.json`. This confirms the
standard local-provider launch path, but is still not evidence for the open
eight-hour/provider-variance gate.

After the long-run variance correction, a connected 90-second smoke passed
2/2 cycles with independent terminal-ledger checks, exact native write,
postcondition, cleanup and unattended lease revoke:
`runtime/unattended-qwen-ollama-smoke-v2-20260909.json`.

The next corrected smoke also passed 2/2 at an explicit disposable-profile
temperature of `0.2`, which reduces provider-compliance variance without
weakening the fail-closed terminal-ledger check:
`runtime/unattended-qwen-ollama-smoke-v3-20260909.json`.

The fresh eight-hour v3 acceptance is currently running as
`qwen-ollama-unattended-8h-v3-20260909` on disposable ports `8770/2368/8767`.
The previous v2 run stopped at cycle 5 after the provider invented the
nonexistent `GoalSkills.complete_goal` action; JAWL rejected the false terminal
state and the orchestrator cleaned the profile and lease successfully. No
eight-hour production claim is made until the v3 report finishes with every
cycle valid.

## Provider recovery harness — 2026-09-09

Added `scripts/run_unattended_provider_recovery.py`, an operator-driven live
acceptance harness for the missing P0 boundary. It uses the same native
Goal/Heartbeat path as the unattended soak, waits for a durable sandbox write
while the Goal remains active, then requires an operator to stop and restore
only the disposable provider endpoint. After restoration it restarts JAWL,
checks that the active Goal survived, verifies the marker through native
`HostOSReader.read_file`, reconciles an uncertain writer outcome by the
`(action_id, tool)` identity, proves exactly one real write, performs native
cleanup and revokes the unattended lease.

The harness never kills a process and never claims success when the durable
write boundary was not reached. Unit coverage protects marker evidence from
idempotent no-op retries and rejects action-id-only ledger matching. The
corrected live acceptance passed in
`runtime/unattended-provider-recovery-live31-20260909.json`: the opt-in exact
relay stop happened after the durable write, the provider was restored on the
same endpoint, JAWL restarted with the Goal active, native readback verified
the SHA, `(action_id, tool)` reconciliation remained safe, the journal proved
exactly one non-idempotent write, native cleanup succeeded and the unattended
lease was revoked. Negative live30-r2/r3 runs remain safety evidence:
malformed completion after outage was blocked rather than falsely accepted.
The provider-recovery P0 acceptance is now closed for the current local
provider; longer unattended soak remains separate.

The new `scripts/run_provider_recovery_live.ps1` keeps the disposable relay
and level-3 profile outside the baseline ports. The harness has an opt-in
`--auto-stop-provider` mode that can terminate only a verified loopback relay
process on its non-baseline port.

## Presentation LAN boundary — 2026-09-09

The isolated avatar/OBS origin now gets a separate read-only bearer token when
it is bound outside loopback. Remote presentation state, configuration and the
avatar page fail closed without that token; the token is accepted only through
the presentation URL/header and cannot authorize the control plane. Loopback
OBS remains unchanged. This closes the implementation slice for the LAN
presentation authorization boundary; real OBS capture and long-run/DPI testing
remain external acceptance work.

## Streaming transport correction — 2026-09-09

The disposable OpenAI-compatible relay now preserves HTTP/1.1 streaming
framing. When an upstream returns a chunked body, the relay re-frames decoded
chunks as downstream `Transfer-Encoding: chunked` instead of silently removing
the header and waiting for a keep-alive EOF. A direct loopback probe completed
all 7 SSE events, including `[DONE]`. This fixes a real transport-level cause
of the symptom “speech starts and then stops”; it does not by itself prove
token-level TTS playback or provider recovery.

The first unattended provider-recovery experiments after this correction are
kept as negative diagnostics, not release evidence: `live25` completed the
native effect before the graceful relay stop, while `live25b` lost the
provider before its durable write. The stronger combined provider/JAWL
restart, checkpoint reconciliation and no-duplicate-side-effect gate remains
open and is not replaced by these runs.

The recovery harness now fails closed at that boundary: when a durable native
write is not observed, it writes a negative report and does not proceed to
restore/readback, preventing a later heartbeat from being misattributed to the
same turn. `live26` is retained as provider-compatibility negative evidence
(`actions[1]` malformed and no durable marker before the bounded window).

## Latest Goal completion gate — 2026-09-09

The pinned snapshot now rejects an explicit Goal Protocol v2 `state=done` when
an active Goal has no terminal durable ledger and successful recorded action
batch. This closes a stale-provider false-completion path: the Goal becomes
`blocked`, never `complete`. Focused policy tests: 9 passed; snapshot
verification: 348 files, digest
`fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33`.

The fresh live14 disposable profile proved the negative path: real native
write/read succeeded, the local provider emitted `state=done` without the
required ledger patch, and JAWL blocked the Goal. This is a safety acceptance,
not an unattended-pass claim. Evidence:
`runtime/unattended-goal-soak-live14-20260909.json`.

The follow-up live15 disposable profile passed one complete unattended cycle
with the real local Ollama provider: exactly one native write, native readback,
terminal ledger (`completed`, empty pending/next-action/blockers), direct
`state=done`, SHA/postcondition verification and native cleanup. No unexpected
tools were observed and the unattended lease was revoked in the final report.
This closes a one-cycle live acceptance only; multi-cycle soak and provider
restart/recovery remain open. Evidence:
`runtime/unattended-goal-soak-live15-20260909.json`.

The live16 two-cycle attempt did not pass: the provider emitted an empty
non-wait response before any native action, leaving the Goal in `waiting` with
an initial ledger until the 300-second goal timeout. The harness failed closed
and the disposable profile was stopped. This exposed an autonomous-liveness
gap, now fixed in the pinned loop: missing action plus no explicit
`state=wait` receives at most three bounded repair wakes, then becomes
`blocked`. Evidence:
`runtime/unattended-goal-soak-live16-20260909.json`.

The bounded-repair behavior is now live-verified by live18; the first
multi-cycle unattended soak is closed by live22, while provider-restart
recovery remains open.

Live17 did not reach Goal execution because the real local provider exceeded the
180-second startup heartbeat budget during its second boot ReAct request;
Companion was never exposed and all disposable processes were cleaned up.
Evidence is limited to `runtime/instances/goal-live17/logs/main.log` and
`runtime/instances/goal-live17/logs/startup/startup_error.log`; this remains a
provider-latency finding, not a product-pass claim.

Live18 then passed the bounded-repair acceptance with a 300-second startup
budget: the provider first omitted the terminal ledger, JAWL scheduled a
bounded continuation, the provider completed the ledger, and native
postcondition/cleanup passed. No unexpected tools were observed and the
unattended lease was revoked. This is still a one-cycle acceptance, not a
multi-cycle soak. Evidence:
`runtime/unattended-goal-soak-live18-20260909.json`.

Live21 exposed a separate false-completion path during a two-cycle attempt:
the provider wrapped `state=done` inside the terminal-message tool, and the
compatibility gate initially treated that communication-only tool as action
evidence. The pinned loop now excludes terminal send/read communication tools
from completion evidence and the focused regression test
`test_terminal_message_wrapper_is_not_action_evidence` passes. The live21
report remains negative evidence; a fresh multi-cycle live run is still
required after this correction. Evidence:
`runtime/unattended-goal-soak-live21-20260909.json`.

Live22 passed the first real two-cycle unattended soak after that correction.
Both cycles used only the expected native writer/reader pair, reached a
terminal ledger and direct `state=done`, passed independent SHA/postcondition
checks, produced exactly one target write, had no unexpected tools, completed
native cleanup, and revoked the ROOT unattended lease. This closes the
multi-cycle unattended acceptance for the current local provider; provider
restart/failure recovery during unattended work remains a separate open gate.
Evidence:
`runtime/unattended-goal-soak-live22-20260909.json`.

The connected P0 recovery gates themselves remain accepted by the existing
live artifacts: provider failure after a durable native effect is restored and
read back in `runtime/provider-failure-native-recovery-current-v11.json`, and
restart during active native inference is accepted in
`runtime/restart-inference-acceptance-2026013829Z.json`. The remaining open
item is the stronger unattended variant that combines provider/JAWL failure,
checkpoint reconciliation and no duplicate side effect.

## Live2D/presentation verification — 2026-09-09

An isolated Companion instance was started on disposable ports `2467/8866`
with the staged Mao Pro bundle. The real browser smoke passed and reported
`Live2D e:on m:on l:on`; the asset validator reported `renderable: true`,
zero missing references, eight expressions, physics, pose and display metadata.
The target release profile also passed with `--require-live2d`. A direct POST
to the presentation state endpoint returned `405`, and its state contained no
session token, CSRF token, policy or chat-history fields. The disposable
instance was stopped after the checks.

This proves the isolated browser/presentation contract, not the whole desktop
avatar product. OBS is not installed or running on the current machine, so
real OBS Browser Source capture, alpha compositing, click-through, DPI and
multi-monitor behavior remain unverified. Evidence:
`runtime/live2d-smoke-production-slice-20260909.png` and
`runtime/target-release-live2d-20260909.json`.

The real presentation smoke passed with the staged Mao Pro bundle:
`runtime/live2d-smoke-production-slice.png`. The browser reported a visible
canvas and active expression, motion and lip-sync capabilities. This closes
the renderer-load slice only; transparent desktop window, OBS capture,
multi-monitor/DPI and long-run presentation acceptance remain open.

After composition extraction, a disposable rerun on ports `2399/8877` loaded
the same Mao Pro model with 20 manifest references and zero missing files; the
browser again reported `Live2D e:on m:on l:on`. Evidence:
`runtime/live2d-composition-smoke-20260909.png`. This remains browser-renderer
evidence, not real OBS capture or desktop-window evidence.

## Earlier Goal compatibility slice — 2026-09-09

The pinned JAWL snapshot now has a narrow fail-closed fallback for local
providers that return a legacy empty action envelope after verified native work:
completion is accepted only when the durable ledger is terminal, has no pending
step/next action/blocker, and every recorded action outcome is `success`. A
successful tool result alone can never produce `done`. Focused policy tests:
6 passed; snapshot verification: 348 files, digest
`89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d` (historical
digest before the explicit `state=done` gate).

The live rerun `runtime/unattended-goal-soak-live12-20260909.json` remains
negative: the real GPU1 JAWL profile successfully performed the native write
and read, but the local Gemma timed out on the following ReAct request and left
the durable ledger in `initial`; the harness correctly did not infer `done` and
failed the cycle after 300 seconds. The same run measured startup inference
latency above 120 seconds for the roughly 10k-token prompt. No unattended or
production claim is closed by this run.

## One-sentence answer

Это уже рабочий интеграционный прототип с несколькими принятыми connected
срезами, но ещё не production-ready продукт. Главный риск теперь не в
отсутствии отдельных API, а в том, что доказательства пока распределены по
разным профилям и не закрывают долгий unattended/runtime сценарий.

## Что реально принято

| Контур | Факт | Evidence |
|---|---|---|
| JAWL-native text/action | Correlated text, native write/read, SHA postcondition, recoverable cleanup | `runtime/latency-gate-20260908.json` |
| RU voice UI | 3 browser capture turns через Qwen3-ASR → JAWL → Tera → playback/avatar; повтор после duplicate-speech fix также passed | `runtime/browser-voice-e2e-20260909-qwen-asr.json` |
| Voice → native | Voice session correlation дошла до native journal и postcondition | `runtime/voice-native-correlation-acceptance-20260907.json` |
| Memory API | remember → revise → restart → recall с новым значением | `runtime/memory-restart-acceptance-20260906.json` |
| Barge-in | Browser playback cancellation и второй turn | `runtime/browser-barge-in-20260907-strict-retry3-gap9.json` |
| Recovery | Fresh live restart during inference после durable effect: mid-flight restart, matching SHA, exactly-one native write; provider-failure recovery также принято на baseline | `runtime/restart-inference-acceptance-2026013829Z.json`, `runtime/provider-failure-native-recovery-current-v11.json` |
| Packaging | Installed wheel smoke вне source cwd | `runtime/clean-install-acceptance-20260908.json` |
| Regression | 360 Python tests после durable Goal Ledger intent/reconciliation и integrated-native launcher/profile changes; полный gate также прошёл 16 HTTP E2E, browser interaction, synthetic mic и diff check | `scripts/run_full_gate.ps1` (exit 0) |
| Regression correction | Latest full gate passed 380 Python tests, 16 HTTP E2E, browser interaction at six viewports including 320x740, synthetic mic gate and diff check | `scripts/run_full_gate.ps1` (exit 0) |
| Browser UI | Chat interaction, synthetic audio lamp, and all six desktop/tablet/mobile viewport checks passed; WebAudio resume is bounded | `runtime/browser-interaction-e2e.json`, latest `run_full_gate.ps1` exit 0 |
| GPU1 local provider | Изолированный Ollama на `11435` обслужил Gemma через physical GPU1; live browser voice 3/3 прошёл после bounded legacy-wrapper normalization | `runtime/browser-voice-e2e-20260909-gpu1-schema.json`, snapshot `54648188…` |
| Connected daily profile | Один реальный профиль прошёл memory remember/revise → 3 voice turns → native write/read → JAWL restart → canonical recall → recoverable cleanup | `runtime/connected-daily-acceptance-20260909-r3.json`, `runtime/connected-daily-voice-20260909-r3.json` |
| Full Access policy/catalog | Native JAWL levels 0–3 representative checks, level 3 write, emergency-stop/reset, ROOT lease issue/revoke, 93-skill catalog и HostOS/HostTerminal/DebugBroker probes | `runtime/native-policy-levels-0-2-20260909.json`, `runtime/native-policy-level-3-20260909.json`, `runtime/native-catalog-matrix-full-access-20260909-r2.json`, `runtime/native-namespace-full-access-20260909-r2.json` |
| Integrated Full Access launcher | Явные profile switches `-NativeAccessLevel 0..3` и `-EnableDebugBroker`; реальный level-3 disposable launch, полный 0→3 catalog и 8 native namespace probes | `runtime/native-catalog-full-access-launcher-20260909-r2.json`, `runtime/native-namespace-full-access-launcher-20260909-r2.json` |
| Native supervisor wiring | Opt-in `-EnableSupervisor`: native InstanceManager owns start/stop, launcher roots are shared with supervisor, startup race and stale marker cleanup are bounded | `runtime/supervised-profile-acceptance-20260909-r3.json` |
| Native supervisor crash gate | Valid ROOT lease permits one bounded child restart; revoked lease moves the profile to `crashed` and prevents a third child | `runtime/supervised-recovery-acceptance-20260909.json` |

### Новая recovery-находка (live, acceptance пока не закрыт)

Disposable-профиль `goal-reconcile-live5` реально дошёл до границы
`HostOSWriter.write_file[action_1]`: после убийства profile-owned JAWL процесс
восстановился, native readback подтвердил marker, а heartbeat сам начал
reconciliation. Live-прогон одновременно выявил дефект ledger: последующий
план с локальным `action_1` мог заменить старый intent. Исправление внесено в
pinned snapshot: unresolved entries сохраняются по `(tool, action_id)`, replay
того же identity блокируется, а неоднозначный reconciliation без `tool` не
меняет ledger. Поэтому этот исторический прогон остаётся диагностическим, а
не `pass`; его заменяет свежий crash-boundary E2E на snapshot digest
`89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d`.

### Acceptance update — live crash-boundary is now passed

The diagnostic `goal-reconcile-live5` run above is superseded by the fresh
connected acceptance `goal-reconcile-live8`. Evidence:
`runtime/goal-reconciliation-live-20260909T024434Z.json` (`pass: true`).
It killed only the disposable profile-owned JAWL processes after a real
`HostOSWriter.write_file[action_1]` start, recovered the goal through native
control, observed `needs_reconciliation`, verified the file marker and SHA via
native `HostOSReader.read_file`, rejected premature completion, reconciled the
ledger, completed the goal, and removed the file through native cleanup.

### Acceptance update — unattended heartbeat remains open

The new harness uses the native JAWL `hostos.autonomy.issue/revoke` lease,
records action-journal evidence, checks the independent postcondition, and
cleans up the disposable marker. The first live attempt exposed an adapter
path 400 and was discarded. The second attempt issued a real ROOT lease and
revoked it cleanly, but the temporary `jawl-gemma4-it:latest` provider emitted
no native action and left the Goal in `waiting`; it was cancelled only during
disposable cleanup. Evidence:
`runtime/unattended-goal-soak-live2-20260909-r2.json`.

This first report is a genuine provider/Goal-planning failure, not an
unattended pass. It predates the bounded empty-action guard and remains a
negative diagnostic.

The current snapshot now refuses to leave an active Goal in silent `waiting`
when its Task Ledger has a concrete `next_action`: it requests at most three
bounded provider repairs and records `blocked` if no action appears. This
improves failure visibility, but does not make an incompatible provider pass.

The current rerun passed one real unattended functional cycle on the current
snapshot: the native ROOT lease was issued and revoked, JAWL performed
`HostOSWriter.write_file` and `HostOSReader.read_file`, the Goal reached
canonical `complete`, the harness independently checked the exact marker and
SHA, and native cleanup removed the file. Evidence:
`runtime/unattended-goal-soak-live4-20260909.json`.

This is not an 8-hour soak. Long-run stability, provider outage/crash
reconciliation, and supervised unattended recovery remain release gates.

### Provider model selection update — explicit override, no false readiness

The integrated launcher now accepts `-JawlModelOverride` for disposable
profiles. The override is applied by the native profile configuration step;
unmarked edits to managed `settings.yaml` still fail closed. This makes model
comparison reproducible without changing the owned baseline.

A live probe of
`gemma-4-12b-coder-fable5-composer2.5-v1:latest` reached JAWL startup but the
local Ollama `/v1/chat/completions` and `/api/chat` endpoints returned
`model not found`. The name was still listed by `/v1/models`, while the
manifest referenced blobs absent from the Ollama blob store. This candidate is
therefore rejected as an unavailable provider, not counted as an unattended
acceptance. The disposable profile was stopped and no model was downloaded or
recreated. The existing `jawl-gemma4-it:latest` remains the only connected
local baseline, and its unattended native-action failure above remains open.

## Что ещё мешает RC/production

1. Connected daily slice теперь принят; он не закрывает длительный unattended
   runtime и не является production claim.
2. Connected route timings 5.085/5.944 s — это полный route после startup,
   а не first-audio latency; свежий Qwen-ASR browser repeat дал 9.7–24.9 s
   до первого audio buffer. TTS headers приходили примерно за 15–17 ms после
   final, поэтому основной следующий bottleneck — JAWL/LLM route. Реальный
   realtime SLO ещё не выбран и не измерен.

The native gateway adapter now supports correlated `assistant.delta` events
with final-text reconciliation and provisional-text discard on failure. The
current pinned JAWL snapshot does not emit those deltas, so this is a forward
compatible contract slice, not evidence of token-level realtime.
3. Browser synthetic capture не заменяет физический микрофон, AEC, echo
   suppression, device permissions и hardware/software gate.
4. Native supervisor startup/intentional-stop и lease-gated crash recovery
   приняты на disposable child. Durable action-intent checkpoint теперь
   сохраняется до dispatch и переводится в `needs_reconciliation` после restart;
   bounded `ledger.reconcile_actions` не даёт потерять recovery obligation и
   запрещает ложный `done`. Live side-effect reconciliation при crash/provider
   failure и длительный unattended soak ещё не приняты. Текущий local Gemma
   также оставил live unattended Goal в `waiting` без native action.
4a. Short unattended functional acceptance now passes on current snapshot:
   native ROOT lease issue/revoke, write/read, canonical Goal completion,
   independent SHA/postcondition, and native cleanup. Evidence:
   `runtime/unattended-goal-soak-live4-20260909.json`. The 8-hour soak and
   crash/provider reconciliation remain open.
5. Ambient audio/system sound, T1/T2/JAWL memory consolidation, forget vs
   erasure и attribution пока частично реализованы, но не приняты в long-run.
6. Live2D model smoke работает, но OBS transparency, privacy separation,
   DPI/multimonitor, reconnect и 8-hour presentation soak не закрыты.
7. Vision намеренно deferred: MiniCPM-o RU gate провален, следующий кандидат
   не интегрируется до прохождения `docs/MULTIMODAL_MODEL_GATE.md`.

Legacy `execute_skill` compatibility issue закрыт только для однозначного
Goal-v2 payload и проверен live: это не новый executor и не alias неизвестных
инструментов. Local Gemma остаётся временным baseline; его latency, provider
timeouts и качество tool planning не являются production SLO.

## Правильная последовательность

```text
single connected daily profile
  -> latency/voice interruption truth
  -> Full Access + unattended checkpoint/recovery
  -> ambient + memory consolidation/erasure
  -> Live2D/OBS/LAN privacy hardening
  -> clean install + release/rollback + long-run soak
  -> production claim
```

Новые модели и дополнительные «мозги» не подменяют эти gates. JAWL остаётся
единственным владельцем persona, goals, reasoning, native policy и canonical
memory; Companion — transport/UI/voice/avatar; VoiceMem — bounded sensory
sidecar; внешние VLM/TTS — capability workers.

## Current unattended correction — 2026-09-09

The two-cycle live unattended run is negative evidence, not a release
acceptance: cycle 1 completed, but cycle 2 ended with the local model calling
`GoalSkills.update_goal` while `action_1` was still unresolved. JAWL correctly
rejected premature completion. The harness now treats `failed` as terminal and
its disposable objective explicitly requires a terminal Goal Protocol v2 ledger
patch followed by direct `state=done`; the native `GoalSkills.update_goal`
implementation is untouched. Evidence: `runtime/unattended-goal-soak-live6-20260909.json`.

The fresh live14 run is a separate negative safety result: the provider emitted
`state=done` without that ledger patch after native write/read, and the new
fail-closed gate moved the Goal to `blocked`. The harness therefore did not
count it as a pass. Evidence:
`runtime/unattended-goal-soak-live14-20260909.json`.

The next live rerun must prove two completed cycles, exactly one target write
per cycle, independent SHA/postcondition checks, native cleanup, and no
unresolved ledger action. Until that evidence exists, unattended heartbeat is
not a production claim. A subsequent disposable `live8` startup attempt also
failed the strict startup heartbeat because the local Gemma emitted repeated
greeting actions instead of a terminal startup cycle; Companion was not
exposed as ready. No working profile or production baseline was changed.

### Long-run provider variance — 2026-09-09

The first requested eight-hour Ollama attempt was stopped fail-closed after
11 cycles: cycles 1–10 passed, while cycle 11 completed the native write/read
and then the provider refused to emit the direct Goal Protocol v2 terminal
envelope, claiming that `GoalSkills.update_goal` was required. That claim is
contrary to the pinned JAWL contract: after a durable terminal ledger patch,
`state=done` is the canonical compact response and `GoalSkills.update_goal` is
not a native side-effect action for this acceptance task. The run is therefore
negative provider-compliance evidence, not an infrastructure pass. Cleanup of
the marker, disposable profile ports and unattended lease succeeded. Evidence:
`runtime/unattended-qwen-ollama-8h-20260909.json` and
`runtime/long-soak/qwen-ollama-unattended-8h-20260909/orchestrator-summary.json`.

The soak objective now states this protocol precedence explicitly, forbids both
`GoalSkills.update_goal` and `set_current_goal`, and independently checks the
returned terminal ledger, required completed step, empty pending/blocker state,
and all-successful last action batch. The eight-hour rerun remains open until
the model demonstrates stable compliance over the full duration. Corrected v2
run `qwen-ollama-unattended-8h-v2-20260909` is currently active on disposable
ports 8770/2368/8767; no pass is claimed before its final report.
