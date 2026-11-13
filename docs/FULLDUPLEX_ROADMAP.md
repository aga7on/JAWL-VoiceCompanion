# Путь разработки: full-duplex аудио-слой с TTS (MOSS-Live-like) — JAWL

Дата: 2026-11-10. Цель владельца: качественный речевой full-duplex аудио-слой с TTS как у MOSS Live. Работает до 11:00 10.11.2026 (ПК) под контролем сторожа.

## Эталон (OpenMOSS/MOSS-Live, архитектура открытая; модель несвободна)
- Foreground: realtime voice lane — turn-taking, barge-in, backchannel, удержание хода, быстрые ответы, selective attention.
- Background: инструменты/долгие задачи (JAWL ReAct).
- Coordination: memory/context/task state + speech sink; результат фона в естественной паузе.
- Референсы (TODO): OpenMOSS/MOSS-Live; arxiv 2611.01639 (local/escalate duplex routing), 2610.35581 (interruptions/backchannels).

## Стек JAWL (факты)
ASR GigaAM v3/crispasr CPU; brain SenseNova-Loop/Bonsai GPU1; TTS OmniVoice default GPU1. Модули: `live_speech.py`, `speech_first.py`, `speech_requests.py`, `tts.py`, `ambient_audio.py`, `app_audio_router.py`, `audio_understanding.py`, `system_audio.py`, `qwen_omni_audio.py`, `duplex_cascade.py`, turn arbitration/perception fusion, `enrich_turn_text`. Cycle 20: исправлен break-на-ошибке TTS в `LiveSpeechSession._run` (нужен рестарт companion для живого процесса).

## Фазы (выполнять по одной итерации = один видимый результат + focused regression + числа)

### P0 — Аудит и контракты (начать здесь, если нет карты)
- Карта потока: mic/loopback capture → VAD/endpoint/turn → ASR partial+final → brain fast/slow (ReAct) → text stream → TTS streaming/synthesis → playback → barge-in/cancel → echo/self-TTS guard → UI events.
- Для каждого узла: файл:строка, текущий контракт, где может рваться full-duplex, как проверяется (mock/synthetic/real).
- Зафиксировать в `docs/FULLDUPLEX_MAP.md` (кратко) и в `docs/STATE.md`. Статус каждого узла: OK / RISK / BROKEN / UNKNOWN.

### P1 — Надёжный barge-in и отмена (без артефактов)
- Пользовательская речь прерывает TTS/воспроизведение детерминированно: cancel in-flight synthesis, очистка очереди, останов playback, сброс speech state, без «залипания» и без самопроизвольного продолжения хвоста.
- Инварианты под тестами: cancel при ошибке/прерывании, нет утечки очереди, state.error не убивает корректные последующие ходы (Cycle 20 — regression уже есть, расширить до barge-in path).
- Метрика: время от barge-in события до фактической остановки (контракт/сим), корректность следующего хода.

### P2 — Streaming first-audio и устойчивость TTS
- Первый слышимый чанк быстро; поток предложений/чанков не обрывается на транзиентной ошибке; backpressure/slot корректны.
- Различать «HTTP200/queued» и «аудио реально отдано/доиграно» (AGENTS.md).

### P3 — Foreground fast lane (MOSS-like turn-taking)
- Короткие реакции/backchannels/быстрые ответы без полного ReAct prefill там, где это безопасно (policy). Удержание хода vs эскалация в background.
- Turn-policy: не спамить, не захватывать ход без причины; barge-in всегда приоритет пользователя.

### P4 — Echo/loopback guard и coordination
- Self-TTS не триггерит ASR/ambient как пользователь (loopback echo). Background результат вставляется в естественную паузу/speech sink. Проактивные комментарии по экрану — только с turn-policy (TODO).

### P5 — Приёмка
- Deterministic/synthetic: все инварианты P1–P4 зелёные, числа зафиксированы.
- Реальные модели (owned): E2E latency/interrupt сценарии, помечены средой.
- Физический mic / owner art / живой companion-процесс: BLOCKED до наличия — отдельные строки, без фальшивого PASS.

## Правило итерации для DSH
1. Прочитать `docs/STATE.md`, `TODO.md`, этот файл.
2. Выбрать СЛЕДУЮЩИЙ невыполненный пункт самой ранней незакрытой фазы (P0→P5). Один пункт = одна итерация.
3. Сделать: код/контракт + focused regression (deterministic где возможно) + числа/доказательство. Без вопросов.
4. Обновить `docs/STATE.md`, `TODO.md`, `CHANGELOG.md` (PASS/FAILED/UNKNOWN/BLOCKED, file:line, метрики, ограничения). Честно.
5. Если BLOCKED (нужен mic/owner art/железо/аккаунт/живой перезапуск процесса владельца) — зафиксировать и взять следующий выполнимый пункт.
