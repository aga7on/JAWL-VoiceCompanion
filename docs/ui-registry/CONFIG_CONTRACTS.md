# Контракты конфигурации и отката (U0 → U1)

## Актуальная граница — 2026-10-10

ConfigHub уже поддерживает revision check, backup generations, secret masking,
readback и restart semantics. Это не подтверждает полную parity формы: полный
round-trip всех scalar, string-list и object-list полей и совпадение effective
state не доказаны. Наличие сохранённого значения отдельно от применённого
состояния обязательно отражать в UI и acceptance. Новые задачи и статус —
[TODO](../../TODO.md) и [STATE](../STATE.md); карта документов —
[docs/README.md](../README.md).

Источник: снапшот `jawl-20260906-daily-v2` (`src/web/server.py`, `config_io.py`, `drives.py`).
Документ фиксирует, КАК сегодня пишутся настройки, чтобы единый writer (U1) не потерял семантику.

## Актуальное расширение — voice capture, 2026-10-05

Обычная ConfigHub запись сохраняет консервативную `agent_restart` политику
ниже. Исключение, проверенное по consumer-коду: `interfaces.yaml voice.capture.*`
использует `next_capture`, без перезапуска JAWL и без изменения уже открытого mic.
Это тот же ConfigHub, revision lock, 5 backup generations и атомарная запись,
не browser localStorage и не второй конфигурационный файл.

Authenticated GET `/api/voice/capture` возвращает `settings`, `revision`,
`settings_writable`, lease state и top-level snapshot значений. POST configure:

```json
{"action":"configure","settings":{"gate_open":0.02,"gate_close":0.012,"silence_ms":1200,"pre_roll_ms":120},"expected_revision":"revision-from-get"}
```

Partial update объединяется с текущими значениями. Разрешены finite numeric
gate_open 0.001–0.25, gate_close ≥0.0005 и строго <open, integer silence_ms
300–5000, integer pre_roll_ms 0–500. Bool/NaN/Infinity/unknown keys отклоняются.
Conflict →409 без записи; ConfigHub не настроен →503; invalid persisted config
→явная ошибка, не молчаливый reset. Ответ сохранения содержит новую revision,
settings, `restart_required:false`, `restart_policy:"next_capture"`.
Persisted/parser/I/O error responses redacted: без YAML соседних строк и
локальных путей; только фиксированные validation hints либо просьба проверить
`interfaces.yaml voice.capture`. UI load/save bounded 5 с, draft не теряется.

Fresh capture subtree вставляется точечно с сохранением комментариев/CRLF.
Перед backup/replace parsed candidate сравнивается с original interfaces плюс
ровно разрешённые capture значения. Неподдерживаемые quoted/flow/null формы
отклоняются, исходные байты не меняются. Protected snapshot writer не изменён.

Acquire/renew/release используют `{action,owner,capture_id}`; owner = desktop
или native, identity ≤128 символов. Busy →409 до device permission, TTL 15 с.
`/api/voice/audio` и `/api/voice/end` несут тот же owner/capture_id. Legacy
unclaimed requests возможны только без активного lease; это не второй default
mic lane. Настройки/lease не расширяют authority JAWL, HostOS или ambient capture.

Actual UI save/readback/new-acquire и release regression PASS в
`gate-capture-settings-20261005.log`; это synthetic media/mock providers,
не реальный микрофон. Статус приёмки — [STATE](../STATE.md).

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

## Restart-карта (U1, срез 1)

Проверено по коду: агент читает конфиг один раз (`main.py:38 → load_config()`),
в цикле сердце настройки не перечитывает. Значит политика — консервативная:
**любая запись в settings/interfaces/env → рестарт агента** (hub возвращает
`restart_required: true, restart_policy: "agent_restart"`). Живыми (без рестарта)
являются только файлы промптов (`prompts/custom/*.md` — читаются каждый цикл),
они и не являются config-ключами. Помечать отдельные ключи как «live» можно только
после аудита по-ключ — отложено в U1 remainder. Авто-рестарт после записи не
выполняется: решение остаётся за пользователем (кнопка «Запустить/Остановить»).
