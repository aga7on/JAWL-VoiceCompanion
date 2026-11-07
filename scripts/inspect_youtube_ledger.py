"""Inspect and format multimodal session ledger from YouTube watching."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def inspect_ledger(ledger_path: Path):
    if not ledger_path.is_file():
        print(f"File not found: {ledger_path}")
        return

    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    print("=" * 70)
    print("YOUTUBE MULTIMODAL WATCHING SESSION SUMMARY")
    print("=" * 70)
    print(f"URL: {data.get('url')}")
    print(f"Watched duration: {data.get('duration_watched_sec')} seconds")
    print(f"Visual events (keyframes): {len(data.get('visual_events', []))}")
    print(f"Audio events (DSP chunks): {len(data.get('audio_events', []))}")
    print(f"Speech events (ASR utterances): {len(data.get('speech_events', []))}")
    print(f"Consolidated episode logs: {len(data.get('episode_logs', []))}")
    print(f"Character cards: {len(data.get('character_cards', []))}")

    sm_state = data.get("spatial_matrix_state")
    if sm_state:
        print("\n" + "=" * 70)
        print("INCREMENTAL SPATIAL MATRIX TELEMETRY (VLMCache / EP-ViT)")
        print("=" * 70)
        print(f"Grid shape: {sm_state.get('grid_shape')} ({sm_state.get('total_tiles')} tiles)")
        print(f"Ticks processed: {sm_state.get('tick_count')}")
        print(f"Cache hit rate: {sm_state.get('cache_hit_rate_pct')}%")
        print(f"Tiles computed: {sm_state.get('total_tiles_computed')}")
        print(f"Tiles cached: {sm_state.get('total_tiles_cached')}")

    print("\n" + "=" * 70)
    print("RECONSTRUCTED SPEECH & DIALOGUE TIMELINE (GigaAM RNN-T)")
    print("=" * 70)
    speech_events = data.get("speech_events", [])
    if not speech_events:
        print("  (No speech detected)")
    for i, s in enumerate(speech_events, 1):
        tr = s.get("time_range", "00:00")
        txt = s.get("text", "")
        print(f"  {i:02d}. [{tr}] {txt}")

    print("\n" + "=" * 70)
    print("AUDIO & SOUNDTRACK CHARACTERISTICS (WASAPI 48kHz -> DSP)")
    print("=" * 70)
    audio_events = data.get("audio_events", [])
    for a in audio_events[:15]:
        tr = a.get("time_range", "")
        rms = a.get("rms", 0.0)
        c_hz = a.get("centroid_hz", 0.0)
        hnr = a.get("hnr_db", 0.0)
        char = a.get("soundtrack_character", "")
        val = a.get("valence", 0.0)
        arousal = a.get("arousal", 0.0)
        print(f"  [{tr}] RMS: {rms:.3f} | Centroid: {c_hz:6.1f} Hz | HNR: {hnr:5.2f} dB | V={val:+.2f} A={arousal:+.2f} -> {char}")

    print("\n" + "=" * 70)
    print("KEYFRAME COLLAGES & VISUAL MEMORY")
    print("=" * 70)
    collages = [v for v in data.get("visual_events", []) if v.get("collage_path")]
    print(f"Total 2x2 Storyboard collages saved: {len(collages)}")
    for c in collages[:5]:
        print(f"  [{c.get('timestamp')}] Collage: {c.get('collage_path')}")

    tracker_sum = data.get("entity_tracker_summary")
    if tracker_sum:
        print("\n" + "=" * 70)
        print("SCENESTATE ENTITY TRACKING & RE-ID CONTINUITY (LEVEL 2 & 3)")
        print("=" * 70)
        active_ents = tracker_sum.get("active_entities", [])
        print(f"Tracked entities in final state: {len(active_ents)}")
        for e in active_ents:
            print(f"  ID: {e.get('track_id')} | Label: '{e.get('label')}' | State: {e.get('state')} | Aliases: {e.get('aliases')} | BBox: {e.get('bbox')}")
        print(f"Total Re-ID Hypotheses: {tracker_sum.get('total_hypotheses', 0)}")
        print(f"  Confirmed: {tracker_sum.get('confirmed_hypotheses', 0)}")
        print(f"  Proposed: {tracker_sum.get('proposed_hypotheses', 0)}")
        for h in tracker_sum.get("hypotheses_log", [])[:8]:
            print(f"    - [{h.get('status').upper()}] {h.get('candidate_id')} -> {h.get('target_track_id')} (sim={h.get('similarity'):.3f}): {h.get('reason')}")

    sem_diffs = data.get("semantic_diffs", [])
    if sem_diffs:
        print("\n" + "=" * 70)
        print(f"SEMANTIC DIFF DELTAS (Language-Out-of-the-Loop Events): {len(sem_diffs)} recorded")
        print("=" * 70)
        for sd in sem_diffs[:6]:
            diff_obj = sd.get("diff", {})
            t_sec = sd.get("vid_time_sec")
            print(f"  [t={t_sec}s] Added: {diff_obj.get('entities_added')} | Modified: {len(diff_obj.get('entities_modified', []))} | Lost: {diff_obj.get('entities_lost')}")

    print("\n" + "=" * 70)
    print("EPISODE LOGS (Consolidated Narrative)")
    print("=" * 70)
    for log in data.get("episode_logs", []):
        print(f"  - {log}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Path to multimodal_session_ledger.json")
    args = parser.parse_args()
    inspect_ledger(args.path)
