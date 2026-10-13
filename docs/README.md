# Карта документации

Обновлено14Oct2026. Активный план один: ежедневная версия D1–D6.

| Читать | Назначение |
| --- | --- |
| [STATE](STATE.md) | Текущие факты и первый блокер |
| [TODO](../TODO.md) | Единственная очередь |
| [DAILY_PLAN](DAILY_PLAN.md) | Этапы, objective, срок и scope |
| [DAILY_ACCEPTANCE](DAILY_ACCEPTANCE.md) | Достаточная проверка личного использования |
| [DAILY_RUNBOOK](DAILY_RUNBOOK.md) | Существующий запуск, честные ограничения |
| [PRODUCT](PRODUCT.md) | Замысел владельца |
| [BACKLOG](BACKLOG.md) | Не отменённые расширения |
| [AGENTS](../AGENTS.md) / [HANDOFF](../HANDOFF.md) | Правила и ближайшее действие |

## Справочники по необходимости

[ARCHITECTURE](ARCHITECTURE.md), [CORE_OWNERSHIP](CORE_OWNERSHIP.md),
[UNIFIED_RUNTIME](UNIFIED_RUNTIME.md), [JAWL capabilities](JAWL_CANONICAL_CAPABILITIES.md),
[prompts](JAWL_PROMPT_ARCHITECTURE.md), [reasoning](REASONING_POLICY.md),
[sensory](SENSORY_STACK_DESIGN.md), [memory](SECONDARY_MEMORY.md).
Wire contracts в `docs/contracts/`; UI inventory в `docs/ui-registry/`.
Запуск/поставка: [RELEASE](RELEASE.md), [LAN](LAN.md), [OBS](OBS.md).
Арт: [direction](CHARACTER_ART_DIRECTION.md), [animation](AVATAR_ANIMATION_PLAN.md),
[последний candidate V9](CHARACTER_INTERFACE_V9_REVIEW.md).
Research: [каталог](RESEARCH.md). ADR: [DECISIONS](DECISIONS.md).

Справочники описывают детали и историю, не отдельную активную очередь.
При расхождении defaults/приоритета главнее текущие STATE/manifest и DAILY_PLAN.
Все функции сохраняются; старые заявления PASS ограничены своим report/profile.

## Архив

[Индекс14Oct](history/2026-10-14-daily-reset/INDEX.md) содержит сохранённые
оригиналы и правила восстановления. Прежние `docs/history/` остаются историей.
Короткие ссылки на старых путях нужны совместимости ссылок, не являются планами.
Runtime reports/data/models не удаляются и не переносятся этой уборкой.
`config/jawl/**/*.md` — runtime prompts, не архивируемая документация.
