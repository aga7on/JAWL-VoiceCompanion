# Полный остаток работ и оценка

Срез **2026-10-10** по локальной документации, исходникам и сохранённым отчётам.
Это инженерная оценка, **не измеренный процент готовности** и не обещание срока.
Новых runtime/device/model запусков при аудите не было.
[STATE](STATE.md) · [TODO](../TODO.md) · [матрица](TECHNICAL_AUDIT.md) · [карта](README.md).

## Общая оценка

Рабочая интеграционная основа существует: JAWL native core/recovery/policy,
сенсорные adapters, Electron/VRM, capture/gate и потоковый playback,
ConfigHub и regression gates. Проект не является пустым макетом.
Но цель «поселить личность на ПК» ещё не принята как единый ежедневный продукт.

Основной остаток — согласование и проверка контуров, плюс конкретно недостающие
UI/память/CDP/интеграции и значительная художественная работа. Не нужен полный
rewrite в монолит; нужны один ownership, контракты, feedback и reproducible release.

## Весь функциональный остаток

| Направление | Что уже есть | Что осталось / ссылка на TODO |
| --- | --- | --- |
| Brain/persona/SOUL/context |JAWL canonical owner, provider/JSON/tool contracts |Current semantic acceptance, context budget без урезания native арсенала; B3-01/04 |
| Сменные LLM/QWB |JAWL provider boundary |Native tools/terminal/error/context compatibility каждого provider, не просто chat completion; B3-01 |
| Fast chat и цели |Native goals/ledger, отдельные recovery slices |Explicit goal_execution/reasoning profiles, voice checkpoints, task≠speech cancel; B3-02/05 |
| Heartbeat/Swarm/Attention |Механизмы ядра и attention gate |Общий фокус/priorities, no double decisions, закрытая панель; B3-03/B4-01 |
| Native PC/RE tools0–3 |Discovery/registry/policy и representative acceptance |Current namespace/risk parity, safe effects/postconditions, recovery; B3-06 |
| CDP/browser/sandbox |openURL/UIA adapter и native tool seam |Изолированный useful CDP workspace, DOM/cancel/audit/postcondition; B3-07 |
| Night Full Access |Supervisor/lease/revoke/checkpoint slices |Current8h unattended, сбои, Stop, no blind retry, morning journal; B4-01 |
| Каноническая память |Факты/черты/предпочтения/сводки/заметки/задачи/mental states/drives/hypotheses/ticks/timeline/journal |Library UI, semantic correction/recall, erasure/derived data; P-01/03,U-05 |
| Ambient T0–T3 |Bounded capture, T1/T2 triage, manual promote |T1/T2/consent durable, dedup/TTL, automatic JAWL consolidation; P-04/05 |
| VoiceMem memory |Semantic/graph recall и heartnote/response_experience/interaction evidence |Использовать как attributed context/candidates, не второй memory authority; P-01/05 |
| System audio |Loopback/segmentation/queues и synthetic recovery |Physical long audio/own-TTS/priority, source uncertainty; P-06 |
| Vision |screen-watch/fusion/VLM/action-plan validation |Текущий RU OCR/grounding, fresh fused context, native action closed loop; P-07/08 |
| Music/sound/voice mood |Adapter seam, не принятая capability |Small RU benchmark captioner/affect, uncertainty, no diagnosis; P-09 |
| Default senses/privacy |Trust boundaries и capture controls |Настроенный ordinary profile, visible pause/revoke/sensitive sources, no raw archive; P-10 |
| Microphone/gate |Device selection, hysteresis/pre-roll/endpoint/lease |Physical calibration, slow/quiet/long speech, UI partials и peaks; B2-02/04 |
| Interruptible voice |NDJSON progressive playback, bounded schedule/cancel/stale drop |Real workers, acoustic echo/duplex, fast Stop, actual latency; B1/B2 |
| TTS/expressiveness |Tera default; Omni/Vox options, envelope emotion, RMS lips |Provider-specific quality/emotion/clone, timing lips и fallback; B2-06,A-04 |
| Основной чат |Text+mic native stream |History/reconnect/retry, files/images/audio/video capability routing, emoji/slash; U-03/04 |
| Общая панель JAWL |Adapters/ConfigHub/revisions/backups/readback |Complete inventory, lists/object-lists/effective/restart, tasks/library, clear mint Aero; U-01/07 |
| LAN/tablet/mobile |HTTPS/auth/Origin foundation |Actual device, responsive/touch/keyboard/mic/reconnect; U-08 |
| OBS/presentation |Presentation-only security boundary и legacy evidence |Current VRM same state, no private/control leak, installed OBS/DPI/multimonitor; U-09 |
| Livestream chat |Требование/архитектурная граница |Chat/Restream source, moderation/rate limit, occasional JAWL response; S-01 |
| Social accounts |Требование scoped autonomy |Owner-connected accounts, credentials/publish policy/idempotency/audit; S-02 |
| Avatar appearance |V9 candidate, rig/morphs/export/limited geometry checks |Hair/face/proportions/garment/boots/UV/material quality ≥90 rubric; A-02/05 |
| Avatar physics |Weighted hair+colliders и6soft helpers |Full tested hair/cloth/body/chest/hip collision-aware movement matrix; A-03 |
| Avatar animations |Procedural idle/listen/speak/greeting/nod;5VRMA exported |One pose owner, minimal graph/retarget/crossfade/gaze/mimic/timing lips; A-04 |
| Resources |Partial buffer/context limits and old resource probes |Whole profile RAM/VRAM/CPU/frame-time/queues/log/token budgets and game priority; B4-02 |
| Install/update/rollback |Wheel smoke/snapshot tooling, shared manifest PS/Python/Electron и fixture preflight |Whole-profile/live/Rust portability; clean profile+workers+assets/licenses, migrations/restore/rollback; B0/B4-03/04 |
| QA/release/docs |Regression and saved slices, consolidated current docs |Current linked daily acceptance + hardware/OBS/8h tests + owner acceptance; B4-06 |

«Эпизод» ambient T2 не заменяет все сущности канонической памяти JAWL.
«Забыть» не physical erasure. «Открыть URL» не successful DOM task.
«Стриминг transport» не гарантия мгновенного LLM/TTS first audible.
«Движется helper bone» не вся физика тела/ткани. Эти различия входят в приёмку.

## Трудоёмкость оставшейся работы

**1 человеко-день ≈6 часов сосредоточенной работы** квалифицированного
исполнителя. Это не6часов runtime и не число запросов/агентов.
Диапазоны включают локальную интеграцию/приёмку пакета; общие gates
пересекаются. Не суммировать верхние оценки как точный календарный deadline.

| Пакет | Остаток, чел.-дни |
| --- | ---: |
| Brain/provider/context + fast chat/goals + Heartbeat/Attention |6–11 |
| Canonical/ambient memory lifecycle, persistence, consolidation, erasure |6–10 |
| System audio/vision fusion + music/non-speech/affect capability |7–15 |
| Native tools/CDP + current recovery/8h unattended acceptance |6–10 |
| Живой voice path/partials/device/duplex/cancel/expressiveness |9–17 |
| Unified UI/config/chat/library/tasks + LAN/OBS/lifecycle/release |25–44 |
| Stream chat/social scoped integrations |6–12 |
| Avatar art/physics/motion, без дублирования voice transport |18–35 |

Общий порядок полного остатка — **около80–140человеко-дней** после вычета
перекрытий, а не «ещё пару правок». Диапазон особенно неопределён для art,
acoustic echo, VLM и live cancellation выбранных providers.
Новые сложные capabilities могут вывести работу за диапазон.

Практические ступени, **не складывать друг с другом**:

- Первый удобный ежедневный conversation+memory+safe task сценарий:
  ориентировочно15–25чел.-дней, без full settings parity/финального art/social.
- Надёжная основная версия с голосом, памятью, PC tasks, общей панелью,
  LAN/OBS и release hardening: ориентировочно50–90чел.-дней;
  без идеального custom art и будущих социальных интеграций.
- Весь обсуждённый объём с финальным персонажем/физикой/стрим-чатом/social:
  ориентировочно80–140чел.-дней.

Это не пользовательский контракт. Два-три непересекающихся потока сокращают
календарь, но не линейно: интеграция, hardware acceptance,8h soak и решение
владельца остаются на критическом пути. Разработка без согласованного профиля
или постоянная смена моделей делает оценку непригодной.

## Критический путь и неопределённости

1. Baseline/effective profile → real Stop/cancel.
2. Current RU voice path → hardware echo/duplex/barge-in/latency.
3. Persona/memory/task/native effect/restart continuity в одном сценарии.
4. Complete useful UI + persistent sensory memory → LAN/actual VRM OBS.
5.8h unattended + clean install/restore/rollback → release acceptance.
6. Art/physics/motion параллельно, финальный owner acceptance отдельно.

Для ≥90 likeness нужна целенаправленная художественная работа с shapes/mesh/
UV и сравнением, не только процедурные правки и новый solver.
Ресурсы CPU/RAM предпочтительны там, где сохраняются качество/задержка;
GPU0 не занимать неявно. Layer offload/Crane/new quant — исследовательские
варианты, не обязательный blocker готового продукта.

Пересчитать оценку после B2/B3: реальные latency, акустика, worker cancel,
effective profile и выбор финального art существенно уточнят остаток.
