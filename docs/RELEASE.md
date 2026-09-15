# Запуск профилей, сборка и будущая поставка

Актуально: 2026-09-05. Проект — **интеграционный прототип**, не RC.
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

## Важное ограничение live runs

Не запускать `scripts/run_target_jawl_smoke.ps1` до исправления A3 аудита.
Он пишет runtime/logs в protected JAWL и небезопасно определяет ownership
процессов при cleanup. Прежняя рекомендация запускать его отозвана.

`G:\AI\JAWL-Coding` — read-only reference, включая runtime/config/data/logs.
Нужен отдельный согласованный JAWL runtime; его provisioning/versioning —
P0-A в [TODO](../TODO.md). Нельзя ради smoke менять рабочий JAWL, его policy,
ключи, MCP/Telethon или приложения пользователя.

Токены заранее поступают из локального хранилища в environment. Не указывать
их значения в CLI arguments: они попадут в argv/history. Native профили
различаются именами env vars; проверить parser, не копировать ключи в файлы.

## Демонстрация UI

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

### Integrated JAWL profile и Full Access

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

## Существующие голосовые workers

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
  --asr-url http://127.0.0.1:8984/v1 --asr-model Qwen3-ASR-0.6B `
  --tts-url http://127.0.0.1:9890 --tts-provider qwen
```

Это составной **development пример**, ещё не принятый one-click профиль.
Для быстрого Tera заменить TTS URL на 9889 и provider на `tera`.
Нынешний default — Tera; автоматического fallback между workers не обещается.
Qwen CPU clone медленный и не имеет принятого emotion control.
Текстовый ответ без TTS остаётся допустимым degraded режимом, не voice acceptance.

VoiceMem sidecar должен сохранять memoryspace/cache в owned runtime; проверить
конфигурацию перед запуском. Сам interpreter path не разрешает запись в upstream.
Qwen-ASR шлёт whole utterance на end; hands-free/real device качество отдельно.
OmniVoice и CozyVoice не обязательны для этого профиля.

Системный звук — отдельный opt-in `--ambient-audio --ambient-memory`;
перед start выбрать источники/политику. Сейчас ASR flush на stop, не непрерывная
суточная сегментация. Модель music/sound captioning не выбрана.
Vision не запускать/фиксировать до решения владельца. OBS — [OBS.md](OBS.md).

## Что проверяют существующие harness

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

## Сборка

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

## Upgrade / rollback / выпуск

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
