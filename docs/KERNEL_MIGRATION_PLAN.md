# Миграция ядра JAWL (ADR-049) — план

**Цель:** `JAWL` = owned-ядро. Дефекты и capability, которые продукт чинит
extension-слоями `native_*` снаружи ядра, переносятся в поставку ядра
минимальными upstream-worthy патчами (patch-queue к `th0r3nt/JAWL`).
**Конечная точка:** в `src/` не остаётся модулей, чинящих ядро снаружи.

> Правило среза: правки делать слайсами «правка в ядре + снятие хука + focused
> regression» одним изменением; двойных слоёв не копить. После каждого блока —
> full gate. Каждый коммит — сразу push (работа не должна жить только локально).

## Baseline

- Снимок `runtime/jawl-sources/jawl-20260906-daily-v2` = upstream `th0r3nt/JAWL`
  @ `4e25fe9` + owned-отклонения; инвентарь и digest держит
  `SOURCE_MANIFEST.json`, целость — `scripts/verify_jawl_snapshot.py`.
- Отчёт отклонений: `docs/research/kernel-upstream-baseline-20261029.md`,
  патч: `patches/kernel/owned-deviations.patch` (генератор —
  `scripts/kernel_upstream_diff.py`; `unstaged` в отчёте должен быть 0).

## Очередь слайсов (правка ядра → снятие хука → тесты)

| # | Модуль-источник | Ядро | Статус |
| --- | --- | --- | --- |
| 1/1b | `native_policy_completion` | goals/policy_completion (policy denial) | DONE `6996f0b` |
| 2 | `native_jawl_streaming` | `llm/speech_first.py` + tee в `openai_compatible` | DONE `1cd7082` |
| 3 | `native_jawl_turn_context` | `context/companion.py` + `context/perception_packet.py` | DONE `1b447ff` |
| 4 | `native_jawl_json_format` | `llm/envelope_policy.py` (+`CompanionTurnState`) | DONE `b6dba07` |
| 5 | `native_jawl_action_repair` | `react/action_repair.py` | DONE `7318a39` |
| 6 | `native_terminal_context_compaction` | `l2_interfaces/host/terminal/compaction.py` | DONE `635c81b` |
| 7 | `native_goal_wakeup_backoff` | `goals/wakeup_backoff.py` | DONE `e30329a` |
| 8 | `native_goal_completion_repair` | `goals/completion_repair.py` | DONE `636189f` |
| 9 | `native_jawl_admission` | admission нативен | DONE `e58eb20` |
| 10 | `native_jawl_delivery` | delivery нативен (`_CYCLE`) | в работе |

Срезы 1–8 перенесены заново после потери рабочей песочницы и опубликованы в
`origin/reorg/kernel-migration-20261029`. Receipt финализирован:
`write_startup_receipt(snapshot, delivery)`, hooks = `{"delivery_guard": True}`.

**Full gate после срезов 1–9:** 1288 passed / 64 skipped / 285 subtests /
37 failed — ровно env-базовая линия (config_hub/web `from web import config_io`,
e2e, voice_capture, preflight со старым снапшот-путём, skill_aliases с
`jawl-20260905-daily-v1`); ничего из падений не связано с миграцией.

**Решение по slice-10 (зафиксировано для продолжения):** hooks-канон сохраняет
`delivery_guard` → `install_native_delivery_guard` остаётся owned-хуком
(receipt сверяет обёртки на трёх классах). «Delivery нативен (`_CYCLE`)» =
пер-ходовая state-машина `_CYCLE`/`_CycleState` (terminal_event, locks,
suppress_private_completion, parent-цепочка) и её хелперы переезжают в
`companion_gateway` (рядом с `CompanionTurnState`); продукт
`native_jawl_delivery.py` делегирует состояние kernel-модулю, guard-обёртки
(observed_emit/guarded_broadcast/guarded_completion/guarded_publish/
guarded_run/emit_missing_terminal) остаются поведением установки, чтобы
фикстуры `test_native_jawl_delivery.py`/`test_native_delivery_snapshot.py`
(19 кейсов на фейковых классах) оставались зелёными. Стираемые дубликаты:
`native_policy_denied`/`record_native_policy_denial` (в ядре с slice-1 —
`goals/policy_completion`), `native_companion_chat_active`/
`active_companion_message` (в ядре с slice-4 — `CompanionTurnState`),
`NATIVE_POLICY_DENIAL_REASON` (источник — `utils/policy_denial`).
`emit_active_delta` — перенести в kernel-модуль без изменений API.

### DONE-записи

- `6996f0b` slice-1/1b — policy denial: `utils/policy_denial.py` +
  `goals/policy_completion.py` (NATIVE_POLICY_DENIAL_REASON, per-turn latch);
  `_check_security_policies` — нативный wrapper, fail-fast в `call_skill`.
- `1cd7082` slice-2 — streaming: `llm/speech_first.py`, `SpeechDeltaSink` +
  `COMPANION_SPEECH_DELTA`, `_stream_first_request`/`_tee_speech`; продукт
  `speech_first.py` — shim.
- `1b447ff` slice-3 — turn context: `context/companion.py`
  (`jawl_companion_turn_binding`, casual-лейн, declared capacity),
  `context/perception_packet.py`; продукт `perception_packet.py` — shim.
- `b6dba07` slice-4 — envelope policy: `llm/envelope_policy.py`
  (`apply_envelope_policy` нативен в `_request_kwargs`), `CompanionTurnState`.
- `7318a39` slice-5 — action repair: `react/action_repair.py`
  (`parse_with_repair` нативен в `_parse_response`).
- `635c81b` slice-6 — terminal compaction:
  `l2_interfaces/host/terminal/compaction.py` (нативен в `get_context_block`).
- `e30329a` slice-7 — goal wakeup backoff: `goals/wakeup_backoff.py`
  (делегирование из `GoalManager`).
- `636189f` slice-8 — goal completion repair: `goals/completion_repair.py`
  (`consider_completion_repair` в `_parse_response`, `note_protocol_error` в
  `_handle_protocol_error`, `_goal_v2_payload` probe).

### Уточнение механики (обязательно для слайсов)

Extension'ы помечают отказ **на моменте raise** (обёртка над
`_check_security_policies`), поэтому kernel-патч повторяет именно эту
механику: attempt-область вокруг вызова скилла + пометка в точке отказа,
а не только `except PermissionError` в `call_skill` (скилл может
проглотить исключение). Пер-тур latch живёт в `companion_gateway`
по `companion_turn_id` — изоляция между параллельными ходами бесплатна.

## Фазы (strangler: после каждой продукт жив, без big bang)

- [x] **Фаза 0 — рабочий слой и мораторий.** `backup/` — рабочий клон;
  вся перекладка — ветка `reorg/kernel-migration-20261029`; `main` не трогаем.
- [x] **Фаза 1 — инфраструктура owned-ядра.** Patch-queue: verify-скрипт,
  генератор upstream-отчёта/патча, правило среза, ADR-049/050.
- [ ] **Фаза 2 — съедаем `native_*`** по таблице, шаг за шагом (правка в ядре →
  снятие хука → focused regression; раз в несколько шагов — full gate). Очередь
  по влиянию на каждый день работы:
  1. `native_jawl_streaming` + `native_jawl_json_format` (латентность голоса — H2/H3);
  2. `native_jawl_delivery` + `native_jawl_turn_context` (надёжность хода);
  3. `native_goal_*` + `native_policy_completion` (goal lifecycle);
  4. `native_jawl_admission` + `native_jawl_action_repair` (прочее).
- [ ] **Фаза 3 — голос и восприятие в extension points.** Контракты голосового
  turn и perception-packet оформляются как `l2_interfaces/voice` и
  `l2_interfaces/multimodality` ядра; inference-воркеры остаются отдельными
  процессами за их client-API.
- [ ] **Фаза 4 — консолидация UI** (это H1 из TODO): один Product API
  (канонические сущности ADR-041); desktop app и LAN-web — один бандл;
  web cockpit JAWL — dev/admin, не продуктовая поверхность.
- [ ] **Фаза 5 — перекладка репо по папкам** — только когда границы фаз 1–4
  доказаны. Папки — последний шаг, не первый.

## Правила переноса

1. Один модуль — один срез: правка в ядре + снятие обёртки + focused regression
   в одном изменении. Не копить «двойной слой».
2. Патчи ядра оформляются как upstream-worthy изменения (минимальные, с
   тестами), чтобы очередь патчей была вливаема обратно в `th0r3nt/JAWL`.
3. Docs-only срезы — по правилу из AGENTS.md (ссылки/hash/diff-check, без моделей).
4. После каждого переноса — focused regression; после каждого блока фазы —
   full gate и живой сценарий затронутой функции (DAILY_ACCEPTANCE).

## Deployment parity (ADR-048) — отдельный срез

Манифест `config/runtime.manifest.json` всё ещё выбирает `local-hikari` /
`local-bonsai2` и legacy visual EG2; требуемые дельты зафиксированы в TODO D0
(«ADR-048 deployment parity»). Правку манифеста выполнять отдельным срезом с
live-проверкой запуска Gemini relay + Qwen3.5-0.8B — не в этой ветке.

## Источники

- ADR-034 (coherent behavioral core), ADR-041 (Product Core поверх engines),
  ADR-048 (канон моделей), ADR-049 (ядро), ADR-050 (двухскоростной контур).
- [TODO](../TODO.md): H1–H5, D0; [HARMONIZED_ARCHITECTURE_AND_ROADMAP.md](HARMONIZED_ARCHITECTURE_AND_ROADMAP.md).
- [STATE.md](STATE.md); upstream: https://github.com/th0r3nt/JAWL (MIT).
