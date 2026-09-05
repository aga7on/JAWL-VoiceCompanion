# JAWL runtime: исходники и запуск

Проверено read-only 2026-09-05. Это инвентаризация для P0-A; поставка ещё
частично собрана; live запуск не выполнен.

## Сохранённый source snapshot

`runtime/jawl-sources/jawl-20260905-daily-v1` содержит 348 отобранных файлов.
`SOURCE_MANIFEST.json` перечисляет их SHA256; все 348 повторно сверены после
записи. Общий digest: `91250ab5fa232c44c3aa22ebaf440d5fe65f6ec935e845a27aa09770bdc6ad0d`.
Сборщик — `scripts/stage_jawl_source.py`, default dry-run, запись по `--write`,
существующий target отклоняется. Два fixture-теста прошли; compileall копии
исходников прошёл. Compileall создаёт локальный pycache, который не включён
в manifest исходников. Protected reference не запускался.

Включены Python/Java/Markdown исходники, системные prompt-модули, example
personality/config, web assets, LICENSE и requirements. Рабочие persona/config,
`.env`, data/log/cache исключены. Проверка key-shaped строк не является полным
secret scan; snapshot не публиковался. Подготовка своего SOUL/config, окружения
с dependency lock и проверка runtime imports/readiness ещё требуются.

Исходный checkout: `G:\AI\JAWL-Coding`; HEAD
`1725747e65b87d642d48dafe913af2550178cee4`, строка версии `0.17.0-stable`.
HEAD не идентифицирует локальные additions. Для сборки нужен полный manifest
выбранных исходников и локальных изменений. Лицензия корня — MIT, copyright
2026 th0r3nt; сохранить LICENSE при включении кода. Зависимости имеют свои лицензии.

## Требуемые части

| Возможность Companion | Native реализация, которую нужно включить |
|---|---|
| `/api/companion/turn`, `/cancel`, `/stream` | `src/web/server.py`, `src/l3_agent/companion_gateway.py`, интеграция в `src/l3_agent/react/loop.py` |
| `/api/memory`, изменения фактов и контекст | `src/l1_databases/sql/management/structured_memory.py`, SQL manager, регистрация в `src/builder.py` |
| `/api/hostos/policy`, `/skill`, `/api/debug/skill` | web routes, `src/system/operator_control.py`, HostOS/Debug registry |
| Срок автономности и stop | `src/l2_interfaces/host/os/autonomy.py`, operator control и соответствующие routes |
| Состояние задачи после restart | action journal, регистрация/хранилище в builder/container; нужен отдельный тест результата |
| Личность и реконструкция контекста | prompt builder, отобранные поведенческие Markdown, context builder, ReAct |

Это карта связей, не список файлов для механического копирования: полное
замыкание импортов ещё предстоит проверить. Одних трёх новых модулей недостаточно.
`requirements.txt` использует диапазоны версий; lock окружения отсутствует
в этой инвентаризации. Python 3.14 Companion не доказывает совместимость JAWL/Kuzu.

Для owned-профиля добавлен `config/jawl/requirements-runtime.txt`. Он меняет
несовместимый `aiogram~=3.17.0` на `aiogram>=3.25,<3.26`, совместимый с
`pydantic>=2.11`. Это вход профиля, не окончательный lock: после установки
нужно сохранить `pip freeze` и хеши и пройти весь импортный граф.
На 3.11 окружение уже установлено в `runtime/jawl-daily-venv`; фактический
version lock сохранён в `config/jawl/requirements.lock.txt`, а `pip check`
сообщил `No broken requirements found`.

## Найденные пути побочных записей

1. `src/main.py` вызывает bootstrap до загрузки настроек, затем читает
   `project_root/.env` с `override=True`, после него instance env. Одних
   переменных `JAWL_*_DIR` недостаточно для изоляции рабочего checkout.
2. `bootstrap_instance_layout` в `src/instances/paths.py` копирует при отсутствии
   целевых файлов не только example config, но и рабочие `settings.yaml` и
   `interfaces.yaml`. В чистой поставке должны быть собственные настройки.
3. Bootstrap рекурсивно копирует всё содержимое prompt directory. Для сборки
   отбирать нужные исходники/Markdown; не переносить pycache и runtime файлы.
4. Исторические `runtime/jawl-live-20260905*` имеют config/data/logs/prompts,
   но на верхнем уровне не содержат собственной поставки `src`. Не считать
   их уже готовым независимым дистрибутивом и не переиспользовать рабочие secrets.

## Следующий implementation шаг

Использовать сохранённый source snapshot с лицензией и manifest хешей;
подготовить отдельный профиль `runtime/integrated-attended` для данных.
Источник остаётся reference. Из включаемых ресурсов исключить рабочие `.env`,
config, data, logs, caches, сторонние аккаунты и их auto-start. Подготовить
минимальную собственную конфигурацию и проверить loader/cleanup до live запуска.
Затем подключить этот профиль к launcher и доказать identity/capabilities
коррелированным запросом через Companion. Интеграция должна проверять
фактические версии; строка версии и HTTP 200 недостаточны.

Контрольные SHA256 выбранных файлов (не полный lock поставки):

| Файл | SHA256 |
|---|---|
| LICENSE | `DC6D4819C16C6A4F745EA76B83C6E0C6A86BBCE556EA780EE1998A344CD73286` |
| requirements.txt | `0E235B80850CC8AAE5B10B7671E6D9DCF4CB1F61D9A22B78E2F651A2AB22337C` |
| src/main.py | `5F24CC828413E16B700EB5E223A49827D6B33743E4B0C0ADFE22124F2D03A494` |
| src/instances/paths.py | `F7900CF06E42E9FCBB034BB21DE2BACA979AC91B4C31D652B90A897E5A1AF8A9` |
| src/web/server.py | `FAEFB41D55F65B08E9EDC196080E99D20E4B5BD169E4E9F62F8DEF8F3F3DD0A3` |
| src/l3_agent/companion_gateway.py | `A6010272AD062AA25D40D79EA82E08B27F77DB317296F15EA594FB6E2FB542CF` |
