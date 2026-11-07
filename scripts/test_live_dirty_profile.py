from jawl_voicecompanion.visual_stream import DXGIScreenCapture, IncrementalSpatialMatrix
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import numpy as np

opts = Options()
opts.add_argument("--autoplay-policy=no-user-gesture-required")
opts.add_argument("--start-maximized")
driver = webdriver.Chrome(options=opts)
driver.get("https://www.youtube.com/watch?v=GXe8XEFA9Pc")
time.sleep(3)

driver.execute_script("""
var v = document.querySelector('video');
if (v) { v.currentTime = 10.0; v.play(); }
""")
time.sleep(1)

cap = DXGIScreenCapture()
matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), keyframe_interval=60, tile_delta_threshold=0.03)

dirty_history = []
max_diffs = []
for i in range(100):
    frame = cap.grab()
    if frame is not None:
        # Check raw luma diff
        luma, blocked = matrix._get_luma_tiles(frame)
        if matrix._prev_luma is not None:
            raw_diff = np.abs(luma - matrix._prev_luma)
            max_diffs.append(float(np.max(raw_diff)))
        changed, dirty, bbox = matrix.update(frame, commit=True)
        dirty_history.append((i, dirty))
    time.sleep(0.05)

cap.stop()
driver.quit()

print(f"Max luma diffs across 100 frames (min/mean/max): {min(max_diffs):.4f} / {np.mean(max_diffs):.4f} / {max(max_diffs):.4f}")
print("Dirty history sample (first 30 ticks):")
for tick, d in dirty_history[:30]:
    print(f"Tick {tick:02d}: dirty = {d}")

non_keyframe_dirty = [d for tick, d in dirty_history if tick % 60 != 0 and tick != 0]
print(f"Non-keyframe ticks: {len(non_keyframe_dirty)}")
print(f"Non-keyframe ticks with dirty > 0: {sum(1 for d in non_keyframe_dirty if d > 0)}")
print("Dirty counts distribution on non-keyframe ticks:", [d for d in non_keyframe_dirty if d > 0][:20])
