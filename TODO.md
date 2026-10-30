# Единственная очередь — ежедневный компаньон

21 октября 2026. Статусы: [ ] не принято, [~] частично, [x] подтверждено.
[План](docs/DAILY_PLAN.md) · [приёмка](docs/DAILY_ACCEPTANCE.md) · [факты](docs/STATE.md).
Старый полный TODO сохранён в архиве; отложенные требования — [BACKLOG](docs/BACKLOG.md).

LFM3-Audio-2B is an audio-only candidate, not approved for daily use. Upstream
llama.cpp support merged 2026-10-27; the isolated CPU-only build exists, but
the GGUF probe is still pending download/inference and Russian support is
unverified. Next gate: isolated Q4 comparison on labeled clips with latency,
RSS and grounding scores: [research](docs/research/lfm3-audio-cpu-candidate-20261029.md).

## D0 — подготовка новой ветки

29Oct production audio bridge replay: a paced 10.01s local song completed through
GigaAM + EG2 + YAMNet + in-memory ambient memory + PerceptionFusion. A follow-up
trailer + song replay round-tripped actual `speech`, `music`, and `audio_candidates`
through the VA packet; all were fresh. EG2 abstained, transcript accuracy was not
scored, and no raw audio was persisted. Live loopback, shared-load freshness and
brain-turn uptake remain OPEN: [report](docs/research/ambient-audio-bridge-paced-replay-20261029.md).

Текущая проверка 29Oct: [ReAct/VA](docs/research/react-perception-audit-20261029.md).
Native canary подтверждает Goal → heartbeat → проверенный результат. Остаются
живое выполнение большого поручения, caching relay и отдельная проверка аудио
при наличии samples; устранение 18K-обрезки само по себе их не закрывает.

- [ ] ADR-048 deployment parity: новый чистый daily launch всё ещё читает
  `local-hikari` / `local-bonsai2` и visual EG2 из legacy manifest/wrapper.
  Поднять/проверить профиль Gemini 3.8 Flash relay + Qwen3.5-0.8B CPU,
  сохранив GigaAM, EG2, YAMNet, MiniLM и OmniVoice; отдельно пройти live
  audio/video acceptance прежде чем считать model lanes принятыми.

29Oct mic backpressure: исправлено выключение capture при заполнении шести
audio-запросов; PCM буферизуется и дренируется под прежним turn id. 125/125
затронутых Node tests PASS. Физический/live-ASR прогон после исправления открыт:
[отчёт](docs/research/mic-backpressure-audit-20261029.md).

29Oct ambient freshness: loopback capture timestamps now travel through ASR and
soundscape segment queues; worker wait no longer makes old audio look fresh.
Segmenter 6/6 + ambient audio 31/31 PASS. Live CPU-load freshness still open:
[report](docs/research/audio-capture-time-provenance-20261029.md).

29Oct audio-channel isolation: YAMNet presence and caption-model descriptions no
longer overwrite the same `music` key. Independent `audio_description` and ASR
channels keep provenance; newer non-music segments invalidate stale captions,
while out-of-order invalidation cannot stale newer evidence. Focused gate 54/54;
real loopback quality/load acceptance remains open:
[report](docs/research/audio-description-channel-20261029.md).

29Oct self-TTS loopback: while the playback marker is active, ambient capture now
routes only to the independent YAMNet lane; GigaAM/VoiceMem ASR and EG2 caption
are suppressed, so the companion does not transcribe its own voice and external
music can still be detected. Focused unit regression passes. A 4s in-memory
Tera-over-Aqua mix, paced in eight real-time chunks through the production bridge,
was detected as music on 2/3 YAMNet CPU windows; ASR was called 0 times, with no
drops/errors/stale results. This directly exercised the marker and model path,
but not live TTS playback/WASAPI. Live mixed audio during TTS and sound-event false
positives remain open:
[session audit](docs/research/live-session-audit-20261029.md).

29Oct audio live cost: active EG2 had no usable grounded music text; fast-path
genre top-3 matched the FMA catalog proxy in 11/18 clips only. Candidate rankings
now reach VA only with overlapping positive YAMNet evidence and remain unverified.
The live PCM path uses one shared full-clip embedding; full temporal windows
remain available offline. YAMNet cutoff 0.35 preserved 18/18 FMA positives and
rejected the two-tone false music/tag control; three other synthetic controls
abstained. Saved 5.99s WAV five-replay latency p50 was 304ms, max 424ms (4
intra-op threads; 969ms process CPU p50). Five related audio suites: 86 passed,
1 skipped. Real speech/noise controls, loopback and shared-load acceptance remain
open: [report](docs/research/audio-description-channel-20261029.md).

29Oct brain handoff audit found `audio_description` and `audio_candidates` were
missing from the VA packet allowlist. Added both and covered the combined
screen/OCR/ASR/audio/music/YAMNet payload through actual web turn enrichment:
packet 9/9, web 85/85, native 17/17, fusion 23/23, ambient audio 32/32,
YAMNet 10/10. Live audio delivery and real-model uptake remain open:
[handoff report](docs/research/va-audio-channel-handoff-20261029.md).

29Oct real-content follow-up: CPU replay on five 10s trailer/anime/game/coding/song
clips showed YAMNet music presence in 4/10, 1/10, 10/10, 10/10, 10/10 windows;
EG2 marked speech and music likely together on every clip and returned competing,
unverified genre/mood candidates (about 1.14s wall per 10s clip at one thread).
GigaAM was nonempty on two clips, but transcript correctness was not scored.
The active audio path can keep ASR and music presence separate; it still lacks a
grounded SFX/style description, especially for action-heavy anime. Keep this open;
research a separate YAMNet sound-event candidate lane against source-disjoint
speech/noise/music/SFX before exposing tags as facts:
[real-content replay](docs/research/realclip-audio-describer-20261029.md).

29Oct ASR fixture gate: the live synthetic harness now scores known speech against
the source transcript (WER ≤0.20) and requires abstention on pure-noise input.
Current GigaAM CPU replay passed all 9 speech variants, correctly retained both
consecutive phrases, and abstained on noise-only. A separate Russian SAPI prompt
with its recorded reference also scored WER 0.000; YAMNet stayed unknown with a
maximum Music score of 0.0002 on its six windows. Faint/SNR0 cases remain tolerated
controls rather than accuracy claims. This improves fixture acceptance only;
independently recorded Russian speech, mixed external media, and live brain uptake
remain open. A known local Tera TTS WAV (2.76 s) also passed the YAMNet negative
control (`unknown`, 0/2 music windows, max Music score 0.0001, no event candidates);
real mixed loopback during JAWL speech remains open.

29Oct follow-up: a narrow YAMNet `audio_event_candidates` lane now reaches the
brain packet separately from music and ASR. On 181 source-deduplicated clips
from three ESC-10 folds, the tuned specific-label lane had 171/189 emitted tags
match the clip class (90.5%); 121/181 clips got an exact category candidate.
An untouched fold-3 validation gave 58/64 exact labels and 40/65 covered clips.
The music gate fired on 0/181 non-music clips. Tags remain unverified; the
corpus does not establish performance on mixed game/music/speech audio. Silence/
noise controls and live brain uptake remain open:
[YAMNet SFX lane](docs/research/yamnet-sound-event-candidates-20261029.md).

29Oct scalar WASAPI route check: default output resolved to NVIDIA DigitalOutput
and opened at 48kHz stereo; the idle 10s sample had zero chunks/callbacks and no
errors, with PCM discarded. This confirms device selection/open/close, not live
signal. JAWL/Companion endpoints were down during this check; live sensor and
brain-uptake acceptance remain open.

29Oct visual freshness: scene-invalidated captions leave current-screen and stay
only in the short event history; delayed Qwen captions enter history only inside
its TTL. Qwen sensor 18/18 + fusion 16/16 + now-TTL 2/2 PASS. Live scene-change
load acceptance remains open: [report](docs/research/visual-stale-context-20261029.md).

29Oct visual archive: late/scene-mismatched captions now persist in the one-hour
and weekly text-only history without duplicating fresh caption records. Combined
fusion/Qwen/history/TTL gate: 41 passed. Follow-up compaction now preserves first,
last and temporally spread salient moments; the rolling-hour prompt budget samples
middle events and orders late results by capture time. Seven history tests pass,
including 20-scene flush/reopen and dense 60-event context. Integrated profile
restart and live recall remain open:
[report](docs/research/visual-history-archive-20261029.md).

29Oct OCR handoff: Qwen visual capture now requests Windows OCR at startup, after
visual dirtiness, and on the static interval (not on every 200ms image poll).
OCR text is a separate redaction-filtered, 5s-current channel in the VA packet;
screen changes invalidate the prior OCR just like the prior caption. Adapter,
sensor, fusion, packet, native-context and web gate: 163 passed + 33 subtests.
The live profile must use `--screen-ocr`; adapter-to-brain handoff passed once
on display 0 with the real Windows OCR provider and a stub Qwen client. Full
live CPU Qwen+OCR→VA-packet smoke also passed once on display 0, with 11
captures, one delivery, and zero capture errors. Caption age was 6.25s and small
text remained unreliable; this does not accept scene accuracy or full-profile
uptake. Sustained live-profile acceptance remains open:
[OCR integration](docs/research/qwen-ocr-channel-20261029.md) ·
[CPU smoke](docs/research/qwen-screen-ocr-cpu-smoke-20261029.md).
Selecting `-VisualDescriber qwen` now enables its capture source without also
starting the legacy ScreenWatch worker; `-EnableScreenOcr` adds OCR. Invalid
OCR-only launch configuration is rejected instead of silently omitting it.

- [x] Согласовать два Python launcher gate расхождения: llama.cpp test fixture
  теперь задаёт пустые Transformers-поля, профильный тест проверяет текущий
  `$nativeProfileArgs` + splatting. Оба точечных теста PASS; полную Python gate
  после правок не перезапускали, исходная 29Oct gate остаётся не PASS. Шесть
  Node voice-lifecycle отказов закрыты отдельно: 125/125.
- [ ] Физическое audio loopback после восстановления профиля и full integrated
  sensory acceptance остаются открытыми; подробности в отчёте ReAct/VA.
- [ ] При следующем штатном рестарте Companion применить уточнённый статус
  invalidated/fresh; наблюдение сохраняется с возрастом. Мозг с capacity fix уже
  перезапущен отдельно, активная пользовательская Goal сохранена.

- [x] D0-01: создать dev/daily-companion-20261014 без reset/массового commit.
- [x] D0-02: архивировать старые планы/историю, проверить сохранность и ссылки;
  старые скрипты переносить только после проверки зависимостей.
- [x] D0-03: одна короткая очередь, текущий статус и сценарий ежедневной приёмки.
- [x] D0-04: зарегистрировать новый tool goal после подготовки; если старый
  незавершённый goal мешает, явно сообщить ограничение, не подделывать completion.
  14Oct: создание было отклонено старым paused goal. 15Oct: при переносе
  сессии в Codex tool goal зарегистрирован, status=active; прежняя история сохранена.

## D1 — один надёжный ответ (первый runtime-срез)

- [x] D1-01: ordinary и supervised запускают owned brain entrypoint.
  15Oct: actual brain PID/create_time/core hooks/source SHA проверены в exact
  launcher Job с Hikari; оба режима завершили native text20/20. Atomic receipt
  без secrets/thoughts; порты/markers очищены, supervised desired_state=stopped.
  Pinned snapshot неизменен. Receipts r5/r6 и checkpoint — в STATE.
- [~] D1-02: terminal final/error и no-thought-speech guards проверены
  focused tests и native text серией. Historical connected synthetic-WAV20/20
  acceptance passed; current-profile provider-fault/recovery and fresh 20-turn
  connected-voice acceptance remain open.
  не озвучивать thoughts; harness прекращает ожидание TTS при terminal error.
  15Oct: native text final/error подтверждены; повтор terminal action внутри
  batch подавляется до history/SSE. Native provider loss даёт один turn.error,
  восстановление — один ответ; это не заменяет current-profile connected-voice
  provider-fault/recovery и свежую 20-turn серию (оба остаются OPEN).
  18Oct: причина live Empty actions закрыта: enable_thinking=false +
  actions.minItems grammar + action_repair хук. Два живых хода OK
  (11.0с/6.6с, terminal Success, thoughts не озвучены). Серия/ошибки OPEN.
- [~] D1-03: серия text/voice с текущими моделями без исчезновения ответа,
  reconnect/error/retry без двойной доставки и слепого повтора действий.
  15Oct:3/3 real-model WAV→/app→JAWL→OmniVoice хода завершены полностью;
  streaming draft3/3, каждый response body EOF, non-silent playback до конца.
  Native HTTP/SSE20/20 отдельно PASS в ordinary и supervised: exact turn_id,
  cancel/reconnect, нет двух terminal events одного хода. Ordinary provider
  loss/recovery PASS.16Oct ordinary connected WAV voice20/20 PASS: real ASR/
  brain/TTS и /app, drafts20/20, body EOF/full playback, exact Job/ports cleanup.
  Три фразы по кругу; владелец сообщил, что ранее проверил Fifine и доволен
  результатом — повторная физическая проверка не нужна. Историческая synthetic
  WAV20/20 приёмка остаётся PASS; current-profile voice provider error/recovery
  и свежая 20-turn серия остаются OPEN.
  18Oct: живые text-ходы восстановлены после фиксов; серия20 text 20/20 OK
  (p50=5.33с/p95=12.1с) и WAV-voice серия 5/5 OK (GigaAM точен, end→reply
  p50=5.16с, runtime/live-*series*.json). Владелец ранее подтвердил Fifine как
  удовлетворительный; повтор не нужен. Историческая synthetic WAV20/20 остаётся
  PASS; current-profile серия20 voice и provider error/recovery остаются OPEN.

## D2 — быстрый русский разговор

- [~] D2-01: capture/gate/partials → JAWL → progressive TTS уже реализованы;
  измерить конец речи→первый звук по стадиям, устранить конкретные задержки
  (включая `Stream-Before-Close` выдергивание речи из JSON до закрытия `}` и
  `Speech-First` порядок полей без ожидания длинных `thoughts`).
  Цель обычных тёплых реплик1–3с; публикация p50/p95 и ошибок, не обещание.
  15Oct новый voice прогон: dispatch→WebAudio first start≈10.272/9.466/11.373с,
  sample3; это не измерение физического конца речи. Native LLM2.8–4.8с/step,
  после voice/end response ещё1.25–2.54с до звука. До цели1–3с далеко.
  16Oct voice series20: dispatch→first WebAudio p50/p95=8.338/11.964с,
  min/max6.377/13.286с. Это endpoint proxy, не physical speech-end;
  first turn отдельно, остальные19 не20 warm sample. Цель1–3с не достигнута.
  16Oct stage audit:22 LLM calls на20 ходов; LLM total p50=6.226с,
  ASR/reset/admission HTTP residual0.384с. Cached tokens8017 на всех22 calls;
  checkpoint spacing1024 вместо8192 — pending benchmark, без runtime change.
  Opt-in CLI candidate подготовлен в отдельном worktree:13 focused/4 subtests
  и CodeSee validator PASS, model/GPU/window прежние; real benchmark OPEN.
  A/B/B/A runner с numeric timings и exact Job RSS подготовлен:30 focused/
  54 subtests +actual native bootstrap PASS без модели, не runtime promotion.
  Новый native text20 на режим: ordinary p50/p95=3.596/4.608с,
  supervised=3.584/6.939с; max7.459с. Это dispatch→terminal без ASR/TTS.
  18Oct после thinking-off/minItems фиксов: text серия20 20/20, p50=5.33с
  (тёплые ~5с — включает полный native JSON-конверт с delivery, тяжелее
  старого native text20); voice end→reply p50=5.16с; TTS first-chunk 1.19с.
  Диспетч→текст теперь стабилен; полный voice-end→first-audio ≈5.2+1.2с —
  до цели1–3с нужен Stream-Before-Close/Speech-First (следующий срез).
  20Oct live повторно: text20/20 без error-envelope, warm p50=5.25с,
  p95=30.71с из-за холодного первого хода31.78с; WAV-voice5/5, ASR точен,
  end→reply p50=5.39с (это не замер до первого звука). Fast Lane отдельно
  измерил dispatch→first-audio 2.47–2.55с warm / 3.39с cold; speech-end→first-
  audio для этого прогона не измерялся, поэтому D2-01 остаётся OPEN с явным
  endpoint-разделением.
- [~] D2-02: простой разговор без ненужных tool loops (`Single-Step Fast-Exit`
  в `ReactLoop`, если вызван только речевой ответ без `memory/hostos/terminal`);
  explicit goal сохраняет полноценный агентный арсенал/reasoning и краткие голосовые checkpoints.
  18Oct: native turn context добавляет fast hint только для conversational turns; native delivery guard подавляет лишний terminal completion; focused tests green. Live 20-turn plain-chat timing still open.
- [~] D2-03: gate/тихая речь и паузы2–3слова/с; не режет начало/конец.
  18Oct: streaming capture tests 31 passed; voice capture lease tests green.
  Владелец ранее проверил Fifine и доволен; физический повтор не запрашивается.
  Новые gate/тихая речь edge cases остаются OPEN только если не покрыты тестами.
- [~] D2-04: надёжный Stop/перезапуск речи/нет stale audio; разговор с наушниками
  первым, acoustic barge-in следующим. Full duplex не blocker первой версии.
  15Oct: исправлены выключенная ветка smart-barge-in и RU word boundaries.
  Поддакивание подтверждается canonical ASR без нового JAWL turn; паузы bounded,
  отмена привязана к playback owner. 36 Node +18 Python PASS; владелец ранее
  подтвердил Fifine как удовлетворительный — физическую проверку не повторять.
- [~] D2-05: при ошибке сохранять текст и понятное состояние; речь Stop не теряет goal.
  18Oct: native delivery guard emits bounded turn.error and preserves goal state; focused tests green. Live provider fault/restart acceptance still open.

## D3 — персонаж постоянно рядом («Окно-Хамелеон», можно параллельно D2)

- [x] D3-01: единое окно `desktop/app.html` в режиме «Хамелеон» (Compact HUD `360×540` поверх окон `Always-on-Top` ↔ выдвижная Studio Drawer `1060×720` с настройками всего фреймворка по клику на ⚙️ и IPC `jawl-window-mode`) реализовано и проверено unit-тестами. 17Oct: добавлены кнопки DND (`🔕`) и Click-through (`👻`) в HUD-dock, IPC `jawl-window-mode` расширен параметром `clickThrough` с `setIgnoreMouseEvents`; hover-логика для временного разрешения кликов при click-through. 18Oct: добавлено сохранение/восстановление позиции окна и режима `compact` в Electron userData; восстановление при запуске; multi-monitor валидация позиции при восстановлении; глобальный хоткей `Ctrl+Shift+G` для выхода из click-through.
- [~] D3-02: текст над головой из того же ответа, парящий мини-док (`🎙`, `⏹`, `👁`, `🔕`, `👻`, `📌`, `⚙️`) прямо под VRM без панели диагностики, сгруппированные по органам чувств настройки JAWL/VoiceMem/Companion в одном месте реализованы; остаётся live приёмка с реальным стеком. 17Oct: кнопки DND и Click-through подключены к `/api/attention` и `/api/ambient-memory/config`; статус синхронизирован с сервером.
  24Oct: добавлен компактный HUD состояния mic/screen/loopback и подробная карточка источников в System; OBS overlay скрывается. Live-интеграция и проверка размеров в запущенном окне остаются открыты.
  24Oct UX follow-up: settings toggles теперь клавиатурно доступны и именованы; ошибка config-hub локализована и получила повтор загрузки. UI E2E: все 6 разделов на 9 размерах, клавиатура и sensor layout PASS. Живая Electron/real-service UX приёмка всё ещё OPEN. Аудит: `docs/research/ui-ux-review-20261024.md`.
  25Oct UX follow-up: карточка сервисов больше не обещает, что «всё работает», когда отдельные службы могут быть недоступны; тест доступности 4/4 и браузерный E2E с 9 viewport прошли. Это mock-brain проверка; живая Qwen/Electron приёмка, screen-reader и длительная работа остаются OPEN.
- [x] D3-03: текущий VRM idle/listen/think/speak (включая читаемую позу `thinking/working` и обогащённый липсинк `aa/oh/ee`) связаны с одним turn; единое ядро `app-scene.js` (включая `?mode=obs`). Не делать новый арт условием запуска. 17Oct: добавлена поза `thinking/working` (upperChest lean + forearm/hand pose) в `avatar-motion.js` и `app-scene.js`; липсинк `aa/oh/ee` в `applyLipSync`.

## D4 — видеть, слышать и уместно проявлять инициативу

- [ ] D4-live-29Oct: закрыть подтверждённые дефекты текущего Hikari-сеанса:
  self-TTS→loopback echo; terminal context_limit=10 при 64K; старый основной
  caption поверх новых сцен;
  шесть attention intents при нуле proactive delivery. Отдельно — mic
  backpressure recovery и живые диагностические логи. [Факты и порядок](docs/research/live-session-audit-20261029.md).
  Follow-up 29Oct: self-TTS suppression подключён к playback lifecycle для
  streamed и обычной речи; focused desktop voice lifecycle 30/30 PASS. Это
  закрывает разрыв в коде, но живой loopback/runtime после рестарта ещё не принят.
  Follow-up: VA теперь сохраняет ASR до 2400 и audio description до 1600
  символов в отдельных каналах вместо общей 1200/600 обрезки. Fusion/packet/
  native-context/web gate: 129 passed + 33 subtests; live prompt readback открыт.
  После добавления per-channel regression семь смежных audio/fusion/packet/
  native-context suites: 111 passed, 1 skipped.

- [~] D4-01: screen/system-audio sources после настройки; bounded recent context,
  timestamps/TTL, ошибки и pause видны; фон уступает разговору/игре. 17Oct: ambient pause/resume (audio+memory+sensory ingest), DND button pauses ambient capture, paused state in sensor status, ResourceGovernor yields_to_game; tests green.
  18Oct live: describe-displays 0.7с (2 дисплея, EG2-теги в perception_fusion);
  ambient-audio теперь пробрасывается лаунчером (-EnableAmbientAudio →
  --ambient-audio --ambient-memory), venv получил PyAudioWPatch; live start OK
  (backend running, NVIDIA loopback, 48к/2ch).
  20Oct live: start/pause/resume/stop PASS на pyaudiowpatch, device
  «Динамики (Game-Audeze Maxwell) [Loopback]»,48к/2ch; тот запуск был при
  тишине и не подтвердил передачу сигнала. Это историческое ограничение
  устранено для текущего NVIDIA endpoint ниже.
  24Oct: shell status теперь безопасно публикует microphone lease, loopback running/error и текущее Qwen freshness состояние; UI показывает paused/off/stale/error отдельно. Реальная совместная проверка с аудио во время 30–60min acceptance остаётся открытой.
  24Oct follow-up: финальный loopback ASR теперь попадает в `PerceptionFusion`
  только после retention/privacy gate с provenance и NOW TTL 20с; privacy-
  suppressed текст не попадает туда или в `stop/flush`. Разрешён только точный
  tentative rhythm cue (`sound`, confidence=0, verified=false, без tags/mood),
  TTL 5с; при наличии ASR текста все звуковые метки подавляются как неподтверждённый
  фон речи. `pause` теперь останавливает capture и отменяет/очищает bridge очередь,
  инвалидируя старый audio context; `resume` запускает bridge до capture. Сквозные
  После дополнительной сериализации service pause/resume, очистки streaming
  audio tap/partial queue, suppression late model results и атомарной
  transcript→fusion publication: combined contract suite 143 passed + 29
  subtests; отдельный lifecycle набор 34 passed; py_compile и scoped diff-check
  проходят. Это подтверждает fake/test lifecycle и privacy plumbing, но не live
  понимание кино/игр или качество модели. 24Oct: пользователь подтвердил
  реальный выход DigitalOutput NVIDIA; read-only WASAPI enumeration нашла
  default output index 27 и точный loopback index 38 (48 kHz stereo). Selector
  теперь выбирает точное уникальное имя, сообщает device/host API index и
  отказывает при неоднозначности; system_audio 9/9, ambient_audio 24/24,
  web 80/80. Выходы NVIDIA различаются: index 38 (имя с префиксом `2-`)
  остаётся без сигнала, index 39 (`DigitalOutput (NVIDIA High Definition Audio)`)
  выдаёт поток. 24Oct live: изолированный daily profile выбрал loopback 39,
  принял 3,806 чанков без потерь/ошибок; GigaAM записал точную тестовую фразу
  «Какой сегодня статус моего проекта?» в ambient memory. Затем launcher исправлен:
  `-NoLocalAudio -EnableAmbientAudio` теперь подключает VoiceMem+GigaAM без TTS.
  Headless health показал `tts=not_configured`; два дополнительных WAV-теста оба
  распознаны дословно («Запомни… короткие ответы», «Сможешь проверить тестовый
  файл…»), zero drops/errors. PCM не сохранялся; микрофон не открывался.
  Отчёт: `runtime/qa-ambient-asr-2phrase-20261024.json`. Подтверждены loopback
  routing и три короткие известные фразы, но не качество длинного/смешанного
  аудио; совместная 30–60min приёмка остаётся открытой.
  24Oct music follow-up: локальная CPU-only оценка YAMNet + HuBERT genre INT8
  + MERT music-affect ONNX. YAMNet отличил музыку (Bach 0.914, sax 0.755) от
  речи (Speech 0.950–0.994), тишины (Silence 1.0) и шума; выдаёт широкие
  теги инструмента. MERT 15s p50 1.874s, но на речи/тишине/шуме тоже даёт
  валентность/возбуждение — запускать только после устойчивого YAMNet music gate.
  HuBERT на 5s CPU p50 2.059s уверенно ошибся на речи (hiphop), тишине
  (hiphop) и шуме (metal), поэтому не подключать в always-on и не публиковать
  жанр из одного результата. Ничего не подключалось в daily profile.
  Отчёт: `docs/research/music-sensory-candidate-evaluation-20261024.md`, сырые
  оценки: `runtime/audio-path-replay/out/music-model-candidate-probe-20261024.json`.
  29Oct: принятой дорожки интонации/эмоции речи нет; музыкальный mood не
  заменяет affect говорящего. Aniemore Russian XLS-R int4 CPU probe отвергнут
  для real-time: 16–24s на 6.5–10s WAV, peak RSS 1.69 GiB; near-certain
  enthusiasm на обоих neutral instruction controls. Подробности и ограничения:
  `docs/research/russian-speech-emotion-cpu-candidate-20261029.md`.
  Acceptance: `docs/DAILY_ACCEPTANCE.md` и
  `docs/research/russian-speech-emotion-cpu-candidate-20261029.md`.
  Уточнение для смешанного аудио: на synthetic speech+chord YAMNet вывел Music
  0.334, но Speech отсутствовал в top-5. ASR не отключает независимый YAMNet,
  однако EG2 safe-claim отбрасывает детальный music claim при наличии transcript,
  а EG2 candidates доходят до VA только при positive YAMNet overlap. Поэтому
  музыка ниже порога может отсутствовать в brain context вместе с EG2 claims.
  В 2s/1s-hop окнах Bach держал Music 0.90–0.99 после частичного первого
  окна, sax 0.52–0.90, а synthetic mix давал Music 0.24–0.38 / Speech
  0.003–0.018. Один порог 0.5 пропустит этот mix, но снижать его пока нельзя
  без source-disjoint реальных негативных примеров.
  Следующий шаг — независимые ASR/soundscape tracks с отдельными timestamp и
  confidence, проверка на нескольких SNR и новых реальных клипах; пороги и
  production-проводку пока не менять.
  29Oct follow-up: one in-memory 4s Tera-over-FMA SNR scout (six artist-distinct
  openings) found YAMNet music at 2/6 for −12/−8 dB, 3/6 at −4 dB, 4/6 at 0 dB;
  matched music-only baseline was 4/6 but on a different set. Speech-only stayed
  unknown. Synthetic repeated TTS and short track openings make this exploratory;
  cutoff/production behavior unchanged. See
  `docs/research/audio-speech-music-overlap-20261029.md`.
  24Oct YAMNet broad-style probe на тех же 18 individually licensed,
  artist-disjoint FMA tracks: 12/18 (66.7%), тот же aggregate, что CLAP;
  Classical 3/3, Electronic 2/3, Folk 1/3, Hip-Hop 1/3, Jazz 2/3, Rock 3/3.
  Ошибки иные; median top-style margin 0.02098, поэтому genre/mood нельзя
  подавать как факт. Модель очень лёгкая (~75.2 MiB isolated RSS; 8s crop
  p50/p95 21.80/23.16ms), годится только для экспериментальных tags/abstention.
  Acceptance расширена на external-media ASR, instrument/timbre, vocals,
  tempo/energy, soundtrack transitions и grounded short description; labels
  остаются открытыми до listener-verified source-disjoint набора. Скрипт:
  `scripts/probe_yamnet_fma_styles.py`; артефакт и детали — в music research.
- [~] D4-02: JAWL получает свежий экран по запросу и изменениям; описывает
  реальные RU окна. Не отправлять каждый кадр без необходимости. 18Oct: VisionLookService dedup/cooldown, ScreenDeltaWatcher backoff, /api/vision/look, UIA context, perception fusion; tests vision/presence/screen_adapter/e2e зелёные.
  18Oct live: /api/vision/look 4.6с с реальным VLM-описанием окна;
  голосовой вопрос «что на экране» → JAWL screen.observe+VLM ответ
  (live-voice-screen-question.json, end→reply 20.2с). Vision требует
  mmproj при запуске brain (llama-server флаг). 24Oct: Qwen co-watch pilot
  подтверждает доставку свежего caption/provenance в brain-bound prompt, но
  новый replay выявил один прямой конфликт с игровой сценой и одну выдуманную
  деталь на caption Земли; один abstain был уместным. Внешний Companion
  `session_id` не сбрасывает native JAWL/provider context. Это grounding fail,
  а не основание заменить Qwen. Нужен integrated continuous-context replay с
  exact prompt/history, scene cuts, false premise и user correction.
   25Oct: экспериментальный профиль использует Qwen3-Omni-30B-A3B-Instruct Q4_K_M как brain endpoint (`local-qwen3-omni`), плюс Qwen visual/audio describers; Hikari не используется. 8h observability-only soak завершён штатно: 960 samples. Аудит: visual fresh 77.6%, age p95 9.58s/max39.41s (906 measured ages), stale gap 23.5min, два outage-окна, minimum free RAM 0.18GiB; per-sample Qwen audio-description success не логировался. Это не 24/7 acceptance. Отчёт: `docs/research/qwen-fullstack-soak-audit-20261028.md`; старые acceleration results: `runtime/qwen3-omni-direct-20261024/ACCELERATION-RESEARCH-20261025.md`.
  25Oct follow-up: future-launch defaults were changed to 4s static/periodic after old 5/10s cadence showed caption gaps. The completed soak used its already-captured old arguments; post-fix freshness and CPU/GPU impact still require a fresh managed run. Qwen sensor tests 16/16 and launcher tests 18/18 passed at that time.

  25Oct shared-slot smoke: concurrent tiny text/audio requests succeeded on the one-slot Qwen endpoint in 0.890s wall (text 0.885s, audio 0.747s). The post-check kept brain/TTS ready and queues empty. This does not measure a full JAWL user turn under sensory contention; exact queue wait and long-prompt latency remain open.

- [~] D4-03: системная речь отделена от пользователя/собственной TTS,
  временная память с provenance; перезапуск/TTL/очистка. 18Oct: ambient audio ingests system_audio, playback suppression фильтрует own TTS, TTS endpoints активируют suppression с TTL, source_app=system_audio; tests ambient_audio/web зелёные.
- [~] D4-04: инициативный комментарий через общий Heartbeat/attention,
  cooldown/DND/приоритет пользователя, без двойного разговора. 18Oct: AttentionPresence tests 13 passed; web attention tests green; live initiative acceptance remains.
- [~] D4-05: совместное прослушивание: захват не ломает голос; metadata/речь
  можно использовать честно. 24Oct: YAMNet CPU lane подключён рядом с GigaAM;
  музыка и ASR хранятся независимо, музыка не пропадает под речью, устойчивый
  инструментальный тег выдаётся только при повторяемом сигнале. Это пока
  soundscape/event-теги, не распознавание жанра или свободное музыкальное
  описание. Требование приёмки — внешний звук игр/видео целиком: ASR речи плюс
  отдельные музыкальные признаки (наличие/переходы, стиль и жанровая семья,
  инструменты/тембр, вокал/инструментальность, энергия/темп) и короткое
  grounded-описание саундтрека. Настроение и музыкальный сюжет — только после
  проверки на человеческой разметке; на слабых/противоречивых данных abstain.
  Следующий шаг — source-labeled game/video clips, сравнение лёгкого
  zero-shot/tagging кандидата с YAMNet и оценка captioner только по запросу.
  Жанр, настроение и свободное описание остаются неподтверждёнными без этого
  gate.
  25Oct: текущая Qwen3-Omni profile config выбирает `qwen-omni` audio describer и Qwen visual sensor. Добавлены counters успешных Qwen audio descriptions/errors/skips, тип и свежесть последнего результата, p95 latency в `/api/shell/status` и строку статуса в System UI. Живой экземпляр ещё не перезапускался, его восьмичасовой soak не содержит этих метрик; после завершения прогон на реальных loopback clips остаётся открытым: музыка без речи, речь поверх музыки, слова песни и тишина; проверить latency, abstention/grounding и влияние на текущий диалог. OmniVoice оставить без изменений.
  24Oct: повторный живой capture после сообщения о включённом playback
  открыл DigitalOutput, но записал только сигнал уровня -101.5 dBFS; YAMNet
  и GigaAM корректно abstain. Отдельный 14.81s live sample ранее дал Music в
  13/13 окнах; это подтверждает присутствие на одном участке, но не стиль.
  Artist-disjoint CLAP research на 18 лицензированных FMA Medium треках получил
  только 12/18 (66.7%) по слабым catalog labels, Electronic 0/3 и Jazz 1/3;
  четыре speech/music/noise/silence controls классифицированы правильно.
  CLAP оставлен research-only; genre, instrument/timbre, vocal, energy/tempo,
  transitions and grounded description остаются незакрытыми до human-labeled
  game/video evaluation. См. `docs/research/music-sensory-candidate-evaluation-20261024.md`.
  18Oct: streaming capture tests 31 passed; voice capture lease tests green;
  live co-listening acceptance remains open.
   24Oct sensor UX: System panel now shows fresh YAMNet music/abstention, age, and pause/stale/unavailable state; renderer does not call event tags genres. Browser interaction E2E covers 9 viewports including 720×480 and 320×420 with no horizontal overflow. 24Oct follow-up: Tab/Enter navigation, Space/Enter DND and visible focus passed browser E2E; axe-core 4.14 reported zero WCAG A/AA/2.2 AA violations at 1280×720 and 360×540. This scoped automation is not a full manual WCAG audit; live profile acceptance remains open.
   24Oct style follow-up: MusicNN (3.18MB weights) ran ~23ms/4s but emitted false genre/instrument tags on speech/noise/silence and used ~770MiB process RSS; rejected for always-on. YAMNet CPU (~71MiB process RSS) detects Bach/sax music, but genre scores were weak (Bach classical .0032, sax jazz .0636); a fresh live DigitalOutput sample also had Electronic/Techno <.03. No style claim. Mood/free-form description remain open; report: `docs/research/music-perception-roadmap-20261024.md`.
   24Oct captioner follow-up: `cahya/whisper-tiny-audio-captioning-v2.0` was tested CPU/1 thread: 12s crops take 0.69–0.79s, but it gives generic Bach/sax captions, misses music under speech, and hallucinates a male voice on exact silence (RMS 0); isolated PyTorch RSS 829.9MiB. Reject for always-on/current-context description; training-audio terms remain unclear. MAGDA CLAP audio ONNX is CDN-fetched and SHA-verified; its graph needs 48kHz log-mel `[1,1,1001,64]` despite README waveform wording. One-thread 8s audio inference: p50 92ms/p95 95ms; isolated two-encoder RSS ~930MiB including runtime. The 478MiB text encoder is now complete and hash-verified. CLAP correctly retrieved the sax sample and speech/music scene, but both fixed and paraphrased prompts mislabeled the Bach excerpt as sax/jazz; style and grounded caption remain open. No daily-profile integration; see `docs/research/music-perception-roadmap-20261024.md`, `scripts/probe_clap_candidate.py`, and `scripts/probe_clap_prompt_bank.py`.
  24Oct real-clip audio replay: CPU YAMNet + GigaAM on the five existing 10s local audio cuts (Russian trailer, anime trailer, RTS, coding UI, Aqua). YAMNet saw Music >=.30 in 4/9, 1/9, 9/9, 9/9, and 9/9 rolling windows; the current 2-window gate abstains on anime and passes the other four. GigaAM returned nonempty output only on trailer and song; transcript text/raw PCM were not persisted. YAMNet top style scores stayed weak (below .081), so it supports music presence, not dependable genre or soundtrack description. Single-thread YAMNet took 25–28ms for nine windows; GigaAM 376–395ms per 10s clip. This is local replay, not live capture or source-disjoint acceptance. Artifact: `runtime/audio-path-replay/out/realclip-audio-lanes-20261024.json`; runner: `scripts/probe_realclip_audio_lanes.py`.

   26Oct semantic follow-up: EG2 теперь ранжирует положительные классы «музыка»,
   «речь преобладает», «окружение» и «речь + музыка»; вокал, ударные, бас и
   электронные тембры считаются отдельными кандидатами. L2 анализирует соседние
   окна, дешёвые DSP-признаки и отдельно фиксирует переходы; L3 сводит поддержку
   кандидатов. Кандидаты остаются uncalibrated и не ослабляют safe-claim gate;
   веса и production-пороги не менялись. На 7 доступных CLAP controls top-scene
   соответствия те же, что у старого банка; русская речь остаётся ложным
   speech+music, поэтому P0 accuracy criterion не пройден. Ручных interval labels
   в репозитории нет. Тесты: coarse-to-fine 3/3, EG2 runtime 2/2, py_compile OK.
   Stage timings разделены для embedding/L1/L2/L3; capture пока отсутствует на
   descriptor boundary. Live P2 не запускался: 503 prefetch drops, 41.8/60s и
   стабильность курсоров требуют следующего контролируемого однопоточного прогона.
   См. `docs/research/audio-coarse-to-fine-20261026.md`.
  28Oct history reliability: штатное завершение теперь flush-ит sensory history
  после остановки capture/description producers и surfaced persistence errors;
  запросы «N минут назад» получают целевое ±30s окно. Lifecycle/history/web tests
  объединённый lifecycle/history/audio/Qwen/web suite 163 passed + 33 subtests.
  Это улучшает restart/history, но не закрывает live retrieval,
  30–60min continuity или integrated 8h acceptance.
  28Oct audit correction: historical Qwen3-Omni 8h soak действительно завершился,
  но acceptance FAIL/PARTIAL: 77.6% visual freshness, p95 9.58s, stale gap 23.5min,
  two outage windows, minimum free RAM 0.18GiB, and no successful audio-description
  telemetry. Нужен новый run после managed restart/freshness fix.

## D5 — полезный агент и непрерывная память

- [x] D5-01: три настоящих поручения в тестовых окнах/браузере/файлах:
  действие → проверка результата → короткий отчёт, с уровнями native policy.
  16Oct r5: file/read/SHA, browser open и form save PASS; fresh native result
  до terminal, один POST. 21Oct r7: harness принимает
  `HostOSReader.read_file_range` как fresh read. 21Oct r11 live PASS:
  `--suite agent-work` 7/7 — file write/read с точным SHA, browser
  navigate+extract и form save (один POST), memory revision1→2, restart,
  recall revised value, sandbox denial; ports/fixture cleanup PASS.
  Startup output-budget закрыт schema-bound для `SYSTEM_CORE_START`;
  r6 chat-bound maxLength320/thinking-off/actions.minItems сохранён.
  Отчёт: `runtime/gateway-agent-work-20261021-r11.json`.
- [~] D5-02: факт → исправление → restart → recall меняет ответ той же личности;
  задачи переживают Stop речи и отказ провайдера без дубля эффекта.
  16Oct r5 real user turns: stable memory_key, revision1→2, новая brain generation,
  fresh SQLStructuredMemory.list_memories и ответ revised value PASS.
  21Oct r11: memory revision/restart/recall PASS в live agent-work. Задачи
  через Stop речи/provider fault ещё не приняты.
- [~] D5-03: эффективный уровень0–3, unattended срок и emergency Stop понятны
  в общей панели. Не вырезать инструменты/goal/swarm, расширенный UI позже. 18Oct: hostos policy/web tests 19 passed; live operator acceptance remains.

## D6 — день использования и ночь работы

- [~] D6-01: один понятный запуск/stop/restart, готовность зависимостей и ошибок,
  закрытие панели не убивает brain; явное поведение сворачивания/выхода.
  15Oct: ordinary и supervised startup/stop PASS; native lease-gated recovery
  на cheap child PASS. Tray/owner daily lifecycle и длительная модельная работа OPEN.
  16Oct: supervisor readback переведён с cmdline fallback на lock-bound PID/
  creation-time receipt.25 focused/38 subtests, новая Hikari supervised20,
  actual receipt/Job proof и cleanup PASS; full gate912/66/16/109 PASS.
  24Oct: managed tray Stop now waits for launcher acknowledgement bound to
  runtime/request ID; timeout remains visible in compact UI. Static labels for
  mic device/settings search added; desktop Node gate restored its archived
  avatar lifecycle test and includes accessibility coverage (118/118 PASS).
  24Oct follow-up: `run_local_bonsai_integrated.ps1 -StartDesktopShell` now
  starts Electron after backend health, monitors shell exit, and cleans its
  owned process tree with the profile; desktop remains opt-in for headless
  acceptance runs. PowerShell parse and launcher tests 13/13 pass. OPEN: live
  24Oct live smoke: isolated Companion reached ready, Electron remained alive,
  a matching runtime/request-ID managed-stop was acknowledged, and launcher
  cleanup closed all disposable ports with exit 0. Found and fixed inherited
  `ELECTRON_RUN_AS_NODE=1`, which had launched Electron as plain Node. Stop was
  injected into the isolated managed request file, not clicked in the UI;
  actual tray interaction and daily-profile launch remain OPEN. Report:
  `docs/research/desktop-launcher-lifecycle-smoke-20261024.md`.
- [~] D6-02: integrated 30–60 min run, then 8h full-stack soak with one controlled worker fault plus source/host interruption (target minimize/occlude/close, loopback endpoint change/loss, display sleep/return, Windows suspend/resume where practical).
  Require bounded RAM/logs/queues; no duplicate workers/actions or stale replay; honest gap/degraded state; fresh-only recovery with DND/Stop/privacy preserved.
  16Oct новый owned native soak: exact Job/creation identity sampler без cmdline/cwd,
  native Goal write/read, lease revoke, controlled provider fault/recovery и cleanup
  PASS на180с. Первый8h native soak FAIL на63.6мин:12 cycles PASS,13-й
  Goal объявил done без actions, native guard перевёл его в blocked.
  Controlled fault/recovery PASS; lease revoke/Jobs/ports cleanup PASS.
  21Oct: false-completion repair (`native_goal_completion_repair.py`) и
  actual pinned-source probe PASS (one protocol retry, ledger не изменён,
  повторный false done отклонён).
  24Oct: native-owned 8h soak PASS, 476 cycles / 0 failed; один
  intentional transport fault восстановлен. Scope: native gateway/brain/Goal/
  Companion; физический mic, screen/audio capture и полный daily runtime не
  входили. Полная интегрированная 30–60min приёмка и full-stack 8h soak остаются
  OPEN. Физическая Fifine-проверка ранее удовлетворила владельца; повтор не нужен.
  24Oct: 4h fixed 20-case local sensory simulation PASS (49 batches, 20/20 per
  batch, 0 errors, 14,411.6s). It covered local Qwen/EG2/GigaAM replay, not live
  capture, YAMNet music styles, or the daily desktop profile; full integrated
  continuity/overnight acceptance remains OPEN. Artifact:
  `runtime/sensory-case-simulation-20261024-clean.json`.
  24Oct Russian-trailer replay through QwenVisualSensor/Describer/Fusion: 10s,
  8 submits, 6 inference completions, 2 queue replacements, 5 scene changes,
  only 2 captions delivered to current context (4 older-scene results rejected),
  p50/p95 delivered age 2.68/4.28s. No model/capture errors; rapid-cut event
  continuity remained unserved. Follow-up added a bounded timestamped visual
  timeline (≤5 distinct scenes/15s), separate from the 5s current caption; late
  older-scene results enter history without entering current state or attention.
  Focused and related integration tests pass (56 passed, 1 opt-in display smoke
  skipped). Replaying the same clips through the updated window and testing
  brain answers while events are fresh remain OPEN. Physical screen, audio
  alignment, Hikari uptake and full-stack runtime remain untested here.
  Report: `docs/research/qwen-visual-trailer-adapter-replay-20261024.md`.
  24Oct telemetry readiness: the integrated launcher can now optionally write
  250ms process-tree JSONL for exact launcher PID+creation-time descendants,
  including CPU, working/private memory, threads, handles, lifecycle events and
  completeness flags. Eleven focused sampler/monitor tests and PowerShell parse
  checks pass; no integrated profile was launched. The monitor can still miss a
  child process that starts and exits wholly between samples. This improves the
  evidence for the next soak but does not close live continuity acceptance.
  28Oct audit of the completed direct Qwen3-Omni eight-hour observability soak:
  960 samples, 745/960 visual-fresh (77.6%), age p95 9.58s/max39.41s, longest
  consecutive non-fresh interval 23.5min; 23 samples lacked visual state across
  two outage windows. Brain/TTS/ambient health also had gaps; minimum free RAM
  was 0.18GiB. The log has no audio-description-success/age series. Soak duration
  completed, but freshness, outage recovery, and audio semantics did not pass.
  Full audit: `docs/research/qwen-fullstack-soak-audit-20261028.md`.
  Managed context budgets now scale down for a 12,288-token window
  (dynamic=9,000 chars) and accept exact legacy receipts for migration; 15
  focused tests pass. This code
  is not loaded into the active soak, so overflow,
  freshness and readiness recovery remain OPEN pending relaunch and retest.
- [~] D6-03: применимый major regression + DAILY_ACCEPTANCE, короткая инструкция
  владельцу и перечень известных ограничений. Это daily release, не весь production TODO. 18Oct: main pytest 1028 passed + 281 subtests; desktop node 95 passed; e2e 18 passed in batches/single runs; live DAILY_ACCEPTANCE items remain.
  16Oct новый full gate PASS:932 unittest/66 pytest/16HTTP/109Node +browser
  harnesses; queue projection checks отдельно12 focused PASS. Новый real-model WAV voice3/3 и native text20/20 обоих режимов PASS.
  DAILY_ACCEPTANCE mic/full actions/durable-task Stop/8h ещё не принята.
  Connected WAV voice20 и memory correction/restart/recall подтверждены. Исторический
  14Oct Argon heartbeat FAIL сохранён в runtime/supervised-profile-acceptance-20261014T174524Z.json.
24Oct full gate PASS after repairing corrupted Cyrillic screen-query/prompt strings:
pinned snapshot + secret scan clean; 1125 unittest, 67 pytest and 18 API/E2E tests;
  browser interaction E2E, synthetic desktop voice E2E, Node tests and git diff check
  passed. This validates the code gate, not the still-open integrated daily-profile
  30–60min run or full-stack overnight acceptance.

---

## Горизонт H1–H5 — целевая гармоничная архитектура (после базовой стабилизации D1/D2)

Подробная спецификация: [HARMONIZED_ARCHITECTURE_AND_ROADMAP.md](docs/HARMONIZED_ARCHITECTURE_AND_ROADMAP.md).

- [~] **H1 — Дефрагментация UI и VRM («Окно-Хамелеон» в стиле Project Airi / N.E.K.O.):**
  18Oct: legacy frontend/rust removed, unified desktop app.html/app.js, obs mode, motion/lipsync; desktop node 95 passed; live VRM acceptance remains.
  полный вывод из эксплуатации устаревших `frontend/index.html`, `--legacy-shell` (`avatar.html` + `avatar-scene.js`) и `rust-client/`; перевод OBS (`8766`) на единое ядро `app.html?mode=obs`; единый контроллер позы (`idle ↔ listening ↔ thinking/working ↔ speaking`) и многоканальная виземная артикуляция губ (`aa/oh/ee/ih/ou`).
- [~] **H2 — Двухскоростной контур мозга (Dual-Lane JAWL — Fast Chat + Deep Task/RE):**
  18Oct: duplex cascade heuristic + tests 9 passed/13 subtests; fast hint in turn context; live latency/task separation acceptance remains.
  разделение потоков внутри единой личности JAWL: быстрый разговорный поток (отклик 1–2 с без тяжёлых tool-loops) и асинхронный поток поручений/модинга/реверса (`HostOS`, `G:\RE`, `Ghidra`, `x64dbg`), присылающий голосовые чекпоинты в быстрый поток.
- [~] **H3 — Full-Duplex голос (`DuplexCascade` + `OmniVoice`):**
  18Oct: deterministic micro-turn controller and tests pass; full audio duplex/OmniVoice live validation remains.
  20Oct DuplexCascade 2.0 (live path): `earlySpeech` (streamed WAV before `final`) теперь считается речью ассистента, и barge-in останавливает именно её (`stopEarlySpeech(true)`, без владельца `speechPlayback`); `/api/voice/draft` принимает `assistant_speaking`/`extended_used` и возвращает `duplex_action`/`avatar_gesture` (backchannel → `nod`, interruption → `cancel_tts`); клиент берёт серверный `required_ms` как окно endpointing (1200 → 800 мс warm, 2000 мс для незаконченной мысли) и показывает `nod` только при смене жеста. Python 44 + streaming 22, JS 24+30 pass.
  21Oct per-request cancel: `speak_cancel` отменяет in-flight TTS по `request_id` (таргетное закрытие HTTP-сокета через `TTSService.cancel(request_id=...)`), поздний WAV после отмены не эмитится; `done.count` теперь кумулятивный. Python 53 focused.
  отказ от жёсткого VAD в пользу микро-ходов (`overlap_window ≈ 0.5–0.6 с`); управление очерёдностью речи через 6 спецтокенов (`<|user is talking|>`, `<|user is thinking|>`, `<|assistant_backchannel|>`, `<|user finish talking|>`, `<|user interruption|>`); мгновенный потоковый синтез микро-чанков в `OmniVoice` с клонированным голосом.
- [~] **H4 — Мультимодальная сенсорная кора на базе `EmbeddingGemma 2` (по принципу `eg2.haku.sh`):**
  18Oct: audio-visual vibe fusion, latent VRM reflex, semantic scene-change trigger, compact episodic vector memory, Russian eg2 reader, PerceptionFusion.observe_eg2 and optional composition integration; tests eg2/perception fusion 14 passed. Live multimodal validation remains.
  20Oct: DetailedSensoryDescriber (eg2_describer.py) - 3-level Coarse-to-Fine: L0 macro domain, L1 facets (style, elements, genre/mood/speech, spatial zones from 29 patch tokens), L2 grounded text (in-memory Windows OCR ru+en-US 4-130 ms, DSP: BPM/key/mode/spectral/speech-modulation). 3-ring perception snapshot (user/world/self). Integrated into PerceptionFusion and composition. Tests: 16 new + 25 existing = 41 passed. Replaces heavy VLM (4.6-20 s) with CPU pipeline (~1.2 s screen + 0.2 s audio).
  20Oct late: vision preprocessing fixed (Gemma4 axial RoPE [pos_x,pos_y] + divisible-by-3 21x30 grid -> 70 spatial tokens; correct detail margin grew from 0.0021 to ~0.24). Haku-style Scene/Character/Plot/Setting/Meme banks expanded to ~158 concepts with 0.4 MB `.npz` cache (2 ms warm init). `enrich_turn_text` now attaches fresh perception on every contextual turn, not only explicit screen words; ambient audio now runs `Eg2AudioDescriptionProvider` (genre/BPM/key/mood); `--screen-watch` can run on EG2 via `-Eg2Vision` without an external VLM. Tests: 125 passed + 29 subtests.
  20Oct live screen-watch: stack `-EnableScreenWatch -Eg2Vision` ready; watcher running, 3 SCREEN_DELTA events; `/api/vision/describe-displays` ok (2 displays, plot/OCR/zones); `/api/vision/look` ok; attention produced SPEAK_INTENT (significance 3), no VLM. Evidence: `runtime/live-eg2-screenwatch-report.json`.
- [~] **D2-01 (Speech-First / Stream-Before-Close) — серверная часть сделана:**
  20Oct: `speech_first.py` — инкрементальный извлекатель речи из *частичного* JSON-конверта
  (терпим к обрезанным escape/\\u-последовательностям, приватные поля `observation`/`reasoning`
  никогда не озвучиваются, фраза режется только по настоящей границе предложения, инвариант
  spoken+tail == финальный ответ байт-в-байт). `live_speech.py` — сессия «произношу первое
  предложение, пока остальной ответ ещё пишется»: рендер работает в отдельном потоке, TTS
  вызывается на каждую готовую фразу. WS-действия `speak_delta` / `speak_finish` /
  `speak_cancel` отдают те же NDJSON-события `audio`, которые уже умеет играть
  `desktop/speech-stream.js`. Тесты: `test_speech_first.py` (18) + `test_live_speech.py` (9) +
  WS-тест в `test_ws.py`; полный гейт **1147 passed + 281 subtests**.
  20Oct P0-связка: `native_jawl_streaming.py` — owned-хук в brain-процессе (tee на
  `_consume_stream`, принудительный `stream=True` для local json-envelope внутри
  активного correlated turn, из потока извлекаются только готовые фразы и уходят
  как `assistant.delta` с `format="speech"`; reasoning/private поля не эмитятся,
  итоговый `LLMResult` не меняется). Bootstrap реального brain-entrypoint:
  `"streaming_installed": true`. Компаньон: `jawl_terminal` отличает speech-дельты
  от display-дельт, `gateway.stream_text` пропускает их, `/api/chat/stream` кормит
  `LiveSpeechSession` и отдаёт `audio`-события до `final`. Клиент `desktop/app.js`
  играет ранние WAV сразу и не дублирует озвучку после `final`.
  **Live-замер 27B (20Oct):** `speech_delta` 15.07с, `final` 15.98с, первый
  `audio` 16.69с, 3 WAV-чанка, `speech_done` 18.79с, ошибок нет. Связка
  end-to-end работает; первый звук пока на 0.7с позже `final`, потому что первая
  фраза приходит за ~0.9с до конца хода (долгий prefill). Цель — сдвинуть первую
  фразу/звук раньше `final` через Fast-Lane Context Slimming и более ранний
  `Speech-First` порядок полей.
  **20Oct Fast Lane (готово):** на коротких разговорных ходах на проводе
  system 38168→1915 символов, user 24465→195 (остаются сама реплика + свежее
  восприятие); стабильный префикс без `turn_id` включает переиспользование
  кэша llama.cpp. Live-замер: первый `speech_delta` **1.01–1.06с** (cold 1.88),
  `final` 1.74–1.82с, первый `audio` **2.47–2.55с** (cold 3.39), 3 WAV,
  ошибок нет. Цель 1–3с для первого звука достигнута на тёплых ходах.
  Задачи с инструментами по-прежнему получают полный контекст.
  - *Zero-Decoder Visual Probe:* мгновенная классификация кадров экрана через матрицу концептов в RAM за ~15 мс (вызов тяжёлой VLM только для детального OCR);
  - *Audio-Visual Vibe Fusion:* одновременное понимание музыки, звуковых эффектов, интонации голоса и видеокадра при совместном просмотре фильмов/аниме (с соблюдением co-watching etiquette — реакция лицом во время диалогов, голос в паузах);
  - *Латентные рефлексы VRM:* прямая реакция эмоций/тела аватара на вектор экрана/звука за ~20 мс в обход LLM;
  - *Семантический детектор смены сцены* (`cos_sim` соседних кадров для пробуждения `Attention`/`Heartbeat`) и *компактная векторная эпизодическая память дня* (~10 МБ/час без raw video);
  - *Русский `eg2` reader:* линейный проектор аудио-слайсов в русские словоформы/токены для сверхбыстрого потокового ASR.
  - **Зрение для управления ПК (Grounding & Affordance Lane):** тот же проход EG2 + UIA + OCR выдаёт `GroundingCandidate` с bbox/role/confidence; кандидаты связаны с `VisionActionPlan`/`VisionPlanExecutor`, действия проверяются postcondition. Без confidence-гейта и свежего observation token клики запрещены.
- [x] **H4-Grounding — live-приёмка зрения как органа управления:** клик/фокус/ввод в тестовом окне через UIA-кандидаты; OCR-кандидаты на canvas/видео; отказ при низкой уверенности; Stop и policy не дают двойного эффекта.
  21Oct live PASS (`scripts/live_grounding_acceptance.py`): окно «Grounding Test Window» + кнопка, UIA-кандидат confidence 0.98/match 0.987, `plan_status=ok`, click через InvokePattern, postcondition `title_changed`, повторный execute → `clicks=1` (идемпотентно), несуществующая цель → `denied:no_grounded_candidate`. OCR-canvas: `OCR CANVAS` найден через OCR (confidence 0.9), `desktop.pointer` клик подтверждён по `canvas_clicks=1`/title, повтор идемпотентен; Stop → `denied:emergency_stop_active`, повторного клика нет. Добавлены `screen.ground` (HostOS, read-only), bounds в UIA, fresh-token/confidence-гейт, Windows OCR fallback (`windows_ocr.py`). Focus берётся через `AttachThreadInput`/`SwitchToThisWindow`.
- [~] **H5 — Игровой моторно-тактический слой (Game Embodied Layer 10–60 Гц + Auto-Modding):**
  18Oct: expanded engineering baseline in `game_embodied.py`: motor controller, voice combat coordinator, strategy/mod planner, GameObservation, SimulatedGameInputBridge, ModScaffold/ModScaffoldWriter, GameEmbodiedLayer orchestration; tests 17 passed. Live game input, mod execution and auto-modding remain open.

---

## M — Дешёвая модель: трек замены тяжёлого мозга

Цель: снизить VRAM/стоимость основного мозга и сенсорного композитора без потери
daily-качества. Default-модель не меняется до отдельной приёмки владельцем.

- [ ] **M1 — Baseline Hikari 27B:** зафиксировать VRAM/RSS, p50/p95 prefill/decode,
  RU-качество и JSON/action validity на одном фиксированном наборе; сохранить отчёт.
- [ ] **M2 — Шортлист дешёвых моделей:** Qwen3-4B/8B, Gemma-3-4B/12B, Llama-3.1-8B,
  Mistral-Nemo-12B (лицензия, GGUF, контекст, RU, tool-calling); отсеять по бюджету
  VRAM и наличию квантов.
- [ ] **M3 — Единый RU-бенч:** 30 диалоговых реплик, 20 JSON/tool-конвертов,
  10 длинных sensory-снимков; метрики: RU-адекватность, JSON validity, action
  correctness, галлюцинации, p50/p95, VRAM. Ошибки считать по каждому пункту.
- [ ] **M4 — Прогон на GPU1/CPU через тот же llama-server:** сравнить top-2 с Hikari
  на одинаковых промптах и температуре; зафиксировать дельту качества/скорости.
- [ ] **M5 — Интеграция за флагом `-BrainModel`/profile:** без смены default;
  focused tests + DAILY_ACCEPTANCE subset + live text/voice; rollback одной командой.
- [ ] **M6 — Решение и ADR:** обновить STATE/TODO, указать цену, VRAM, latency,
  известные ограничения; promotion только после подтверждения владельца.
- [ ] **M7 — Дешёвый сенсорный композитор (опционально):** EG2 + детерминированный
  Coarse-to-Fine composer как default; `Needle 3` — только English tool-router
  (русский словарь 8k BPE не подходит для генерации RU-текста).
  24Oct paired CPU overlap probe (YAMNet + existing GigaAM): 18 controlled
  speech/music mixes across 3 phrases × 2 sources × 3 SNR; ASR expected phrase
  17/18, YAMNet Music ≥.3 in at least one 2s window 18/18, and 0/5 clean
  speech/noise/silence controls crossed a ≥2-window rule at thresholds .2–.5.
  This supports parallel tracks but is too small/synthetic to set production
  thresholds. Remove blanket ASR→music suppression only after source-disjoint
  real media validation. Music-Descriptor (MERT genre/instrument/mood heads)
  is a research lead, but demo + MTG-Jamendo declare CC-BY-NC; not a shipping
  candidate absent license review. No production wiring. Details:
  `docs/research/yamnet-gigaam-overlap-20261024.md`.  24Oct live-media check: while playback was active on NVIDIA loopback 39,
  captured 14.91s in memory (699 chunks, 0 drops/errors). YAMNet CPU saw
  persistent Music (13 rolling windows, 12 above 0.3, median score .683, max .867); GigaAM
  returned no text. Conditional MERT ran CPU in 1.94s, outputs .324/.293.
  Secondary instrument/genre tags were only .001–.006 and are not publishable;
  source identity was not labeled, so this is a live-path/detector smoke, not a
  music accuracy acceptance. No PCM/transcript persisted. Probe/artifact:
  `scripts/probe_live_music_loopback.py`,
  `runtime/audio-path-replay/out/live-music-loopback-probe-20261024.json`.
  QA segment audit found segA/C/D AAC tracks are digital silence (mean/max
  -91 dBFS), segB has no audio stream. Do not count those visual fixtures as
  audio-positive coverage; report:
  `docs/research/yamnet-gigaam-overlap-20261024.md`.  24Oct implementation follow-up: `YamnetSoundscapeDetector` is now an optional
  CPU-only ambient lane alongside GigaAM, not a replacement. It emits a music
  event only after repeated ≥.30 YAMNet windows (long clips require at least
  25% positive windows), includes only stable tags ≥.15, and never fabricates
  mood/free-form captions. ASR and music persist separately with segment/source
  metadata; music Fusion TTL is 20s and pause clears it. Detector load failure
  leaves ASR intact and is visible in bridge/UI telemetry. Production-venv
  isolated RSS +31.5 MiB after 8s sax inference, 29.7ms per 8s segment; not a
  combined companion budget. Focused test suites: 129 Python + 7 UI passed,
  py_compile passed. Real fixture replay separated Bach/sax/music, speech,
  speech+synthetic chord, noise and silence. This remains below acceptance:
  need source-labeled game/video audio, full companion overlap, and 30–60m soak.
  24Oct live known-music check in isolated no-mic/no-TTS profile: 15s FMA
  Electronic fixture at -18dB yielded a fresh YAMNet `audio_kind=music` event;
  GigaAM emitted no transcript, 0 capture drops and 0 soundscape errors. No genre
  or instrument tag was emitted, so only music presence is proven. This unclosed
  30m run still has time remaining. It exposed monotonic-vs-wall clock misuse for
  YAMNet memory retention (1970 event timestamps); fixed conversion and added a
  regression. 30 focused ambient/YAMNet unittest cases pass; short live
  verification of the fix remains open. Details in music research.
    24Oct design review: connection badge now says «Панель подключена» only
    after `/api/session` succeeds, and «Сервер недоступен» on failure; the old
    «В контуре» overclaimed overall readiness. Mock-brain browser E2E passes
    after the copy change; all nine responsive viewports remain overflow-free.
    Голосовая ошибка теперь объясняет 503 как недоступный TTS и предлагает
    проверить службу/повторить, а сетевые ошибки дают краткую инструкцию.
    E2E mock-flow подтвердил показ сообщения после неудачи озвучивания.


- 24Oct: ???????? 29-???????? no-mic/no-TTS loopback integration run: 174 polls, 115 segments, zero capture drops/errors, one known electronic control yielded `music`; broad genre/style and external-media transcript remain unverified. Fix wall-clock timestamps covered by 30 tests; live post-fix timestamp check remains open. Run details: `docs/research/music-sensory-candidate-evaluation-20261024.md`.


- 24Oct three-role multimodal smoke: Hikari text brain + two concurrent Qwen2.5-Omni-3B sensor slots accepted a video and an audio request (2.70s video, 2.54s audio; Hikari 0.56s). Video got Earth/scene changes but missed clouds/icon detail; audio tagged electronic/EDM but was repetitive and omitted instruments/vocal/transitions. Isolated servers left on localhost 8990/8995; no screen/loopback capture, no daily-profile wiring, and no TTS. Keep audio description quality open; report and proposed detailed role prompts: `docs/research/omni-three-role-smoke-20261024.md`.
  24Oct follow-up replay with the bounded event window plus one direct Hikari
  request: 8 submissions, 5 scene changes, 2 current captions, 4 retained visual
  events; brain endpoint answered in 1.79s and cited details from prior scenes,
  but output truncated and temporal grounding was inconsistent on a second probe.
  Confirms context transport only, not reliable continuity or Companion chat.
  Artifact: `runtime/instances/goal-trailer-visual-replay-20261024/trailer-sensor-replay-timeline-hikari.json`.
  24Oct follow-up: default full repository gate now passes after the unstable
  desktop-wallpaper OCR assertion became opt-in: 1,129 unit + 67 pytest + 18
  API E2E; browser interaction, synthetic desktop voice, Node, PowerShell parse,
  and diff checks also pass. This does not clear the live-profile blocker:
  Hikari currently exposes 8,192 tokens against a measured 11,536-token JAWL
  startup prompt. Gate report: `docs/research/full-gate-20261024.md`.
  24Oct Hikari follow-up: active 8990 was launched at ctx 8192; workspace owned
  launcher is configured for 65536. Same model at 16k CPU passes JAWL startup
  (10,992 prompt tokens) but the first live chat turn times out at 120s while
  startup ReAct is still running. Need GPU1 16k chat retest; this requires an
  owner-approved restart of Hikari 8990. Do not treat the CPU chat as PASS.
  Report: `docs/research/hikari-context-startup-probe-20261024.md`.
  Readiness fix: normal local-bonsai launch no longer opts into AllowBusyStartup;
  the existing heartbeat gate waits for SYSTEM_CORE_START completion before
  exposing Companion readiness. 17 launcher tests, PowerShell parse and CodeSee
  validation passed. Live GPU1 verification still depends on permission to
  restart the current user-owned 8990 service.

## 2026-10-25 sensory history follow-up

- Implemented a bounded one-hour text timeline and seven-day compact hourly history for screen/audio observations, with provenance, sensitive-text suppression, and no raw media persistence. Store/fusion/web tests pass (25 passed, 4 subtests).
- The ten-minute live acceptance captured 199 status samples and 264 text observations with zero capture/API errors. Current scene descriptions worked; direct unaided two-minute retrieval and full ten-minute visual/audio synthesis remain PARTIAL. The existing running companion predates the history-store wiring, so a managed restart and in-process acceptance remain OPEN.
- Report: `docs/research/sensory-history-acceptance-20261025.md`; raw-media-free ledger: `runtime/sensory-history-acceptance-20261025.json`.

- [ ] 28Oct follow-up: compare LFM1.6B GPU with Qwen GPU on labeled sequential content and live brain/TTS coexistence before selecting a detailed visual describer. Five-frame speed probe completed; runtime/lfm-detail-probe-20261028/STATUS.md.

- [~] 28Oct live YouTube sensory check: LFM450→target-window buffer 50/50 at 1Hz with 64.8ms p50; Hikari caption-only recap in 1.08s declined to invent a plot but answered English and stayed broad. Need labeled story-quality set and Florence tags→brain comparison before selection. Report: runtime/lfm450-story-replay-20261028/STATUS.md.


- [ ] Visual detail acceptance: rerun identical LFM450 and Florence-2 moments at the current 960 x 520 adapter output and at the target window's native/highest practical resolution; record pre/post-resize dimensions and scale factor. Score small objects and readable UI text against manual labels; keep JPEG quality fixed for the resolution A/B, then test compression separately. Current 28Oct live comparison is resolution-limited/inconclusive for maximum detail. Report: `runtime/lfm450-story-replay-20261028/STATUS.md`.

- [~] Hikari conversation continuity: managed restart applied 200-message history/cache and startup receipt reports `terminal_context_compaction.installed=true`; compaction is character-budget-driven (18K target) with the latest 12 messages preserved verbatim. Still exercise a long live conversation across the compaction threshold and confirm the summary retains needed decisions. Current health is degraded because captions age out amid scene-change drops; loopback awaits samples.

- [~] Weak YAMNet music-candidate offline screen: 181 source-disjoint ESC-10 non-music clips + three recorded speech fixtures produced zero candidates; five real media clips yielded four confirmed music results and one weak anime candidate; 54 speech/music mixes produced 11 weak candidates and 34 confirmed detections; four speech/noise controls produced zero candidates. Promising routing evidence, not full acceptance: add human-checked speech-only and game/SFX/tonal clips and validate live loopback under load. Candidate cutoff remains uncalibrated; confirmed gate stays 0.35. Report/artifact: `docs/research/audio-speech-music-overlap-20261029.md`, `runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json`.

29Oct direct-mic delivery cues are an experimental DSP lane, disabled by default and opt-in via `-EnableVoiceDeliveryCues` (pitch/level/voiced-frame measurements, no emotion inference). Acceptance remains OPEN pending owner-reviewed mic samples, calibration, CPU/latency cost, and brain uptake: `docs/research/voice-delivery-cues-20261029.md`.

29Oct ambient loopback ASR now filters only clear artifacts (blank/filler, repeated-character and CJK/Hangul) before memory/VA, with an `asr_noise_filtered` counter and no invented default confidence. This is not VAD or semantic validation; mixed-loopback accuracy remains OPEN: `docs/research/ambient-asr-artifact-gate-20261029.md`.
