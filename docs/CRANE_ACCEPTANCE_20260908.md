# Crane acceptance — 2026-09-08

## Scope

Проверен локальный CPU-контур Crane на Ryzen 9 9900X3D / 24 потока:

- Qwen3.5-2B VLM: F32 и patched `q4k`;
- Qwen3-TTS CustomVoice 0.6B: WAV и streaming PCM;
- наличие Crane-реализаций ASR/VAD/CosyVoice3.

Тесты выполнялись с корректным UTF-8 русским промптом. Старый
`runtime/vision-smoke/crane_bench.py` не использовался как источник истины:
его русский промпт сохранён в mojibake.

## Qwen3.5-2B VLM

| Режим | RAM процесса | Первый содержательный chunk | Полный ответ | Качество RU form |
|---|---:|---:|---:|---|
| F32 | около 10 GB по предыдущему запуску | 29.2 s | 69.9 s | корректно прочитал ключевые строки |
| q4k | около 4.5 GB | 41.0 s | 65.3 s | корректно прочитал ключевые строки |

Q4K уменьшает footprint примерно вдвое, но не даёт realtime: даже простой
скриншот требует десятки секунд. По качеству RU OCR и краткому описанию
Qwen3.5-2B пригоден как качественный редкий vision-tool/secondary perception,
но не как постоянный CPU screen stream.

Патч q4k собирался в отдельном target-каталоге
`runtime/crane-target-q4k`, поскольку старый `target/release/crane-serve.exe`
был залочен. Патч не изменяет основной Companion и не принят в production
baseline до повторной проверки на GPU.

## Qwen3-TTS CustomVoice

На `crane-serve`, CPU/F32, русская фраза из 41 символа:

- обычный WAV: 2.48 s аудио за 6.07 s, RTF 2.45;
- PCM streaming: первый chunk через 1.07 s, но поток завершился через 81.23 s
  и содержал 27.6 s PCM для той же короткой фразы, RTF 2.94.

Это не соответствует ожидаемому streaming playback: первый chunk приходит
рано, но длительность/объём потока расходятся с обычным WAV-тестом. Поэтому
Crane Qwen3-TTS пока не принимается как playback backend. Текущий TeraTTS
остаётся быстрым production fallback, пока streaming queue не будет исправлена
и подтверждена round-trip транскрипцией.

## Остальные модели

- Crane содержит поддержку Qwen3-ASR, но соответствующие веса в текущем
  `runtime/models/crane` отсутствуют; рабочим ASR остаётся faster-whisper
  sidecar.
- Silero VAD не является частью Crane; ранее он прошёл отдельный CPU smoke.
- CosyVoice3 GGUF скачан, но Crane не имеет для него model type/backend. Его
  нельзя считать протестированным только по наличию файлов.
- PaddleOCR-VL даёт хороший RU OCR на форме, но не принят для постоянного
  desktop perception из-за формульных hallucinations вне OCR-сценария.

## Решение

Crane сейчас не внедряется как постоянный perception/TTS контур.

Разрешённый статус — opt-in экспериментальный sidecar:

1. Qwen3.5-2B q4k — редкий on-demand vision tool, когда качество важнее
   задержки;
2. TeraTTS — основной быстрый TTS;
3. faster-whisper — основной ASR;
4. Silero VAD — отдельный gate;
5. Crane Qwen3-TTS и CosyVoice3 — pending до исправления/проверки streaming
   и полноценного RU round-trip gate.

Для реального realtime screen perception нужен отдельный GPU1-бенчмарк:
проверить q4k/bf16 с ограничением VRAM, first-content latency, устойчивость
при повторных кадрах и связать результат с bounded attention buffer.
