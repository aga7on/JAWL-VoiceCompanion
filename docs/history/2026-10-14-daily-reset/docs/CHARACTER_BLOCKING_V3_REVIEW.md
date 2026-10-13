# Blocking V3: текущий review и история

> **Исторический candidate review (срез 2026-10-05).** PASS/OPEN и визуальные
> выводы ниже относятся к указанным итерациям, не являются текущей приёмкой.
> Текущее состояние — [STATE](STATE.md), очередь — [TODO](../TODO.md),
> каталог — [docs/README.md](README.md).

## Iteration 6 — 2026-10-05

Текущий кандидат: `JawlieBlockingV3.vrm`, 13 799 428 байт.
SHA256: `7010263cddf7f46a203304f2df651f1da7541fc2e4e3c1e5604d90d6685b1e17`.
Packed source: `runtime/character-reference/jawlie-blocking-v3.blend`.
Blender log: `runtime/character-reference/blocking-v3-build-6.log`, exit 0.
Actual browser identity run: `c5709912976d49bd8102979ec2846bc1`,
`runtime/character-reference/blocking-v3-identity-20261005.log`, exit 0.
Checker сверяет SHA до/после теста: одинаковый размер файла не подтверждает
идентичность разных итераций.

Рассмотрены те же rest-front/back/profile/three-quarter камеры. Задний контур
сужен, удлинён до пояса, вместо одной капли — центральное длинное окончание
и два более коротких несимметричных. Передняя масса имеет больший объём
поперечного сечения, без прежнего крупного закрывания глаза. Cargo seat
сглажен cloth-envelope, только для blocking; проверка посадки ещё открыта.
V2 output/его стандартный генератор и активный avatar пользователя сохранены.

Technical smoke: 54 humanoid, 56 исходных unique face morphs, 52 browser
primitives, 39 реально weighted hair joints, 6 weighted cloth/body helpers.
Native solver: 7.0017 с, peak 0.4508 rad, late drift/rest delta 0. Эмоция,
приветствие и reduced motion прошли. Эти числа НЕ измеряют cloth collision,
качество skin deformation в приседе, hardware frame time или art likeness.

**Stage A / target ≥90 OPEN.** Силуэт стал ближе по длине/объёму, но сверху
и сзади масса ещё слишком гладкая; front fall/пробор читаются жёстко. Не
переходить к micro-strands/текстурам, пока крупные массы и посадка плеч не
приняты. Унаследованные temple markings/глаза/материалы лица требуют B;
плечевой стык и тканевая посадка cargo/кармана/ботинок всё ещё не соответствуют
референсу. User acceptance и полная physics matrix не выполнялись.

## Первый проход — история

2026-10-04. Статус: PARTIAL / ART OPEN, сходство в процентах **не измерено**.
Сборка: `JawlieBlockingV3.vrm`, 13 799 412 байт; packed
`runtime/character-reference/jawlie-blocking-v3.blend`.
Вариант запуска: Blender `build_vroid_reference.py -- --blocking`.
Прежние модели и текущий выбор пользователя не менялись.

## Проверено

- Рассмотрены rest-front/back/profile/three-quarter, face и crown-back
  из `runtime/character-reference/jawlie-blocking-v3-*.png` рядом с turnaround.
- Три крупные массы: одна непрерывная crown/back поверхность и две
  асимметричные передние. Прежний горизонтальный стык cap/panels и одинаковые
  поднятые полосы удалены. Веса непрерывной массы смешаны между цепями;
  это не 11 независимых пластин с разрывами.
- Blender smoke exit 0, 54 humanoid и исходные face morphs сохранены;
  export/license и отсутствие перчаток проверены.
- Actual isolated `/app` Edge smoke exit 0. Отчёт:
  `runtime/character-reference/JawlieBlockingV3/validation.json`.
  52 browser primitives, 6 weighted helpers, все 39 HairRef joints weighted,
  13 native chains / 6 attached colliders. Native warm-up/turn/return:
  7.020 solver seconds, peak 0.4531 rad, late drift/rest delta 0.
  Это один технический прогон, не доказательство cloth/body collisions.

## Открыто / следующий проход A

1. Задняя масса слишком монолитная и «каплевидная». Нужны 4–5 крупных
   нерегулярных окончаний при сохранении цельной корневой массы, не возвращение
   к одинаковым пластинам. Детальные линии/текстуры пока не добавлять.
2. Передняя широкая масса чрезмерно закрывает глаз, выглядит жёсткой лентой;
   уменьшить ширину у глаза, сохранить side part и естественное сужение.
3. У правого корня/front mass есть складка/борозда: согласовать поверхность
   с crown и убрать резкий переход surface-conformance.
4. Профиль/temple содержит исходные маркировки/неподходящую фактуру лица.
   Это отдельный B likeness шаг; одними волосами не скрывать.
5. Cargo всё ещё слишком повторяют анатомию, плечевой переход/манжеты,
   ботинки и детали одежды требуют B/C. Новая причёска не закрывает эти пункты.

Stage A не принят. Полная physics/art delivery и target ≥90 остаются OPEN.
