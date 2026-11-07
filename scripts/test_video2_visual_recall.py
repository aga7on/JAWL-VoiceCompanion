"""Test visual recall and foveal crop inspection on Video 2 (Infographics)."""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory

ROOT = Path(__file__).resolve().parent.parent
v2_mem = ROOT / "runtime/instances/daily/data/sensory/youtube_watch/video2/visual_memory"
if not v2_mem.exists():
    v2_mem = ROOT / "runtime/instances/daily/data/sensory/youtube_watch_video2/visual_memory"

mem = EpisodicVisualMemory(
    db_path=v2_mem / "lancedb",
    image_cache_dir=v2_mem / "keyframes",
)

queries = [
    "график времени и задержки 100 секунд",
    "видеокарта Radeon 16 ГБ",
    "архитектура DeepSeek инфографика",
    "токены системного промпта 37000",
]

print("=" * 60)
print("TESTING EPISODIC VISUAL RECALL ON VIDEO 2 (INFOGRAPHICS)")
print("=" * 60)

for q in queries:
    results = mem.search_visual(q, top_k=2)
    print(f"\nQuery: '{q}' -> Hits: {len(results)}")
    for r in results:
        meta = r.get("metadata", {})
        print(f"  Sim: {r['similarity']:.3f} | Scene: {r['scene_id']} | Image: {Path(r['image_path']).name}")
        print(f"    Timestamp: {meta.get('timestamp_str')} (sec {meta.get('video_time_sec')}) | Saliency: {meta.get('saliency_delta')}")
        if meta.get("foveal_path"):
            print(f"    Foveal Crop 1:1: {Path(meta['foveal_path']).name}")
