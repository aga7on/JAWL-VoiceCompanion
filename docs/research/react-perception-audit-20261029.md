# ReAct, heartbeat и передача VA — 29 октября 2026

## Результат

Исправлены owned-границы формирования контекста, транспорта Gemini и регистрации
фонового поручения. Pinned JAWL snapshot не менялся. Daily-профиль работает с
`gemini-3.8-flash`, явно объявленным окном 1 048 576 токенов и прежними сенсорами/TTS.
Название профиля `hikari-clean-20261029` историческое, не имя текущего мозга.

## Причины

1. Терминальный final закрывает текущий correlated turn. Ответ «беру в работу»
   сам по себе не регистрировал продолжение; обычная схема исключала GoalSkills.
2. Фоновый heartbeat был ограничен терминальным комментарием/пустым actions.
3. Loopback relay Gemini ошибочно получал constrained grammar для llama.cpp.
   В прямых пробах action-union возвращал пустые actions, а generic parameters
   терял аргументы. Для Gemini теперь plain JSON envelope с обычной native
   проверкой действий и политик; SDK wrapper tools убраны с этой ветки.
4. Фон восприятия повторял диагностику в истории. Native bridge также заменяет
   переводы строк пробелами, ломая разделение по строковым маркерам.
5. Большое окно не отменяло Goal `compact_max_chars=18000`. В живом логе
   84 320 символов превращались в 18 000 с удалением skills/host_terminal.

## Что изменено

- VA передаёт компактный пакет отдельно от реплики. Native контекст получает
  `PERCEPTION / VA`, а распарсенный ответ — заполненный источником `Perception`.
  Мозг не генерирует этот сенсорный блок заново. Возраст, давность caption,
  неопределённость и отдельная история сохранены; RMS, frame IDs и прочая
  техническая телеметрия не идут в разговорный фон. Новые записи истории чистые;
  старые сенсорные приложения удаляются при построении контекста.
- Доступны native Goal lifecycle и полезные heartbeat-действия. Поручение
  регистрируется до финального обещания продолжить. Счётчик Step относится
  к одному циклу; новый wake снова начинается с 1.
- Явно объявленное окно >=64K задаёт runtime char budget `tokens * 1.5` и
  отключает отдельное фиксированное Goal-сжатие. Общий native budget остаётся.
  Для текущего окна allowance 1 572 864 символа; это консервативная оценка,
  а не точный токенизатор. Без такого окна native настройки сохраняются.
- Прямой вход на 8770 переводит браузер через локальную сессию Companion;
  секрет не помещается в URL. Activity и журналы Companion передают CSRF.
  Наличие рабочего шага больше не задерживает готовность UI до idle.

## Реальные проверки

- Изолированный native canary `continuity-canary-ecdded19`: неизвестный модели
  marker прочитан, скопирован, проверен; Step 1→2→3. Второе поручение создало
  Goal, продолжилось по heartbeat без новой реплики и завершилось с проверенным
  файлом. Protocol errors=0; sensor packets в сохранённой истории=0.
  Артефакт: `runtime/continuity-audit-20261029/continuity-canary-ecdded19/report.json`.
- Managed restart только мозга в 03:15:48 сохранил активную Goal. Сенсоры,
  Companion и OmniVoice продолжали работу. Новый процесс начал с ~30K input
  tokens и выполнил 27 инструментальных действий на контрольном срезе;
  прежнего повторного поиска HostOSReader и 18K-compaction на этом участке нет.
  После Step 15 произошёл настоящий heartbeat и продолжение через пять секунд.
- API: JAWL connected/running, модель Gemini; console chat содержит 50 записей;
  plain 8770 перенаправляет на bootstrap Companion, authenticated console=200.
  Артефакт: `runtime/continuity-audit-20261029/live-after-restart.json`.
- Focused suite ранее: 192 passed. После поправки capacity: 48 passed + 5
  subtests; Node startup/settings/lifecycle: 16 passed. Это пересекающиеся suites,
  их числа не следует складывать.

## Ограничения

- Нулевой `prompt_reuse` — отдельный вопрос caching relay, данная правка его
  не исправляет. Не подменять отсутствие cache сжатием полезного контекста.
- Health остаётся degraded: ambient loopback ожидает samples, streaming ASR idle.
  Текущая приёмка не доказывает физический микрофон или качество живого аудио.
- Canary доказывает выполнение/heartbeat на малой проверяемой задаче; это не
  гарантия завершения произвольного большого поручения и не 24×7-приёмка.
- В уже открытом браузере нужно обновить страницу для нового JS/маршрута входа.
- Старые противоречивые Qwen/fusion тесты, ожидающие удаление устаревшего caption,
  требуют согласования с текущим контрактом сохранённого last observation.

## Общая регрессия: не PASS

Полная Python gate: 1181 tests, 6 failures + 1 error. Два отказа pause/fresh
исправлены после прогона: invalidated-наблюдение сохраняется, но больше не
считается fresh; устаревание учитывается и в текстовом compose. Связанный suite
ambient/packet/TTL/enrichment/web: 127 passed + 33 subtests, затем после поправки
compose ещё 38 passed. Эти последние изменения fusion потребуют следующего
штатного перезапуска Companion; мозг уже работает с исправлением capacity.

После последующих правок Qwen/fusion named mismatches по устаревшим caption
контрактам закрыты: Qwen sensor 18/18, fusion 16/16, now-TTL 2/2. Два
launcher mismatch из исходной gate перепроверены отдельно и закрыты: тест
`--n-predict 512` теперь явно задаёт пустые Transformers-поля в `Mock`, а тест
профиля проверяет фактический `$nativeProfileArgs` + splatting вместо старой
inline-формы. Оба точечных теста прошли. Полную Python gate после этих правок
не перезапускали; исходный результат ниже исторический, оставшиеся падения
полной gate по-прежнему не считаются принятыми.

Node общая gate: 124 tests, 118 passed, 6 failed в `app-voice-lifecycle`:
flush/finalization/overlap/409. Эти сценарии не принимались данной проверкой.
Focused startup/settings/lifecycle 16 passed. Все четыре PowerShell entrypoint
парсятся без ошибок, snapshot hash неизменен, diff-check PASS.
CodeSee: обновлены 4 feature из 30, validator — 0 errors (есть warnings по длине имён).

Логи: `runtime/continuity-audit-20261029/full-gate.log`, `node-gate.log`.
