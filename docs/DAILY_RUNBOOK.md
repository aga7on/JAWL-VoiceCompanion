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

Из `G:\AI\JAWL-VoiceCompanion-V0.5`:

Ярлык `JAWL Voice Companion` на рабочем столе запускает
`scripts/launch_integrated_clean.py`: локальный профиль SenseNova из
`runtime/sensenova-loop/runtime.manifest.gpu.json`, окно Electron, наблюдение
экрана с OCR и явный запуск системного аудио. Настройки устройства берутся из
этого manifest; их фактическая работоспособность проверяется отдельно. При
необходимости общего запуска без автоматической сенсорики используйте:

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

## Единый интерфейс (ADR-052, 2026-10-30)

Отдельный presentation-сервер `8766` удалён: интерфейс один —
`http://127.0.0.1:2367/app`. Режим сцены для OBS/«питомца» — та же страница в
`?mode=obs` (прозрачный фон, без органов управления):

```powershell
.\scripts\run_avatar_window.ps1   # окно поверх других окон
# или Browser Source в OBS: http://127.0.0.1:2367/app?mode=obs
```

Старые ссылки `http://127.0.0.1:8766/avatar` и аргументы `-PresentationPort` /
`--presentation-port` / `--presentation-url` — deprecated: первые не работают,
вторые принимаются как no-op один релиз и будут удалены. В
`config/runtime.manifest.json` и профилях ключ `ports.presentation` больше не
нужен (загрузчики принимают его и игнорируют один релиз).
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
устройство определяется выбранным manifest: в локальном SenseNova-профиле
указано `Динамики (Game-Audeze Maxwell)`. В общем запуске capture остаётся
opt-in через `-EnableAmbientAudio` и `-StartAmbientAudio` либо управление в UI;
в полном desktop-профиле оба флага заданы явно. Ни этот документ, ни docs-only
проверка не подтверждают фактический захват устройств.

**Предусловие для системного звука (проверено 9 ноября 2026).** Захват привязан к
конкретному render-endpoint; если он отключён, `SystemAudioLoopback` по дизайну
падает с явной ошибкой и НЕ переключается молча на другое устройство. На момент
проверки активные loopback-устройства были: `Динамики (fifine Microphone)`,
`Интерфейс SPDIF (Realtek USB2.0 Audio)`, `DigitalOutput (NVIDIA High Definition
Audio)`, `Динамики (Steam Streaming Speakers)` — Audeze Maxwell среди них не было.
Перед запуском с ambient audio либо подключите Audeze (он станет активным
endpoint), либо задайте фактически активное имя в манифесте. Проверить список:

```powershell
runtime\jawl-daily-venv\Scripts\python.exe -c "import pyaudiowpatch as p; a=p.PyAudio(); [print(d['index'], d['name']) for d in a.get_loopback_device_info_generator()]; a.terminate()"
```

Синтез речи (проверено 9 ноября 2026): worker `scripts/omnivoice_server.py`
генерирует речь в режиме language-guided без клонирования по референсу. Любой
режим с `ref_audio`/`ref_text` на этой сборке модели подмешивал референсную фразу
в ответ (GigaAM слышал «Привет! Я твой голосовой компаньон…» вместо вопроса),
поэтому референс принимается как аргумент, но не влияет на генерацию. Три
канонические фразы в `runtime/synthetic-questions/` распознаются дословно;
скрипт пересоздания — `scripts/make_synthetic_question_fixtures.py`.

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
