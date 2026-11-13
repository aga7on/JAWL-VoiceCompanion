"""Contract tests for the per-turn latency tracer.

The tracer is diagnostics: it must never raise into a live turn, must bound its
own disk use, and must let us attribute time between stages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion import turn_trace  # noqa: E402
from jawl_voicecompanion.turn_trace import TurnTracer  # noqa: E402


def test_marks_are_appended_in_order(tmp_path: Path) -> None:
    tracer = TurnTracer(tmp_path)
    tracer.mark("t1", "browser.button_pressed")
    tracer.mark("t1", "server.voice_end_received")
    tracer.mark("t1", "server.brain_returned")
    records = tracer.read("t1")
    assert [r["stage"] for r in records] == [
        "browser.button_pressed",
        "server.voice_end_received",
        "server.brain_returned",
    ]
    assert records[0]["since_start_s"] == 0.0
    assert records[-1]["since_start_s"] >= 0.0


def test_summary_reports_the_largest_gap(tmp_path: Path) -> None:
    tracer = TurnTracer(tmp_path)
    base = 1_700_000_000.0
    tracer.mark("t2", "start", wall_ts=base)
    tracer.mark("t2", "quick", wall_ts=base + 0.05)
    tracer.mark("t2", "slow", wall_ts=base + 30.0)
    summary = tracer.summary("t2")
    assert summary["marks"] == 3
    assert summary["largest_gap"]["from"] == "quick"
    assert summary["largest_gap"]["gap_ms"] == 29950.0


def test_trace_files_are_bounded(tmp_path: Path) -> None:
    tracer = TurnTracer(tmp_path, max_traces=4)
    for index in range(10):
        tracer.mark(f"t{index}", "stage")
    assert len(list(tmp_path.glob("*.jsonl"))) == 4


def test_mark_without_trace_is_a_noop(monkeypatch) -> None:
    monkeypatch.setattr(turn_trace, "_TRACER", None)
    # Must not raise when tracing was never configured.
    turn_trace.mark("anything", "stage")


def test_mark_swallows_writer_failures() -> None:
    class Broken(TurnTracer):
        def mark(self, *args, **kwargs):  # noqa: D401 - deliberate failure
            raise OSError("disk gone")

    original = turn_trace._TRACER
    try:
        turn_trace._TRACER = Broken(Path("."), max_traces=4)
        turn_trace.mark("t", "stage")  # must not propagate
    finally:
        turn_trace._TRACER = original


def test_empty_trace_id_is_rejected(tmp_path: Path) -> None:
    tracer = TurnTracer(tmp_path)
    try:
        tracer.mark("", "stage")
    except ValueError:
        return
    raise AssertionError("empty trace_id must be rejected")


def test_records_are_valid_json_lines(tmp_path: Path) -> None:
    tracer = TurnTracer(tmp_path)
    tracer.mark("t3", "stage", detail={"nested": {"a": 1}})
    line = (tmp_path / "t3.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["detail"]["nested"]["a"] == 1