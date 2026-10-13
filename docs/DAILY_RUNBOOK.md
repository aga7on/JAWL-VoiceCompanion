# Запуск текущей интеграционной сборки

Это существующий путь запуска для Windows, не заявление о готовом daily release.
Модели и зависимости должны уже быть установлены; состояние — [STATE](STATE.md).

Из `G:\AI\JAWL-VoiceCompanion`:

```powershell
.\scripts\run_local_bonsai_integrated.ps1
```

Проверить сообщения готовности нужного профиля/моделей. Открывать
`http://127.0.0.1:2367/app`, не WebSocket URL.
Electron при уже запущенном backend и установленных desktop dependencies:

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

Микрофон/экран/системный звук настраиваются явно. Начать mic проверку с наушниками.
Ни этот документ, ни docs-only проверка не включают фактический захват устройств.
