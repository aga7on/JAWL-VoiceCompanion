# Short-caption CPU VLM benchmark — 2026-10-22

## Протокол

- 8 уникальных последовательных кадров, снятых с реального экрана с частотой 1 Hz
  (`runtime/vlm-cpu-bench/sequence/screen-01..08.jpg`, 960x270).
- Для каждого кадра: **full** 960x270 против **crop** 480x270 (правая половина).
- Бюджеты вывода: **32 и 64 токена**.
- Схема ответа только `caption`, `events`, `uncertainty`; **без OCR и без
  аудиополей**. Промпт прямо запрещает транскрибировать текст.
- RAM/prompt-кэш выключен: `--cache-ram 0 --no-cache-prompt
  --no-cache-idle-slots`; у всех запросов `prompt_cached_tokens=0`.
- Повторные изображения — отдельная группа: один и тот же full-кадр 3 раза по
  64 токена.
- Отдельно измерены prefill/TTFT (обработка изображения + текстовый prefill) и
  generation (генерация). У Florence-2 отдельно измерен vision encoder.
- Florence-2-base-ft ONNX q8 запущен через Transformers.js 4.3.1,
  `onnx-community/Florence-2-base-ft`, task `<CAPTION>` /
  `<MORE_DETAILED_CAPTION>`.

## Результаты

| Модель | 32 токена | 64 токена | prefill/TTFT p50 | generation p50 | total p50 | RSS |
|---|---:|---:|---:|---:|---:|---:|
| LFM2.5-VL-450M | 0/16 JSON | **15/16 JSON** | 262 ms (crop 224 / full 389) | 263 ms | **532 ms** | 541→596 MB |
| Qwen3.5-0.8B | 0/16 JSON | 2/16 JSON | 707 ms (crop ~390 / full ~700) | 904 ms | 1611 ms | 1040→1157 MB |
| Florence-2-base-ft ONNX q8 | 16/16 caption | 16/16 caption | vision 625 ms | 126 ms | **742–749 ms** | 471→1447 MB |

Повторные кадры:

| Модель | Повторы | TTFT | prompt | generation | total | cached |
|---|---:|---:|---:|---:|---:|---:|
| LFM450 | 3/3 JSON | 388 ms | 354 ms | 299 ms | 757 ms | 0 |
| Qwen3.5-0.8B | 0/3 JSON | — | — | — | ~1.6 s | 0 |
| Florence-2 | 3/3 caption | vision 610 ms | — | 114 ms | 729 ms | — |

С отключённым RAM-кэшем повторы не ускоряются: LFM и Florence обрабатывают
изображение заново, Qwen так же. Память после загрузки стабильна; у Florence
разовый рост до ~1.45 GB (ONNX/Node), затем плато; у LFM 541→596 MB; у Qwen
1040→1157 MB.

## Качество: события, детали, пропуски, выдумки

- **LFM2.5-VL-450M, 64 токена.** JSON в 15/16 случаях, но содержание слабое:
  full-кадр → «Two screenshots of a computer screen showing code and text»
  (на самом деле один экран с двумя панелями); crop → «Dark web forum discussion
  about a mysterious event» с выдуманными `User 1234: 'What's happening?'`.
  Часть кадров: «Dark web page with a green 'P' and a white 'P'». Детали
  терминала/кода не распознаны, события почти всегда обобщённые или выдуманные.
- **Qwen3.5-0.8B, 32/64.** JSON обрезается: на 64 токенах валидны только 2/16;
  crop-ответ содержал правильные «Reactions, Options, Parameters», но не
  закрылся. На 32 токенах — 0/16. Для короткого контракта не подходит; ему
  нужен бюджет около 512.
- **Florence-2-base-ft ONNX, 32/64.** 16/16 caption, без выдуманных людей и
  форумов: full → «A computer screen with a green background and a blue screen»;
  crop → «A computer screen with a purple background and rows of words»;
  detail crop → «...purple background, many windows, loading screen». Меньше
  fabrications, но и меньше деталей: точные события/код/терминал не называет,
  структурного `events` нет — только текст caption.

## Приёмка

- **Распознавание событий/деталей:** недостаточное у всех трёх на 32/64.
  LFM даёт структуру, но ненадёжен; Qwen не укладывается в бюджет; Florence
  даёт безопасный, но обобщённый caption без событий.
- **Пропуски:** у LFM и Florence высокие — не различают терминал/код/UI-панели.
- **Выдумки:** у LFM подтверждены (фейковые пользователи, «dark web forum»);
  у Florence не замечены; Qwen на валидном 512 был точнее, но в 32/64 не
  помещается.
- **Задержка:** Florence ~0.74 s, LFM ~0.53 s (когда JSON валиден), Qwen ~1.6 s.
  Full-кадр у LFM дороже crop примерно на 160 ms prefill; у Florence разница
  full/crop мала.
- **Память:** при выключенном RAM-кэше все три стабильны; роста, как в 15-мин
  live LFM с включённым кэшем, нет.
- **OmniVoice не изменялся.**

## Вывод

Короткие 32/64-токенные описания **недостаточны** для достоверных событий и
деталей. Если нужен безопасный короткий caption — лучший вариант
**Florence-2-base-ft ONNX** (~0.74 s, 16/16, мало выдумок), но он не даёт JSON
и `events`. Если нужен JSON — только LFM, и его нельзя использовать для фактов
без OCR/верификации. Qwen для 32/64 не подходит. Точные детали и текст должны
оставаться за OCR/UIA/EG2; VLM — только грубый визуальный caption.

## Воспроизведение

```powershell
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_short_bench.py --model lfm2.5-vl-450m
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_short_bench.py --model qwen3.5-0.8b
cd runtime\florence-node
node bench.mjs "models/florence2-base-ft" "..\vlm-cpu-bench\sequence" "..\vlm-cpu-bench\short\florence2-base-ft.json"
```

Сырые данные: `runtime/vlm-cpu-bench/short/lfm2.5-vl-450m.json`,
`qwen3.5-0.8b.json`, `florence2-base-ft.json`.

??. ?????: [vlm-content-vision-20261022.md](vlm-content-vision-20261022.md) ? ????????????, Florence vs Qwen, ???? ??????.
