# Лёгкий animation graph для Companion

Дата: 2026-10-04. Статус: следующий этап, **не реализованный AnimGraph 2**.

Сверка документации: 2026-10-10. Последний scene lifecycle gate 2026-10-05
подтверждает handoff/reset/stale-load safety в synthetic regression, а не
реализацию графа/VRMA/фонемного lip-sync. Единственная очередь —
[TODO, A-04](../TODO.md), факты — [STATE](STATE.md), карта — [README](README.md).

Идея владельца целесообразна как единый механизм управления анимацией, а не
порт Source 2. Valve описывает [AnimGraph 2](https://www.counter-strike.net/newsentry/528750051218948816?l=french)
как обновление затрат CPU/network в CS2; эти результаты нельзя переносить на
наш одиночный VRM без измерений. Для VRMA у three-vrm уже есть
[официальный loader/mixer пример](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-animation/examples/loader-plugin.html).

## Что есть и чего пока нет

Есть `avatar-motion.js`: состояния idle/listening/speaking, плавные additive
смещения и greeting/nod. `app-scene.js` отдельно применяет idle, мимику, губы
и gaze. `avatar-physics.js` — bounded вторичная инерция weighted helpers,
не полноценная ткань/soft-body. Пять VRMA экспортированы, но продукт их пока
не проигрывает. Сходство с turnaround требует отдельной художественной приёмки.

## Последовательность

1. Принять внешний вид/риг: фронт, профиль, спина, 3/4, руки и лицо в движении;
   проверить веса, clipping и отсутствие двух владельцев spring bones.
2. Выделить **одного pose owner** из текущих процедурных слоёв. Входы: состояние
   разговора, turn/generation, speech RMS, эмоция, разрешённый жест, reduced motion.
   Без дополнительных LLM и запросов на каждый кадр.
3. Добавить минимальный граф в данных: idle ↔ listening ↔ thinking ↔ speaking;
   переходы с crossfade, ограниченные веса/тайминги, один верхнетелесный жест.
   Мимика/губы/gaze отдельными непересекающимися каналами.
4. Подключить проверенные VRMA через mixer и ретаргетинг normalized humanoid.
   Сперва один клип, затем остальные. При отсутствующем/плохом клипе оставлять
   уже работающий процедурный слой. Assets из гардероба, не произвольные URL.
5. Связать interruption: прекратить речь/речевой жест старой generation,
   сбросить губы и вернуться к listening; idle/дыхание не обрывать. Swap модели
   освобождает mixer/контроллер и не применяет старые события к новому ригу.

## Приёмка

- Реальные browser tests переходов, наложения эмоций/жестов, отмены и remap;
  не только тест числа состояний или успешного `triggerGesture`.
- Нет накопления смещений, скачков pose, застрявшей улыбки/рта, старого жеста
  после нового turn. Native hair и custom helpers имеют разных владельцев.
- Reduced motion, missing rig/clip, dt spike/background tab и модельный swap.
- Измерить CPU frame time и память до/после на одном профиле; не объявлять
  экономию по числу строк. Во время речи/OBS сравнить движение и звук.
- Пользователь принимает образ и движения. Граф не исправляет плохую топологию,
  лицо, текстуру и неверную одежду.

Сейчас не нужны visual node editor, locomotion/motion matching, сетевые
оптимизации CS2, Unreal/Unity migration или тяжёлая физика на GPU. Их добавлять
только при реальном новом сценарии. Перестройка графа не меняет JAWL personality,
policy, память или brain provider.
