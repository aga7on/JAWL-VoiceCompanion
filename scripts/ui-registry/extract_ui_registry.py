"""U0 registry extractor: DOM controls, schema keys and endpoints of both panels.

Writes a machine-readable registry to docs/ui-registry/ for the U0 parity work.
"""
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
SNAP = REPO / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
OUT = REPO / "docs" / "ui-registry"
OUT.mkdir(parents=True, exist_ok=True)

html = (SNAP / "web" / "index.html").read_text(encoding="utf-8")
cfgs = re.findall(r'data-cfg="([^"]+)"', html)
groups = Counter(c.split(".")[0] for c in cfgs)
registry = {
    "source": str(SNAP),
    "dom_data_cfg_total": len(cfgs),
    "dom_groups": dict(sorted(groups.items())),
    "dom_keys": sorted(cfgs),
}

js = (SNAP / "web" / "console.js").read_text(encoding="utf-8")
api_calls = sorted(set(re.findall(r"['\"](/api/[^'\"?$]+)", js)))
registry["console_js_api_calls"] = api_calls

server = (SNAP / "src" / "web" / "server.py").read_text(encoding="utf-8")
routes = re.findall(r"app\.router\.add_(get|post|put|delete)\(\"([^\"]+)\",\s*(\w+)\)", server)
registry["console_endpoints"] = [
    {"method": m.upper(), "route": r, "handler": h} for m, r, h in routes
]

schema = (SNAP / "src" / "web" / "schema.py").read_text(encoding="utf-8")
schema_blocks = {}
for block in re.finditer(r"^([A-Z_]+): Dict\[str, str\] = \{(.*?)^\}", schema, re.MULTILINE | re.DOTALL):
    name, body = block.group(1), block.group(2)
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', body)
    if pairs:
        schema_blocks[name] = dict(pairs)
registry["schema_blocks"] = {k: len(v) for k, v in schema_blocks.items()}
registry["schema_mapped_total"] = sum(len(v) for v in schema_blocks.values())

# data-cfg keys that exist in the DOM but have no schema mapping
mapped = set()
for block in schema_blocks.values():
    mapped.update(block.keys())
registry["dom_keys_without_schema_mapping"] = sorted(set(cfgs) - mapped)

comp_html = (REPO / "frontend" / "index.html").read_text(encoding="utf-8")
comp_api = sorted(set(re.findall(r"['\"](/api/[^'\"?$]+)", comp_html)))
registry["companion_ui_api_calls"] = comp_api

console_routes = {f"/api/{r.split('/api/')[-1]}" for _, r, _ in routes}
registry["console_js_calls_not_in_routes"] = sorted(
    c for c in api_calls if not any(c.startswith(r.rstrip("/")) or c == r for r in console_routes)
)

out_file = OUT / "registry.json"
out_file.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"written: {out_file}")
print(f"data-cfg total: {len(cfgs)}")
print("DOM groups:", dict(sorted(groups.items())))
print(f"console endpoints: {len(routes)}")
print(f"console.js api calls: {len(api_calls)}")
print(f"companion ui api calls: {len(comp_api)}")
print(f"schema blocks: { {k: len(v) for k, v in schema_blocks.items()} }")
print(f"schema mapped total: {registry['schema_mapped_total']}")
unmapped = registry["dom_keys_without_schema_mapping"]
print(f"dom keys without schema mapping: {len(unmapped)}")
for key in unmapped[:25]:
    print("  -", key)
print("console.js calls not in routes:", registry["console_js_calls_not_in_routes"])
