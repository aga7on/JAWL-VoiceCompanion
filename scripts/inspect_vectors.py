import lancedb
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
db_path = ROOT / "runtime/instances/daily/data/sensory/youtube_watch/video1/visual_memory/lancedb"
db = lancedb.connect(str(db_path))
table = db.open_table("keyframes")
pydict = table.to_arrow().to_pydict()

total_rows = len(pydict['vector'])
print(f"Total rows in keyframes: {total_rows}")
print("Vector length:", len(pydict['vector'][0]))
for i in range(total_rows):
    img_name = Path(pydict['image_path'][i]).name
    ts = pydict['timestamp'][i]
    vec = np.array(pydict['vector'][i])
    print(f"  Row {i}: TS={ts} | Path={img_name} | norm={np.linalg.norm(vec):.4f}, mean={np.mean(vec):.6f}, std={np.std(vec):.6f}")

v0 = np.array(pydict['vector'][0])
v1 = np.array(pydict['vector'][1])
dot = np.dot(v0, v1)
print(f"\nCosine similarity between frame 0 and frame 1 vectors: {dot:.6f}")
