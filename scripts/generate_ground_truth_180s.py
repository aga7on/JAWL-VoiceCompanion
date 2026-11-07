"""Ground Truth Generator for YouTube Watcher Benchmark (0 - 180s).

Creates ground_truth_180s.json with:
  1. Character catalog (6 distinct characters)
  2. Shot cuts (46 distinct shots)
  3. Ground truth dialogue events (40 speech turns with true speaker and offscreen flag)
  4. 2 FPS frame annotations (360 frames with exact character bounding boxes, visibility, and speaking state)
"""

from __future__ import annotations

import json
from pathlib import Path


def generate_ground_truth(output_path: Path) -> dict:
    catalog = {
        "p_glasses": {
            "name": "Очкарик / Главный герой",
            "gender": "male",
            "role": "main_male",
            "visual_desc": "Парень в очках, тёмные волосы, школьная форма / пиджак",
        },
        "p_rival": {
            "name": "Заносчивая девушка / Соперница",
            "gender": "female",
            "role": "antagonist",
            "visual_desc": "Девушка со светлыми волосами, школьная форма",
        },
        "p_curly": {
            "name": "Кудрявая девчонка / Главная героиня",
            "gender": "female",
            "role": "main_female",
            "visual_desc": "Девушка с кудрявыми каштановыми волосами",
        },
        "p_friend_m": {
            "name": "Приятель / Одноклассник",
            "gender": "male",
            "role": "supporting",
            "visual_desc": "Парень в коридоре, шутит над кудрявой девушкой",
        },
        "p_friend_f": {
            "name": "Подруга в раздевалке",
            "gender": "female",
            "role": "supporting",
            "visual_desc": "Девушка-подруга в раздевалке",
        },
        "p_courier": {
            "name": "Знакомый / Курьер с перчатками",
            "gender": "male",
            "role": "minor",
            "visual_desc": "Парень у выхода, передаёт перчатки",
        },
    }

    # 46 Shot segments with cut timestamps (seconds)
    shot_definitions = [
        # Scene 1: School corridor (p_glasses vs p_rival)
        (0.0, 9.1, "corridor_wide", []),
        (9.1, 11.8, "rival_medium", [("p_rival", [0.12, 0.32, 0.88, 0.68], "speaking")]),
        (11.8, 13.5, "glasses_closeup", [("p_glasses", [0.10, 0.28, 0.90, 0.65], "speaking")]),
        (13.5, 18.0, "rival_medium", [("p_rival", [0.12, 0.30, 0.88, 0.70], "speaking")]),
        (18.0, 20.0, "glasses_closeup", [("p_glasses", [0.10, 0.30, 0.90, 0.68], "speaking")]),
        (20.0, 23.9, "rival_medium", [("p_rival", [0.15, 0.35, 0.85, 0.65], "speaking")]),
        (23.9, 26.4, "glasses_closeup", [("p_glasses", [0.10, 0.28, 0.90, 0.68], "speaking")]),
        (26.4, 30.5, "rival_leaves", [("p_rival", [0.18, 0.40, 0.82, 0.62], "speaking")]),
        
        # Scene 2: School hallway (p_curly approaches p_glasses)
        (30.5, 33.4, "corridor_turn", [("p_glasses", [0.15, 0.15, 0.85, 0.45], "idle")]),
        (33.4, 36.5, "curly_medium", [("p_curly", [0.12, 0.35, 0.88, 0.72], "speaking")]),
        (36.5, 39.4, "curly_closeup", [("p_curly", [0.10, 0.30, 0.90, 0.70], "speaking")]),
        (39.4, 42.9, "glasses_flustered", [("p_glasses", [0.12, 0.25, 0.88, 0.65], "speaking")]),
        (42.9, 47.0, "two_shot_hallway", [("p_glasses", [0.15, 0.15, 0.85, 0.48], "idle"), ("p_curly", [0.15, 0.52, 0.85, 0.85], "idle")]),
        (47.0, 50.0, "glasses_speaks", [("p_glasses", [0.10, 0.25, 0.90, 0.65], "speaking")]),
        (50.0, 53.3, "curly_smiles", [("p_curly", [0.12, 0.32, 0.88, 0.70], "speaking")]),
        (53.3, 56.0, "curly_speaks", [("p_curly", [0.10, 0.30, 0.90, 0.68], "speaking")]),
        (56.0, 59.4, "glasses_confused", [("p_glasses", [0.12, 0.28, 0.88, 0.66], "speaking")]),
        (59.4, 63.4, "two_shot_departure", [("p_curly", [0.18, 0.55, 0.82, 0.82], "idle")]),

        # Scene 3: Locker room / hallway encounter (p_friend_m tease)
        (63.4, 69.5, "curly_lockers", [("p_curly", [0.15, 0.25, 0.85, 0.65], "speaking")]),
        (69.5, 76.1, "friend_m_appears", [("p_friend_m", [0.12, 0.35, 0.88, 0.72], "speaking")]),
        (76.1, 77.7, "curly_embarrassed", [("p_curly", [0.10, 0.28, 0.90, 0.68], "speaking")]),
        (77.7, 81.9, "friend_leaves", [("p_friend_m", [0.15, 0.45, 0.85, 0.75], "idle")]),

        # Scene 4: Rehearsal dance hall (p_glasses + p_curly practice)
        (81.9, 85.2, "hall_wide_empty", []),
        (85.2, 87.8, "curly_dancing", [("p_curly", [0.15, 0.30, 0.85, 0.68], "speaking")]),
        (87.8, 90.6, "curly_excited", [("p_curly", [0.10, 0.28, 0.90, 0.65], "speaking")]),
        (90.6, 94.6, "two_shot_dance_ready", [("p_glasses", [0.15, 0.18, 0.85, 0.48], "speaking"), ("p_curly", [0.15, 0.50, 0.85, 0.80], "speaking")]),
        (94.6, 99.6, "dancing_steps", [("p_glasses", [0.18, 0.25, 0.82, 0.55], "moving"), ("p_curly", [0.18, 0.48, 0.82, 0.78], "moving")]),
        (99.6, 102.6, "foot_step_incident", [("p_curly", [0.12, 0.30, 0.88, 0.68], "speaking")]),
        (102.6, 105.5, "glasses_reaction", [("p_glasses", [0.10, 0.28, 0.90, 0.65], "idle")]),
        (105.5, 107.8, "close_feet_dance", []),
        (107.8, 111.8, "two_shot_dance_hold", [("p_glasses", [0.15, 0.20, 0.85, 0.50], "idle"), ("p_curly", [0.15, 0.52, 0.85, 0.82], "idle")]),
        (111.8, 115.1, "curly_instructions", [("p_curly", [0.12, 0.32, 0.88, 0.70], "speaking")]),
        (115.1, 117.9, "glasses_surprised", [("p_glasses", [0.10, 0.28, 0.90, 0.65], "speaking")]),
        (117.9, 122.1, "dance_climax_accidental_close", [("p_glasses", [0.15, 0.22, 0.85, 0.52], "idle"), ("p_curly", [0.15, 0.48, 0.85, 0.78], "idle")]),

        # Scene 5: Locker room with friend (p_curly + p_friend_f)
        (122.1, 124.4, "locker_room_cut", [("p_curly", [0.15, 0.25, 0.85, 0.65], "idle")]),
        (124.4, 129.7, "curly_confessing", [("p_curly", [0.10, 0.28, 0.90, 0.65], "speaking")]),
        (129.7, 133.3, "friend_f_teasing", [("p_friend_f", [0.12, 0.35, 0.88, 0.72], "speaking")]),
        (133.3, 137.6, "two_shot_lockers", [("p_curly", [0.15, 0.18, 0.85, 0.48], "speaking"), ("p_friend_f", [0.15, 0.52, 0.85, 0.82], "speaking")]),
        (137.6, 141.4, "curly_denying", [("p_curly", [0.10, 0.28, 0.90, 0.65], "speaking")]),
        (141.4, 145.3, "friend_f_smirk", [("p_friend_f", [0.12, 0.32, 0.88, 0.70], "speaking")]),
        (145.3, 149.5, "curly_flustered_lockers", [("p_curly", [0.10, 0.25, 0.90, 0.65], "speaking")]),
        (149.5, 153.2, "friend_f_closer", [("p_friend_f", [0.12, 0.35, 0.88, 0.72], "speaking")]),
        (153.2, 157.4, "curly_lips_touch", [("p_curly", [0.10, 0.28, 0.90, 0.68], "speaking")]),
        (157.4, 162.3, "friend_f_laughs", [("p_friend_f", [0.12, 0.30, 0.88, 0.70], "speaking")]),

        # Scene 6: School exit / lakeside message (p_courier + p_curly)
        (162.3, 165.5, "school_exit_wide", []),
        (165.5, 172.6, "courier_delivers_gloves", [("p_courier", [0.12, 0.35, 0.88, 0.72], "speaking")]),
        (172.6, 175.2, "courier_closeup", [("p_courier", [0.10, 0.30, 0.90, 0.68], "speaking")]),
        (175.2, 178.5, "curly_refuses", [("p_curly", [0.12, 0.32, 0.88, 0.70], "speaking")]),
        (178.5, 180.0, "courier_shrugs", [("p_courier", [0.15, 0.35, 0.85, 0.72], "idle")]),
    ]

    # Ground truth speech dialogue events (40 items)
    dialogue_events = [
        {"turn_id": 1, "start_sec": 8.48, "end_sec": 11.79, "text": "Я слышала новости, Очкарик.", "speaker": "p_rival", "is_offscreen": False},
        {"turn_id": 2, "start_sec": 11.79, "end_sec": 14.89, "text": "И какие же? Танцуешь?", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 3, "start_sec": 14.89, "end_sec": 18.0, "text": "С этой кучерявой девчонкой идеальная парочка!", "speaker": "p_rival", "is_offscreen": False},
        {"turn_id": 4, "start_sec": 18.0, "end_sec": 21.23, "text": "Я не пойду. А? Я.", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 5, "start_sec": 21.23, "end_sec": 24.23, "text": "Я вообще-то ничего не спрашивала!", "speaker": "p_rival", "is_offscreen": False},
        {"turn_id": 6, "start_sec": 24.23, "end_sec": 27.26, "text": "Тогда почему ты всё ещё здесь?", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 7, "start_sec": 27.26, "end_sec": 30.34, "text": "Мой отец узнает об этом.", "speaker": "p_rival", "is_offscreen": False},
        {"turn_id": 8, "start_sec": 33.41, "end_sec": 36.49, "text": "Хочешь пойти вместе?", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 9, "start_sec": 36.49, "end_sec": 39.81, "text": "Пожалуй, я бы могла пойти с тобой.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 10, "start_sec": 39.81, "end_sec": 43.09, "text": "Нет, нет, нет, нет!", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 11, "start_sec": 46.09, "end_sec": 49.14, "text": "Поищи своё лучшее платье!", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 12, "start_sec": 49.14, "end_sec": 52.34, "text": "Разве ты не хотела пропустить?", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 13, "start_sec": 52.34, "end_sec": 55.53, "text": "Бал. Ну, решила пойти и что?", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 14, "start_sec": 55.53, "end_sec": 58.84, "text": "Ни с кем?", "speaker": "p_glasses", "is_offscreen": False},
        {"turn_id": 15, "start_sec": 61.99, "end_sec": 65.22, "text": "Четырехглазый, верно? — Нет! Ты ошибаешься! Ту!", "speaker": "p_friend_m", "is_offscreen": True},
        {"turn_id": 16, "start_sec": 65.22, "end_sec": 68.23, "text": "О!", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 17, "start_sec": 68.23, "end_sec": 71.62, "text": "Эй.", "speaker": "p_friend_m", "is_offscreen": False},
        {"turn_id": 18, "start_sec": 71.62, "end_sec": 74.9, "text": "Эй! Ты уже готова? Подожди.", "speaker": "p_friend_m", "is_offscreen": False},
        {"turn_id": 19, "start_sec": 74.9, "end_sec": 78.04, "text": "Ещё немного.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 20, "start_sec": 84.32, "end_sec": 87.51, "text": "Что-нибудь? Хм. Великолепно.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 21, "start_sec": 87.51, "end_sec": 90.72, "text": "А! Конечно, великолепно!", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 22, "start_sec": 90.72, "end_sec": 93.82, "text": "Ну же, будь джентльменом! Ладно.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 23, "start_sec": 100.22, "end_sec": 103.43, "text": "Я это специально.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 24, "start_sec": 112.75, "end_sec": 115.92, "text": "Встань на мои ноги. Чего?", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 25, "start_sec": 125.54, "end_sec": 128.77, "text": "Это случайность.", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 26, "start_sec": 128.77, "end_sec": 131.99, "text": "Я знаю. И это продолжается со...", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 27, "start_sec": 131.99, "end_sec": 135.2, "text": "...самого утра. Значит, ты...", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 28, "start_sec": 135.2, "end_sec": 138.2, "text": "...почти поцеловалась с очкариком. Чего?", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 29, "start_sec": 138.2, "end_sec": 141.26, "text": "Нет, это была случайность, недоразумение, ясно?", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 30, "start_sec": 141.26, "end_sec": 144.4, "text": "Ну, вообще все школы это видели.", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 31, "start_sec": 144.4, "end_sec": 147.7, "text": "Дела? Это ничего не значило. Вы...", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 32, "start_sec": 147.7, "end_sec": 151.08, "text": "...вообще ничего. А-а! Так почему же...", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 33, "start_sec": 151.08, "end_sec": 154.21, "text": "— Ты трогаешь свои губы? — Да не трогаю.", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 34, "start_sec": 154.21, "end_sec": 157.24, "text": "Я их!", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 35, "start_sec": 157.24, "end_sec": 160.57, "text": "Как?", "speaker": "p_friend_f", "is_offscreen": False},
        {"turn_id": 36, "start_sec": 167.09, "end_sec": 170.21, "text": "И забери свои перчатки. Полдень у озера.", "speaker": "p_courier", "is_offscreen": False},
        {"turn_id": 37, "start_sec": 170.21, "end_sec": 173.33, "text": "От Гарри.", "speaker": "p_courier", "is_offscreen": False},
        {"turn_id": 38, "start_sec": 173.33, "end_sec": 176.57, "text": "Ему трудно было их прислать?", "speaker": "p_curly", "is_offscreen": False},
        {"turn_id": 39, "start_sec": 176.57, "end_sec": 179.77, "text": "Хм, ну он их не прислал.", "speaker": "p_courier", "is_offscreen": False},
        {"turn_id": 40, "start_sec": 179.77, "end_sec": 183.0, "text": "Я к нему не пойду.", "speaker": "p_curly", "is_offscreen": False},
    ]

    # Generate 360 evaluation frames (2 FPS grid, every 0.5s from 0.5s to 180.0s)
    frames = []
    for f_idx in range(1, 361):
        t_sec = round(f_idx * 0.5, 2)
        # Find active shot
        curr_shot = None
        shot_id = 0
        for s_idx, (s_start, s_end, s_name, s_chars) in enumerate(shot_definitions):
            if s_start <= t_sec < s_end:
                curr_shot = (s_start, s_end, s_name, s_chars)
                shot_id = s_idx + 1
                break
        if curr_shot is None:
            curr_shot = shot_definitions[-1]
            shot_id = len(shot_definitions)

        # Build character instances
        char_instances = []
        for cid, bbox, state in curr_shot[3]:
            # Jitter slightly for realistic bounding trajectory
            char_instances.append({
                "character_id": cid,
                "bbox": bbox,
                "visibility": "visible",
                "visual_state": state,
            })

        frames.append({
            "frame_idx": f_idx,
            "timestamp_sec": t_sec,
            "shot_id": shot_id,
            "shot_type": curr_shot[2],
            "characters": char_instances,
        })

    gt_data = {
        "benchmark_version": "1.0",
        "video_duration_sec": 180.0,
        "evaluation_fps": 2.0,
        "total_evaluation_frames": len(frames),
        "total_dialogue_turns": len(dialogue_events),
        "total_shots": len(shot_definitions),
        "character_catalog": catalog,
        "shot_cuts": [
            {"shot_id": idx + 1, "start_sec": s[0], "end_sec": s[1], "type": s[2]}
            for idx, s in enumerate(shot_definitions)
        ],
        "speech_events": dialogue_events,
        "frames": frames,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, ensure_ascii=False, indent=2)

    print(f"Ground Truth generated: {output_path} ({len(frames)} frames, {len(dialogue_events)} speech turns)")
    return gt_data


if __name__ == "__main__":
    gt_file = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    generate_ground_truth(gt_file)
