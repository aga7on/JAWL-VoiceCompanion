# Текущее состояние — 29 октября 2026

## ReAct / VA / большой контекст — актуальное состояние

Daily `hikari-clean-20261029` запущен с Gemini 3.8 Flash через локальный relay,
окно 1M; название профиля историческое. Исправлены Gemini envelope, доступ к
Goal lifecycle из чата, heartbeat-инструменты, отдельный VA/Perception и скрытое
Goal-сжатие до 18K символов. Изолированный native canary завершил проверяемую
фоновую Goal; живой агент после рестарта мозга прошёл 11 полезных шагов без
повторного поиска HostOSReader. Консоль/чат доступны через session bootstrap.
OmniVoice не менялся. Health degraded из-за ожидания ambient audio samples;
весь live audio path этой проверкой не принят. Подробности и доказательства:
[аудит ReAct/VA](research/react-perception-audit-20261029.md).

## Микрофонная backpressure — 29 октября 2026

Заполненная очередь из шести audio uploads больше не выключает capture:
PCM откладывается, посылается укрупнёнными пачками и полностью дренируется до
конца той же реплики. Ограниченный 60-секундный аварийный буфер остаётся только
для backend, который не успевает восстановиться. 28/28 voice lifecycle tests и
125/125 полный Node subset прошли. Live profile завершился, 8045 сейчас не
слушает; физический mic/ASR acceptance после изменения ещё не выполнен.
[Отчёт](research/mic-backpressure-audit-20261029.md).

Ambient audio freshness was also corrected: queue workers now preserve source
capture-time instead of assigning timestamps at processing time. Segmenter 6/6 and
audio integration 31/31 passed. Live loopback under load remains open; details:
[capture-time provenance](research/audio-capture-time-provenance-20261029.md).

YAMNet music-presence and audio-caption model outputs now use separate current
context channels, alongside ASR; source provenance is retained and delayed
non-music/out-of-order events do not leave a stale caption presented as current.
The live EG2 PCM path uses one whole-clip embedding, with full overlapping-window
analysis retained for offline diagnostics; composition limits EG2 to four
intra-op threads. Fast FMA replay found 18/18 YAMNet positive detections but
EG2's catalog genre proxy was top-3 in only 11/18, so specialist outputs stay
unverified and require overlapping YAMNet music support. YAMNet cutoff 0.35
preserved all 18 FMA positives and rejected one two-tone synthetic music/tag
false positive; three other synthetic controls abstained. Five audio suites:
86 passed, 1 skipped; five fast-path replays of the saved 5.99s WAV measured
304ms wall p50 / 424ms max and 969ms process CPU p50.
Live loopback quality, false-positive rate and shared-load behavior remain
unverified: [audio channel report](research/audio-description-channel-20261029.md).

Real-content audio follow-up on five local 10s clips: YAMNet music presence was
4/10 windows in a Russian trailer, 1/10 anime, and 10/10 in gameplay, coding UI
and the song. EG2 marked both speech and music likely in all five, with competing
unverified style/mood candidates; its one-thread wall latency was ~1.14s per
10s clip. GigaAM produced nonempty output twice, but transcript accuracy was not
scored. This confirms music presence plus ASR can coexist, while reliable style
and sound-effect description are not accepted. Details:
[real-content replay](research/realclip-audio-describer-20261029.md).

Visual context now separates invalidated/current captions from short history.
Late Qwen results can be historical within the event TTL; older ones are dropped.
Qwen sensor 18/18, fusion 16/16, now-TTL 2/2 passed. Live scene-change latency
acceptance remains open: [visual stale-context report](research/visual-stale-context-20261029.md).

History-only Qwen captions now also reach the durable one-hour/weekly text archive
with original provenance, without duplicating fresh-screen writes. Fusion/Qwen/
history/TTL suites: 41 passed. Process-restart recall remains open:
[visual history archive report](research/visual-history-archive-20261029.md).

Windows OCR now follows the selected Qwen capture source, including display-index
captures. It runs on initial capture, a pending visual change, or the static
refresh interval, then enters VA as a separate redaction-filtered OCR channel
with a 5s current-context TTL. Scene invalidation also expires earlier OCR.
The combined adapter/sensor/fusion/packet/native-context/web gate passed 163
tests plus 33 subtests. One live capture on display 0 verified Windows OCR through
the sensor and VA packet using a stub Qwen client. Live-profile acceptance and
CPU cost remain open; launch must explicitly enable `--screen-ocr`.
Details: [Qwen OCR channel](research/qwen-ocr-channel-20261029.md).

## Аудит живого Hikari-профиля 29 октября 2026

На момент раннего аудита `hikari-clean-20261029` работал с Hikari 64K, Qwen CPU, GigaAM,
OmniVoice и loopback Game-Audeze Maxwell. Живой аудит выявил context_limit=10,
подмешивание собственного TTS в внешний ASR, устаревание основного caption,
обрезку аудиотекста и исчерпанную квоту инициатив при нулевых proactive delivery.
На том этапе Health degraded; поведение компаньона не было принято.
Факты и проверки: [аудит сеанса](research/live-session-audit-20261029.md).

Кодовый follow-up: frontend сообщает backend о начале и окончании собственного
TTS playback через ephemeral playback marker; аренда обновляется во время
длинного ответа и завершается при Stop/done. Desktop voice lifecycle: 30/30
PASS. Это не доказывает, что активный loopback не транскрибирует собственную
речь в живом профиле; managed live recheck открыт.

Дополнительный VA follow-up: `PerceptionFusion.note()` и snapshot теперь дают
ASR отдельный лимит 2400 символов, audio description — 1600; короткая legacy
summary остаётся отдельно bounded. Native enrichment сериализует полные каналы
в brain-bound packet. Fusion/packet/native-context/web gate: 129 passed + 33
subtests. Проверка фактического prompt в живом профиле после managed restart ещё
открыта.

После добавления регрессий на бюджеты каналов семь смежных audio/fusion/packet/
native-context suites повторно прошли: 111 passed, 1 skipped.

## Обновление статуса 28 октября 2026 — сенсорная история и lifecycle

- Запись 25Oct о «идущем» восьмичасовом soak историческая: при текущей
  проверке процесса сенсорного профиля и его локальных endpoint-ов не было.
  Она не является доказательством текущего unattended/24×7 режима.
- `CompanionRuntime.close()` теперь после остановки источников делает финальный
  flush текстовой сенсорной истории; ошибки `SensoryHistoryStore` больше не
  теряются внутри его best-effort writer и могут быть повторены при повторном
  закрытии.
- Вопрос вида «что было две минуты назад?» теперь подаёт мозгу записи только
  из минутного окна вокруг целевого времени, а не произвольный хвост из пяти
  минут. Слова с числом по-русски и по-английски поддержаны.
- Проверка lifecycle/history/enrichment после добавления restart-регрессии:
  объединённый suite 163 passed + 33 subtests; `py_compile` прошёл.
  Это закрывает две регрессии хранения и извлечения контекста, но не живую
  интеграционную приёмку. Проверки свежести на 30–60 мин, audio ground truth,
  отказ/восстановление источников, restart и полный 8h soak остаются OPEN.

Ветка `dev/daily-companion-20261014`; dirty changes владельца сохранены.
Очередь: [TODO](../TODO.md). План: [DAILY_PLAN](DAILY_PLAN.md).
Приёмка: [DAILY_ACCEPTANCE](DAILY_ACCEPTANCE.md). Запуск: [DAILY_RUNBOOK](DAILY_RUNBOOK.md).

## Обновление статуса 26 октября 2026 — audio semantics

- В `eg2_describer.py` добавлены положительные многоклассовые сцены, отдельные
  candidate-ветки вокала/ударных/баса/электронных тембров и L1→L2→L3 разбор
  перекрывающихся окон с сигналовыми признаками и отдельными межоконными
  изменениями. Кандидаты остаются непроверенными; safe-claim gate и веса не менялись.
- Целевые проверки прошли: coarse-to-fine 3/3, EG2 runtime 2/2, `py_compile`.
  Семь локальных CLAP-контролей не показали улучшения scene top-1 относительно
  предыдущего prompt bank; русская речь всё ещё даёт ложный overlap.
- В репозитории не найден набор вручную проверенных audio-интервалов, поэтому
  критерий P0 по точности/ложным срабатываниям не принят. Детали и артефакт:
  [audio coarse-to-fine report](research/audio-coarse-to-fine-20261026.md).
- Stage latency отдельно отдаёт embedding/L1/L2/L3; capture пока `null`, так как
  descriptor получает WAV после upstream capture. Live P2 не запускался: 503
  prefetch drops, 41.8/60 s capture и непрерывность курсоров не перепроверены.

Сессия OpenCode `ses_ec36a8f41ffe6wjzIAbHN7DnXG` прочитана и продолжена в Codex.
OpenCode остановился на недельной квоте. Новый Codex tool goal зарегистрирован,
status=active: автономно выполнить доступную часть D1–D6. TODO ещё не завершён.

## Обновление статуса 25 октября 2026

- Восьмичасовой observability-only soak профиля `jawl-qwen3-omni-sensors`
  завершился штатно в 15:51:35Z: 960 сэмплов за 28,800.3 с. Ретроспективный
  аудит нашёл visual fresh только в 745/960 сэмплах (77.6%), age p95 9.58 с
  среди 906 измеренных возрастов (54 sample без возраста),
  максимум 39.41 с и два outage-окна; минимум свободной RAM — 0.18 GiB.
  JSONL не считал успешные Qwen audio descriptions. Это длительное
  observability-измерение, но не PASS для 24/7. Подробности:
  [Qwen soak audit](research/qwen-fullstack-soak-audit-20261028.md).
- Текущий active profile подтверждён как Qwen3-Omni (не Hikari), визуальный
  Qwen и `qwen-omni` audio describer выбраны в Companion launch config.
  Доступные измерения CPU/GPU не проходят acceptance по grounding/latency;
  подробности в `runtime/active-goal-addendum-20261025.md` и
  `runtime/qwen3-omni-direct-20261024/ACCELERATION-RESEARCH-20261025.md`.
- Добавлены bounded Qwen audio-description counters/freshness/p95 в shell status
  и System UI; live-процесс изменения ещё не загрузил. UI больше не закрепляет
  устаревшее имя Hikari за brain status.
- Full gate PASS: 1,144 unittest, 18 e2e, pytest fixtures, browser/desktop voice
  E2E, 121 Node tests, PowerShell parse, snapshot/secret scan и diff check.
  Изменения аудио-диагностики отдельно: 32 Python и 14 Node tests PASS.
- Остаются открыты: завершение 8h soak, fresh restart/health, audio-description
  ground-truth acceptance на музыке и речи, full 30–60min mixed-content run,
  controlled worker/capture failure recovery и непрерывная restart acceptance.
  Post-soak: prove a full brain turn on one Qwen slot at context 12,288 with exact token counts; then run matched serial CPU/GPU A/B. Consider two 12K slots only after measured queue contention and KV/VRAM preflight. Cancel the old three-slot 8K plan: it cannot fit the observed full prompt.

## Sensory history acceptance (2026-10-25)

A one-hour rolling text timeline plus seven-day compact hourly store is implemented and covered by focused tests. Ten-minute live sensors ran without errors (199 samples, 264 observations), but direct retrieval of a two-minute-old state and full-session audiovisual synthesis were only partial. The run used a companion started before the new store wiring, so a managed restart is still needed to verify persistence and prompt retrieval end to end. Details: `docs/research/sensory-history-acceptance-20261025.md`.

28Oct LFM visual GPU probe: 60 measured single-frame requests, five source frames; detail p50 GPU1 LFM450 128 ms, LFM1.6B 198 ms, Qwen0.8B 293 ms. All remain imperfect fact sources; no daily-profile switch or live acceptance. [Report](../runtime/lfm-detail-probe-20261028/STATUS.md).

28Oct live YouTube capture via ScreenCaptureAdapter and LFM450 GPU1: 50/50 text observations, raw live frames not persisted, latency p50 64.8 ms/p95 108.5 ms/max269 ms. 46 adjacent frame digests changed. Hikari text-only recap 1.08s declined to infer a coherent plot but answered in English and omitted details; no independent ground truth for personalized clip. Report: [LFM450 story replay](../runtime/lfm450-story-replay-20261028/STATUS.md). A same-frame live Florence-2 `<OD>` comparison then ran for 25 frames, p50 853ms, on the same 960?520 adapter output; detections were mostly generic faces/people and Hikari could not build a plot from them. The adapter is capped at 960px width and JPEG quality 72; original source dimensions were not recorded, so maximum-detail acceptance remains inconclusive. Higher-resolution matched replay is open.

## 2026-10-29 — terminal dialogue context

- The Hikari process already has a 65K model context window, but its active terminal configuration exposes only 10 recent messages (about five exchanges). The owned brain now installs a terminal-context adapter that keeps recent messages verbatim and compacts older turns into bounded chronological excerpts before the provider budget is reached. Appended live perception snapshots are omitted from compacted older turns; the separate sensory timeline remains the source for historical observations.
- Managed restart completed at 2026-10-29 01:00 MSK. The active profile has `history_limit: 200` and `context_limit: 200`; startup receipt confirms the terminal compaction hook is installed. It preserves the full transcript until 18K characters, then keeps the latest 12 messages verbatim and compacts older messages into chronological excerpts. The provider budget is 20K characters.
- All six profile endpoints are listening and the desktop window is visible. Health is `degraded`: screen captures run with zero capture errors, but recent captions age out amid scene-change drops; loopback capture is running on the NVIDIA output and is waiting for samples. No long-conversation threshold exercise has been done yet.
- Static Python/Powershell syntax checks succeeded. The owned runtime lacks `pytest`, so focused pytest execution could not start.
