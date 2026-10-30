# Архив перед ежедневной версией

14 октября2026. Сохранено27 документов и2 скрипта; исходные байты проверены SHA256
при переносе. [Машинный перечень](manifest.json). Это история, не active instructions.
Ветка dev/daily-companion-20261014 создана от0e53329 с dirty worktree, без commit/reset.

## Содержимое

- [AGENTS.md](AGENTS.md)
- [CHANGELOG.md](CHANGELOG.md)
- [HANDOFF.md](HANDOFF.md)
- [README.md](README.md)
- [TODO.md](TODO.md)
- [docs/AMBIENT_TRIAGE_BENCHMARK.md](docs/AMBIENT_TRIAGE_BENCHMARK.md)
- [docs/CHARACTER_BLOCKING_V3_REVIEW.md](docs/CHARACTER_BLOCKING_V3_REVIEW.md)
- [docs/CHARACTER_CLOSEUP_AUDIT_20261004.md](docs/CHARACTER_CLOSEUP_AUDIT_20261004.md)
- [docs/CHARACTER_DELIVERY_20261004.md](docs/CHARACTER_DELIVERY_20261004.md)
- [docs/CHARACTER_FIT_V4_REVIEW.md](docs/CHARACTER_FIT_V4_REVIEW.md)
- [docs/CHARACTER_HAIR_V7_REVIEW.md](docs/CHARACTER_HAIR_V7_REVIEW.md)
- [docs/CHARACTER_HAIR_V8_REVIEW.md](docs/CHARACTER_HAIR_V8_REVIEW.md)
- [docs/CHARACTER_SHOULDER_V6_REVIEW.md](docs/CHARACTER_SHOULDER_V6_REVIEW.md)
- [docs/COSYVOICE3_CPU_BENCHMARK.md](docs/COSYVOICE3_CPU_BENCHMARK.md)
- [docs/CRANE_ACCEPTANCE_20260908.md](docs/CRANE_ACCEPTANCE_20260908.md)
- [docs/MINICPM5_1B_REVIEW.md](docs/MINICPM5_1B_REVIEW.md)
- [docs/MINICPM_O45_BENCHMARK.md](docs/MINICPM_O45_BENCHMARK.md)
- [docs/PRODUCT.md](docs/PRODUCT.md)
- [docs/PRODUCTION_DELIVERY_GOAL.md](docs/PRODUCTION_DELIVERY_GOAL.md)
- [docs/PRODUCTION_STATUS_20260909.md](docs/PRODUCTION_STATUS_20260909.md)
- [docs/README.md](docs/README.md)
- [docs/RECOVERY_PLAN.md](docs/RECOVERY_PLAN.md)
- [docs/STATE.md](docs/STATE.md)
- [docs/TECHNICAL_AUDIT.md](docs/TECHNICAL_AUDIT.md)
- [docs/UNIFIED_UI_INTEGRATION_PLAN.md](docs/UNIFIED_UI_INTEGRATION_PLAN.md)
- [docs/VOXCPM_INTEGRATION_20260909.md](docs/VOXCPM_INTEGRATION_20260909.md)
- [docs/WORK_REMAINING.md](docs/WORK_REMAINING.md)
- [scripts/needle3_extract_probe.py](scripts/needle3_extract_probe.py)
- [scripts/needle3_framing_probe.py](scripts/needle3_framing_probe.py)

## Как читать и восстановить

Пути внутри сохранённых документов относятся к ИСХОДНОМУ положению в repo;
они намеренно не переписаны, чтобы сохранить точную историю. Новая карта:
[docs/README](../../README.md). Архивный AGENTS не задаёт правила активной разработки.

Для восстановления выбрать конкретный path из manifest, сверить SHA256 и
скопировать файл в исходное место только после сравнения с текущими изменениями.
Не восстанавливать весь архив поверх новой ветки и не делать git reset.
Старые отчёты сохраняют PASS/FAIL своего профиля; это не сегодняшняя приёмка.

Два Needle3 probe перенесены после проверки отсутствия внешних ссылок в
tracked/untracked/hidden repo (кроме runtime/.git/истории). Они standalone,
с абсолютным REPO path; их config/модель оставлены на месте. Не запускать
архивные probes автоматически. Другие scripts имеют ссылки/операционную роль
и сохранены; возраст файла не основание удаления.

Runtime logs/reports/assets/models/data, contracts, конфигурация и prompts не
переносились. Прежние docs/history каталоги сохранены. Удалений безвозвратно нет.
