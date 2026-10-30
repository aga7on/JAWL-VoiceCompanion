# Приёмка ежедневной версии

Цель — пригодность для личного использования, не универсальная сертификация.
Это сценарии для TODO D1–D6, не ещё одна очередь. Дата плана:14Oct2026.
Канонический набор ролей моделей зафиксирован в [ADR-048](DECISIONS.md#adr-048--canonical-daily-model-roles);
принятие набора не заменяет аудио-, визуальную и integrated live-приёмку.
Ни одна строка ниже пока не означает самостоятельный acceptance PASS; строка
«Микрофон» фиксирует только принятие владельцем прежней Fifine-проверки.

Статус 24Oct: native-owned 8h soak пройден (476 cycles, 0 failed; один
контролируемый transport fault восстановлен), но он не покрывал полный daily
profile, физический ввод или screen/audio capture. Поэтому строка «Ночь» ниже
остаётся открытой как integrated full-stack acceptance. Владелец сообщил, что
ранее проверил Fifine и доволен; повторная физическая микрофонная проверка не
планируется.

29Oct ASR fixture gate: known synthetic speech is now checked against its exact
source phrase with WER ≤0.20; the repeated-phrase case must retain both copies,
and pure noise must yield no transcript. Current GigaAM CPU replay passed nine
speech variants and the noise-only abstention control. This is fixture-level
evidence, not acceptance for independent speakers, external-media speech, or the
integrated live profile.

24Oct live audio update: the configured NVIDIA DigitalOutput loopback (device 39)
delivered fresh nonzero signal; the integrated ambient bridge and GigaAM returned
exact transcripts for three known short Russian fixtures with no drops/errors and
without persisting PCM. A headless ambient profile reported `tts=not_configured`,
so this ASR smoke required no TTS worker. This closes endpoint routing and these
fixture cases only; mixed-media semantics and the integrated 30–60-minute
continuity gate remain open.

24Oct soundscape update: YAMNet now runs as a separate one-thread CPU lane
beside GigaAM in ambient capture. A live playback smoke detected sustained music
while ASR abstained; a synthetic speech+music bridge smoke retained both lanes.
The detector emits only recurrent class evidence and at most one strongest
stable tag; the MERT affect result and weak style guesses are not current-context
claims. This does not pass source-labeled game/video accuracy or long-run
acceptance. The 30–60-minute run must include music-only, narration over music,
speech-only/noise/silence controls, transitions, correct dual-track composition,
false-claim rate, age/TTL, CPU/RSS, DND, pause and recovery. Music acceptance
also explicitly covers broad style/genre, audible instrument/timbre families,
vocal versus instrumental changes, energy/tempo and soundtrack transitions,
plus a concise grounded description when evidence supports one. Mood and
narrative interpretation must be validated against human labels; otherwise the
sensor should abstain. ASR transcript quality alone cannot pass this criterion.

24Oct live music/style follow-up: a fresh 14.81s NVIDIA DigitalOutput loopback
sample had 694 chunks, 0 drops/errors, persistent YAMNet Music in 13/13 rolling
windows (median .8925; mean 2.76ms per window CPU), and no GigaAM transcript.
Electronic music/Techno scores were below .03, so style remains unidentified;
conditional MERT completed in 1.91s but its affect coordinates are not validated
against labels. This proves live path + presence on one sample, not music style,
mood or general live accuracy. PCM/transcript were not persisted.

24Oct integrated real-clip audio canary: with the normal GigaAM path enabled,
241s of NVIDIA DigitalOutput capture processed 16 ASR segments and 16 YAMNet
classifications with zero capture/processing drops, zero stale results, and a
fully drained stop. YAMNet detected music in the Electronic control and Aqua
montage segment, but supplied no stable genre/instrument tags. GigaAM retained
four speech observations; the monitor redacted their text, so transcript
accuracy was not scored. The 15s segment cap made event age roughly 14–15s
despite fast inference. A VoiceMem-only control accumulated an 8-segment queue
and produced a stale first description after ~120s. A Qwen-backed chat request
echoed the user question rather than describing audio; a direct Qwen prompt over
the same YAMNet metadata answered correctly. Hikari startup was blocked because
live `n_ctx=8192` is below the measured 11,536-token startup prompt. Full report:
`docs/research/live-audio-gigaam-canary-20261024.md`. These results do not close
integrated co-watching or 24/7 acceptance.

24Oct conditional CLAP research: the pinned audio/text ONNX pair ran CPU-only at
one thread. It recognized a saxophone sample and speech/music scene, but
misidentified the Bach excerpt as saxophone/jazz with both a single phrase and
a three-paraphrase bank; its style rankings on the synthetic chord were weak
and ambiguous. The ~930 MiB isolated process and small non-source-disjoint
suite do not justify a daily-profile lane. Style/genre and grounded musical
description remain open; see
`docs/research/music-sensory-candidate-evaluation-20261024.md`.

24Oct source-disjoint music-style probe: 18 FMA Medium recordings from 18 unique
artists across Classical, Electronic, Folk, Hip-Hop, Jazz and Rock, plus four
speech/music/noise/silence controls. CLAP top-1 matched weak catalog genres on
12/18 (66.7%); it missed all three Electronic examples and matched Jazz 1/3.
Controls ranked as expected, but this small proxy-labeled set does not pass
style acceptance. CPU audio-encoder p50/p95 93.65/97.15 ms; isolated process RSS
~0.96 GiB with both encoders and Python. CLAP remains research-only; detailed
instrument/vocal/tempo/transition/caption quality remains unverified. No PCM or
transcript was written by the probe.

24Oct follow-up after playback was reported enabled: NVIDIA loopback opened and
collected 697 chunks over 14.87s with no drops, but RMS was `8e-6` (-101.5 dBFS).
YAMNet classified all thirteen windows as silence and GigaAM abstained. No
PCM/transcript was persisted. This did not provide audible music evidence; the
live probe reports `no_audio` for this capture. A separate 14.81s capture on
the same device had persistent Music in 13/13 windows, confirming the detector
works when signal reaches loopback; genre/style remains unverified.

24Oct code gate: `scripts/run_full_gate.ps1` passed after fixing corrupted Russian
screen-query/prompt strings. Snapshot verification and secret scan were clean;
1119 unittest, 67 pytest and 18 API/E2E tests passed, plus browser interaction,
synthetic desktop voice, Node and diff checks. This does not close integrated
daily-profile acceptance.

24Oct 4-hour sensory case simulation: PASS on the fixed 20-case local suite,
49 batches (20/20 cases passed each), 14,411.6 seconds elapsed, 0 errors. It
covered Qwen CPU vision, EmbeddingGemma ONNX, GigaAM CPU, speech/noise/silence,
and one Bach music-context fixture. Scope was local replay only: it did not use
live screen/audio capture, YAMNet style inference, multiple labeled music styles,
or the full daily desktop/service profile. Thus it validates fixture stability,
not live co-listening or music genre/description. Result:
`runtime/sensory-case-simulation-20261024-clean.json`.

24Oct sensor UX update: the System panel now shows the latest YAMNet result and
capture-time age, distinguishes a fresh music event from an abstention, and
suppresses the previous music claim while loopback is paused. Only a stable
event tag may be shown; it does not call that tag a genre. Backend and renderer
tests cover positive, no-confirmation, stale, paused, unavailable and recovery
states. A hidden Electron renderer harness with representative state was visually
checked at 320×420, 360×540 and 1280×770; browser interaction E2E now covers 9
viewports including 720×480 and 320×420 with no horizontal page overflow. The
compact HUD wraps at narrow widths and keeps music age/DND visible. Keyboard
Tab/Enter navigation, Space/Enter DND control and visible focus passed browser
E2E; axe-core 4.14 reported zero WCAG A/AA/2.2 AA violations at 1280×720 and
360×540. This scoped automated result is not a full manual WCAG audit or live
daily-profile acceptance.

24Oct parallel real-media sensory review: independent video and audio audits
were run against the same five-case, 50s montage. The existing Qwen2.5-Omni
GPU endpoint received the full audio track plus ten timestamped stills in one
request (4.065s, completed); it declared no speech in all ten intervals,
omitted music evidence, mislabeled Electric Noosphere as StarCraft II, and
overgeneralized a brief Aqua keyboard close-up as the whole 40–45s interval.
The contact sheet confirms the keyboard appears around 42–43s among singer
shots, so this is weak temporal aggregation rather than an invented object.
This rejects that exact one-call fusion
path as the daily sensory describer, not the separate modular lanes. Repeated
CPU YAMNet/GigaAM replay was deterministic: persistent music in four of five
clips, with weak/unsupported style tags and no transcript-accuracy scoring.
The clip-level evidence still lacks human labels and live freshness under load.
Do not claim music genre/mood or close the context/continuity gate from these
results. Reports: `docs/research/qwen25-omni-full50-joint-20261024.md`,
`docs/research/realclip-audio-five-case-recheck-20261024.md`, and
`docs/research/music-vibe-build-vs-train-20261024.md`.

| Проверка | Достаточный результат первой версии |
| --- | --- |
| Запуск | Одна понятная команда поднимает сохранённый профиль и Electron UI; effective модели и готовность понятны; закрытие окна скрывает его, отдельный Stop подтверждается launcher owner и чистит только принадлежащие ему службы; Stop/restart не дублируют workers |
| Доставка | 20 последовательных коротких RU text/voice ходов: нет потерянных/двойных ответов; при специально вызванном отказе один явный error |
| Скорость | Измерены20 warm реплик и cold отдельно: конец речи→первый звук, p50/p95 и min/max; целимся1–3с, превышения перечислены и оценены владельцем |
| Звук | Полная разборчивая речь без обрыва/самоповтора, правильные partials; пользовательский Stop прекращает старый звук, следующий ответ работает |
| UI/UX | HUD и Studio проверены при 320×420, 360×540, 720 px breakpoint и обычном desktop размере; нет горизонтального overflow, все вкладки доступны клавиатурой с видимым focus, интерактивные поля озвучиваются по имени; screenshots и axe/contrast review относятся к актуальному renderer |
| Sensor UX / continuity | На минимальном HUD без DevTools понятны активные источники, freshness и DND; при совместном просмотре DND подавляет речь, но не захват; вопрос о смене сцены/текущем звуке получает grounded ответ и correction учитывается; при потере/возврате источника UI честно показывает unavailable→fresh, gap, Stop и erase не возвращают stale observations |
| Микрофон |Владелец ранее проверил Fifine и доволен; повторная физическая проверка не требуется. Это owner-confirmed, а не независимая проверка Codex. Отдельно не заявлять акустический barge-in/full duplex без его специальной проверки |
| Интонация речи | На размеченных RU примерах отдельно проверить акустические признаки подачи (темп, громкость/энергия, высота и вариативность тона) и эмоцию; не выводить эмоциональное состояние из ASR-текста. На спонтанной речи classifier обязан уверенно abstain при слабом сигнале; считать precision/recall и ложные эмоциональные срабатывания, прежде чем передавать метку мозгу как факт |
| Присутствие | Персонаж остаётся видимым, окно не мешает ПК, позиция сохраняется; текст над головой совпадает с ответом, один audio owner |
| Контекст | Три смены тестового окна/видео и размеченный soundtrack: свежие description/transcript/music observations с provenance; ASR и музыка сосуществуют поверх речи; проверены broad style/genre, audible instrument/timbre families, vocal/instrumental changes, energy/tempo and soundtrack transitions, плюс grounded short music description; жанр/инструмент/настроение заявляются только при устойчивой подтверждённой метке, иначе abstain; музыка-only, речь+музыка, speech-only/noise/silence и transitions проверены; stale/TTL/pause видны, собственная TTS не команда |
| Инициатива | Самостоятельный уместный комментарий; пользователь и DND подавляют инициативу, нет повторяющейся болтовни |
| Действия | Три disposable поручения: открыть/изменить/прочитать результат через native tools; отказ и Stop не дают обхода policy или двойного эффекта |
| Память | Факт, исправление, restart и содержательный recall; незавершённая задача сохраняется после прерывания речи |
| Непрерывность и ночь | Интегрированная приёмка 30–60 мин и 8-часовой full-stack soak с отказом worker, потерей/возвратом источника и окна; по возможности — suspend/resume Windows. Ограниченные ресурсы, явный пробел наблюдения, восстановление только на свежих данных, без stale replay и дублей; DND, Stop и privacy сохраняются после восстановления |
| Regression | После крупного runtime объединения existing full gate + затронутые live сценарии; docs-only не требует запуска моделей |

Числа20/3/8h — выбранный инженерный объём проверки, не статистическая гарантия24/7.
Нет бесконечного повтора gate ради зелёного результата: каждый FAIL → причина/
исправление/новый прогон. Если capability отсутствует, записать ограничение,
а не подменять её mock. После успешной ежедневной эксплуатации расширять backlog.

Для каждого запуска достаточно одной короткой записи: дата, revision+dirty
baseline, профиль, вход/ожидание/факт, ошибки/timings, ссылки на report, итог
и границы (synthetic WAV/real models/physical mic). Не хранить секреты/CoT.

24Oct YAMNet CPU probe: music presence separated Bach/saxophone from Russian speech, noise, and silence on local controls. Top tags also identified keyboard/piano/harpsichord on Bach and woodwind/saxophone on the sax sample (one-thread model-load RSS 78.9 MB). Its broad-style and mixed speech+music evidence is still inconsistent, so music evaluation now explicitly includes style, instrument/timbre, vocals, tempo/energy, transitions, and grounded descriptions alongside external-media ASR. No genre/mood claims are accepted from uncalibrated scores; see `docs/research/music-sensory-candidate-evaluation-20261024.md` and `runtime/audio-path-replay/out/yamnet-music-style-probe-20261024.json`.

24Oct YAMNet FMA style probe: the one-thread ONNX CPU model matched catalog broad-style labels on 12/18 artist-disjoint clips (66.7%), same aggregate as CLAP; per-class results were Classical 3/3, Electronic 2/3, Folk 1/3, Hip-Hop 1/3, Jazz 2/3, Rock 3/3. Median top-style margin 0.02098; labels are weak catalog proxies and model scores uncalibrated. 8s crop p50/p95 21.80/23.16 ms; process RSS ~75.2 MiB. This is a low-cost candidate tagger, not accepted genre/mood recognition or captioning. Do not make genre claims without confidence/abstention validated on a larger listener-checked set. Reproducer and artifact are in `docs/research/music-sensory-candidate-evaluation-20261024.md`.

24Oct live no-mic/no-TTS ambient profile: 1,741 seconds / 174 polls, zero monitor errors, zero loopback drops, zero soundscape errors, 115 audio segments processed. The 15s individually licensed Electronic FMA positive-control playback at -18dB produced one fresh `music` event; GigaAM stayed silent, with no stable style/instrument tag. Most other segments were unknown, so this does not validate broad music recognition, style, or general external-media ASR. The monitor stored categorical telemetry only. One 1970 memory timestamp exposed monotonic time being passed as wall time; the source fix is covered by 30 passing focused tests. The fix was not in the running profile; live revalidation remains open. Report: `runtime/qa-audio-live-30m-20261024.json`.

24Oct desktop lifecycle smoke: isolated Qwen-backed profile reached Companion
ready, Electron stayed alive, and a request/instance-ID matched managed Stop
was acknowledged; launcher exited 0 and its four temporary ports were closed.
Process-tree telemetry recorded 35 complete 250ms samples with zero monitor
errors. This fixed an inherited `ELECTRON_RUN_AS_NODE=1` child-environment bug.
The stop was sent through the profile request file, so a real tray click is
still untested; this was not daily-profile or long-run acceptance. See
`docs/research/desktop-launcher-lifecycle-smoke-20261024.md`.

24Oct music latency follow-up: ASR retains its 15s segment limit while the
independent YAMNet lane now segments at 4s and publishes measured
`MusicFrame` telemetry to PerceptionFusion; an unconfirmed frame replaces the
current music claim without being stored as a memory fact. A CPU-only replay of
the five local 10s clips was paced at source duration through the production
bridge (50.97s wall time for 50.05s audio), with 15 segment inferences, zero
queue drops and zero worker errors. The artifact records `local_fixture_replay`
and ~11ms post-segment processing age; it does not measure hardware capture
latency or ASR text. The shorter segment horizon does not establish live
capture-to-context age or 24/7 stability. 89 focused tests pass after the
provenance and age telemetry assertions.
Live loopback, integrated 30–60m acceptance and 8h soak remain open; see
`docs/research/music-frame-bridge-20261024.md`.

24Oct context-contract update: stable YAMNet class labels now pass through
PerceptionFusion into brain context as `candidate_tags_unverified`, with a
calibration flag, rather than being silently discarded or asserted as facts.
Audio interval start/end ages are serialized relative to the same snapshot
moment as video-frame age. This proves context wiring only; tag accuracy and
brain use remain unvalidated. Focused audio/web gate: 120 tests plus 29
subtests passed.

24Oct managed Hikari GPU1 16k retest: after explicit owner approval, the
user-owned 8990 process was replaced by an isolated managed profile at 16,384
context, CUDA1, one slot. `/props` and `/slots` matched 16,384; `SYSTEM_CORE_START`
completed in 6.66s at 11,543 provider prompt tokens, and one real JAWL
`/api/chat` control turn returned the expected `4` in 0.828s. GPU1 showed
8,767 MiB used / 7,211 MiB free; no allocation failure. This was text-only with
TTS, microphone, loopback and visual capture disabled; OmniVoice 8995 was
untouched. It clears only the 16k startup and single-turn probe. It does not
pass multi-turn quality, concurrent sensing, the daily profile, or long-run
acceptance. Evidence: `runtime/hikari-gpu1-context16k-live-turn-20261024.json`
and `docs/research/hikari-context-startup-probe-20261024.md`. Three post-turn
windows (15 samples over 150 seconds) kept health ready, Hikari RSS at
8,592 MiB, and GPU1 usage steady; this is not a soak.
The bounded managed profile subsequently exited with code 0 and
`brain_leaked_after_run=false`; ports 8990/2367/8766/8770 were closed. See
`runtime/hikari-gpu1-context16k-acceptance-20261024.json` for lifecycle proof.

24Oct regression gate after the dual-segmenter change: an initial full run
found missing dev dependencies for imports from the pinned JAWL source snapshot,
missing Selenium for browser E2E, and two Windows supervisor tests using
`os.kill(pid, 0)` as a non-destructive liveness probe. Dev requirements now
include the packages required by snapshot-backed tests and browser E2E; the
Windows check now observes a process synchronization handle. Current full gate
passes: 1,138 unittest, 67 pytest, 18 API E2E, nine-viewport browser interaction,
synthetic desktop voice, Node, PowerShell parse, snapshot, secret scan and
`git diff --check`. This is still deterministic repo evidence; Hikari context,
real media grounding, live daily profile and 8h soak remain unaccepted. See
`docs/research/full-gate-20261024.md`.

24Oct 20-case sensory simulation: the clean CPU fixture harness completed 49
five-minute batches (4h 00m, 980 case executions, zero runtime errors) with
stable Qwen captions and bounded Qwen RSS. This is an isolated harness pass,
not semantic or daily-profile acceptance; its EG2 raw audio argmax produced
false music/SFX labels on speech, noise and silence controls. It did not run
the production YAMNet/MusicFrame path or Hikari turn fusion. Full details and
limits: `docs/research/sensory-case-simulation-audit-20261024.md`.

25Oct direct Qwen3-Omni experiment used `Qwen3-Omni-30B-A3B-Instruct Q4_K_M` for brain/video/audio descriptions; Hikari was not part of that profile, and OmniVoice remained the TTS. The observability-only eight-hour soak ended normally after 960 samples / 28,800.3 seconds. A later audit found visual freshness only 77.6%, age p95 9.58s over 906 measured ages / max39.41s, a 23.5-minute stale run, and two outage windows. Its JSONL did not record successful Qwen audio-description count/age, so loopback availability cannot be treated as evidence of continuous audio analysis. This is duration evidence, not integrated acceptance. [Recomputed audit](research/qwen-fullstack-soak-audit-20261028.md).

Before the next run, restart Qwen with one slot and exact 12,288 context; prove real tokenized full-prompt fit and output reserve before any CPU/GPU comparison. The old three-slot 8K proposal is invalid because a full JAWL prompt previously reached 12,310 tokens. Then run matched serial GPU-vs-CPU turns and the 30–60min sensory/user-flow acceptance before a failure-injected 8h integrated soak. Detailed sequence and historical evidence are in `runtime/active-goal-addendum-20261025.md`.

The five-clip direct-Qwen quality matrix, human-labeling requirements, and claim-level scorecard are specified in `docs/research/qwen3-omni-realclip-scorecard-20261025.md`. Existing audio labels are provisional, so audio semantics and cross-modal accuracy remain unscored until human annotation is complete.

For the post-soak 30–60-minute run, treat freshness as a continuity gate, not a point-in-time health check: require at least 95% fresh visual observations, age p95 ≤3s, and no stale gap longer than 5s; report capture-to-submit and submit-to-delivery latency separately. Track the Qwen audio lane independently (successful descriptions, errors, silence skips, last-result age/freshness and p95 latency); `ambient_audio_running=true` alone proves device/service availability, not that audio was described. Label speech, music-only, speech+music, game/SFX, transitions, silence and noise against human-reviewed ground truth. Score transcript WER/CER only where a reference exists, and score audio claims for supported/unsupported events and correct abstention on silence/noise. Do not count lyrics, genre, mood or narrative as accepted without matching reference labels. Include source loss/recovery and Pause/Stop, and prove stale audio is not replayed into a later turn. Keep CPU/RSS and both GPU memory readings alongside quality and freshness.

29Oct exploratory speech/music overlap probe: six FMA track openings mixed in memory
with repeated local Tera TTS speech at music-to-speech RMS ratios −12/−8/−4/0 dB.
YAMNet CPU music detections were 2/6, 2/6, 3/6 and 4/6 respectively; a matched
music-only baseline detected 4/6, and speech-only abstained. Track identities
changed between baseline and mixed conditions. This small synthetic set is not
acceptance, but it confirms the need for labeled speech+music/SNR cases; the
production threshold stays unchanged. See
`docs/research/audio-speech-music-overlap-20261029.md`.

29Oct follow-up YAMNet subthreshold Music candidate screen (CPU, one thread):
zero weak candidates on 181 source-disjoint ESC-10 non-music clips, three
spoken-query fixtures, and four synthetic speech/noise controls. On 54 in-memory
speech/music mixtures (three speech fixtures, six artist-disjoint FMA tracks,
three SNRs), 11 fell into the weak-candidate lane and 34 passed the confirmed
music gate; 18 FMA four-second positive openings produced 16 confirmed, one
candidate, one abstention. Raw scores are uncalibrated and the clips were not
human-labeled, so this is a screening result only. Five real-media excerpts
produced four confirmed music results and one weak anime candidate. No live
loopback acceptance.
Artifact and limits: `runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json`;
`docs/research/audio-speech-music-overlap-20261029.md`.

29Oct weak-music routing follow-up: YAMNet’s confirmed music gate remains 0.35 plus the existing window quorum. Raw Music max ≥0.20 is routed separately as an unverified/uncalibrated music-like-or-tonal hypothesis with 12s TTL; it is excluded from confirmed music memory. Focused unit suites verify gate preservation and delivery to the brain packet. Source-disjoint real-negative evaluation of the candidate cutoff remains OPEN.

The VA hypothesis text also includes YAMNet's raw Music maximum and hit/total
windows, explicitly labeled as a non-probability, so the brain can reason about
recurrence without treating the raw score as confidence. Focused bridge and
packet tests verify these details survive delivery.
