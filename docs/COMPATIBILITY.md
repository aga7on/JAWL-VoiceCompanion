# Совместимость и runtime-профили

Documentation-only reconciliation (no runtime execution): 2026-10-10. Последнее сохранённое
runtime evidence — 2026-10-05; новые запуски не выполнялись. Эта матрица
разводит выбранный профиль, source defaults и принятую приёмку. Она не
сертифицирует все сочетания. См. [README.md](README.md), [STATE.md](STATE.md),
[TODO.md](../TODO.md) и [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md).

## Профиль и evidence

| Слой | Выбранный профиль / текущее состояние | Source defaults и предел доказательств |
|---|---|---|
| Desktop | Electron shell, 3D VRM через three-vrm | Наличие renderer не означает приёмку полного UX, OBS, DPI/multimonitor или длительного soak. Live2D/Mocari удалены; legacy markers не являются renderer. |
| LLM | Hikari Bonsai-2 27B PQ2_0 на GPU1 — выбранный brain | Это выбор профиля, не доказательство, что каждый launcher default ему соответствует или что provider/tool контракт принят на всех сценариях. |
| Vision | Bonsai worker на 8986 — выбранная/configured vision lane | Не является приёмкой всех OCR, grounding и desktop-action цепочек. Launcher default может выбрать другой worker. |
| ASR | GigaAM v3 only | Нет альтернативного ASR fallback. ASR не captioner и сам по себе не даёт affect/speaker capability. |
| TTS | TeraTTSv2 `ru_f1`, 9889 — default; OmniVoice selectable | Выбираемый provider не равен принятой provider quality/cancel capability. Sentence streaming не является token-level TTS. |
| Memory | JAWL — canonical durable owner; VoiceMem — sensory/context | T1/T2 process-local; manual promote реализован; durable automatic consolidation OPEN. |
| Windows/browser | UIA, WASAPI и desktop adapters доступны по соответствующим путям | Конкретные OS/build/device permissions, BrowserAdapter openURL/UIA и long-running profile требуют отдельной acceptance. BrowserAdapter не полноценный CDP. |
| Attachments | Backend presence/route может быть доступен | Это не доказывает интегрированный Electron desktop attachment UX. |

### Selected profile ≠ launcher defaults

Source inspection показывает известный drift, описанный отдельным B0 пунктом
в текущем `TODO.md`:

| Source | Обнаруженный default | Как читать |
|---|---|---|
| `scripts/run_coding_server.ps1` | Port 8986, Bonsai-27B Q1_0 | Legacy coding/chat server default; не выбранный Hikari brain и не доказательство vision acceptance. |
| `scripts/run_integrated_profile.ps1` | Vision URL 8983, model `qwen3-vl` | Launcher default; не выбранная Bonsai 8986 vision lane. |
| `scripts/run_local_bonsai_integrated.ps1` | Control port 2467, `RunSeconds = 60` | Изолированный launcher defaults; не обычный control port 2367 и не длительный soak. |

Эти строки фиксируют source defaults, а не факт запуска. Смена defaults или
скрытая синхронизация документации с ними не подразумевается. Проверять
актуальное соответствие выбранного профиля и launcher — отдельная задача из
TODO.

## Профили

| Профиль | Смысл | Статус |
|---|---|---|
| demo/mock | UI и deterministic contract behavior | Не настоящий JAWL-компаньон. |
| provider-test | Прямой LLM adapter в Companion | Non-agentic; не сохраняет native JAWL persona/tools. |
| integrated-attended | JAWL, voice, memory, native policy, Electron VRM | Отдельные реализации/evidence существуют; целый профиль и desktop UX оцениваются по текущему STATE. |
| integrated-unattended | Тот же JAWL, Full Access/lease без per-action prompts для разрешённых задач | Native-owned 8h soak PASS (24Oct r29); полная integrated-unattended и 24/7 acceptance OPEN. |

Profile manifest должен фиксировать версии/runtime/model/ports/data dirs,
data-class consent и capabilities. Его наличие само по себе не является
clean-install acceptance.

## Проверки

Developer gate и его исторические результаты см. в [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md)
и [STATE.md](STATE.md). Для docs-only обновления gate не запускается; текущая
проверка ограничивается Markdown-ссылками/согласованностью и diff hygiene.
Fake HTTP, synthetic media, configured/HTTP 200 и launcher defaults не
заменяют real provider, real device, desktop UX и production acceptance.
