"""Experimental verification of Kernel & Vision Hypotheses:
1. AVX2/Int32 SIMD-style downsampling vs Numpy vs Naive
2. DWM extended frame bounds and foreground window cropping
"""

from __future__ import annotations

import time
import ctypes
from ctypes import wintypes
import numpy as np

# --- Experiment 1: DWM Extended Frame Bounds (Hypothesis 6) ---
def get_foreground_window_dwm_rect():
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None

    # Get Window Title
    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    title = buff.value

    # DWMWA_EXTENDED_FRAME_BOUNDS = 9 (accurate physical bounds excluding drop shadow)
    rect = wintypes.RECT()
    res = dwmapi.DwmGetWindowAttribute(
        hwnd,
        9,  # DWMWA_EXTENDED_FRAME_BOUNDS
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if res == 0:
        return title, (rect.left, rect.top, rect.right, rect.bottom)
    
    # Fallback to GetWindowRect
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return title, (rect.left, rect.top, rect.right, rect.bottom)


# --- Experiment 2: Fast Integer Math / Strided Kernel Benchmark (Hypothesis 8) ---
def benchmark_downsampling_kernels():
    # 1080p synthetic frame
    frame = np.random.randint(0, 256, (1080, 1920, 3), dtype=np.uint8)
    grid_size = 64

    # Baseline: float32 multiply and sum
    def kernel_float(f):
        h, w = f.shape[:2]
        sub = f[:: h // grid_size, :: w // grid_size][:grid_size, :grid_size]
        return (sub[:, :, 0] * 0.299 + sub[:, :, 1] * 0.587 + sub[:, :, 2] * 0.114).astype(np.float32)

    # Fast Integer Vectorized: (R*77 + G*150 + B*29) >> 8
    def kernel_int_shift(f):
        h, w = f.shape[:2]
        sub = f[:: h // grid_size, :: w // grid_size][:grid_size, :grid_size]
        s0 = sub[:, :, 0].astype(np.int32)
        s1 = sub[:, :, 1].astype(np.int32)
        s2 = sub[:, :, 2].astype(np.int32)
        return ((s0 * 77 + s1 * 150 + s2 * 29) >> 8).astype(np.uint8)

    # Benchmark 200 iterations
    t0 = time.perf_counter()
    for _ in range(200):
        res_float = kernel_float(frame)
    t_float = (time.perf_counter() - t0) / 200 * 1000

    t1 = time.perf_counter()
    for _ in range(200):
        res_int = kernel_int_shift(frame)
    t_int = (time.perf_counter() - t1) / 200 * 1000

    return t_float, t_int


def main():
    print("=" * 70)
    print("KERNEL & VISION HYPOTHESES BENCHMARK")
    print("=" * 70)

    # 1. Test DWM Foreground Window
    title, bounds = get_foreground_window_dwm_rect()
    print(f"\n[DWM Kernel Test (Hypothesis 6)]")
    print(f"  Active Window Title: {title!r}")
    print(f"  DWMWA_EXTENDED_FRAME_BOUNDS: {bounds}")
    if bounds:
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        print(f"  Resolution: {w}x{h} ({w*h/(1920*1080)*100:.1f}% of 1080p desktop)")

    # 2. Test Downsampling Kernels
    t_fl, t_i = benchmark_downsampling_kernels()
    print(f"\n[Luminance Downsampling Kernel Test (Hypothesis 8)]")
    print(f"  Float32 Math: {t_fl:.4f} ms")
    print(f"  Int32 Bit-Shift Math: {t_i:.4f} ms")

if __name__ == "__main__":
    main()
