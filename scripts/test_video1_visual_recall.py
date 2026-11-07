"""Test semantic visual search and recall on Video 1 visual memory."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory

ROOT = Path(__file__).resolve().parent.parent
v1_mem = ROOT / "runtime/instances/daily/data/sensory/youtube_watch/video1/visual_memory"
if not v1_mem.exists():
    v1_mem = ROOT / "runtime/instances/daily/data/sensory/youtube_watch_video1/visual_memory"

mem = EpisodicVisualMemory(
    db_path=v1_mem / "lancedb",
    image_cache_dir=v1_mem / "keyframes",
)

queries = [
    "девушка разговаривает",
    "парень в очках очкарик",
    "сцена диалога персонажей",
    "комната или интерьер",
]

print("=" * 60)
print("TESTING EPISODIC VISUAL RECALL ON VIDEO 1")
print("=" * 60)

for q in queries:
    results = mem.search_visual(q, top_k=2)
    print(f"\nQuery: '{q}' -> Hits: {len(results)}")
    for r in results:
        print(f"  Sim: {r['similarity']:.3f} | Scene: {r['scene_id']} | Image: {Path(r['image_path']).name}")
        meta = r.get("metadata", {})
        print(f"    Timestamp: {meta.get('timestamp_str')} (sec {meta.get('video_time_sec')}) | Saliency: {meta.get('saliency_delta')}")
