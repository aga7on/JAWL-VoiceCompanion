# Проактивная сенсорика через мотивации (drives) — дизайн-черновик, 2026-11-10

Идея владельца: создать мотивацию сенсорики; если в описаниях изображений в памяти появляется что-то, что мозг сочтёт интересным, мотивация поднимается и JAWL отвечает проактивно.

## Факты архитектуры (проверено)
- Drives/мотивации: `system.db.sql.drives` (fundamental: curiosity/social/mastery, decay/interval), пути в `config_hub.py`; `/api/drives` в `jawl_web.py`. Поведение/CRUD в read-only snapshot `runtime/jawl-sources/jawl-20260906-daily-v2/src/web/drives.py` и L1 SQL management — **не патчить snapshot**.
- Сенсорика/описания экрана: `sensory_history`, `episodic_visual_memory` (`composition.py`, `web.py`), `memory_policy.py` классифицирует `screen_description`; `eg2_describer.py` даёт описание; `screen_commentary.py` + `ProactiveFeed.deliver_direct` уже умеют bounded проактивный ход с rate limits/«тишина».
- `proactive_guidance` и `screen-commentary` флаги есть (история STATE).

## Предлагаемый контракт (companion-side, без правок snapshot)
1. **Источник сигнала:** новое `screen_description`/visual observation (или дельта episodic visual memory) с текстом описания.
2. **Оценка интересности (детерминированный v0):** novelty относительно недавних описаний (overlap/EG2-инфраструктура есть в проекте) + маркеры изменения/значимости; порог. LLM-«интересно» — дорогой режим, не v0.
3. **Мотивация:** выделенный сигнал «sensory_curiosity» в companion policy/telemetry; опционально отразить на `curiosity` drive через разрешённый owned интерфейс (`/api/drives`/настройки), если доступен в живом контуре — **не второй источник правды**. При недоступности write-пути: companion-side счётчик с семантикой рост/decay/порог, логируемый.
4. **Проактивный ответ:** при пороге + turn-policy (idle, не mute/quiet, rate limit, не во время user/assistant speech, echo-safe) — bounded observation turn в JAWL («что изменилось/почему важно» по факту описания), мозг может ответить «тишина». Доставка через proactive/screen_commentary.
5. **Без спама/галлюцинаций:** только факт описания, цитирование наблюдения, cooldown; метрики срабатывания/подавления/ложные поводы — UNKNOWN до owner review.

## Шаги
- **P-M0 (выполнимо):** контракт + детерминированный скорер novelty/interest + wiring в companion, без правок read-only snapshot; focused tests.
- **P-M1 (может быть BLOCKED):** связь с реальным drive/curiosity через разрешённый owned путь после проверки живого контракта.
- **P-M2:** owner-tuned пороги, live/mic проверка.