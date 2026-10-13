# Fit V4 — разбор дефектов со скриншотов владельца

> **Исторический geometry review (2026-10-05).** Сохранённый PASS относится
> только к этому geometry slice; art/full-physics и текущая приёмка им не
> подтверждаются. См. [STATE](STATE.md), [TODO](../TODO.md),
> [карту документации](README.md).

2026-10-05. Статус: geometry slice PASS, ART / full physics OPEN.
Эталон и последовательность приёмки: [art direction](CHARACTER_ART_DIRECTION.md).
Текущий пользовательский avatar не переключался. V2/V3 и исходники сохранены.

## Что исправлено и чем проверено

Отдельный `runtime/vrm-models/JawlieFitV4.vrm`, 13 845 276 bytes;
packed `runtime/character-reference/jawlie-fit-v4.blend`.
SHA256: `7febbad9fa64484be55349f06492079c37cd36db0139bf71433ff93526c18fcd`.
Генератор: `build_vroid_reference.py -- --fit-review`; без флага V2 и
`--blocking` V3 сохраняют прежнюю ветку. Это не изменение активной модели.

| Участок | Причина / исправление | Evidence / граница |
| --- | --- | --- |
| Подошвы снизу | Открытый контур заменён замкнутым дном; seam welded | Обе evaluated meshes: 0 boundary / 0 nonmanifold edges, bottom face есть |
| Мятные края ботинок | Per-face порог давал ступеньки; отдельные небольшие изогнутые вставки проецируются на boot | Просмотр quarter/underside; контур, шнуровка и материал пока не финальны |
| Карман cargo | Плоская панель висела над ногой; поверхность спроецирована на ткань с barycentric skin weights | Rest clearance 2 мм; клапан/полоса 3.5 мм; normalized weights. Не full-motion collision proof |
| Запястья | Centroid deletion давал рваный skin boundary | Точные bisect cuts под манжетами; unweighted body vertices = 0 |
| Воротник | Два наложенных слоя standalone collar / torso | Стойка — продолжение основной поверхности; плечевой стык всё ещё OPEN |

Все пользовательские скриншоты разобраны; чёрные линии костей — Blender
overlay, но ступенчатые края/открытая подошва/отстоящая панель были реальными
дефектами. Settling физики не исправляет rest topology.

Geometry report: `runtime/character-reference/fit-v4-geometry.json`,
run `b3ada5df557e4221a0ae56c80bf61d7f`, PASS / exit 0.
Read-only check: `tools/vrm_gen/check_fit_geometry.py`, запуск Blender с
`--python-exit-code 1`; требует ровно две подошвы, отсутствие mesh не PASS.
Это rest-only geometry test, не likeness score.

Actual `/app` browser smoke: run `6530066878b445398aa7e02802ba6466`,
`runtime/character-reference/JawlieFitV4/validation.json`, PASS / exit 0.
54 humanoid bones; один root; 51 browser primitives; 39 weighted hair joints
и 6 weighted helpers. Native springs: 7.021 с / 278 frames, peak 0.4341 rad,
late drift / rest delta = 0. Greeting, Surprised, disable/reset/reduced motion
проверены отдельно. Ни hardware FPS, ни отсутствие всех mesh intersections
этими цифрами не доказаны. VRoid attribution / Other license сохранены.

## Открытые дефекты и следующий шаг

- Плечо/рукав — раздельные перекрывающиеся поверхности, плохая rest-посадка.
  Нужен согласованный armhole/shoulder mesh и веса, не дополнительные складки.
- Волосы всё ещё слишком монолитны; front fall похож на жёсткую пластину.
  Stage A не закрыт. Лицо/наследованные nail/temple markings также не приняты.
- Cargo остаются слишком близки к анатомии; нижний край/ремень, силуэт ботинок,
  шнуровка и UV требуют дальнейшего review после крупных форм.
- Helpers дают малую вторичную инерцию; полноценная ткань, chest/hip deformation
  и collision-aware motion matrix остаются в stage D. ≥90% не измерено.

Проверка V5 с адаптацией исходной Tops topology **отклонена**: residual hood
и массовое shirt clipping в front/shoulder/back. Export PASS не превратился
в art PASS. Не использовать `--seam-review`: генератор явно отвергает эту
ветку; код не включён в working pipeline. Диагностические картинки/packed
blend сохранены; VRM перемещён из гардероба в
`runtime/character-reference/rejected/JawlieSeamV5.vrm` (не удалён).
Следующая гипотеза: связная новая посадка бомбера с согласованной внутренней
футболкой, прежде hair detail/material work; сравнивать четыре те же камеры.
