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
matrix_05 = IncrementalSpatialMatrix(grid_shape=(21, 30), keyframe_interval=60, tile_delta_threshold=0.05)

dirty_history_05 = []
for i in range(50):
    frame = cap.grab()
    if frame is not None:
        changed, dirty, bbox = matrix_05.update(frame, commit=True)
        dirty_history_05.append((i, dirty))
    time.sleep(0.05)

cap.stop()
driver.quit()

print("With tile_delta_threshold=0.05:")
for tick, d in dirty_history_05[:25]:
    print(f"Tick {tick:02d}: dirty = {d}")
non_kf = [d for tick, d in dirty_history_05 if tick != 0 and tick != 60]
print(f"Non-keyframe dirty > 0 count: {sum(1 for d in non_kf if d > 0)} / {len(non_kf)}")
print("Sample non-zero dirty:", [d for d in non_kf if d > 0][:15])
