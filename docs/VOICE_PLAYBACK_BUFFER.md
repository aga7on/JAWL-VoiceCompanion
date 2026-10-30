# Голосовой playback buffer

Текущий продуктовый статус и карта: [docs/README.md](README.md),
[STATE](STATE.md), [очередь](../TODO.md). Этот контракт описывает streaming TTS
playback после финального ответа JAWL и не означает live-device/provider
acceptance.

## Решение

Актуально 2026-10-05 для Electron `/app`. JSON-envelope JAWL остаётся
транспортом решения. После final UI запрашивает `/api/tts/stream`: сервер
возвращает NDJSON audio/done/error/cancelled, audio содержит ordered WAV chunks.
`speech-stream.js` декодирует и планирует их через один native WebAudio owner;
не читает NDJSON как Blob и не создаёт отдельный HTML Audio на каждую фразу.
Прогрессивное проигрывание начинается до done. WAV делится на slices ≤0.4 с,
реальный scheduled horizon ограничен ≤0.8 с; длинный chunk не обходит лимит.
Corrupt/out-of-order/late events и deadline ведут к cleanup, не скрытой тишине.

Защита транспорта: cumulative wire budget 64 MiB на ответ до decode/split,
line limit включая whitespace-only строки, 32 MiB decoded audio payload и
300 с суммарной audio duration. Учитываются и служебные/пустые данные;
при превышении — reader cancellation и остановка scheduled sources.
Это не общий peak RAM cap: входящий reader chunk уже выделен браузером.
Focused regression suite — 21 тест, итоговый full gate — в STATE.

## Перебивание

Capture работает параллельно playback. При qualified onset после RMS gate
`cancelSpeechPlayback()` отменяет fetch/reader и останавливает все scheduled
`AudioBufferSourceNode`; старая generation не может проиграть поздние chunks.
Gate имеет hysteresis, bounded pre-roll и минимальный onset. Это не ASR/VAD
нейросеть и не доказательство устранения акустического echo. Пользователь
может нажать Stop независимо от capture. Durable JAWL task этим не отменяется.

Это потоковое воспроизведение TTS после полного JSON-ответа, не token-level
streaming LLM. Бюджет scheduled tail не равен измеренной задержке barge-in.
Actual synthetic `/app` capture→mock ASR/JAWL→tone NDJSON→WebAudio проверяет
plumbing/cancel/stale; real RU ASR/JAWL/TTS, медленные фразы, echo и физическое
устройство принимаются отдельно. Production обязана измерить p50/p95 first-audio
и interruption, cold/warm режимы и отсутствие ложных обрывов.

Контракт gate/lease/config — [CONFIG_CONTRACTS](ui-registry/CONFIG_CONTRACTS.md).
Evidence и оставшиеся строки — [STATE](STATE.md), [delivery goal](PRODUCTION_DELIVERY_GOAL.md).
