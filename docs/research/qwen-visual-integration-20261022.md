# Qwen visual describer integration — 2026-10-22

## Что подключено

- `--visual-describer qwen` выбирает Qwen3.5-0.8B как визуальный описатель
  через существующий `composition` и существующий `ScreenCaptureAdapter`
  (`hostos_executor.screen_capture`). Один адаптер захвата, CPU-only.
- Новые флаги:
  - `--visual-describer-url` (по умолчанию берётся `--vision-url`),
  - `--visual-describer-model` (по умолчанию `qwen3.5-0.8b`),
  - `--visual-describer-roi X,Y,W,H` — нормализованная выбранная область,
  - `--visual-describer-active-interval` (по умолчанию 1.0 s),
  - `--visual-describer-static-interval` (по умолчанию 5.0 s),
  - `--visual-describer-periodic` (по умолчанию 10.0 s),
  - `--visual-describer-max-age` (по умолчанию 6.0 s).
- `--visual-describer eg2` (по умолчанию) сохраняет прежнее поведение.

## Архитектура

`src/jawl_voicecompanion/qwen_visual_sensor.py`:

- один фоновый поток захвата и один `QwenEventDescriber` с очередью
  «один выполняющийся + последний ожидающий»;
- триггеры до attention: изменение ROI, смена сцены, периодическая проверка;
- активное видео — не чаще одного запроса в секунду; статичное содержимое —
  `static_interval`; основной режим — одиночный кадр, парный режим не включён;
- каждый кадр несёт `frame_id`, `source`/ROI и `scene_id`;
- если сцена сменилась до завершения запроса, результат старой сцены
  отбрасывается и не попадает в «сейчас»;
- результат доставляется в `PerceptionFusion` один раз; повторное чтение
  `compose` не продлевает TTL, TTL считается от исходного времени захвата;
- `on_observation` вызывается после доставки в fusion; `composition` превращает
  его в `SCREEN_DELTA` для `AttentionPresence`.

`PerceptionFusion`:

- `observe_caption(...)` хранит caption вместе с `captured_at`,
  `frame_id`, `source`, `scene_id`, `roi`;
- экранный канал и EG2-канал разделены: EG2 пишет в `eg2_media`, Qwen — в
  `screen`; словарное описание EG2 больше не перекрывает caption Qwen;
- OCR/UIA продолжают идти отдельными каналами (`window`, `speech`, `eg2`).

`StreamingPerception` (EG2 embeddings/memory) переведён на канал `eg2_media`,
поэтому его описания не перезаписывают Qwen caption. Attention решает, стоит
ли заговорить; DND или активный разговор не останавливают обновление
восприятия — они только подавляют проактивный интент.

## Проверки

`tests/test_qwen_visual_sensor.py` (8 тестов) и
`tests/test_qwen_event_describer.py` (3 теста):

- старение без новых ответов и сохранение исходного времени захвата;
- остановка зависшего запроса и повторный запуск;
- смена сцены во время обработки — результат не доставляется;
- однократная доставка и вызов attention после fusion;
- разделение каналов EG2/Qwen;
- периодический/статичный/активный rate limit.

Все 11 тестов проходят. Дополнительно `tests.test_web` — 75/75 passed,
`tests.test_perception_fusion`, `tests.test_perception_now_ttl`,
`tests.test_streaming_perception` — без регрессий.

End-to-end smoke с реальным Qwen-сервером и реальным экраном: 58 захватов,
6 запросов, 5 доставок, 0 ошибок; `compose` содержит Qwen caption.

## Что осталось

- Qwen-сервер запускается отдельно на CPU (порт из URL); composition его не
  стартует.
- Парный режим кадров не включён: по результатам он дороже (~1.85×) и давал
  выдуманные детали.
- Daily companion сейчас остановлен, поэтому живая приёмка в полном профиле
  ещё не пройдена.
## Dirty/pending ? ????? ?????

- `QwenVisualSensor` ?????? `dirty`/`dirty_reason` ?? ????????? `submit`:
  ????????? ROI, ????? ????? ??? periodic ?????? ???????; ????????????
  ??????? ?????? ??????????? ????????.
- ????? ???????? ?????, ???????????? ????????? ????????? ????, ???? ???? ??
  ????????? ? ?????????? ????????; ???????? periodic ?? ?????????.
- ??? ??????????? ????? ????? ?????? caption ?????????? ????????? ?? ??????
  `screen` (`PerceptionFusion.invalidate`), ??????? ?????????? ????? ??
  ??????????? ??? ????????, ???? ?? ?????? ?????????? ?????????.
- ?????????: `test_scene_change_inside_cooldown_sends_latest_frame_after_interval`
  ? ????? ????? ?????? cooldown, ????? ??????????? ????, ?????? ????? ?????
  ???????????? ?????????.

??. ?????: [qwen-daily-15min-20261022.md](qwen-daily-15min-20261022.md) ? 15-???????? daily run, PARTIAL ? ????????? EG2/Qwen channel collision.

??. ?????: [qwen-on-off-comparison-20261022.md](qwen-on-off-comparison-20261022.md) ? EG2 ???????? ?? ?????, static/periodic=2, ???????????? Qwen-off/on.

24Oct reliability follow-up: QwenEventDescriber stop/restart now recovers when a bounded stop times out during an in-flight transport, without starting a second inference worker. Capture age is computed from monotonic time; the visual adapter records timestamps immediately after the capture adapter returns, before image decoding/cropping/encoding. Regression coverage: hung transport → stop timeout → restart → release → second frame; wall-clock correction versus monotonic freshness. `uv run --extra test pytest -q tests/test_qwen_event_describer.py tests/test_qwen_visual_sensor.py`: 16 passed. This is code-level reliability evidence, not a live long-run acceptance.
