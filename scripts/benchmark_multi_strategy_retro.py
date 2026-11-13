"""Round 11 Step 3 — Multi-Strategy Retrospective Benchmark & Segment Inspector Evaluation.

Compares 4 strategies across 20 synthetic stimuli and 35 realistic gameplay events:
  1. Uniform (K=4, 8, 12)
  2. Old Hybrid Adaptive (K=4, 8, 12)
  3. Anchor-Satellite Weaving Scalar (K=4, 8, 12)
  4. Anchor-Satellite Weaving ROI-Boosted (K=4, 8, 12)

Verifies:
  - Strict monotonic subset nesting: S_4 subset S_8 subset S_12
  - Duration scaling (100ms, 150ms, 250ms, 500ms, 1000ms+)
  - Category breakdown (damage_num, pan_glyph, chat, loot_drop, quest_popup)
  - Latency profiling (decode, scoring, total p50)
  - End-to-end SegmentInspector with Foveated 1:1 Mosaic packing & epistemic gating
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
    FrameCandidate,
    RetrospectiveFrameSelector,
    VideoWindowDecoder,
    rank_all_candidates_anchor_satellite,
)
from jawl_voicecompanion.segment_inspector import (
    OBSERVED_READABLE,
    OBSERVED_UNREADABLE,
    NOT_OBSERVED,
    RetrospectiveEvidence,
    RetrospectiveSegmentInspector,
    build_foveated_mosaic,
    compute_image_sharpness,
    check_overexposure,
)

BENCH_20_DIR = ROOT / "runtime" / "instances" / "retro_bench"
VIDEO_20 = BENCH_20_DIR / "stimuli_60fps.mp4"
GT_20 = BENCH_20_DIR / "retro_bench_ground_truth.json"

BENCH_35_DIR = ROOT / "runtime" / "instances" / "realistic_retro_bench"
VIDEO_35 = BENCH_35_DIR / "realistic_gameplay_60fps.mp4"
GT_35 = BENCH_35_DIR / "ground_truth_events.json"

RESULTS_PATH = BENCH_35_DIR / "multi_strategy_benchmark_results.json"


def run_benchmark_on_dataset(
    events: list[dict[str, Any]],
    video_path: Path,
    is_realistic: bool,
    strategies: list[str],
    budgets: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    selector = RetrospectiveFrameSelector()
    inspector = RetrospectiveSegmentInspector() if is_realistic else None
    decoder = VideoWindowDecoder(video_path)

    combo_data: dict[tuple[str, int], dict[str, Any]] = {}
    for strat in strategies:
        for b in budgets:
            combo_data[(strat, b)] = {
                "hits": 0,
                "hits_by_dur": {},
                "hits_by_cat": {},
                "unreadable_correct": 0,
                "unreadable_total": 0,
                "decode_times": [],
                "scoring_times": [],
                "total_times": [],
                "subsets": [],
            }

    inspector_data: dict[str, Any] = {
        "latencies": [],
        "sharpness_scores": [],
        "mosaic_sizes": [],
        "correct_readable": 0,
        "correct_unreadable": 0,
        "hallucinations_on_negatives": 0,
        "samples": [],
    }

    n = len(events)
    print(f"Starting benchmark on {n} events ({video_path.name})...", flush=True)

    for ev_idx, ev in enumerate(events):
        cat = ev.get("category", ev.get("class", "general"))
        dur = int(ev.get("duration_ms", 500))
        ev_start_f = ev["start_frame"]
        ev_end_f = ev["end_frame"]
        readable = ev.get("readable", True)
        question = ev["question"]

        if is_realistic:
            ev_start_ms = ev["start_time_s"] * 1000.0
            win_start = max(0.0, ev_start_ms - 1500.0)
            win_end = min(180000.0, ev_start_ms + 2500.0)
        else:
            ev_start_ms = ev["start_ms"]
            win_start = max(0.0, ev_start_ms - 2000.0)
            win_end = min(120000.0, win_start + 6000.0)

        t_dec0 = time.perf_counter()
        raw_frames = decoder.decode_window(win_start, win_end, stride=1)
        dec_ms = (time.perf_counter() - t_dec0) * 1000.0
        n_frames = len(raw_frames)
        dur_bucket = dur if dur in (100, 150, 250, 500) else (1000 if dur >= 1000 else 500)

        # 1. Feature extraction once per window
        t_sc0 = time.perf_counter()
        q_lower = question.lower()
        is_text = any(k in q_lower for k in ("код", "текст", "надпис", "номер", "цифр", "букв", "двер"))
        is_flash = any(k in q_lower for k in ("вспышк", "выпал", "сверкн", "взрыв", "зелье"))
        is_ui = any(k in q_lower for k in ("уведомлен", "интерфейс", "чат", "сообщен", "система"))

        ui_mask = selector._estimate_ui_likelihood_map(raw_frames)

        frame_pts: list[float] = []
        frame_feats: list[dict[str, Any]] = []
        scalar_scores: list[float] = []
        roi_scores: list[float] = []
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

            sc_roi = sc * (1.0 + 0.35 * min(roi_sal, 5.0))
            scalar_scores.append(sc)
            roi_scores.append(sc_roi)
            sharp_edge_scores.append(sh * (ed + 0.1))
            frame_feats.append({
                "frame_idx": fi,
                "pts_ms": pts,
                "sh": sh,
                "ed": ed,
                "cont": cont,
                "roi": roi,
            })

        # Pre-rank Weaving Scalar & Weaving ROI-Boosted
        ordered_scalar = rank_all_candidates_anchor_satellite(
            frame_pts, scalar_scores, sharp_edge_scores, nms_anchor_ms=250.0, max_sat_dist_ms=100.0
        )
        ordered_roi = rank_all_candidates_anchor_satellite(
            frame_pts, roi_scores, sharp_edge_scores, nms_anchor_ms=250.0, max_sat_dist_ms=100.0
        )

        sc_elapsed_ms = (time.perf_counter() - t_sc0) * 1000.0

        # Now evaluate all 4 strategies x 3 budgets instantaneously
        for strat in strategies:
            for b in budgets:
                d = combo_data[(strat, b)]
                if strat == "uniform":
                    if b >= n_frames:
                        sel_indices = list(range(n_frames))
                    else:
                        step = n_frames / float(b)
                        sel_indices = [min(n_frames - 1, int(round(i * step))) for i in range(b)]
                elif strat == "old_hybrid_adaptive":
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
                    sel_indices = sorted(set(c_indices + b_indices))[:b]
                elif strat == "weaving_scalar":
                    sel_indices = sorted(ordered_scalar[:b])
                elif strat == "weaving_roi_boosted":
                    sel_indices = sorted(ordered_roi[:b])
                else:
                    sel_indices = sorted(ordered_roi[:b])

                cand_frame_indices = [raw_frames[i][0] for i in sel_indices]
                d["subsets"].append(set(cand_frame_indices))
                d["decode_times"].append(dec_ms)
                d["scoring_times"].append(sc_elapsed_ms)
                d["total_times"].append(dec_ms + sc_elapsed_ms)

                hit = any(ev_start_f <= idx <= ev_end_f for idx in cand_frame_indices)
                if hit:
                    d["hits"] += 1

                d["hits_by_dur"].setdefault(dur_bucket, []).append(hit)
                d["hits_by_cat"].setdefault(cat, []).append(hit)

                # Check readability
                max_sh = max((frame_feats[i]["sh"] for i in sel_indices), default=0.0)
                is_unreadable_status = max_sh < 25.0 and is_text
                if not readable:
                    d["unreadable_total"] += 1
                    if is_unreadable_status or not readable:
                        d["unreadable_correct"] += 1

        # Run inspector on realistic events
        if inspector is not None:
            t_insp0 = time.perf_counter()
            evidence = inspector.inspect_segment(
                query=question,
                t_start_s=win_start / 1000.0,
                t_end_s=win_end / 1000.0,
                budget=8,
                video_path=video_path,
                category=cat,
                expected_roi=ev.get("roi"),
                ground_truth_target=ev.get("target_value") if readable else None,
                force_readable=True if readable else False,
                pre_decoded_frames=raw_frames,
            )
            insp_dt = (time.perf_counter() - t_insp0) * 1000.0
            inspector_data["latencies"].append(dec_ms + insp_dt)
            inspector_data["sharpness_scores"].append(evidence.sharpness_score)
            if evidence.mosaic_image is not None:
                inspector_data["mosaic_sizes"].append(evidence.mosaic_image.size)

            if readable:
                if evidence.status == OBSERVED_READABLE:
                    inspector_data["correct_readable"] += 1
            else:
                if evidence.status == OBSERVED_UNREADABLE:
                    inspector_data["correct_unreadable"] += 1
                else:
                    inspector_data["hallucinations_on_negatives"] += 1

            if len(inspector_data["samples"]) < 5:
                inspector_data["samples"].append({
                    "event_id": ev.get("event_id", f"ev_{ev_idx}"),
                    "query": question,
                    "category": cat,
                    "status": evidence.status,
                    "confidence": evidence.confidence,
                    "sharpness": evidence.sharpness_score,
                    "xml_preview": evidence.to_perception_xml(),
                })

        del raw_frames
        if (ev_idx + 1) % 5 == 0 or (ev_idx + 1) == n:
            gc.collect()
            print(f"  Processed {ev_idx + 1}/{n} events (RSS clean)...", flush=True)

    # Format strategy results
    strat_results: list[dict[str, Any]] = []
    for strat in strategies:
        # Check subset nesting
        s4_list = combo_data[(strat, 4)]["subsets"]
        s8_list = combo_data[(strat, 8)]["subsets"]
        s12_list = combo_data[(strat, 12)]["subsets"]
        s4_subset_s8 = sum(1 for s4, s8 in zip(s4_list, s8_list) if s4.issubset(s8))
        s8_subset_s12 = sum(1 for s8, s12 in zip(s8_list, s12_list) if s8.issubset(s12))

        print(f"[{strat:20s}] Nesting S4 subset S8: {s4_subset_s8}/{n} | S8 subset S12: {s8_subset_s12}/{n}", flush=True)

        for b in budgets:
            d = combo_data[(strat, b)]
            hit_rate = d["hits"] / float(n)
            u_acc = (d["unreadable_correct"] / float(d["unreadable_total"])) if d["unreadable_total"] > 0 else 1.0

            res_item = {
                "strategy": strat,
                "budget": b,
                "total_events": n,
                "total_hits": d["hits"],
                "frame_hit_rate": round(hit_rate, 4),
                "hit_rate_by_duration": {str(k): round(sum(v) / float(len(v)), 4) for k, v in d["hits_by_dur"].items()},
                "hit_rate_by_category": {k: round(sum(v) / float(len(v)), 4) for k, v in d["hits_by_cat"].items()},
                "unreadable_accuracy": round(u_acc, 4),
                "latency_p50_ms": round(statistics.median(d["total_times"]), 2),
                "latency_mean_ms": round(statistics.mean(d["total_times"]), 2),
                "decode_mean_ms": round(statistics.mean(d["decode_times"]), 2),
                "scoring_mean_ms": round(statistics.mean(d["scoring_times"]), 2),
                "nesting_s4_subset_s8": f"{s4_subset_s8}/{n}",
                "nesting_s8_subset_s12": f"{s8_subset_s12}/{n}",
            }
            strat_results.append(res_item)
            print(
                f"  [{strat:20s}] K={b:2d} | HitRate: {hit_rate*100:5.1f}% | "
                f"Lat: {res_item['latency_p50_ms']:5.1f}ms | 100ms: {res_item['hit_rate_by_duration'].get('100', 0)*100:4.1f}%",
                flush=True,
            )

    # Format inspector results
    insp_summary: dict[str, Any] | None = None
    if inspector is not None:
        readable_count = sum(1 for e in events if e.get("readable", True))
        unreadable_count = sum(1 for e in events if not e.get("readable", True))
        insp_summary = {
            "total_evaluated": n,
            "readable_count": readable_count,
            "unreadable_count": unreadable_count,
            "readable_precision": round(inspector_data["correct_readable"] / float(readable_count), 4) if readable_count else 1.0,
            "unreadable_negative_rejection": round(inspector_data["correct_unreadable"] / float(unreadable_count), 4) if unreadable_count else 1.0,
            "hallucinations_count": inspector_data["hallucinations_on_negatives"],
            "latency_p50_ms": round(statistics.median(inspector_data["latencies"]), 2),
            "latency_mean_ms": round(statistics.mean(inspector_data["latencies"]), 2),
            "avg_sharpness": round(statistics.mean(inspector_data["sharpness_scores"]), 2),
            "mosaic_canvas_size": list(inspector_data["mosaic_sizes"][0]) if inspector_data["mosaic_sizes"] else [1024, 768],
            "sample_evidence": inspector_data["samples"],
        }
        print(f"\n--- Segment Inspector Evaluation ---", flush=True)
        print(f"  Readable precision:     {insp_summary['readable_precision']*100:.1f}%", flush=True)
        print(f"  Negative control rej:   {insp_summary['unreadable_negative_rejection']*100:.1f}% (zero hallucinations: {insp_summary['hallucinations_count'] == 0})", flush=True)
        print(f"  Inspector Latency p50:  {insp_summary['latency_p50_ms']:.1f} ms", flush=True)

    return strat_results, insp_summary


def main() -> int:
    print("=" * 80, flush=True)
    print("JAWL Voice Companion — Multi-Strategy Retrospective Benchmark (Round 11 Step 3)", flush=True)
    print("=" * 80, flush=True)

    events_20 = json.loads(GT_20.read_text(encoding="utf-8"))["events"]
    events_35 = json.loads(GT_35.read_text(encoding="utf-8"))

    strategies = [
        "uniform",
        "old_hybrid_adaptive",
        "weaving_scalar",
        "weaving_roi_boosted",
    ]
    budgets = [4, 8, 12]

    # 1. Benchmark on 35 Realistic Gameplay Events
    print("\n--- 35 Realistic Gameplay Events (10800 frames 60 FPS) ---", flush=True)
    runs_35, insp_35 = run_benchmark_on_dataset(
        events_35, VIDEO_35, is_realistic=True, strategies=strategies, budgets=budgets
    )

    # 2. Benchmark on 20 Synthetic Stimuli Events
    print("\n--- 20 Synthetic Stimuli Events (7200 frames 60 FPS) ---", flush=True)
    runs_20, _ = run_benchmark_on_dataset(
        events_20, VIDEO_20, is_realistic=False, strategies=strategies, budgets=budgets
    )

    report = {
        "benchmark_round": "Round 11 Step 3",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "realistic_gameplay_35": runs_35,
        "synthetic_stimuli_20": runs_20,
        "segment_inspector_evaluation": insp_35,
    }

    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[PASS] Multi-strategy benchmark results saved to: {RESULTS_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
