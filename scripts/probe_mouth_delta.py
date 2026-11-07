import json
from pathlib import Path
from PIL import Image
import numpy as np

gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
frames_dir = Path("runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s")
with open(gt_path, "r", encoding="utf-8") as f:
    gt = json.load(f)

# Inspect frames where one character is speaking and another is idle:
# E.g., Turn 23 (100.22 - 103.43s, frames 200 to 206)
# curly is speaking, glasses is idle
f201 = np.array(Image.open(frames_dir / "frame_0201.jpg").convert("RGB"))
f202 = np.array(Image.open(frames_dir / "frame_0202.jpg").convert("RGB"))
h, w = f201.shape[:2]

print("Frame 201-202 (Turn 23: curly speaking, glasses idle):")
for c in gt["frames"][200]["characters"]:
    cid = c["character_id"]
    st = c["visual_state"]
    b = c["bbox"]
    y1, x1, y2, x2 = int(b[0]*h), int(b[1]*w), int(b[2]*h), int(b[3]*w)
    
    # Full body delta
    body_delta = np.abs(f202[y1:y2, x1:x2].astype(float) - f201[y1:y2, x1:x2].astype(float)).mean()
    
    # Face & mouth region
    face_h = int((y2 - y1) * 0.40)
    m_y1 = y1 + int(face_h * 0.45)
    m_y2 = y1 + face_h
    m_x1 = x1 + int((x2 - x1) * 0.25)
    m_x2 = x2 - int((x2 - x1) * 0.25)
    mouth_delta = np.abs(f202[m_y1:m_y2, m_x1:m_x2].astype(float) - f201[m_y1:m_y2, m_x1:m_x2].astype(float)).mean()
    
    print(f"  {cid:12s} ({st:8s}): mouth_delta={mouth_delta:5.2f}, body_delta={body_delta:5.2f}, mouth/body={mouth_delta/(body_delta+1e-5):.2f}")
