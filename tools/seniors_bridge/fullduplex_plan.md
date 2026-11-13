=== ПРИОРИТЕТ ВЛАДЕЛЬЦА (10.11.2026) — ПОЛНОДУПЛЕКСНЫЙ ГОЛОСОВОЙ СЛОЙ ===
Ты — агент-исполнитель JAWL Voice Companion. Новая постоянная задача: следить за собой и ПРОДОЛЖАТЬ работу, пока не будет построен качественный речевой full-duplex аудио-слой с TTS — по качеству/поведению как у MOSS Live (OpenMOSS).

Эталон поведения (MOSS-Live, архитектура открытая): foreground interaction model — turn-taking, barge-in, backchannels, удержание хода, быстрые ответы, selective attention/live vision; background model — инструменты, долгие задачи (JAWL ReAct); coordination — memory/context/task state + speech sink. Результат фона вставляется в естественной паузе. Модель SenseNova/MOSS несвободна — строим СВОЮ реализацию на стеке JAWL.

Текущий стек (факты): ASR GigaAM v3/crispasr CPU; brain SenseNova-Loop/Bonsai на GPU1; TTS OmniVoice (default) на GPU1; уже есть `live_speech.py`, `speech_first.py`, `speech_requests.py`, `tts.py`, `ambient_audio.py`, `app_audio_router.py`, `audio_understanding.py`, `system_audio.py`, `duplex_cascade.py`, `perception_fusion.py`/turn arbitration, `enrich_turn_text`. TODO: «собрать свою foreground/background архитектуру» (MOSS-Live образец), «комментирование происходящего» с turn-policy. Cycle 20 починил break-на-ошибке в `LiveSpeechSession._run` (нужен рестарт companion, чтобы применилось в живом процессе).

Правила работы (AGENTS.md + BRIDGE_LOOP.md):
- Одна итерация = один видимый, проверяемый результат (код/контракт + focused regression + числа задержек/качества, где применимо). Без вопросов — работай.
- Не трогать read-only (`JAWL-Coding`, `VoiceMem`, `G:\RE`, `runtime/jawl-sources/jawl-20260906-daily-v2`). Не коммитить/reset/убивать чужие процессы. GPU0 не занимать. Тесты в owned профиле, `-B` для protected imports. Секреты не печатать.
- Различать mock / synthetic WAV с реальными моделями / физический mic / owner art. Не считать HTTP200/queued/первые мс звука завершённым ответом.
- После КАЖДОЙ итерации обновить `docs/STATE.md`, `TODO.md`, `CHANGELOG.md` (факты, PASS/FAILED/UNKNOWN, числа, ограничения). Вердикт честный.

Что делать сейчас (итерация 1 этого приоритета), если предыдущее не завершено:
1) Аудит full-duplex контура по коду и тестам: карта потока mic/loopback → VAD/turn → ASR partial/final → brain fast/slow → TTS streaming → playback → barge-in/cancel → echo/loopback guard; где именно рвётся «полный дуплекс» (одновременный слушать+говорить, перебивание без артефактов, backchannel без захвата хода). Зафиксировать в STATE с file:line и статусами.
2) Выбрать ОДИН самый узкий дефект/контракт, который реально мешает качественному full-duplex (например: надёжный barge-in+cancellation сквозь live_speech→playback; или streaming first-audio latency; или echo suppression self-TTS; или foreground fast-lane turn policy) — обосновать по фактам аудита.
3) Реализовать фикс/контракт + focused regression (deterministic, без реального mic/GPU где возможно; реальные модели помечать отдельно). Измерить до/после хотя бы одну метрику (latency/инвариант/cancel correctness).
4) Обновить STATE/TODO/CHANGELOG. В TODO держать явный чек-лист до «MOSS-Live-like full-duplex с TTS» (barge-in, backchannel policy, echo guard, streaming TTS, fast foreground lane, coordination с ReAct) с честными статусами.

Продолжай итерациями по этому приоритету, пока владелец не остановит. Если упёрся в блокер (нужен физический mic/owner art/аккаунт/железо) — зафиксируй BLOCKED с точной причиной и возьми следующий выполнимый пункт из чек-листа full-duplex.
