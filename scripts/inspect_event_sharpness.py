"""Inspect sharpness and overexposure across the 35 benchmark events."""

import json
from pathlib import Path
from jawl_voicecompanion.segment_inspector import compute_image_sharpness, check_overexposure
from jawl_voicecompanion.retro_selector import VideoWindowDecoder

video_path = Path("runtime/instances/realistic_retro_bench/realistic_gameplay_60fps.mp4")
gt_path = Path("runtime/instances/realistic_retro_bench/ground_truth_events.json")

events = json.loads(gt_path.read_text(encoding="utf-8"))
decoder = VideoWindowDecoder(video_path)

for ev in events:
    t_start = ev["start_time_s"] * 1000.0
    t_end = t_start + ev["duration_ms"]
    frames = decoder.decode_window(t_start, t_end)
    if not frames:
        continue
    roi = ev.get("roi")
    sharpnesses = [compute_image_sharpness(f[2], roi) for f in frames]
    overexposures = [check_overexposure(f[2], roi) for f in frames]
    max_sh = max(sharpnesses) if sharpnesses else 0.0
    mean_sh = sum(sharpnesses) / len(sharpnesses) if sharpnesses else 0.0
    over_cnt = sum(overexposures)
    print(
        f"{ev['event_id']:8s} | readable={str(ev.get('readable', True)):5s} | "
        f"max_sh={max_sh:7.1f} | mean_sh={mean_sh:7.1f} | over={over_cnt:2d}/{len(frames):2d} | "
        f"cat={ev.get('category')}"
    )
