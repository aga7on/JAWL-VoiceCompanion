# FULLDUPLEX_MAP — аудит контура (P0, инженерный снимок 2026-11-10 02:xx)

Статусы: OK (контракт+путь есть) / RISK (есть, неполно/хрупко) / BROKEN / UNKNOWN (требует проверки). Факты привязаны к `file:line`. Это карта, не PASS приёмки.

## Поток

| Узел | Факты (file:line) | Статус | Риск/заметка |
|---|---|---|---|
| Capture mic/loopback | `ambient_audio.py` (сегментация/подача, playback suppression), `system_audio.py`, `web.py:/api/voice/audio`→`_feed_voice_chunk` (pcm16_base64, sample_rate/channels, scope/session, cancel_event) `web.py:3283+`, streaming tap `3310` | RISK | Реальный mic/E2E — отдельная проверка; loopback+self-TTS под suppression. |
| VAD / endpoint / turn | `duplex_cascade.py:DuplexCascadeArbiter` (6 токенов, RU эвристики, `assistant_speaking`, опц. EG2 scorer не меняет решение `25-27`,`194-199`) `1-348`; `turn_policy.py:decide` (`looks_incomplete`, BASE/EXTENDED silence, при `assistant_speaking` + `cancel_tts/ignore_backchannel` → `action:listen` с токеном) `1-147` | RISK | Эвристика детерминирована, но качество на реальной речи/шуме — UNKNOWN; EG2 — диагностика. |
| ASR partial/final | `/api/voice/draft` использует `streaming_asr.snapshot`, подаёт `assistant_speaking/extended_used`, отдаёт `draft/hold/required_ms/duplex_token/duplex_action/avatar_gesture` `web.py:2297-2338`; финал через voice end flow (`voice_end` ws `3198-3200`, `_finish_voice_turn` ниже по файлу) | RISK | Partial/final ownership — CrispASR bridge; точность/latency под load — числа нужны. |
| Barge-in decision → execution | `duplex_cascade` даёт `cancel_tts` при перебивании во время речи ассистента `249-257`; `turn_policy` прокидывает действие; draft API возвращает `duplex_action` `2333`. **Desktop** потребляет `cancel_tts` (`desktop/app.js:1775`, `voice-input.js:50`), шлёт отмену. **WS lane** имеет `speak_cancel` → `session.cancel(); _live_speech=None` `web.py:3214-3239`. | RISK | Серверный draft-путь сам не останавливает TTS/playback — полагается на клиента. Сквозной инвариант «решение→фактическая остановка < N мс» не зафиксирован тестом/метрикой. |
| TTS synthesis | `tts.py`: `TTSCancelled`, `synthesize/cancel/cancel_generation` (28,32,145,209,230,236,322,334,423 — по grep); `live_speech.py` вызывает `tts.synthesize(..., request_id=...)`, ловит `TTSCancelled`, на ошибке **не рвёт очередь** (`315-322`, Cycle 20 fix), на пустом аудио — ошибка+break `326-329`; cancel best-effort через `tts.cancel(request_id)` `136-160` | OK/RISK | Устойчивость к единичной ошибке — OK (есть регрессия `test_live_speech_error_resilience.py`). Пустой аудио/slot/backpressure/реальный OmniVoice под баржином — RISK. |
| Streaming first-audio / playback | `LiveSpeechSession` (sentence gate, очереди 32/32, `on_audio` callback + audio queue, `drain_all`) `1-366`; `speech_first.py` shim → upstream kernel gate; WS `speak_delta/speak_finish` пушит `audio` base64 WAV чанки `3255-3281` | RISK | «Первый звук до конца ответа» зависит от клиента и upstream speech_first; метрика turn→first_audio в реальном контуре колеблется (STATE: E2E 3/3 но AC-03 скорость не достигнута в ранних раундах). |
| Echo / self-TTS guard | `ambient_audio.py`: `playback_suppression` marker, `self_tts_active` подавляет self-TTS (`180,229,239,248-258,271,334,378-386,669,1773-1774`), счётчик `suppressed_self_tts`. Фильтр артефактов loopback ASR упомянут в STATE/TODO (mixed-loopback accuracy OPEN). | RISK | Маркер есть; сквозная гарантия «TTS→loopback→ASR не создаёт ложный user turn во время/сразу после playback» в full-duplex сценарии — UNKNOWN/требует теста. |
| Brain fast/slow | Fast-lane/turn policy есть в кодовой базе (TODO/history); `web.py` stream_text enrich_turn_text. Полный ReAct prefill тяжёлый. | RISK | Не foreground fast lane уровня MOSS-Live; эскалация/latency — предмет P3. |
| Coordination / proactive | SQLTasks/Goal, `enrich_turn_text` время (Cycle 19), proactive guidance включена по TODO; комментарии экрана с turn-policy — TODO open. | RISK | Вставка фона «в естественной паузе» и anti-spam policy — P3/P4. |

## Главные разрывы для MOSS-Live-like full-duplex (P1 приоритеты кандидаты)
1. **Barge-in end-to-end инвариант:** `duplex_action=cancel_tts` должен детерминированно приводить к остановке playback+TTS+очереди+speech state и готовности принять следующий user turn. Сейчас решение распределено (server draft → client → `speak_cancel`/локальный stop) — нужен явный контракт + тест (sim/mock transport).
2. **Self-TTS echo guard в turn path:** playback suppression в ambient, но связка с «assistant_speaking»/активным TTS запросом и ASR/turn-arbiter при barge-in — проверить на гонки.
3. **Cancel correctness под ошибками/slot:** Cycle 20 чинит «ошибка не убивает хвост», но barge-in+cancellation+следующий запрос+`SpeechRequests` TTL/active — инварианты под focused regression.
4. **Streaming first-audio метрика:** измеримый контракт (delta→first WAV bytes/mark) в симуляции.

## Следующий выполнимый инженерный шаг (если DSH не закроет P0)
- Уточнить, где на сервере обрабатывается barge-in во время активной `LiveSpeechSession` (кроме клиентского `speak_cancel`): поиск по `assistant_speaking` в ws voice flow / `_handle_live_speech` взаимодействию; при отсутствии — зафиксировать как gap и подготовить минимальный контрактный тест.
- Не трогать STATE/TODO/CHANGELOG, пока DSH в активной итерации (избежать гонки записи). После завершения итерации — сверить и дополнить.
