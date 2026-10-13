# Технический аудит и приёмочная матрица

Сверка: **2026-10-12 (Москва)**. После docs-only аудита начат B0 code slice:
manifest/defaults/preflight;12Oct добавлен isolated real Tera CPU probe, без devices.
Новый fixture
и regression evidence фиксируется в STATE; исторический gate2026-10-05 сохранён.
[STATE](STATE.md) — факты; [TODO](../TODO.md) — единственная очередь;
[PRODUCT](PRODUCT.md) — требования; [остаток/оценка](WORK_REMAINING.md).
Предыдущий аудит целиком сохранён в [архиве](history/2026-10-10-before-docs-consolidation/INDEX.md).

## Заключение

Основа не требует переписывания в один монолит. Один JAWL decision/policy/
memory owner, отдельные сенсорные workers и общий клиент — подходящая граница.
Но интеграционный код и отдельные PASS не равны принятому приложению.
Главный риск — отсутствие доказанного цельного поведения на текущем стеке,
плюс недостающий UX, долговечность ambient-памяти и художественное качество.

Численный процент готовности не измерен. Количество строк, тестов, коммитов
или классов не является таким измерением.

## Что уже подтверждено и в каких пределах

Дополнение13Oct: верх STATE содержит более новые ownership/PIPE/final-ASR и
actual GPU1 evidence. Latest finished fullgate814/66/16/86/6/8, baseline352;
последующий353-source gate проверяется отдельно. Historical12Oct строки ниже
не являются latest-coverage claim. Actual selected GPU1 generation cancellation
теперь принята в узком single-slot native SDK сценарии, не весь B1/voice.

| Область | Evidence | Не следует из этого evidence |
| --- | --- | --- |
| Selected Hikari GPU1 |13Oct r4 PASS parent+child0:CUDA1/layers99/ctx65536/threads12, generation n_decoded2→cancel→idle78.267ms, same-client RU followups0.931/0.773s, own cleanup |Не concurrent stream B, long-context quality, full native agent loop, first-audible/voice/device acceptance |
| Selected GigaAM CPU |13Oct actual3 synthetic Tera WAV final-ASR PASS0.480/0.206/0.257s; normalized words match; file-worker own tree cleanup regression11 tests PASS3.14/3.11 |Не microphone/noise/overlap/long natural speech, model mid-call cancel latency, whole voice pipeline |
| Полная локальная regression |12OctMoscow:779unit/66manifest-worker/diagnostics pytest/16HTTP/86Node/6legacy browser/8desktop composite; direct child exit0, receipt passed (`runtime/gate-client-post-20261012.json`),343 frozen sources matched |Synthetic/mock scope; production/live/device/art acceptance NOT accepted. Whole RU pipeline, device, current profile readiness и initial network root cause OPEN;94 старых ResourceWarning markers остаются |
| Desktop capture/playback |Actual app/serializer/AudioWorklet/WebAudio, synthetic media, mock ASR/JAWL, tone TTS |Акустический echo/duplex и semantic answer реальной модели |
| Selected Tera CPU |12Oct r3 PASS/observed exit0:cancel→worker+lease idle102.8ms,3 WAV1.465–1.859s/RTF0.399–0.482; own Job/listener teardown |Не precise kernel timing, transcript/acoustic quality, first-audible/p95, default9889 readiness, full RU voice |
| Native admission / installed SDK |Owned HTTP guard, owner diagnostics; default client scoped POST socket/deadline,13 HTTP/TLS+3 adapter loopback cases PASS3.11/3.14. Actual owned-console r5 PASS/exact Job/cleanup/no model; SDK EOF0.14–0.48ms |Process-local/TTL, не durable/exactly-once; opaque custom opener reap, selected model compute/slot release и current goal continuity OPEN |
| Selected LLM CPU probe |12Oct r1/r2 actual Hikari FAIL35s; required progress не подтверждён, own server/Job cleanup, RAM guard не tripped.9 diagnostic tests PASS, application343 sources unchanged |Не compute-release acceptance, не причина failure и не GPU speed/quality. No third CPU load без новой гипотезы; independent B1 early Popen→Job gap далее |
| Память JAWL |Ранее real remember→revise→restart→recall в выделенном профиле |Durable T1/T2, erasure всех производных данных, auto consolidation |
| Native policy/tools |Ранее representative levels0–3/debug/catalog acceptance |Успех каждого инструмента на любом процессе/ОС |
| Goal recovery |Provider-failure-native-recovery-current-v11, action reconciliation и supervisor lease slices |Exactly-once всех side effects, current voice Stop continuity,8h soak |
| Avatar InterfaceV9 |Geometry/seam/actual scene PASS по одному SHA |≥90 likeness, all-pose collisions, full cloth/body physics, hardware FPS |

Артефакты подробно перечислены в STATE и датированных reviews. Старые
реальные прогоны не удалены; их scope не расширяется при переносе в новую сцену.

## Критические пробелы и конструктивные исправления

| Приоритет | Факт / риск | Требуемый выход |
| --- | --- | --- |
| P0 |Manifest/defaults PS/Python/Electron согласованы fixtures; whole-profile/live/UI/Rust portability ещё не приняты |B0: один воспроизводимый effective профиль, реальная identity/readiness |
| P0 |Native upload/final cancellable, mock Stop+join<1s;22 Rust unit+1CLI PASS. Streaming ASR scoped child/reap и HTTP fence:17+9 tests PASS. Transport abort не доказывает real-model release |B1: actual-model latency/cancel и device/whole-turn acceptance; desktop partial UX, descendant containment OPEN |
| P0 |TTS scoped cancel и actual Tera CPU service probe PASS12Oct:idle102.8ms/3WAV, own Job proof. Daily9889 не принят; first-audible/p95/акустика/whole-profile OPEN |B1/B2: real replacement timing, WORLD/other providers, bare disconnect и whole RU route. Busy остаётся bounded отказом при uncooperative owner, не premature release |
| P0 |Owned HTTP admission закрывает late dispatch/duplicates в TTL scope; default client POST abort/deadline проверен loopback, exact-ID cancel независим. Socket EOF не compute release |B1: actual selected-model slot release и current voice/task continuity. Restart/cross-transport durable dedup и opaque opener reap отдельно; protected snapshot immutable |
| P0 |Нет принятого current full voice path и физического duplex |B2: real RU route, stage timings, acoustic echo/barge-in |
| P0 |Voice cancel и durable task связаны не полной приёмкой |B3: interrupted speech не теряет поручение и не повторяет эффект |
| P1 |Главный app UX не имеет полной history/attachments/library/tasks/settings parity |U: inventory→contract→round-trip→actual user acceptance |
| P1 |Ambient T1/T2 process-local; clear не erasure T3 |P: persistence/consolidation/provenance/correction/retention/erasure |
| P1 |Own browser adapter — openURL/UIA, не CDP; успешный opener не loaded page |B3: DOM/CDP isolation и postcondition, не только dispatch |
| P1 |Vision/system audio код не доказывает постоянный полезный контекст |P: свежесть, attribution, source trust, priority и closed-loop acceptance |
| P1 |Длительная unattended и полный stop/revoke не приняты |B4:8h disposable run с контролируемыми сбоями и утренним журналом |
| P1 |VRM технически валиден, но внешний вид/физика не соответствуют финальной приёмке |A: art rubric/closeups/physics matrix отдельно от export |
| P1 |Много dirty changes; нет проверенного release baseline/rollback всего профиля |B0/B4: reviewable baseline и воспроизводимая поставка |
| P2 |Непринятые audio-caption/affect и stream/social integrations |P/S: отдельные capabilities, без model download/rewrite по умолчанию |

Не урезать native tools/goal/Heartbeat ради latency и не добавлять второго
агента. Измерить bottleneck, уменьшать bounded context/очереди/дублирование,
сохраняя discovery и нативную policy. Механизмы Companion, уже лучше
подходящие сценарию, не перезаписывать механически upstream-версией.

## Приёмочная матрица

Это критерии завершения; не отдельный список задач. Реализация ведётся в TODO.
`OPEN` означает, что полный актуальный результат не принят; код может существовать.

| ID | Сценарий и обязательное наблюдение | Текущая граница |
| --- | --- | --- |
| M01 |Regression: compile/unit/HTTP E2E/Node/browser, snapshot/hash/secret/diff checks |12OctMoscow PASS:779/66/16/86/6/8, direct child exit0 + receipt; synthetic/mock scope,343 source hashes matched |
| M02 |Cold start, actual model/context/capability identity, ports, worker failure, graceful stop |Частичные slices; current whole profile OPEN |
| M03 |100 correlated native chat turns: one terminal result, JSON errors/timeouts/reconnect/cancel |OPEN; число100 — acceptance target, не выполненный счётчик |
| M04 |Persona/SOUL/traits/facts меняют смысл text+voice ответа и переживают restart |Ранее memory slices; current combined OPEN |
| M05 |Observation→attention→JAWL decision→feedback→memory/task, нет double wake/answer/action |OPEN |
| M06 |UI и voice поручение→native tool→disposable effect→postcondition/artifact→task update |Ранее native slices; current combined OPEN |
| M07 |Fast chat vs explicit goal, reasoning capability, краткие voice checkpoints |OPEN |
| M08 |≥3RU synthetic questions в actual app через real ASR/JAWL/TTS, смысл ответа и timings |Synthetic mocks PASS; current real-provider OPEN |
| M09 |Physical mic, device/gate/slow speech/pauses, echo, duplex/barge-in, no own-TTS command |OPEN |
| M10 |TTS first audible/cold/warm p50p95, supported emotion/fallback, stale drop, worker release |Controlled real Tera cancel+3WAV PASS12Oct; first-audible/p95/emotion/acoustic/whole-profile OPEN |
| M11 |Speech cancel≠goal cancel; interruption/provider failure/restart без потери задачи/дубля |Native crash slices PASS; current voice continuity OPEN |
| M12 |Native levels0–3, discovery/namespace representative risk fixtures, deny/revoke/audit |Ранее representative PASS; полный current matrix OPEN |
| M13 |8h unattended, panel closed, Heartbeat/goal, worker crash/lease expiry/Stop, morning journal |OPEN; короткие/прерванные runs не8h PASS |
| M14 |JAWL typed memory, provenance/contradiction/revise/restart recall/forget/physical erasure |Часть real slice; полный lifecycle OPEN |
| M15 |T1→T2→JAWL persistence/TTL/dedup/auto consolidation, source not USER_FINAL |Manual/process-local minimum; target OPEN |
| M16 |Physical long system audio, segment rotation, TTS overlap, speech priority/bounded RAM |Код/синтетика есть; long physical OPEN |
| M17 |Fresh RU screen/VLM/UIA→plan→native action→new postcondition; stale/deny/degraded |Код/отдельные profile slices; current whole OPEN |
| M18 |Music/non-speech/voice-affect реальные annotated samples, uncertainty, no diagnosis |Adapter seam; accepted model capability OPEN |
| M19 |Unified panel inventory/readback/effective/restart, history/attachments/memory/tasks |Partial; full JAWL parity OPEN |
| M20 |LAN HTTPS/auth/Origin, actual tablet/mobile touch/keyboard/mic/reconnect |Security foundation; physical OPEN |
| M21 |Actual VRM OBS source: shared state, privacy, one audio owner, DPI/multimonitor/lifecycle |Legacy boundary evidence; current VRM/installed OBS OPEN |
| M22 |Avatar ≥90rubric, four views/closeups/motion; cloth/body/hair collision matrix |V9 limited geometry PASS; art/full physics OPEN |
| M23 |Animation graph/VRMA retarget/gaze/mimic/lip timing; cancel/swap/reduced motion |Procedural/RMS foundation; target OPEN |
| M24 |RAM/VRAM/CPU/frame-time/token/log/queue budgets, game/voice priority |Частичные limits; whole profile measurement OPEN |
| M25 |Clean install outside cwd, versions/hashes/licenses, upgrade/backup/restore/rollback |Wheel smoke; whole release OPEN |
| M26 |Stream chat/social: untrusted input/scopes/moderation/idempotency/privacy |Future integration; OPEN or explicit release-scope exception |

## Протокол доказательства

Для каждой применимой строки: commit+dirty-diff/hash, profile, model/worker/
asset/config versions, run/turn/generation IDs, вход, ожидание, наблюдение,
timings, screenshots/аудио/артефакт по необходимости, pass/fail/skip и exit code.
Logs redacted/bounded, без ключей/raw TTD/скрытого chain-of-thought.

Различать: unit, mock HTTP, synthetic media, real provider, real device,
installed OBS, owner visual acceptance. `queued`/`configured`/HTTP200,
DOM marker, закрытый socket или finite rotations не доказывают конечный результат.
SKIP/N/A требует причины/области релиза и не становится PASS.

Docs-only validation — ссылки/согласованность/`git diff --check`; runtime
gates не запускать ради изменения текста. RC — после цельного ежедневного
сценария; production-ready — после всей применимой матрицы и пользовательской
приёмки, с явными согласованными исключениями.

## Исторические диагнозы

Legacy-A3: старый smoke мог затрагивать protected runtime/небезопасный cleanup.
Сейчас source `run_target_jawl_smoke.ps1` содержит explicit-Live, owned marker,
protected-root/no-reparse и shared-env guards. Это статическое улучшение, не
новая live safety-приёмка. Скрипт не применять без отдельной review/acceptance
owned layout/loader/process ownership; историческую причину не выдавать за
сегодняшнее воспроизведение.

R1–R4, provider failures, пяти failed recall attempts и исходный HTTP503
сохранены в исходном аудите/recovery в архиве. Некоторые причины уже закрыты
поздними slices; нельзя повторно выставлять их активным блокером по старой дате.
Если для historical503 нет конкретного закрытия, он остаётся диагностическим
долгом B3-08, не утверждением о сегодняшнем воспроизведении.
