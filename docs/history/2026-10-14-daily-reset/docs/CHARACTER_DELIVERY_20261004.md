# Статус персонажа — 2026-10-04

> **Историческая сводка поставки (2026-10-04).** Статусы относятся к
> зафиксированному тогда кандидату и не задают текущую очередь. Актуальные
> evidence и ограничения — [STATE](STATE.md), очередь — [TODO](../TODO.md),
> карта — [docs/README.md](README.md).

## Текущий кандидат: `JawlieRefinedV2` — ART ACCEPTANCE OPEN

Владелец: текущая причёска не соответствует turnaround; перчатки **убрать**.
Следующий шаг — blocking формы волос в 4 ракурсах, не детализация/physics
поверх непринятого силуэта. Успешный solver/export smoke не меняет art-статус.

- `runtime/vrm-models/JawlieRefinedV2.vrm`: 13 341 168 байт.
- `runtime/character-reference/jawlie-refined-v2.blend`: editable, packed.
- Builder `build_vroid_reference.py` + `reference_tailoring.py` +
  `reference_head.py`: 54 humanoid, 56 face morphs; 124 skin joints,
  39 glTF meshes / 54 browser primitives. Morph bindings 504 — не 504 эмоции.
- Hair: complete cap/back underlay/front-side locks, 13 chains/39 bones;
  2 группы/6 interior sphere colliders привязаны к native springs. Центр Hips
  оставляет head-turn inertia; Head-space отменял бы её. Верхние front locks
  подогнаны к cap с небольшим зазором, а не вынесены на сантиметры вперёд.
  Stiffness 4.0 / drag 0.90 после stress-прогона, выявившего чрезмерный transient
  на исходных 1.35 / 0.82. Финальный solver результат хранится в validation.json.
- Обе кисти открыты; source hand/face UV и выражения сохранены. Теменные
  материалы/лицо ещё наследуют VRoid, не оригинальная голова из turnaround.
- Actual `/app` smoke: `runtime/character-reference/JawlieRefinedV2/validation.json`,
  `browser.png`, `browser-three-quarter.png`, `browser-hair-settled.png`.
  Native solver: warm-up 2.5 с, yaw ±0.32 rad, возврат и наблюдение до 7 с.
  Все 39 hair bones weighted; custom helpers 6, Surprised/reduced motion/
  greeting проверены. Ни screenshot, ни spring stability не доказывают
  отсутствие mesh-пересечений во всех позах.

Крупные планы/дефекты/порядок исправления:
[CHARACTER_CLOSEUP_AUDIT_20261004.md](CHARACTER_CLOSEUP_AUDIT_20261004.md).
Прежние модели сохранены; выбор пользователя не изменён. Атрибуция VRoid/Other
и исходная ссылка лицензии сохранены, не CC0. Бинарники вне git.

## Предыдущий кандидат: `JawlieRefined` — ART ACCEPTANCE OPEN

Координатор лично забрал art-задачу у Laplace. Это отдельная производная
`AvatarSample_A`, **не точная копия turnaround и не финальная поставка**.
Исходный образец и прежние `JawlieReference`/`JawlieVroidReference` сохранены;
выбор модели пользователя автоматически не изменён.

- Гардероб: `runtime/vrm-models/JawlieRefined.vrm` — 13 193 424 байта.
- Редактируемый исходник: `runtime/character-reference/jawlie-refined.blend`.
- Повторяемая сборка: `tools/vrm_gen/build_vroid_reference.py` и
  `reference_tailoring.py`, Blender 5.2 с установленным VRM Add-on.
- Перед пошивом применяются mesh rotation/scale ко всем исходным мешам и
  ключам лица. Ошибка local/world coordinates раньше отправляла рукава на
  противоположные кости; новая одежда строится в единой rest-системе.
- Отдельные поверхности открытого petrol-бомбера, белой футболки, cargo,
  ремня с пряжкой и высоких ботинок. Есть мятная окантовка, манжеты,
  карман/клапан, шнуровка и одна серая перчатка. Старые hood springs удалены.
- Длинные задние волосы изменены вместе с rest-костями HairJoint, а не только
  растяжением вершин. Это не доказывает правильную укладку/коллизии в движении.
- Сохранены 54 humanoid-кости и 56 морфов лица (57 ключей с Basis).
  Всего 109 skin joints и 36 glTF meshes; в three-vrm 53 примитива-меша.
  504 primitive morph bindings **не означают 504 уникальные выражения**.
- Проверка `refined-browser-4.log`: один root, все 6 помощников реально
  взвешены в одежде, bounded offsets, точное восстановление после отключения,
  custom `Surprised`, reduced motion и приветствие прошли в реальном `/app`.
  Baseline физики берётся после отключения инерции, не из случайного кадра.

Evidence: `runtime/character-reference/JawlieRefined/validation.json`,
`browser.png`, `browser-three-quarter.png`; оффлайн front/back/3/4:
`runtime/character-reference/jawlie-refined-*.png`.

### Оценка сходства, не результат автоматического теста

| Элемент | Текущее отличие от референса |
| --- | --- |
| Палитра | Направление совпадает; оттенки toon/light ещё не откалиброваны |
| Бомбер | Узнаваем, но слишком короткий/пухлый; воротник, плечо и посадка требуют ручной доводки |
| Футболка/ремень | Белый слой появился; ткань слишком гладкая, ремень и пряжка недостаточно читаются |
| Брюки | Цельная посадка вместо отдельных труб; пока ближе к леггинсам, нужны тканевые складки, швы и правильный карман |
| Ботинки/перчатка | Тип и акценты узнаваемы; подошва, шнуровка и конструкция упрощены |
| Волосы/лицо | Главный разрыв: узкий задний объём, не та чёлка/линия прядей и исходное лицо VRoid вместо лица референса |

Приоритет: волосы/лицо и silhouette → крой одежды/стыки в движении → швы,
тканевые детали, нормали → проверка front/back/profile/3/4 и анимаций.
Не лечить плохую базовую форму добавлением физики. Вторичная инерция 6 костей
не является симуляцией ткани, лица или полноценным soft body.
После art-приёмки проверить объединение однотипных garment meshes/draw calls,
не объединяя морфы лица или native hair rig вслепую.

Выбор: вкладка аватара → гардероб → `JawlieRefined`. Лицензионная атрибуция
VRoid/Other сохранена, не CC0. Бинарники остаются вне git.
Полный runtime gate и real-provider/device/OBS/tablet acceptance отражены
отдельно в `STATE.md`; технический smoke не закрывает визуальную приёмку.

## Исторический прототип: `JawlieReference` — ART ACCEPTANCE FAILED

Технически проверенный прототип отклонён владельцем: Roblox-подобный вид и неподходящее лицо. Это не финальный персонаж и не принятая поставка.

- VRM: 1,374,544 bytes, 21 bone, 87 meshes. Из 18 заявленных имён подтверждены 4 фактических expression bindings: blink/aa/happy/sad.
- Есть 5 VRMA-клипов: idle/listening/speaking/greeting/nod; редактируемые исходники: `JawlieReference.blend` и `JawlieReference-animated.blend`.
- Строгая загрузка в браузере пройдена. `runtime/character-reference/JawlieReference/validation.json`: один root, emotion arm peak 0.25 rad, reduced-motion drift <0.003, greeting trigger работает.
- VRMA — переносимые редактируемые retarget exports; интерфейс их не проигрывает, движение процедурное.

## Исторический срез `JawlieVroidReference` (до доводки Laplace/координатора)

Отдельная адаптация полноценной anime-геометрии `AvatarSample_A`, не новая оригинальная модель с нуля. Лицо/чёлка сохранены; изменены оттенки материалов, удлинены 1 843 вершины задних прядей. Одежда пока остаётся кардиганом и шортами, а не бомбером и cargo из референса.

- Гардероб: `runtime/vrm-models/JawlieVroidReference.vrm`, 15 055 048 байт (14.36 MiB). Исходный `AvatarSample_A.vrm` не заменён.
- Редактируемый исходник с упакованными текстурами: `runtime/character-reference/vroid-reference.blend`; сборка: `tools/vrm_gen/build_vroid_reference.py` (Blender 5.2 + установленный VRM Add-on).
- Сохранены 54 humanoid-кости, 103 кости скелета, 56 морфов лица; 3 исходных меша, 17 примитивов в three-vrm. 504 ссылки на morph targets в разных примитивах **не означают 504 уникальные мимики**.
- Реальная сцена в изолированном Edge: один аватар, 15 выражений с привязками, руки опущены, поворот при эмоции ограничен 0.25 рад, reduced motion без позднего дрейфа. Приветствие измерено на реальном риге: пик предплечья 0.58 рад, не только успешный вызов функции.
- Отчёт: `runtime/character-reference/JawlieVroidReference/validation.json`; снимки `browser.png` и `browser-three-quarter.png` в том же каталоге.
- Сцена пока использует процедурные движения. Пять VRMA из прототипа доступны отдельно; их воспроизведение/ретаргетинг в продукте не подтверждены. Поведение удлинённых волос в длительном движении ещё не принято.

Сохранены автор VRoid и лицензия Other со ссылкой на [официальные условия образцов](https://vroid.pixiv.help/hc/en-us/articles/4402394424089-VRoidPreset-A-Z): это **не CC0**. Повторный импорт производного VRM в Blender требует ручного решения владельца о подтверждении лицензии; агент его не принял. Открытие собственного `.blend` не требует этого повторного импорта. Бинарники не включены в git.

Выбор в интерфейсе: гардероб → `JawlieVroidReference`. Текущая модель автоматически не заменяется. Лицо стало полноценным anime, но точное сходство с turnaround не достигнуто; финальным персонажем кандидат не объявляется.

В этом историческом срезе desktop TTS ждал `response.blob()`. Это уже заменено
NDJSON/WebAudio-клиентом: чанки WAV проигрываются с горизонтом 0.8 с и slices
до 0.4 с, отменой владельца и явной кнопкой остановки. Synthetic browser
acceptance не заменяет реальную речь/микрофон; desktop endpoint остаётся
после 2 секунд тишины. Это ещё не ChatGPT Live и не production-ready.
Второй мозг не добавлять.
