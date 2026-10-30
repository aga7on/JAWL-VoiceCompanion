# Текущие риски и проверка

14Oct2026. Evidence — [STATE](STATE.md); приёмка — [DAILY_ACCEPTANCE](DAILY_ACCEPTANCE.md).

| Приоритет | Риск | Исправление |
| --- | --- | --- |
| P0 | Hooks только в console, brain отдельный | D1 actual child entry/installation proof |
| P0 | Потерянный четвёртый R6 ответ | D1 terminal delivery; fail-fast при error, без thoughts fallback |
| P0 | Реальные голосовые задержки слишком велики | D2 stage timing, нормальный conversational path |
| P1 | Mic/echo/перебивание не приняты физически | D2 наушники+Stop сначала, acoustic duplex отдельно |
| P1 | Сцена и сенсоры не приняты как постоянный companion | D3/D4 единый daily UX/context/attention |
| P1 | Tool dispatch не доказательство действия/памяти | D5 native postconditions/restart/reconciliation |
| P1 | Короткий PASS не24/7 | D6 измеренный8h soak и recovery |

Полная историческая матрицаM01–M26 сохранена
[в архиве](history/2026-10-14-daily-reset/docs/TECHNICAL_AUDIT.md).
Она применяется к полному продукту; ближайшая daily версия имеет явный
scope/known limitations. Не закрывать задачи числом тестов или статусом HTTP200.
