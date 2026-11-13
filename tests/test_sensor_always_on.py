"""Tests for JAWL Cycle 09 Sensor Soak Runner (AC-01, AC-08, AC-09).

Verifies the soak runner contracts:
  1. Configuration setup and event schedule validation.
  2. Multi-stage metrics collection (frames, resources, integrity, pause).
  3. Clear separation of captured, accepted, dropped, recorded, and indexed frames.
  4. Preservation of machine-readable report even on abrupt failure.
  5. Enforcement of disk overflow safety guards.
  6. Clean resource teardown (threads stopped, files flushed).
  7. Strict AC-09 pause guarantees (0 frames ingested, clean segment close).
  8. Anti-spoofing rubric: partial or short runs cannot claim 60M verified status.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from jawl_voicecompanion.live_evidence_archive import LiveEvidenceArchive
from jawl_voicecompanion.temporal_index import TemporalIndexReader
from scripts.benchmark_sensor_always_on import FrameGenerator, SensorSoakRunner


@pytest.fixture
def temp_soak_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="test_soak_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_runner_configuration_and_setup(temp_soak_dir: Path) -> None:
    """Test 1: Runner correctly establishes configuration, paths, and event schedule."""
    runner = SensorSoakRunner(
        duration_s=600.0,
        fps=30.0,
        segment_duration_s=5.0,
        max_retention_s=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        checkpoint_interval_s=60.0,
        max_disk_mb=500.0,
        mock_capture=True,
        launch_qwen=False,
    )
    runner._setup_directories()
    runner._schedule_events()

    assert runner.archive_dir.exists()
    assert runner.report_path.parent.exists()
    assert len(runner.events_ledger) >= 4
    # Check scheduled fractions are monotonic
    t_starts = [ev["t_start_s"] for ev in runner.events_ledger]
    assert sorted(t_starts) == t_starts


def test_stale_artifacts_from_previous_run_are_removed(temp_soak_dir: Path) -> None:
    """Test: a stale checkpoint/report must not survive into a fresh run."""
    runner = SensorSoakRunner(
        duration_s=600.0,
        fps=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        mock_capture=True,
        launch_qwen=False,
    )
    # Simulate leftovers of an earlier soak that reported a different duration.
    runner.report_path.parent.mkdir(parents=True, exist_ok=True)
    runner.report_path.write_text('{"verdict": "PARTIAL", "target_duration_s": 180.0}', encoding="utf-8")
    runner.checkpoint_path.write_text('{"checkpoint_at_s": 135.0, "progress_pct": 75.0}', encoding="utf-8")

    runner._setup_directories()

    assert not runner.checkpoint_path.exists(), "stale checkpoint survived _setup_directories"
    assert not runner.report_path.exists(), "stale report survived _setup_directories"


def test_stage_metrics_collection_and_accounting(temp_soak_dir: Path) -> None:
    """Test 2 & 3: Run short headless soak; verify metrics collection & frame separation."""
    runner = SensorSoakRunner(
        duration_s=4.0,
        fps=30.0,
        segment_duration_s=2.0,
        max_retention_s=10.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        checkpoint_interval_s=2.0,
        pause_at_s=2.0,
        pause_duration_s=0.5,
        mock_capture=True,
        launch_qwen=False,
    )

    report = runner.run()

    assert runner.report_path.is_file()
    assert report["status"] == "COMPLETED"
    assert report["verdict"] == "PARTIAL"  # Short run (< 3600s) cannot be 60M verified!

    frames = report["frames"]
    assert frames["captured"] > 0
    assert frames["ingested_accepted"] > 0
    assert "ingested_dropped_queue" in frames
    assert "archive_recorded" in frames
    assert "archive_encoder_dropped" in frames
    assert "indexed_records_valid" in frames

    # Metric groups present
    assert "resources" in report
    assert "baseline_rss_mb" in report["resources"]
    assert "integrity" in report
    assert "ac_09_control" in report
    assert report["ac_09_control"]["pause_executed"] is True
    assert report["ac_09_control"]["frames_ingested_during_pause"] == 0


def test_report_preservation_on_abrupt_failure(temp_soak_dir: Path) -> None:
    """Test 4: Abrupt failure during soak preserves valid JSON report with fault reason."""
    runner = SensorSoakRunner(
        duration_s=10.0,
        fps=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        mock_capture=True,
        launch_qwen=False,
    )

    # Inject simulated hardware failure in frame ingestion
    with patch.object(runner, "_schedule_events", side_effect=RuntimeError("Simulated DXGI device loss")):
        report = runner.run()

    assert runner.report_path.is_file()
    assert report["status"] == "FAILED"
    assert report["verdict"] == "FAILED"
    assert "Simulated DXGI device loss" in report["fault_reason"]


def test_disk_limit_guard_triggers_safe_abort(temp_soak_dir: Path) -> None:
    """Test 5: Exceeding safe disk bound triggers emergency halt before running out of space."""
    # Place a dummy file in archive dir that exceeds max_disk_mb
    arch = temp_soak_dir / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    dummy_file = arch / "overflow.dat"
    dummy_file.write_bytes(b"0" * 1024 * 1024)  # 1 MB

    runner = SensorSoakRunner(
        duration_s=10.0,
        fps=30.0,
        segment_duration_s=1.0,
        archive_dir=arch,
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        max_disk_mb=0.5,  # 0.5 MB limit < 1 MB file
        mock_capture=True,
        launch_qwen=False,
    )

    # Note: runner._setup_directories() clears archive_dir, so we write after setup or patch _get_archive_disk_mb
    with patch.object(runner, "_get_archive_disk_mb", return_value=5.0):
        report = runner.run()

    assert report["status"] == "FAILED"
    assert "Archive disk usage exceeded safe bound" in report["fault_reason"]
    # Teardown was executed cleanly
    assert runner.archive is None or not runner.archive.is_running


def test_resource_release_and_teardown(temp_soak_dir: Path) -> None:
    """Test 6: Teardown stops worker thread and closes all open handles."""
    runner = SensorSoakRunner(
        duration_s=2.0,
        fps=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        mock_capture=True,
        launch_qwen=False,
    )
    runner.run()
    # Confirm archive stopped
    assert runner.archive is not None
    assert runner.archive.is_running is False


def test_pause_guarantees_zero_ingestion_ac09(temp_soak_dir: Path) -> None:
    """Test 7: AC-09 invariant — paused archive rejects all frames and closes active segment."""
    archive = LiveEvidenceArchive(
        archive_dir=temp_soak_dir / "archive",
        segment_duration_s=5.0,
        fps=30.0,
    )
    archive.start()

    dummy = np.zeros((720, 1280, 3), dtype=np.uint8)

    # Ingest while running
    assert archive.ingest_frame(dummy, pts_us=1000) is True

    # Pause
    archive.pause()
    assert archive.is_paused is True

    # All ingest attempts during pause MUST be rejected
    for i in range(10):
        ok = archive.ingest_frame(dummy, pts_us=2000 + i * 1000)
        assert ok is False, "Ingest accepted during paused state!"

    # Resume
    archive.resume()
    assert archive.is_paused is False
    assert archive.ingest_frame(dummy, pts_us=50000) is True

    archive.stop(timeout_s=2.0)


def test_cannot_claim_60m_verified_on_short_or_partial_run(temp_soak_dir: Path) -> None:
    """Test 8: Anti-spoofing rubric — runs < 3590s cannot be declared VISION_SOAK_60M_VERIFIED."""
    runner = SensorSoakRunner(
        duration_s=5.0,
        fps=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        mock_capture=True,
        launch_qwen=False,
    )
    report = runner.run()

    # Even if cleanly completed, verdict MUST be PARTIAL, never VISION_SOAK_60M_VERIFIED
    assert report["verdict"] == "PARTIAL"
    assert report["verdict"] != "VISION_SOAK_60M_VERIFIED"


def test_report_schema_and_component_intervals(temp_soak_dir: Path) -> None:
    """Test 9: Verify required fields in soak report including active components, intervals, and config."""
    runner = SensorSoakRunner(
        duration_s=3.0,
        fps=30.0,
        archive_dir=temp_soak_dir / "archive",
        report_path=temp_soak_dir / "report.json",
        checkpoint_path=temp_soak_dir / "checkpoint.json",
        mock_capture=True,
        launch_qwen=False,
    )
    report = runner.run()

    assert "configuration" in report
    assert "active_components" in report
    assert "activity_intervals" in report
    assert "source_report_path" in report
    assert "log_paths" in report
    assert report["configuration"]["duration_s"] == 3.0
    assert "SoakTestWindow_DXGI_GDI" in report["active_components"]
    assert "wasapi_audio" in report["activity_intervals"]
    soak_mirrored = Path(__file__).resolve().parent.parent / "runtime" / "instances" / "soak_h1_60min.json"
    assert soak_mirrored.exists()
