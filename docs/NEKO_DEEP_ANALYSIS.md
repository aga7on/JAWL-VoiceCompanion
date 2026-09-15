# Разбор N.E.K.O: почему у них «гладко», а у нас ощущается как поделка

Дата: 2026-09-12. Источник: shallow-клон `G:\AI\N-E-K-O`
(github.com/Project-N-E-K-O/N.E.K.O, ~48 МБ Python, 4581 файл, 799 тестовых
файлов). Сравнение с нашим `G:\AI\JAWL-VoiceCompanion`.

## Вердикт в одном абзаце

Их гладкость — не магия и не «лучше написанный код» по мелочи. Это пять
архитектурных решений, каждое из которых снимает целый класс багов, которые
мы ловим руками: (1) **один постоянный WebSocket** браузер↔сервер для всего
диалога и звука; (2) **постоянная Realtime-сессия** с провайдером, где VAD,
endpointing и перебивание делает протокол, а не наши эвристики; (3)
**LLMSessionManager на персонажа** — одна централизованная машина состояний с
эпохами/генерациями и compare-and-set; (4) **шина между сервисами**
(ZeroMQ PUB/SUB + PUSH/PULL с ACK/retry + outbox), а не HTTP-поллинг; (5)
**дуракоустойчивость как продукт**: circuit breaker, поколения сокетов,
durable-очереди, анти-повтор. У нас всё это было собрано по частям и
разъединено; отсюда каждый наш баг — не случайность, а отсутствие
конкретного из этих пяти паттернов.

## 1. Их голосовой контур: одна сессия, а не цепочка

Их документированный поток (`docs/architecture/data-flow.md`):

```
Client                Main Server              LLM client
connect /ws/{name} -> accept + bind manager
start_session      -> create/connect -------> Realtime API
stream_data PCM    -> stream_data ---------->  (16 kHz)
<- gemini_response deltas
<- audio_chunk + binary PCM frame
<- system: turn end
```

- Один `WebSocket /ws/{lanlan_name}` на персонажа; управление и звук — по
  нему (`docs/architecture/three-servers.md`, `data-flow.md`).
- `OmniRealtimeClient` — постоянная сессия к Realtime API провайдера
  (`main_logic/omni_realtime_client/_transport.py` 206 КБ,
  `_response_arbiter.py` 116 КБ — арбитраж ответов!). Провайдер сам делает
  VAD, endpointing, перебивание, нативный аудиовыход 24 кГц; их сервер
  только ресемплит в 48 кГц для браузера.
- Переключение text↔audio — это **rebuild сессии**, не режим-тумблер:
  «Changing between text and audio is a rebuild, not an in-place toggle».

Наш контур на каждый ход: браузер POST чанков (5/сек) → Companion →
streaming-ASR (процесс) → финальный ASR (ещё процесс, HTTP) → ход (HTTP POST
+ SSE к консоли) → мост консоли (TCP к агенту) → цикл JAWL → TTS (HTTP) →
браузер. **7+ хопов, каждый со своими таймаутами, гонками и состояниями.**
Все наши «странные» баги — из этой топологии:
- «первый ход всегда с ошибкой» — гонка idle→connecting моста консоли;
- gap-курсор SSE — самодельный протокол вместо шины;
- заклинивание входа агента после отмены — нет epoch/поколений и
  восстановления сессии;
- деградация ASR при перебивании — нет арбитра ответов, всё на эвристиках
  гейта.

## 2. LLMSessionManager: одна машина состояний

`docs/architecture/session-management.md`, `main_logic/core/`:
- `manager.py` 34 КБ + миксины: `lifecycle.py` **229 КБ**, `proactive.py`
  **200 КБ**, `asr_runtime.py` **202 КБ**, `tts_runtime.py` 114 КБ,
  `turn.py` 110 КБ. Почти мегабайт оркестрации сессии.
- Явная машина старта: `session_preparing → session_started /
  session_failed`; circuit breaker после 3 неудачных стартов; cooldown.
- **Поколения**: «only the newest connection generation may control it»;
  cleanup проверяет, что сокет актуальный — устаревший сокет не может
  снести новое соединение.
- **Сравнение-и-подстановка**: «compare-and-set client into self.session»,
  аудио-эпохи: «Each stream operation snapshots the session and audio epoch.
  Data is discarded if teardown or replacement occurs».
- Порядок входа: буфер `pending_input_data` + bounded `asyncio.Queue`
  (300 записей, при переполнении дропается самое старое).
- Hot-swap: прогрев новой сессии в фоне, кэш входного аудио на момент
  свопа, атомарная замена.
- Память — **зависимость старта**, а не «fallback с пустым контекстом»:
  если Memory Server не ответил — старт падает в circuit breaker.

У нас: состояние размазано между inline-JS фронтенда (97 КБ), web.py (2 КБ
строк), gateway.py, jawl_web.py, мостом консоли и агентом JAWL. Каждый наш
баг последних дней — следствие того, что нет единого владельца состояния
сессии и эпох: старый стрим подчинял себе новый, зомби-агент переживал
рестарт, отменённый ход клинил очередь.

## 3. Шина между сервисами, а не HTTP-лапша

`docs/architecture/three-servers.md`:
- Три сервера: Main (48911), Memory (48912), Agent (48915/48916).
- Main↔Agent: **ZeroMQ** — PUB/SUB события (`:48961`), PUSH/PULL надёжная
  очередь `analyze_request` (`:48963`), обратный канал ACK/результатов
  (`:48962`). «Agent→Main delivery has no HTTP fallback» — доставка
  гарантируется протоколом, а не ретраями по таймауту.
- Memory: outbox, event log, cursors, reconciliation, decay — восстановление
  после сбоев встроено в дизайн.
- Проактив доставляется через `proactive_delivery.py` (44 КБ) с durable
  outbox: сообщение не теряется при рестарте.

У нас: proactive-очередь в памяти (+ файл состояния только для кулдауна);
ходы через HTTP+SSE с самодельными курсорами (мы только что чинили эхо
курсора и gap-гонки); никаких ACK/восстановления.

## 4. Локальная обработка звука — тоже инженерная дисциплина

`main_logic/voice_input/`: `suppression.py` — «revocable, TTL-bounded
suppression leases» для микрофона (лизы с TTL и идемпотентным release!),
`endpointing/`, `speaker_shadow/`, `workers/`, `registry.py` 15 КБ.
У нас: calibrated gate, duck и turn_policy — полезные, но это эвристики без
модели лизов и без арбитра; отсюда AEC-каша при перебивании.

## 5. Что честно не копировать

- **Их гладкость на 50% — облачный Realtime API** (Gemini/OpenAI-стиль), где
  VAD/endpointing/перебивание — серверные. Мы строим локальный дуплекс на
  CPU; потолок будет ниже при любом коде. Это не отменяет пункты ниже —
  просто ожидания: «как у них» без их провайдера не будет, «сильно
  стабильнее» — будет.
- Их монолит (миксины по 200 КБ) — цена их истории; нам не нужно
  копировать размер, нужно копировать инварианты.
- Plugin-платформа/Steam/Workshop — вне нашего продукта.

## Приоритетный план для нас (по убыванию отдачи)

**P0. СОБРАН 2026-09-12.** Прямой постоянный сокет Companion ↔ агент JAWL:
`src/jawl_voicecompanion/jawl_terminal.py` (`JawlTerminalGateway` +
`JawlChatRouter`), handshake `JAWL_GATEWAY <seq>` с replay по курсору,
`turn_id`-корреляция, cancel-контрол-лайн, переподключение с backoff.
Компаньон теперь держит одно соединение с агентом для ходов (mode
`jawl_terminal_gateway`), консоль HTTP остаётся для памяти/журнала/UI.
Тесты `tests/test_jawl_terminal.py` 4/4 (roundtrip, cancel, reconnect c
replay, turn.error); живой ход подтверждён. Дополнительно: профиль
переведён на `event_acceleration.active_cycle_policy: defer` (автономные
события больше не прерывают ход пользователя — их же пример это
подразумевает). Замечание: локальный Bonsai как мозг отклонён по факту —
Q1-квант ломает строгий JSON-протокол инструментов («Tool protocol error»),
облачный big-pickle стабильнее.

**P0. Прямой постоянный сокет Companion ↔ агент JAWL (терминальный
протокол).** Мы уже доказали на их и нашем коде, что терминальный протокол
несёт `turn_id` и `gateway_event` по одному TCP (`JAWL-Coding/src/
l2_interfaces/host/terminal/client.py`). Companion должен подключаться к
порт-файлу агента сам и держать одно соединение с реконнектом и эпохами,
минуя консоль+мост вообще. Это убивает весь класс наших багов: idle-мост,
gap-курсоры, отмена-клинит-очередь. Оценка: 1-2 сессии. Консоль остаётся
для UI/конфига.
Проверено: сервер агента — `asyncio.start_server` с множествами
`active_writers` и `_gateway_writers` (мультиклиентный по дизайну, порт в
`terminal.port`, loopback без auth), т.е. прямое подключение Companion —
поддерживаемый сценарий, а не хак.
**P1. Session coordinator в Companion** по образцу LLMSessionManager:
явные состояния, поколения сессии/сокета, bounded очередь входа,
circuit breaker, «память как зависимость старта». Оценка: 1 сессия.
**P2. Один WebSocket браузер↔Companion** для чата+аудио (вместо POST на
каждый чанк) — меньше хопов, натуральная отмена/барж-ин. Оценка: 1-2
сессии (переписать фронтенд-транспорт).
**P3. Durable outbox для проактива** (персист очереди + реплей при
рестарте). Оценка: часы.
**P4. Анти-повтор ответов** (их `anti_repeat.py` + `fact_dedup.py`) —
берём идею, не код: детект повторов в генерации и подмешивание «не
повторяйся». Оценка: полсессии.

## Ссылки на доказательства

- `docs/architecture/data-flow.md`, `session-management.md`,
  `three-servers.md` (клон N.E.K.O).
- `main_logic/core/{manager,lifecycle,proactive,turn,asr_runtime}.py`.
- `main_logic/omni_realtime_client/{_transport,_response_arbiter}.py`.
- `main_logic/voice_input/suppression.py`.
- Наши боли: `docs/STATE.md` записи 2026-09-12 (bridge idle, gap-курсор,
  заклинивание входа, AEC при перебивании).
