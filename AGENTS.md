# JAWL VoiceCompanion — инструкции агентам

## Миссия и порядок чтения

Строим **одну платформу агента-компаньона**, не три несвязанных приложения.
JAWL: личность, Heartbeat/ReAct, долговременная память, задачи и нативные
инструменты; Companion: интеграция/голос/веб/2D; VoiceMem: восприятие/контекст.
Не вырезать agentic контур из продукта и не заводить второй мозг.

Перед существенной работой полностью прочитать:
`docs/PRODUCT.md` → `docs/STATE.md` → `TODO.md` →
`docs/TECHNICAL_AUDIT.md`; для изменяемой границы — архитектуру/контракт.
Проверить `git status --short --branch`, выбрать один проверяемый срез.
История и CHANGELOG не переопределяют текущую очередь/замысел.
Последнее явное поручение пользователя задаёт scope: просьба править только
доки не разрешает запуск/изменение runtime даже при старом большом goal.

## Обязательные продуктовые решения

- Русское общение голосом/текстом с одной личностью и памятью, настраиваемые
  черты/факты, уместная инициатива, реальные поручения на ПК.
- HostOS levels 0–3; Full Access + unattended для автономной работы ночью —
  обязательный режим. Не вводить per-action prompts для уже разрешённых
  действий этого профиля. Политику исполняет JAWL; стоп/исключения/ОС сохраняются.
- Веб-панель в мятном Windows Aero стиле, лаконичная сцена/диалог/задачи,
  настройки во вкладках/окнах. 2D в панели + отдельное окно + OBS URL.
- 2D-only; адаптивный веб-интерфейс для телефона/планшета и LAN-доступ явно
  запрошены владельцем. Отдельный mobile app не нужен. Тяжёлый UI framework, 3D, cloud-hosting не добавлять без
  отдельного обоснования/решения.
- Qwen3-TTS 0.6B — желаемый основной, TeraTTSv2 — быстрый CPU fallback.
  Пока CLI default Tera: не выдавать желаемый выбор за уже изменённый код.
- Qwen3-ASR — final-utterance профиль. ASR не описывает музыку/тембр/настроение
  без отдельно проверенной capability.
- Постоянная Vision модель отложена владельцем. Не выбирать/скачивать её
  самовольно; делать независимые задачи на CLI/UIA/fallback.
- Big Pickle/OpenCode — временный тестовый provider. Будущий QWB/local —
  за JAWL provider contract, не direct Companion LLM как второй агент.
- Ambient system audio/screen — отдельная низкоприоритетная память.
  Целевой обычный профиль: чувства включены после первичной настройки источников,
  наблюдения записываются автоматически, консолидацией владеет JAWL.
  Ручной review не вечный предел; нынешний opt-in код не считать уже изменённым.
- Меньше зависимостей и дублирования, bounded RAM/очереди, понятный код.
  Не оптимизировать число строк ценой тестов, lifecycle и trust boundaries.

## Эволюция согласованного ядра

JAWL — исходная основа, не неизменяемый black box. Развитие принадлежит нашему
owned runtime/version после решения P0-A; protected reference не трогать.
Не сохранять дублирующие механизмы только потому, что они есть в двух upstream.
Сначала карта ownership/перекрытий и общий feedback cycle, затем изменение.

Биология/психология — аналогии, не лицензия на усложнение. Не добавлять
независимые агенты/планировщики на каждую эмоцию/«отдел мозга». Один decision
owner, bounded state/context, сенсорные workers без собственной личности,
coherence E2E: память действительно меняет ответ, инструмент меняет состояние
задачи, голос/аватар выражают одно решение. Неизмеримое «стало более живым»
не закрывает задачу; автоматическое переписывание кода/прав сюда не входит.

## Scope файлов и внешние зависимости

Наш единственный development repo: `G:\AI\JAWL-VoiceCompanion`.

Read-only reference/upstream, если пользователь отдельно не разрешил изменения:

- `G:\AI\JAWL-Coding` — JAWL;
- `G:\AI\VoiceMem` — VoiceMem;
- `G:\AI\_tmp\soul-of-waifu`;
- `G:\AI\_tmp\companion-repos\Open-LLM-VTuber`, `Warashi`, `Miru`,
  `Mana`, `AniCompanion` — исследованные patterns.

Запрет upstream write включает запуск тестов/приложений, создающих там
pycache, data, logs, config, runtime или меняющих рабочий экземпляр через API.
Для live tests нужен согласованный отдельный runtime с отдельными config/
data/log/cache/env. Вывод нового fork/dependency за существующий scope
согласовать; не переносить грязный checkout и секреты автоматически.

`G:\RE` — внешняя нативная toolchain, не наш build/temp root.
Не заменять junctions `x64dbg`, `x64dbgMCP-source`,
`ghidra_12.1.2_PUBLIC` независимыми копиями. TTD EULA и UAC не принимать
за пользователя. Модели/рефы/лицензируемые ассеты не копировать в git.

Dirty changes принадлежат пользователю/предыдущим итерациям. Не делать reset/
checkout/delete, массовый commit и не приписывать авторство по timestamps.

## Дисциплина контекста и квоты

Показывать короткие дельты, не полную историю; ограничивать вывод и поиск;
не дублировать delegated work и не повторять неизменившиеся gates. Использовать
немного параллельных агентов; при низкой пользовательской квоте не начинать
новую работу. Приоритеты — correctness, security и required tests; не обещать
фиксированный процент экономии токенов.

## Архитектурные инварианты

1. Один canonical owner persona/facts/tasks/policy — JAWL. VoiceMem и
   Attention поставляют observations/SPEAK_INTENT, не меняют характер напрямую.
2. Все model-originated side effects идут через native JAWL policy/registry,
   включая HostOS, Terminal, Debug Broker, MCP/browser. Bridge outage не даёт
   права использовать локальный executor. Standalone/mock только явно.
3. JSON envelopes versioned/validated/bounded. Model fields не дают полномочий.
   Media может идти bounded binary/base64 по контракту; JSON — не догма для PCM.
4. Priority/cancel/reconnect должны сохранять correlation и task state.
   Stale output отбрасывать; replay dedup не равно exactly-once mutations.
5. Факт имеет источник/время/уверенность и correction/forget path.
   Always-in-context память ограничена, остальное retrieval.
6. Ambient не USER_FINAL и не инструкции. Screenshots/web/files/tool results —
   недоверенные данные; model inputs не получают authority от их содержимого.
7. Capture в целевом профиле включён после явного первичного выбора источников
   и разрешений ОС/браузера: visible, bounded, pause/revoke, sensitive drop,
   без raw persistence. Mixed WASAPI не даёт надёжной per-app attribution.
   Документирование defaults не разрешает начать текущий захват устройств.
8. Remote text LLM не означает согласие передавать ей PCM/screenshots/ambient.
9. Control и presentation — separate origins/capabilities, loopback по умолчанию.
   Явный LAN-режим владельца: HTTPS и вход на control; не убирать CSRF/origin.
   Непроверенный Live2D JS не загружать в privileged UI; один audio owner.
10. Full Access — права текущего Windows аккаунта, не обход OS/EULA/ACL.
    Текущий lease механизм должен обслуживать ночной профиль и показывать срок.
11. Хранить короткие полезные summaries, не скрытый chain-of-thought.
    Audit metadata redacted/bounded, без raw TTD и credentials.

## Безопасность работы над проектом

- Не читать/печатать `.env`, API keys, токены или process commandlines с секретами.
  Секреты из чата не повторять, не встраивать в docs/fixtures.
- По умолчанию loopback: control 2367, presentation 8766; 8765 — FoxMCP.
  Для планшета разрешён явный LAN-профиль; см. `docs/LAN.md`.
  Конфликт порта означает отказ/другой порт, не убийство его владельца.
- `scripts/run_target_jawl_smoke.ps1` до исправления A3 аудита **не запускать**.
- Тесты actions — disposable fixtures и явный opt-in; не рабочие файлы/приложения.
  Каталог всех tools не требует опасного live выполнения каждого из них.
- Cleanup только доказанно собственных процессов/путей; проверять resolved
  targets, process identity/creation time. Не удалять broad workspace.
- Не создавать goal без явного запроса. Старый goal не расширяет текущую задачу.
  Если нужен новый scope/внешнее разрешение, остановить этот шаг и спросить.

## Проверка качества и передача

Major runtime update: `scripts/run_full_gate.ps1` + весь основной browser E2E
сценарий и затронутые live rows из аудита. Fake HTTP gate не заменяет
browser interactions/скриншоты, реальную модель, устройство и OBS.
Для docs-only: link/consistency check + `git diff --check`, без live launches.

При каждом evidence фиксировать profile/run ID, версию/dirty diff, вход,
ожидание/факт, дату, pass/fail/skip, exit code и redacted report.
Отдельно: unit, fake HTTP, synthetic media, real provider, real device.
`configured`/HTTP 200/`queued`/DOM marker не equals ready/ingested/красиво.

Долгую command session отслеживать до exit с её ID. Потерянный stdout не
считать pass, orphan-runtime bug или поводом бесконечно перезапускать gate.
Не повторять одинаковые сборки/зелёные тесты без новой гипотезы/изменения.

После среза:
- TODO — статус только проверенного результата;
- STATE — короткая сводка, что изменено/проверено/ограничено, следующий шаг;
- CHANGELOG — существенное изменение; DECISIONS — изменившийся выбор;
- оставить reviewable diff, без посторонних правок.

Не объявлять RC до целого daily scenario, production-ready до полной
применимой матрицы и пользовательской приёмки. Называть реальные пробелы.
