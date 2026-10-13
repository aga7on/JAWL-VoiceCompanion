> Исторический снимок 2026-10-10. Исходный путь: `docs/TECHNICAL_AUDIT.md`.
> Не текущие инструкции. [Текущее состояние](../../../STATE.md),
> [активная очередь](../../../../TODO.md), [карта](../../../README.md).
> Старые относительные ссылки/команды читать от исходного пути, см. INDEX архива.

# Аудит продукта, архитектуры и доказательств

## Последняя дельта — 2026-10-05, seam acceptance вместо узких проверок

Успешные wrist-weight/closed-sole проверки не обнаруживали разрывов одежды.
Interface V9 добавляет evaluated radial coverage в rest/16 isolated poses на
двух сторонах: все 34 wrist + 34 ankle checks PASS после исправления contour,
UV weld/offset порядка и barycentric weights. Geometry/browser regression PASS;
run IDs/SHA — [STATE](STATE.md), детали — [review](CHARACTER_INTERFACE_V9_REVIEW.md).
Нельзя называть это full cloth/body physics или numeric exported runtime seam
acceptance. Край манжет/язычки/шнуровка художественно не приняты, ≥90% OPEN.
Последующие дельты — история своих срезов; полный backend gate ниже актуален.

## Последняя дельта — 2026-10-05, Hair V8 / scene lifecycle

Смена avatar теперь снимает старые additive offsets/aa до disposal и сбрасывает
lip target нового rig; stale/failed load сохраняет текущую модель/state. RMS
ограничен finite/[0,1]/speaking, не выдаётся за vowel-aware lip-sync.
Full gate exit 0: 551 unit / 16 HTTP E2E / 75 Node / 6 legacy browser /
26 desktop synthetic условий; real RU/device остаётся отдельной приёмкой.
Исправлен material pointer API, VRM export подтверждает 12 texture-free flat
материалов. Hair V8 rest surface overlaps с Face = 0, actual solver smoke PASS;
[art review](CHARACTER_HAIR_V8_REVIEW.md) не закрывает ≥90/all-pose physics.
Подробные SHA/run IDs и границы — [STATE](STATE.md); последующие записи ниже
являются историей соответствующих срезов, не актуальной сводкой.

## Последняя дельта — 2026-10-05, после AIRI research

Новый full gate exit 0: 551 unit / 16 HTTP E2E / 72 Node / 6 legacy browser /
26 desktop synthetic условий; evidence — [STATE](STATE.md). TTS transport
теперь ограничивает весь входящий поток 64 MiB до decode/split, включая
whitespace/служебные данные; 21 stream regression test PASS. Это не замер
peak RAM и не доказательство остановки native worker по transport abort.
Hair V7 прошёл технические проверки; [review](CHARACTER_HAIR_V7_REVIEW.md)
сохраняет открытые художественные/physics критерии. Старые baseline/counts
ниже относятся к своим срезам, не заменяют эту дельту. Реальная RU/device
приёмка и design-kit gates не закрыты общим synthetic regression gate.

## Активная граница — 2026-10-05

Текущее состояние и evidence: [STATE](STATE.md), [поставка персонажа](CHARACTER_DELIVERY_20261004.md).
Записи ниже — исторические проверки сентября, не текущий диагноз каждого
дефекта. Основной клиент теперь Electron `/app` + VRM (ADR-045–046).

Исправлены несовместимость NDJSON/Blob и пропущенный static route
`/voice-input.js`. Последний дефект нашёл actual browser capture, а не Node
helper tests. Baseline full gate exit 0: 534 unit / 16 HTTP E2E / 57 Node /
6 browser / 13 desktop synthetic voice условий. Критерий всё ещё разделяет
synthetic MediaStream + mock ASR/JAWL/TTS и real provider/device/barge-in.
Новые persistent capture settings/lifecycle приняты отдельным full gate:
543 unit / 16 HTTP E2E / 68 Node / 6 legacy browser / 26 desktop synthetic
условий, exit 0. Capture errors redacted, unsafe YAML writes fail-closed;
owned-test resource leaks исправлены. 47 warnings immutable config_io остаются.
Real provider/device и canonical voice-cancel→durable-goal continuity не закрыты:
existing recovery evidence относится к crash/restart, не пользовательскому Stop.
Evidence — [STATE](STATE.md). Design-kit mandatory gates тоже не закрыты.

Art acceptance остаётся открытой: VRoid face/rig улучшает прототип, бомбер
уже заменил hoodie, но лицо/пробор, посадка cargo/плеч и материалы не приняты.
Отдельные V3 blocking и [Fit V4](CHARACTER_FIT_V4_REVIEW.md) проходят свои
export/solver/rest-geometry checks; это не likeness ≥90 и
не all-mesh collision acceptance. Вторичная weighted-bone инерция отдельно
проверена и не называется полной физикой ткани/тела. Animation graph —
[следующий план](AVATAR_ANIMATION_PLAN.md), не уже внедрённый Source 2.

## Исторический аудит — 2026-09-06

Актуальные findings и порядок исправлений: [RECOVERY_PLAN](RECOVERY_PLAN.md).
Срез: HEAD `1bb3117` плюс три dirty config/prompt/patch файла.
Проверены текущий код, Git diff и сохранённые JSON/логи; live запуска не было.

- P0: hardcoded `set_execution_blocklist(["HostOS"])` в owned snapshot,
  ограниченный native catalog и запрещённый discovery расходятся с Full Access
  и обязательными поручениями. Исправлять через native policy и bounded lookup.
- P0: записанный context patch не разбирается Git (`corrupt patch ...:76`).
  `copy_missing` не доставляет обновления в существующий профиль.
- P0: пять свежих recall reports failed. Один gateway pass (~48 с)
  не закрывает совместимость модели, память и connected daily scenario.
- P0: browser voice harness обходит capture/gate и штатный playback/avatar;
  нет достаточной проверки смысла ответа и terminal error.
- Исходный 503 при установке уровня 3 остаётся unexplained. Утверждение,
  что это deliberate emergency-stop fixture, не соответствует traceback
  `runtime/full-gate-20260905T101053Z.log:670`.

Следующий путь: R1 воспроизводимость/tools → R2 turn/memory → R3 browser voice
→ R4 native task/recovery/full gate. Код этих исправлений пока не реализован.

## Исторический аудит 2026-09-05

Ниже сохранены первоначальные findings и общая матрица. Датированные статусы
и указания «следующий шаг» читать с учётом текущего аудита выше и RECOVERY_PLAN.

2026-09-05. Документальный аудит: требования владельца → документация →
выборочная проверка исходников и существующих отчётов. Это не полный code/
security audit и не новая live-приёмка. Исходный аудит был docs-only;
последующий частичный readiness-срез описан ниже и в STATE.

## Вывод

Направление жизнеспособно, но проект пока **интеграционный прототип**.
Самая большая опасность — принять коллекцию исправных адаптеров и скриптов
за готового компаньона. До RC нужен целый сценарий из [PRODUCT.md](PRODUCT.md),
а не ещё один отчёт о независимых HTTP endpoint.

Обнаружен перекос плана: native testing/release tooling вытеснили удобный
диалог, управление характером, задачу на ПК и ощущение одного персонажа.
Full Access, VoiceMem и агентный JAWL контур сохраняются в продукте.
Исправления ниже — задачи, не якобы уже устранённые кодовые дефекты.

## P0: критические изъяны

### A1. Невоспроизводимая зависимость и protected upstream

В `G:\AI\JAWL-Coding` изменены native web/policy/heartbeat и есть untracked
`companion_gateway.py`, `structured_memory.py`, `autonomy.py`.
В Companion это описывалось как законченная часть платформы без зафиксированной
поставки JAWL. Git status/timestamps не доказывают авторство или разрешение.

Исправление: инвентаризация минимальных зависимостей, согласованный owned
runtime/fork или зафиксированная совместимая dependency, versions/capabilities,
clean startup. До этого запрещены правки и runtime-запись в protected repo.
Не сбрасывать чужие changes и не копировать рабочие credentials.

### A2. Ошибочная готовность и несвязанные smoke-проверки

В первоначальном срезе `__main__.py` без flags выбирал `phase1_mock_brain`.
`doctor.py:build_doctor_report` считает некоторые `configured` ready; Vision/
ambient проверяются по наличию конфигурации. `run_target_release_profile.py`
читает Companion и отдельно JAWL; не посылает коррелированный turn через bridge.
Dependency check принимает HTTP 200, не проверяя реальную model readiness.
Native policy check не утверждал `authority=jawl` как обязательный инвариант.

Последующее частичное исправление: doctor больше не принимает configured
за готовый JAWL/Vision/ambient; dependency probe требует явные положительные
health-маркеры, policy check требует authority=jawl и уровень 0–3.
Unit и focused fake HTTP evidence — в STATE. Identity, профиль capabilities
и связанный live proof-of-path ещё не сделаны; A2 не закрыт целиком.

Исправление: readiness профиля с обязательными capabilities, instance identity
и proof-of-path. `not_configured`, `loading`, `offline`, `mock`, `ready`
не смешивать. Отдельная проверка выполняет безопасный запрос через тот UI/API,
которым пользуется владелец, и связывает ответы всех компонентов.

### A3. Небезопасный и машинно-зависимый test launcher

В исходной версии `scripts/run_target_jawl_smoke.ps1` по умолчанию использовал
data/logs внутри protected JAWL, фиксированные dated paths/report и запускал
native runtime.
В cleanup он добавляет текущих владельцев порта в список для Stop-Process:
свободный порт до старта не доказывает, что его будущий владелец — наш процесс.
Токен передаётся в argv. В native `src/main.py` сначала загружается общий
`.env`, затем instance env; переопределение только provider URL/key не изолирует
остальные credentials и автозапускаемые интеграции.

Исправление до повторного запуска: disposable directories вне upstream,
явный live opt-in, allowlisted environment/config, отключённые посторонние
integrations, process ownership + creation time/job tracking, безопасная
передача токена, redaction, unique run ID, fail report и bounded cleanup.
Этот wrapper **не рекомендован к запуску**. Третий revision принят main как
PARTIAL offline safety slice: Gauss' unittest — 8 OK без skips, PS AST pass и
diff pass; AST-extracted PS helpers проверены для CreateNew nonoverwrite,
containment и отказа файла под junction. Unsafe defaults/token argv/arbitrary
port-owner killing убраны; добавлены env allowlist, protected paths, explicit
Live/owned marker и bounded profile deadline.

Это не закрывает A3 и не доказывает полную безопасность: LIVE запуск запрещён
до owner-approved runtime/loader review и полной isolated process lifecycle
validation. Cleanup parent-exit race может оставить orphan; нужен отдельный
доказанный lifecycle result.

### A4. Голосовой worker benchmark подменяет разговор

Qwen-ASR обрабатывает final utterance, не partial stream. VoiceMem enrichment
асинхронен, но `queued` не доказывает сохранение и recall. Audio profile не
проверяет native LLM identity; `end_seconds` не включает весь TTS/playback.
Текущие TTS workers whole-WAV, cancel транспорта может оставить inference
занимающим worker. Для Qwen Base нет проверенного cloned emotion control.

Исправление: correlated browser→ASR→JAWL→TTS→audible path, stage timings и
cold/warm p50/p95; настоящий cancel/release worker; RU оценка пауз/шума/
barge-in. Qwen основной желаемый, Tera явный быстрый профиль, без скрытой
подмены и ложного real-time. Пока владелец недоступен — синтетика с честной меткой.

### A5. Полнота агента, UX и безопасная автономность не приняты

Есть native tool catalog и отдельные safe probes, но это не весь пользовательский
сценарий действий/восстановления. Inline-персонаж — CSS fallback, не произвольный
Live2D model mirror. UI smoke проверяет строки DOM; не проверяет удобство,
persona/задачи, сохранение настроек и визуальное качество.

Исправление: приоритет диалог+черты+память+реальное поручение в общей панели,
затем unattended на заданный период, checkpoints/reconciliation и утренний
журнал. Не урезать нативные инструменты второй sandbox Companion.
Новая фраза отменяет устаревший ответ, не уничтожает порученную фоновую задачу.

### A6. Единственная authority ещё не гарантирует цельное поведение

JAWL как единственный tool/memory owner — необходимая граница, но её
недостаточно: независимые Heartbeat, Attention, voice finalization и triage
могут давать дубли wake/ответов, устаревший контекст и несогласованные реакции.
Это архитектурный риск, не уже воспроизведённый дефект каждого из этих путей.

Исправление: карта перекрытий механизмов, общий bounded state/context snapshot,
один владелец решения, согласованные clocks/correlation и обратная связь
от проверенных действий. Добавить coherence E2E к подсистемным тестам.
Эволюционировать минимальный цельный цикл JAWL, переиспользуя только полезные
части VoiceMem/референсов; не собирать несколько самостоятельных когнитивных
циклов и не усложнять код нейробиологической терминологией.

## P1: важные незакрытые границы

- **Ambient частично исправлен, но не принят как production.** Companion теперь
  имеет time/audio-size segmenter, idle rotation, finite queues, byte/drop
  counters, generation fencing и явный Start/Stop lifecycle. Synthetic ambient
  suite и full gate прошли. Не доказаны физический loopback весь день, live ASR,
  длительный soak, per-app attribution и durable T1/T2 recovery после restart.
- **Приватность mixed audio.** Общий WASAPI output не знает достоверно источник
  каждого звука. Foreground deny-list не гарантирует исключение частного
  разговора в другом приложении. Нужна source-specific capture либо явная
  пауза/раздельный output. Self-TTS suppression по времени имеет потери.
- **Автопамять.** Ручная promotion есть, но пользователь хочет естественный
  жизненный цикл памяти. Добавить JAWL-controlled consolidation в обычном
  профиле после первичной настройки источников/разрешений,
  provenance/validity/contradictions/forget; не принимать медиа за слова владельца.
- **Забывание.** Append-only forget/archive исключает из контекста, не стирает
  старое значение. UI/дока должны различать логическое забывание и erasure.
- **Граф/дневник.** Daily journal уже описан в native structured memory, поэтому
  требование второй модели дневника удалено. Graph capabilities зависят от
  Python/env: stub не live Graph RAG; отдельный 3.11 runtime не делает 3.14
  автоматически совместимым. Нужна матрица, а не общая «Python ≥3.10 supported».
- **Жизненный цикл событий.** SSE наличие не доказывает streaming генерацию.
  Tool lifecycle summaries могут приходить после final. Replay dedup не
  гарантирует exactly-once side effects; нужны effect-level idempotency и
  сверка состояния после crash, без слепого retry.
- **Vision.** Stale tokens и координаты проверяются, но движение курсора не
  доказывает успех в приложении. После действия нужен новый кадр/postcondition.
  Постоянную модель не выбирать без владельца; CLI/UIA не должны ждать VLM.
- **Дизайн/2D.** Нужны безопасный общий renderer, audio ownership, реальные
  OBS/transparency/DPI и длительный прогон. Licensed asset pending не блокирует
  остальной UX на fallback.
- **Лёгкость.** Большие web.py/index.html можно делить по ответственности без
  тяжёлого framework. Число строк не критерий качества; startup/RAM/CPU,
  понятность и отсутствие дублирования — критерии. Не наращивать тестовые
  wrappers быстрее, чем готовые пользовательские функции.

## Коррекция прежних выводов

1. Убрано «release candidate in validation»: ежедневный integrated сценарий
   ещё не принят. Fallback/demo не скрывать.
2. Старое утверждение «full gate 252+14» заменено сохранённым отчётом
   `runtime/full-gate-20260905T101615Z.json`: exit 0, 299 non-E2E и 16 HTTP E2E.
   Это fake/synthetic regression. В предыдущем запуске получен HTTP 503;
   причина остаётся неизвестной, успешный повтор не закрывает расследование.
3. Big Pickle 100-turn pass не потерян: существующий JSON отчёт подтверждает
   отдельный native gateway profile через relay. Не заставлять повторять
   его без причины; повтор нужен при изменении runtime/provider/контракта.
4. 114 skills и 0–3 availability — catalog projection, 8 read-only probes и
   filesystem mutation — representative execution. 35 Debug operations metadata
   не означают 35 выполненных операций. Проверять риски/пути, не запускать
   разрушительное на живом ПК ради покрытия.
5. Target smoke с sink/placeholder подтверждает доступность отдельных
   поверхностей, не Companion↔JAWL↔LLM integration.
6. 5 degraded restart cycles занимают суммарно около 5.45 s; это startup/
   teardown smoke, не extended/night soak. Wheel import/--help не clean
   install всего продукта. Headless DOM не visual acceptance.
7. Записи 1679/13 JAWL и прежние provider availability — исторические,
   не текущая проверка. Не обещать «все free модели работают» без нового запроса.
8. Ошибка получения вывода долгой tool-сессии не является сама по себе багом
   runtime. Сохранять session ID/exit code/отчёт, не подменять это предположением
   об orphan-процессах и бесконечным повтором gate.

## Приёмочная матрица

Для каждого результата: дата/run ID, checkout/version или dirty diff hash,
profile/capabilities, вход/ожидание/наблюдение, pass/fail/skip + причина,
exit code, redacted report. Mock, synthetic, live provider и physical device
обозначаются раздельно. Числа ниже — критерии приёмки, не обещанные результаты.

| Путь | Минимальное доказательство |
|---|---|
| Regression | Один завершённый full gate: compile/non-E2E/HTTP E2E/mic gate/Node/diff, сохранённые ошибки |
| Startup | Clean runtime, верная identity всех required components, no mock substitution, graceful stop/port conflict |
| Диалог | 100 native correlated turns выбранного профиля + ошибки/empty JSON/reconnect/cancel; реальный bridge |
| Согласованность | Observation→решение→verified feedback→memory/task; без двойных wake/ответов/actions, согласованный text/voice/avatar |
| Характер | Изменённая черта/факт влияют на следующий голосовой и текстовый ответ; сохраняются после restart |
| Поручение | UI/голос → задача JAWL → native инструмент → проверка результата → понятный итог/артефакт |
| Голос | 3+ RU synthetic questions с pacing/паузами; затем dynamic mic/AEC; полная latency p50/p95 |
| TTS | Qwen/Tera capabilities, first audible, RU качество/эмоция fallback, stale suppression и worker release |
| Tools/policy | 0–3 deny/allow/approval и safe representative tests по каждому нужному namespace/risk, native audit |
| Автономность | 8h разрешённых disposable задач, закрытая панель, crash/recovery/lease expiry/stop, утренний журнал |
| Память | Source/contradiction/revise/forget/retention/restart/recall; explicit erasure semantics |
| Ambient | Длительная ротация audio, TTS echo/overlap, CPU load, no USER_FINAL/tools, attributed consolidation |
| UI/2D/OBS | Browser interaction+скриншоты+оценка владельцем; общий state, один звук, real OBS/DPI/8h |
| Vision | После выбора модели: fresh capture → plan → native action → новый postcondition; deny/stale cases |
| Поставка | Вне repo cwd: install/start выбранного профиля, versions/licenses, backup/migrate/rollback, secrets check |

Мажорное обновление: весь local gate + весь основной пользовательский E2E
сценарий и затронутые live строки. Unit tests недостаточны. Deferred функции
явно помечать; не объявлять весь обещанный продукт production-ready, если
из приёмки незаметно исключены голос, autonomy или avatar.

Для docs-only достаточно ссылок/согласованности/diff; тяжёлый внешний запуск
не нужен и не разрешается автоматически документационной задачей.

## Порядок исправления

[TODO.md](../TODO.md): P0-A ownership/runtime/harness → P0-B цельный
диалог+поручение вместе с P0-C голосом/UX → P1 автономность/память/2D →
Vision по выбору → полная приёмка. Независимый полезный срез можно продолжать,
если отсутствует конкретная модель или ассет.

Ключи TokenRouter и OpenCode, опубликованные владельцем в чате, должны быть
заменены владельцем. Этот аудит не проводил полный secret scan и не утверждает
отсутствие ключей в history/logs. Никаких самовольных revocation, UAC/EULA или
изменений в protected repositories.
# 2026-09-07 read-only upstream status note

На текущем read-only осмотре `G:\AI\JAWL-Coding` уже обнаружен dirty
worktree (изменённые tracked-файлы), а `G:\AI\VoiceMem` также содержит
локальные изменения/артефакты. Авторство этих изменений этим аудитом не
устанавливается. Companion их не откатывает и не переписывает; для live
запуска используется отдельный pinned snapshot с независимым SHA-256.

