import json
from pathlib import Path
from collections import Counter

gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
with open(gt_path, "r", encoding="utf-8") as f:
    gt = json.load(f)

events = gt["speech_events"]
gt_frames = {f["frame_idx"]: f for f in gt["frames"]}

print(f"Total speech events: {len(events)}")
char_counts = Counter(e["speaker"] for e in events)
print("Turns per character:")
for c, cnt in char_counts.most_common():
    print(f"  {c:12s}: {cnt} turns")

print("\nDetail of all 40 turns:")
print(f"{'ID':2s} | {'Time (s)':13s} | {'Speaker':12s} | {'Off?':5s} | {'Vis Chars':25s} | Text")
print("-" * 80)
for e in events:
    tid = e["turn_id"]
    t_span = f"{e['start_sec']:5.1f} - {e['end_sec']:5.1f}"
    spk = e["speaker"]
    off = str(e["is_offscreen"])
    
    # check frames
    f_start = int(round(e["start_sec"] * 2.0))
    f_end = int(round(e["end_sec"] * 2.0))
    vis = set()
    for fi in range(f_start, f_end + 1):
        if fi in gt_frames:
            for c in gt_frames[fi]["characters"]:
                vis.add(f"{c['character_id']}({c['visual_state'][0]})")
    vis_str = ", ".join(sorted(vis)) if vis else "NONE"
    
    txt = e["text"][:30]
    print(f"{tid:2d} | {t_span:13s} | {spk:12s} | {off:5s} | {vis_str:25s} | {txt}")
