# Hair V7 — отдельный кандидат, не финальная художественная приёмка

> **Исторический candidate review (2026-10-05).** Измерения и PASS ниже
> ограничены указанными проверками и не означают likeness/art acceptance.
> См. [STATE](STATE.md), [TODO](../TODO.md), [карту документации](README.md).

2026-10-05. Продолжение [Shoulder V6](CHARACTER_SHOULDER_V6_REVIEW.md).
После обзора AIRI/3D-tools владелец попросил продолжить перспективные
направления и подтянуть модель; пауза моделирования отменена для нового среза.
Цель и критерии остаются в [art direction](CHARACTER_ART_DIRECTION.md).

## Гипотеза и фактическое изменение

V6 имел чрезмерно толстую прямую front mass, скрывавшую глаз/часть лица,
и слишком глубокие симметричные разрезы сзади — силуэт трёхзубой пластины.
V7 уменьшает толщину/ширину передних масс, переносит fall к контуру щеки,
смягчает задние долины, расширяет shoulder-level массу и добавляет небольшую
асимметрию hairline. Остались 3 крупных mesh-массы и 13 spring chains;
не добавлены одинаковые отдельные пластины или тяжёлые модели/зависимости.

Флаг `build_vroid_reference.py -- --hair-review` наследует garment fixes V6,
пишет отдельные файлы и не меняет V2/V3/V4/V6 default branches. Форма лица,
морфы и атрибуция VRoid сохранены. Активный пользовательский avatar не менялся.

## Визуальное ревью координатором

Просмотрены front/profile/back/3/4 в relaxed pose и крупный план лица.
Передняя масса тоньше, глаза виднее; задний контур больше не имеет двух
глубоких повторяющихся вырезов. Это локальное улучшение, не измеренные 90%.

Открыто:

- Crown/back по-прежнему слишком гладкие и монолитные, боковой корневой
  переход читается как жёсткая линия; не закрыт Stage A likeness.
- На temple виден унаследованный тёмный участок; необходимо локализовать
  UV/material region, не перекрашивать вслепую лицо/веки или исходную текстуру.
- Front fall ещё выглядит прямым; нужен контролируемый breakdown крупных
  асимметричных масс по turnaround, без возврата к одинаковым strip-пластинам.
- Relaxed shoulder cap складка и tight cargo silhouette/boot detailing не
  исправлены этим hair-срезом. Full cloth/soft-body и all-pose collisions OPEN.

Кадры находятся в `runtime/character-reference/`:
`jawlie-hair-v7-rest-front.png`, `-rest-profile.png`, `-rest-back.png`,
`-rest-three-quarter.png`, `-face-quarter.png`; повторяемые камеры те же, что V6.

## Артефакт и evidence

- `runtime/vrm-models/JawlieHairV7.vrm`, 14 278 616 bytes;
  packed `runtime/character-reference/jawlie-hair-v7.blend`.
- SHA256 `4d005ee6feeaa60244325e9ba793d5310e6b97df636ebb61304b42c598ecab03`.
- Build exit 0: `runtime/character-reference/hair-v7-build-20261005.log`.
  38 exported meshes, 124 skeleton joints, 54 humanoid bones, 504 primitive
  morph targets (это не число независимых эмоций).
- Geometry exit 0: `runtime/character-reference/hair-v7-geometry.json`,
  run `726239e29d30492c99e79a4abffb5d13`. Проверены унаследованные boots,
  wrist weights, connected bomber/shell и cargo clearance в двух flex-позах.
  Это проверка garment regression, не полная collision-проверка волос.
- Actual `/app` solver smoke exit 0:
  `runtime/character-reference/JawlieHairV7/validation.json`,
  run `8a2d29e69c8a48dfaee7a4023c8b3fe9`, тот же SHA.
  39 фактически weighted hair joints, 6 collider proxies, 7.016 с / 250 frames,
  peak 0.42445 rad, finalRestDelta/lateDrift 0. Один root; эмоции/приветствие/
  reduced motion проверены. SwiftShader/headless — не аппаратный FPS.

Следующий модельный срез: root/temple geometry-material localisation и
естественные primary masses, затем снова четыре вида; детализацию и сложную
физику не использовать для маскировки плохого силуэта. Заимствование AIRI
сцены/липсинка не заменяет качество исходного avatar asset.
