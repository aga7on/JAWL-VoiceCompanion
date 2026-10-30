# Порядок стабилизации и восстановления

Сверка: **2026-10-10**. Это руководство по последовательности и
инвариантам, **не вторая очередь задач**. После docs-only аудита владелец
разрешил реализацию, новый actual goal создан; первый срез — B0 manifest.
Текущие задачи: [TODO](../TODO.md); состояние: [STATE](STATE.md);
критерии: [TECHNICAL_AUDIT](TECHNICAL_AUDIT.md); карта: [README](README.md).

## Почему прежний R1–R4 нельзя просто повторить

Сентябрьский recovery plan описывал проблемы конкретного профиля: discovery/
HostOS blocklist, corrupt context patch, recall failures и ранний voice path.
Позднее появились owned snapshot, native recovery/checkpoint, реальные memory
и disposable action slices, затем GigaAM-only и Electron/VRM. Исходные
измерения/исправления целиком сохранены в
[архиве](history/2026-10-10-before-docs-consolidation/INDEX.md).
Старое ограничение «Vision не выбирать» и цель Live2D не задают нынешний продукт.

| Историческая область | Что сохраняем | Что проверять сейчас |
| --- | --- | --- |
| R1 delivery/tools/context |Owned snapshot/hash, managed defaults/overrides, native discovery/policy, sandbox paths |B0 effective profile/port/model/defaults drift |
| R2 turns/memory |Canonical types, terminal/correlation, bounded context/retry, revise/restart recall |B3 current combined semantic scenario, P persistence/erasure |
| R3 voice |Actual UI capture/playback owner, stage timings, real RU provider route |B1 Stop/worker; B2 partials/device/echo/duplex |
| R4 effects/recovery |Durable intent до side effect, reconciliation перед retry, native task authority |B3 voice interruption continuity, B4 current8h unattended |

## Последовательность безопасного runtime-среза

1. **B0: установить baseline.** Сверить tracked/dirty code, pinned snapshot,
   actual launcher/profile/ports/model/context. Readiness проверяет нужную
   модель и способность работать по JAWL contract, не просто listening socket.
   Архивировать/сравнивать config перед миграцией, overrides не терять.
2. **B1: остановка и ownership.** Capture lease и audio generation имеют
   конкретного владельца. Stop освобождает его ресурсы, worker отменяется по
   реальному контракту. Перебивание озвучки не удаляет durable goal.
3. **B2: один реальный разговор.** ≥3RU synthetic questions через actual app
   и реальные GigaAM/JAWL/TTS; затем physical mic/echo/duplex/barge-in.
   Transcript и смысл ответа обязательны. Cold/warm stage latency отдельно.
4. **B3: один реальный опыт.** Persona/fact correction → содержательный recall →
   поручение → native effect → postcondition → task update → restart.
   Повторить с voice Stop и отказом provider без слепого повторного действия.
5. **P/U/A: повседневная полнота.** Память/чувства, единая панель и art идут
   принятыми срезами, не через массовую замену frameworks/providers.
6. **B4: эксплуатация.**8h disposable unattended, отказ workers, lease/revoke,
   morning journal, LAN/OBS, clean install/restore/rollback и общая матрица.

Срез должен приносить один проверяемый результат; не запускать сразу
пересекающиеся изменения20агентов. Независимые code/art/документальные
дорожки допустимы, интеграцию принимает координатор.

## Правила восстановления

- Durable intent фиксируется **до** side effect; после сбоя неопределённый
  эффект требует reconciliation, не автоматического blind retry.
- Native JAWL владеет task/action ledger, authority, supervisor и ROOT lease.
  Companion не выполняет запасной локальный executor при bridge outage.
- Отдельный run/generation/audio fence защищает от stale speech и frames,
  но не заменяет durable recovery и не доказывает exactly-once всех tools.
- Speech Stop, turn cancel, task stop и emergency revoke различаются.
  Просьба замолчать не отменяет поручение; emergency stop прекращает execution.
- Истечение/отзыв полномочий не обходится моделью. Ночной профиль заранее
  разрешён владельцем и покрывает выбранный интервал.
- External observations/files/web не authority. После restart сохраняются
  source/validity и effective permissions, а не только текст сводки.

## Проверки и ограничения

Provider-failure после real native effect, goal reconciliation и supervisor
lease recovery имеют ранее сохранённые PASS; не объявлять их отсутствующими.
Но они не доказывают arbitrary crash внутри syscall, все native tools,
current voice Stop continuity или8h soak.
Transport abort не доказывает завершённый worker; HTTP200/openURL не
доказывает выполненное поручение.

Для live действий — отдельный owned runtime и disposable targets;
JAWL-Coding/VoiceMem/RE read-only. Не создавать там pycache/config/logs.
Не менять системные процессы/соседние порты. UAC/TTD EULA не принимать за пользователя.
Секреты/TTD/raw recordings в reports не включать.

Каждый runtime-срез завершается применимыми gates, redacted evidence,
обновлением STATE/TODO/CHANGELOG и честными OPEN. Docs-only срез требует
только документальных проверок. Новый goal регистрируется лишь по явному
поручению; status в Markdown не означает активную задачу продукта.
