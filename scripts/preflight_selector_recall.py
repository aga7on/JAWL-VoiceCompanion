"""Step 2 Recall Preflight: Compare Old Hybrid Adaptive vs Anchor-Satellite Weaving (Scalar).

Evaluates:
  - Strategy A: Old Hybrid Adaptive (coarse grid sweep + refinement burst, v1 baseline)
  - Strategy B: Anchor-Satellite Weaving (Scalar, roi_boost=False)
Across budgets K in {4, 8, 12, 16} on:
  1. 20 Synthetic Stimuli (stimuli_60fps.mp4)
  2. 35 Realistic Gameplay Events (realistic_gameplay_60fps.mp4)

Verifies:
  - Monotonic subset nesting: S_4 subset S_8 subset S_12 subset S_16 for every event.
  - Absence of duplicate frames in all selected sets.
  - Numerator / denominator for Hit@4, Hit@8, Hit@12, Hit@16.
  - Separate recall breakdown for short-duration text labels (100ms, 150ms).
"""

from __future__ import annotations

import gc
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from jawl_voicecompanion.retro_selector import (
    RetrospectiveFrameSelector,
    VideoWindowDecoder,
    rank_all_candidates_anchor_satellite,
)

BENCH_20_DIR = ROOT / "runtime" / "instances" / "retro_bench"
VIDEO_20 = BENCH_20_DIR / "stimuli_60fps.mp4"
GT_20 = BENCH_20_DIR / "retro_bench_ground_truth.json"

BENCH_35_DIR = ROOT / "runtime" / "instances" / "realistic_retro_bench"
VIDEO_35 = BENCH_35_DIR / "realistic_gameplay_60fps.mp4"
GT_35 = BENCH_35_DIR / "ground_truth_events.json"

OUT_PATH = BENCH_35_DIR / "preflight_selector_recall_results.json"


def evaluate_dataset(
    dataset_name: str,
    events: list[dict[str, Any]],
    video_path: Path,
    is_realistic: bool,
    budgets: list[int] = [4, 8, 12, 16],
) -> dict[str, Any]:
    selector = RetrospectiveFrameSelector()
    decoder = VideoWindowDecoder(video_path)
    n = len(events)

    print(f"\n{'='*70}", flush=True)
    print(f"Dataset: {dataset_name} ({n} events, {video_path.name})", flush=True)
    print(f"{'='*70}", flush=True)

    # Accumulators for both strategies
    # stats[strat][K] -> dict of counts
    strategies = ["old_hybrid_adaptive", "rank_all_candidates_anchor_satellite"]
    stats: dict[str, dict[int, dict[str, Any]]] = {}
    for st in strategies:
        stats[st] = {}
        for b in budgets:
            stats[st][b] = {
                "hits": 0,
                "short_text_hits": 0,
                "short_text_total": 0,
                "hits_by_dur": {},
                "duplicate_errors": 0,
            }

    # Per-event subset nesting checks
    nesting_counts = {
        st: {
            "s4_in_s8": 0,
            "s8_in_s12": 0,
            "s12_in_s16": 0,
            "full_nesting": 0,
        }
        for st in strategies
    }

    for ev_idx, ev in enumerate(events):
        dur = int(ev.get("duration_ms", 500))
        ev_start_f = ev["start_frame"]
        ev_end_f = ev["end_frame"]
        question = ev["question"]
        is_short_text = (dur <= 150)

        if is_realistic:
            ev_start_ms = ev["start_time_s"] * 1000.0
            win_start = max(0.0, ev_start_ms - 1500.0)
            win_end = min(180000.0, ev_start_ms + 2500.0)
        else:
            ev_start_ms = ev["start_ms"]
            win_start = max(0.0, ev_start_ms - 2000.0)
            win_end = min(120000.0, win_start + 6000.0)

        raw_frames = decoder.decode_window(win_start, win_end, stride=1)
        n_frames = len(raw_frames)

        # Precompute features for the window once
        q_lower = question.lower()
        is_text = any(k in q_lower for k in ("код", "текст", "надпис", "номер", "цифр", "букв", "двер"))
        is_flash = any(k in q_lower for k in ("вспышк", "выпал", "сверкн", "взрыв", "зелье"))
        is_ui = any(k in q_lower for k in ("уведомлен", "интерфейс", "чат", "сообщен", "система"))

        ui_mask = selector._estimate_ui_likelihood_map(raw_frames)

        frame_pts: list[float] = []
        scalar_scores: list[float] = []
        sharp_edge_scores: list[float] = []

        for fi, pts, arr in raw_frames:
            frame_pts.append(pts)
            sh, ed, cont, roi, roi_sal = selector._compute_frame_features(arr, ui_mask, is_ui)
            if is_text:
                sc = sh * 0.6 + ed * 0.3 + cont * 0.1
            elif is_flash:
                sc = cont * 0.5 + ed * 0.3 + sh * 0.2
            else:
                sc = sh * 0.4 + ed * 0.4 + cont * 0.2

            scalar_scores.append(sc)
            sharp_edge_scores.append(sh * (ed + 0.1))

        # 1. Rank using Anchor-Satellite Weaving (Scalar: roi_boost=False)
        ordered_indices_as = rank_all_candidates_anchor_satellite(
            frame_pts, scalar_scores, sharp_edge_scores, nms_anchor_ms=250.0, max_sat_dist_ms=100.0
        )

        # Evaluate both strategies across all K for this event
        event_selections: dict[str, dict[int, list[int]]] = {"old_hybrid_adaptive": {}, "rank_all_candidates_anchor_satellite": {}}

        for b in budgets:
            # Anchor-Satellite
            sel_as = sorted(ordered_indices_as[:b])
            event_selections["rank_all_candidates_anchor_satellite"][b] = [raw_frames[i][0] for i in sel_as]

            # Old Hybrid Adaptive
            k_coarse = max(2, b // 2)
            k_burst = b - k_coarse
            step = max(1, n_frames // k_coarse)
            c_indices = [min(n_frames - 1, i * step) for i in range(k_coarse)]
            best_c = c_indices[int(np.argmax([scalar_scores[ci] for ci in c_indices]))]
            b_half = max(1, k_burst // 2)
            b_indices = [
                i for i in range(max(0, best_c - b_half), min(n_frames, best_c + b_half + 1))
                if i not in c_indices
            ][:k_burst]
            sel_old = sorted(set(c_indices + b_indices))[:b]
            event_selections["old_hybrid_adaptive"][b] = [raw_frames[i][0] for i in sel_old]

        for st in strategies:
            s_dict = event_selections[st]
            s4 = set(s_dict[4])
            s8 = set(s_dict[8])
            s12 = set(s_dict[12])
            s16 = set(s_dict[16])

            # Check subset nesting
            in4_8 = s4.issubset(s8)
            in8_12 = s8.issubset(s12)
            in12_16 = s12.issubset(s16)

            if in4_8:
                nesting_counts[st]["s4_in_s8"] += 1
            if in8_12:
                nesting_counts[st]["s8_in_s12"] += 1
            if in12_16:
                nesting_counts[st]["s12_in_s16"] += 1
            if in4_8 and in8_12 and in12_16:
                nesting_counts[st]["full_nesting"] += 1

            for b in budgets:
                frames_k = s_dict[b]
                # Check duplicates
                if len(frames_k) != len(set(frames_k)):
                    stats[st][b]["duplicate_errors"] += 1

                hit = any(ev_start_f <= f_id <= ev_end_f for f_id in frames_k)
                if hit:
                    stats[st][b]["hits"] += 1
                if is_short_text:
                    stats[st][b]["short_text_total"] += 1
                    if hit:
                        stats[st][b]["short_text_hits"] += 1
                stats[st][b]["hits_by_dur"].setdefault(dur, []).append(hit)

        del raw_frames
        if (ev_idx + 1) % 10 == 0 or (ev_idx + 1) == n:
            gc.collect()

    # Summarize results
    dataset_summary: dict[str, Any] = {"total_events": n, "strategies": {}}
    for st in strategies:
        strat_info: dict[str, Any] = {
            "subset_nesting": {
                "S4_subset_S8": f"{nesting_counts[st]['s4_in_s8']}/{n}",
                "S8_subset_S12": f"{nesting_counts[st]['s8_in_s12']}/{n}",
                "S12_subset_S16": f"{nesting_counts[st]['s12_in_s16']}/{n}",
                "full_nesting_S4_S8_S12_S16": f"{nesting_counts[st]['full_nesting']}/{n}",
                "monotonic_property_holds": (nesting_counts[st]["full_nesting"] == n),
            },
            "budgets": {},
        }
        print(f"\n--- Strategy: {st} ---", flush=True)
        print(f"  Nesting S4 in S8:   {nesting_counts[st]['s4_in_s8']}/{n}", flush=True)
        print(f"  Nesting S8 in S12:  {nesting_counts[st]['s8_in_s12']}/{n}", flush=True)
        print(f"  Nesting S12 in S16: {nesting_counts[st]['s12_in_s16']}/{n}", flush=True)
        print(f"  Full Nesting:       {nesting_counts[st]['full_nesting']}/{n} (Monotonic: {nesting_counts[st]['full_nesting'] == n})", flush=True)

        for b in budgets:
            d = stats[st][b]
            hit_rate = d["hits"] / float(n)
            sh_tot = d["short_text_total"]
            sh_rate = (d["short_text_hits"] / float(sh_tot)) if sh_tot > 0 else 0.0

            b_info = {
                "hit_at_k": f"{d['hits']}/{n}",
                "hit_rate": round(hit_rate, 4),
                "short_text_hit": f"{d['short_text_hits']}/{sh_tot}",
                "short_text_recall": round(sh_rate, 4),
                "duplicate_errors": d["duplicate_errors"],
                "by_duration": {
                    str(k): f"{sum(v)}/{len(v)} ({sum(v)/len(v):.1%})"
                    for k, v in sorted(d["hits_by_dur"].items())
                },
            }
            strat_info["budgets"][str(b)] = b_info
            print(
                f"  K={b:2d}: Hit@{b} = {d['hits']:2d}/{n} ({hit_rate*100:5.1f}%) | "
                f"ShortText (<=150ms) = {d['short_text_hits']:2d}/{sh_tot} ({sh_rate*100:5.1f}%) | "
                f"Duplicates = {d['duplicate_errors']}",
                flush=True,
            )
        dataset_summary["strategies"][st] = strat_info

    return dataset_summary


def main() -> int:
    print("=" * 80, flush=True)
    print("Step 2 Recall Preflight: Old Hybrid Adaptive vs Anchor-Satellite Weaving", flush=True)
    print("=" * 80, flush=True)

    events_20 = json.loads(GT_20.read_text(encoding="utf-8"))["events"]
    events_35 = json.loads(GT_35.read_text(encoding="utf-8"))

    summary_35 = evaluate_dataset("Realistic Gameplay Events", events_35, VIDEO_35, is_realistic=True)
    summary_20 = evaluate_dataset("Synthetic Stimuli Events", events_20, VIDEO_20, is_realistic=False)

    out_data = {
        "preflight_round": "Round 11 Step 3 - Step 2 Preflight",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "realistic_gameplay_35": summary_35,
        "synthetic_stimuli_20": summary_20,
    }

    OUT_PATH.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[PASS] Preflight results saved to: {OUT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
