# JAWL Companion

Один локальный русскоязычный агент-компаньон для Windows: общение голосом и
текстом, личность и память, фоновое восприятие, поручения на ПК и персонаж.
JAWL — единственный владелец решений, памяти, задач и нативных полномочий;
VoiceMem — сенсорная инфраструктура; Companion — общий интерфейс и голос.
Основной клиент — Electron с 3D VRM / three-vrm, чатом и настройками.
Раннее ограничение 2D и Live2D/Mocari заменено ADR-045–046.

## Состояние на 2026-10-12 (Москва)

**Интеграционная версия, не release candidate и не production-ready.**
Архитектурная основа и отдельные реальные сценарии существуют; полный
ежедневный сценарий на текущем стеке, физический duplex/barge-in, единая
панель, ночная автономность и художественная приёмка персонажа ещё открыты.
Аудит документации не является новым запуском или подтверждением runtime.

Последний полный regression gate — 12OctMoscow, direct child exit0; receipt
`runtime/gate-client-post-20261012.json` — `passed`, exit0
(UTC 2026-10-12T00:23:34–00:28:20): 779 Python unit, 66 manifest/worker/diagnostics
pytest, 16 HTTP E2E, 86 Node, 6 legacy browser и 8 desktop composite checks.
В desktop-прогоне реальны
`/app`, capture/playback и serializer, но ASR/JAWL — mock, TTS — tone WAV.
Это не проверка русского разговора с физическим микрофоном.
Отдельный actual Tera CPU probe12Oct: cancel+worker/lease idle102.8ms,3 WAV,
RTF0.399–0.482; ephemeral worker закрыт, daily-профиль этим не принят.
Native sync/stream admission сериализован, blind POST replay удалён. Owned native
HTTP guard предотвращает поздний dispatch после cancel и duplicate ID; startup
tokens редактируются. Actual owned-console probe PASS, но actual LLM compute
release/whole voice ещё OPEN. Default POST имеет scoped abort/absolute deadline,
HTTP/TLS loopback PASS. Все343 frozen hashes совпали; подробности в STATE.

## С чего начать

- [Карта всей документации](docs/README.md) — актуальные документы и история.
- [Замысел и требования](docs/PRODUCT.md) — какое приложение строим.
- [Текущее состояние](docs/STATE.md) — что доказано и чего не доказано.
- [Единственная очередь разработки](TODO.md) — фазы и критерии завершения.
- [Весь остаток и оценка трудоёмкости](docs/WORK_REMAINING.md).
- [Архитектура](docs/ARCHITECTURE.md), [приёмочная матрица](docs/TECHNICAL_AUDIT.md).
- [Запуск, зависимости и поставка](docs/RELEASE.md), [LAN](docs/LAN.md), [OBS](docs/OBS.md).
- [Правила работы агентов](AGENTS.md), [передача работы](HANDOFF.md).

## Локальное демо и основной интерфейс

Из корня репозитория, при установленных Python-зависимостях:

```powershell
.\scripts\run_web.ps1
```

Без connected-параметров это **демо**, не полноценный JAWL-агент.
Основной интерфейс: `http://127.0.0.1:2367/app`.
Корневая страница `/` и `/console/` — ещё существующие поверхности;
их функциональность не считается автоматически перенесённой в `/app`.
Открывать HTTP-страницу, не WebSocket endpoint.

Electron подключается к уже готовому backend и сам по себе не устанавливает
модели. При установленных desktop-зависимостях:

```powershell
cd desktop
npm start
```

Порт берётся из `JAWL_DESKTOP_CONTROL_PORT`, затем canonical + optional local
`config/runtime.manifest*.json` (default2367). Некорректный порт/manifest
отклоняется без скрытого fallback. При недоступном backend оболочка показывает
reconnect/readiness, а не готовность агента.

## Connected-профиль

`scripts/run_integrated_profile.ps1` запускает owned JAWL-профиль из
`runtime/instances/<name>`; native access по умолчанию — 0, Debug Broker
выбирается явно. `scripts/run_local_bonsai_integrated.ps1` дополнительно
поднимает supervised Hikari brain. Оба читают общий runtime manifest: defaults
2367/8766/8770/9889/8990, RunSeconds0 (до остановки). Для ограниченного smoke
задавать `-RunSeconds 60` явно. Это разные уровни запуска, не два brain owner.

До запуска сверить выбранный профиль, параметры и effective state по
[RELEASE.md](docs/RELEASE.md). Сведение launch defaults и runtime manifest
добавлено в B0; whole-profile/live/Rust/portability остаются открытыми.
Нельзя запускать protected checkout JAWL-Coding вместо
owned runtime или принимать HTTP 200 за полную model readiness.

Предпочтительные продуктовые порты: control 2367, presentation 8766;
8770 — внутренняя JAWL console. 8765 принадлежит FoxMCP.
Presentation endpoint сам по себе ещё не доказывает текущую VRM-приёмку OBS.
Конфликт порта не разрешает останавливать чужой процесс.

## Текущий выбранный стек, не универсальные defaults всех скриптов

| Контур | Выбор |
| --- | --- |
| Главная LLM | Bonsai-2 27B Hikari PQ2_0, локально GPU1, за контрактом JAWL |
| ASR | GigaAM v3 / crispasr — единственный движок; partial bridge отдельно от desktop UX |
| TTS default | TeraTTSv2 ru_f1; OmniVoice — выбираемая опция, VoxCPM — отдельный опциональный путь |
| Vision | Bonsai / screen-watch / PerceptionFusion; live RU OCR и action loop принимаются отдельно |
| Фоновый текст | CPU/RAM worker, Bonsai-1.7B — испытанный кандидат, не второй агент |
| Клиент | Electron + three-vrm; адаптивный веб-доступ — тот же продукт |

Qwen3-TTS, CosyVoice и другие benchmark-кандидаты не являются новым дефолтом.
ASR не описывает музыку, настроение и окружающие звуки без отдельной capability.
Облачный или QWB-JAWL provider подключается через JAWL contract, не напрямую
как второй мозг Companion.

## Проверка и границы работы

Major runtime update: `scripts/run_full_gate.ps1`, основной browser E2E и
затронутые live rows из матрицы. Для docs-only: ссылки, согласованность и
`git diff --check`; модели, устройства и сервисы запускать не требуется.

Рабочий репозиторий: `G:\AI\JAWL-VoiceCompanion`.
`G:\AI\JAWL-Coding`, `G:\AI\VoiceMem`, `G:\RE` — read-only references/toolchain.
Full Access действует в правах Windows-аккаунта, не обходит UAC/ACL/EULA.
Веса, окружения, голосовые референсы, лицензируемые ассеты и секреты не входят
в git или wheel. Исходники персонажа и лицензии принимаются отдельно.

История до консолидации сохранена в
[архиве 2026-10-10](docs/history/2026-10-10-before-docs-consolidation/INDEX.md).
Старые команды, статусы goals и цифры относятся к своим датам, не к текущей очереди.
