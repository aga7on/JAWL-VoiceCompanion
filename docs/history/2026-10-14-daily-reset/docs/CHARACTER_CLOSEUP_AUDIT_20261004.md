# Крупные планы персонажа — 2026-10-04

> **Исторический визуальный аудит (2026-10-04).** Наблюдения относятся к
> названному ниже кандидату; они не являются текущей приёмкой активного
> аватара. См. актуальные [STATE](STATE.md), [TODO](../TODO.md) и
> [карту документации](README.md).

Источник: `docs/concept/jawl-companion-turnaround-v1.png`. Кандидат:
`JawlieRefinedV2`. **Не принят по внешности**. Перчаток больше не требуется —
явное решение владельца имеет приоритет над turnaround.

Evidence: `runtime/character-reference/jawlie-refined-v2-<вид>.png`, 900×1100;
front/profile/back/three-quarter — T-pose; `rest-*` и крупные планы — опущенные
руки. Позу после render восстанавливаем перед export. Статичный Blender render
не рассчитывает native VRM springs: ошибки в исходной форме не лечатся ожиданием.
Старые файлы `glove-*` исторические; актуальные открытые кисти — `hand-*`.

## Что увидено, а не автоматически «пройдено»

| Зона / виды | Результат и остаток | Приоритет |
| --- | --- | --- |
| Лицо: face / face-profile / face-quarter | Morphs сохранены; это исходное VRoid-лицо с лёгкой правкой, не лицо референса. Blush/iris highlights и maroon temple marking наследованы | P1 |
| Чёлка и crown: face / crown-back | Убраны исходная дыра/оторванная дуга; боковой пробор и fall вместо поперечной полосы. Всё ещё гладкая «шапка», грубоватые стыки корней, не принятый blocking | P0 art |
| Задние волосы: rest-back / rest-profile / collar-back | Более широкий waist-length объём и underlay без прежних щелей; концы/flow слишком регулярные. Нужен blocking рядом с рефом, затем material/detail | P0 art |
| Воротник/шея: collar-front / collar-back | Stand collar существует; слишком прямые края, несовпадающее shading шеи/лица. Neck/scalp material убирает часть старого atlas, temple marking остаётся на лице | P1 |
| Плечо/рукав/манжета: shoulder / rest-front / hand-front | Отдельные скинированные рукава; стык у плеча читается ступенькой, cuff у кисти угловат. Нужны согласованные rings/weight transition и pose check | P1 |
| Кисти: hand-front / hand-back | Перчатки полностью удалены; устранены серые рваные glove tips. Сохранились исходные nail UV/контур; wrist/cuff границу ещё довести | P1 |
| Футболка/пояс: waist-front / collar-front | Открытый бомбер и белый слой, пряжка теперь читается. Ткань слишком гладкая, zipper strip упрощён, hem/belt spacing требует art-калибровки | P1 |
| Посадка сзади: waist-back | Цельная topology вместо отдельных труб, но остаются анатомические pinches/складки исходного body, а не правдоподобный крой cargo | P1 |
| Карман/бедро: pocket / rest-three-quarter | Клапан/мятная полоса видны; плоская выступающая пластина вместо пришитого кармана, нужна посадка к штанине | P1 |
| Колени: knees | Нет очевидной открытой дыры в rest; брюки всё ещё близки к леггинсам, складки/швы недостаточны. Согнутая поза не принята | P1 |
| Ботинки: boots-front / boots-quarter / boots-back | Верх/подошва/язычок есть; шнуровка — упрощённые диагонали, mint toe area слишком большая, seams читаются. Нет точного совпадения конструкции | P1 |
| Целый силуэт: rest-front / rest-profile / rest-back / rest-three-quarter | Узнаваемое направление палитры/одежды; пропорции/посадка ещё не ref identity. Техническая загрузка не является art-приёмкой | P0 art |

## Динамика — что действительно проверено

`check_reference_character.py --model JawlieRefinedV2`, actual `/app` в isolated
Edge: real three-vrm solver, не mock springs. Тестовый wrapper только задаёт
normalized head yaw после idle; solver/render остаются продуктовыми.

- Native hair: 13 chains, 39 weighted bones, 2 attached groups / 6 colliders.
- 2.5 с warm-up в solver-time → yaw +0.32 → -0.32 → 0 → наблюдение до 7 с.
- Проверяются finite quaternion, bounded rotation, поздний дрейф и возврат в rest.
- Исходные параметры 1.35 / 0.82: первый smoke peak 0.973 rad, дополнительный
  weighted-bones прогон **FAIL** по bounded transient (1.245 rad). Статичные
  poses при этом возвращались в rest — возврат сам по себе недостаточен.
  Это не принималось как правильная художественная физика. Жёсткость/drag
  подняты до 4.0 / 0.90; результат повторной проверки — в
  `runtime/character-reference/JawlieRefinedV2/validation.json`.
  Итоговый прогон `refined-v2-browser-3.log`: **PASS**, 7.014 с solver-time,
  peak 0.4794 rad, late drift 0, final rest delta 0; все 39 hair bones weighted.
  Это улучшение transient/stability, не приёмка художественной формы.
- 6 custom helpers реально имеют skin weights; off восстанавливает rest,
  Surprised, reduced motion и greeting работают.

Interior sphere proxies защищают spring particles, **не каждую вершину меша**.
Не закрыты hair/face/collar mesh penetration во всех позах, сцепление прядей,
cloth/face soft-body, native spring feel на длинной сцене. Не обещать полного
устранения клиппинга одним warm-up или вынесением чёлки.

## Правильный следующий проход

1. Blocking: crown, side part, left front fall, объём сзади и длина/концы.
   Сделать 4 простых вида рядом с turnaround; согласовать до деталей.
2. После принятия blocking: непрерывные корни/нормали, temple materials/UV,
   объём локонов; сохранить expression bindings/лицензию.
3. Согласовать garment fit/seams/pocket/boot construction по таблице.
4. Только затем head turns/наклоны/greeting/body poses, warm-up и контроль
   видимых mesh-контактов; solver smoke — отдельная проверка, не art verdict.
5. После визуальной приёмки сокращать draw calls и вводить VRMA/лёгкий graph.

Главный art-блокер — базовая форма/сходство, не отсутствие ещё одной physics
библиотеки. Основной код/voice/live acceptance отслеживаются отдельно в TODO/STATE.
