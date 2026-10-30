# Передача работы — 21 октября 2026

> Актуальный статус продолжения на 24 октября: используйте [docs/STATE.md](docs/STATE.md)
> и [runtime/active-goal-addendum-20261024.md](runtime/active-goal-addendum-20261024.md).
> Этот handoff сохраняет историческую очередь на 21 октября; пункты ниже могли
> быть закрыты или изменены последующими проверками.

Ветка `dev/daily-companion-20261014`, dirty worktree владельца сохранён.
Очередь — [TODO](TODO.md), факты — [STATE](docs/STATE.md), вход — [AGENTS](AGENTS.md).
Pinned snapshot `runtime/jawl-sources/jawl-20260906-daily-v2` не менять.

## Где находимся

- **H4-Grounding live PASS**: UIA-клик, OCR-canvas клик и Stop без двойного
  эффекта проверены `scripts/live_grounding_acceptance.py`. OCR работает через
  Windows.Media.Ocr без tesseract (`windows_ocr.py`).
- **D5-01 live PASS**: `--suite agent-work` 7/7 — file write/read с точным
  SHA, browser navigate+extract и form save, memory revision/restart/recall,
  sandbox denial. Startup `SYSTEM_CORE_START` ограничен schema-bound, иначе
  2048-token completion обрывал JSON до готовности.
- **TTS per-request cancel** реализован и покрыт focused tests; живая проверка
  Stop во время реального OmniVoice-синтеза отложена по решению владельца.
- **voice_end → ASR** измерен: warm p50 0.307с, p95 0.408с; GigaAM/crispasr.
- Гейт на 21Oct: 1175 passed + 281 subtests, JS 102 passed.

## Открытые хвосты

- D5-02: memory revision/restart/recall уже PASS в live agent-work; остаются
  задачи через Stop речи и controlled provider fault без дубля эффекта.
- D6-02: `native_goal_completion_repair.py` реализован и покрыт unit/probe;
  новый 8-часовой soak после repair ещё не прогонялся. Короткий прогон не
  выдавать за 8h acceptance.
- D2/D1: физический микрофон Fifine, 20 голосовых ходов, provider error/recovery
  и barge-in через колонки остаются интерактивными.
- TTS first chunk ~1.19с — главный оставшийся latency floor; оптимизация позже.

## Запуск и проверка

Запуск стека — по `docs/DAILY_RUNBOOK.md` и `scripts/run_local_bonsai_integrated.ps1`.
Перед live-прогоном заново проверить ports/ownership; cleanup receipt не
описывает процессы, запущенные позже. Тесты: `python -X utf8 -m pytest tests/ -q`
и desktop node tests. Не коммитить и не делать reset без явной просьбы владельца.
