# Контракты конфигурации и отката (U0 → U1)

Источник: снапшот `jawl-20260906-daily-v2` (`src/web/server.py`, `config_io.py`, `drives.py`).
Документ фиксирует, КАК сегодня пишутся настройки, чтобы единый writer (U1) не потерял семантику.

## Три файла-владельца

| Файл | Что содержит | Writer | Читают на ходу |
|---|---|---|---|
| `config/settings.yaml` | identity, llm, system (63 скаляра + 1 список) | `apply_yaml(SETTINGS_FILE, …)` через `PUT /api/config` | частично (prompt-bUILDER каждый цикл; ядро — по-разному) |
| `config/interfaces.yaml` | интерфейсы: host, telegram, voice, web, github, email, mcp, meta, debug_broker, calendar, code_graph, multimodality (127 скаляров + 5 списков + object-списки) | `apply_yaml(INTERFACES_FILE, …)` | частично |
| `.env` | 16 секретов/URL (ENV_FIELDS) + префикс-списки (LLM_API_KEY_) | `save_env()` — точечное редактирование с сохранением комментариев и порядка | нет |

`restartRequired` в ответе `PUT /api/config` сейчас **всегда пустой** (TODO в коде):
какие параметры перечитываются на ходу, а какие требуют рестарт агента — не определено.
Это обязательный элемент U1 (readback/effective state).

## Семантика записи

1. **Скаляры и списки** — `apply_yaml`: правит строки на месте (`set_scalar`/`set_list`/`set_object_list`),
   возвращает `missing[]` для ключей, которых в файле нет. Ключи-«unknown» блокируются целиком? Нет:
   файл НЕ пишется только если ALL ключи missing; частичная запись возможна (`total > len(missing)`).
   **Риск для U1:** частичный успех (одна часть ключей записана, другая — missing) молча возвращает ok.
2. **Сохранение раскладки файла**: `_write_lines` сохраняет точный CRLF/LF-микс существующего файла
   (one-value edit не разворачивается в whole-file diff).
3. **`.env`**: точечная замена строк, добавление в конец, сквозная перенумерация
   префикс-списков (`LLM_API_KEY_1..N`), удаление лишних закомментированных заготовок.
4. **Drives — исключение**: `settings:system.db.sql.drives.*` живут в SQLite
   (`drives.py::_connect`), UI-ключи на 14 полей идут через `GET/PUT /api/drives`,
   НЕ через config. В U1 writer для drives остаётся отдельным либо получает свой ревизионный протокол.

## Revision / конфликты / readback (U1 gaps)

- **Ревизии нет**: GET возвращает `values+lists+version` (версия фреймворка, не ревизия данных).
  Два клиента могут перезаписать друг друга (last-write-wins) — конфликтов нет вовсе.
- **Readback/effective**: после PUT ревизионного ответа нет; UI консоли перечитывает GET, но
  «saved» ≠ «effective» нигде не различается.
- **Секреты**: GET отдаёт env-значения в ОТКРЫТОМ виде (строка 59: `env.get(env_key, "")`),
  маскирования нет. U1 обязан ввести secret-семантику (write-only, `__SET__`-маркеры).

## Бэкапы и откат (фактические)

- В профиле: `settings.yaml.bak`, `settings.yaml.bak.sync`, `interfaces.yaml.bak` —
  артефакты снапшотера/синка, НЕ системный backup writer'а. `apply_yaml` бэкапов не делает.
- **Откат сегодня**: git (`config/jawl/*.yaml` — baseline; `runtime/instances/daily/config/*.yaml` —
  живой профиль, вне git) + ручные .bak-копии. Надёжной процедуры отката последней правки нет.
- **U1 контракт**: перед каждой записью — ротируемая копия `*.pre-save.bak` (хранить N=5),
  атомарная запись через tmp+`os.replace`, ответ с `revision` (инкремент/хэш), readback списком
  записанных ключей с effective-значениями.

## CRITICAL-действия (из реестра эндпоинтов)

`/api/db/wipe`, `/api/hostos/emergency-stop(+reset)`, `/api/agent/stop|start`, `/api/fs/open`,
`/api/debug/skill` — в едином UI требуют: явного подтверждения, владельца JAWL,
журналирования в audit, запрета на автосохранение в drafts.

## Вывод для U1

Единый writer должен сохранить: пофайловую раскладку YAML (CRLF/LF), сквозную нумерацию
env-префиксов, unknown-key политику (отклонять, а не молчать), separate drives writer —
и добавить: revision, secret-маскирование, pre-save backup, effective/readback, restart-карту
(какие ключи требуют рестарт агента).
