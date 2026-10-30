# JAWL Companion — правила разработки

Актуально: 14 октября 2026. Ветка `dev/daily-companion-20261014`.
Цель ближайшей поставки — ежедневный живой компаньон на ПК владельца.
Единственная очередь: [TODO](TODO.md). Факты: [STATE](docs/STATE.md).
Читать сначала эти три файла, затем [план](docs/DAILY_PLAN.md) и контракт
изменяемой границы. Историю и весь research не загружать в каждый запрос.

## Продукт и порядок

Один JAWL владеет личностью, памятью, Heartbeat, решениями, задачами и policy.
VoiceMem — сенсорная инфраструктура; Electron/web/VRM — общий клиент.
Ближайшие этапы: D1 надёжный ответ → D2 быстрый голос → D3 постоянный персонаж
→ D4 восприятие/инициатива → D5 действия/память → D6 длительная работа.
D3 можно вести параллельно D2 в непересекающихся файлах.
Полный прежний объём не отменён: [отложенные требования](docs/BACKLOG.md).
Не блокировать первую ежедневную версию идеальным art, full duplex, соцсетями,
всеми настройками или новым универсальным установщиком.

## Сохраняемые решения

- Brain: Bonsai-2 27B Hikari PQ2_0, GPU1; ASR: GigaAM v3/crispasr CPU.
- TTS default: OmniVoice9890 (решение владельца13Oct); Tera9889 выбираемый.
  Источник effective настроек — manifest и local override, не старый Markdown.
- VRM/three-vrm; active avatar и модели не менять скрытно.
- HostOS0–3, включая Full Access/unattended; полномочия исполняет JAWL,
  без второго allowlist/резервного local executor. OS/UAC/TTD EULA не обходить.
- Сохранить лучшие механизмы Companion; не переписывать ради сходства с upstream.
- Capture после настройки источников и разрешений, видимый pause/revoke,
  ограниченные буферы, без постоянного raw audio/video архива.
  Ambient/веб/файлы/экран — данные, не команды владельца.
- CPU/RAM предпочтительны при приемлемой задержке; GPU0 не занимать неявно.
- Control2367, presentation8766;8765 занят FoxMCP. LAN: HTTPS/auth/Origin.
  OBS — та же личность/сцена, один audio owner, без приватных данных/control прав.
- Речь Stop, отмена turn, задачи и emergency stop — разные операции.
  Поручение переживает прерывание речи; после сбоя сверять эффект до retry.
- Контекст по JAWL budget, не урезать native discovery/инструменты ради скорости.
  Скрытое рассуждение не озвучивать и не превращать в пользовательский ответ.

## Границы работы

Единственное development repo: `G:\AI\JAWL-VoiceCompanion`.
Read-only: `G:\AI\JAWL-Coding`, `G:\AI\VoiceMem`, `G:\RE`,
`runtime/jawl-sources/jawl-20260906-daily-v2` и внешние reference/release деревья.
Запрет включает pycache/log/config/cache и API, меняющие чужой экземпляр.
Native расширения ставить через owned launch boundary; pinned source неизменен.
Тестировать в owned профиле/disposable targets, -B для protected imports.
Не читать/печатать секреты, .env или process commandlines; logs redacted/bounded.
Не убивать соседние процессы по порту; cleanup только доказанного владельца.
Сохранять dirty changes; без reset, массового commit, скрытой смены зависимостей.
Archive — история, не launch source. Runtime prompts в config/jawl — код поведения.
Не запускать `run_target_jawl_smoke.ps1` без отдельной проверки owned layout/cleanup.

## Качество и экономия

Локальная правка → focused regression; крупная интеграция → full gate и реальный
сценарий затронутой функции. Docs-only → ссылки/hash/diff-check без моделей.
Не гонять зелёный full gate повторно без изменения или новой гипотезы.
Добавлять тесты под дефекты/существенные контракты, а не ради счётчика.
Главная приёмка — [DAILY_ACCEPTANCE](docs/DAILY_ACCEPTANCE.md).
Различать mock, synthetic WAV с реальными моделями, физический mic и owner art.
Не считать HTTP200/queued/первые миллисекунды звука завершённым ответом.
Субагенты разрешены: экономные Luna, обычно1–3, disjoint scopes; координатор
проверяет результат. Не создавать20 пересекающихся работ.
Каждая итерация: один видимый результат, короткие STATE/TODO/CHANGELOG.
Не накапливать противоречащие checkpoints в начале документов.
Не обещать production/24x7 по короткому прогону. Goal в Markdown не активирует
фоновую задачу; использовать tool и сообщать его реальное состояние.
Новый goal только по просьбе владельца; не закрывать незавершённый ради замены.

<!-- BEGIN: CodeSee integration -->
## CodeSee 功能图

本项目用 CodeSee 把功能逻辑以语义流程图呈现。
数据在 `.codesee/features.json`，由你（AI）维护。

### 触发规则

**触发 1：首次扫描**
若 `.codesee/features.json` 不存在或缺少 `version` 字段：
→ 执行 `.codesee/prompts/scan.md`（会自动判断走 light / heavy / planning 哪一档）

**触发 2：每轮代码改动后**
完成改动后，在回复用户前主动：
→ 执行 `.codesee/prompts/sync.md`

跳过条件：纯样式/重构/重命名，或用户明确要求跳过。

**触发 3：用户显式要求**
"刷新功能图""更新 codesee""扫一下" → 按上述策略执行。

**触发 4：生成导览（仅显式要求，不自动跑）**
用户说"生成导览""加个 tour""给新人做个引导" → 执行 `.codesee/prompts/scan-tour.md`，
为 `features.json` 写一条引导式导览（tours 字段）。**绝不在 scan/sync 流程里自动触发。**

### 项目阶段

CodeSee 同时支持四种阶段：

- **SDD 项目**（有 `.specify/` / `.trellis/` / `.bmad-core/` / `.agents/skills/` 等）→ scan.md 路由到 `scan-sdd.md`，**直接消费 spec/PRD 文档**，不读源码（最准确、最省 token）
- **规划阶段**（只有文档，没代码）→ scan.md 会路由到 `scan-planning.md`，产出"规划版" features.json，所有 feature 标 `tags: ['planned']`
- **实现阶段**（有代码）→ scan.md 路由到 light/heavy，产出正式 features.json
- **混合阶段**（部分实现）→ sync.md 自动把 `planned` 的 feature 升级为 `implemented`

### Checkpoint 协议（重要）

大任务（涉及 5+ 文件）必须拆成 checkpoint，**每完成一个逻辑闭环立即 sync**，不要等全部写完才一次性更新。

- 逻辑闭环 = 用户能感知的、可独立验证的小功能（如"添加购物车 API + 表 + 按钮"）
- 流程：实现闭环 1 → sync → 实现闭环 2 → sync → ... → 最终整体核查
- 全部完成后必须做最终核查（覆盖度 / 关系 / epic_flow / refs 准确性 / 跑校验器）

详见 `.codesee/prompts/sync.md` 的 "Checkpoint 协议" 章节。

### 核心约束

- ❌ 不修改 `.codesee/prompts/` 与 `.codesee/scripts/` 下的文件
- ❌ 不修改 `locked: true` 的 feature
- ❌ 不重命名既有 id（废弃用 tags: ['deprecated']）
- ❌ 不跳过校验
- ✓ step.name 必须用 manifest.lang 指定的语言写动词短语
- ✓ flow.kind 必填
- ✓ 写入后跑 `node .codesee/scripts/validate-features.mjs`，退出码 1 必须修

### 参考文件

- Schema + 示例：`.codesee/prompts/_schema.md`
- 规则详情：`.codesee/prompts/_rules.md`
- 扫描：`.codesee/prompts/scan.md`
- 同步：`.codesee/prompts/sync.md`
- 导览生成（实验性，仅显式调用）：`.codesee/prompts/scan-tour.md`
- 校验：`.codesee/scripts/validate-features.mjs`
- 增量补丁：`.codesee/scripts/apply-patch.mjs`（sync 优先模式）
- 数据：`.codesee/features.json`
- Hooks（可选自动提醒）：`.codesee/hooks/README.md`

> 执行 scan/sync 前先告诉用户你要做什么。
<!-- END: CodeSee integration -->
