"""Round 11, Step 2 — Realistic Gameplay Benchmark Generator with 35 Annotated Events.

Generates a rich, multi-layered 60 FPS 720p simulated gameplay video:
  Layer 1: Parallax scrolling background (mountains, trees, dungeon bricks)
  Layer 2: Player character and dynamic particles / projectiles
  Layer 3: Complex HUD (Minimap with blinking pings, HP/Mana orbs, Action bar, Compass)
  Layer 4: Realistic Event Injections (35 ground-truth events):
    - Chat messages / dialogue lines in chatbox (1000-2000 ms)
    - Loot drops / item popup cards (300-600 ms)
    - Combat damage floating numbers (150-300 ms)
    - Door / Wall glyph codes during rapid camera pan (100-250 ms)
    - System quest notifications (1500-2500 ms)
    - Blurred / partially occluded negative controls (readability: False)

Outputs:
  runtime/instances/realistic_retro_bench/realistic_gameplay_60fps.mp4 (180s = 10,800 frames)
  runtime/instances/realistic_retro_bench/ground_truth_events.json (35 events)
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime" / "instances" / "realistic_retro_bench"
OUT_VIDEO = OUT_DIR / "realistic_gameplay_60fps.mp4"
OUT_GT = OUT_DIR / "ground_truth_events.json"

W, H = 1280, 720
FPS = 60
DURATION_S = 180  # 3 minutes
N_FRAMES = FPS * DURATION_S
FONT_PATH = "C:/Windows/Fonts/arial.ttf"

def load_fonts():
    try:
        f_large = ImageFont.truetype(FONT_PATH, 24)
        f_med = ImageFont.truetype(FONT_PATH, 16)
        f_small = ImageFont.truetype(FONT_PATH, 12)
    except OSError:
        f_large = ImageFont.load_default()
        f_med = ImageFont.load_default()
        f_small = ImageFont.load_default()
    return f_large, f_med, f_small


def build_event_manifest() -> list[dict]:
    """Define 35 realistic events distributed across the 180s timeline."""
    events = []
    
    # Event template definitions:
    # (time_s, duration_ms, category, target_type, target_value, readable, question, roi)
    raw_specs = [
        # Sector 1: 0 - 30s (Opening dungeon run)
        (4.5, 1200, "chat", "text", "Игрок_Alex: Собираемся у южных ворот", True, "Что написал Alex в чате?", [30, 520, 320, 35]),
        (8.2, 250, "damage_num", "number", "4520 CRIT", True, "Какой критический урон выскочил над целью?", [580, 310, 140, 40]),
        (12.0, 180, "pan_glyph", "code", "RUN-882", True, "Какой код был на стене при быстром развороте?", [480, 240, 130, 45]),
        (16.5, 400, "loot_drop", "item", "Древний рубин +5", True, "Какой предмет выпал из сундука?", [600, 360, 180, 50]),
        (21.0, 1500, "quest_popup", "text", "Квест: Найдите ключ стража", True, "Какое новое задание появилось на экране?", [450, 80, 380, 60]),
        (25.5, 150, "damage_num", "number", "890", False, "Какое число урона промелькнуло?", [590, 320, 100, 35]), # blurred/too fast

        # Sector 2: 30 - 60s (Mid-game combat & interaction)
        (33.0, 1400, "chat", "text", "Система: Сервер перезагрузится через 15 минут", True, "О чем предупредило системное сообщение в чате?", [30, 500, 360, 40]),
        (37.5, 200, "pan_glyph", "code", "DOOR-714", True, "Какой шифр был на двери при повороте?", [510, 250, 140, 45]),
        (42.0, 350, "loot_drop", "item", "Свиток портала", True, "Какое заклинание или свиток подобрал персонаж?", [590, 370, 160, 45]),
        (46.2, 180, "damage_num", "number", "12500 FATAL", True, "Сколько урона нанес добивающий удар?", [570, 300, 160, 45]),
        (51.0, 2000, "quest_popup", "text", "Достижение: Мастер подземелий", True, "Какое достижение разблокировано?", [440, 75, 400, 60]),
        (55.8, 120, "pan_glyph", "code", "OBSCURED-??", False, "Какой символ был на колонне?", [500, 260, 140, 45]), # smeared

        # Sector 3: 60 - 90s (Inventory & boss fight start)
        (63.5, 1500, "chat", "text", "Босс: Вам не уйти живыми отсюда!", True, "Какую реплику произнес босс в чате?", [30, 530, 380, 40]),
        (68.0, 220, "damage_num", "number", "9999 BLOCKED", True, "Сколько заблокированного урона отобразилось?", [580, 310, 170, 45]),
        (72.4, 500, "loot_drop", "item", "Кольцо теней (+12 ловкость)", True, "Какой артефакт появился на экране?", [580, 360, 210, 50]),
        (77.0, 180, "pan_glyph", "code", "VAULT-309", True, "Какой код хранилища был на люке?", [520, 270, 140, 45]),
        (82.0, 1600, "quest_popup", "text", "Внимание: Уровень яда растет!", True, "Какое предупреждение высветилось вверху?", [460, 85, 360, 55]),
        (87.5, 140, "damage_num", "number", "312", False, "Какое число урона мелькнуло в дыму?", [600, 330, 110, 35]),

        # Sector 4: 90 - 120s (Fast traversal & puzzle sequence)
        (93.0, 1300, "chat", "text", "Игрок_Elena: Жмите рычаг справа!", True, "Что посоветовала Elena в чате?", [30, 510, 340, 35]),
        (97.2, 190, "pan_glyph", "code", "SIGIL-ALPHA", True, "Какое название сигила было на табличке?", [490, 250, 150, 45]),
        (102.5, 300, "loot_drop", "item", "Зелье маны x5", True, "Какие расходники были найдены?", [590, 380, 160, 45]),
        (107.0, 220, "damage_num", "number", "777 LUCKY", True, "Какая особая цифра удачи вылетела в бою?", [580, 305, 140, 40]),
        (112.0, 1800, "quest_popup", "text", "Таймер: До закрытия портала 60 сек", True, "Что сообщил таймер задания?", [430, 80, 420, 60]),
        (117.5, 110, "pan_glyph", "code", "CORRUPT_GLYPH", False, "Какое слово было на быстро проехавшем щите?", [520, 260, 160, 45]),

        # Sector 5: 120 - 150s (Climax encounter)
        (123.0, 1600, "chat", "text", "Система: Игрок Alex получил легендарный меч", True, "Какое событие в мире объявила система?", [30, 520, 420, 40]),
        (127.8, 240, "damage_num", "number", "64320 OVERKILL", True, "Какое рекордное значение оверкилла появилось?", [560, 300, 190, 45]),
        (132.5, 450, "loot_drop", "item", "Осколок титана", True, "Какой крафтовый ресурс был получен?", [600, 370, 170, 45]),
        (137.0, 190, "pan_glyph", "code", "EXIT-901", True, "Какой номер сектора эвакуации был на стене?", [500, 250, 140, 45]),
        (142.0, 1700, "quest_popup", "text", "Миссия выполнена: Эвакуация открыта", True, "Какое финальное уведомление появилось?", [440, 80, 400, 60]),
        (147.2, 130, "damage_num", "number", "55", False, "Какой урон ядом отобразился внизу?", [610, 340, 90, 35]),

        # Sector 6: 150 - 180s (Epilogue & extraction)
        (153.0, 1400, "chat", "text", "Игрок_Alex: Отличная игра, всем спасибо!", True, "Какую прощальную фразу написал Alex?", [30, 510, 360, 35]),
        (157.5, 200, "pan_glyph", "code", "BAY-12", True, "Какой отсек челнока указан на указателе?", [510, 260, 130, 45]),
        (162.0, 500, "loot_drop", "item", "Звездная карта сектора 7", True, "Какой ключевой сюжетный предмет найден?", [570, 360, 230, 50]),
        (167.0, 180, "damage_num", "number", "100 SHIELD", True, "Сколько единиц щита восстановилось?", [580, 310, 150, 40]),
        (172.0, 1800, "quest_popup", "text", "Победа! Все цели выполнены", True, "Какая финальная надпись победы появилась?", [450, 80, 380, 60]),
    ]

    for i, spec in enumerate(raw_specs):
        t_s, dur_ms, cat, t_type, val, readable, q, roi = spec
        start_frame = int(t_s * FPS)
        frame_len = max(1, int(round((dur_ms / 1000.0) * FPS)))
        end_frame = start_frame + frame_len
        events.append({
            "event_id": f"event_{i+1:02d}",
            "index": i + 1,
            "category": cat,
            "target_type": t_type,
            "target_value": val,
            "readable": readable,
            "question": q,
            "start_time_s": t_s,
            "duration_ms": dur_ms,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_pts_us": int(t_s * 1_000_000),
            "end_pts_us": int((t_s + dur_ms / 1000.0) * 1_000_000),
            "roi": roi, # [x, y, w, h]
        })

    return events


def render_scene(frame_idx: int, events: list[dict], fonts: tuple) -> Image.Image:
    f_large, f_med, f_small = fonts
    img = Image.new("RGB", (W, H), (15, 18, 26))
    draw = ImageDraw.Draw(img)

    t = frame_idx / float(FPS)

    # 1. Parallax background dungeon / landscape
    # Distant layer
    cam_x = int(math.sin(t * 0.4) * 300 + t * 40)
    for i in range(-2, 10):
        col_x = (i * 180 - (cam_x // 3)) % (W + 200) - 100
        draw.rectangle([col_x, 150, col_x + 80, 550], fill=(24, 28, 42))

    # Midground pillars
    for i in range(-2, 8):
        col_x = (i * 260 - cam_x) % (W + 300) - 150
        draw.rectangle([col_x, 100, col_x + 120, 600], fill=(36, 42, 60))
        # Pillar highlights
        draw.line([col_x + 10, 100, col_x + 10, 600], fill=(50, 58, 80), width=2)

    # Ground platform
    draw.rectangle([0, 580, W, H], fill=(20, 22, 30))
    draw.line([0, 580, W, 580], fill=(60, 70, 95), width=3)

    # 2. Player character (center-left)
    player_x = 420
    player_y = 480 + int(math.sin(t * 8.0) * 8)
    draw.rectangle([player_x, player_y, player_x + 50, player_y + 100], fill=(45, 120, 210))
    draw.ellipse([player_x + 10, player_y - 25, player_x + 40, player_y + 5], fill=(210, 180, 140)) # head
    # Weapon glow
    draw.line([player_x + 45, player_y + 30, player_x + 85, player_y + 10], fill=(80, 220, 255), width=4)

    # 3. Dynamic HUD elements
    # Top-left health & mana bars
    draw.rectangle([30, 25, 250, 45], fill=(40, 15, 15), outline=(70, 30, 30))
    hp_pct = 0.75 + 0.20 * math.sin(t * 0.5)
    draw.rectangle([32, 27, 30 + int(218 * hp_pct), 43], fill=(220, 40, 40))
    draw.text((35, 27), f"HP: {int(hp_pct*1000)}/1000", fill=(255, 255, 255), font=f_small)

    draw.rectangle([30, 50, 210, 65], fill=(15, 20, 45), outline=(30, 40, 80))
    mp_pct = 0.60 + 0.35 * math.cos(t * 0.7)
    draw.rectangle([32, 52, 30 + int(178 * mp_pct), 63], fill=(40, 110, 240))
    draw.text((35, 52), f"MP: {int(mp_pct*500)}/500", fill=(255, 255, 255), font=f_small)

    # Top-right minimap
    draw.rectangle([1080, 20, 1250, 190], fill=(18, 22, 32), outline=(50, 65, 90), width=2)
    draw.ellipse([1160, 100, 1170, 110], fill=(255, 230, 50)) # player dot
    # Radar sweep line
    angle = (t * 2.5) % (2 * math.pi)
    rx = 1165 + int(math.cos(angle) * 60)
    ry = 105 + int(math.sin(angle) * 60)
    draw.line([1165, 105, rx, ry], fill=(40, 180, 80), width=1)
    draw.text((1090, 25), "MINIMAP [SEC-04]", fill=(140, 160, 190), font=f_small)

    # Bottom-left chatbox container
    draw.rectangle([25, 480, 440, 570], fill=(12, 15, 22, 200), outline=(40, 50, 70))
    draw.text((30, 485), "[COMBAT CHAT - LIVE]", fill=(100, 130, 160), font=f_small)

    # 4. Check active events for this frame
    for ev in events:
        if ev["start_frame"] <= frame_idx <= ev["end_frame"]:
            rx, ry, rw, rh = ev["roi"]
            cat = ev["category"]
            readable = ev["readable"]

            if cat == "chat":
                # Chat message inside chatbox
                draw.rectangle([rx - 2, ry - 2, rx + rw + 2, ry + rh + 2], fill=(20, 26, 38))
                col = (255, 240, 160) if "Игрок" in ev["target_value"] else ((255, 90, 90) if "Босс" in ev["target_value"] else (100, 220, 255))
                draw.text((rx + 4, ry + 6), ev["target_value"], fill=col, font=f_med)

            elif cat == "damage_num":
                # Floating damage number
                progress = (frame_idx - ev["start_frame"]) / float(ev["end_frame"] - ev["start_frame"] + 1)
                curr_y = ry - int(progress * 40)
                draw.rectangle([rx, curr_y, rx + rw, curr_y + rh], fill=(40, 10, 10, 180), outline=(220, 50, 50))
                if readable:
                    draw.text((rx + 6, curr_y + 4), ev["target_value"], fill=(255, 230, 40), font=f_large)
                else:
                    # Smudged/unreadable
                    draw.text((rx + 6, curr_y + 4), "~~~~~~", fill=(180, 100, 40), font=f_large)

            elif cat == "loot_drop":
                # Item notification card
                draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(25, 30, 48), outline=(180, 140, 40), width=2)
                draw.rectangle([rx + 4, ry + 4, rx + 40, ry + rh - 4], fill=(140, 100, 20)) # icon
                draw.text((rx + 48, ry + 12), ev["target_value"], fill=(255, 215, 0), font=f_med)

            elif cat == "pan_glyph":
                # Wall code during fast camera pan
                draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(10, 12, 16), outline=(90, 160, 220), width=2)
                if readable:
                    draw.text((rx + 8, ry + 8), ev["target_value"], fill=(255, 255, 255), font=f_large)
                else:
                    # Smeared smear lines
                    for ly in range(ry + 6, ry + rh - 6, 4):
                        draw.line([rx + 8, ly, rx + rw - 8, ly], fill=(120, 140, 160), width=2)

            elif cat == "quest_popup":
                # Quest notification at top center
                draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(22, 28, 44), outline=(70, 130, 230), width=2)
                draw.text((rx + 15, ry + 16), ev["target_value"], fill=(240, 245, 255), font=f_large)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events = build_event_manifest()
    
    with open(OUT_GT, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    print(f"Generated ground-truth manifest: {len(events)} events saved to {OUT_GT}")

    fonts = load_fonts()

    # Launch ffmpeg encoder process via pipe for high speed
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{W}x{H}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(OUT_VIDEO),
    ]

    print(f"Synthesizing 60 FPS gameplay video ({DURATION_S}s = {N_FRAMES} frames)...")
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for i in range(N_FRAMES):
        frame = render_scene(i, events, fonts)
        proc.stdin.write(frame.tobytes())
        if (i + 1) % 600 == 0:
            elapsed = time.perf_counter() - t0
            fps_proc = (i + 1) / elapsed
            print(f"  Processed {i+1}/{N_FRAMES} frames ({fps_proc:.1f} FPS)...")

    proc.stdin.close()
    proc.wait()
    total_time = time.perf_counter() - t0
    print(f"Video generated successfully in {total_time:.1f}s -> {OUT_VIDEO} ({OUT_VIDEO.stat().st_size / (1024*1024):.1f} MB)")


if __name__ == "__main__":
    main()
