# Запуск профилей, сборка и будущая поставка

## Актуальный статус — 2026-10-12

После документального аудита начат code slice B0 (2026-10-10): общий manifest,
launcher defaults и preflight. Результат полного gate — в STATE. Текущий UI —
Electron single-window `/app` с VRM three-vrm; JAWL остаётся единственным
агентом, VoiceMem — сенсорным слоем. Выбранный target: Bonsai-2 27B Hikari
PQ2_0 / GPU 1, GigaAM v3 only, TeraTTS ru_f1 default на 9889, OmniVoice как
выбираемый TTS; Bonsai 8986 настроен для vision без заявления полной
OCR/grounding acceptance. Python, два основных PS launchers и Electron теперь
используют этот manifest. Rust получил bounded local overlay и discovery;
полная differential parity и portable installation OPEN.

Текущая safety-граница: `scripts/run_target_jawl_smoke.ps1` не применять до
отдельной review и acceptance owned runtime/layout, native loader и process
ownership/lifecycle. Source содержит explicit-`-Live`, owned-marker,
protected-root, no-reparse и shared-`.env` guards. Их наличие — статическая
защита, не live acceptance.

### Общий профиль и границы launchers

Daily/integrated launchers используют выбранный owned Python в форме
`python -B scripts/run_owned_jawl_console.py ...`.
Entry проверяет immutable snapshot и все instance/registry paths, добавляет
bounded HTTP admission после native auth и редактирует startup console tokens.
Core JAWL/ChatBridge не копируется/не патчится. Integrated readiness требует
`/api/companion/admission-capabilities`, feature `http-turn-admission-v1`.
Прямой `python -m src.web.server` не имеет этой защиты и не является daily
Companion entry. Исходный JAWL-Coding остаётся read-only референсом.
Actual isolated console probe PASS12Oct не доказывает whole-profile/model/device
readiness; параметры/TTL и ограничения — [контракт](contracts/jawl.md).

Default client turn/cancel POST используют scoped socket abort и абсолютный
deadline;13 HTTP/TLS +3 native-adapter loopback tests входят в unittest gate.
Для ephemeral TLS cert fixtures нужен pinned `requirements-dev.txt`
(`cryptography` только test dependency); production runtime не расширяется.
Этот gate не подтверждает освобождение compute выбранной LLM.

Selected-model diagnostic (не daily launcher) требует явного opt-in:
`python -B scripts/run_llm_model_cancel_acceptance.py --allow-cpu-model --report runtime/llm-model-cancel-cpu-new.json`.
Не повторять без новой гипотезы: оба actual CPU runs12Oct FAIL35s; reports retained,
canonical GPU1/65536 не менялся. Протокол — [benchmark](LLM_MODEL_CANCEL_BENCHMARK.md).

| Источник / профиль | Параметры по source или выбранный target | Как соотносится с target |
|---|---|---|
| `config/runtime.manifest.json` | console8770/control2367/presentation8766/Tera9889/brain8990; RunSeconds0; local-bonsai2, Hikari PQ2_0, ctx65536, output2048, CUDA1 | Canonical defaults; configured не означает live ready |
| `run_local_bonsai_integrated.ps1` | Manifest + explicit overrides; поднимает supervised Hikari holder, затем integrated | Preflight до holder; health + exact alias; daily до остановки, smoke60s задаётся явно |
| `run_integrated_profile.ps1` | Тот же manifest, Tera paths, vision8986 alias bonsai; owned JAWL/Companion | Сам по себе не поднимает primary brain; screen-watch opt-in, нет auto GPU0 launch |
| `run_coding_server.ps1` | Port 8986, Bonsai-27B-Q1_0, taardis server | Отдельный legacy coding/chat server; не Hikari brain и не доказательство выбранного vision runtime |

Сначала проверить effective конфигурацию без запуска моделей/устройств:

```powershell
python -B scripts/resolve_runtime_manifest.py
```

Не копировать секреты в manifest. `config/runtime.manifest.local.json`
(gitignored) содержит только изменённые поля и deep-merges canonical JSON.
Явные CLI параметры приоритетнее manifest. Brain URL должен совпадать с
brain_port; reserved8765, collisions, неверные aliases/paths/limits отклоняются.
`--manifest`/`-ManifestPath` выбирает alternate canonical и sibling local file.
Electron поддерживает canonical/local control port и env override; не начинает
второй model runtime. При ошибке manifest не подключается молча к2367.

Local wrapper поддерживает `-ProfileName <owned-name> -NoBrowser` и передаёт
temperature явно; больше не применяет overrides к hardcoded daily. Integrated
блокирует профиль до prepare/native configure и освобождает lock при отказе.
Для acceptance использовать новую instance, не daily. Это пока не live startup
acceptance: сначала проверить resource availability, GPU1 mapping и VoiceMem
storage/cache isolation. Занятые порты/модели не «освобождать» чужим kill.

Для согласованного ограниченного startup smoke после проверки ресурсов/consent:

```powershell
.\scripts\run_local_bonsai_integrated.ps1 -RunSeconds 60
```

Без `RunSeconds` daily работает до остановки. VisionUrl/VisionModel передаются
wrapper→child явно; endpoint сам не запускается. Пример не является новой live
приёмкой. Legacy Qwen/mmproj пути на текущем диске отсутствуют: они optional,
не основание автоматически скачать модель или заменить primary brain.

Reviewable baseline без git commit:

```powershell
python -B scripts/capture_runtime_baseline.py --report runtime/baseline-unique-run.json
```

Report должен быть новым JSON внутри runtime. Он хранит HEAD, dirty-diff и
source hashes, pinned snapshot, версии Python/packages, worker/VRM inventory.
Сырые diff/код/env/PCM туда не попадают; большие GGUF имеют metadata, не полный
weight hash. Baseline не доказывает active avatar selection, art или clean install.

Wheel smoke подтверждает только ограниченный package/import/startup сценарий.
Он не равен full clean install, полной матрице внешних ресурсов, проверенной
миграции данных или rollback. RC/production readiness не заявляются без
сценариев и приёмки, указанных ниже. Не заменять исторические PASS/FAIL и
числа новой интерпретацией. [Карта](README.md) · [STATE](STATE.md) ·
[очередь](../TODO.md).

## Исторические инструкции по запуску и поставке — срез 2026-09-05

Все следующие команды и примеры сохранены как инструкции того среза. Они не
являются актуальным рецептом запуска/установки; перед применением нужно
сверить конкретные параметры с выбранным профилем и source. Выше находится
текущая граница и таблица расхождений launcher defaults.

Исторический срез 2026-09-05: проект — **интеграционный прототип**, не RC.
Wheel не содержит JAWL, VoiceMem, model weights и лицензируемый Live2D bundle.
Следующие команды — существующие интерфейсы разработки, не «установка готового
компаньона». Аудит/ограничения — [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md).

Профиль runtime описывается bounded JSON-manifest без секретов:
`config/profile.example.json`. Его можно проверить без запуска сервисов:

```powershell
python scripts/validate_profile.py config/profile.example.json
```

Manifest фиксирует относительные config/data/log/cache/sandbox пути, control и
presentation ports, зарезервированные соседние порты, версии компонентов и
consent. Он пока не является one-click installer и не подменяет pinned JAWL
runtime; это первый P0-A контракт воспроизводимой поставки.

## Историческая диагностика A3 — архивный снимок 2026-10-10

Архивное описание предыдущей версии launcher-а утверждало, что runtime/logs
могли попадать в protected JAWL и cleanup небезопасно определял владельцев
процессов. Это исторический диагноз, сохранённый в архивном аудите; дата
первичного диагноза там не указана. Его нельзя считать воспроизведённой
проблемой текущего source. Текущий source содержит перечисленные выше guards,
но их наличие само по себе не является live acceptance и не снимает требование
отдельной review/acceptance owned layout и lifecycle.

`G:\AI\JAWL-Coding` — read-only reference, включая runtime/config/data/logs.
Нужен отдельный согласованный JAWL runtime; его provisioning/versioning —
P0-A в [TODO](../TODO.md). Нельзя ради smoke менять рабочий JAWL, его policy,
ключи, MCP/Telethon или приложения пользователя.

Токены заранее поступают из локального хранилища в environment. Не указывать
их значения в CLI arguments: они попадут в argv/history. Native профили
различаются именами env vars; проверить parser, не копировать ключи в файлы.

## Историческая инструкция: демонстрация UI

```powershell
cd G:\AI\JAWL-VoiceCompanion
.\scripts\run_web.ps1
```

По умолчанию deterministic mock, dry-run; control 2367 и presentation/OBS
8766. Никакого «автоматически подключённого мозга». Порт 8765 занят FoxMCP
по конфигурации владельца и не должен использоваться нашим launcher.

Подключиться к уже подготовленному совместимому JAWL можно так
(`JAWL_WEB_TOKEN` уже установлен безопасным способом):

```powershell
.\scripts\run_web.ps1 --jawl-web-url http://127.0.0.1:8770 --jawl-hostos-control
```

Сначала проверить capability/instance, затем operator controls: изменение
уровня/stop/start меняет подключённый runtime. `--hostos-live` не заменяет
native JAWL и не является готовым Full Access профилем общей системы.

### Историческая инструкция: integrated JAWL profile и Full Access

Для connected runtime используйте `scripts/run_integrated_profile.ps1`. Его
безопасный default — native access level `0` и отключённый Debug Broker. Для
явного disposable Full Access/RE-профиля:

```powershell
$env:LLM_API_URL = 'http://127.0.0.1:11434/v1'
$env:LLM_API_KEY_1 = 'local-loopback'
.\scripts\run_integrated_profile.ps1 `
  -ProfileName native-integrated `
  -NativeAccessLevel 3 `
  -EnableDebugBroker
```

Launcher вызывает `prepare_daily_profile.py`, затем применяет только два
разрешённых profile override через `configure_profile_native.py`. Весь
каталог HostOS/HostTerminal/Debug Broker и side effects остаются native JAWL;
Companion не является fallback executor. `-NativeAccessLevel 3` означает
права текущего Windows-пользователя и не обходит UAC, ACL, EULA или TTD.
`G:\RE` используется как настроенный внешний tool root; upstream
`G:\AI\JAWL-Coding` не изменяется.

Принятый launcher live-срез:
`runtime/native-catalog-full-access-launcher-20260909-r2.json` и
`runtime/native-namespace-full-access-launcher-20260909-r2.json`.

## Исторические инструкции: голосовые workers

Запускать каждый выбранный worker в отдельной сессии: launcher остаётся
работать до остановки. Веса/окружения должны уже существовать; это не команды
загрузки моделей.

Qwen3-TTS Base — желаемый основной/clone профиль:

```powershell
.\scripts\run_qwen3_tts_server.ps1 -Port 9890 -Threads 24
```

TeraTTSv2 — быстрый CPU профиль рядом:

```powershell
.\scripts\run_teratts_server.ps1 -Port 9889 -Voice ru_f1
```

Русский final-ASR:

```powershell
.\scripts\run_asr_server.ps1
```

После readiness workers, в новой сессии (и при запущенном совместимом JAWL):

```powershell
.\scripts\run_web.ps1 --jawl-web-url http://127.0.0.1:8770 --jawl-hostos-control `
  --voicemem-python 'G:\AI\VoiceMem\.venv\Scripts\python.exe' `
  --voicemem-local-memory --voicemem-warmup text `
  --streaming-asr --streaming-asr-exe 'G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe' `
  --streaming-asr-model 'G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf' `
  --tts-url http://127.0.0.1:9890 --tts-provider qwen
```

Это составной **development пример**, ещё не принятый one-click профиль.
Для быстрого Tera заменить TTS URL на 9889 и provider на `tera`.
Нынешний default — Tera; автоматического fallback между workers не обещается.
Qwen CPU clone медленный и не имеет принятого emotion control.
Текстовый ответ без TTS остаётся допустимым degraded режимом, не voice acceptance.

Integrated launcher передаёт VoiceMem explicit memory-root в
`runtime/instances/<profile>/data/sensory/voicemem`; standalone CLI поддерживает
`--voicemem-memory-root`. Это sensory cache, не отдельный JAWL memory owner.
Пути model/HF/torch caches ещё проверить до live; interpreter path не разрешает
запись в upstream. GigaAM final транскрибирует whole utterance на end;
hands-free/real device качество отдельно, Qwen-ASR fallback отсутствует.
OmniVoice и CozyVoice не обязательны для этого профиля.

Системный звук — отдельный opt-in `--ambient-audio --ambient-memory`;
перед start выбрать источники/политику. Сейчас ASR flush на stop, не непрерывная
суточная сегментация. Модель music/sound captioning не выбрана.
Vision не запускать/фиксировать до решения владельца. OBS — [OBS.md](OBS.md).

## Исторические заметки: область проверок harness

| Инструмент | Реальная граница |
|---|---|
| run_full_gate.ps1 | Compile, non-E2E, fake-provider HTTP E2E, synthetic gate, Node, diff |
| run_browser_render_smoke.ps1 | Headless DOM markers, не визуальная/interactive приёмка |
| run_restart_soak.ps1 | Короткие startup/health/teardown циклы, не ночная работа |
| run_target_release_profile.py | Read-only co-availability поверхностей; не identity/LLM bridge |
| run_native_gateway_profile.ps1 | Opt-in native turns/cancel/reconnect выбранного JAWL/provider |
| run_native_namespace_profile.py | Read-only representative routes/catalog |
| run_native_catalog_matrix.py | Меняет policy/restart в disposable runtime; catalog availability, не все executions |
| run_native_action_profile.py | Mutating safe fixture slice, только disposable sandbox |
| run_native_policy_profile.py | Меняет policy/stop/lease и тестовый файл; не production endpoint |
| run_asr_profile.ps1 / run_teratts_profile.ps1 | Отдельный реальный worker на фиксированных WAV/text |
| run_voicemem_profile.ps1 | Process/VAD/fixture; bundled fixture не русский microphone test |
| run_audio_pipeline_profile.py | Audio routes/enqueue/TTS bytes; не native LLM identity/physical playback |

For the unattended production-duration check, use the isolated orchestrator:

```powershell
.\scripts\run_long_unattended_acceptance.ps1 `
  -ProfileName qwen-ollama-unattended-8h `
  -DurationSeconds 28800
```

It uses only the persistent local Ollama OpenAI-compatible endpoint, starts a
disposable level-3 profile on the requested Companion ports, writes separate
profile/soak logs, and verifies that all three owned ports close in `finally`.
It never uses FoxMCP `8765` or Ollama `11434` as disposable ports and does not
claim success until both the soak report and cleanup check pass. A short smoke
must be run before an eight-hour acceptance; this does not replace physical
microphone, OBS or provider-variance acceptance.

Наличие `--live` не делает окружение изолированным. До любого mutating
профиля проверить targets, cleanup, настройки и authority. Старые dated JSON
могут перезаписываться — использовать unique run IDs. Положительный target
report с fake provider sink не переносить в integrated acceptance.
Gateway 100-turn Big Pickle отчёт остаётся evidence своего disposable relay
профиля; нельзя обещать прямой или бессрочно бесплатный доступ.

## Историческая инструкция: сборка

Из нашего checkout:

```powershell
.\scripts\run_full_gate.ps1
.\scripts\build_release.ps1
```

Build создаёт `dist\wheel\*.whl` и `dist\SHA256SUMS.txt`.
Хеш — integrity record, не подпись и не проверка функционирования приложения.
Повторять сборку при изменении packaged inputs, не ради накопления pass-строк.

Перед release-приёмкой полный gate запускает
`scripts/release_secret_scan.py`. Он проверяет текстовые source/config/docs
inputs, исключает только сгенерированные `runtime`/`dist` деревья и в отчёте
сохраняет лишь путь, строку и категорию — значение совпадения никогда не
выводится. Отчёт последнего запуска: `runtime/release-secret-scan.json`.

Для изолированной установки использовать **новое** venv и ровно выбранный
wheel из манифеста; не force-reinstall рабочий профиль по glob. Проверить
package import, наличие frontend и CLI, затем реальный запуск из cwd вне repo.
Прежний import/--help smoke доказывал только layout/entry point.
Python/env и модельные зависимости фиксировать отдельно; требования
`requires-python` не равны полной Windows/model compatibility.

## Исторические инструкции: upgrade / rollback / выпуск

Перед изменением schema/версии сделать согласованный backup owned runtime.
Новая версия ставится рядом, проходит приёмку, затем operator переключает
launcher. Старое окружение сохраняется до принятия нового.
Откат бинарника не обещает откат несовместимой миграции данных: нужна
проверенная migration/restore стратегия.

Для RC сначала принять полный ежедневный сценарий; для production —
всю заявленную feature matrix и 8h профили, реальные устройства/UI/OBS,
clean install/restore и пользовательскую оценку. Отложенная VLM не блокирует
честно ограниченную версию, но не должна молча исчезнуть из общей цели.

Сохранять версии/checkouts/dirty diff hashes, profile/permissions,
requirements/models/assets manifests, expected/observed, pass/fail/skip,
полный exit code и redacted evidence. Не прикладывать секреты, raw TTD,
пользовательский PCM/screenshots. Публикация, подпись и лицензии — отдельный
осознанный шаг, не следствие успешного wheel build.
