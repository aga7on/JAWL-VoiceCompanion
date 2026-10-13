# Текущее состояние — 14 октября 2026

Ветка: `dev/daily-companion-20261014`, базовый HEAD `0e53329`.
Dirty worktree владельца сохранён, нового release commit нет.
Ближайшая цель: [ежедневная версия](DAILY_PLAN.md). Очередь: [TODO](../TODO.md).
Подготовка ветки и документов не исправляет runtime и не является live acceptance.

## Последние проверенные результаты

- Full gate `runtime/gate-turn-context-20261014.json`: exit0,
  875unit/66pytest/16HTTP/104Node +6legacy browser/8desktop checks.
  Synthetic regression, не гарантия живого разговора.
- [R6 receipt](../runtime/live-voice-turn-context-20261014-r6.json): TERMINAL FAIL.
  Три полных озвученных ответа, четвёртый native turn.error; browser ожидал TTS
  до timeout. Cleanup всех пяти owned listeners/Jobs PASS по receipt.
- Первый звук11.245/12.396/33.346с от начала тестового хода, включая входную речь.
  Обработка voice/end4.389/4.986/27.640с. Не выдавать первую метрику за паузу
  после окончания речи. Physical mic/full duplex/24x7 не приняты.
- R6 source baseline362/SHA6721866f391c0236fa5f6b6dfb933afcb78de0063dd72eb459952d49a6ce5610.
  Это входы прежнего прогона, не автоматически baseline новой ветки.

## Первый блокер

`scripts/run_owned_jawl_console.py` устанавливает delivery/context hooks
в console process. Native `src/web/agent.py` запускает `src/main.py` отдельным
Popen process; supervised path также требует отдельной проверки.
Process-local monkeypatch не переносится в новый Python process.
Установка hooks в actual brain НЕ доказана. Console probe это не проверяет.
Улучшение отдельных R6 ходов нельзя приписывать этим hooks.
D1-01: owned brain entry + proof child identity/install, оба режима запуска.

## Существующая основа

Есть native JAWL, реальные voice turns, streamed audio/Stop/stale fences,
ASR partials, owned worker lifecycle, VRM/панель, sensory adapters.
Открыты стабильность ответа/latency, физический mic/echo, всегда видимый
персонаж с bubble UX, полезный постоянный sensory context/инициатива,
полный action/memory сценарий и8h эксплуатация. ASR не понимает музыку.

## Текущий выбранный профиль

Hikari Bonsai-2 27B PQ2_0 GPU1; GigaAM v3/crispasr CPU;
OmniVoice9890 default, Tera9889 selectable. VRM active asset сохраняется.
Vision8986 opt-in; наличие конфигурации не current RU screen acceptance.
Effective значения брать из manifest/local override. Соседние порты не вытеснять.

## Подготовка новой ветки

Старые планы/checkpoints/датированные отчёты сохранены byte-for-byte:
[архив](history/2026-10-14-daily-reset/INDEX.md). Контракты, runtime prompts,
модели, данные и текущий исполняемый код не менялись при подготовке.
Старый tool goal при проверке имеет status=paused и незавершённую широкую цель.
Новый objective подготовлен в DAILY_PLAN. Попытка create_goal после подготовки
отклонена: `cannot create a new goal because this thread has an unfinished goal;
complete the existing goal first`. Новый tool goal НЕ создан. Прежняя широкая
цель не выполнена; фиктивно отмечать complete нельзя. Доступный API не имеет
cancel/replace/resume. Нужен сброс/замена прежней цели средствами продукта;
после этого зарегистрировать objective из DAILY_PLAN. D0-04 остаётся открытым.

Проверка подготовки: SHA256 всех29 архивных файлов совпали после переноса;
62 активных документа прочитаны как UTF-8,268 локальных ссылок ведут на
существующие пути; git diff --check exit0 (обычные предупреждения CRLF).
Архивировано27 документов и2 standalone Needle3 probe. На прежних путях
15 исторических документов оставлены короткие ссылки. Текущие launchers/tests
сохранены. Проверка не включает исторические anchors и runtime acceptance.
