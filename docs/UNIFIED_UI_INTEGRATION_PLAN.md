# Единая панель JAWL Companion

Дата: 2026-09-15. Статус: план, не реализованная интеграция.
База просмотра Companion: `24a4fdc4e6cec268ed01c5946e066d304688dcc0`.
Этот документ задаёт очередь интеграции UI; не отменяет незакрытые runtime gates
из [TODO](../TODO.md), [аудита](TECHNICAL_AUDIT.md) и [recovery](RECOVERY_PLAN.md).

## Решение

Одна панель, одна навигация, один разговор, одна библиотека памяти. Не переносим
три приложения целиком в три вкладки. JAWL остаётся владельцем личности, целей,
Heartbeat, инструментов и политики. Companion владеет представлением, голосовым
транспортом и аватаром. VoiceMem является инфраструктурой наблюдений.
Единый интерфейс не требует одного процесса и не оправдывает переписывание
работающего голоса или смену UI-фреймворка.

`/console/` — временный маршрут совместимости. Iframe не является завершением
интеграции: у него отдельные формы, чат, навигация и жизненный цикл.

## Что проверено в исходниках

Оригинал изучается только чтением: `G:/AI/JAWL-Coding/web/index.html`,
`src/web/server.py`, `schema.py`, `config_io.py`. `console_ui.py` — не исходник
браузерной панели. Оригинальная панель содержит Settings, Interfaces, Chat, DB,
Logs; внутри настроек уже есть личность, модели, Heartbeat, память, мотиваторы,
swarm, дерево мыслей, консолидация, рефлексия и забывание.

`schema.py` связывает `data-cfg` с `settings:`, `env:` и `interfaces:`.
Это хорошая основа инвентаризации, но наличие поля в HTML ещё не доказывает
сохранение, применение без restart или работоспособность интеграции.
Companion `src/jawl_voicecompanion/jawl_web.py` уже имеет адаптер памяти,
native policy, каталога и lifecycle; `web.py` содержит `/console/` и
`/console-api/` proxy. Это переиспользуемые границы, а не полная UI parity.

Перед реализацией обязательно сравнить оригинал с owned snapshot
`runtime/jawl-sources/jawl-20260906-daily-v2`: совпадение API не предполагается.
Секреты и живую конфигурацию в отчёты не копировать.

## Приоритетные находки

| Важность | Наблюдение / риск | Решение | Эвристика |
|---|---|---|---|
| Major | Две панели и два маршрута общения могут восприниматься как разные агенты | Один chat/turn owner; старый чат становится совместимым маршрутом, не вторым циклом | H4, H6 |
| Critical, риск миграции | Повторные формы конфигурации могут перезаписать несвязанные поля или права | Один writer на поле, проверка версии, readback, effective state отдельно | H1, H5 |
| Major | TTS/STT и зрение присутствуют в обеих системах с разными возможностями | Общий выбор capability/provider, сохранить лучший Companion pipeline | H4 |
| Major | Копирование исходных вкладок заставляет пользователя знать архитектуру | Навигация по задачам пользователя, внутренние названия в подробностях | H2, H8 |
| Critical, риск миграции | DB wipe, reset emergency stop и обычное выключение речи нельзя объединять | Разные действия, разные последствия, native policy и подтверждения опасных ручных операций | H3, H5 |
| Major | Перенос только видимых scalar controls теряет списки/профили/секреты | Инвентаризация schema + DOM + handlers + routes и round-trip tests | H6, H9 |

Текущий браузер здесь не запускался. Баллы design-review: hierarchy (20%),
consistency (20%), accessibility (20%), usability (20%), responsive (10%),
performance (10%) — **не измерены**, общий балл не вычисляется. Старый скриншот
не подтверждает текущий вид. U0 включает полноценную исходную визуальную оценку.

## Пользовательская структура

```text
JAWL Companion
├─ Компаньон: Live2D + единый чат/голос/вложения
├─ Задачи: цели, ход работы, результаты, остановка задачи
├─ Память: библиотека, поиск, источник, исправление, забывание
└─ Настройки
   ├─ Личность и поведение: характер, Heartbeat, мотиваторы, тихий режим
   ├─ Модели и мышление: провайдеры, контекст, reasoning, swarm, ToT
   ├─ Голос и восприятие: устройства, gate, ASR/TTS, экран, системный звук
   ├─ Персонаж и стрим: Live2D, отдельное окно, OBS, чат трансляции
   ├─ Доступ и инструменты: HostOS 0–3, unattended, coding, MCP, RE
   ├─ Подключения: браузер/CDP, Telegram, GitHub, почта, RSS, календарь
   └─ Система: процессы, хранилища, журналы, диагностика, LAN
```

На главном экране не дублировать навигацию кнопками под персонажем. Чат —
основной путь отправки текста/изображения/аудио/видео/документа; неподдерживаемый
формат честно объясняется. `+`, slash-команды и emoji picker сохраняются.
Ручной vision probe находится в диагностике, не во втором основном чате.

Глобально видны источник захвата, mute, эффективный доступ и аварийный стоп.
«Не беспокоить» означает ограничение инициативных реплик; это не выключение
наблюдения и не остановка фоновых задач. Остановить речь, отменить turn,
остановить goal и аварийно остановить исполнение — четыре явных действия.
На планшете сцена сворачивается; чат и ввод остаются доступны над клавиатурой.

## Карта переноса и владельцев

| Область JAWL | Целевая панель | Владелец / обязательная полнота |
|---|---|---|
| Имя, язык, proactive guidance | Личность | JAWL; не отдельная persona Companion |
| Основная модель, температура, min interval, ReAct, multimodal | Модели | JAWL; provider capabilities и фактическая модель |
| Список моделей, провайдер/прокси, ключи | Модели / Подключения | JAWL config; маскирование, отдельно сохранить/удалить секрет |
| Continuous cycle, heartbeat, timezone, пять приоритетов событий | Поведение | JAWL scheduler; не второй таймер инициативы |
| Глубина ticks, размеры action/result/thought summary | Модели / Контекст | Канонические лимиты JAWL, не простой срез истории |
| RAG, embeddings, vector similarity, graph и SQL caps, hypotheses | Память / расширенные | JAWL; единицы, ограничения и restart semantics |
| Drives: custom, decay, pause, reflection history, правила | Поведение | JAWL; состояние отдельно от настроек |
| Swarm: model, workers, detailed/context steps | Модели / Swarm | JAWL; задачи и результаты в общем Tasks |
| ToT: model, mode, interval, branches, simulations, depth | Модели / Мышление | JAWL; не обещать управление reasoning неподдерживающего провайдера |
| Subconscious: consolidation, reflection, forgetting | Память / обработка | JAWL; VoiceMem только observations/context |
| HostOS, terminal, desktop, coding backend, env/deploy access | Доступ и инструменты | Native policy; сохранённый уровень не equals effective |
| Commands, exclusions, profiles, containers, code graph | Доступ / Coding | Полные list/object-list формы, без потери argv/cwd/ресурсных лимитов |
| Telegram Telethon/бот, media/confirmations, GitHub, email | Подключения | JAWL; сохранить все опции и диагностику недоступности |
| Search/deep research, browser, HTTP, hooks, RSS | Подключения | JAWL; feeds и headers/config не теряются при частичном сохранении |
| Meta/custom skills, MCP servers, Debug Broker | Инструменты | Native catalog/policy; G:/RE не копировать и не изменять |
| Calendar | Подключения / Задачи | JAWL; отличать запись календаря от goal |
| Multimodality/media limits | Голос и восприятие | Согласовать с Companion vision routing, не второй обзор экрана |
| ElevenLabs, Edge, Whisper, списки голосов | Голос / провайдеры | Сохранить как альтернативы; не заменить ими Tera/GigaAM |
| Chat/history/stream, companion turn/cancel | Компаньон | Один native turn; один playback owner; dedup/reconnect |
| Memory, DB stats, SQL/vector/graph/cache folders, wipe | Память + Система / Хранилища | JAWL canonical memory; физическое удаление не equals forget |
| Tick, logs/stream/download, status/journal, start/stop | Система; краткое состояние в shell | Нативный lifecycle, redaction, bounded logs |
| Mic gate, Live2D, OBS, ambient TTL, stream chat | Companion native controls | Не потерять при переносе исходного JAWL UI |

Это групповая карта, не утверждение о проверке каждого поля. U0 обязан выдать
машиночитаемый реестр каждой настройки/операции; без него полная parity не закрыта.
Каждая запись: source revision, key, route+method, handler, type/default/range,
secret, owner, saved/effective, restart, target section, status, test ID.
Статусы: keep / merge / migrate / unavailable / explicitly deferred. Удаление
функции допускается только с отдельным решением владельца, не по вкусу дизайнера.

## API и конфигурация: требования до переноса форм

Учесть исходные группы маршрутов: `/api/config` GET/PUT, `/api/drives` GET/PUT,
`/api/chat` GET/POST и stream; `/api/companion/turn`, cancel, stream;
`/api/memory` GET/POST; `/api/db/stats`, wipe; `/api/tick`;
`/api/logs`, stream/download; `/api/agent/status`, journal, start/stop;
`/api/hostos/policy`, autonomy, emergency-stop/reset, skill;
`/api/debug/skill`, `/api/skills/catalog`, `/api/fs/open`.
При сверке owned версии добавить её дополнительные endpoints, а не ограничить
её возможностями оригинала.

1. Один публичный control origin 2367, типизированные адаптеры к владельцам.
   Не универсальный неограниченный proxy. Presentation/OBS остаётся без control
   credentials на отдельной границе; «одна панель» не означает объединение trust.
2. Настройки читаются у владельца; UI содержит draft, не вторую конфигурацию.
   Писать только изменённые поля, проверять revision, не терять неизвестные поля.
3. Состояния формы: unchanged, dirty, saving, saved, pending restart, effective,
   failed, conflict. «Сохранено» не означает «применено». Без поддержки revision
   сначала добавить контракт, не имитировать безопасную конкурентную запись.
4. Multi-owner save не притворяется атомарным. Показать результат каждой секции,
   дать retry только несохранённой части; native policy не откатывать автоматически.
5. Секрет: unchanged / replace / delete. Маска не отправляется как новый ключ.
   Не хранить credentials в URL/localStorage, логах или OBS.
6. Переключение ASR/TTS/VLM не означает загрузку модели при каждом открытии формы.
   Capability, configured, available, ready, failed — разные состояния.
7. Два клиента/планшет: конфликты настроек обнаруживаются; микрофон/звук имеют
   явного владельца, новый клиент не создаёт второе воспроизведение.

## Дизайн и лёгкость

Направление: спокойная мятная Aero-панель, выразительность у персонажа, ясность
у управления. Сохраняем HTML/CSS/JS, общий CSS token layer и небольшие модули.
Не добавлять React/Electron только ради объединения. Сначала использовать
имеющиеся tokens/components; размеры и palette фиксировать после U0.

Одна семантическая тема: surface/page/panel, text/primary/muted, action,
focus, success/warning/danger, spacing, control sizes, radius, motion.
Матовые читаемые формы; прозрачность ограничена shell/сценой. Статус передаётся
текстом и значком, не одним цветом. Для иконок — существующие SVG, для сообщений
оставляем эмодзи. Прямые подписи вместо «control center» и технического DND.
Поиск настроек понимает старые названия и раскрывает нужную секцию.

Проверка: 320/390/768/1024/1440/1920 px, portrait/landscape, 200% zoom,
длинный русский текст, клавиатура/NVDA, focus return из диалогов,
reduced-motion/high-contrast. Touch ориентир 48 px; text contrast 4.5:1,
крупный текст и значимые controls 3:1. Темная тема, если доступна, тестируется
тем же набором. Lazy-load Live2D и редких секций, bounded/виртуализированный
журнал, один набор подписок. CPU/RAM/DOM/network измерять до и после на одинаковом
профиле; не объявлять ускорение по числу строк.

## Фазы и критерии выхода

### U0 — baseline и точная parity

- [ ] Снять source revisions и сверить оригинал, owned runtime, Companion UI.
- [ ] Собрать реестр всех DOM data-cfg, schema keys, list editors, handler actions
  и endpoints; каждый key/action имеет назначение и test ID.
- [ ] Снять screenshots/interaction baseline всех уникальных экранов и ошибок.
- [ ] Зафиксировать существующие voice/sensory regression blockers отдельно;
  не приписывать их будущему redesign. Проверить gate timebase, flush/session
  boundary и checkpoint сенсорного журнала до связанной приёмки.
- [ ] Зафиксировать текущие config/state contracts, backups и rollback procedure.

Выход: нет неразобранных функций; baseline воспроизводим. Это первый срез.

### U1 — общие контракты

- [ ] Capability/config registry поверх native schema, без дублирования defaults.
- [ ] Partial save, secret semantics, revision conflicts, readback/effective state.
- [ ] Контракт snapshot + instance/event sequence, bounded reconnect/dedup.
- [ ] Test fixtures offline/error/restart/unknown keys/two-client conflicts.

Выход: формы не могут незаметно перезаписать чужие настройки; никаких dual writes.

### U2 — shell и дизайн-система

- [ ] Общие tokens, controls и их applicable states, затем layout и motion.
- [ ] Четыре раздела, settings search, history/deep links, сохранение draft/focus.
- [ ] Согласовать desktop/tablet/mobile макеты на реальных данных.
- [ ] Аварийный стоп доступен вне модальных настроек, права видимы и достоверны.

Выход: новый shell использует существующее поведение; визуальная/a11y приёмка.

### U3 — чтение и диагностика

- [ ] Перенести status/tick/journal/logs/catalog/DB stats с pagination и redaction.
- [ ] Различать offline, stale, loading, empty, failed; давать конкретное действие.
- [ ] Сравнить значения с нативными endpoints, проверить reconnect и длительный UI idle.

Выход: одно место диагностики без второго heartbeat или фонового polling каждой вкладки.

### U4 — настройки, память, подключения

- [ ] Переносить секциями по карте выше; перед каждой миграцией contract tests.
- [ ] Списки/контейнеры/MCP/голоса/ключи проходят round-trip без потерь.
- [ ] Библиотека показывает реальные типы памяти, evidence и provenance;
  create/revise/forget/archive и restart/recall проверены через того же JAWL.
- [ ] Интеграции без credentials остаются видимыми с объяснением; никакой фиктивной ready.
- [ ] Lifecycle, HostOS level/lease/emergency и DB wipe имеют отдельные тесты.

Выход: все перенесённые controls меняют именно владельца; остальные доступны
через временную совместимость и отмечены незавершёнными.

### U5 — единый ежедневный сценарий

- [ ] Один chat/goal entry, native goals/swarm status и краткие отчёты в чате.
- [ ] Голос, отмена, аватар, вложения, memory recall используют общую correlation.
- [ ] Нет второго TTS при открытии console/OBS/планшета; старый звук не воскресает.
- [ ] Голосовое прерывание не отменяет порученную фоновую цель автоматически.
- [ ] Сенсоры и stream chat дают наблюдения; не повышают полномочия.

Выход: разговор → поручение → инструмент → результат → память, включая reconnect,
без потери задачи/двойного эффекта. Не подменять реальный стриминг анимацией текста.

### U6 — отключение старой панели и выпуск

- [ ] 100% реестра функций покрыто native UI и тестами; нет скрытых deferred rows.
- [ ] Поэкранные feature flags позволяют вернуть прежний UI без отката данных.
- [ ] Старые ссылки перенаправляются; убрать iframe/proxy только после parity.
- [ ] `scripts/run_full_gate.ps1`, browser E2E всей матрицы, связанные реальные
  audio/agent/OBS/LAN gates, измерение ресурсов до/после.
- [ ] Design-review шесть оценок и weighted overall; контраст/hardcode lint из kit
  адаптированы к CSS token source, ручной keyboard/NVDA не заменён линтером.
- [ ] Пользовательская приёмка; TODO/STATE/CHANGELOG и руководство согласованы.

Выход: единая панель завершена. Production-ready всего приложения требует также
остальных функциональных/надёжностных gates проекта; UI parity сама по себе недостаточна.

## Порядок безопасного внедрения

Одна секция → отдельный diff → контрактные тесты → browser walkthrough → rollout.
Не менять схему хранения и visual redesign в одном коммите. Не переносить базы
ради UI. Rollback меняет маршрут отображения, не возвращает старую память/права.
Мажорный срез проходит полный регресс. Тестовые удаления/инструменты только на
disposable данных, без записи в protected JAWL-Coding/VoiceMem/RE.

## Использованные навыки

Установлены 19 навыков из https://github.com/plugin87/ux-ui-agent-skills,
commit `ca7bfbe73475702a725ed75fdba9e39448a7a9f1` в
`C:/Users/ARTEM/.codex/skills/<skill-name>`; общий kit сохранён в
`C:/Users/ARTEM/.codex/skills/ux-ui-agent-skills-kit`.
Общие reference directories подключены junctions, не продублированы.
Перед переносом/удалением kit учитывать эти зависимости.

Применены redesign и design-review: Scan → Diagnose → Direct, сохранение
поведения, одна тема, отдельная a11y/responsive приёмка. Использован vanilla-css
adapter. Apply/Verify относятся к будущей реализации, не объявлены выполненными.
Рекомендации навыка по emoji/эффектам не отменяют пользовательский emoji picker
и мятный Aero. Не загружать всю библиотеку навыков на каждый запрос.
