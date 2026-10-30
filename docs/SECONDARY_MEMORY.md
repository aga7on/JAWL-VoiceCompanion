# Ситуационная (ambient) память

Обзор обновлён 2026-10-10 (read-only; latest saved runtime evidence 2026-10-05).
Требование — помнить полезный окружающий контекст, не
мешая разговору и не занимая VRAM без необходимости. Это часть одного
компаньона, не второй агент. Это target design, если явно не указано
IMPLEMENTED. См. [README.md](README.md), [PRODUCT.md](PRODUCT.md),
[STATE.md](STATE.md) и актуальную очередь [TODO.md](../TODO.md).

## Слои и владелец

Важно не смешивать два разных значения слова «эпизод». `ambient episode` ниже —
это временный сжатый кандидат из фоновых наблюдений (обычно с TTL), а не
канонический эпизодический журнал JAWL. Канонический JAWL сохраняет отдельно
задачи, рабочие заметки, факты/предпочтения/черты/сводки, mental states, drives,
hypotheses, ticks/timelines и daily journal. Эти сущности не должны сводиться к
одному полю `episode` в UI.

```text
T0: ограниченный raw audio/frame в RAM → ASR/description → удалить raw
T1: наблюдение (текст, время, источник, уверенность) → короткий TTL
T2: сжатый эпизод → полезное удержать, шум забыть, ограничить объём/срок
T3: JAWL память → provenance/validity/corrections/retrieval
```

VoiceMem также не является заменой JAWL memory owner. Его left brain даёт
фактический semantic/graph recall, а right brain — `heartnote`,
`response_experience`, interaction profile и evidence для эмоциональных
ситуаций. Audio-память VoiceMem может хранить VAD/attribution, speaker identity,
scene/place/routine/music и abnormal-sound observations. Это perceptual context
и кандидаты; окончательная durable запись, task, journal и forget/revise остаются
у JAWL.

Около 30 минут для деталей и недели для эпизода — предложенные владельцем
ориентиры, а не жёсткий «биологический» алгоритм. Настраивать TTL, count/bytes,
приоритет и правила консолидации по полезности и нагрузке.

Текущие T1/T2/consent preferences — process-local и не переживают restart.
Ручной `POST /api/ambient-memory/promote` передаёт confirmed candidate в JAWL
structured memory с source/validity/standard tier; это IMPLEMENTED. Durable
automatic consolidation — OPEN, не постоянный запрет и не уже реализованная
функция.

Целевой обычный профиль: после первичной настройки источников/разрешений
восприятие включено, наблюдения регистрируются по мере поступления, JAWL консолидирует
подходящие эпизоды автоматически по выбранной политике; manual review
остаётся опцией. Хранение эпизода не означает изменение личности или
признание услышанного фактом о владельце. Слова из видео не равны словам
пользователя. Пользователь может просматривать, исправлять, исключать
источники, задавать сроки и отключать продвижение.

## Раздельные потоки

```text
Микрофон → ASR → один пользовательский turn JAWL + async VoiceMem enrichment
Звук ПК → segmenter → ASR + [будущий sound/music captioner] → triage
Экран → change/keyframe/UIA + [configured Bonsai 8986; acceptance open] → triage
triage → attributed episodes → JAWL consolidation/recall
```

Фоновое аудио имеет отдельные session/correlation IDs. Оно никогда не
превращается в USER_FINAL и напрямую не запускает речь/инструменты.
Наблюдение может повлиять на последующий ответ/уместный SPEAK_INTENT только
через JAWL, Attention/DND и общую политику, не как скрытая команда сенсора.

ASR распознаёт речь. GigaAM v3 — единственный ASR; он не является captioner и
не измеряет тембр/настроение. Музыка, шум окружения и affect требуют отдельных
capabilities и приёмки. `AudioDescriptionService` — adapter seam, принятого
captioning model нет. Affect — оценка с
неопределённостью, не диагноз, идентичность или устойчивый trait.

## Текущие ограничения

- Ambient GigaAM final-ASR path копит bounded PCM; текущий manual flush
  выполняется при Stop. Это не заменяет регулярную ротацию сегментов.
  Для повседневной фоновой памяти нужен segmenter с регулярной ротацией,
  backpressure и recovery; бесконечный один session buffer непригоден.
- Self-TTS suppression основано на времени playback. Это может убрать
  одновременно звучащую чужую речь; нужны тесты overlap/эхо и учёт потерь.
- Default-output WASAPI смешивает приложения. Без достоверной per-app
  attribution нельзя обещать privacy-фильтр по foreground window. На время
  приватного звука — пауза либо выбранный/раздельный output; source-aware
  capture остаётся задачей.
- `memory_sync=queued` подтверждает только enqueue, не завершённое сохранение/
  recall. Важные user commitments принадлежат durable JAWL tasks, не только
  droppable VoiceMem очереди.
- UI `disable` останавливает новый capture; `disable_and_erase` очищает
  transient buffer после подтверждения. Продвинутые JAWL записи отдельно.
  Native append-only forget/archive — логическое забывание, не стирание
  старого содержимого/индексов/backup.
- Объём контекста/RAM должен оставаться ограниченным при долгом audio +
  разговоре + игре. Одиночный RTF не доказывает совместную производительность.

## Delayed triage и JSON

Целевой CPU/RAM worker получает ограниченный текст с источниками, без raw media,
секретов, tools или полномочий. Bonsai-1.7B — испытанный кандидат для этого
слоя; Prism-ML/Ternary-Bonsai-8B из ранней идеи не обязательные зависимости.
Резидентность и unload — выбор профиля, не скрытый расход ресурсов.

Результат: `importance=ignore|retain|promote_candidate`, краткое summary,
topics, confidence, source_event_ids, observed interval, retention.
Схема валидируется, выдуманные provenance/инструкции отвергаются.
Противоречивое остаётся неопределённым свидетельством до уточнения.
Модельная JSON-оценка не выдаёт ей право менять canonical facts.

## OPEN: targets для проверки результата

1. Synthetic speech/music/тишина/наложения → правильные раздельные events.
2. Несколько последовательных сегментов без ручного Stop и без переполнения RAM.
3. Delayed triage не задерживает пользовательский ответ; потери видны.
4. Ни один ambient event не стал командой/чужой персоной; private sources
   действительно исключены или capture честно приостановлен.
5. Полезный эпизод найден по вопросу позже, с корректным источником.
6. TTL/консолидация/revise/forget/restart работают в одном JAWL memory owner.
7. Обычный auto mode после настройки источников сохраняет полезное без ручного подтверждения;
   его правила прозрачны и отменяемы пользователем.

Протокол измерения — [AMBIENT_TRIAGE_BENCHMARK.md](AMBIENT_TRIAGE_BENCHMARK.md);
модельные исторические прогоны — [MODEL-TESTS.md](MODEL-TESTS.md).
