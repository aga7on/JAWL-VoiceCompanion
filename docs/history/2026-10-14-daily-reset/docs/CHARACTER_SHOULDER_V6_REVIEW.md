# Shoulder V6 — посадка кармана и связное плечо

> **Исторический geometry/browser review (2026-10-05).** PASS относится к
> этому срезу; художественная и общая приёмка остаются отдельными.
> См. [STATE](STATE.md), [TODO](../TODO.md), [карту документации](README.md).

2026-10-05. Geometry/browser smoke PASS; художественная приёмка OPEN.
Продолжение [Fit V4](CHARACTER_FIT_V4_REVIEW.md), не новая активная модель.
Целевой образ и этапы: [art direction](CHARACTER_ART_DIRECTION.md).

## Причина нового крупного плана

У старого плоского кармана была реальная геометрическая дистанция от ноги.
Settling волос/физики её не устраняет. V4 проецировал поверхность и веса на
брюки; V6 дополнительно учитывает толщину ткани и прижимает границу панели.
Проекция только к centerline с зазором 0.6 мм оказалась неправильной:
Solidify брюк выступает наружу на 1.5 мм, панели — внутрь на 0.5 мм.
Первая проба давала clipping и не принята. Итоговый border centerline 2.1 мм,
середина кармана 2.6 мм; клапан/полоса 3.3–3.8 мм, отдельный слой над карманом.

Side-on крупный план: `runtime/character-reference/jawlie-shoulder-v6-pocket-profile.png`.
Два тестовых сгибания ноги (-0.55 / +0.65 rad): max centerline clearance
2.709 мм для кармана, 3.893 мм для клапана, 3.833 мм для mint bar;
минимальный signed clearance положителен. Это две изолированные позы,
не полная collision matrix и не доказательство всех shell intersections.

## Новая поверхность бомбера

Вместо наложенных torso/sleeve tubes построены отверстия пройм с общими
вершинами и переходными кольцами рукавов. Один связный mesh; creased
границы zipper/cuffs; один subdivision перед skinning, веса снова нормированы
до четырёх influences. Root веса заданы по пройме, не по всей боковой стенке
торса: первая попытка с x-based весами вытягивала стенку и открывала футболку.
Футболка согласована по envelope, скрытая skin geometry не выступает сквозь неё.

Исходная поверхность: 1 component, 0 loose vertices, 0 branched boundary
vertices, 0 oversubscribed edges. Evaluated Solidify shell: 0 nonmanifold edges.
Техническая связность не означает правильную форму: в relaxed shoulder
остаётся неестественная cap-складка, требуются дальнейшие shape/weight правки.
Stage B плеча не закрыт. Не добавлять фактуру/cloth solver, чтобы скрыть дефект.

## Артефакт и проверки

- `runtime/vrm-models/JawlieShoulderV6.vrm`, 14 278 784 bytes.
- `runtime/character-reference/jawlie-shoulder-v6.blend`, packed source.
- SHA256 `b7c3352e40aa6657857600ce536f166f7baf98ee7e2bb7fbfcbf959a871ce55e`.
- `build_vroid_reference.py -- --shoulder-review`, третья итерация exit 0;
  log `runtime/character-reference/shoulder-v6-build-3-20261005.log`.
- Geometry run `35a0e52b509b44e2b68050791d2f79c8`, exit 0:
  `runtime/character-reference/shoulder-v6-geometry.json`. Boots/wrists также PASS.
- Actual `/app` smoke run `ed2e8bdecad740ea8fa518c0df16a77a`, exit 0:
  `runtime/character-reference/JawlieShoulderV6/validation.json`.
  54 humanoid bones, inherited face morphs, один root; native springs
  7.0043 с / 237 frames, peak 0.4025 rad, rest delta 0.
  Это не hardware FPS. Browser и geometry связаны тем же SHA256.

Генератор сохраняет прежние V2/V3/V4 ветки и VRoid Other/required attribution.
V5 остаётся rejected. V6 — отдельный кандидат, выбор пользователя не изменён.
Волосы, лицо, cargo silhouette, шнуровка и ≥90% OPEN; helpers не выдаются
за полноценную ткань/soft-body. Следующий art slice — исправить shoulder cap
в relaxed pose и hair blocking, затем заново сравнить четыре вида/close-ups.
