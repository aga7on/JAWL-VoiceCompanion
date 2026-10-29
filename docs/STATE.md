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

ADR-048 now fixes the permanent model-role canon: Gemini 3.8 Flash brain via
relay; Qwen3.5-0.8B Q4 CPU vision; Windows OCR/UIA; GigaAM q8 CPU ASR;
EmbeddingGemma 2 ONNX and YAMNet ONNX CPU audio lanes; MiniLM ONNX CPU memory
vectors; OmniVoice 0.6B on CUDA 1. This is a role decision, not live acceptance.
The legacy runtime manifest still defaults to Hikari/local-bonsai2 and must not
be used alone to claim a canonical Gemini launch.

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

29Oct Russian speaker-affect candidate probe: Aniemore XLS-R int4 loaded in the
CPU-only vision environment after an isolated `compressed-tensors` dependency
was supplied. On three real WAVs, inference took 16.1–24.4s for 6.5–10.0s
inputs; peak RSS was 1.69 GiB. It emitted near-certain enthusiasm on both
neutral instruction fixtures, so reject it for always-on affect. There is no
accepted learned voice-affect classifier; see
[candidate probe](research/russian-speech-emotion-cpu-candidate-20261029.md).

29Oct follow-up adds an experimental, non-neural direct-microphone delivery
measurement lane: coarse pitch percentiles, signal-level range and periodic
frame ratio flow from a successful GigaAM mic turn into a separate, 12-second
VA channel. It does not classify emotion, analyze system loopback, or persist raw
audio/history. It is disabled by default; `--voice-delivery-cues` opts in. The CPU path is source-integrated but **not accepted**: calibration,
latency/RSS, owner-reviewed speech, and live brain uptake remain open. Details:
[voice delivery cues](research/voice-delivery-cues-20261029.md).

29Oct VA audit found the packet serializer omitted the existing
`audio_description` and `audio_candidates` channels from its fixed label list.
Both now survive packet creation. Combined regression gates verify screen, OCR,
ASR, audio caption, music evidence and YAMNet event hypotheses through web
enrichment and native `PERCEPTION / VA`: packet 9/9, web 85/85, native 17/17,
fusion 23/23, ambient audio 32/32 and YAMNet 10/10. Live audio delivery and
real-model uptake remain to be observed:
[VA audio handoff](research/va-audio-channel-handoff-20261029.md).

Real-content audio follow-up on five local 10s clips: YAMNet music presence was
4/10 windows in a Russian trailer, 1/10 anime, and 10/10 in gameplay, coding UI
and the song. EG2 marked both speech and music likely in all five, with competing
unverified style/mood candidates; its one-thread wall latency was ~1.14s per
10s clip. GigaAM produced nonempty output twice, but transcript accuracy was not
scored. This confirms music presence plus ASR can coexist, while reliable style
and sound-effect description are not accepted. Details:
[real-content replay](research/realclip-audio-describer-20261029.md).

29Oct ambient ASR now shares the narrow noise-artifact predicate already used
for microphone transcripts. Empty/filler, repeated-character and CJK/Hangul
outputs are dropped before ambient memory or current VA context; filtered count
is exposed as `asr_noise_filtered`, and missing ASR confidence is no longer
filled with an invented 0.7. YAMNet still sees all audio independently. This is
not speech detection or transcript accuracy acceptance; plausible hallucinations
and live mixed-loopback quality remain open:
[ambient ASR artifact gate](research/ambient-asr-artifact-gate-20261029.md).
Ambient screen/audio observations now retain `verified=false` through current VA,
delayed-triage inputs and generated episodes; triage is instructed to preserve
that uncertainty. Unscored GigaAM text of at least eight characters may now enter
the seven-day archive as retain-only `Непроверенная ASR-расшифровка`; it is
not auto-promoted. This is provenance labeling, not ASR accuracy validation.
The system-sensor card now reports loopback ASR mode, accepted-fragment and
artifact-filter counts, plus age/freshness of its last transcript without
showing transcript contents. This is status plumbing, not live ASR acceptance:
[loopback ASR status](research/ambient-asr-status-20261029.md).

ASR fixture acceptance now compares known synthetic speech with its source text
(WER ≤0.20) and requires an empty result for pure noise. Current GigaAM CPU replay
passed all nine speech variants, including both copies in the consecutive-phrase
case, and abstained on noise-only. A separate Russian SAPI-generated prompt with
its recorded reference also scored WER 0.000. Faint speech and 0 dB SNR remain
tolerant controls without an accuracy assertion. This does not establish accuracy
on independently recorded speech or live mixed-media audio. On the same SAPI
speech-only WAV, YAMNet emitted no event tags and Music peaked at 0.0002 over six
windows; this is one controlled negative for music presence, not a broad false
positive estimate.

The CPU YAMNet sound-event candidate lane now travels separately from music and
ASR through the brain packet, with explicit unverified status and rapid
stop/pause invalidation. Source-deduplicated ESC-10 folds 4/5 were used to
remove generic Vehicle/Engine/Aircraft labels and select a raw-score cutoff of
0.15. Untouched fold 3 produced 58/64 exact-category labels (90.6%) and 40/65
clips with an exact class candidate; pooled across three folds, 171/189 labels
matched the single ESC-10 class and the separate music gate fired on 0/181
environmental clips. This remains corpus-specific, uncalibrated evidence, not
full audio acceptance. Silence/noise controls, live loopback and brain uptake
remain open:
[SFX candidate report](research/yamnet-sound-event-candidates-20261029.md).

29Oct output-route check: WASAPI selected the current default
`DigitalOutput (2- NVIDIA High Definition Audio)` loopback at 48kHz stereo and
started/stopped without error. A 10s scalar-only idle probe received zero
callbacks/chunks (no playback stimulus), so it proves endpoint opening only;
the JAWL/Companion service ports were also stopped. No live audio content or
PCM was stored. Signal delivery and brain uptake still require a live profile
with playback.

Visual context now separates invalidated/current captions from short history.
Late Qwen results can be historical within the event TTL; older ones are dropped.
Qwen sensor 18/18, fusion 16/16, now-TTL 2/2 passed. Live scene-change latency
acceptance remains open: [visual stale-context report](research/visual-stale-context-20261029.md).

History-only Qwen captions now also reach the durable one-hour/weekly text archive
with original provenance, without duplicating fresh-screen writes. Fusion/Qwen/
history/TTL suites: 41 passed. Hourly compaction now preserves both boundaries and
temporally spread salient moments; rolling-hour prompt compaction also preserves
source-time order and samples the middle under its character budget. Seven history
tests pass, including dense 60-event context and late-result ordering. Integrated-
profile restart and live recall remain open:
[visual history archive report](research/visual-history-archive-20261029.md).
The hourly archive now also samples meaningful ambient-ASR phrases (≥16 transcript
characters), unverified music descriptions and sound-event candidates; all remain
marked unverified, and the timeline's hourly compaction keeps the record bounded.
The new selection rule has not yet been regression-tested or observed in a live run.
`PerceptionFusion` now counts history-store outcomes/errors and the sensor card
shows these counters without text content. This verifies only record-call status,
not disk flush/reopen or brain retrieval:
[history-write telemetry](research/sensory-history-write-telemetry-20261029.md).
The sensor card now separately reports last successful flush age and identifies
whether persistence errors came from loading, writing, clearing, or telemetry;
this remains process-reported status and does not verify reopen
or recall by the brain. An unreadable, oversized, or unsupported-schema archive
is now protected from an automatic empty/partial overwrite until explicit clear.
The focused sensory-history suite passed 8/8, including preservation of the
original file for all three invalid-archive cases and successful writes after
explicit clear. History-query context now warns the brain when saved history is
unavailable and labels remaining observations as current-process-only; live
retrieval by the brain remains unverified. Missing or failed history retrieval
is also disclosed in the VA packet instead of silently presenting visual-only
fallback as the complete audiovisual timeline.

Windows OCR now follows the selected Qwen capture source, including display-index
captures. It runs on initial capture, a pending visual change, or the static
refresh interval, then enters VA as a separate redaction-filtered OCR channel
with a 5s current-context TTL. Scene invalidation also expires earlier OCR.
The combined adapter/sensor/fusion/packet/native-context/web gate passed 163
tests plus 33 subtests. One live capture on display 0 verified Windows OCR through
the sensor and VA packet using a stub Qwen client. Live-profile acceptance and
CPU cost remain open; launch must explicitly enable `--screen-ocr`.
Details: [Qwen OCR channel](research/qwen-ocr-channel-20261029.md).

29Oct standalone live CPU smoke then ran the real Qwen3.5-0.8B Q4 server with
GPU layers/projector offload disabled and Windows OCR on display 0. Eleven
transient captures produced one Qwen delivery with separate `screen` and `ocr`
channels in the VA packet and zero capture errors; confirmation age was 31ms,
caption age 6.25s. No raw frame or OCR/caption text was persisted. Broad scene
transport passed, but small text was corrupted; full-profile uptake, visual
accuracy, scene-change continuity and sustained resource use remain open:
[CPU screen/OCR smoke](research/qwen-screen-ocr-cpu-smoke-20261029.md).
The launcher now enables `--hostos-live --screen-enabled` when Qwen is selected,
without requiring the separate legacy ScreenWatch worker; `-EnableScreenOcr`
adds OCR, and an OCR-only configuration without a capture path fails early.
Focused launcher regression passed.

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

Loopback во время этой аренды теперь продолжает только независимый YAMNet
music/SFX lane: ASR и текстовый EG2-caption не получают собственный голос JAWL.
Focused regression подтверждает, что музыка остаётся в ambient memory, а final
ASR и captioner не вызываются. Реальный loopback с музыкой поверх речи и точность
SFX во время TTS пока не проверены.

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

## Production ambient audio bridge replay: 29 October 2026

Paced 10.01-second Aqua clip through the real `AmbientAudioASRBridge` with
GigaAM q8, EG2 ONNX, YAMNet ONNX, in-memory ambient retention and
`PerceptionFusion`; no Companion, capture device or network service started.
The 11.16-second replay flushed cleanly: one GigaAM final was retained, YAMNet
reported music (raw score max 0.9834), EG2 abstained as unknown, and
`speech`/`music`/`audio_candidates` were fresh in fusion. No transcript text or
PCM was persisted; transcript correctness was not scored. This is a local bridge
replay, not live loopback or brain-turn acceptance. Follow-up replay of Russian trailer + Aqua
song passed actual `speech`, `music`, and `audio_candidates` through
`make_packet`/`attach_packet`/`split_packet`/`render_packet`; packet round-trip
was valid and all three channels were fresh. No caption/SFX event appeared on
those samples, and no live brain request was made. [Report](research/ambient-audio-bridge-paced-replay-20261029.md).

Self-TTS mixed-audio follow-up: a 4 s in-memory Tera speech + Aqua mix, paced as
eight 0.5 s loopback chunks with `PlaybackSuppression` active, ran through the
production bridge and real YAMNet `CPUExecutionProvider`. YAMNet reported music
on 2/3 windows with no drops/errors/stale results; the ASR client received zero
calls. Neither PCM nor transcript was persisted. This verifies bridge routing
and music presence on one local mixed clip, not physical TTS/WASAPI capture or
general sound-event precision. [Live-session audit](research/live-session-audit-20261029.md).

Speech/music masking scout: six opening 4 s FMA clips (one per broad genre) were
mixed in memory with repeated Tera speech at music/speech RMS SNR −12, −8, −4,
and 0 dB. YAMNet CPU detected 2/6, 2/6, 3/6, and 4/6; matched music-only
baseline detected 4/6, while speech-only abstained. Detected track identities
changed under overlap, so this is exploratory sensitivity evidence, not a
calibrated recall figure; the 0.35 production cutoff was not changed. The EG2
safe-claim adapter drops its detailed music claim when transcript text is
present, while independent YAMNet remains active. [Overlap report](research/audio-speech-music-overlap-20261029.md).

## LFM3-Audio-2B candidate ? 29 October 2026

Official Q4_K_M GGUF is 1.1 GB plus a 338 MB audio mmproj, but project llama.cpp
commit `1a07bfa` has no LFM3-Audio runtime support; upstream PR #31257 is pending.
Official Q4 CPU ONNX bundle is 2.71 GB and requires a decoder/cache runtime, so it
is not a drop-in classifier. No daily-profile change. An isolated benchmark remains
a candidate only after a compatible runtime is available.
[Research note](research/lfm3-audio-cpu-candidate-20261029.md).

29Oct follow-up: the 0.35 confirmed-music gate and multi-window requirement are unchanged. Weak unconfirmed YAMNet Music scores (raw max ≥0.20) now pass to a separate `music_candidate` hypothesis channel with 12s current-context TTL; they are not stored as confirmed music and are invalidated by the next confirmed/no-candidate segment. This preserves a clue for the brain when speech masks music without relabeling tones as music. The 0.20 routing cutoff is exploratory and still needs source-disjoint real negatives; focused bridge, fusion, packet, and YAMNet suites pass. Details: `docs/research/audio-speech-music-overlap-20261029.md`.

29Oct CPU route evaluation: 181 source-disjoint ESC-10 non-music clips, three
recorded speech-query fixtures, and four synthetic speech/noise controls emitted
zero weak Music candidates. Eighteen four-second FMA music openings yielded 16
confirmed, one weak candidate, and one with no Music cue. Across 54 in-memory
speech+music mixtures (three speech fixtures × six tracks × three SNRs), the
bridge decision emitted 11 weak candidates and 34 confirmed music detections.
Five existing real-media excerpts yielded four confirmed detections and one
weak anime candidate (raw max 0.3819, one of ten windows).
This supports the separated hypothesis route but is exploratory: mixtures reuse
the same small set, labels are not listener-verified, and there was no live
loopback. Confirmed threshold remains 0.35. Raw-free artifact:
`runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json`;
reproducer/report: `scripts/probe_yamnet_weak_music.py` and
`docs/research/audio-speech-music-overlap-20261029.md`.
