# Совместимость и runtime-профили

Актуально: 2026-09-05. Это инвентаризация/цель, не сертификация всех сочетаний.
[PRODUCT.md](PRODUCT.md), [STATE.md](STATE.md), [RELEASE.md](RELEASE.md).

## Уровни совместимости

| Слой | Известно / заявлено | Что ещё подтвердить |
|---|---|---|
| Companion package | Python requires-python ≥3.10; core stdlib; ранее gate на Python 3.14.6 | Matrix всех заявленных версий, clean installed startup вне repo |
| Windows live | Цель Windows 10/11 x64, UIA/WASAPI/desktop | Конкретные OS/build/device permissions, DPI, долгий профиль |
| JAWL | Native gateway/control/memory additions в dirty external checkout | Pinned compatible dependency, owned runtime, handshake |
| VoiceMem | Отдельный Python environment и JSON-lines sidecar | Версии моделей, cache/memoryspace location, реальный RU путь |
| ASR/TTS | Внешние Qwen-ASR, Qwen-TTS, Tera workers | Полная pipeline latency, capabilities, cancel/recovery |
| Graph memory | Зависит от native Kuzu/runtime | Import-only stub не accepted Graph RAG; отдельный 3.11 профиль не сертифицирует 3.14 |
| 2D | Fallback встроен, Live2D runtime/model внешний | Лицензия, версии bundle, общий renderer/OBS |
| Vision | Adapter присутствует | Постоянная модель отложена владельцем |

Не переносить версию Python core на PyTorch/VoiceMem/JAWL без проверки.
Веса не поставляются в repo/wheel; см. пути и выбор в PRODUCT.

## Профили

| Профиль | Смысл | Статус |
|---|---|---|
| demo/mock | UI и deterministic contract tests, dry-run | Default launcher, не настоящий компаньон |
| provider-test | Прямой LLM adapter в Companion | Non-agentic, не сохраняет JAWL persona/tools |
| integrated-attended | Один JAWL, voice, memory, native policy, 2D | Отдельные slices есть; целый профиль не принят |
| integrated-unattended | Тот же агент, explicit Full Access/lease без per-action prompts для разрешённых задач | Ночная recovery/8h acceptance открыта |

Один profile manifest должен фиксировать версии/runtime/model/ports/data dirs,
data-class consent и capabilities. Это P0-A, не готовая команда installation.

## Developer gate

```powershell
cd G:\AI\JAWL-VoiceCompanion
python -m pip install -r requirements-dev.txt
.\scripts\run_full_gate.ps1
```

Gate предпочитает .venv, иначе сообщает выбранный python. Он проверяет compile,
non-E2E, fake-provider HTTP E2E, synthetic mic/Node и diff.
Проверка только документации не требует установки зависимостей/запуска gate.
Реальные профили отдельно по [матрице](TECHNICAL_AUDIT.md#приёмочная-матрица);
запускать их лишь в разрешённых owned runtimes, не в protected upstream.
