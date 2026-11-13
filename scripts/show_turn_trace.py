"""Render one turn trace as a millisecond timeline with gaps called out.

Usage:
    python -X utf8 scripts/show_turn_trace.py                 # newest trace
    python -X utf8 scripts/show_turn_trace.py <trace_id>
    python -X utf8 scripts/show_turn_trace.py --all           # list recent
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "runtime" / "instances" / ".turn-trace"

# Stages that represent a user-perceived milestone, in expected order.
MILESTONES = (
    "browser.button_pressed",
    "browser.capture_started",
    "browser.audio_first_chunk",
    "browser.audio_last_chunk",
    "server.voice_end_received",
    "server.asr_start",
    "server.asr_done",
    "server.brain_dispatch",
    "server.brain_returned",
    "server.first_audio_chunk_ready",
    "browser.playback_started",
)


def load(trace_id: str) -> list[dict]:
    path = TRACE_DIR / f"{trace_id}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def traces() -> list[Path]:
    if not TRACE_DIR.exists():
        return []
    return sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def show(trace_id: str) -> int:
    records = [r for r in load(trace_id) if r.get("stage") != "http"]
    http = [r for r in load(trace_id) if r.get("stage") == "http"]
    if not records:
        print(f"no trace records for {trace_id}")
        return 1
    ordered = sorted(records, key=lambda r: r["wall_ts"])
    base = ordered[0]["wall_ts"]
    print(f"trace: {trace_id}")
    print(f"marks: {len(ordered)}   http events: {len(http)}")
    print()
    print(f"{'at_s':>9}  {'gap_ms':>9}  stage")
    print("-" * 78)
    previous = None
    for record in ordered:
        at = record["wall_ts"] - base
        gap = "-" if previous is None else f"{(record['wall_ts'] - previous) * 1000:9.1f}"
        marker = " *" if record["stage"] in MILESTONES else "  "
        detail = record.get("detail")
        shown = ""
        if detail:
            shown = json.dumps(detail, ensure_ascii=False)
            if len(shown) > 60:
                shown = shown[:57] + "..."
        print(f"{at:9.3f}  {gap:>9}  {record['stage']}{marker} {shown}")
        previous = record["wall_ts"]
    print()
    # Attribute the time between milestones.
    print("milestone deltas:")
    found = [(r["stage"], r["wall_ts"]) for r in ordered if r["stage"] in MILESTONES]
    for (name_a, ts_a), (name_b, ts_b) in zip(found, found[1:]):
        print(f"  {(ts_b - ts_a) * 1000:9.1f} ms   {name_a}  ->  {name_b}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_id", nargs="?")
    parser.add_argument("--all", action="store_true", help="list recent traces")
    args = parser.parse_args()

    if args.all:
        for path in traces()[:20]:
            records = load(path.stem)
            span = ""
            if records:
                times = [r["wall_ts"] for r in records]
                span = f"{max(times) - min(times):7.2f}s  {len(records):3d} marks"
            print(f"{path.stem}  {span}")
        return 0

    if args.trace_id:
        return show(args.trace_id)
    recent = traces()
    if not recent:
        print(f"no traces in {TRACE_DIR}")
        return 1
    return show(recent[0].stem)


if __name__ == "__main__":
    raise SystemExit(main())