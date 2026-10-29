"""Score content-vision captions against the pre-listed manifest."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "runtime/vlm-cpu-bench/video/manifest.json").read_text(encoding="utf-8"))

HALLUCINATIONS = [
    "moon", "parachute", "light fixture", "room", "wall", "person", "people",
    "man", "woman", "car", "tree", "building", "animal", "star", "table",
    "window", "curtain", "flower", "chair", "phone", "book",
]
EARTH_CATEGORIES = {
    "earth": ["earth", "planet", "globe", "world"],
    "lights": ["city light", "night light", "illuminated", "lights", "lit city", "lit cities", "lit land"],
    "land": ["continent", "land", "landmass", "ocean", "coast"],
    "clouds": ["cloud"],
    "space": ["space", "void", "black", "dark background", "blackness"],
    "terminator": ["terminator", "day-night", "day night", "shadow line", "sunlight", "shadow"],
}
ICON_CATEGORIES = {
    "icon": ["bracket", "rectangle", "symbol", "icon", "yellow", "golden", "dot"],
}
PAIR_ACTIONS = {
    "5-6": ["cut", "scene change", "changes to", "switches", "transition", "appears", "different"],
    "6-7": ["icon", "bracket", "rectangle", "symbol", "yellow", "golden", "gold", "dot", "remains", "same"],
    "7-8": ["cut", "scene change", "changes to", "switches", "transition", "appears", "earth", "planet"],
    "9-10": ["rotat", "shift", "moving", "motion", "continent", "land", "cloud"],
}


def match(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def score_text(text: str, scene: str) -> dict:
    categories = EARTH_CATEGORIES if scene == "earth" else ICON_CATEGORIES
    hits = {name: match(text, words) for name, words in categories.items()}
    fabrications = [word for word in HALLUCINATIONS if word in text.lower()]
    return {
        "hits": hits,
        "correct": sum(1 for value in hits.values() if value),
        "total": len(hits),
        "misses": [name for name, value in hits.items() if not value],
        "fabrications": fabrications,
    }


def main() -> int:
    qwen = json.loads((ROOT / "runtime/vlm-cpu-bench/content/qwen3.5-0.8b.json").read_text(encoding="utf-8"))
    florence = json.loads((ROOT / "runtime/vlm-cpu-bench/content/florence2-base-ft.json").read_text(encoding="utf-8"))
    for label, data in (("qwen3.5-0.8b", qwen), ("florence2-base-ft", florence)):
        print(f"\n=== {label} ===")
        totals = {"correct": 0, "total": 0, "fabrications": 0}
        for case in data["cases"]:
            if case.get("kind") != "single":
                continue
            expected = MANIFEST["frames"][case["frame"] - 1]
            result = score_text(case.get("caption", ""), expected["scene"])
            totals["correct"] += result["correct"]
            totals["total"] += result["total"]
            totals["fabrications"] += len(result["fabrications"])
            print(
                f"frame {case['frame']:02d} {expected['scene']:9s} "
                f"{result['correct']}/{result['total']} "
                f"misses={result['misses']} fabrications={result['fabrications']} | {case.get('caption','')[:140]}"
            )
        print(f"single totals: correct={totals['correct']}/{totals['total']} fabrications={totals['fabrications']}")
        pair_correct = 0
        pair_total = 0
        pair_fab = 0
        for case in data["cases"]:
            if case.get("kind") != "pair":
                continue
            pair = case.get("pair")
            keywords = PAIR_ACTIONS.get(pair, [])
            ok = match(case.get("caption", ""), keywords)
            pair_correct += int(ok)
            pair_total += 1
            fab = [word for word in HALLUCINATIONS if word in case.get("caption", "").lower()]
            pair_fab += len(fab)
            print(f"pair {pair} action_ok={ok} fabrications={fab} | {case.get('caption','')[:160]}")
        print(f"pair totals: action_ok={pair_correct}/{pair_total} fabrications={pair_fab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
