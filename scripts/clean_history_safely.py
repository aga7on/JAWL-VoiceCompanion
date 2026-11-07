import json
import shutil
from pathlib import Path

path = Path("runtime/instances/daily/data/interfaces/host/terminal/history.json")
if path.exists():
    bak = path.with_suffix(".json.bak")
    shutil.copy2(path, bak)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned = []
    for item in data[-30:]:
        text = item.get("text", "")
        if "[CURRENT USER MESSAGE]\n" in text:
            text = text.split("[CURRENT USER MESSAGE]\n", 1)[1]
        cleaned.append(dict(item, text=text.strip()))

    with path.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"Cleaned {len(data)} turns -> {len(cleaned)} turns.")
    chars = sum(len(m["text"]) for m in cleaned)
    print(f"Remaining history characters: {chars}")
