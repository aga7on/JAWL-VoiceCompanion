# Interface V9 — кисти/манжеты и штанины/ботинки

> **Historical geometry/seam review (2026-10-05).** The saved PASS applies to
> its named checks and candidate; it does not establish artistic, full-motion,
> or current production acceptance. See [STATE](STATE.md), [TODO](../TODO.md),
> and [documentation map](README.md).

Последнее поручение: закрыть видимые стыки и проверить их при сгибах.
Предыдущая проверка весов кистей и закрытой подошвы была недостаточной:
она не проверяла посадку одежды вокруг открытого края кожи/штанин.

## Исправление

- Манжеты строятся по реальному сечению Skin, а не по эллипсу из bounding box.
  Последние кольца прилегают к контуру; внутренний отворот закрывает проём.
  Концы рукавов получают интерполированные веса Skin через BVH/barycentric
  projection после Subsurf, вместо pure forearm/nearest-vertex binding.
  Запас 2.3 мм включает 0.7 мм на угловую интерполяцию/сглаживание.
- Голенища строятся по реальным сечениям штанин. Верх следует голени,
  стопа — Foot, между ними плавный переход. Штанина заканчивается на z=0.185,
  голенище доходит до z=0.210: край скрыт перекрытием в 25 мм.
- Исправлен порядок построения штанов: source UV splits свариваются ДО
  смещения по нормали. Иначе разные split normals раскрывают мелкие трещины.
  Лица выбираются по пересечению диапазона высот, а не по центроиду;
  после этого выполняется точный срез подола. Изменение ограничено флагом V9.
- Язычки и шнуровка повторно спроецированы на изменённую поверхность ботинок.
  Их художественная детализация ещё не принята.

Это визуально непрерывные перекрывающиеся стыки с согласованным skinning,
а не сварка кожи и всей одежды в один mesh. Простое Join объектов не
закрывает отверстия и не исправляет разные веса. Активный аватар не заменён;
предыдущие V4/V6/V7/V8 артефакты сохранены.

## Доказательства

Финальная сборка r8: Blender 5.2.1 LTS / VRM add-on, exit 0 с
`--python-exit-code 1`; `interface-v9-build-20261005-r8.log`.

- VRM: `runtime/vrm-models/JawlieInterfaceV9.vrm`, 14 327 276 bytes.
- Source: `runtime/character-reference/jawlie-interface-v9.blend`, 10 452 470 bytes.
- SHA256: `b0396e670a86a873c0932489735b7bf19e045dfc8ba9912804b47341530c8ba6`.
- Garment geometry PASS, run `41520a7b54ac4b25bcbe28951e209abc`: закрытые
  подошвы, connected bomber/shell, cargo clearance и два сгиба ноги;
  face morphs/temple UV и rest Face–hair regression сохранены.
- Actual `/app` PASS, run `74b2ce657f914801972a7d349c0380fd`: один root,
  эмоции, жест, reduced motion, 39 weighted native hair joints / 6 colliders.
- Seam acceptance PASS / exit 0, run `bd56a8c597794266b197d1b8c11188a2`:
  `runtime/character-reference/interface-v9-joints.json`, log
  `interface-v9-check-r8-20261005.log`. Все 34 wrist + 34 ankle проверки PASS.
  На каждой стороне wrist 31 sample, ankle 26; max outward hit 3.613 мм / 3.319 мм.

Строгий seam checker проверяет обе стороны в rest и 16 изолированных позах:
кисти ±0.35 rad вокруг Y/Z, стопы ±0.40 rad вокруг X/Y. Точки исходного
открытого края проходят реальный Armature; covering surfaces — evaluated
mesh с толщиной. Каждый наружный луч должен попасть в оболочку не далее
5 мм для wrist / 6 мм для ankle. Диагностический предел 30 мм не расширяет
критерий приёмки. Это sampled coverage, не гарантия всех возможных поз.

Первая r2 проверка FAIL сохранена в `interface-v9-joints-r2-failed.json`:
nearest-surface maxima около 10 мм, недостаточная посадка. r3–r5 сборки
останавливались на проблемном исходном сечении; ошибки не считаются успехом.
Для r6 исправлено исходное построение штанов. r7 прошёл rest/all ankle, но
провалил три wrist-flex проверки: nearest-vertex binding давал скачок весов.
Отчёты FAIL сохранены отдельно; r8 исправляет binding barycentric projection.
Пороги 5/6 мм не увеличивались.

## Граница приёмки

Просмотрены rest hand-front/back, boots-front/quarter/back и четыре posed
close-ups обеих сторон. Видимых разрывов на этих видах нет; край манжет
остается низкодетальным, язык/шнуровка ботинок требуют художественной доработки.
Численная проверка не заменяет видимые края/силуэт. Проверка actual `/app`
не измеряет hardware FPS и сама не проверяет все seam poses после экспорта.
≥90% likeness, финальная шнуровка, crown/front hair, shoulder cap и полная
cloth/body collision physics остаются открытыми. Backend/voice regression
этого среза — полный gate Hair V8/scene lifecycle, а не новые live RU tests.
