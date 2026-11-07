from PIL import Image
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
key_dir = ROOT / "runtime/instances/daily/data/sensory/youtube_watch/video1/visual_memory/keyframes"
images = sorted(list(key_dir.glob("*.webp")))

for i, p in enumerate(images):
    im = Image.open(p)
    arr = np.array(im)
    print(f"Image {i} ({p.name}): size={im.size}, mode={im.mode}, mean_rgb={arr.mean(axis=(0,1)).astype(int)}")

im0 = Image.open(images[0])
im4 = Image.open(images[4])
diff = np.abs(np.array(im0, dtype=int) - np.array(im4, dtype=int))
print(f"Diff between img 0 and img 4: max={diff.max()}, mean={diff.mean():.4f}")
