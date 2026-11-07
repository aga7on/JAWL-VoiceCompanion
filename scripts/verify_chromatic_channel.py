import numpy as np
import time

# Create isoluminant frames (Red -> Green)
frame_red = np.zeros((1080, 1920, 3), dtype=np.uint8)
frame_red[400:600, 800:1000] = [200, 0, 0]

frame_green = np.zeros((1080, 1920, 3), dtype=np.uint8)
frame_green[400:600, 800:1000] = [0, 100, 0]

# Old Luma-only calculation:
def get_luma(frame):
    trimmed = frame[::4, ::4]
    luma = (trimmed[:, :, 0].astype(np.uint16) + (trimmed[:, :, 1].astype(np.uint16) << 1) + trimmed[:, :, 2].astype(np.uint16)) >> 2
    # reshape 21x30
    h, w = luma.shape
    th, tw = h // 21, w // 30
    luma_trim = luma[:21*th, :30*tw]
    blocked = luma_trim.reshape(21, th, 30, tw).transpose(0, 2, 1, 3)
    return blocked.mean(axis=(2, 3)) / 255.0

luma_red = get_luma(frame_red)
luma_green = get_luma(frame_green)
diff_old = np.abs(luma_green - luma_red)
print("Old Luma max diff:", np.max(diff_old))
print("Old Luma dirty tiles (>0.03):", np.sum(diff_old > 0.03))

# New Opponent-Color augmented calculation:
def get_luma_and_chroma(frame):
    trimmed = frame[::4, ::4]
    r = trimmed[:, :, 0].astype(np.int16)
    g = trimmed[:, :, 1].astype(np.int16)
    b = trimmed[:, :, 2].astype(np.int16)
    
    luma = (r + (g << 1) + b) >> 2
    crg = (r - g)
    cby = (b - ((r + g) >> 1))
    
    h, w = luma.shape
    th, tw = h // 21, w // 30
    
    b_y = luma[:21*th, :30*tw].reshape(21, th, 30, tw).transpose(0, 2, 1, 3).mean(axis=(2, 3)) / 255.0
    b_crg = crg[:21*th, :30*tw].reshape(21, th, 30, tw).transpose(0, 2, 1, 3).mean(axis=(2, 3)) / 255.0
    b_cby = cby[:21*th, :30*tw].reshape(21, th, 30, tw).transpose(0, 2, 1, 3).mean(axis=(2, 3)) / 255.0
    
    return b_y.astype(np.float32), b_crg.astype(np.float32), b_cby.astype(np.float32)

t0 = time.perf_counter()
for _ in range(100):
    y_r, crg_r, cby_r = get_luma_and_chroma(frame_red)
    y_g, crg_g, cby_g = get_luma_and_chroma(frame_green)
    diff_new = np.maximum(np.abs(y_g - y_r), np.maximum(np.abs(crg_g - crg_r) * 0.7, np.abs(cby_g - cby_r) * 0.7))
t_elapsed = (time.perf_counter() - t0) * 10 / 2 # ms per frame

print(f"New computation time: {t_elapsed:.3f} ms per frame")
print("New max diff on isoluminant Red->Green:", np.max(diff_new))
print("New dirty tiles (>0.03):", np.sum(diff_new > 0.03))
