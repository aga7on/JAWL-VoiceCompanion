# Запуск текущей интеграционной сборки

Это существующий путь запуска для Windows, не заявление о готовом daily release.
Модели и зависимости должны уже быть установлены; состояние — [STATE](STATE.md).

Канонические роли моделей для постоянной работы зафиксированы в
[ADR-048](DECISIONS.md#adr-048--canonical-daily-model-roles). Важно: нижняя
команда `run_local_bonsai_integrated.ps1` поднимает brain из
`config/runtime.manifest.json`, где пока выбран `local-hikari` /
`local-bonsai2`; её visual default также EG2. Без явных Gemini relay и Qwen
visual settings она не запускает канонический набор. Не считать запуск этой
команды proof, что весь канонический набор поднят.

Из `G:\AI\JAWL-VoiceCompanion`:

```powershell
.\scripts\run_local_bonsai_integrated.ps1 -StartDesktopShell
```

Проверить сообщения готовности нужного профиля/моделей. Открывать
`http://127.0.0.1:2367/app`, не WebSocket URL. Флаг `-StartDesktopShell` открывает Electron после проверки здоровья компаньона и завершает его дерево процессов вместе с профилем. Без флага launcher работает без окна для acceptance-скриптов. Зависимости desktop должны быть установлены заранее:

Для ручного подключения Electron к уже работающему backend (без владения деревом процессов launcher):

```powershell
cd desktop
npm start
```

Manifest задаёт порты и пути, local override может изменить effective значения.
Не запускать второй стек поверх первого и не убивать владельца занятого порта.
Подробные existing flags/dependencies: [RELEASE](RELEASE.md).
`run_web.ps1` без connected parameters — демо, не замена этого стека.

Пока D1/D2 не закрыты, возможны native error и долгий ответ.
Речь Stop останавливает озвучку; закрытие окна не гарантирует остановку всех
workers. Пользовательский единый launch/stop/tray будет принят в D3/D6.
Не использовать архивные скрипты как runbook и не завершать процессы по имени
или номеру порта. Для разработчика — owned launcher/Job и его cleanup.

Микрофон/экран/системный звук настраиваются явно. Для системного loopback
machine-specific имя render-устройства задаётся в `audio.loopback_output_device_name`
в runtime manifest; пустое значение использует WASAPI default output. Сейчас daily
профиль настроен на `DigitalOutput (NVIDIA High Definition Audio)`, выбранное
владельцем устройство. Capture остаётся opt-in через `-EnableAmbientAudio` и
включение источника в UI. Ни этот документ, ни docs-only проверка не включают
фактический захват устройств.

В едином окне `Ctrl+Shift+M` переключает Studio и компактный режим; настройки
открываются из компактного дока. Speech Stop прекращает текущую озвучку,
а emergency Stop и остановка задачи — отдельные операции.

Проверка15Oct после новых hooks:3 real-model WAV voice turns через `/app`
прошли с Hikari, GigaAM и OmniVoice. Dispatch→WebAudio≈9.47–11.37с;
Fifine-ввод ранее принят владельцем; повтор не нужен. Акустический full duplex
не проверялся. Native-owned 8h r29 принят, интегрированная 8h эксплуатация OPEN.
`-RunBrowserVoiceE2E` теперь выбирает актуальный `/app`; его WAV-захват
не требует говорить в микрофон и не подтверждает аппаратную слышимость.


Изолированная native проверка без физических устройств:

```powershell
python -B scripts/run_owned_gateway_acceptance.py --live --mode ordinary --suite policy --report runtime/policy-check-unique.json
python -B scripts/run_owned_gateway_acceptance.py --live --mode ordinary --suite voice --voice-turns 20 --report runtime/voice-check-unique.json
python -B scripts/run_owned_gateway_acceptance.py --live --mode ordinary --suite soak --soak-seconds 28800 --report runtime/soak-check-unique.json
```

Каждый запуск создаёт свой профиль и Jobs; существующий report не перезаписывается.
Voice использует три WAV по кругу, реальные ASR/brain/TTS и headless `/app`.
Soak включает native ROOT3 только в новом disposable profile, временный unattended
lease, Goal write/read и один контролируемый отказ owned модели с восстановлением.
Atomic `soak-checkpoint.json` находится в run_root из отчёта. Smoke180с прошёл.
Первый 8h native soak16Oct исторически остановился с FAIL на63.6мин:
Goal13 false completion отвергнут native guard; cleanup PASS.
[Итог первого прогона](../runtime/native-owned-soak-8h-20261016-r1.json). Этот результат заменён для native-owned scope: 24Oct r29 завершился PASS — 8h, 476 cycles, 0 failed; один контролируемый transport fault восстановлен ([отчёт](../runtime/native-owned-soak-8h-20261023-r29.json)). Проверка охватывала native gateway/brain/Goal/Companion, не полный daily runtime, устройства захвата или integrated 24/7 acceptance; эти этапы остаются открытыми. Старый standalone soak с cwd/cmdline sampler не используется.
