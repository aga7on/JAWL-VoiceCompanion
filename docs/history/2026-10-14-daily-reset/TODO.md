# TODO — единая очередь JAWL Companion

Актуализация: **2026-10-13**. Это единственная очередь реализации.
[PRODUCT](docs/PRODUCT.md) — требования; [STATE](docs/STATE.md) — доказанные
результаты; [матрица](docs/TECHNICAL_AUDIT.md) — критерии; [остаток и оценки](docs/WORK_REMAINING.md).
Чекбокс закрывается по результату, не по наличию класса/HTTP200/тексту плана.

Статусы: `[x]` — результат в указанных границах принят; `[~]` — часть
реализована/проверена, остаток открыт; `[ ]` — требуемый результат не принят.
Synthetic/provider/device/OBS evidence различаются. Ни один старый PASS
не распространяется автоматически на новый стек или другой клиент.

## Результат, который строим

Один русскоязычный агент: JAWL brain/persona/memory/tasks/native policy;
VoiceMem sensory/context; единый Electron/web UI с VRM, голосом и настройками.
Sandbox0 по умолчанию, явный Full Access3/unattended; чувства включены после
первичной настройки источников. Продакшен требует реального ежедневного
сценария, ночной работы и принятого персонажа, не набора benchmark.

Ранние Live2D/2D/Qwen-ASR/Qwen-TTS-default очереди заменены текущими ADR.
Код не переписывать ради механического совпадения с upstream.
Текущий запрос — реализация по этой очереди; новый goal создан 2026-10-10.
Первый срез B0: общий manifest/defaults/preflight. Отдельные успешные fixtures
не закрывают live/profile/device приёмку.

## D0 — документация и воспроизводимая точка отсчёта

- [x] D0-01: сохранить прежние STATE/TODO/README/HANDOFF/audit/recovery без потери
  исторических результатов; выделить текущие документы и research/evidence.
- [x] D0-02: единые состояния target/implemented/synthetic/provider/device,
  актуальные модели/VRM/UI и ссылки; docs-only validation отражена в CHANGELOG.
  Проверены current Markdown paths/headings, UTF-8, целостность архива и diff;
  новый runtime evidence этим не заявляется.
- [x] B0-01: зафиксировать reviewable runtime baseline: commit+dirty-diff/hash,
  версии snapshot/workers/assets; не включать чужие правки массовым commit.
  Добавлен metadata-only `scripts/capture_runtime_baseline.py`: HEAD, dirty
  diff/source hashes, snapshot verification, worker/VRM inventory; без commit.
  `runtime/baseline-b0-manifest-20261010-final.json`; whole release/weight locks
  этим не приняты, большие GGUF — metadata only. Fullgate direct child exit0.
- [~] B0-02: canonical + local manifest связан с Python/PowerShell/Electron;
  defaults сведены к 2367/8766/8770/9889/8990, RunSeconds0, Hikari alias/64k,
  vision Bonsai8986 opt-in. Явные overrides сохраняются, reserved8765 отклоняется.
  Readiness brain проверяет точный alias, не только HTTP200. Остаток: live
  current profile/model/context readback в общем UI. Rust bounded local overlay,
  schema/ports/profile/discovery добавлены; differential cross-client parity OPEN.
  Readback13Oct (live overview): model=local-bonsai2 виден (tick), persona/access
  уровни видны; context/profile в readback ОТСУТСТВУЕТ — остаток. `/api/tts/status`
  provider=TeraTTSHttpClient при model=OmniVoice — по дизайну (composition:
  "omnivoice": TeraTTSHttpClient, same contract). Evidence: `runtime/b0-02-*`.
- [x] B0-03: воспроизводимый старт/остановка одного owned профиля вне source cwd;
  конфликт порта/отсутствующая модель дают понятный отказ, не чужой kill.
  Принято13Oct: whole owned профиль 5× запущен из C:\ (owner-записи, лог
  «Integrated profile ready», естественные и досрочные остановки, порты/дерево чисты);
  gate test busy-port/foreign-cwd не стартует модели. Под-остатки ниже — отдельные
  residuals (Failed to fetch; cache-bootstrap в B0-02/B0-04 дополнении).
  ProfileName/NoBrowser/temperature forwarding добавлен; wrapper больше не
  pre-write daily. Lock берётся до prepare/configure и освобождается при ошибке.
  Real PS invocations из чужого cwd проверяют busy-port/colliding overrides
  без запуска весов; исправлен PSBoundParameters.Contains overload crash.
  VoiceMem memory-root теперь explicit в data/sensory/voicemem выбранной
  instance; inherited storage env не redirect. Перед live проверить прочие
  model/cache paths и actual GPU1 mapping; чужие процессы не kill.
  Protected JAWL-Coding/VoiceMem/RE остаются read-only.
  Отдельно расследовать intermittent desktop acquire `Failed to fetch`:
  initial fullgate10Oct FAIL, standalone PASS, bounded diagnostics добавлены.
  Profile-isolation gate: unit unauthorized POST WinError10053; добавлен bounded
  early-rejection body drain +6 tests, без ослабления session/CSRF assertions.
  Не считать неповторение ошибки доказанным root-cause fix.
  Test isolation debt: stale logger handler ссылается на удалённый temp/logs
  после fixture cleanup (4 stderr FileNotFoundError в green612 и625 unit runs).
  Исправлено в owned test_jawl_goal_recovery.py: identity snapshot до imports,
  remove+close только новых handlers до temp cleanup, чужие сохраняются.
  Recovery+continuity+cleanup regression3 PASS, stderr empty; fullgate693 имеет
  0 прежних FileNotFoundError. Pinned logger не изменялся.
- [~] B0-04: закрыть portability machine-dependent paths/env через собственный
  manifest/config/data/log/cache и migration, не переносить секреты в git.
  VoiceMem root изолирован по instance (3 mocked CLI/forwarding tests);
  standalone default сохранён. Остальные caches/asset paths/migration OPEN.

Дополнение к B0-02/B0-04 из strict live bootstrap13Oct: fresh offline instance
не стартует без MiniLM/FastEmbed cache; нужны declared asset/preflight и safe
isolated seeding, не junction к shared/protected weights (native recovery удаляет
model_path). Минимальный Windows env также требует ProgramFiles для NVML и
ProgramFiles(x86) для Edge discovery. Ручной test seed/env fix — не clean-install
acceptance. `/api/health` legacy status=degraded не равен provider readiness;
strict test отдельно доказывал instance identity и exact owned listeners.

## B1 — capture, playback, отмена и ownership

- [x] B1-01: desktop synthetic path устройства/gate/hysteresis/pre-roll/endpoint,
  bounded capture/upload/lease и единственный playback owner; regression5Oct.
- [x] B1-02: bounded NDJSON playback, scheduled cancel/stale drop,
  scene handoff/reset; regression5Oct. Это не provider worker cancellation.
- [~] B1-03: реальный Stop/cancel освобождает ASR/TTS/LLM ресурсы соответствующей
  генерации; доказать отсутствие stale audio, actual-model/device release.
  Native upload уже cancellable:22 Rust unit (включая16 capture/mock-HTTP)
  +1 CLI PASS; stalled upload Stop+join<1s, no replay/late ACK. 10s — deadline
  без отмены, не текущая задержка Stop; hardware/real-model остаются OPEN.
  Supervisor start/restart теперь используют общий checked Win Job assignment,
  отказ reap-ит только созданный child. Stop закрывает Job handle;16 tests PASS,
  включая parent hard-kill после restart, idempotent start и Stop при startup.
  Final ASR теперь per-call cancellable: release/expiry capture, discard/close
  и ambient Stop(false) отменяют только свой scope; late transcript не становится
  ходом.76 focused ASR/capture/ambient tests PASS, включая реальные cheap children.
  Streaming ASR привязан к capture+utterance и lease token: old readers/reset
  не трогают replacement, expiry/release reaps own child, queue8/line64KiB/text4000,
  HTTP не ждёт pipe writer.17 bridge+9 scoped HTTP tests PASS; среди них actual
  HTTP/buffer/bridge/cheap child. Новый utterance reaps/reloads child: latency
  real GigaAM ещё измерить, без acked reset нельзя гарантировать чистый context.
  Real-model ASR/LLM release, полная TTS matrix, per-worker descendants и barge-in
  in-flight voice turn остаются OPEN; synthetic cancellation не закрывает B1.
  TTS old-finalizer fix + generation-scoped HTTP abort:21 focused tests PASS;
  Scoped request_id cancel добавлен в service/HTTP/desktop:13 новых Python
  registry/service/HTTP +7 Node tests PASS; early cancel и late old cancel
  не задевают replacement, replay bounded60s/128 IDs. До first chunk проверен
  cooperative provider, не actual Tera. Tera adapter теперь передаёт scoped
  worker UUID per sentence + batch cancel;28 provider tests PASS. Worker≤8
  pending/queue10s/cancel signal120s, proxies4 Tera+4 RUAccent ONNX sessions
  без upstream patch;8 proxy +9 worker tests PASS. Native ORT1.29 CPU fixture
  отменил A за4.494ms, не задел B, follow-up PASS — это не Tera weights/SLA.
  Service admission теперь отменяет previous до ожидания слота≤2s; latest waiter
  не может ожить после replacement. Lease ждёт actual local provider return;
  paused native iterator закрывается до передачи слота, stale cleanup не
  освобождает чужой.17 admission tests PASS, planner≤1 с cancel-aware ожиданием.
  Tera close атомарно отвергает новую работу и сигналит active/queued tokens;
  idempotent/concurrent close проверены,13 worker tests PASS (было9).
  Actual Tera service r3 PASS12Oct/observed exit0: cancel→worker+lease idle102.8ms,
  3 follow-up WAV/RTF0.399–0.482 CPU24/ru_f1, own worker закрыт, daily9889 не принят.
  RAM-guarded harness12 tests, exact Job ownership3 + supervisor16 PASS; исходные
  SKIP/FAIL и старые baselines сохранены в STATE, не текущие next actions.
  Native sync/stream admission теперь единый producer с queue32 и cleanup fence;
  strict outgoing IDs, без blind POST replay на409/offline/lost ACK.53 focused
  chat/SSE/admission/SDK harness PASS. Pinned installed SDK fake loopback:
  cancel→server EOF0.14–0.48ms, no retry, B/follow-up success; не real model release.
  Owned native HTTP guard добавлен:1024IDs/TTL300s, pending не expires/evicts,
  cancel-before-dispatch tombstones, no duplicate replay, body128KiB/1s absolute,
  ready5s/send2s/cancel-forward1s, native auth и balanced bridge lease. Unknown/
  expired IDs ВСЕГДА best-effort forward exact native cancel: TTL test FAIL→PASS.
  ACK local_dispatch_prevented не compute release. Entry обоих launchers проверяет
  snapshot/instance/registry isolation, integrated capability readback; startup
  console token redaction/UTF8. Native core не копировался и не патчился.
  Actual owned-console r5 PASS/exit0: startup0.726s, exact own Job/listener,
  auth401/cancel200/turn409, root+listener закрыты, без agent/model/device.
  Owner-fenced diagnostics добавлены,7 tests явно в pytest gate;14 HTTP guard +
  5 boundaries (3.11/3.14) +11 entry focused PASS. Fullgate final scope — STATE.
  Default client turn/cancel POST теперь scoped socket-owner до connect/TLS,
  absolute deadline headers/body, no redirects/proxy/replay, TLS verify включён.
  Отмена A закрывает peer socket и exact-ID cancel, B/follow-up работает;13 HTTP/TLS
  +3 native adapter loopback PASS на3.14/3.11, combined65+11subtests PASS.
  Opaque custom opener reap не заявляется. Следом actual selected-LLM slot release,
  затем current voice/task continuity.8990 недоступен, обе GPU почти заполнены:
  чужие процессы не kill; продолжать независимую транспортную работу.
  Actual selected Hikari CPU probes12Oct r1/r2 FAIL: load19.416/21.654s, за35s
  required generation/prefill progress не подтверждён; both own Job/listener gone,
  RAM guard не tripped. Не compute release acceptance и не оценка GPU.9 focused
  diagnostic tests PASS; протокол STATE/LLM_MODEL_CANCEL_BENCHMARK. Без новой
  гипотезы CPU не reload. 13Oct RuntimeSupervisor early create→Job gap закрыт
  атомарным JOB_LIST; evidence и границы — верх STATE. Следующий независимый срез:
  per-worker restart descendant teardown реализован13Oct:4 real tree tests PASS
  на3.14/3.11, B не затронут, root-dead cleanup проверен; final gate receipt STATE.
  Streaming ASR/VoiceMem PIPE ownership реализован13Oct; tree/EOF/failure tests
  PASS3.14/3.11, latest fullgate receipt/baseline — STATE. Следом file-mode
  final ASR giga_final.py реализован13Oct:11 scoped tests PASS3.14/3.11, actual
  GigaAM3 synthetic WAV0.206–0.480s/normalized words match. Actual Hikari GPU1
  generation cancel→idle78.267ms +same-client RU followups PASS; details/failures
  retained STATE. Следом connected RU voice first-audible/replacement/whole-turn,
  concurrent inference B и реальные устройства, не повтор infra-only tests.
  Restart/TTL/cross-transport durable dedup ещё OPEN. Старые pinned config_io warnings
  сохранить как debt для owned repair, не патчить immutable snapshot.
  TTS replacement latency, bare disconnect, WORLD mid-call, other providers,
  acoustic/p95/whole-profile и direct Popen/PIPE owners остаются OPEN.
  Latest full gate и frozen source SHA — в STATE; не перезапускать без code change.
- [x] B1-04: аудио-owner поверхностей принят: DECISIONS (Electron `/app` =
  getUserMedia→Worklet→gate; Rust = явная альтернатива, не параллельный default
  owner; lease до открытия устройства, renew/release по identity; expiry ограничивает
  потерянного клиента). Evidence13Oct: `test_lease_renews_expires_and_requires_matching_identity`
  + busy-owner rejections в gate; Rust half-duplex не называется desktop duplex.
- [~] B1-05: speech cancel, native turn cancel и durable goal cancel имеют
  разные явно видимые команды/состояния; перебивание речи не стирает задачу.
  13Oct evidence: /app `#speech-stop` «Остановить речь» (scoped /api/tts/cancel) и
  `#emergency-stop` danger в настройках — видимые отдельные команды; exact native
  turn cancel сохраняет goal (test_jawl_goal_voice_continuity, gate); mic-stop
  прерывает in-flight финализацию (turn-level, наблюдение13Oct). Видимый goal-cancel
  в /app отсутствует (консольная сторона) — остаток.

## B2 — живое русское общение

- [~] B2-01: минимум3 RU WAV через actual capture основного `/app` →
  real GigaAM → native JAWL → выбранный TTS → WebAudio/VRM.
  Проверить transcript, смысл ответа, correlation, отсутствие error/duplicate.
  Route evidence13Oct: `runtime/browser-voice-e2e-20261013-app.json` PASS (3 turn через `/app`;
  Edge fake-input device, приложение владеет getUserMedia/gate/VAD/upload/finalize).
  Transcripts чистые, по одной session/correlation, voice_ends1, TTS/WebAudio играл,
  VRM в скриншотах; ответы по смыслу: Паста/короткие ответы/статус (с проверкой задач).
  Не физический mic и не аппаратный duplex — это B2-04/B2-05.
  Review13Oct: прежний gate доказывает старт playback, не полную озвучку без
  обрыва/ошибки. До нового completion-aware browser evidence B2-01 partial.
  Strict live r3:2 turns full playback PASS3.012/3.397s, third status turn75s
  timeout before UI final/TTS; fourth duplicate preference not reached. Suite FAIL,
  exact owned listener cleanup PASS; report/limitations — верх STATE.
  Owned completion guard13Oct подключён:11 guard/snapshot +12 launcher tests
  PASS3.14/3.11, actual isolated console import/install/auth/cancel probe PASS,
  no model/device. Missing terminal теперь bounded error; полноценный ответ этим
  не восстановлен. Повтор strict real-model suite после regression всё ещё OPEN.
  Strict r4 13Oct: selenium env исправлен (browser child user-site);attempt2 turn1
  completion-aware PASS (playback3.42s+EOF), turn2 heartbeat-interleave;attempt3
  heartbeat-misframe после failed remember → guard turn.error; отчёты
  …-r4-attempt{1-selenium,2-interleave,3-heartbeat}*. Fresh-profile/prompt-fix OPEN.
  Prompt-fix13Oct (failed-tool→доставка) дал turn1–2 PASS в attempts4/7; attempt7
  на OmniVoice (Job владеет9890, playback2.68/3.24s+EOF), turn3 флейк (замирание
  захвата/длинный статус-ход). Отчёты `…attempt{1..7}*`.
- [~] B2-02: вывести streaming ASR partials в desktop UX с turn/generation,
  bounded UI update и stale-drop; final приходит через канонический путь.
  Частичное13Oct e2e: `browser-voice-draftprobe-20261013.json` PASS на OmniVoice —
  13 `/api/voice/draft` mode=streaming, текст рос 0→8→…→49, 26 DOM-семплов
  превью (max73≤160), очистка после финала, финал канонический, озвучка2.36s+EOF.
  Consumer уже served/wired,16 helper tests и actual app function-body test
  проверяют bounds/scoping/clear. Audit: DOM classifier считает «Слушаю…»
  preview, draft_lane не влияет на result.ok; поэтому telemetry не strict gate.
  Нужны exact prefix+content assertions, matching identity, clear after final
  и отдельный stale DOM scenario. Strict --require-draft-preview реализован:
  23 controlled harness tests PASS, late-preview/oversize rejection и scoped
  text matching. R5 first required turn PASS (12 preview samples/content<=49,
  clear/no-late, full audio2.68s/EOF); whole suiteFAIL on second native reply.
  Stale replacement DOM scenario и эксплуатационная latency/reliability OPEN.
- [~] B2-03: измерить cold/warm endpoint/ASR/queue/LLM TTFT/final/TTS first
  audible/total; для p50/p95 расширить набор,3вопроса не статистическая приёмка.
  13Oct синтетическая серия13 успешных turn (`control`+`/app`,5 прогонов): first-audio
  p50 11.7с/p95 24.65с (empirical linear, reviewed report); voice/end→TTS headers10мс
  p50; voice/end request (ASR+JAWL) p50 4.9с/p95 16.71с. Turn→first-audio включает
  время пользовательской фразы; это не endpoint→answer latency. Не закрыто: LLM TTFT отдельно, queue depth,
  cold/warm-разбивка, физический mic. Исходный timing report сохранён; ограниченная
  эмпирическая оценка — `runtime/b2-03-timings-20261013-reviewed.json`,13 successful
  turns без учёта failure-rate не являются эксплуатационным SLA.
- [ ] B2-04: физический mic: устройства, шум/тихая речь, темп2–3слова/с,
  долгие паузы/монолог; gate не отрезает слоги, пики/лампы отражают реальный звук.
- [ ] B2-05: акустические echo/duplex/barge-in: пользователь перебивает,
  старый звук прекращается, новая реплика принята, собственный TTS не команда.
- [ ] B2-06: согласовать текст/реальную просодию/эмоцию аватара; недоступная
  эмоция явно деградирует. OmniVoice default с13Oct (ADR-047), Tera/Vox выбираемые;
  клон отдельно. Фонемный lip-sync — A-04, не дублирующая голосовая реализация.
  13Oct: переключение дефолта и live-подтверждение владельцем — STATE; prosody/emotion отдельно.

## B3 — один согласованный агент

- [ ] B3-01: текущий provider проходит JAWL JSON envelope/native tool/context/
  terminal response/ошибки. Повторить при замене provider, включая QWB.
  Контекст ограничивать по JAWL с budget для persona/memory/tools/history/output.
  13Oct: terminal-канал вернул error-envelope на фактовый вопрос, когда модель
  закрыла turn без send_message_to_terminal (после preference-памяти; воспроиз.2).
  Детали и границы — STATE.
  Review13Oct: конфликт общего разрешения actions[] с correlated delivery
  уточнён в owned RESPOND_DIRECTLY; duplicate-key recovery bounded.4 static
  contract tests PASS, не model compliance. Требуется fresh owned profile
  sync/restart и correlated final/error проверка; Empty actions после успешной
  доставки или SYSTEM_CORE_START не считать отдельным failure.
  Strict live13Oct выявил другой конкретный missing-final путь:
  duplicate_success_concluded после successful list_memories не публикует
  correlated final/error. Следом owned native completion guard (no thought/text
  fallback, no goal cancellation), затем   correlated delivery recovery/live rerun.
  Envelope13Octb: полный набор полей подтверждён на OmniVoice-turn
  (`b3-01-envelope-20261013.txt`; speak=True, actions0, turn_id/response_id согласованы).
- [~] B3-02: fast-chat vs explicit goal_execution; reasoning по capability,
  быстрое общение без ненужного thinking, полное выполнение поручения отдельно.
  В голосе краткие checkpoints; длинный отчёт по запросу, без скрытого CoT.
  13Oct: политика есть (`docs/REASONING_POLICY.md`: приказ → goal_execution);
  verification поведения на текущем provider — открыто.
- [~] B3-03: Heartbeat/Swarm/Attention используют общий state и приоритет;
  проактивность уместна, нет двойного ответа/действия или sensory authority.
  13Oct evidence: heartbeat DEFERRED активный ReAct cycle на safe boundary
  (agent.log14:56; test_jawl_goal_voice_continuity: Heartbeat._active_react_task);
  proactive tests в gate. Полный приоритет/no-double acceptance — открыто.
- [ ] B3-04: единый связанный UI/voice→persona+memory→поручение→native effect→
  postcondition→task update→restart/recall. Реальное содержательное влияние
  исправленного факта, не только GET из базы.
  13Oct: отдельные звенья покрыты (test_e2e: gigaam_final→voicemem→chat,
  approval/postcondition, restart, memory visible); полный связанный сценарий открыт.
  Инструмент: `scripts/run_connected_daily_acceptance.py` (нужен running профиль,
  `--live --sandbox-dir`; remember/revise→voice→native write/read→restart→recall→
  cleanup) — запускать в следующем live-окне.
- [~] B3-05: voice Stop/barge-in во время durable goal, provider failure/restart:
  обязательство сохраняется, эффект сверяется до retry, старый звук не возвращается.
  Ранее принятый crash reconciliation не закрывает этот current voice case.
  Тест-приёмка13Oct: `test_tts_stop_and_exact_native_turn_cancel_preserve_resumable_goal`
  — goal сохранён (тот же goal_id, active, pending_work, phase/next_action) в gate;
  scoped-cancel без stale возврата. Live provider-failure во время голоса — открыт.
- [ ] B3-06: уровни0–3 и все обязательные namespaces доступны через native discovery;
  representative safe fixtures для filesystem/terminal/coding/debug/MCP/browser.
  Не вводить второй HostOS allowlist; OS/UAC/EULA не обходить.
  13Oct: live-матрица не запускалась — owned console требует operator token
  (секрет не читаем); fixtures в тестах есть; September receipts — история.
- [ ] B3-07: отдельный CDP browser/workspace полезен в sandbox; DOM/navigation,
  cancellation/audit и postconditions. openURL/UIA adapter не full CDP.
  13Oct: только доки (ARCHITECTURE/PRODUCT/DECISIONS); actual CDP acceptance открыт.
- [x] B3-08: исправление ошибки/пустого JSON/timeout/reconnect даёт один terminal
  status, bounded retry без повторных мутаций.
  Принято13Oct: единый terminal status/reconnect и запрет blind replay на409/offline/
  lost ACK покрыты (53 focused + native gateway terminal-error тест в gate);
  saturation503/409 документированы в STATE. Исторический503: закрыт в history —
  bounded Ollama transport failure, не воспроизводится (test_e2e16/16), no blind
  retry/duplicate; «original external cause remains unproven» — диагностический риск.

## P — память и чувства, часть того же агента

- [~] P-01: канонические записи JAWL доступны через один memory owner:
  notes/tasks/facts/preferences/traits/summaries/mental state/drives/hypotheses/
  ticks/timeline/journal; не сводить всё к одному ambient episode.
  13Oct: live overview отдаёт counts sql (mental_states/tasks/notes/traits/drives/
  ticks) + vector/graph; /api/jawl/memory и /api/jawl/journal живые; episodic_timeline —
  единый TimeService. Доступ есть; per-type acceptance — открыто.
- [~] P-02: correction/validity/provenance/contradictions/retrieval проверены
  после restart на выбранном backend и влияют на ответ.
  13Oct: restart-survivability покрыта (audit file/offset/settings; memory видна
  после рестарта в test_e2e); влияние исправленного факта на ответ — открыто.
- [ ] P-03: различить forget/archive и physical erasure; очистка производных
  индексов/сводок/истории/backups по явной политике. Ambient clear не стирает T3.
  13Oct: политика в доках (CORE_OWNERSHIP:120; DECISIONS:505); erasure-пайплайн
  и тест «ambient clear не стирает T3» — открыто.
- [~] P-04: durable T1/T2 и consent, дедупликация, TTL/count/bytes, атомарное
  восстановление. Сейчас эти слои process-local.
  13Oct audit: bounds/consent в модуле есть (observation_ttl1800s/episode_ttl7d,
  max_bytes256KiB с caps, raw_audio/raw_frame_persisted=False; capture по умолчанию
  выключен); durability T1/T2 и атомарное восстановление — открыто.
- [~] P-05: автоматическая T1→T2→JAWL консолидация по прозрачной отменяемой
  политике, не manual promote как вечный предел. Наблюдение не факт о владельце.
  13Oct audit: triage/consolidation путь есть (reflection write path, promote endpoint,
  AmbientTriage benchmark); автоматическая прозрачная политика вне promote — открыто.
- [ ] P-06: physical system loopback: segment rotation, own-TTS overlap,
  длинный звук, speech priority и bounded queue. Mixed loopback не доказывает
  per-app identity; при невозможности attribution показывать неопределённость.
- [ ] P-07: screen-watch/VLM/UIA/fusion/attention: свежий контекст с TTL,
  чувствительные окна/пауза/деградация. Принять RU OCR/grounding на своём профиле.
- [ ] P-08: visual closed loop capture→план→native action→новый postcondition;
  stale image/coordinate/capability deny и bounded lag. Не каждую секунду LLM
  без полезности; не большой download до RU gate.
- [ ] P-09: music/non-speech audio captioner и вероятностный voice-affect:
  выбрать capability на небольшом RU наборе, связать с общей памятью, no diagnosis.
  ASR не считать этой реализацией.
- [ ] P-10: после первичной настройки sources/permissions обычный профиль
  включает чувства и запись observations; visible pause/revoke/sensitive drop,
  без raw persistence и без отправки remote media по согласию только на text LLM.

## U — единый пользовательский интерфейс

- [~] U-01: сверить field/action inventory source и owned JAWL, обновить registry
  с evidence по каждой строке, без неподтверждённых процентов покрытия.
  13Oct snapshot: `/api/capabilities`+overview сняты с живого профиля
  (`runtime/b0-02-capabilities-20261013.json`); per-row registry evidence — открыто.
- [x] U-02: один ConfigHub writer, scalar/list/object-list/secrets round-trip,
  revisions/backups/readback/effective/restart в понятном UX.
  Имеющиеся механизмы не переписывать как отсутствующие.
  Принято13Oct: 11 unit tests (revision-conflict, secrets mask/merge/dash/tail,
  backups rotate, restart-required, readback) + browser settings acceptance в gate
  (saved/readback/conflict-preserve/invalid-recovery). Граница: object-list не назван
  отдельным тестом; owner visual — U-07.
- [~] U-03: чат: history loading/pagination/reconnect/retry/cancel, корреляция
  text+voice и ошибки без потери разговора.
  13Oct: control-консоль грузит /api/history (live 200 turns); reconnect/terminal
  error и scoped cancel покрыты тестами (gate); в /app код загрузки истории не найден
  (grep desktop/*.js), pagination отсутствует — остаток.
- [ ] U-04: attachments documents/images/audio/video с capability check, лимитами,
  безопасным разбором и честным unsupported; emoji picker и slash-command menu.
- [ ] U-05: библиотека памяти с типами/источниками/редактированием/исправлением/
  забыванием и отдельным erasure. JAWL сам наполняет её через общие contracts.
- [~] U-06: цели/задачи/actions/status/artifacts и управление reasoning/swarm/
  Heartbeat/HostOS/debug/моделями/интеграциями в общей панели.
  13Oct audit: endpoints есть и живые (/api/tasks proxied к native, /api/state,
  /api/timeline, /api/audit; overview: tick/persona/drives), console-панель их
  использует; покрытие в /app и управление моделями/интеграциями — открыто.
- [ ] U-07: лаконичный мятный Aero, понятная навигация, однократные настройки
  отдельно от разговора, focus/keyboard/touch/contrast; owner visual acceptance.
- [ ] U-08: responsive/HTTPS/auth на реальном tablet/mobile, secure context mic,
  reconnect/virtual keyboard; тот же UI, не отдельное мобильное приложение.
- [ ] U-09: actual VRM presentation для OBS: тот же state/emotions/lips,
  один audio owner, никаких control secrets/private chat/memory.
  Проверить installed OBS, transparent/DPI/multimonitor/window lifecycle.
- [ ] U-10: убрать legacy console/fallback только после полной актуальной parity,
  regression и принятия пользователя; отсутствие iframe не самоцель.

## A — персонаж и движения, отдельная art-приёмка

- [x] A-01: отдельный InterfaceV9: ограниченные geometry/seam/scene gates PASS,
  34wrist+34ankle/rest+16poses; active avatar сохранён.
- [ ] A-02: blocking→лицо/волосы/пропорции→посадка одежды/обувь→материалы/UV.
  По turnaround, без перчаток; четыре вида и крупные планы.
  Не тратить физику на исправление неверной rest geometry.
- [ ] A-03: cloth/body/hair/chest/hip collision-aware вторичная физика,
  согласованные веса тела/одежды, settling/turn/bend/squat/reset/swap/dt spike/
  reduced motion/off. Helpers finite motion не full physics acceptance.
- [ ] A-04: один pose owner, лёгкий idle/listening/thinking/speaking graph,
  crossfade/жесты/gaze/mimic и timing-aware lip-sync; playback5VRMA после
  ретаргетинга/проверки одного клипа. Рот по RMS — текущий fallback.
  Кандидат-источник idle/жестов: ActionForge CC0 (`idle_loop`,
  docs/RESEARCH_ACTIONFORGE_IDLE_LOOP.md); первый срез — 1 клип после GLB→VRMA
  ретаргета; ассеты вне git, физика/арт-приёмка отдельно.
- [ ] A-05: ≥90/100 по art rubric, волосы/лицо отдельно≥90% максимума,
  нет critical clipping/UV/rig; owner acceptance и согласование active switch.
  Потом frame-time/draw/memory budget в реальном Electron/OBS.
- [ ] A-06: упакованные редактируемые исходники, asset versions/hashes/licenses/
  attribution; не коммитить runtime модели автоматически.

## S — согласованные будущие интеграции

- [ ] S-01: stream chat/Restream URL adapter, источник/identity/модерация/rate limit,
  уместные реакции через JAWL; чужой чат не authority.
- [ ] S-02: собственные social accounts подключает владелец; scopes/credentials,
  publication policy/idempotency/audit; не публиковать до настройки полномочий.
- [ ] S-03: улучшения из AIRI/NEKO и model research переносить малыми принятыми
  slices. Crane/новые TTS/VLM только по capability/resource gate, не обязательная
  замена всех моделей ради завершения продукта.
  Кандидат13Oct: bounded RAM ring buffer выбранных screen/audio источников
  (OBS optional adapter, не обязательная зависимость). Свежий snapshot/последние
  секунды доступны native JAWL tool; эмбеддер только optional temporal retrieval,
  не OCR/ASR/VLM. Gate: consent/redaction/TTL/no raw persistence, sync AV,
  self-TTS exclusion, budget/backpressure и RU retrieval на исходных фрагментах.
  Сначала оценить существующий sensory buffer, не заводить второй memory owner.

## B4 — эксплуатация и поставка

- [ ] B4-01: current native task/action recovery и 8h disposable unattended:
  закрытая панель, Heartbeat, worker/provider failure, lease expiry/revoke,
  Stop, постусловия, утренний журнал. Тест8h не равен8h разработки.
- [ ] B4-02: RAM/VRAM/CPU/frame-time/cold-load/token/queue/log budgets на целевом ПК;
  сенсоры уступают голосу/задаче/игре, GPU0 не занимать неявно.
  CPU/RAM offload принимается по latency/качеству, не по названию quant.
- [ ] B4-03: clean install outside cwd, dependency/model/asset manifests+hash/license,
  понятный запуск/diagnostics/stop; wheel smoke не one-click install.
- [~] B4-04: update/migrate/backup/restore/rollback на копии данных, не терять
  personality/memory/tasks; не дублировать workers после crash/restart.
  13Oct audit: managed-file backup при sync (prepare_daily_profile .bak), goal/task
  ledger restore проверяется live-harness (run_goal_reconciliation_live); полный
  backup/restore/rollback данных — открыто.
- [ ] B4-05: secret scan/redacted logs; ранее переданные ключи заменить, если
  ещё активны; raw audio/video/TTD не входят в обычную поставку.
- [ ] B4-06: major updates — полный regression, затронутые real-provider/device/
  OBS rows, screenshots/latency/errors, без превращения SKIP в PASS.
  RC после whole daily scenario, production-ready после применимой матрицы
  и приёмки владельца с явными согласованными исключениями.

## Порядок и Definition of Done

B0 → B1 → B2 → B3 — первый связный ежедневный сценарий.
Далее P/U, artA параллельно с непересекающимся scope, затем B4;
S — расширение принятого основного контура. Не начинать20пересекающихся workers.

Каждый срез: исходный baseline, вход/ожидание/наблюдение, run+turn IDs,
versions/hash, pass/fail/skip, redacted artifacts, предел evidence;
обновить STATE/CHANGELOG/TODO. Без полного текущего доказательства не закрывать
задачу по старому тесту. Новый goal только по явному запросу пользователя.

Полный прежний список сохранён в
[архиве](docs/history/2026-10-10-before-docs-consolidation/INDEX.md):
это история, не ещё одна активная очередь.
