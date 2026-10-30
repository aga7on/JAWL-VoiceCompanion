# SPEECH-FIRST механизм — формальная спецификация (2026-10-30)

> Статус: действующий механизм, зафиксирован документально по запросу
> «TTS уже отвечает на подходе генерации ответа — нужно оформить лучше».
> Историческая база исследований: [DUPLEX_RESEARCH_ADOPTION.md](DUPLEX_RESEARCH_ADOPTION.md)
> (TinyDuplex, 2026-09). Внешний ориентир архитектуры: sbintuitions/DuplexCascade
> (микро-туры, VAD-free control tokens) — см. вердикт в
> [MERGE_PLAN_20261030.md](MERGE_PLAN_20261030.md) и ADR-051.

## 1. Принцип

Речь отвечает **на подходе генерации**, а не после неё: первый законченный
предложение ответа синтезируется и уходит в эфир, пока мозг ещё дописывает
остальной ход. Окончательный конверт (receipt/envelope) приходит ПОСЛЕ речи —
гарантии admission/receipt/delivery при этом не ослабляются: ранняя речь —
presentation-слой, конверт — источник истины.

## 2. Конвейер (от микрофона до эфира)

```
микрофон → voice_capture (lease + gate_open/gate_close/silence_ms/pre_roll)
         → UtteranceBuffer (PCM16, до 4 MiB/сессия) ── финал: GigaAM (crispasr file-mode)
         → streaming_asr (частичные гипотезы ~0.5–0.8 c, rolling window)
каждый чанк:
  /api/voice/draft → turn_policy.decide(partial, silence_ms, assistant_speaking)
       → hold/listen/end + duplex_token (см. §4)
  /api/voice/preface → voice_preface: короткая ПРОВИЗОРНАЯ фраза без LLM
       («Сейчас посмотрю…»), только на явные вопросы про экран
ответ мозга (JAWL gateway.stream_text):
  speech_delta ──► SpeechFirstGate (ядро, src.l3_agent.llm.speech_first)
       └─ first_speakable_chunk / extract_speech_text — первое «озвучиваемое»
          предложение отделяется от служебных действий (tool call и т.п.)
       └─► LiveSpeechSession.feed(delta) — режет на предложения, кладёт в очередь
            TTS-синтеза; WAV уходит через on_audio СРАЗУ по готовности
            (аудио обгоняет текстовый поток)
  финальный envelope (receipt) ──► admission guard → delivery
```

## 3. Ключевые свойства

| Свойство | Где реализовано | Механика |
|---|---|---|
| Ранняя речь (speech-first) | `SpeechFirstGate` (ядро, ADR-049 slice-3/9) | первый speakable-chunk синтезируется до закрытия конверта |
| Инкрементальный TTS | `live_speech.LiveSpeechSession` | покадровая нарезка на предложения; WAV уходит мгновенно (`on_audio`), очередь ограничена, cancel/replay через `speech_requests` |
| Провизорная речь без LLM | `web.voice_preface` | короткая уточняющая фраза во время «размышлений»; stale-частички отбрасываются |
| Семантический конец хода | `turn_policy` (RU continuation cues, hesitate tails) | тишина ≠ конец: 800 мс → 2000 мс на синтаксически открытом хвосте |
| Микро-туры | `duplex_cascade.DuplexCascadeArbiter` | 6 control-токенов (см. §4), детерминированные правила |
| Barge-in | capture cancel + `SpeechRequests` | DUCK (~120 мс fade) до STOP; cancel-before-start tombstones; повторная отправка финала идемпотентна (replay-cache, ADR-051) |
| Адаптивный опрос черновика | `/api/voice/draft` | ~800 мс активный стриминг / 2500 мс фолбэк; hold/silence_ms/required_ms в ответе |

## 4. Control-токены микро-туров (duplex_cascade.py)

Соответствие taxonomy из DuplexCascade (sbintuitions): наша реализация —
**детерминированный эвристический арбитр**, честно задокументированный как
не обученный контроллер (см. докстринг модуля). Правила решают локально,
без обращения к LLM и без новых моделей (канон ADR-048).

| Токен | Условие | Действие |
|---|---|---|
| `<|no voice|>` | тишина, незавершённой речи нет | ждать |
| `<|user is talking|>` | активная многословная речь | держать ход |
| `<|user is thinking|>` | пауза на союзе/предлоге/филлере («э-э», «чтобы», «который…») | продлить тишину до 2000 мс |
| `<|user backchannel|>` | во время речи ассистента — короткое «угу/ага/понятно» | НЕ прерывать (avatar nod) |
| `<|user interruption|>` | «стой/стоп/хватит» или содержательная реплика поверх речи | немедленный cancel TTS (duck→stop) |
| `<|user finish talking|>` | реплика семантически завершена (терминальная пунктуация, закрытый хвост) | коммит хода при ~300–800 мс тишины |

`turn_policy.decide` возвращает `duplex_token` + `duplex_action`
(`continue | hold_turn | commit_turn | cancel_tts | ignore_backchannel`)
и `avatar_gesture` (backchannel → кивок).

## 5. Идемпотентность отправки сообщений (ASR → мозг)

Финализация уттеранса (`/api/voice/end`, WS `voice_final`) — единственная
точка, где распознанный текст превращается в сообщение мозгу
(`gateway.handle_text` с `correlation_id`). Правила:

1. **Один dispatch на correlation_id**: транспортный повтор с тем же
   `correlation_id` отдаёт закэшированный результат (`replay: true`) и не
   вызывает мозг второй раз (`web._TurnReplayCache`, 32 записи / 120 с).
2. **Шум не отправляется**: `transcript_quality.is_meaningful_transcript`
   отбрасывает артефакты GigaAM (пустое, односимвольное, CJK/Hangul,
   механические повторы филлеров «ага ага ага»).
3. **Backchannel не отправляется**: `suppress_backchannel` + канонический
   ack («Угу, понятно.») гасится без dispatch и без записи в память.
4. **Ошибки и отмены не кэшируются**: ретрай после сбоя ASR или cancel
   может завершиться нормально.
5. **Один владелец частичек**: стриминговый черновик принадлежит только
   `StreamingASRBridge`; после канонического финала `reset_utterance`
   очищает scope, чужие scope'ы не трогаются.

## 6. Границы и честные ограничения

- Арбитр микро-туров — правила, не обученная модель. Замена на обученный
  endpoint/barge-in классификатор (как SmartTurn в pipecat) возможна **за тем
  же интерфейсом** `MicroTurnDecision` (зарезервировано в turn_policy), но
  требует нового артефакта модели → ADR-048 сейчас это запрещает.
- DuplexCascade генерирует control-токены самим LLM (обученный full-duplex
  контроллер). Мы намеренно НЕ дублируем это: текстовый мозг остаётся
  единственным когнитивным рантаймом, токены — транспортная политика.
- «TTS отвечает на подходе» относится к речи хода; проактивные/расписанные
  реплики идут через отдельный daily/scheduled контур с теми же гарантиями.
