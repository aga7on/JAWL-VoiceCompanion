# Документация JAWL Companion

Карта на **2026-10-12**. Здесь перечислены рабочие документы, контракты и
датированные свидетельства. **Планы не означают реализованную capability.**
Последний полный regression — 12OctMoscow (scoped client POST), direct child exit0:
779 unit /66 pytest /16 HTTP /86 Node /6 legacy browser /8 desktop checks.
Receipt gate-client-post-20261012,343 frozen sources, отдельные actual Tera
CPU, installed SDK и owned native console probes — [STATE](STATE.md).
Сверка документации сама по себе не обновляет device/model evidence.

## Как читать и что имеет приоритет

1. Последнее явное поручение владельца определяет текущий scope.
2. [PRODUCT](PRODUCT.md) — согласованный замысел и границы продукта.
3. [STATE](STATE.md) — реализованное и доказанное, с пределами evidence.
4. [TODO](../TODO.md) — **единственная активная очередь** реализации.
5. [TECHNICAL_AUDIT](TECHNICAL_AUDIT.md) — приёмочная матрица и инженерные риски.
6. Архитектура/контракты выбранной границы; затем нужный датированный report.

[AGENTS](../AGENTS.md) задаёт правила работы; [HANDOFF](../HANDOFF.md) — краткий
вход для следующего исполнителя. Не загружать архивные тысячи строк в каждый
запрос. Полный остаток с диапазонами трудоёмкости: [WORK_REMAINING](WORK_REMAINING.md).

## Текущая база

Одна платформа, один JAWL brain/memory/tasks/policy, сенсорная инфраструктура
VoiceMem, клиент Electron/web + three-vrm. Hikari Bonsai-2 PQ2_0 — выбранный
brain, GigaAM v3 — only ASR, TeraTTSv2 — default TTS, OmniVoice — опция.
Ранние Live2D/2D/Qwen-ASR/default Qwen-TTS указания не текущие.
Default launchers расходятся с selected profile — B0, не скрытая смена решения.

## Продукт, план и архитектура

| Документ | Роль |
| --- | --- |
| [Корневой README](../README.md) |Вход в проект, демо vs connected, ссылки |
| [PRODUCT](PRODUCT.md) |Требования/поведение, не статус готовности |
| [STATE](STATE.md) |Короткий текущий срез, факты/evidence/ограничения |
| [TODO](../TODO.md) |Одна очередь B0–B4/P/U/A/S и проверяемые выходы |
| [WORK_REMAINING](WORK_REMAINING.md) |Полный функциональный остаток и приблизительная оценка |
| [TECHNICAL_AUDIT](TECHNICAL_AUDIT.md) |Риски, matrix M01–M26 и protocol evidence |
| [RECOVERY_PLAN](RECOVERY_PLAN.md) |Последовательность стабилизации, durable recovery-инварианты |
| [PRODUCTION_DELIVERY_GOAL](PRODUCTION_DELIVERY_GOAL.md) |Delivery specification; Markdown не регистрирует goal |
| [ARCHITECTURE](ARCHITECTURE.md) |Компоненты/потоки/границы ownership |
| [UNIFIED_RUNTIME](UNIFIED_RUNTIME.md) |Модульный runtime одного продукта |
| [CORE_OWNERSHIP](CORE_OWNERSHIP.md) |Единственные owners, устранение дублей |
| [JAWL_CANONICAL_CAPABILITIES](JAWL_CANONICAL_CAPABILITIES.md) |Арсенал JAWL и правила сохранения лучшей реализации |
| [JAWL_PROMPT_ARCHITECTURE](JAWL_PROMPT_ARCHITECTURE.md) |SOUL/контекст/память/prompt, не скрытый второй мозг |
| [REASONING_POLICY](REASONING_POLICY.md) |Fast chat и goal execution; target vs actual |
| [COMPATIBILITY](COMPATIBILITY.md) |Версии/совместимость/профили и ограничения |
| [SENSORY_STACK_DESIGN](SENSORY_STACK_DESIGN.md) |Audio/vision/attention как инфраструктура |
| [SECONDARY_MEMORY](SECONDARY_MEMORY.md) |T0–T3, canonical JAWL vs ambient/VoiceMem |
| [DECISIONS](DECISIONS.md) |Хронологические ADR; поздние заменяют ранние |
| [CHANGELOG](../CHANGELOG.md) |Хронология фактических изменений, не очередь |

## Wire и поведенческие контракты

JSON — семантические сообщения/metadata, не запрет на bounded media streaming.
Описание API и код не заменяют доказательство user-visible результата.

- [JAWL gateway](contracts/jawl.md) и [LLM/provider](contracts/llm.md).
- [Response envelope](contracts/response-envelope.md), [events](contracts/events.md).
- [Voice/ASR](contracts/voice.md), [TTS](contracts/tts.md).
- [HostOS](contracts/hostos.md), [native JAWL authority](contracts/jawl-hostos.md).
- [Avatar](contracts/avatar.md): current VRM boundaries; legacy Live2D scope отдельно.

## Интерфейс, запуск и эксплуатация

| Документ | Роль / граница |
| --- | --- |
| [UNIFIED_UI_INTEGRATION_PLAN](UNIFIED_UI_INTEGRATION_PLAN.md) |План полной parity панели JAWL, не выполненный чеклист |
| [UI_ACCEPTANCE](UI_ACCEPTANCE.md) |Сценарии UI/внешнего вида, actual interactions |
| [UI_REGISTRY](ui-registry/UI_REGISTRY.md) |Сверяемый field/action inventory |
| [U6_PARITY_STATUS](ui-registry/U6_PARITY_STATUS.md) |Current header + исторические snapshots покрытия, не текущий процент |
| [CONFIG_CONTRACTS](ui-registry/CONFIG_CONTRACTS.md) |Writer/revision/secrets/readback/effective/restart |
| [RELEASE](RELEASE.md) |Launchers, зависимости/поставка и открытые release gates |
| [JAWL_RUNTIME_INVENTORY](JAWL_RUNTIME_INVENTORY.md) |Owned runtime provenance, historical vs selected defaults |
| [LAN](LAN.md) |HTTPS/auth/Origin; actual tablet/mobile acceptance OPEN |
| [OBS](OBS.md) |Presentation boundary, VRM target и отдельно legacy instructions |
| [VOICE_PLAYBACK_BUFFER](VOICE_PLAYBACK_BUFFER.md) |Progressive audio/limits/cancel; не доказательство real worker stop |

## Персонаж

- [CHARACTER_ART_DIRECTION](CHARACTER_ART_DIRECTION.md): обязательный образ,
  rubric ≥90 и matrix физики, owner acceptance.
- [AVATAR_ANIMATION_PLAN](AVATAR_ANIMATION_PLAN.md): лёгкий pose graph/VRMA/
  lips; состояние реализации не выводить из плана.
- [Эталон turnaround](concept/jawl-companion-turnaround-v1.png),
  [концепт](concept/jawl-companion-pinup-v1.png).
- Последний отдельный кандидат:
  [CHARACTER_INTERFACE_V9_REVIEW](CHARACTER_INTERFACE_V9_REVIEW.md).
  Technical PASS не означает принятого art или active switch.

Датированные reviews сохраняют свои входы/SHA/runs/FAIL/PASS:
[delivery20261004](CHARACTER_DELIVERY_20261004.md),
[closeups20261004](CHARACTER_CLOSEUP_AUDIT_20261004.md),
[blockingV3](CHARACTER_BLOCKING_V3_REVIEW.md),
[fitV4](CHARACTER_FIT_V4_REVIEW.md),
[shoulderV6](CHARACTER_SHOULDER_V6_REVIEW.md),
[hairV7](CHARACTER_HAIR_V7_REVIEW.md),
[hairV8](CHARACTER_HAIR_V8_REVIEW.md).
Не редактировать цифры старого report для согласования с новой моделью.

## Research и benchmark — не active defaults

- [LLM_MODEL_CANCEL_BENCHMARK](LLM_MODEL_CANCEL_BENCHMARK.md): actual selected
  Hikari CPU r1/r2 FAIL35s;9 diagnostic tests не заменяют compute-release PASS.

- [RESEARCH](RESEARCH.md): исследованные upstream patterns/лицензии.
- [3D AI News/AIRI](RESEARCH_3D_AI_NEWS_AIRI.md): очередь перспективных идей,
  внедрение по slices, не whole AIRI/второй brain.
- [ActionForge idle-петли](RESEARCH_ACTIONFORGE_IDLE_LOOP.md): CC0-клипы движения
  для A-04 (idle/жесты); путь GLB→VRMA после ретаргета, ассеты вне git.
- [NEKO family](NEKO_FAMILY_AUDIT.md), [NEKO deep analysis](NEKO_DEEP_ANALYSIS.md).
- [DUPLEX_RESEARCH_ADOPTION](DUPLEX_RESEARCH_ADOPTION.md),
  [COMPANION_VISION_REVIEW](COMPANION_VISION_REVIEW.md): рекомендации своих дат.
- [MODEL-TESTS](MODEL-TESTS.md), [AMBIENT_TRIAGE_BENCHMARK](AMBIENT_TRIAGE_BENCHMARK.md).
- [MULTIMODAL_MODEL_GATE](MULTIMODAL_MODEL_GATE.md): capability-specific RU gate
  до большого скачивания; четыре RU tests для Omni-замены, N/A с причиной
  для специализированной модели.
- [MINICPM_O45_BENCHMARK](MINICPM_O45_BENCHMARK.md): EN opt-in/RU FAIL неизменен;
  [MINICPM5_1B_REVIEW](MINICPM5_1B_REVIEW.md) — отдельный исследовательский кандидат.
- [CRANE_VLM_GATE](CRANE_VLM_GATE.md) и [CRANE_ACCEPTANCE_20260908](CRANE_ACCEPTANCE_20260908.md).
- [COSYVOICE3_CPU_BENCHMARK](COSYVOICE3_CPU_BENCHMARK.md),
  [VOXCPM_INTEGRATION_20260909](VOXCPM_INTEGRATION_20260909.md).
- [PRODUCTION_STATUS_20260909](PRODUCTION_STATUS_20260909.md): исторический срез,
  название файла не означает сегодняшний production-ready.

## Архив и файлы вне этого каталога

- [Архив до консолидации2026-10-10](history/2026-10-10-before-docs-consolidation/INDEX.md)
  сохраняет длинные STATE/TODO и исходные README/HANDOFF/audit/recovery.
- [Архив2026-09-05](history/2026-09-05-before-product-audit/README.md) — ещё более
  ранний продуктовый срез. Относительные команды/ссылки архивов относятся
  к их исходной структуре, не к текущей инструкции.
- `config/jawl/**/*.md` — **runtime prompts/SOUL**, не документация.
  Docs-only не разрешает менять поведение через эти файлы.
- `runtime/**` — локальные модели/assets/logs/reports, не воспроизводимая
  поставка только потому, что файл есть на этой машине.
- Protected JAWL-Coding/VoiceMem/RE — read-only references/toolchain.

## Правила поддержки документации

Функция имеет один task ID в TODO и один current status в STATE.
Контракт не обещает target API как существующий; roadmap не дублируется
между HANDOFF/recovery/delivery/research. При смене решения обновить
PRODUCT/ADR/контракт и применимые gates, историю не переписывать.

Для evidence фиксировать дату/profile/versions/run/turn, вход/ожидание/
наблюдение/exit code и границы synthetic/provider/device/OBS/owner acceptance.
Для docs-only достаточно ссылок/согласованности/encoding и diff-check;
не запускать модели и hardware для подтверждения текста.

## Проверка консолидации — 2026-10-10

- Проверен актуальный набор: 68 Markdown-файлов, 373 локальные ссылки;
  отсутствующих путей/заголовков и ошибок UTF-8 нет.
- Карта покрывает все 62 текущих документа в `docs/` вне historical archive,
  плюс корневые правила/вход/очередь/историю изменений.
- Текст всех шести исходных снимков сохранён полностью; архивные относительные
  ссылки остаются привязаны к исходным путям, как явно указано в INDEX.
- `git diff --check -- '*.md'` PASS. Проверка кодировки Crane имеет отдельную
  резервную копию исходных смешанных байтов, не меняет benchmark-результат.
- Код/runtime/config/prompts/models/devices/active avatar и protected references
  не менялись. Эти проверки не добавляют runtime evidence после 2026-10-05.
