# Правильный путь развития после аудита 2026-09-06

Это рабочий план восстановления и текущая карта приёмки. R1 уже применён:
owned v2 snapshot создан, context patch удалён, managed profile tooling обновлён.
Аудит: HEAD `1bb3117` и незакоммиченные изменения config/prompt/profile tooling.
Повреждённый context patch удалён после проверки воспроизводимости.
Проверялись код, Git diff и сохранённые отчёты; новые модели и сервисы не запускались.
Продуктовые требования — [PRODUCT](PRODUCT.md), очередь — [TODO](../TODO.md).
Последний полный gate прошёл: 360 Python tests, 16 HTTP E2E, browser
interaction, synthetic mic, Node и diff check. Snapshot verifier остаётся
зелёным на 348 файлах после native action-intent recovery.

## Текущий P0-срез — 2026-09-08

Provider-failure recovery после durable native side effect принято на локальном
Gemma baseline: `runtime/provider-failure-native-recovery-current-v11.json`.
Проверены correlated terminal `error` + non-speakable `final`, восстановление
провайдера, restart JAWL, native readback SHA, exactly-one actual write и
recoverable cleanup.

Для этого acceptance исправлены owned JAWL delivery defects: `turn.error`
теперь публикуется как typed gateway event; gateway socket drain и terminal
EventBus flush bounded. Snapshot verifier проходит: 348 файлов,
`89b73e12f824e843436234b59939996eccdb76b6f9ce0b8693f8006d88c7ed2d`.

The fresh live crash-boundary acceptance is now passed by
`runtime/goal-reconciliation-live-20260909T024434Z.json` (`pass: true`).
The earlier `goal-reconcile-live5` report remains diagnostic history only.
Срез не доказывает arbitrary-tool exactly-once, crash внутри syscall,
долгую unattended-сессию или production readiness.

Старые v6/v7/v8/v9/v10 отчёты — только диагностика: они выявили отсутствие
терминального события, неправильную синхронизацию остановки провайдера и
unbounded writer wait; их `pass` нельзя считать acceptance.

Native Goal Ledger теперь записывает bounded action intent (`in_flight`) до
dispatch. При восстановлении активной цели после процесса, оборванного до
результата, запись становится `needs_reconciliation`: следующая итерация
обязана проверить postcondition и записать `ledger.reconcile_actions` со
статусом `confirmed` или `not_applied`; пока этого нет, `done` отвергается и
recovery obligation не исчезает после нового read-action. Это закрывает
checkpoint/reconciliation contract, но не заявляет exactly-once для
произвольного системного вызова.

После live-проверки найден и исправлен второй recovery-дефект: новые native
планы с локальным повторяющимся id (`action_1`) больше не затирают старый
неопределённый intent. Read/recovery-действия сохраняются рядом с ним,
повтор того же `(tool, action_id)` блокируется до reconciliation, а patch с
повторяющимися id обязан указывать `tool`. Новый snapshot digest указан выше;
live crash-boundary acceptance для этого исправления принят; свежий evidence
зафиксирован в `runtime/goal-reconciliation-live-20260909T024434Z.json`.

## Какое приложение строим

Один агент-компаньон: JAWL владеет личностью, памятью, задачами, решениями и
native policy; Companion обеспечивает удобный веб-интерфейс, голос и 2D;
VoiceMem поставляет сенсорный/эмоциональный контекст. Способность выполнять
поручения на ПК обязательна. Короткий разговор должен обходиться без лишних
действий, а реальное поручение — иметь доступ к нужным инструментам.

Full Access 0–3, unattended, heartbeat, память и последующая интеграция
QWB/local сохраняются. Ограниченный диагностический профиль допустим только
с явным названием и отдельной приёмкой; его нельзя сделать единственным
режимом продукта ради успешного приветствия.

## Подтверждённые проблемы

| Приоритет | Доказательство | Последствие и исправление |
|---|---|---|
| P0 | Owned snapshot ранее имел `set_execution_blocklist(["HostOS"])`, ограниченные prefixes и запрет discovery | Удалено из owned snapshot/config/prompt; native policy 0–3 и live disposable поручение ещё требуют приёмки. |
| P0 | Старый context patch возвращал `corrupt patch ...:76` | Удалён; v2 snapshot содержит 348 файлов и проверяется по manifest/hash. |
| P0 | Прежний `copy_missing` не доставлял обновления в существующий профиль | Исправлено managed hash/backup sync в `prepare_daily_profile.py`; обновление профиля и preflight прошли. |
| P0 | `daily-memory-recall*.json`: пять неуспешных попыток, четыре timeout (240/360/180/150 с), затем SSE EOF | Один удачный ответ не устранил зависания/recall. Найти причину по конкретному turn и стадиям; проверить содержательный ответ и restart. |
| P0 | Browser harness проверяет форму `responses`, читает text и создаёт собственный `new Audio` | Ошибка может быть озвучена и засчитана как прохождение; штатный playback/аватар обходятся. Приёмка должна идти через реальный UI/audio owner и отклонять error envelope. |
| P1 | Prompt требует сохранять любой факт в SQLNotes; запрещает recall при вопросах о себе | Разные слои памяти сведены к заметкам; отсутствие сведений в prompt может скрывать нужный retrieval. Сохранить канонические типы и дать JAWL выбирать bounded recall. |
| P1 | goal_mode/task ledger/subconscious и часть инициативы выключены в baseline | Это диагностические настройки, полнота автономного продукта не доказана. Возвращать функции с проверкой scheduling/task recovery после стабилизации foreground. |

Искусственные ограничения сняты; аудит не утверждает, что native policy и
каждый маршрут HostOS уже прошли live-приёмку.

## Что удалось и что ещё не доказано

`runtime/daily-live-64k.json` подтверждает завершение одного native gateway
turn примерно за 48 с. `daily-memory-write.json` также имеет `pass:true`.
Эти сводки не доказывают содержание сохранённого факта, последующий recall,
браузерный голос и полезное поручение. Счётчики SSE включают несколько turns:
их нельзя читать как число действий именно последнего вопроса.

Предыдущий срез дал работающие интерфейсы ASR/TTS, обработку no-speech,
синтетические акустические случаи, responsive UI и отдельный memory API
restart probe. Сохраняем полезный код; проверяем его в пределах доказанного
сценария. 48 секунд до завершения одного ответа пока не удобное живое общение.

Диагноз переполнения контекста согласуется с предыдущими отчётами о загрузке
LM Studio на ~16k и запросах большего размера. Загрузка 64k устранила один
наблюдавшийся барьер; она не объясняет все последующие timeout и не является
универсальным решением. Текущая доступность модели в этом аудите не проверялась.

## Очередь исправлений и критерии выхода

### R1 — сохранить полноценного агента и воспроизводимость

1. Удалить глобальную HostOS blocklist из продуктового owned runtime/patch.
   Восстановить on-demand discovery. Проверить все обязательные namespace
   (HostOS, terminal, coding/debug, MCP/browser) на обнаружимость; representative
   execution делать только на disposable целях и соответствующем native уровне.
2. Разделить выбор краткого каталога для текущего запроса и полномочия.
   Минимальный prompt не должен изменять registry/policy. Нужные полные
   сигнатуры доступны через bounded поиск; после ошибки неизвестного имени
   выполнять ограниченное исправление плана.
3. Собрать snapshot из известной базы и упорядоченных патчей; сохранить версии,
   хеши и результат проверки. Повторная сборка даёт тот же результат.
4. Сделать prepare/update предсказуемыми: managed defaults отдельно от overrides,
   сравнение исходного/активного hash, миграция с backup и без молчаливой потери
   персональных настроек. Проверить как новый, так и существующий instance.
5. Привязать sandbox paths к instance. Рабочая директория source не должна
   подменять рабочую директорию поручений.
6. Readiness показывает фактическую модель, лимит контекста и профиль.
   Не полагаться на постоянство идентификатора LM Studio с суффиксом `:2`.
   Токенный бюджет включает system/persona, память, каталог, историю и запас
   для результата; количество символов не равно количеству токенов.

Выход: один воспроизводимый профиль; разрешённое поручение достижимо через
JAWL, запрет policy соблюдается; активный config/prompt соответствует версии.

### R2 — завершение реплики и память

1. Проследить конкретный зависший recall: доставка события, очередь heartbeat,
   сборка контекста, provider, tool result, final. Различать ошибку контекста,
   повтор действий, ожидание модели и потерю конечного события.
2. Foreground получает приоритет с безопасной остановкой устаревшей генерации.
   Не повторять выполненные side effects. Ограничить одинаковые бесполезные
   действия и время turn; при исчерпании бюджета выдать понятный terminal status.
   Долгая порученная задача сохраняется отдельно от отменённой озвучки.
3. Оставить прямой ответ для простого разговора; при необходимости использовать
   инструменты и память. Prompt советует экономный план, а native policy
   определяет доступ.
4. Память: Notes — рабочие заметки; structured fact/trait/preference/summary —
   соответствующие устойчивые записи; tasks/ticks/journal — отдельные слои.
   Evidence хранит происхождение. VoiceMem ambient-кандидат не становится
   автоматически фактом о владельце.
5. Через UI создать уникальное предпочтение, исправить его, спросить модель,
   перезапустить профиль и снова спросить. Проверить смысл: новое значение
   используется, старое не подаётся как актуальное. Отдельный GET из базы
   подтверждает хранение, но не влияние на ответ.

Выход: содержательный ответ с актуальной памятью до/после restart; bounded
ошибки и прерывания сохраняют correlation и состояние задач.

Фактическая поправка 2026-09-06: реальный Companion control/API-путь уже
прошёл уникальный `remember → revise → restart → recall` на локальном Gemma;
см. `runtime/memory-restart-acceptance-20260906.json`. Это закрывает только
API/control slice. До закрытия R2 ещё нужны browser-click evidence и чистый
profile acceptance, чтобы старые conflicting preferences не могли исказить
семантическую проверку.

Live native action correction 2026-09-06: browser-session `/api/hostos/execute`
доставил пять операций в JAWL native HostOS на уровне 0; запись прочитана с
совпавшим postcondition и затем удалена штатными native skills. См.
`runtime/native-action-ui-acceptance-20260906.json`. Остались голосовая
команда, task ledger/checkpoint и interruption/recovery.

### R3 — голос через тот интерфейс, которым пользуется владелец

1. Подать минимум три русских WAV в реальный браузерный capture path с темпом
   2–3 слова/с, паузами и тихой речью. Синтетика допустима до теста микрофона.
2. Использовать тот же UI submit/finalization и единственный playback controller;
   проверять видимые сообщения, error/speaking состояния, начало и завершение
   звука и синхронизацию fallback-аватара. Отдельный Audio в harness не заменяет это.
3. Проверять transcript, native turn identity, семантику ответа, отсутствие
   error/cancel envelope и повторов. Сохранять провалившийся turn до остановки.
4. Измерить upload/endpoint, ASR, очередь, LLM TTFT/final, TTS first audible,
   playback end и total отдельно для cold/warm. Для трёх вопросов сохранять
   индивидуальные значения; для устойчивых p50/p95 нужен больший набор.
5. Прервать речь уточнением: старый звук прекращается, поздние chunks отбрасываются,
   новая реплика обрабатывается, порученная задача сохраняется. Проверить
   освобождение worker, а не только отмену HTTP.
6. Partial ASR, semantic barge-in и streaming TTS принимать по реальному
   контракту выбранных workers. Пока их нет, статус half-duplex указывать явно.
   ASR не считать анализатором музыки/тембра. Qwen TTS — желаемый основной;
   Tera — быстрый явно выбранный профиль. Возможности проверять отдельно.

Выход: три полезных голосовых ответа через одну личность, реальный playback
и аватар; испытанные failure/interruption пути с измеренной задержкой.

### R4 — поручение, восстановление и полный gate

Из UI/голоса поручить изменение disposable файла/тестового приложения.
JAWL выбирает native инструмент, выполняет действие, проверяет postcondition,
показывает артефакт и обновляет задачу. Повторить с interruption, отказом
провайдера и restart: сверять эффект до retry, не терять обязательство.

Срез provider failure после durable native effect принят 2026-09-08 в
`runtime/provider-failure-native-recovery-current-v11.json`; поэтому этот
пункт больше не является открытым для проверенного локального профиля.
Остаются расширенные варианты: crash внутри syscall, произвольные native
инструменты, длительная unattended-сессия и stale speech/task recovery.

Разобрать исходный `runtime/full-gate-20260905T101053Z.log:670`:
неожиданный 503 произошёл в
`test_jawl_hostos_control_syncs_native_and_companion_policy` при
`POST /api/hostos/level {"level":3}`. Намеренный 503 в тесте аварийного стопа
и внешний QWB WAF — другие события; ими нельзя закрыть эту ошибку.
Нужна конкретная причина или честный статус unresolved.

После runtime-изменений пройти полный gate и связанный browser/live сценарий.
Отчёт: commit + dirty diff hash, patch/config/model versions, run/turn IDs,
вход → ожидание → наблюдение, stage timings, screenshots, pass/fail/skip.
Три независимых зелёных benchmark не заменяют связанный путь.

## Порядок работы агентов

Координатор проверяет доказательства и согласованность, исполнители получают
непересекающиеся файлы/задачи: owned delivery + tools; turn/memory;
browser/audio acceptance. Проверку интеграции проводить после ревью.
Не выдавать трём агентам один и тот же аудит и не гонять неизменившийся gate.
Для каждого завершённого среза — diff, тесты, ограничения и следующий шаг.

## Готовая формулировка goal

Довести R1 → R2 → R3 → R4 настоящего документа и исходные P0-A/P0-B/P0-C:
воспроизводимый owned профиль с полноценными native инструментами;
три русских синтетических браузерных аудиовопроса через тот же JAWL/реальную
LLM/TTS и единый playback/аватар; UI-изменение факта/предпочтения с влиянием
на ответ и recall после restart; поручение через native инструменты с
disposable изменением и проверенным артефактом; interruption/provider
 failure/restart без дублей действий, stale речи и потери задачи. Проверенный
 local provider-failure slice уже принят; цель теперь требует расширить его
 до crash/unattended и полного связанного production gate.
Сохранить cold/warm timings, correlation IDs, версии/хеши, screenshots,
полный gate и связанный отчёт; расследовать исходный 503 без blind retries.
Обновлять TODO/STATE/CHANGELOG по фактам. Работать только в Companion;
JAWL-Coding/VoiceMem/RE read-only. Использовать имеющиеся модели, Vision
не выбирать. Физический микрофон, настоящий Live2D/OBS, ночная автономность,
stream chat/соцсети и остальные P1–P3 остаются в roadmap.

Попытка зарегистрировать новый goal 2026-09-06 отклонена инструментом:
в потоке уже есть незавершённый goal со статусом `usageLimited`.
Формулировка выше подготовлена для замены через управление задачей в клиенте;
вызов создания не состоялся. Старый goal не объявлен выполненным.

### Live correction — 2026-09-06

The owned JAWL snapshot now uses SQLite WAL and a 30-second busy timeout; its
manifest and snapshot verifier are green. With the local Ollama provider
available, the real Companion barge-in test passed: a newer turn cancelled the
active native turn and completed normally, with no fresh `database is locked`.
Evidence: `runtime/interrupt-acceptance-20260906.json`. The earlier failed
attempt was a provider outage, not accepted as a product result. Remaining R4
work is provider-failure/restart semantics, voice-to-native task execution and
the complete connected gate.

### Current evidence correction — 2026-09-07

The later reports supersede the older partial-status wording above: connected
three-turn voice, memory revise/recall after restart, voice-to-native
postcondition/correlation, strict browser barge-in and Companion restart soak
are now accepted. The active-inference recovery gate is also accepted by
`runtime/restart-inference-acceptance-2026160037Z.json`: restart landed during
inference, the durable checkpoint was recovered, the final read SHA matched disk,
and the native journal proved exactly one real mutation. The browser
`runtime_instance_id` guard remains responsible only for stale local speech; it
is not a substitute for JAWL's native recovery lifecycle.
## 2026-09-08 gate result

The next P0 slice is accepted for the local baseline: a fresh managed profile
was prepared from the pinned JAWL snapshot, its manifest/preflight matched, and
the real Companion → JAWL → local Ollama route completed two correlated native
turns with postcondition and cleanup. Measured wall-clock route times were
`5.085 s` on the first connected turn after readiness and `5.944 s` on the
second consecutive turn.

This does not close voice realtime work. Startup heartbeat warmed the provider,
so the measurements do not represent provider cold-load or first-audio latency;
ASR, streaming TTS, playback cancellation/barge-in, historical 503 diagnosis,
and broader unattended crash recovery remain separate gates.

## 2026-09-09 native supervisor boundary

The integrated launcher now has an opt-in `-EnableSupervisor` path. The native
JAWL `InstanceManager`/`src.instances.supervisor` owns the child lifecycle; the
Companion web console only requests the native `desired_state` transition. The
supervisor resolves `JAWL_INSTANCES_ROOT` and `JAWL_SANDBOX_DIR` from the same
profile environment as the child, preventing a split registry between the
immutable source snapshot and the managed runtime.

The live disposable acceptance passed startup, JAWL heartbeat readiness,
intentional stop, profile cleanup, port cleanup, and stale supervisor marker
cleanup: `runtime/supervised-profile-acceptance-20260909-r3.json`.
This is a lifecycle boundary, not a full unattended claim. The follow-up live
gate now proves the lease boundary itself: a valid ROOT lease permits one
restart, while revocation blocks the next restart and leaves the profile
`crashed`: `runtime/supervised-recovery-acceptance-20260909.json`. The next
required gate is task-ledger/checkpoint reconciliation after an interrupted
side effect, followed by a long disposable unattended soak.
