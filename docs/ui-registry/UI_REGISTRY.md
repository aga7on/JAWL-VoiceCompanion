# Реестр UI-функций: JAWL-консоль vs Companion (U0)

Источник: снапшот jawl-20260906-daily-v2 + фронт компаньона. 
Сгенерировано `extract_ui_registry.py`; обновлять при изменении панелей.

## Сводка

- DOM-контролов консоли (data-cfg): **213**
- Схема-маппинг (config/env записи): **206**
- Без маппинга: **14** — все `settings:system.db.sql.drives.*`, пишутся через `/api/drives` (отдельный writer, осознанно)
- Эндпоинтов консоли: **31**; вызовы console.js не выходят за роуты: **True**
- Вызовов API в UI компаньона: **45**

## Группы DOM-контролов консоли

| Группа | Контролов | Владелец данных | Вердикт |
|---|---|---|---|
| settings:system | 63 | JAWL config (settings.yaml) | migrate (U4) |
| interfaces:host | 33 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:web | 24 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:telegram | 17 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:voice | 14 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:debug_broker | 9 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:multimodality | 7 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:mcp | 6 | JAWL config (interfaces.yaml) | migrate (U4) |
| settings:llm | 6 | JAWL config (settings.yaml) | migrate (U4) |
| interfaces:github | 5 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:calendar | 3 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:code_graph | 3 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:email | 3 | JAWL config (interfaces.yaml) | migrate (U4) |
| interfaces:meta | 3 | JAWL config (interfaces.yaml) | migrate (U4) |
| env:AIOGRAM_BOT_TOKEN | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:CLOUD_WHISPER_API_KEY | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:CLOUD_WHISPER_API_URL | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:ELEVENLABS_API_KEY | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:ELEVENLABS_API_URL | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:EMAIL_ACCOUNT | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:EMAIL_PASSWORD | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:GITHUB_TOKEN | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:LLM_API_URL | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:PROXY_URL | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:SUB_LLM_API_KEY_1 | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:SUB_LLM_API_URL | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:TAVILY_API_KEY | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:TELETHON_API_HASH | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:TELETHON_API_ID | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| env:WEBHOOK_SECRET | 1 | .env (секреты) | migrate с secret-семантикой (U4) |
| settings:identity | 1 | JAWL config (settings.yaml) | migrate (U4) |

## Контролы без schema-маппинга (drives — отдельный writer)

Все 14: `settings:system.db.sql.drives.*` → `/api/drives` GET/PUT. Verdict: **keep** (отдельный API, переносится как блок «Мотивация» с собственным сохранением).

## Эндпоинты консоли (31)

| Метод | Роут | Handler | Примечание для переноса |
|---|---|---|---|
| GET | `/api/tick` | tick_state |  |
| GET | `/api/chat` | chat_history |  |
| POST | `/api/chat` | chat_send |  |
| GET | `/api/chat/stream` | chat_stream |  |
| POST | `/api/companion/turn` | companion_turn |  |
| POST | `/api/companion/cancel` | companion_cancel |  |
| GET | `/api/companion/stream` | companion_stream |  |
| GET | `/api/db/stats` | db_stats |  |
| POST | `/api/db/wipe` | db_wipe | CRITICAL: двойное подтверждение + владелец JAWL |
| GET | `/api/drives` | drives_list | отдельный writer drives |
| PUT | `/api/drives` | drives_update | отдельный writer drives |
| GET | `/api/logs` | logs_tail |  |
| GET | `/api/logs/stream` | logs_stream |  |
| GET | `/api/logs/download` | logs_download |  |
| GET | `/api/agent/status` | agent_status |  |
| GET | `/api/agent/journal` | agent_journal |  |
| POST | `/api/agent/start` | agent_start | CRITICAL: lifecycle |
| POST | `/api/agent/stop` | agent_stop | CRITICAL: lifecycle |
| GET | `/api/hostos/policy` | hostos_policy |  |
| POST | `/api/hostos/autonomy` | hostos_autonomy |  |
| POST | `/api/hostos/emergency-stop` | hostos_emergency_stop | CRITICAL: явное действие |
| POST | `/api/hostos/emergency-stop/reset` | hostos_emergency_reset | CRITICAL: явное действие |
| GET | `/api/memory` | memory_list |  |
| POST | `/api/memory` | memory_mutation |  |
| POST | `/api/hostos/skill` | hostos_skill |  |
| POST | `/api/debug/skill` | debug_skill | RE/debug — отдельно, с ограничением |
| GET | `/api/skills/catalog` | skills_catalog |  |
| GET | `/api/config` | get_config | главный writer настроек (PUT, revision) |
| PUT | `/api/config` | put_config | главный writer настроек (PUT, revision) |
| POST | `/api/fs/open` | post_open | локальный shell — только loopback |
| GET | `/` | index |  |

## Вызовы API в UI компаньона (42) и дубль-анализ

Консольные зоны, которые компаньон уже покрывает нативно (не переносить второй раз):
- `/api/ambient-audio` — Companion native
- `/api/ambient-audio/playback` — Companion native
- `/api/ambient-memory` — Companion native
- `/api/ambient-memory/clear` — Companion native
- `/api/ambient-memory/config` — Companion native
- `/api/ambient-memory/promote` — Companion native
- `/api/ambient-memory/triage` — Companion native
- `/api/attention` — Companion native
- `/api/audit` — Companion native
- `/api/avatar/audio` — Companion native
- `/api/avatar/config` — Companion native
- `/api/chat` — Companion native
- `/api/chat/stream` — Companion native
- `/api/doctor` — Companion native
- `/api/history` — Companion native
- `/api/hostos/level` — Companion native
- `/api/perception/now` — Companion native
- `/api/proactive` — Companion native
- `/api/proactive/feedback` — Companion native
- `/api/proactive/settings` — Companion native
- `/api/session` — Companion native
- `/api/state` — Companion native
- `/api/tts/cancel` — Companion native
- `/api/tts/status` — Companion native
- `/api/tts/stream` — Companion native
- `/api/tts/synthesize` — Companion native
- `/api/vision/look` — Companion native
- `/api/vision/status` — Companion native
- `/api/voice/audio` — Companion native
- `/api/voice/draft` — Companion native
- `/api/voice/end` — Companion native
- `/api/voice/preface` — Companion native

Обёртки компаньона над консольными действиями (verdict: keep, консольные дубли не переносить):
- `/api/config-hub` — 
- `/api/config-hub/save` — 
- `/api/emergency-stop` — CRITICAL-обёртка над /api/hostos/emergency-stop* — двойное подтверждение
- `/api/emergency-stop/reset` — CRITICAL-обёртка над /api/hostos/emergency-stop* — двойное подтверждение
- `/api/health` — 
- `/api/hostos/approvals` — 
- `/api/hostos/denylist` — 
- `/api/hostos/unattended` — 
- `/api/jawl/hostos` — нативный адаптер jawl_web (memory/journal/hostos/overview)
- `/api/jawl/journal` — нативный адаптер jawl_web (memory/journal/hostos/overview)
- `/api/jawl/memory` — нативный адаптер jawl_web (memory/journal/hostos/overview)
- `/api/jawl/overview` — нативный адаптер jawl_web (memory/journal/hostos/overview)
- `/api/shell/status` — 

## Открытые вопросы U0

1. Секреты в env-группе: маскирование при чтении `/api/config` — проверить config_io (readback).
2. `/api/chat` GET/POST и companion turn: два писателя истории — владелец записи чата должен остаться один (JAWL).
3. Drives UI: свой ревизионный протокол или общий с config?
4. Списочные редакторы (INTERFACES_LISTS: 5, SETTINGS_LISTS: 1, ENV_LISTS: 1) — контракт добавления/удаления элементов.