# -*- coding: utf-8 -*-
"""Offline canvas rendering diagnostic (no models, no GPU): verifies the new
hint-free test window renders correctly and the captured frame contains the
blue triangle at the expected position. Zero frames written to disk."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_step27_true_e2e_acceptance import OwnedTestWindow  # noqa: E402
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402


def main() -> int:
    win = OwnedTestWindow()
    win.start()
    try:
        win.bring_to_front()
        time.sleep(0.3)

        adapter = ScreenCaptureAdapter(enabled=True)
        grabbed = adapter.grab_pil_with_timestamp()
        frame, t_cap = grabbed if grabbed else (None, 0.0)
        if frame is None:
            print("FAIL: no frame captured")
            return 1
        t_capture = t_cap

        print(f"Frame: {frame.size}, display_index={adapter.display_index}, t_capture={t_capture:.3f}")
        print(f"Window title: '{win.title}' (hint-free check: no 'JAWL'/'Canvas'/'Autonomous'/'Test Target')")

        # Triangle center in window client coords: (400, 300) -> screen (500, 400)
        # (window at 100,100, 800x600). Monitor 0 = (0,0,1920,1080), frame downscaled
        # to max 1280x720 (from 1920x1080 -> scale 2/3): frame point ~ (333, 266).
        scale_x = frame.size[0] / 1920.0
        scale_y = frame.size[1] / 1080.0
        tri_x = int(500 * scale_x)
        tri_y = int(400 * scale_y)
        px_tri = frame.getpixel((tri_x, tri_y))
        is_blue_tri = px_tri[0] < 60 and px_tri[2] > 140
        print(f"Triangle center frame point ({tri_x},{tri_y}) RGB={px_tri} -> blue={is_blue_tri}")

        # Triangle edge (wide base, y=420 client -> screen 520): expect blue near (600, 520) screen
        base_x = int(600 * scale_x)
        base_y = int(520 * scale_y)
        px_base = frame.getpixel((base_x, base_y))
        is_blue_base = px_base[0] < 60 and px_base[2] > 140
        print(f"Triangle base point frame ({base_x},{base_y}) RGB={px_base} -> blue={is_blue_base}")

        # Background point (top-left inside window, e.g. client (80, 150) -> screen (180, 250)):
        # expect light gray (0xEEEEEE)
        bg_x = int(180 * scale_x)
        bg_y = int(250 * scale_y)
        px_bg = frame.getpixel((bg_x, bg_y))
        is_gray_bg = px_bg[0] > 200 and px_bg[1] > 200 and px_bg[2] > 200
        print(f"Background point frame ({bg_x},{bg_y}) RGB={px_bg} -> gray={is_gray_bg}")

        # Digit area (white text on blue, client ~(400, 310) center of digit rect):
        # inside triangle, expect NOT gray background: either blue or white pixel
        dig_x = int(500 * scale_x)
        dig_y = int(410 * scale_y)
        px_dig = frame.getpixel((dig_x, dig_y))
        print(f"Digit area point frame ({dig_x},{dig_y}) RGB={px_dig}")

        ok = is_blue_tri and is_blue_base and is_gray_bg
        print(f"\nVERDICT: {'RENDERING OK (hint-free canvas, blue triangle present)' if ok else 'RENDERING FAIL'}")
        print("Frame stored to disk: False (privacy invariant)")
        return 0 if ok else 1
    finally:
        win.close()


if __name__ == "__main__":
    sys.exit(main())
