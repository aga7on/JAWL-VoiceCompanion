# Передача работы — 2026-09-06

Начать с AGENTS.md → docs/PRODUCT.md → docs/STATE.md → TODO.md →
docs/TECHNICAL_AUDIT.md → [docs/RECOVERY_PLAN.md](docs/RECOVERY_PLAN.md).
Последний документ задаёт порядок R1 → R4 и готовую формулировку goal.

Срез аудита: HEAD `1bb3117` плюс R1-правки. Используется owned snapshot
`runtime/jawl-sources/jawl-20260906-daily-v2` (348 файлов). Глобальная HostOS
blocklist и запрет discovery удалены из owned snapshot/config; повреждённый
context patch удалён. Последний full gate `20260906T021700Z` зелёный, но это
не live voice acceptance.

Один live gateway pass (~48 с) сохранён. Пять свежих recall-попыток failed;
связанный голос/память/поручение не принят. Нельзя продолжать с утверждением
«модель и память уже работают». Проверить конкретные turn IDs и содержательный
результат. Historical mock/browser/full-gate не доказывают live daily scenario.

prepare_daily_profile копирует только отсутствующие файлы. До эксперимента
сравнить effective config/prompt с источником и построить корректную миграцию.
Выбранная локальная модель и контекст требуют readiness; суффикс LM Studio
`:2` не считать постоянным. Ошибку контекста и tool loop исследовать отдельно.

Следующие исполнители могут параллельно взять: R1 delivery/tools, R2 turn/memory,
R3 browser/audio acceptance с непересекающимися файлами. Координатор принимает
изменения и запускает R4 integrated acceptance. Не урезать права ради latency.

Рабочее репо только G:\AI\JAWL-VoiceCompanion; protected JAWL-Coding/VoiceMem/RE
read-only. Не читать секреты, не менять чужие процессы. Синтетические live
проверки не требуют присутствия владельца; физический микрофон/OBS — отдельные
приёмки. Vision не выбирать.

Goal `01a058db-f310-7d03-bbb3-63eba8ba78a5` зарегистрирован и активен.
Не закрывать его до связанного live-сценария: memory recall, три browser voice
turns, native disposable action с postcondition/recovery и реального Live2D.

## Актуальная поправка аудита — 2026-09-06

Текущий HEAD — `5f5ec7f`, а не исторический `1bb3117`; рабочее дерево содержит
незакоммиченные изменения. Snapshot `jawl-20260906-daily-v2` проверен digest
`7c2d3f1814c67dc7c8ae8c0ed3d1dee183380f54177b691f1f5825dbb3d10422`.
MiniCPM-o 4.5 не входит в RU production gate. Для следующих мультимодальных
кандидатов обязателен `docs/MULTIMODAL_MODEL_GATE.md` до скачивания полного веса.
