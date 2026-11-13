# Адаптация google-research/harness2 (Recursive Agent Harnessing) под JAWL/DSH — 2026-11-10

Источник: https://github.com/google-research/harness2 — Propose–Probe–Compose на уровне задачи + рекурсия уровня harness с накоплением принятых harness/уроков (improvement harness), без обновления весов модели.

## Маппинг на нашу связку (я = оркестратор/инженер, DSH = воркер-исполнитель)
| Harness² | У нас |
|---|---|
| Execution harness / executor | DSH в браузере (worker), действует по одной итерации; кодовая база JAWL — среда |
| Task-level Propose–Probe–Compose | Я формулирую следующий ограниченный пункт дорожной карты (Propose) → DSH выполняет итерацию (Probe: код+regression+числа) → я читаю `STATE/TODO/CHANGELOG`+дифф/тесты и принимаю/корректирую, фиксируя урок (Compose) |
| Harnessing-level recursion / improvement harness | Накопительный файл уроков/принятых решений: `tools/seniors_bridge/IMPROVEMENT_HARNESS.md` + обновляемые roadmap/карты; нуджи оркестратора читают актуальный контекст |
| Evidence, не ground-truth оракула | `STATE/CHANGELOG` факты, результаты focused regression, числа задержек; спорные PASS помечаются VERIFIED только при воспроизводимом доказательстве |
| Parallel/sequential k | Последовательно по приоритету (full-duplex P0→P5, затем sensory motivation), одна итерация = один видимый результат (AGENTS.md) |

## Практические правила оркестрации
1. После каждого завершённого хода DSH: прочитать отчёты, сверить claims (точечно прогнать cited focused tests), записать урок/решение в `IMPROVEMENT_HARNESS.md`.
2. Следующее задание — не общий «продолжай», а конкретный пункт с критерием приёмки и запретом на фальшивый PASS; при BLOCKED — фиксировать причину и брать следующий выполнимый.
3. При 503/падении модели — backoff + узкий, самодостаточный промпт; при повторном провале — инженерная итерация мной.
4. Дедлайн 11:00 10.11.2026 ПК: непрерывность через detached оркестратор + мой сессионный контроль.

## Статус адаптации
- [x] Дорожная карта full-duplex (`docs/FULLDUPLEX_ROADMAP.md`), инженерная карта (`docs/FULLDUPLEX_MAP.md`), оркестратор до дедлайна.
- [~] Накопительный improvement harness и контекстные нуджи — внедряется сейчас.
- [ ] Явный цикл Propose→Probe→Compose с записью уроков после каждой итерации DSH — по мере завершения ходов.
