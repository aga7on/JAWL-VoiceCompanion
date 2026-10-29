# Content-vision benchmark: Florence-2 vs Qwen3.5-0.8B — 2026-10-22

## Материал и протокол

- Локальный разрешённый фрагмент: `world.mp4` (вращение Земли) + `a.mp4`
  (тёмная карточка с жёлтым значком), склеены в
  `runtime/vlm-cpu-bench/video/content-actions.mp4`, 12 с, 1 fps.
- Подаётся **область самого видео** 480x270, без интерфейса и без letterbox.
- Кадры: 1–5 Земля; 6–7 тёмная карточка с жёлтым значком; 8–12 Земля.
- Предварительный список объектов/событий:
  `runtime/vlm-cpu-bench/video/manifest.json`.
  Ожидались: Земля/планета, облака, континенты/океаны, огни городов, космос,
  линия терминатора; значок; события: вращение, движение облаков, смена сцены,
  появление значка.
- **Qwen**: одно предложение обычным текстом, без JSON, OCR и лишних полей;
  бюджет 64, при обрезании — 128; упаковка в observation делает код.
- **Florence-2-base-ft ONNX q8**: обычный `<CAPTION>`, бюджет 64.
- Пара последовательных кадров: Qwen — два `image_url` в одном запросе;
  Florence — два изображения в процессоре + side-by-side composite.
- Кэш выключен: `--cache-ram 0 --no-cache-prompt --no-cache-idle-slots`.

## Задержки

| Режим | p50 TTFT/prefill | p50 generation | p50 total | RSS |
|---|---:|---:|---:|---:|
| Qwen, одиночный кадр | 352 ms | 315 ms | **664 ms** | 1039→1110 MB |
| Qwen, пара кадров | 615 ms | 621 ms | **1231 ms** | 1110 MB |
| Florence, одиночный кадр | vision 611 ms | 109 ms | **724 ms** | 471→1704→1483 MB |
| Florence, composite-пара | vision 606 ms | 123 ms | **725 ms** | — |
| Florence, detail-пара | vision 616 ms | 382 ms | **996 ms** | — |

Пара у Qwen стоит примерно **1.85× одиночного кадра** (в основном растёт
prefill и generation), поэтому её имеет смысл применять только для событий
«что изменилось», а не постоянно.

## Качество на видеоконтенте

Счёт по заранее объявленным категориям (`scripts/score_content_vision.py`):

| Модель | Одиночные объекты | Fabrications (одиночные) | Парные действия | Fabrications (пары) |
|---|---:|---:|---:|---:|
| Qwen3.5-0.8B | **41/62 (66%)** | **0** | 3/4 | 2 |
| Florence-2-base-ft | 6/62 (10%) | 6 | 0/4 | 2 |

Qwen уверенно называет: «planet Earth», «oceans», «continents», «city lights»,
«black void/space»; значок на кадрах 6–7 описан как «golden bracket symbol» и
«yellow vertical rectangle with white dot» — это корректно. Пропуски: облака
(0/10), линия терминатора (0/10), иногда «land». Парные события: переход
7→8 (карточка → Земля) и смещение континентов 9→10 распознаны; переход
5→6 пропущен, 6→7 описан как значок без события; fabrications —
«starry space» и «stylized representation of a person».

Florence на этом материале остаётся обобщённой и часто ошибается: Земля
названа «moon», «blue object», «blue and white ball»; значок — «parachute»,
«light fixture»; пары — «two blue circles», «dark room with two lights».
Объектов 6/62, fabrications 6, действий 0/4. Двухкадровый режим технически
принимается, но содержательного выигрыша не даёт.

## Решение

1. **Florence-2-base-ft исключается из постоянного контура.** На реальном
   видеоконтенте она обобщённая и выдумывает объекты; её короткие caption
   не годятся для событий.
2. **Qwen3.5-0.8B содержателен** для объектов и части действий. Его нужно
   использовать **асинхронно по событиям**, а не постоянно:
   - триггер — scene change / значимое изменение кадра (pHash, EG2, attention),
     а не каждый кадр;
   - одиночный кадр стоит ~0.66 s, пара — ~1.23 s; пару применять только для
     «что изменилось»;
   - каждый observation несёт `observed_at`, `processed_at`, `age_ms`, `stale`;
     при `age_ms` больше порога (например, 6 s) наблюдение помечается stale и не
     подаётся как «сейчас»;
   - бюджет 64, fallback 128 только при обрезании; JSON/OCR/audio не
     запрашиваются, упаковку делает код.
3. Для этого добавлен модуль
   `src/jawl_voicecompanion/qwen_event_describer.py` с фоновым воркером,
   очередью «один последний pending», честным возрастом и fallback 64→128.
   Тесты: `tests/test_qwen_event_describer.py` — 3/3 passed.
   Живая проводка в daily companion не делалась: приложение сейчас остановлено.

## Ограничения

- Qwen пропускает облака и терминатор, а в парах даёт 2 fabrications; события
  смены сцены распознаёт не всегда.
- Florence не поддерживает временную пару содержательно; composite не заменяет
  temporal reasoning.
- OmniVoice не изменялся.

## Воспроизведение

```powershell
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_content_bench.py
cd runtime\florence-node
node content-bench.mjs "models/florence2-base-ft" "..\vlm-cpu-bench\video" "..\vlm-cpu-bench\content\florence2-base-ft.json"
runtime\jawl-daily-venv\Scripts\python.exe scripts\score_content_vision.py
```

Сырые данные: `runtime/vlm-cpu-bench/content/qwen3.5-0.8b.json`,
`florence2-base-ft.json`; манифест:
`runtime/vlm-cpu-bench/video/manifest.json`.

??. ?????: [qwen-visual-integration-20261022.md](qwen-visual-integration-20261022.md) ? ??????????? Qwen ????? composition.
