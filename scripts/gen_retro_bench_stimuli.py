"""Round 11, Step 1 — Retrospective Perception Benchmark: stimulus generator.

Synthesizes a controlled 60 FPS 720p test video with ground-truth events for
benchmarking retrospective frame-selection strategies (A: uniform, B: spatial,
C: hybrid one-pass, D: hybrid adaptive) against an Oracle best-frame baseline.

Event classes (per approved protocol):
  T-Motion : text/code on a "door" during fast camera pan (motion blur variants)
  T-Static : popup notification with a code on a calm camera
  O-Static : small key object appearing in a nearly static scene
  O-Flash  : bright flash with an item icon (global-delta distractor)

Each event has an exact frame interval, ROI (start/end for moving targets),
true value, readability label and per-class question. Unreadable variants
exist to measure hallucination rate (expected: observed_unreadable, not a
guessed value).

The video is fully synthetic (procedural corridor, HUD overlay) — no desktop
or third-party screen content is captured or stored. Output:
  runtime/instances/retro_bench/stimuli_60fps.mp4
  runtime/instances/retro_bench/retro_bench_ground_truth.json

Runs CPU-only (PIL + numpy + ffmpeg pipe). Deterministic via fixed seed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime" / "instances" / "retro_bench"
OUT_VIDEO = OUT_DIR / "stimuli_60fps.mp4"
OUT_GT = OUT_DIR / "retro_bench_ground_truth.json"

W, H = 1280, 720
FPS = 60
DURATION_S = 120
N_FRAMES = FPS * DURATION_S
SEED = 4242
PATTERN_W = 3840  # world strip width (loopable)

FONT_PATH = "C:/Windows/Fonts/arial.ttf"

HUD_REGIONS = [
    {"name": "ammo", "roi": [16, 12, 190, 52], "dynamic": True},
    {"name": "hp_bar", "roi": [1064, 12, 200, 40], "dynamic": False},
    {"name": "minimap", "roi": [1088, 528, 176, 176], "dynamic": True},
    {"name": "subtitle", "roi": [340, 640, 600, 64], "dynamic": True},
]

SUBTITLES = [
    "Нам нужно найти выход отсюда.",
    "Ты видел этот коридор раньше?",
    "Проверь дверь, там должен быть код.",
    "Осторожно, впереди что-то сверкнуло.",
    "Ключ у тебя? Не потеряй его.",
    "Система защиты активирована.",
]


def build_world_strip(rng: np.random.RandomState) -> np.ndarray:
    """Procedural corridor wall strip (H x PATTERN_W x 3), loopable."""
    strip = np.zeros((H, PATTERN_W, 3), dtype=np.uint8)
    panel_w = 160
    x = 0
    while x < PATTERN_W:
        base = rng.randint(60, 150, size=3)
        tint = (base * np.array([0.8, 0.85, 1.15])).clip(0, 255).astype(np.uint8)
        strip[:, x : x + panel_w] = tint
        # vertical seam
        strip[:, x : x + 4] = (tint * 0.45).astype(np.uint8)
        # horizontal trim line
        strip[380:388, x : x + panel_w] = (tint * 0.6).astype(np.uint8)
        x += panel_w
    # ceiling band
    strip[:80, :] = (strip[:80, :] * 0.45).astype(np.uint8)
    # floor band with tiles
    strip[560:, :] = (strip[560:, :] * 0.55).astype(np.uint8)
    for fx in range(0, PATTERN_W, 120):
        strip[560:, fx : fx + 5] = (25, 25, 30)
    # subtle noise texture (deterministic)
    noise = rng.randint(-6, 7, size=(H, PATTERN_W, 3), dtype=np.int16)
    strip = (strip.astype(np.int16) + noise).clip(0, 255).astype(np.uint8)
    return strip


def hsmear_rgba(img: Image.Image, k: int) -> Image.Image:
    """Horizontal box smear of an RGBA overlay (motion blur of text)."""
    if k <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    out = np.zeros_like(arr)
    for d in range(-k, k + 1):
        out += np.roll(arr, d, axis=1)
    out /= 2 * k + 1
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def make_code_overlay(text: str, font: ImageFont.FreeTypeFont, fg=(245, 245, 245), smear: int = 0) -> Image.Image:
    ov = Image.new("RGBA", (220, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.text((110, 32), text, font=font, fill=fg + (255,), anchor="mm")
    if smear > 0:
        ov = hsmear_rgba(ov, smear)
    return ov


def schedule_events(rng: np.random.RandomState) -> list[dict]:
    """Deterministic event schedule: up to 22 events, >=4s apart.

    Plan entries carry (class, duration_ms, forced_unreadable). The two appended
    T-Motion and two appended O-Flash entries are forced unreadable to measure
    hallucination rate (the only correct outcome for them is observed_unreadable).
    """
    events: list[dict] = []
    t = 3.0
    plan: list[tuple[str, int, bool]] = []
    for cls in ("T-Motion", "T-Static", "O-Static", "O-Flash"):
        for dur in (100, 150, 250, 500):
            plan.append((cls, dur, False))
    # unreadable controls: heavy motion blur codes + flash-saturated items
    plan += [
        ("T-Motion", 150, True),
        ("T-Motion", 250, True),
        ("O-Flash", 150, True),
        ("O-Flash", 250, True),
    ]
    rng.shuffle(plan)
    used_codes: set[str] = set()

    for i, (cls, dur_ms, forced_unreadable) in enumerate(plan):
        if t + dur_ms / 1000.0 > DURATION_S - 3:
            break
        ev: dict = {
            "event_id": f"ev{i:02d}_{cls}",
            "class": cls,
            "start_ms": round(t * 1000.0, 1),
            "duration_ms": dur_ms,
        }
        if cls in ("T-Motion", "T-Static"):
            while True:
                code = "".join(str(d) for d in rng.randint(0, 10, size=4))
                if code not in used_codes:
                    used_codes.add(code)
                    break
            ev["value"] = code
            ev["value_type"] = "door_code" if cls == "T-Motion" else "notification_code"
            ev["question"] = (
                "Какой код был на двери?" if cls == "T-Motion" else "Какой код появился в уведомлении?"
            )
            if cls == "T-Motion":
                ev["camera"] = "fast_pan"
                ev["readable"] = not forced_unreadable
                ev["blur_px"] = 10 if forced_unreadable else 2
            else:
                ev["camera"] = "static"
                ev["readable"] = True
        elif cls == "O-Static":
            ev["value"] = "ключ"
            ev["value_type"] = "held_object"
            ev["question"] = "Какой предмет ненадолго появился внизу слева?"
            ev["camera"] = "static"
            ev["readable"] = True
        else:  # O-Flash
            ev["value"] = "красное зелье"
            ev["value_type"] = "dropped_item"
            ev["question"] = "Какой предмет выпал во время вспышки?"
            ev["camera"] = "fast_pan"
            ev["readable"] = not forced_unreadable
            ev["flash_alpha"] = 0.88 if forced_unreadable else 0.45
        events.append(ev)
        t += dur_ms / 1000.0 + rng.uniform(4.0, 7.0)
    return events


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(SEED)

    font_code = ImageFont.truetype(FONT_PATH, 40)
    font_hud = ImageFont.truetype(FONT_PATH, 26)
    font_note = ImageFont.truetype(FONT_PATH, 24)

    strip = build_world_strip(rng)

    events = schedule_events(rng)
    if not events:
        print("FAIL: empty schedule")
        return 1

    # Per-event derived frame intervals and anchors
    for ev in events:
        f0 = int(round(ev["start_ms"] / 1000.0 * FPS))
        n = max(1, int(round(ev["duration_ms"] / 1000.0 * FPS)))
        ev["start_frame"] = f0
        ev["end_frame"] = min(N_FRAMES - 1, f0 + n - 1)
        if ev["class"] == "T-Motion":
            ev["anchor_x"] = int(rng.randint(300, 900))
            ev["roi_start"] = [ev["anchor_x"], 220, 260, 240]
        elif ev["class"] == "T-Static":
            ev["roi"] = [440, 90, 400, 96]
        elif ev["class"] == "O-Static":
            ev["roi"] = [280, 500, 64, 40]
        else:
            ev["roi"] = [860, 380, 72, 88]

    # Camera plan: slow drift + fast pan windows around T-Motion/O-Flash
    pan_windows = []
    for ev in events:
        if ev.get("camera") == "fast_pan":
            t0 = ev["start_ms"] / 1000.0 - 0.6
            t1 = (ev["start_ms"] + ev["duration_ms"]) / 1000.0 + 0.6
            speed = 1000.0 if not ev["readable"] else 430.0
            direction = 1.0 if rng.rand() < 0.5 else -1.0
            pan_windows.append((t0, t1, speed * direction))

    def camera_offset(t_s: float) -> tuple[float, bool, float]:
        drift = 60.0 * np.sin(2 * np.pi * 0.05 * t_s)
        vel = 0.0
        for (t0, t1, sp) in pan_windows:
            if t0 <= t_s <= t1:
                vel = sp
                break
        return drift + vel * t_s, vel != 0.0, vel

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(OUT_VIDEO),
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None

    prev_world: np.ndarray | None = None
    t0_wall = time.monotonic()
    active_flash = 0.0
    cam_x_prev = 0.0

    for fi in range(N_FRAMES):
        t_s = fi / FPS
        t_ms = t_s * 1000.0

        cam_x, panning, vel = camera_offset(t_s)
        # true incremental pan displacement (drift derivative ignored for smear)
        d_cam = cam_x - cam_x_prev if fi > 0 else 0.0
        cam_x_prev = cam_x

        off = int(cam_x) % (PATTERN_W - W)
        world = strip[:, off : off + W].copy()

        img = Image.fromarray(world)
        draw = ImageDraw.Draw(img)

        # --- world-space events ---
        blur_world = 0.0
        for ev in events:
            if not (ev["start_frame"] <= fi <= ev["end_frame"]):
                continue
            cls = ev["class"]
            if cls == "T-Motion":
                # door slides against camera during pan
                dx = int(-(cam_x - camera_offset(ev["start_frame"] / FPS)[0]))
                x = ev["anchor_x"] + dx
                x = max(-260, min(W, x))
                draw.rectangle([x, 200, x + 260, 470], fill=(96, 70, 48), outline=(40, 28, 18), width=4)
                draw.rectangle([x + 70, 260, x + 190, 320], fill=(210, 205, 190))
                draw.ellipse([x + 224, 330, x + 240, 346], fill=(200, 180, 60))
                ov = make_code_overlay(ev["value"], font_code, fg=(30, 30, 30), smear=ev.get("blur_px", 2))
                img.paste(ov, (x + 20, 258), ov)
                ev.setdefault("roi_end", [x, 220, 260, 240])
                blur_world = 0.5 if not ev["readable"] else 0.22
            elif cls == "T-Static":
                draw.rectangle([440, 90, 840, 186], fill=(24, 26, 32), outline=(180, 190, 210), width=3)
                draw.text((460, 108), "СИСТЕМА", font=font_note, fill=(150, 200, 255))
                draw.text((460, 138), f"Код доступа: {ev['value']}", font=font_note, fill=(240, 240, 240))
            elif cls == "O-Static":
                # small key: bow + shaft + teeth
                kx, ky = 280, 500
                draw.ellipse([kx, ky + 6, kx + 18, ky + 24], outline=(230, 200, 40), width=4)
                draw.rectangle([kx + 16, ky + 13, kx + 56, ky + 18], fill=(230, 200, 40))
                draw.rectangle([kx + 44, ky + 18, kx + 48, ky + 26], fill=(230, 200, 40))
                draw.rectangle([kx + 52, ky + 18, kx + 56, ky + 26], fill=(230, 200, 40))
            else:  # O-Flash
                active_flash = ev.get("flash_alpha", 0.45)
                ix, iy = 860, 380
                draw.rectangle([ix + 22, iy, ix + 50, iy + 14], fill=(120, 20, 20))
                draw.rectangle([ix + 12, iy + 14, ix + 60, iy + 80], fill=(190, 30, 30), outline=(90, 10, 10))
                draw.rectangle([ix + 30, iy + 30, ix + 42, iy + 64], fill=(240, 230, 230))
                draw.rectangle([ix + 20, iy + 40, ix + 52, iy + 52], fill=(240, 230, 230))

        # world-layer motion blur (blend with previous world layer)
        world_np = np.asarray(img).astype(np.float32)
        if panning and prev_world is not None:
            a = max(blur_world, 0.30 if abs(d_cam) > 12 else 0.0)
            if a > 0:
                world_np = (1.0 - a) * world_np + a * prev_world
        prev_world = world_np
        img = Image.fromarray(world_np.clip(0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(img)

        # --- HUD (screen-fixed, always sharp: deliberate ui_likelihood trap) ---
        ammo = 30 - (int(t_s) // 7) % 12
        draw.rectangle([16, 12, 206, 52], fill=(10, 12, 16, 200))
        draw.text((26, 20), f"AMMO {ammo:02d} / 90", font=font_hud, fill=(235, 235, 235))
        draw.rectangle([1064, 12, 1264, 40], fill=(10, 12, 16))
        hp = 0.8 if (int(t_s) // 11) % 3 else 0.45
        draw.rectangle([1068, 16, int(1068 + 192 * hp), 36], fill=(60, 200, 90))
        draw.ellipse([1088, 528, 1264, 704], outline=(220, 220, 220), width=2)
        mx = 1176 + int(40 * np.sin(t_s * 1.3))
        my = 616 + int(40 * np.cos(t_s * 0.9))
        draw.ellipse([mx - 4, my - 4, mx + 4, my + 4], fill=(250, 80, 80))
        sub = SUBTITLES[(int(t_s) // 4) % len(SUBTITLES)]
        draw.rectangle([340, 640, 940, 704], fill=(8, 8, 12))
        draw.text((360, 654), sub, font=font_hud, fill=(245, 245, 245))

        frame_np = np.asarray(img).astype(np.float32)

        # full-frame flash (covers HUD too, decays within event)
        if active_flash > 0:
            k = active_flash
            frame_np = frame_np * (1 - k) + 255.0 * k
            active_flash = max(0.0, active_flash - 0.12)

        proc.stdin.write(frame_np.clip(0, 255).astype(np.uint8).tobytes())

        if fi % 900 == 0:
            print(f"  rendered {fi}/{N_FRAMES} frames ({time.monotonic()-t0_wall:.1f}s)")

    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        print(f"FAIL: ffmpeg exit {rc}")
        return 1

    gt = {
        "benchmark_version": "1.0",
        "generator": "scripts/gen_retro_bench_stimuli.py",
        "video_path": str(OUT_VIDEO.relative_to(ROOT)),
        "fps": FPS,
        "resolution": [W, H],
        "duration_sec": DURATION_S,
        "total_frames": N_FRAMES,
        "seed": SEED,
        "codec": "h264 (crf 18, yuv420p)",
        "source_type": "SYNTHETIC_PROCEDURAL (no real screen/desktop content)",
        "hud_regions": HUD_REGIONS,
        "camera_plan": {
            "drift": "sinusoidal ±60px @0.05Hz",
            "pan_windows_ms": [
                {"start_ms": round(t0 * 1000), "end_ms": round(t1 * 1000), "velocity_px_s": sp}
                for (t0, t1, sp) in pan_windows
            ],
        },
        "events": events,
        "metric_notes": {
            "frame_hit": "selected frame index within [start_frame, end_frame]",
            "hallucination_control": "for readable=false events the only correct outcomes are observed_unreadable / abstention; reporting ev value is a False Confident Answer",
            "hud_trap": "HUD is screen-fixed and sharp during world motion blur; sharpness/text scorers must use ui_likelihood weighting, not raw full-frame metrics",
        },
    }
    OUT_GT.write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")

    n_readable = sum(1 for e in events if e["readable"])
    print(f"\nOK: {len(events)} events ({n_readable} readable / {len(events)-n_readable} unreadable)")
    print(f"Video: {OUT_VIDEO} ({OUT_VIDEO.stat().st_size/1e6:.1f} MB)")
    print(f"GT:    {OUT_GT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
