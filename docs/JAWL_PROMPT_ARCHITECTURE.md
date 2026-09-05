# Prompt-архитектура JAWL и её перенос в Companion

Актуально: 2026-09-05.

Этот документ фиксирует выводы по read-only изучению `G:\AI\JAWL-Coding`.
`G:\AI\JAWL-Coding` остаётся protected reference: файл не является разрешением
изменять upstream или запускать в нём write-producing проверки.

## Короткий ответ

`SOUL.md` и остальные markdown-файлы JAWL — это не случайные документы,
которые модель «читает для справки». Это версионируемая декларация поведения
агента: личность, правила, протокол инструментов, язык и подключаемые
возможности. `PromptBuilder` собирает выбранные модули в system prompt, а
`ContextBuilder` добавляет изменяющийся снимок состояния.

JAWL отправляет system prompt при каждом запросе намеренно. Его ReAct-цикл
восстанавливает полный контекст на каждом шаге после tool call, ошибки,
изменения задачи или перезапуска provider-сессии. Provider session и cache
уменьшают цену повторения, но не являются источником истины. Долговечное
состояние должно оставаться локально у JAWL.

Это не означает, что модель каждый раз заново «рождается» или что ей нужна
вторая память. Повторная сборка — механизм детерминированного восстановления
и защиты от потери правил при смене провайдера.

## Что именно делает JAWL

По исходникам `src/l3_agent/prompt/builder.py`,
`src/l3_agent/context/builder.py`, `src/l3_agent/react/loop.py` и
`src/l3_agent/llm/executor.py` поток имеет две части:

```text
изменяемые markdown-модули
        ↓ PromptBuilder.build()
статический system prompt
        +
L0/L1/skills/heartbeat/goal/наблюдения
        ↓ ContextBuilder.build() на каждом шаге
динамический context snapshot
        ↓
LLM request → tool/action → новый snapshot → следующий LLM request
```

`PromptBuilder` при сборке:

- рекурсивно находит `.md`, исключая `*.example.md`;
- выбирает только один совместимый вариант function-call protocol;
- выбирает язык;
- не включает отключённые optional modules;
- сортирует материалы в установленном порядке;
- соединяет `Personality → Custom → System`.

`ReactLoop` строит prompt в начале цикла, а перед каждым шагом формирует
свежий набор сообщений `system + user(context)`. Это необходимо, потому что
результат инструмента и состояние задачи меняются между шагами. Поэтому
одинаковый system prompt в логах — ожидаемое поведение, а не признак того,
что JAWL не умеет вести сессию.

`LLMExecutor` дополнительно вычисляет хэш статической части и передаёт
`session_id`; QWB может использовать серверную сессию и cache/rebase. Это
оптимизация передачи и latency, а не замена локальной реконструкции.

## Роли markdown-модулей

| JAWL-модуль | Смысл | Решение для Companion |
|---|---|---|
| `SOUL.md` | личность, ценности, стиль речи и отношений | один source of truth, владелец — JAWL |
| `INSTRUCTIONS.md` | границы автономности, память, проверка результата, контекст и протокол работы | перенести в JAWL profile и адаптировать под единый продукт |
| `FUNCTION_CALL*.md` | строгий machine-readable контракт инструментов | выбрать ровно один capability-compatible transport |
| language module | язык и локальные правила ответа | включать по выбранному языку, не дублировать в UI |
| `EXAMPLES_OF_STYLE.md` | калибровка манеры общения | оставить опциональным и ограниченным по бюджету |
| `DRIVES`, `TASKS`, `NOTES`, `PERSONALITY_TRAITS`, `MENTAL_STATES` | отдельные когнитивные/состояниевые возможности | подключать только если функция реально включена |
| `SUBCONSCIOUS`, `HYPOTHESES`, `SWARM`, `TREE_OF_THOUGHTS` | дополнительные режимы размышления | не включать по умолчанию; сначала доказать пользу и бюджет |

Названия файлов не являются универсальным API. Важны их семантика, порядок
сборки, условия включения и версия профиля. Для нашей системы нужен
собственный зафиксированный профиль, совместимый с JAWL, а не копирование
всех файлов из рабочего checkout.

## Что переносим как единый организм

1. JAWL остаётся владельцем личности, целей, Heartbeat/ReAct, durable memory,
   tool registry и policy/audit.
2. Companion остаётся sensory/presentation и transport-слоем: микрофон, gate,
   ASR, TTS, avatar, UI, OBS, bounded observations и корреляция turn/event.
3. VoiceMem поставляет голосовые наблюдения и recall по явному контракту; он не
   меняет `SOUL`, не создаёт вторую persona DB и не запускает собственный ReAct.
4. Native JAWL response сохраняется целиком: текст, emotion/voice/avatar,
   actions, ошибки, `response_id` и корреляция. Plain text допускается только
   для отдельного non-agentic тестового adapter.
5. Любое наблюдение проходит один согласованный цикл:

```text
sensor → bounded observation → attention/context → JAWL decision
      → verified action/expression → memory/task update
```

Так JAWL, Companion и VoiceMem остаются одной платформой с разными
границами ответственности, а не тремя конкурирующими агентами.

## Что не переносим вслепую

- не отправляем все optional markdown-модули всегда;
- не помещаем гигантский статический prompt в быстрый аудиопуть без cache и
  измерения latency;
- не храним долговременную память в provider conversation;
- не позволяем полям ответа модели самостоятельно повышать policy level;
- не добавляем локальный «fallback-мозг», который отвечает параллельно JAWL;
- не считаем наличие SSE, HTTP 200 или заполненного prompt доказательством
  работающей интеграции.

## Экономия токенов без потери поведения

Экономия строится в таком порядке:

- один компактный versioned `SOUL` и один компактный policy/instructions;
- capability-driven включение protocol и optional modules;
- хэш статического prompt и provider cache/session, когда они доступны;
- bounded dynamic context с приоритетами и TTL;
- отдельные короткие sensory events вместо пересылки сырых аудио/видео;
- консолидация памяти вне realtime turn.

Нельзя удалять правила только потому, что они повторяются в запросах:
сначала проверяем cache hit, размер dynamic snapshot и p50/p95 latency.
При смене Big Pickle на QWB, Luna или local provider локальная сборка должна
оставаться достаточной для корректного поведения.

## Минимальные acceptance-проверки

До production-ready нужно доказать через один и тот же Companion:

- изменение `SOUL`/traits/fact видно в следующем разговоре и переживает restart;
- после tool result следующий шаг получает свежий context, а не stale snapshot;
- provider restart/reconnect не теряет policy, correlation и memory source;
- выбран ровно один tool protocol, malformed envelope завершается ошибкой;
- optional module не попадает в prompt, если capability выключена;
- JAWL выдаёт один ответ и один tool execution, без локального дубля;
- voice/text/avatar получают согласованный validated response;
- повторная отправка static prompt измерена и, при наличии поддержки, попадает
  в cache/session;
- ошибка provider не превращается в правдоподобный «успешный» ответ.

Подробные этапы и фактические ограничения остаются в [TODO.md](../TODO.md),
[ARCHITECTURE.md](ARCHITECTURE.md) и [STATE.md](STATE.md).
