from jawl_voicecompanion.visual_stream import DXGIScreenCapture, IncrementalSpatialMatrix
import time
import numpy as np

cap = DXGIScreenCapture()
matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), keyframe_interval=60, tile_delta_threshold=0.05)

print("Capturing 120 frames with DXGIScreenCapture...")
dirty_counts = []
for i in range(120):
    t0 = time.monotonic()
    frame = cap.grab()
    if frame is not None:
        changed, dirty, bbox = matrix.update(frame, commit=True)
        dirty_counts.append((i, dirty, changed))
    time.sleep(0.05)

cap.stop()

print("Dirty counts distribution:")
non_zero = [d for i, d, c in dirty_counts if d > 0]
print(f"Total frames: {len(dirty_counts)}")
print(f"Non-zero dirty ticks: {len(non_zero)} / {len(dirty_counts)}")
print(f"Keyframe ticks (dirty=630): {sum(1 for i, d, c in dirty_counts if d == 630)}")
print(f"Partial dirty ticks (0 < dirty < 630): {sum(1 for i, d, c in dirty_counts if 0 < d < 630)}")
print("Sample partial dirty counts:", [d for i, d, c in dirty_counts if 0 < d < 630][:20])
