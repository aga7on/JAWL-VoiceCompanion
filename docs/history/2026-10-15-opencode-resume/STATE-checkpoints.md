# Текущее состояние — 15 октября 2026

## Возобновление OpenCode в Codex — 15Oct

- Прочитана сессия `ses_ec36a8f41ffe6wjzIAbHN7DnXG` из `session_v2/session_message`;
  последняя остановка — недельная квота провайдера. В Codex зарегистрирован
  active tool goal: автономно выполнить доступную часть TODO D1–D6.
- Исправлен desktop smart-barge-in: незаданный флаг оставлял прежнюю отмену
  на любом gate onset; `\b` не работал для русского текста. Теперь onset только
  начинает наблюдение, explicit interruption/содержательная речь отменяет
  свой playback; fallback считает voiced PCM, а не время после шума.
- Короткий ack проходит обычный flush/final ASR и смену identity, затем
  `suppress_backchannel=true` подавляет только подтверждённое поддакивание,
  не создавая brain turn/memory event. Старые buffers не переиспользуются.
  RU unfinished tail удерживает endpoint до2200ms; явный законченный вопрос
  допускает380ms. Это bounded heuristic, не принятый trained full-duplex.
- Focused:36 Node voice/input lifecycle +18 Python streaming/policy PASS.
  Physical Fifine/echo/full duplex остаются OPEN.
- Первичный полный pytest:979 PASS/5 FAIL. Четыре fixture-отказа устранены
  переносом sys.path до импорта в helper supervisor. Пятый выявил реальную
  гонку: Job active=0 раньше, чем descendant process handle стал signaled.
  Model-free probe воспроизвёл50/50; после фикса0/50.
- Cleanup теперь сохраняет handles проверенных членов exact Job до terminate
  и ждёт их сигналов плюс active=0. При неудаче retry сохраняет identities;
  temp WAV/замена worker допускаются после reap.39 focused process tests PASS,
  включая немедленный WaitForSingleObject(0), foreign control и retry.
- Первый full gate PASS:888 unittest/66 pytest/16HTTP/109Node и оба browser
  harnesses. Он стартовал до правки drain; финальная проверка после неё OPEN.
  Изолированный console+brain bootstrap и synthetic desktop voice browser PASS.
  Receipts: `runtime/resume-owned-console-20261015.json`,
  `runtime/resume-desktop-voice-e2e-20261015.json`,
  `runtime/resume-job-drain-probe-20261015-before.json` и `...20261015.json`.
- Прежние169–240ms в истории не являются latency полного JAWL: harness
  возвращал заданный/эхо-текст вместо настоящего brain turn. EG2 timing
  отдельных энкодеров не доказывает распознавание музыки или замену VLM/ASR;
  в test6 разрыв vision top2 всего0.0021. D1/D2/H3/H4 не закрыты этими цифрами.
- Real-model ordinary startup и3/3 полных голосовых хода PASS:
  `runtime/resume-local-voice-20261015-attempt2.json`. Реальные Hikari/GigaAM/
  OmniVoice, synthetic WAV вместо physical mic; stream drafts3/3, EOF и
  non-silent playback до конца. Исправлен launcher harness `--ui app`: прежний
  default legacy `/` отвергался строгой проверкой redirect на `/app`.
- `runtime/resume-local-latency-20261015.json`: voice/end dispatch→первый
  WebAudio start11.495/6.972/12.553с; это endpoint proxy, не конец речи.
  LLM steps3.4–5.1с, voice/end response→звук2.1–2.5с. Target1–3с не принят.
  Native terminal skill уже запрашивает early terminate; дополнительного
  completion LLM после terminal в3 traces нет. Нужен plain-chat20 benchmark.
- Native supervised recovery control-plane PASS после исправления fixture
  readiness (живой PID ещё не гарантирует запись generation marker): действующая
  ROOT lease разрешает restart, revoke блокирует следующий, cleanup PASS.
  Receipt `runtime/resume-native-recovery-20261015-attempt2.json`; это cheap
  child test, не полная production supervised модельная приёмка.

Ветка: `dev/daily-companion-20261014`, базовый HEAD `0e53329`.
Dirty worktree владельца сохранён, нового release commit нет.
Ближайшая цель: [ежедневная версия](DAILY_PLAN.md). Очередь: [TODO](../TODO.md).
Подготовка ветки и документов не исправляет runtime и не является live acceptance.

## Последние проверенные результаты

- Full gate `runtime/gate-turn-context-20261014.json`: exit0,
  875unit/66pytest/16HTTP/104Node +6legacy browser/8desktop checks.
  Synthetic regression, не гарантия живого разговора.
- [R6 receipt](../runtime/live-voice-turn-context-20261014-r6.json): TERMINAL FAIL.
  Три полных озвученных ответа, четвёртый native turn.error; browser ожидал TTS
  до timeout. Cleanup всех пяти owned listeners/Jobs PASS по receipt.
- Первый звук11.245/12.396/33.346с от начала тестового хода, включая входную речь.
  Обработка voice/end4.389/4.986/27.640с. Не выдавать первую метрику за паузу
  после окончания речи. Physical mic/full duplex/24x7 не приняты.
- R6 source baseline362/SHA6721866f391c0236fa5f6b6dfb933afcb78de0063dd72eb459952d49a6ce5610.
  Это входы прежнего прогона, не автоматически baseline новой ветки.

## Первый блокер

`scripts/run_owned_jawl_console.py` устанавливает delivery/context hooks
в console process. Native `src/web/agent.py` запускает `src/main.py` отдельным
Popen process; supervised path также требует отдельной проверки.
Process-local monkeypatch не переносится в новый Python process.
Установка hooks в actual brain НЕ доказана. Console probe это не проверяет.
Улучшение отдельных R6 ходов нельзя приписывать этим hooks.
D1-01: owned brain entry + proof child identity/install, оба режима запуска.

## Существующая основа

Есть native JAWL, реальные voice turns, streamed audio/Stop/stale fences,
ASR partials, owned worker lifecycle, VRM/панель, sensory adapters.
Открыты стабильность ответа/latency, физический mic/echo, всегда видимый
персонаж с bubble UX, полезный постоянный sensory context/инициатива,
полный action/memory сценарий и8h эксплуатация. ASR не понимает музыку.

## Текущий выбранный профиль

Hikari Bonsai-2 27B PQ2_0 GPU1; GigaAM v3/crispasr CPU;
OmniVoice9890 default, Tera9889 selectable. VRM active asset сохраняется.
Vision8986 opt-in; наличие конфигурации не current RU screen acceptance.
Effective значения брать из manifest/local override. Соседние порты не вытеснять.

## Подготовка новой ветки

Старые планы/checkpoints/датированные отчёты сохранены byte-for-byte:
[архив](history/2026-10-14-daily-reset/INDEX.md). Контракты, runtime prompts,
модели, данные и текущий исполняемый код не менялись при подготовке.
Старый tool goal при проверке имеет status=paused и незавершённую широкую цель.
Новый objective подготовлен в DAILY_PLAN. Попытка create_goal после подготовки
отклонена: `cannot create a new goal because this thread has an unfinished goal;
complete the existing goal first`. Новый tool goal НЕ создан. Прежняя широкая
цель не выполнена; фиктивно отмечать complete нельзя. Доступный API не имеет
cancel/replace/resume. Нужен сброс/замена прежней цели средствами продукта;
после этого зарегистрировать objective из DAILY_PLAN. D0-04 остаётся открытым.

Проверка подготовки: SHA256 всех29 архивных файлов совпали после переноса;
62 активных документа прочитаны как UTF-8,268 локальных ссылок ведут на
существующие пути; git diff --check exit0 (обычные предупреждения CRLF).
Архивировано27 документов и2 standalone Needle3 probe. На прежних путях
15 исторических документов оставлены короткие ссылки. Текущие launchers/tests
сохранены. Проверка не включает исторические anchors и runtime acceptance.

## 14 Oct 2026 — D1 owned launch wiring

- Confirmed `run_owned_jawl_console.py` enforces owned `JAWL_*` paths, verifies pinned snapshot, installs native delivery/context hooks before console startup, and sets brain child entrypoint to `run_owned_jawl_brain.py`.
- Fixed `tests/test_owned_jawl_console.py` fixture to stub both `src.web.server` and `src.web.agent`; prior failure was an incomplete module stub, not a runtime import failure.
- Targeted D1 verification: `test_native_jawl_delivery`, `test_native_jawl_turn_context`, `test_owned_jawl_console` — 35 tests PASS. CodeSee `f-profile-launch` step `jawl` now references owned console and its wiring test; validator passes with 61 pre-existing length warnings.
- D1 remains partial: no live owned brain child/session was launched or accepted yet, no 20-turn delivery run. Preserve all pre-existing dirty files and use an unused disposable child profile for next smoke.
## 14 Oct 2026 — owned launcher smoke on clean snapshot

- Root cause of prior snapshot rejection: earlier native snapshot imports/connected runs wrote generated `logs/*.log` into the read-only pinned snapshot. Historical changelog already records the same incident. No source cleanup was attempted.
- Fixed direct snapshot test fixtures to route all JAWL paths into disposable temp profiles (`test_jawl_goal_recovery`, `test_jawl_react_policy`). Their focused tests pass.
- Built a new isolated 348-file snapshot using `stage_jawl_source.py`; hashes matched pinned sources exactly (`fa7587…`). Added `JAWL_SOURCE_ROOT`, restricted to a child under `runtime/jawl-sources` and still guarded by strict `verify_jawl_snapshot`, to owned console/brain launchers for clean staged snapshots.
- Fixed the owned-console acceptance harness to pass the selected source/cache into its sanitized child environment.
- Live isolated console acceptance PASS: startup 2.159s; exact Windows Job ownership confirmed; native auth 401, cancel-before-turn 200, cancelled tombstone rejects turn with 409; listener gone after cleanup. No model/agent/device was started.
- Remaining D1 gap: no actual brain child bootstrap or live terminal final/error turn has been proven; the acceptance scope above does not cover that.
## 14 Oct 2026 — actual brain-child bootstrap verified

- Added opt-in `JAWL_BRAIN_BOOTSTRAP_ONLY=1` branch after source verification, isolation checks, and delivery/context hook installation, before native `src.main` import.
- Extended isolated acceptance to launch the real owned brain entrypoint as a child process. Clean 348-file staged snapshot verified by strict manifest. Brain child PID 24788 exited 0 and emitted both initialization/probe-complete markers; no model/native main started.
- Combined live acceptance PASS: console startup 2.141s; exact Windows Job ownership; auth 401; cancel 200; cancelled-turn tombstone 409; console listener gone after cleanup; brain bootstrap exit 0.
- D1-01 is verified. D1-02/03 still require real user-turn final/error and repeated text/voice delivery acceptance.- Correction: the isolated bootstrap smoke proves the owned child entrypoint and hook installation, but it does not prove both integrated ordinary/supervised production modes. D1-01 remains partial until those two launch paths are exercised.
- Integrated launcher now supports `-JawlSourceRoot` only under the managed snapshot root, resolves canonical paths, verifies manifest, and passes the source to the JAWL child. PowerShell parse and 49 focused tests pass.
## 14 Oct 2026 — clean snapshot selection on launchers

- `run_integrated_profile.ps1` and `run_daily_profile.ps1` now accept a source snapshot only after canonical path resolution under `runtime/jawl-sources`; both set `JAWL_SOURCE_ROOT` before prepare/preflight and production process startup.
- `prepare_daily_profile.py` uses the same root-confined source when computing managed-file provenance. `preflight_jawl_runtime.py` resolves and strictly verifies that source and compares profile manifest identity.
- Added CodeSee refs for daily launcher, prepare, and preflight. PowerShell parsers and focused source/profile tests pass (65 tests in latest combined run).
- This provides a supported route to use the clean 348-file staged snapshot without modifying the contaminated read-only pinned source. Actual integrated ordinary/supervised launch modes and live connected text acceptance remain unverified.- 14 Oct 2026 live supervised acceptance: launched an isolated profile with clean snapshot `d1-probe-20261014-a`, unique ports, and selected model `gemini-4-argon`. Production launcher reached JAWL startup, but the initial model heartbeat timed out and exhausted its single retry; launcher correctly refused readiness at 180s. The acceptance harness stopped JAWL gracefully and verified registry/profile, supervisor markers, and all test ports were clear. No user profile was touched. The harness now records `startup_heartbeat_timeout` explicitly; successful supervised readiness remains unverified.

## 15 Oct 2026 — Repo hygiene, Harmonized Architecture & Chameleon UI (D3 foundation)

- **Repo hygiene:** Removed untracked throwaway probes and artifacts (`desktop/%SystemDrive%`, `tool-call-proof.txt`, `scripts/copy_configs.py`, `scripts/patch_settings.py`, `scripts/test_launcher.py`, `scripts/test_live_text_turn.py`, and duplicate untracked `config/settings.yaml` / `config/interfaces.yaml` that shadowed `config/jawl/*`), while preserving all active dirty worktree changes (`run_owned_jawl_brain.py`, launcher/profile scripts, and tests).
- **Harmonized Architecture & Horizon Roadmap (`H1–H5`):** Documented in [HARMONIZED_ARCHITECTURE_AND_ROADMAP.md](HARMONIZED_ARCHITECTURE_AND_ROADMAP.md) and linked in `TODO.md`, `docs/BACKLOG.md`, and `docs/README.md`:
  1. Single Chameleon UI (`Compact HUD Mode` ↔ `Studio Drawer Mode` + `?mode=obs` in `desktop/app.html`);
  2. Three-tier temporal agent architecture (Layer 1: 15–50ms Game & Latent Reflex Layer, Layer 2: 0.5–1.5s Fast Duplex Conversational Lane, Layer 3: Async JAWL Deep Task/RE/Modding Lane);
  3. VAD-free full-duplex speech via `DuplexCascade` micro-turns + `OmniVoice` streaming chunks;
  4. `EmbeddingGemma 2` (`eg2`) multimodal sensory cortex (Zero-Decoder Visual Probe, Audio-Visual Vibe Fusion for co-watching anime/movies & listening to music, 20ms VRM latent reflexes, semantic scene-change trigger, and compact vector episodic memory).
  5. Three JAWL JSON-cycle acceleration patterns (`Speech-First` field order, `Stream-Before-Close` incremental TTS dispatch, and `Single-Step Fast-Exit` in `ReactLoop`).
- **D1-01 supervised & ordinary owned brain wiring:**
  - Fixed supervised launch gap: `scripts/run_owned_jawl_supervisor.py`, `scripts/register_supervised_profile.py`, `scripts/run_owned_jawl_console.py` (`agent._supervised_manager`), and `scripts/run_integrated_profile.ps1` now all bind `InstanceManager.entrypoint` to `scripts/run_owned_jawl_brain.py` instead of unhooked `src/main.py`.
- **Chameleon UI & VRM motion improvements (`D3` foundation):**
  - Added `Compact HUD Mode` (`body.compact-mode`, floating `.hud-dock` with `🎙`, `⏹`, `📌`, `⚙️`, header toggle button, `Ctrl+Shift+M` shortcut, and Electron IPC `jawl-window-mode` resizing between `360×540` Always-on-Top and `1060×720` Studio Drawer) and `?mode=obs` (`body.obs-mode`) directly to `desktop/app.html`, `desktop/app.js`, `desktop/panel-preload.js`, and `desktop/main.js` without reloading the WebGL context.
  - Added distinct `thinking` (`working`) procedural pose in `desktop/avatar-motion.js` and `desktop/app-scene.js` (upper-chest contemplation lean + forearm/hand pose) and multi-vowel lip-sync modulation (`aa`, `oh`, `ee`) in `applyLipSync`.
  - Grouped `desktop/app-settings.js` by human-centric capabilities (`🧠 Мозг и Личность`, `👁 Чувства и Мультимодальность`, `🔌 Инструменты и MCP-мосты`, `🛠 Инженерия и Реверс`).
  - Verification: 56 focused Python tests (`pytest`) and 43 Node desktop tests (`node --test`) + CodeSee validator all PASS.


## 15 Oct 2026 — Codex brain identity / native gateway trials

- r1: ordinary4/20, explicit turn.error after malformed JSON; cleanup/cancel/reconnect passed.
- r2: full object schema plus SDK wrapper failed sampler initialization; strict startup refused readiness. Owned jobs cleaned.
- r3: full native schema without SDK wrapper7/20; repeated actions exhausted2048 tokens.
- r4: generic object grammar20/20 under the old harness, but journal audit found2/4/2 finals in three turns. That series PASS does not prove one delivery. Provider fault also incorrectly counted replay history.
- r5: fixed delivery guard and harness. Ordinary20/20 plus provider loss/restart/recovery passed; all24 journal turns have exactly one terminal. A real batch contained several terminal actions, with one delivery. Supervised20/20 passed but cleanup retained native supervisor.lock; overall r5 remains FAIL.
- Native SystemInstanceLock.release closes/unlocks but retains the lock file. After exact owned Job drain, the driver now removes only the captured dead supervisor PID marker and refuses foreign/live markers. Separate r5 marker cleanup receipt retained.
- r6: supervised20/20, exact brain identity/hooks/Job, cancel/reconnect and complete marker/port cleanup PASS. All22 journal turns have one terminal. No physical capture or audio acceptance in these HTTP/SSE series.
- Receipts: runtime/owned-gateway-series-20261015-r1.json through r6.json; runtime/owned-gateway-checkpoint-20261015.json; runtime/gateway-series-lock-cleanup-20261015.json. Native pinned snapshot unchanged.


## 16Oct — native work, policy refusal and owned soak smoke

- Agent-work r5: file/read/SHA, browser open, form save with one POST and fresh native observation, remember, revise and restart/recall PASS. Last policy case FAIL: native sandbox denied all writes but ReAct repeated the same attempt15 times without a terminal reply.
- r6 FAIL before actions: two protocol-error ticks, finish_reason=length, ~1965 output tokens each. Diagnostics inspect structure/counts only, never print private reasoning. r7 FAIL: file was written and its SHA reported, but requested fresh native read was skipped. These failures remain evidence; no full D5 PASS is claimed.
- Owned policy completion hook observes PermissionError only from actual native HostOS security check while registry call runs; correlated request yields once and subsequent batch calls do not execute. Policy, permissions and durable goals stay native. Uncorrelated autonomy and arbitrary error text do not trigger this hook.
- runtime/native-policy-refusal-20261016-r1.json PASS with Hikari: exactly one denied writer attempt, one explicit policy turn.error, outside file absent, later effects absent, exact Jobs/ports cleaned.
- Chat-only object grammar now bounds observation/reasoning/reflection to320 chars each. Active native Goals and uncorrelated cycles retain their budget; arbitrary discovered tool args and Goal v2 fields remain available. This addresses the observed completion consumed by private reasoning, not all model planning errors.
- runtime/full-gate-policy-completion-20261016.json PASS:927 unittest/66 pytest/16 HTTP/109 Node +browser. It predates final chat budget and new soak/voice harness changes; a new major gate is running.
- runtime/native-owned-soak-smoke-20261016-r1.json PASS:180 seconds, native Goal file write+read, one controlled provider failure/error and recovery, temporary ROOT unattended lease revoked, exact Job resource samples and full process/port cleanup. Original narrow journal projection omitted the cross-plan read; durable native journal proves write and read in the same ReAct trace before the harness read. New harness requires that proof explicitly. This is not8h acceptance.


### 16Oct — connected voice20 and8h running

- Latest major gate runtime/full-gate-native-work-soak-20261016.json PASS:932 unittest/66 pytest/16 HTTP/109 Node and both browser harnesses. Subsequent queue/policy acceptance projections covered by focused tests; no repeated major gate for harness-only changes.
- Voice r1 failed before ASR: clean env omitted standard Windows browser-discovery variables. Those OS-only variables restored, isolated owned Edge probe PASS. Voice r2 real GigaAM/Hikari/OmniVoice /app20/20 PASS with three WAV fixtures repeated, drafts20/20, body EOF and full non-silent playback, exact Jobs/ports cleanup. runtime/owned-voice-series-20261016-r2.json and runtime/owned-voice-latency-20261016.json retain proof. Dispatch proxy p50/p95=8.338/11.964s (min6.377/max13.286), not physical speech-end; first turn separate, remaining19 not20 warm sample.1–3s goal unmet.
- Eight-hour native Goal/Heartbeat/Companion soak launched16Oct09:59:53UTC, expected17:59:53UTC (20:59MSK), status=running. First Goal write→fresh same-trace read and one provider failure/error/recovery PASS. Temporary ROOT lease remains enabled for the active test and must be revoked on completion. No audio/physical-device acceptance claimed.
- Profile turn-series-ordinary-24679b3fd5; checkpoint runtime/gateway-series-5eaa9d15dfe9/soak-checkpoint.json, launch receipt runtime/native-owned-soak-8h-start-20261016.json, final report target runtime/native-owned-soak-8h-20261016-r1.json. Owned code baseline241 files captured at launch, no subsequent code/prompt edits while soak runs. Tool goal remains active; full8h and cleanup are pending.


### 16Oct — latency stages and isolated cache candidate

Voice20 stage evidence now at runtime/owned-voice-stages-20261016.json:22 LLM calls on20 turns, per-turn LLM total p50=6.226s, native other0.189s, HTTP residual0.384s, response→WebAudio1.088s. No private context exported. Prompt cached tokens8017 on all22 calls, median prompt14641; prefill/decode/GPU contention not separately measured. Actual binary help and GGUF qwen35 header recorded in runtime/llama-checkpoint-capabilities-20261016.json.

Isolated worktree runtime/experiments/d2-cache-worktree-20261016 seeded from current dirty code. Opt-in cache controls candidate,13 focused/4 subtests and CodeSee validator PASS; reviewable patch/receipt in runtime/d2-cache-candidate-20261016.*. Not promoted and no real-model benchmark performed. Main241-code-file baseline unchanged while8h soak remains running; specific unified exec handle96825 was polled live. Full objective remains active.


### 16Oct — cache benchmark measurement ready

The isolated worktree now contains native numeric timing preservation, warm20 exact turn/trace/request projection and A/B/B/A comparison with matching model/window/GPU/prompt-bank/cleanup requirements.30 focused tests/54 subtests and CodeSee validator PASS. Actual native hook bootstrap PASS (no model), native SDK retains timing extras. Candidate patch applies cleanly to main with git apply --check; no promotion or real-model benchmark performed.

Existing worktree checkout snapshot had a hash mismatch and remains untouched. New experiment snapshot jawl-20261016-cache-baseline is a348-file verified copy of active fa7587eb0d202e44a72d71d3c9d823a76a3b3f4a84cbc4547f5037757da1df33, selected explicitly via owned --source-root. Main snapshot/source unchanged. Preparation receipt runtime/d2-cache-benchmark-preparation-20261016.json, reviewable805-line patch runtime/d2-cache-benchmark-candidate-20261016.patch.
