# Текущее состояние — 14 октября 2026

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
