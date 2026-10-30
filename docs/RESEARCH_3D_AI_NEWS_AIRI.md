# Обзор 3D AI News #16 и Project AIRI

> **Исторический research snapshot (2026-10-05).** Рекомендации ниже не
> означают внедрение. AIRI — источник отдельных идей, не второй мозг и не
> новый владелец persona/tasks/policy. Указанная в старом тексте пауза 3D
> описывает момент исследования, а не текущую очередь. См. [STATE](STATE.md),
> [TODO](../TODO.md) и [карту документации](README.md).

Дата проверки: 2026-10-05. Статус: исследование, не решение об интеграции.
На момент исследования владелец остановил 3D-моделирование. Последующее
поручение возобновило отдельный model/voice срез: [Hair V7](CHARACTER_HAIR_V7_REVIEW.md),
текущее состояние — [STATE](STATE.md). Это не одобрение всей интеграции AIRI.
Не устанавливать перечисленные проекты и не скачивать веса
только на основании этого документа. Сохраняются JAWL как единственный
decision owner и правило «не перезаписывать уже лучшую реализацию».

## Что действительно изучено

[Ролик Stefan 3D AI](https://www.youtube.com/watch?v=2uk9v3DDBEo):
«Open-Source LLM Masters 3D Design, NVIDIA ARDY & MageFlow by Microsoft –
3D AI News #16», опубликован 2026-07-26, длительность 11:32.
Получены полные описание и английская расшифровка через yt-dlp; визуальные
демо/кадры и звук ролика не просмотрены. Названия и технические обещания
сверены с первоисточниками, а не только с автоматическими субтитрами.

Все 15 URL описания учтены ниже: 10 технических, 2 промо, 3 контактных.
Содержание 10 доступных страниц изучено; 5 недоступных не считаются
прочитанными. Связанные официальные README, лицензии и отдельные исходники
открывались дополнительно. Никаких локальных установок или benchmark runs.

## Реестр ссылок из описания

| № | Источник | Результат и значение |
| --- | --- | --- |
| 1 | [LATO.2](https://github.com/LoHhhha/LATO.2) | Изучен: генерация новой topology/vertex set из mesh, не готовый VRM. |
| 2 | [ComfyUI-LATO.2](https://github.com/Rizzlord/ComfyUI-LATO.2) | Изучен: mesh-to-mesh node, checkpoint auto-download при использовании. |
| 3 | [Kimi K3](https://www.kimi.com/blog/kimi-k3) | Изучен после redirect на kimi.ai: LLM coding/vision iteration, не специализированный avatar generator. |
| 4 | [3DGenStudio](https://github.com/visualbruno/3DGenStudio) | Изучены README и LICENSE: отдельная authoring-среда поверх ComfyUI/API. |
| 5 | [NVIDIA ARDY](https://research.nvidia.com/labs/sil/projects/ardy/) | Изучены project page и официальный repo: motion generation, не cloth/body simulation. |
| 6 | [NKD VFX Tools](https://github.com/Nekodificador/ComfyUI-NKD-VFX-Tools) | Изучен: свет, проекция текстур, camera/control maps. |
| 7 | [Tripo: X-пост](https://x.com/tripoai/status/2079473920646996184) | Недоступен. Обещания про fitting одежды не подтверждены содержимым поста. |
| 8 | [MeshTailor](https://meshtailor.github.io/) | Изучен: mesh-native seam prediction для UV; публичный code пока TBA. |
| 9 | [Microsoft Mage-Flow](https://microsoft.github.io/Mage/flow/) | Изучены project page/README: image generation/editing, не 3D rig. |
| 10 | [Omniverse Agent Toolkit](https://nvidianews.nvidia.com/news/nvidia-agent-toolkit-expands-with-new-omniverse-libraries-putting-ai-agents-to-work-building-simulation-ready-worlds) | Изучен: OpenUSD/simulation-ready worlds, не лёгкая avatar runtime. |
| 11 | [Top3D Arena](https://top3d.ai/arena) | Изучен: blind visual voting; не тест VRM rig/physics/latency. |
| 12 | [Pixel Artistry newsletter](https://pixel-artistry.com/newsletter) | Недоступен; промо, не архитектурный источник. |
| 13 | [Discord](https://discord.gg/am7nu68r9Z) | Недоступен; контакт автора, содержимое сервера не изучено. |
| 14 | [X автора](https://x.com/Stefan_3D_AI) | Недоступен; не обходить авторизацию. |
| 15 | [LinkedIn автора](https://www.linkedin.com/in/stefan-3d-ai/) | Недоступен; контакт, не проверенный технический материал. |

## Отбор для нашего проекта

### LATO.2: экспериментальная ретопология, не ремонт готового персонажа

Две стадии V-Flow/T-Flow создают новые вершины и связность; выходы OBJ/PLY.
README предупреждает об отверстиях и неверных соединениях. Указанные
примерно 8 GB VRAM/5 секунд относятся к H800, не к нашим RTX 5080.
Есть CUDA build dependencies; CPU-путь wrapper не означает пригодную скорость.
[Первичный README](https://github.com/LoHhhha/LATO.2).

Вывод: потенциально полезно на изолированных unrigged предметах/одежде.
При смене topology нельзя предполагать сохранение UV, skin weights,
morph targets или likeness. Тестировать только на копии с явной проверкой
связности/силуэта и последующим rig transfer; не применять поверх рабочего VRM.
[ComfyUI wrapper](https://github.com/Rizzlord/ComfyUI-LATO.2) не включать
в постоянный runtime и не запускать auto-download в исследовательском срезе.

### 3DGenStudio: наиболее полезная отдельная мастерская из ролика

Authoring workspace: UV/paint/sculpt, retopology, SkinTokens auto-rig,
перенос weights, reference animation/retargeting, LOD и baking. Работает
поверх ComfyUI/внешних API, имеет свою desktop/UI/data инфраструктуру.
Это не гарантия сохранения VRM expressions/colliders и не тест качества
посадки одежды. [README](https://github.com/visualbruno/3DGenStudio).

Собственная Community License ограничивает продажу/платный hosting/bundles
самого ПО; outputs разрешены для коммерческого использования, при сохранении
условий сторонних сервисов/моделей. Это не MIT/Apache. Перед переносом кода
проверять конкретные условия, а не надпись «open source» в ролике.
[LICENSE](https://github.com/visualbruno/3DGenStudio/blob/main/LICENSE).

Вывод: оценивать отдельно как asset workbench, экспортировать результат в
наш Blender/VRM acceptance pipeline. Не встраивать вторую тяжёлую оболочку
и базы данных в JAWL Companion. Сначала качественный base mesh, затем rig,
выражения, клипы и коллизии; auto-rig сам по себе не даёт готовую физику.

### ARDY: кандидат для движения с CPU-энкодером, пока без нашего benchmark

Генерирует поток humanoid motion из текста и kinematic constraints.
Официальный demo допускает text encoder LLM2Vec на CPU bf16/fp32;
GPU bf16 вариант энкодера занимает около 14 GB. Поэтому утверждение
«обязательно >20 GB VRAM» не описывает все возможные конфигурации.
Опубликованная проверенная среда — Ubuntu/RTX 4090; Windows/5080 не приняты.
Есть gated Llama-3-8B, отдельные лицензии checkpoints и Apache-2.0 код.
[Официальный README](https://github.com/nv-tlabs/ardy).

Вывод: RAM для энкодера + GPU для motion model согласуется с пожеланием
владельца, но CPU prompt latency, resident VRAM и streaming cadence надо
измерить. Начать, если разрешено, с offline клипов → retarget → VRMA; не
добавлять постоянно работающую модель до сравнения с лёгким animation graph.
Это генератор skeletal motion, не симуляция груди/ткани/волос. Две карты
по 16 GB не считать единым 32 GB устройством без поддержки шардирования.

### MeshTailor: важное исправление трактовки видео

Предсказывает edge-aligned seams и UV charts, в том числе для одежды.
Это не garment fitting, не шитьё физического паттерна и не collision solver.
На странице код обозначен TBA. Вывод: watchlist для UV, интегрировать сейчас
нечего; не обещать исправление floating pockets/cloth clipping этим методом.
[Project page](https://meshtailor.github.io/).

### Остальные кандидаты

- **NKD VFX**: отдельный ComfyUI-инструментарий для relight/camera/texture
  projection. Полезен для offline текстур/света/фона, не rig/physics;
  GPL-3.0 учитывать перед переносом кода. [Repo](https://github.com/Nekodificador/ComfyUI-NKD-VFX-Tools).
- **Mage-Flow**: MIT, 4B image generation/editing, Turbo 4 шага. Авторы
  указывают peak 18–20 GB при 1024² на A100. Это не наш CPU/offload benchmark
  и не доказательство fit в 16 GB. Сейчас альтернативная image toolchain,
  а не причина менять уже подготовленный Qwen-Image pipeline.
  [Официальный README](https://github.com/microsoft/Mage/blob/main/mage_flow/README.md).
- **Kimi K3**: 2.8T MoE; автор рекомендует supernodes с 64+ accelerators.
  Local full weights не соответствуют нашему бюджету RAM/VRAM. Vision-in-loop
  coding/3D reasoning не равно качественной mesh по референсу. Только
  возможный remote authoring provider, не новый постоянный мозг.
  [Tech blog](https://www.kimi.ai/blog/kimi-k3).
- **Omniverse**: OpenUSD/RTX sensors/physics/world building. Для текущего
  three-vrm продукта неоправданная смена asset/runtime ecosystem.
  Даже standalone [ovphysx](https://github.com/NVIDIA-Omniverse/PhysX/tree/main/ovphysx)
  не является готовой подменой нашего browser spring/cloth solver.
  [Анонс NVIDIA](https://nvidianews.nvidia.com/news/nvidia-agent-toolkit-expands-with-new-omniverse-libraries-putting-ai-agents-to-work-building-simulation-ready-worlds).
- **Top3D Arena**: полезна для визуального shortlist; ELO не заменяет нашу
  проверку rig, anatomy, likeness, collisions, expressions и frame time.
  [Arena](https://www.top3d.ai/arena).

## Project AIRI — добавлен по поручению владельца

[Reddit-пост](https://www.reddit.com/r/BestGitHubRepos/comments/1wwjgxs/project_airi_selfhosted_ai_companion_that_plays/)
использован как указатель; технические выводы — по
[официальному AIRI](https://github.com/moeru-ai/airi), MIT.
Репозиторий проверен на commit `edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5`.
Web/desktop/mobile surfaces, VRM/Live2D, speech и game/chat integration
близки нашему замыслу. Но README помечает Memory Alaya как WIP,
Factorio как WIP/PoC и Helldivers 2 как незавершённый, а не готовый продукт.
Наличие русского README не доказывает качество RU speech providers.

### Конкретные прочитанные механизмы и полезные идеи

Ссылки ниже закреплены на изученном commit; это code review без запуска.

- [Voice input session](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/stage-ui/src/composables/audio/voice-input-session.ts):
  segment identity, VAD/recording gates, session ticket и stale checks до/после
  ASR; callbacks отделяют capture от продуктового поведения. Полезный
  reference для race tests. Это не доказательство акустического echo control.
- [TTS chunker](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/pipelines-audio/src/processors/tts-chunker.ts):
  grapheme-aware вход, punctuation/flush/special events, ранние chunks при
  достаточной длине. Для нас вход должен быть только валидированным
  speakable text из JAWL, не raw JSON/tool payload. Проверить RU числа,
  аббревиатуры, эмодзи и стоимость отдельных TTS requests.
- [Playback manager](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/pipelines-audio/src/managers/playback-manager.ts):
  owner/intent identity, AbortController, cancellation активных и ожидающих
  items, приоритеты. Лимит maxVoices не ограничивает длину waiting queue:
  не переносить queue policy без byte/time/item bounds и backpressure.
- [Chat interruption](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/stage-layouts/src/composables/use-chat-interruption.ts):
  response owner сохраняется при переключении чата; Stop/новый Send отменяют
  LLM/TTS перед заменой. У нас voice interrupt не должен уничтожать durable
  JAWL goal/task. Acoustic barge-in требует отдельной цепочки и теста.
- [Streaming TTS session](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/stage-ui/src/libs/speech/streaming-session.ts):
  JSON control + binary audio, abort и ошибка при close без session.finished.
  Однако конкретно `streamingSynthesize()` накапливает chunks и возвращает
  их конкатенацию после finished. Это streaming transport, не progressive
  playback внутри этого helper. Изучить соседний streaming-pipeline отдельно;
  не делать вывод, что ни один другой путь AIRI не умеет живое проигрывание.
- [VRM lifecycle](https://airi.moeru.ai/docs/en/blog/DevLog-2026.03.14/) и
  [instance cache](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/stage-ui-three/src/components/Model/vrm-instance-cache.ts):
  window/scope ownership, reason-aware teardown, load→validate→commit,
  stale-load disposal, сцена не скрывается display:none во время readiness.
  Полезно для app/settings/OBS, но кеш обязан иметь eviction/cleanup;
  сама cache helper возвращает старые объекты, не освобождает их автоматически.
- [VRM lip-sync](https://github.com/moeru-ai/airi/blob/edbbcf5384b5ed183979fa1ccadf1f1e15cb66b5/packages/stage-ui-three/src/composables/vrm/lip-sync.ts):
  wLipSync → aa/ee/ih/oh/ou, cleanup при смене source/context; AudioContext
  принадлежит вызывающему owner. Кандидат лучше простого RMS-open-mouth,
  но отдельная проверка RU, CPU budget и морфов нашей модели обязательна.

Дополнительный компактный reference:
[WebAI realtime voice demo](https://github.com/proj-airi/webai-example-realtime-voice-chat)
(MIT), отдельные ступени VAD → ASR → LLM → TTS. Пока изучен README,
не исходники/качество живого demo. [unspeech](https://github.com/moeru-ai/unspeech)
добавлен в очередь для audio provider protocol; не вводить ещё один proxy
без доказанного отсутствующего capability.

## Предлагаемая очередь, не разрешение на миграцию

1. AIRI code map voice/interrupt/streaming и совместимость с нашим JAWL.
   Сравнить actual call sites и tests, измеряемые latency/queue/resource
   guarantees; принять только выигрыш, не whole monorepo.
2. Shared scene/presentation ownership, vowel lip-sync и game/chat adapters.
   JAWL хранит persona/memory/goals/policy; внешний чат/игры — недоверенные
   observations, side effects только через нативную политику JAWL.
3. После решения владельца: 3DGenStudio offline asset workbench, затем
   отдельный LATO disposable test. MeshTailor пока watchlist.
4. ARDY CPU encoder/GPU motion benchmark и offline clip retargeting только
   при разрешённом новом срезе. Mage/NKD вторичны; K3/Omniverse не включать
   в обязательный local runtime.

Итог: инструменты из видео могут облегчить отдельные authoring-этапы,
но не закрывают автоматически ≥90% likeness или полную физику. AIRI —
более прямой источник решений для ощущения живого компаньона, не основание
заменять JAWL/VoiceMem несогласованным вторым framework. Поддержка Live2D
в AIRI не отменяет автоматически действующий VRM ADR нашего репозитория.
