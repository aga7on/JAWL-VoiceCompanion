# CPU VLM benchmark — 2026-10-22

## Что проверяли

Тот же набор из 13 кейсов, что у Gemma 4 E4B: 2 реальных экрана, 6 аудио-кейсов и
5 combined. VLM не принимает аудио, поэтому аудио-кейсы отправлены **без
изображения** как negative control: честная модель должна вернуть `scene=unknown`,
а не выдумывать сцену. В combined-кейсах отправлен только кадр.

Единый контракт: JSON schema с `scene`, `changes`, `audio`, `uncertainty`;
английский системный промпт; `temperature=0`; 6 CPU-потоков; `-ngl 0
--no-mmproj-offload`; 160 и 512 токенов; одинаковые
`runtime/live-sensory-run/display1.jpg` и `display2.jpg`.

Инструменты: `scripts/vlm_cpu_bench.py`, конфиг `config/vlm-cpu-bench.json`.
Сырые результаты: `runtime/vlm-cpu-bench/out/*.full.json`.

## Результаты

| Модель | 160: JSON / image | 512: JSON / image | total p50, 160 | total p50, 512 | RSS | Вывод |
|---|---:|---:|---:|---:|---:|---|
| LFM2.5-VL-450M Q4_K_M | **13/13**, 7/7 | 13/13, 7/7 | **1.04 s** | **1.02 s** | **0.61 GB** | быстрый coarse-описатель |
| LFM2.5-VL-1.6B Q4_K_M | **13/13**, 7/7 | 13/13, 7/7 | 2.68 s | 2.55 s | 1.93 GB | лучше видео, слабее UI |
| Qwen3.5-0.8B Q4_K_M | 6/13, **0/7** | **13/13**, 7/7 | 2.48 s* | 4.09 s | 1.33 GB | лучший UI/детали, нужен 512 |
| MiniCPM-V-4.7-1B Q4_K_M | 12/13, 6/7 | 13/13, 7/7 | 3.37 s | 3.72 s | 2.21 GB | без выигрыша над Qwen |
| Gemma 4 E4B Q2 (ранее) | 8/13 | — | 10.7 s | — | ~6 GB | отклонена |
| Gemma 4 E4B Q4 (ранее) | 0/13 | 13/13 | — | 18.9 s | — | отклонена |

\* Qwen 160: 6 валидных — это только no-image кейсы; все 7 image-кейсов обрезаны.
Поэтому для Qwen реальный минимум — 512 токенов.

Все модели: `no_image_honest=6/6`, HTTP/request errors 0 при валидном бюджете.
GPU-оффлоада нет; inference CPU-only.

## Качество по кадрам

- **LFM2.5-VL-450M**: `display1` → `"game"`, changes «two characters, trees,
  wooden floor»; `display2` → `"desktop"`, changes «game, video, website, app».
  Быстро и без галлюцинаций на статике, но слишком обобщённо; текст/UI не читает.
- **LFM2.5-VL-1.6B**: `display1` → `"video"`, YouTube, два персонажа, лес,
  русский текст, 4 превью; `display2` ошибочно описан как video/«text added to
  video description». Для видео лучше 450M, для UI — нет.
- **Qwen3.5-0.8B (512)**: `display1` — YouTube thumbnail, персонажи, парк,
  дерево, русский заголовок (кириллица в ответе повреждена); `display2` —
  окно opencode, «Standard mode», «4 background jobs», лог, New Session.
  Самый точный UI-ответ, но ~4.1 s и текст надо брать из OCR, не из модели.
- **MiniCPM-V-4.7-1B (512)**: `display1` — YouTube, персонажи, парк, сайдбар
  превью; `display2` — software interface, New Session, Settings, Textures,
  но также выдуманное «Organize maximum number of games». Детальнее LFM,
  но не точнее Qwen и дороже по RAM/времени.

## Live-проверка LFM2.5-VL-450M

Screen-only 15 минут, `max_tokens=512`, реальный foreground Chrome, 1 Hz capture,
`change_threshold=0`:

- **515 валидных кадров**, **1 ошибка JSON**, dropped/stale = 0.
- Фактический темп **0.57 кадра/с**; `age_ms` обычно **1.6–2.9 s**.
- JSON/schema стабильны, RSS после загрузки ~0.55 GB.
- Но качество на реальном экране слабое: почти всегда `"Desktop computer
  screen"`, изменения повторяются, модель выдумывает audio events
  (`pause/play`, `new session`) и иногда отвечает не по формату.

Вывод: LFM450 стабилен и достаточно быстр, но **не является качественным
описателем сцены/UI**. Это датчик присутствия и грубого изменения, не источник
деталей.

## Решение

Если нужен один **качественный** VLM-описатель, выбираю **Qwen3.5-0.8B на 512**:
13/13, ~4.1 s, 1.33 GB, лучший разбор UI и самый информативный `scene`.
Его ограничения: обязательные 512 токенов (на 160 все 7 image-кейсов падают),
кириллица в ответе повреждена — текст брать из OCR.

Если жёстко ограничена латентность, **LFM2.5-VL-450M** остаётся быстрым
coarse-слоем: 13/13 на 160, ~1.0 s, 0.61 GB, live 0.57 fps. Но его нельзя
ставить единственным источником деталей: он обобщает и выдумывает события.

Практичная схема:

1. **LFM2.5-VL-450M** — быстрый presence/change слой; только для «что-то
   происходит / тип контента», с обязательным uncertainty и без доверия к audio.
2. **Qwen3.5-0.8B 512** — on-demand detail/UI; 4 s допустимы для явного вопроса,
   не для постоянного 1 Hz контура.
3. OCR/UIA/EG2 остаются отдельными источниками; ни одна из этих VLM не заменяет
   точное чтение текста.

LFM1.6B и MiniCPM не дают достаточного выигрыша, чтобы оправдать 2–4 s и
2 GB RSS. SmolVLM2 и Gemma E4B остаются отклонёнными.

## Не сделано

15-минутный live для Qwen/MiniCPM не запускался; для Qwen он будет медленнее
(~0.25 fps) и нужен только если Qwen выбран как постоянный слой. Текущий daily
companion остановлен, поэтому влияние на Hikari/EG2 ещё не измерено.

## Воспроизведение

```powershell
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_cpu_bench.py --model lfm2.5-vl-450m
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_cpu_bench.py --model lfm2.5-vl-1.6b
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_cpu_bench.py --model qwen3.5-0.8b
runtime\jawl-daily-venv\Scripts\python.exe scripts\vlm_cpu_bench.py --model minicpm-v-4.7-1b
```

??. ?????: [vlm-short-caption-20261022.md](vlm-short-caption-20261022.md) ? 32/64 ??????, full/crop, RAM-??? ???????? ? Florence-2 ONNX.

??. ?????: [vlm-content-vision-20261022.md](vlm-content-vision-20261022.md) ? ????????????, Florence vs Qwen, ???? ??????.
