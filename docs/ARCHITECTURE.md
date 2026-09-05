# Архитектура единого агента-компаньона

Разбор prompt-модулей JAWL, повторной отправки `SOUL` и правил переноса:
[JAWL_PROMPT_ARCHITECTURE.md](JAWL_PROMPT_ARCHITECTURE.md).

Актуально: 2026-09-05. [PRODUCT.md](PRODUCT.md) задаёт результат,
[STATE.md](STATE.md) — фактическую готовность. Ниже целевые границы и
подтверждённые кодом адаптеры; наличие схемы не означает завершение интеграции.

## Одна платформа, один агентный контур

```text
Микрофон → gate/ASR ───────────────→ пользовательский turn
                    └→ VoiceMem ─→ контекст/наблюдения
Системный звук → сегменты/ASR ─────→ ambient buffer/triage
Экран/UIA → capture/[будущий VLM] ─→ наблюдения/Attention
                                             │
Панель/голос → Companion Gateway ──────────────┤
                                             ▼
                         JAWL: persona, память, Heartbeat, задачи, ReAct
                             │                        │
                       JSON ответ                native policy 0–3
                             │                        │
                    TTS + avatar state        HostOS/Terminal/Debug/MCP
                             │                        │
               Панель · отдельное окно · OBS     Windows/приложения
```

Companion — интеграционная часть того же продукта, не замена JAWL и не
«вырезание агента». Отдельные процессы изолируют тяжёлые зависимости.
Единый пользовательский профиль запуска/остановки пока предстоит завершить.

## Согласованный цикл вместо параллельных «мозгов»

В прочитанных локальных JAWL `docs/architecture.md` и
`docs/yaml/settings/sql/drives.md` уже есть state L0, memory L1,
interfaces L2, core L3, общий EventBus и Heartbeat. Их используем как
отправную точку, не имитируя мозг буквально.

Целевая эволюция — один цикл выбора поведения:

```text
Observation → attention/context snapshot → JAWL decision
    ↑                                      ↓
Memory/task/state update ← verified outcome ← native action / expression
```

Это целевой поток, не новый wire API и не утверждение, что каждый переход
сейчас интегрирован. Распределение уже существующих обязанностей:

- Sensory workers извлекают признаки/текст, normalizers добавляют время,
  источник и корреляцию. Ни worker, ни сенсорный timer не запускает свой ReAct.
- Attention сокращает/ранжирует события; Heartbeat решает когнитивное пробуждение
  и учитывает drives/задачи. Это не два независимых планировщика личности.
- TurnArbiter обеспечивает речь/отмену/приоритет транспорта, не выбирает цели.
  ResourceGovernor ограничивает ресурсы, не ведёт второй цикл мотивации.
- JAWL Context Builder читает bounded snapshot текущего фокуса, задачи,
  наблюдений и recall. Долговременный источник истины — native memory/tasks;
  frontend и sidecars получают только нужные проекции.
- Один валидированный выбранный response state проецируется на text/voice/avatar.
  Feedback о playback, tool outcome и interrupted состоянии возвращается
  в соответствующий owner; старый snapshot не перекрывает новый.
- Проверенный результат меняет task/episode, consolidation отбирает опыт.
  Самоотчёт модели «я сделала» не заменяет результат инструмента/проверку.

Перед добавлением нового механизма составить карту перекрытий JAWL/VoiceMem/
Companion: что оставить, отключить в профиле, адаптировать или заменить.
Решение должно уменьшать дублирование и улучшать наблюдаемый сценарий, а не
сохранять фреймворки целиком любой ценой. Число процессов — вопрос dependency/
crash isolation, не количество личностей.

Drives — ограниченные подсказки инициативе, не источник прав или повод
занимать CPU/тревожить владельца. Реальные мотиваторы/параметры сначала
оставить в существующем JAWL; новые вводить лишь с поведением, бюджетом и тестом.

## Владение состоянием

| Компонент | Владеет | Не должен делать |
|---|---|---|
| JAWL runtime | Персона, факты/дневник/задачи, Heartbeat/ReAct, провайдер главной LLM, registry/policy/audit | Делегировать власть model-controlled полям ответа |
| Companion | UI/API, turn transport, очереди ASR/TTS, transient sensing, presentation, ресурсные приоритеты | Второй мозг, второй tool registry или durable persona DB |
| VoiceMem sidecar | Голосовые наблюдения и дополнительный recall по контракту | Независимо изменять характер; задерживать final-ASR ответ холодной загрузкой |
| ASR/TTS/VLM/triage workers | Ограниченный inference с явными capabilities | Выполнять инструменты или самостоятельно утверждать факты |
| Presentation | Рендер состояния персонажа | Токены control plane, управление ПК или второй аудиовывод |

Компоненты affect/speaker/speculative recall — возможности контракта, не
подтверждённые функции выбранного VoiceMem акустического профиля.

## Где находится код JAWL

`G:\AI\JAWL-Coding` и `G:\AI\VoiceMem` — внешние reference/upstream,
не неявные write-targets. В текущем JAWL checkout есть изменённые и untracked
gateway/memory/autonomy файлы. По git status нельзя назначить им автора.
Проверки на таком checkout не доказывают совместимость с чистым upstream.

Целевой путь: зафиксированная версия совместимого JAWL и собственный runtime
с config/data/logs/cache. Если нужен перенос native additions в owned fork/
dependency, сначала инвентаризация diff, лицензий и согласование способа.
Не откатывать, не копировать секреты и не «чинить» protected upstream автоматически.
Версия/capability handshake и воспроизводимая установка — P0 в TODO.

`G:\RE` остаётся внешней нативной toolchain. Junctions `x64dbg`,
`x64dbgMCP-source`, `ghidra_12.1.2_PUBLIC` не заменяются копиями.

## Диалог, JSON и конкуренция

Нативный путь: `POST /api/companion/turn`, SSE
`GET /api/companion/stream`, точная отмена turn. События коррелированы
`turn_id` и `event_seq`; финал — валидированный ResponseEnvelope.
См. [JAWL](contracts/jawl.md), [ответ](contracts/response-envelope.md).

JAWL provider JSON/tool-envelope и UI ResponseEnvelope — разные уровни.
Непустой plain-text ответ, обёрнутый Companion, не доказывает сохранение
эмоций, tool calls и поведения JAWL. Смена Big Pickle на QWB/local выполняется
в JAWL provider path и проверяется по контракту. `--llm-url` в Companion —
явный non-agentic test mode, не регулярная платформа.

JSON используется для управления, текстовых наблюдений и метаданных.
Текущие transport-контракты местами несут bounded base64 PCM/WAV и image_url;
это совместимость, не требование кодировать все медиапотоки в JSON.
Новый binary transport допустим лишь при измеренной пользе.

Приоритет: emergency stop → пользователь/отмена речи → интерактивный turn →
фоновая задача → ambient/консолидация. TurnArbiter управляет откликом, JAWL —
жизнью задач. Нельзя потерять поручение только потому, что пользователь сказал
новую фразу. Replay-dedup событий не означает exactly-once побочных эффектов;
повторные mutations требуют native idempotency/reconciliation.

Нативные lifecycle summaries могут приходить после действия/финала. UI не
должен выдавать их за достоверный pre-dispatch progress; реальные streaming
deltas JAWL — отдельная capability, не гарантия наличия SSE.

## Голосовой путь

Browser AudioWorklet → software gate/pre-roll → bounded PCM → ASR final →
transport-only VOICE_TURN → JAWL. Тот же текст идёт в bounded VoiceMem queue,
не дожидаясь её завершения. Очередь — дополнительный контекст; важные обещания
и факты не должны существовать только в droppable transient задаче.

Qwen3-ASR работает после end-of-utterance. Hands-free endpointing есть как
RMS heuristic, true partial streaming и реальные AEC/barge-in не приняты.
Нужны измерения всей цепочки: конец речи → endpoint → ASR → LLM → первый
слышимый звук. Скорость 2–3 слова/с не превращается напрямую в LLM tok/s.

Желаемый основной TTS — Qwen3-TTS 0.6B Base/clone, быстрый профиль — Tera.
Нынешние workers выдают complete WAV; Companion умеет sentence streaming.
Отмена HTTP/playback ещё не гарантирует остановку inference и освобождение
worker. Нужны capabilities и явный fallback, не фиктивные эмоции.
См. [voice](contracts/voice.md), [tts](contracts/tts.md).

## Ситуационная и долговременная память

Звук ПК не является микрофоном владельца. В целевом обычном профиле capture
включён после первичного выбора источников/разрешений, с видимой паузой/отзывом;
нынешний opt-in код ещё предстоит привести к этому поведению.
Raw media ограничены и transient. CPU/RAM triage возвращает attributed
наблюдения и кандидаты, JAWL решает консолидацию. Планируемый авто-режим после
согласия не означает автоматическое принятие чужой речи за факт.

Сейчас ambient ASR завершается при flush/stop; длительное наблюдение требует
segmenter с ротацией сессий, backpressure и измерением потерь. T1/T2 находятся
в RAM и не обеспечивают неделю памяти после перезапуска.
JAWL structured_memories содержит версии, provenance, validity и дневник
`journal:YYYY-MM-DD`; задачи не дублируются. Доступность graph backend зависит
от конкретного environment, импорт-заглушка не равен реальному Graph RAG.

Default-output WASAPI смешивает приложения. Без per-app attribution нельзя
обещать надёжное исключение звука частного приложения по одному foreground
window. Пауза/отдельное устройство/выбранный источник — явные варианты до
полноценной реализации. Подавление self-TTS по времени может убрать и
одновременно звучащую чужую речь. См. [SECONDARY_MEMORY.md](SECONDARY_MEMORY.md).

## Действия, экран и автономность

JAWL — единая authority для HostOS, Terminal, Debug Broker, MCP и browser.
Level 0 — default. Изолированный CDP browser/workspace дают полезную работу
внутри native policy; browser profile не заменяет OS sandbox. Общий desktop
требует соответствующих native прав. Аккаунты и автономные публикации получают
явный scope; результаты внешних mutations сверяются перед retry.
В bridge mode отказ native route не вызывает local fallback. Представительский
каталог HostOS/Terminal/Debug не является полным каталогом всех MCP providers.

Full Access сохраняет все настроенные нативные возможности, unattended
убирает per-action prompts для разрешённого профиля. Emergency stop, сроки
lease, OS/UAC/EULA и выбранные исключения сохраняются. При сомнении после
сбоя проверять итог действия, а не автоматически повторять его.

UIA/CLI/API позволяют делать полезные дела без VLM. Экранная capture/Vision
граница уже есть, окончательная модель отложена. Observation token,
координаты и postcondition нужны для действия по изображению; прежний кадр
после собственного клика может устареть — многошаговый цикл требует свежего
наблюдения, а не бесконечного повтора старого плана.
См. [HostOS](contracts/hostos.md), [native bridge](contracts/jawl-hostos.md).

## UI, окно, OBS и ресурсы

Основная панель — сцена/диалог/задачи с настройками, а не вывод внутренних API.
Планшет/телефон используют адаптивную версию той же панели. Явный LAN-профиль
добавляет HTTPS и вход перед control UI/API, сохраняя session/CSRF/origin;
настройка сертификата и устройства описана в [LAN.md](LAN.md).
Персона/черты и журнал работы должны быть доступны из неё. Control origin
2367 изолирован от presentation origin 8766. Встроенное отображение реального
Live2D должно использовать безопасную presentation-границу; текущая inline
CSS-фигура — fallback, ещё не зеркало загруженного model3.

Аудио воспроизводит один выбранный клиент; окно/OBS получают только состояние
и amplitude. Backend задачи не зависят от вкладки; текущий browser mic/playback
зависит. Persisted audio owner без браузера — отдельный будущий adapter.

Python stdlib core и небольшие frontend-модули — предпочтительный путь.
Разделение больших файлов по ответственности допустимо без добавления
тяжёлого framework. Бюджеты очередей/RAM/CPU и pause ambient в игровом режиме
измеряются под одновременной нагрузкой, а не по одиночному benchmark.
