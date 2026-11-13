"""Round 11, Step 1 — Retrospective Perception Benchmark.

Benchmarking retrospective frame selection strategies across:
  A — Uniform
  B — Spatial-Only (IncrementalSpatialMatrix 21x30)
  C — Hybrid One-Pass (Grid + soft HUD-suppressed sharpness/edge peak)
  D — Hybrid Adaptive (Coarse sweep + temporal refinement burst)
  Oracle — Ground-truth best frame upper bound

Dataset:
  Video: runtime/instances/retro_bench/stimuli_60fps.mp4 (60 FPS, 120s, 7200 frames)
  GT:    runtime/instances/retro_bench/retro_bench_ground_truth.json (20 events)
  Search window per query: 10.0 seconds (600 frames). Target duration: 100-500 ms.

Zero real desktop or owner screen content is used.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.retro_selector import RetrospectiveFrameSelector

BENCH_DIR = ROOT / "runtime" / "instances" / "retro_bench"
VIDEO_PATH = BENCH_DIR / "stimuli_60fps.mp4"
GT_PATH = BENCH_DIR / "retro_bench_ground_truth.json"
RESULTS_PATH = BENCH_DIR / "benchmark_results.json"


def evaluate_run(
    events: list[dict],
    strategy: str,
    budget: int,
    selector: RetrospectiveFrameSelector,
) -> dict[str, Any]:
    hits = 0
    hits_by_dur: dict[int, list[bool]] = {100: [], 150: [], 250: [], 500: []}
    hits_by_class: dict[str, list[bool]] = {"T-Motion": [], "T-Static": [], "O-Static": [], "O-Flash": []}
    unreadable_correct = 0
    unreadable_total = 0

    decode_times: list[float] = []
    scoring_times: list[float] = []
    total_times: list[float] = []

    event_logs: list[dict[str, Any]] = []

    for ev in events:
        ev_id = ev["event_id"]
        ev_cls = ev["class"]
        dur = ev["duration_ms"]
        ev_start = ev["start_ms"]
        ev_start_f = ev["start_frame"]
        ev_end_f = ev["end_frame"]
        readable = ev.get("readable", True)

        # 10.0 second window around the event (centered with slight randomized jitter)
        # Target must be located inside the 10s search window
        win_start = max(0.0, ev_start - 4500.0)
        win_end = min(120000.0, win_start + 10000.0)
        if win_end - win_start < 10000.0:
            win_start = max(0.0, win_end - 10000.0)

        t_res = selector.select_frames(
            video_path=VIDEO_PATH,
            start_ms=win_start,
            end_ms=win_end,
            question=ev["question"],
            strategy=strategy,
            budget_frames=budget,
            oracle_gt=ev if strategy == "oracle" else None,
        )

        decode_times.append(t_res.decode_ms)
        scoring_times.append(t_res.scoring_ms)
        total_times.append(t_res.total_ms)

        selected_indices = t_res.frame_indices()
        # Hit if at least one selected frame lies strictly in [ev_start_f, ev_end_f]
        hit_indices = [idx for idx in selected_indices if ev_start_f <= idx <= ev_end_f]
        is_hit = len(hit_indices) > 0

        if is_hit:
            hits += 1
        if dur in hits_by_dur:
            hits_by_dur[dur].append(is_hit)
        if ev_cls in hits_by_class:
            hits_by_class[ev_cls].append(is_hit)

        # Unreadable control calibration
        if not readable:
            unreadable_total += 1
            if t_res.detail_status == "observed_unreadable":
                unreadable_correct += 1

        event_logs.append({
            "event_id": ev_id,
            "class": ev_cls,
            "duration_ms": dur,
            "readable": readable,
            "hit": is_hit,
            "hit_frames": hit_indices,
            "selected_frames": selected_indices,
            "detail_status": t_res.detail_status,
            "target_status": t_res.target_status,
            "decode_ms": round(t_res.decode_ms, 2),
            "scoring_ms": round(t_res.scoring_ms, 2),
            "total_ms": round(t_res.total_ms, 2),
        })

    n_ev = len(events)
    hit_rate = (hits / float(n_ev)) if n_ev > 0 else 0.0

    dur_rates = {
        d: (sum(lst) / len(lst)) if lst else 0.0
        for d, lst in hits_by_dur.items()
    }
    cls_rates = {
        c: (sum(lst) / len(lst)) if lst else 0.0
        for c, lst in hits_by_class.items()
    }
    unreadable_acc = (unreadable_correct / float(unreadable_total)) if unreadable_total > 0 else 1.0

    return {
        "strategy": strategy,
        "budget": budget,
        "total_events": n_ev,
        "total_hits": hits,
        "frame_hit_rate": round(hit_rate, 4),
        "hit_rate_by_duration": {str(k): round(v, 4) for k, v in dur_rates.items()},
        "hit_rate_by_class": {k: round(v, 4) for k, v in cls_rates.items()},
        "unreadable_control_accuracy": round(unreadable_acc, 4),
        "latency_ms": {
            "decode_mean": round(statistics.mean(decode_times), 2) if decode_times else 0.0,
            "scoring_mean": round(statistics.mean(scoring_times), 2) if scoring_times else 0.0,
            "total_p50": round(statistics.median(total_times), 2) if total_times else 0.0,
            "total_mean": round(statistics.mean(total_times), 2) if total_times else 0.0,
        },
        "event_logs": event_logs,
    }


def main() -> int:
    if not VIDEO_PATH.is_file() or not GT_PATH.is_file():
        print(f"FAIL: Missing stimuli video or GT in {BENCH_DIR}")
        return 1

    gt_data = json.loads(GT_PATH.read_text(encoding="utf-8"))
    events = gt_data["events"]
    print(f"Loaded {len(events)} events from {GT_PATH}")

    selector = RetrospectiveFrameSelector()

    experiments = [
        ("uniform", 8),
        ("uniform", 12),
        ("spatial", 8),
        ("spatial", 12),
        ("hybrid_onepass", 8),
        ("hybrid_onepass", 12),
        ("hybrid_adaptive", 8),
        ("hybrid_adaptive", 12),
        ("oracle", 1),
        ("oracle", 12),
    ]

    all_results: list[dict[str, Any]] = []

    print("\nStarting Retrospective Perception Benchmark (Round 11, Step 1)...")
    print("-" * 80)

    for strat, bud in experiments:
        t0 = time.monotonic()
        res = evaluate_run(events, strat, bud, selector)
        dt = time.monotonic() - t0
        all_results.append(res)
        print(
            f"Strategy: {strat:16s} | K={bud:2d} | HitRate: {res['frame_hit_rate']*100:5.1f}% | "
            f"100ms: {res['hit_rate_by_duration']['100']*100:4.1f}% | "
            f"150ms: {res['hit_rate_by_duration']['150']*100:4.1f}% | "
            f"T-Motion: {res['hit_rate_by_class']['T-Motion']*100:4.1f}% | "
            f"Latency: {res['latency_ms']['total_p50']:5.1f}ms | elapsed: {dt:4.1f}s"
        )

    out = {
        "benchmark_round": "Round 11, Step 1",
        "benchmark_name": "Retrospective Perception Benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "video": str(VIDEO_PATH),
        "total_events": len(events),
        "runs": all_results,
    }

    RESULTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 80)
    print(f"\nSaved benchmark results to: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
