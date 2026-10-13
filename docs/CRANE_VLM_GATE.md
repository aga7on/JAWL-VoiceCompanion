# Crane Benchmark / VLM Gate — план по фазам

> Датированный исследовательский план и evidence 2026-09-07/08, не текущая
> очередь и не активный provider. Crane/Qwen3-TTS здесь не default Companion.
> Текущий стек/факты: [STATE](STATE.md); задачи: [TODO](../TODO.md);
> навигация: [README](README.md). В docs-only срезе 2026-10-10 нормализована
> смешанная UTF-8/CP1251 кодировка; исходные байты сохранены в архиве.

Статус: активный, 2026-09-07. Хост: Windows, CPU-only (Ryzen 9 9900X3D, 94 GB RAM).

## Цель (goal)
Заменить слабый 500M-VLM-контур (smol/moondream/namo — CONDITIONAL, без надёжного RU OCR)
на CPU-движок Crane (Rust/Candle) и довести RU-перцепцию до работоспособного гейта:
VLM-описание + точное кириллическое OCR + RU TTS, всё через OpenAI-совместимый
`crane-serve` (тот же контракт, что у наших sidecar-воркеров).

## Модели-кандидаты (репозитории/размеры, download через slice-метод без прокси)
| Модель | Репо | Вес | Фаза | Роль |
|---|---|---|---|---|
| Qwen3.5-2B | Qwen/Qwen3.5-2B | 4548221488 (1 shard) | 2 | VLM-эталон (arch Qwen3_5) |
| Qwen3.5-4B | Qwen/Qwen3.5-4B | 5329398688 + 3990429408 (2 shards) | 3 | VLM побольше |
| PaddleOCR-VL-1.5 | PaddlePaddle/PaddleOCR-VL-1.5 | 1917255968 | 4 | RU text-extraction |
| Qwen3-TTS-12Hz-0.6B-Base | Qwen/Qwen3-TTS-12Hz-0.6B-Base | 1829344272 + speech_tokenizer 682293092 | 5 | RU TTS + вок-клон |
| Qwen3-TTS-12Hz-0.6B-CustomVoice | Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice | 1811626576 + speech_tokenizer 682293092 | 5 | Предзаданные голоса |

## Фикстуры (общие, как в runtime/vision-smoke/fixtures/)
- ru_form.png (900x500) — русская форма/дашборд с цифрами и временем.
- desktop_live.png (1280x360) — «живой» срез десктопа.
- RU_PROMPT: «Опиши, что сейчас на экране. Прочитай весь видимый русский текст точно
  и полностью, затем кратко перескажи смысл. Отвечай только по-русски.»

## Критерии приёмки фазы (числовые, повторяемые 2x)
- RU_SCREEN_OCR: >=5 проверяемых кириллических строк/сущностей в ответе на ru_form
  (даты «14.02», «06:00», «13.40», суммы «1240» и т.п. считаются проверяемыми).
- Емкость ответа: нет галлюцинаций-повторов, <=1 нерелевантного блока.
- Realtime-бюджет: первый ответ <= 2x реального времени кадра (поллинг ~10-15 c/кадр
  допустим для desktop_ambient; OCR-запрос — отдельно, гейт >= 5 строк).
- TTS: RU-фраза синтезируется, понятность субъективная + длительность >= текста.

## Вердикты фазы
- PASS / CONDITIONAL / REJECT → пишутся в docs/MULTIMODAL_MODEL_GATE.md (общий gate)
  и сводятся в runtime/vision-smoke/results.json (формат уже принят).

## Фазы (последовательность)
1. **Phase 0 — toolchain + repo**: rust/MSVC ✓ (есть), build crane-serve CPU, план.
2. **Phase 1 — build**: `cargo build -p crane-serve --release` (CPU, без onnx).
3. **Phase 2 — Qwen3-VL-2B**: download, запуск `/v1/chat/completions` + image base64 по
   двум фикстурам, замер latency+RAM, запись в results.json, вердикт.
4. **Phase 3 — Qwen3-VL-4B**: то же, сравнение с 2B.
5. **Phase 4 — PaddleOCR-VL-1.5**: RU text extraction на фикстурах (через crane ocr или
   python remote code), замер точности строк.
6. **Phase 5 — Qwen3-TTS**: `/v1/audio/speech` RU wav (Base + CustomVoice), сравнение с
   TeraTTS (9889), замер латентности.
7. **Phase 6 — VAD**: Silero VAD endpointing поверх whisper (порог качества хвостов).
8. **Phase 7 — свод**: results.json + gate-таблица + DOCS, решение по интеграции
   (замена VLM-слоя / TTS / добавление OCR).

## Артефакты
- Репо: G:\AI\JAWL-VoiceCompanion\runtime\crane-repo
- Веса: G:\AI\JAWL-VoiceCompanion\runtime\models\crane\...
- Скачиватель: C:\Users\ARTEM\AppData\Local\Temp\opencode\slice_download.ps1
- Логи: runtime\crane\logs\...

## Ход работ (2026-09-07)
- **P0/P1 ✓**: rust 1.95 + MSVC BuildTools; `crane-serve` собран `cargo build -p crane-serve --release` (CPU, 6м24с), бинарь в target/release.
- **Класс-выбор**: Qwen3-VL-2B (arch Qwen3VLForConditionalGeneration) crane-serve НЕ поддерживает —
  сервер поддерживает Qwen3.5 (arch Qwen3_5ForConditionalGeneration, `--model-type qwen3_5_vl`).
  Поэтому Phase 2 переведена на **Qwen3.5-2B** (4.55GB, 1 шард + index).
- **Phase 4 (PaddleOCR-VL-1.5)**: веса докачаны; crane-serve `--model-type paddleocr_vl --cpu`
  на 8081. Итог на фикстурах: **ru_form = PASS** (реальное кириллическое извлечение:
  «Сводка по продажам», «Прибыль 1 240 500», «Сегодня 14:02», «13:40», «06 сентября»;
  31s/кадр). desktop_live — провал: формульный мусор (повторные \text{...} формул) —
  модель распознала сырой код как химические формулы; вне OCR-сценария.
  Бенч записан в runtime/vision-smoke/results.json (ключ paddleocr-vl15).
## Результаты фаз (2026-09-07/08, все прогоны на CPU F32)
- **Phase 2 — Qwen3.5-2B VLM (PASS)**: сервер `--model-type qwen3_5_vl --cpu` 8082
  (веса rename > model.safetensors-00001-of-00001.safetensors перед запуском).
  ru_form: 83.8s, ИТОГ — все ключевые строки прочитаны точно и пересказаны по-русски
  (даты 14:02/13:40/06 сентября, «Прибыль 1 240 500 рублей», «УСТАНОВЛЁНО», «ОТКРЫТЬ ОТЧЁТ»).
  desktop_live: 151.2s, PARTIAL — реальные данные интерфейса (Telegram Desktop 1.2.100.1,
  список чатов), но повтор-петля на спам-тексте (x10). RAM ~10 GB.
- **Phase 4 — PaddleOCR-VL-1.5 (PASS на формах)**: ru_form 30.6s (стабильно x2) — чистое
  извлечение label:значение; desktop_live 78.7s — formula-халюцинация (вне OCR-сценария).
  => OCR-слой для форм годится; десктоп-анализ — только Qwen3.5-2B.
- **Phase 5 — Qwen3-TTS (WORKING, RTF?2.4)**: `/v1/audio/speech` wav 24kHz.
  CustomVoice — прямой TTS работает; Base — требует voice-clone reference audio (в Rust-пути
  не реализован). F32: 25.8s синтеза на 10.88s аудио (RTF 2.37). `--dtype f16` на CPU падает
  (NaN). Whisper-верификация 100% совпала с исходником. TeraTTS (9889) сравнить на клипе не
  успели — синтезы объективны по RTF: TeraTTS быстрее (см. профили), Qwen3-TTS качественнее.
- **Phase 6 — Silero VAD (PASS, quick)**: vision-venv silero-vad+torchaudio; на синтезированном
  RU-clip 10.88s получено 3 сегмента речи (0.50-5.60, 5.80-8.20, 8.40-10.30; 9.40s суммарно),
  endpointing корректный. Пороги: threshold=0.5, min_speech=180ms, min_silence=150ms.
- **Phase 7 (свод)**: consolidation в этом доке + MULTIMODAL_MODEL_GATE.md + results.json —
  решено: VLM-слой заменяем на crane-serve Qwen3.5-2B; OCR для форм = PaddleOCR-VL;
  TTS-голос помощника = Qwen3-TTS CustomVoice (порядок RTF приемлем при асинхронном
  произнесении), Base-вок-клон = бэклог (нужен Rust reference-audio код).
- qwen3-vl-2b/ каталог (частичные 30/37 блоков Qwen3-VL-2B) — не используется, удалить.
- Сервера: 8081 OCR, 8082 VLM, 8083 TTS-CV — работают; при интеграции поднять sidecar-ом.
