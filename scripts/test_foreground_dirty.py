from jawl_voicecompanion.visual_stream import DXGIScreenCapture, IncrementalSpatialMatrix
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import ctypes
import time
import numpy as np

opts = Options()
opts.add_argument("--autoplay-policy=no-user-gesture-required")
opts.add_argument("--start-maximized")
driver = webdriver.Chrome(options=opts)
driver.get("https://www.youtube.com/watch?v=GXe8XEFA9Pc")
time.sleep(3)

# Force Chrome to foreground via Win32
hwnd = ctypes.windll.user32.FindWindowW(None, driver.title)
if hwnd:
    ctypes.windll.user32.ShowWindow(hwnd, 3) # SW_MAXIMIZE
    ctypes.windll.user32.SetForegroundWindow(hwnd)

driver.execute_script("""
var v = document.querySelector('video');
if (v) { v.currentTime = 10.0; v.play(); }
""")
time.sleep(1)

cap = DXGIScreenCapture()
matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), keyframe_interval=60, tile_delta_threshold=0.03)

dirty_distribution = []
for i in range(120):
    frame = cap.grab()
    if frame is not None:
        changed, dirty, bbox = matrix.update(frame, commit=True)
        dirty_distribution.append(dirty)
    time.sleep(0.05)

cap.stop()
driver.quit()

print("Distribution across 120 ticks:")
print(f"Total ticks: {len(dirty_distribution)}")
print(f"Keyframe ticks (dirty=630): {dirty_distribution.count(630)}")
print(f"Zero dirty ticks (dirty=0): {dirty_distribution.count(0)}")
partial = [d for d in dirty_distribution if 0 < d < 630]
print(f"Partial dirty ticks (0 < dirty < 630): {len(partial)}")
print(f"Min partial: {min(partial) if partial else None}")
print(f"Median partial: {int(np.median(partial)) if partial else None}")
print(f"Max partial: {max(partial) if partial else None}")
print("Sample partial dirty counts:", partial[:25])
