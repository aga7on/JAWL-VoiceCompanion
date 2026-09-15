"""Generate the human-readable U0 registry markdown from registry.json."""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
reg = json.loads((REPO / "docs" / "ui-registry" / "registry.json").read_text(encoding="utf-8"))

lines = []
lines.append("# Реестр UI-функций: JAWL-консоль vs Companion (U0)")
lines.append("")
lines.append("Источник: снапшот jawl-20260906-daily-v2 + фронт компаньона. ")
lines.append("Сгенерировано `extract_ui_registry.py`; обновлять при изменении панелей.")
lines.append("")
lines.append("## Сводка")
lines.append("")
lines.append(f"- DOM-контролов консоли (data-cfg): **{reg['dom_data_cfg_total']}**")
lines.append(f"- Схема-маппинг (config/env записи): **{reg['schema_mapped_total']}**")
lines.append(f"- Без маппинга: **{len(reg['dom_keys_without_schema_mapping'])}** — все `settings:system.db.sql.drives.*`, пишутся через `/api/drives` (отдельный writer, осознанно)")
lines.append(f"- Эндпоинтов консоли: **{len(reg['console_endpoints'])}**; вызовы console.js не выходят за роуты: **{not reg['console_js_calls_not_in_routes']}**")
lines.append(f"- Вызовов API в UI компаньона: **{len(reg['companion_ui_api_calls'])}**")
lines.append("")

lines.append("## Группы DOM-контролов консоли")
lines.append("")
lines.append("| Группа | Контролов | Владелец данных | Вердикт |")
lines.append("|---|---|---|---|")
owners = {
    "settings": "JAWL config (settings.yaml)",
    "interfaces": "JAWL config (interfaces.yaml)",
    "env": ".env (секреты)",
}
verdicts = {
    "settings": "migrate (U4)",
    "interfaces": "migrate (U4)",
    "env": "migrate с secret-семантикой (U4)",
}
for group, count in sorted(reg["dom_groups"].items(), key=lambda kv: -kv[1]):
    prefix = group.split(":")[0]
    lines.append(f"| {group} | {count} | {owners.get(prefix, '?')} | {verdicts.get(prefix, 'inventory')} |")
lines.append("")

lines.append("## Контролы без schema-маппинга (drives — отдельный writer)")
lines.append("")
lines.append("Все 14: `settings:system.db.sql.drives.*` → `/api/drives` GET/PUT. Verdict: **keep** (отдельный API, переносится как блок «Мотивация» с собственным сохранением).")
lines.append("")

lines.append("## Эндпоинты консоли (31)")
lines.append("")
lines.append("| Метод | Роут | Handler | Примечание для переноса |")
lines.append("|---|---|---|---|")
notes = {
    "/api/db/wipe": "CRITICAL: двойное подтверждение + владелец JAWL",
    "/api/hostos/emergency-stop": "CRITICAL: явное действие",
    "/api/hostos/emergency-stop/reset": "CRITICAL: явное действие",
    "/api/agent/stop": "CRITICAL: lifecycle",
    "/api/agent/start": "CRITICAL: lifecycle",
    "/api/config": "главный writer настроек (PUT, revision)",
    "/api/drives": "отдельный writer drives",
    "/api/fs/open": "локальный shell — только loopback",
    "/api/debug/skill": "RE/debug — отдельно, с ограничением",
}
for ep in reg["console_endpoints"]:
    note = notes.get(ep["route"], "")
    lines.append(f"| {ep['method']} | `{ep['route']}` | {ep['handler']} | {note} |")
lines.append("")

lines.append("## Вызовы API в UI компаньона (42) и дубль-анализ")
lines.append("")
lines.append("Консольные зоны, которые компаньон уже покрывает нативно (не переносить второй раз):")
comp = reg["companion_ui_api_calls"]
native = sorted(c for c in comp if c.startswith(("/api/voice", "/api/tts", "/api/avatar", "/api/mic", "/api/ambient", "/api/attention", "/api/perception", "/api/proactive", "/api/vision", "/api/stream-chat", "/api/chat", "/api/session", "/api/state", "/api/history", "/api/doctor", "/api/resources", "/api/hostos/level", "/api/audit")))
for c in native:
    lines.append(f"- `{c}` — Companion native")
rest = sorted(set(comp) - set(native))
lines.append("")
lines.append("Обёртки компаньона над консольными действиями (verdict: keep, консольные дубли не переносить):")
for c in rest:
    note = ""
    if "emergency" in c:
        note = "CRITICAL-обёртка над /api/hostos/emergency-stop* — двойное подтверждение"
    elif c.startswith("/api/jawl/"):
        note = "нативный адаптер jawl_web (memory/journal/hostos/overview)"
    lines.append(f"- `{c}` — {note}")
lines.append("")
lines.append("## Открытые вопросы U0")
lines.append("")
lines.append("1. Секреты в env-группе: маскирование при чтении `/api/config` — проверить config_io (readback).")
lines.append("2. `/api/chat` GET/POST и companion turn: два писателя истории — владелец записи чата должен остаться один (JAWL).")
lines.append("3. Drives UI: свой ревизионный протокол или общий с config?")
lines.append("4. Списочные редакторы (INTERFACES_LISTS: 5, SETTINGS_LISTS: 1, ENV_LISTS: 1) — контракт добавления/удаления элементов.")

(REPO / "docs" / "ui-registry" / "UI_REGISTRY.md").write_text("\n".join(lines), encoding="utf-8")
print("written:", REPO / "docs" / "ui-registry" / "UI_REGISTRY.md")
print("lines:", len(lines))
