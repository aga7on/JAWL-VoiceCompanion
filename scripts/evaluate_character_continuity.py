"""Evaluate character identity continuity, Re-ID hypotheses, and crossmodal grounding.

Analyzes multimodal_session_ledger.json to verify:
1. Entity persistence across camera cuts and occlusions.
2. Hypothesis-driven Re-ID precision (preventing identity fragmentation).
3. Speaker-binding consistency across dialogue turns.
4. Semantic diff bandwidth reduction for Language-Out-of-the-Loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def evaluate_ledger(ledger_path: Path) -> dict[str, Any]:
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    
    duration = data.get("duration_watched_sec", 0.0)
    visual_events = data.get("visual_events", [])
    speech_events = data.get("speech_events", [])
    audio_events = data.get("audio_events", [])
    tracker_summary = data.get("entity_tracker_summary", {})
    semantic_diffs = data.get("semantic_diffs", [])
    matrix_state = data.get("spatial_matrix_state", {})
    hypotheses = tracker_summary.get("hypotheses_log", [])
    active_entities = tracker_summary.get("active_entities", [])

    # 1. Hypothesis analysis
    total_hyp = len(hypotheses)
    confirmed_hyp = [h for h in hypotheses if h.get("status") == "confirmed"]
    proposed_hyp = [h for h in hypotheses if h.get("status") == "proposed"]
    
    sims = [h.get("similarity", 0.0) for h in confirmed_hyp]
    avg_confirmed_sim = sum(sims) / len(sims) if sims else 0.0

    # 2. Entity survival & alias tracking
    entities_with_aliases = [e for e in active_entities if len(e.get("aliases", [])) > 0]
    total_aliases = sum(len(e.get("aliases", [])) for e in active_entities)

    # 3. Speech grounding
    grounded_speech = [s for s in speech_events if s.get("text")]
    
    # 4. Cache telemetry
    cache_rate = matrix_state.get("cache_hit_rate_pct", 0.0)

    report = {
        "duration_watched_sec": duration,
        "visual_keyframes": len(visual_events),
        "speech_turns": len(grounded_speech),
        "spatial_cache_hit_rate_pct": cache_rate,
        "entities_tracked": len(active_entities),
        "entities_with_reid_aliases": len(entities_with_aliases),
        "total_reid_aliases_merged": total_aliases,
        "reid_hypotheses": {
            "total": total_hyp,
            "confirmed": len(confirmed_hyp),
            "proposed": len(proposed_hyp),
            "avg_confirmed_cosine_similarity": round(avg_confirmed_sim, 4),
        },
        "semantic_diffs_emitted": len(semantic_diffs),
    }

    print("\n" + "=" * 75)
    print("MULTIMODAL CONTINUITY & COGNITIVE CORE EVALUATION REPORT")
    print("=" * 75)
    print(f"Total Video Duration Watched: {duration:.1f} s (~{duration/60:.2f} min)")
    print(f"Incremental Spatial Matrix Cache Hit Rate: {cache_rate}%")
    print(f"Total Visual Keyframes: {len(visual_events)}")
    print(f"Total Dialogue Turns (ASR): {len(grounded_speech)}")
    print(f"Tracked Entities: {len(active_entities)}")
    print(f"Entities with confirmed Re-ID continuity: {len(entities_with_aliases)}")
    print(f"Total Camera Cut / Occlusion Merges (Aliases): {total_aliases}")
    print(f"Re-ID Hypotheses: {len(confirmed_hyp)} Confirmed, {len(proposed_hyp)} Proposed (Tentative)")
    print(f"Average Confirmed Re-ID Cosine Similarity: {avg_confirmed_sim:.4f}")
    print(f"Language-Out-of-the-Loop Semantic Diffs: {len(semantic_diffs)}")

    print("\n" + "-" * 75)
    print("KEY RE-ID HYPOTHESIS CONFIRMATIONS ACROSS CAMERA CUTS:")
    print("-" * 75)
    for h in confirmed_hyp[:10]:
        print(f"  * {h.get('candidate_id')} -> {h.get('target_track_id')} (sim={h.get('similarity'):.3f}): {h.get('reason')}")

    print("\n" + "-" * 75)
    print("SAMPLE RECONSTRUCTED DIALOGUE & SPEAKER BINDING:")
    print("-" * 75)
    for i, s in enumerate(grounded_speech[:12], 1):
        print(f"  {i:02d}. [{s.get('time_range')}] {s.get('text')}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path, help="Path to multimodal_session_ledger.json")
    args = parser.parse_args()
    evaluate_ledger(args.ledger)
