# Delivery specification: законченная платформа и персонаж

Актуализация **2026-10-10**. Основание — требования владельца к русскоязычному
компаньону, автономному агенту и персонажу ≥90% сходства по turnaround.
Это **спецификация результата**, не сам процесс выполнения. Новый actual goal
создан 2026-10-10 по запросу «Действуй по TODO… Goal новый»; первый срез B0.
Завершение не заявлено. Текущий tool-status запрашивается у продукта, не из MD.

[PRODUCT](PRODUCT.md) · [STATE](STATE.md) · [единственная очередь TODO](../TODO.md) ·
[полный остаток/оценка](WORK_REMAINING.md) · [приёмочная матрица](TECHNICAL_AUDIT.md).

## Итог

Один JAWL Companion: персона/SOUL, память, Heartbeat, goals/Swarm/native tools
JAWL; сенсорная инфраструктура VoiceMem; Electron/web панель с VRM, interruptible
русским голосом, настройками и отдельной presentation-поверхностью OBS.
Полезный sandbox0 и явно включаемый Full Access3/unattended.
Чувства включены после первоначальной настройки источников/разрешений,
с паузой/отзывом; наблюдения не становятся пользовательскими командами.

Не требуется монолит в одном процессе, новый тяжёлый framework, второй brain,
Source2 engine, Unity migration, перезапуск удалённого Live2D или новая модель
вместо каждого уже работающего worker. Лучшие Companion-механизмы сохраняются.

## Дорожки и выходы

| Фаза | Обязательный результат | Текущая граница |
| --- | --- | --- |
| B0 baseline |Воспроизводимый actual профиль/модель/порты/readiness/версия |Общий manifest/defaults и fixture preflight добавлены; whole-profile/live/UI/Rust/portability OPEN |
| B1 lifecycle |Один capture/playback owner, bounded buffers, stale-safe cancel/worker release |Desktop synthetic PASS; native Stop≤10s/real worker OPEN |
| B2 разговор |Actual capture→real GigaAM/JAWL/TTS→playback/VRM; RU, latency, physical echo/duplex/barge-in |Actual synthetic mocks PASS; current real provider/device OPEN |
| B3 цельный агент |Persona/memory/task/native effect/postcondition/restart и voice cancel continuity |Ранее recovery/memory/native slices; combined current OPEN |
| P память/чувства |Persistent T1/T2, автоматическая консолидация, erasure, audio/vision context |Adapters/process-local/manual minimum; target OPEN |
| U один UI |Full field/action parity, chat/history/attachments/library/tasks, LAN и OBS |Partial; legacy fallback не удалять до приёмки |
| A персонаж |Art A→E, motion graph/lips/VRMA, cloth/body collision-aware physics |InterfaceV9 limited technical PASS; ≥90 art/full physics OPEN |
| B4 эксплуатация |8h unattended, failures/Stop/revoke, budgets, clean install/rollback |OPEN |
| S развитие |Stream chat/social и принятые research slices |Отдельная будущая интеграция, не внедрено |

Code дорожки можно параллелить по непересекающимся write scopes; coordinator
принимает интеграцию и art. Порядок исполнения — TODO, не новая копия
всех задач в этом документе.

## Definition of Done

- Применимые строки matrix приняты или имеют явное согласованное исключение
  версии; SKIP/N/A не PASS, no silent deferral обязательного scope.
- Один содержательный ежедневный сценарий на реальном выбранном профиле:
  общение/память/поручение/инструмент/проверка/перезапуск.
- Голос: фактический RU transcript/answer/playback, stage cold/warm p50/p95,
  acoustic device duplex/barge-in, настоящая отмена worker и no stale audio.
  Флаг AEC и синтетический тон не доказывают качество ChatGPT Live.
- Task переживает speech interruption; сомнительный side effect сверяется
  до повторного выполнения. Нативные0–3/policy/discovery сохраняются.
- Полезное фоновое восприятие и memory lifecycle проверены; источник/TTL/
  uncertainty и удаление честны; внешний текст не authority.
- Общая панель управляет actual/effective состоянием, не duplicate config.
  Tablet/LAN и current VRM/installed OBS приняты с privacy/one audio owner.
- Персонаж ≥90/100 по [art rubric](CHARACTER_ART_DIRECTION.md), лицо/волосы
  отдельно≥90% максимума, no critical defects и приёмка владельца.
  Geometry/spring helpers PASS не full art/cloth/body acceptance.
-8h disposable unattended с postconditions, worker failure/lease/revoke/Stop
  и morning journal; clean install/restore/rollback и resource budgets.
- Docs актуальны, dependencies/assets/licenses/versions воспроизводимы;
  reviewable release baseline без секретов и случайной потери dirty changes.

До этого production-ready и COMPLETE не заявляются. Запись спецификации не
разрешает захват устройств или изменение protected upstream в текущем turn.
