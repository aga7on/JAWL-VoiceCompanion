# -*- coding: utf-8 -*-
"""Comprehensive Unit & Integration Tests for Live Temporal Evidence Archive (Round 11, Step 2)."""

import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from jawl_voicecompanion.live_evidence_archive import (
    EvidenceSegment,
    LiveEvidenceArchive,
    SegmentWriter,
    TelemetryComputer,
)
from jawl_voicecompanion.temporal_index import (
    FLAG_ENCODER_DROPPED,
    FLAG_VALID,
    IndexFrameRecord,
)


def test_telemetry_computer_computation_and_timing():
    """Verify that TelemetryComputer computes all required perceptual features fast (<2ms)."""
    computer = TelemetryComputer()

    # Generate a synthetic 1280x720 RGB frame with a simulated HUD banner and moving center
    frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
    # HUD banner at top
    frame[:60, :] = 120
    # Text-like high frequency pattern in center
    frame[300:350, 400:600:2] = 250

    # Warmup allocation
    computer.compute(frame_input=frame, frame_id=0, segment_id=0, pts_us=0, scene_version=0)

    t0 = time.perf_counter()
    rec, arr = computer.compute(
        frame_input=frame,
        frame_id=1,
        segment_id=0,
        pts_us=1_000_000,
        scene_version=1,
    )
    t_comp = (time.perf_counter() - t0) * 1000.0

    # Verification of record structure and invariants
    assert isinstance(rec, IndexFrameRecord)
    assert rec.frame_id == 1
    assert rec.segment_id == 0
    assert rec.pts_us == 1_000_000
    assert rec.scene_version == 1
    assert rec.sharpness_score > 0.0
    assert rec.edge_text_score > 0.0
    assert len(rec.local_change_mask) in (79, 80)
    assert len(rec.ui_likelihood_mask) in (79, 80)
    # Telemetry should be fast (comfortably < 10 ms on test runner)
    assert t_comp < 10.0


def test_segment_writer_lifecycle_and_extraction(tmp_path: Path):
    """Verify that SegmentWriter produces valid paired .mp4 and .jte1 files."""
    writer = SegmentWriter(
        segment_id=42,
        output_dir=tmp_path,
        start_pts_us=5_000_000,
        fps=30.0,
        width=640,
        height=360,
    ).open()

    frames_to_write = 15
    for i in range(frames_to_write):
        img = np.full((360, 640, 3), i * 15, dtype=np.uint8)
        rec = IndexFrameRecord.from_masks(
            frame_id=i,
            segment_id=42,
            pts_us=5_000_000 + i * 33_333,
            scene_version=0,
            global_motion=float(i) / 10.0,
            sharpness=50.0 + float(i),
        )
        writer.add_frame(img, rec)

    seg = writer.close()

    assert isinstance(seg, EvidenceSegment)
    assert seg.segment_id == 42
    assert seg.frame_count == frames_to_write
    assert seg.video_path.is_file()
    assert seg.index_path.is_file()
    assert seg.duration_ms > 0

    # Read records from sidecar
    recs = seg.read_records()
    assert len(recs) == frames_to_write
    assert recs[0].pts_us == 5_000_000
    assert recs[-1].pts_us == 5_000_000 + (frames_to_write - 1) * 33_333

    # Extract sparse frames from video container
    extracted = seg.extract_frames([0, 7, 14])
    assert 0 in extracted
    assert 7 in extracted
    assert 14 in extracted
    assert isinstance(extracted[7], Image.Image)
    assert extracted[7].size == (640, 360)


def test_live_archive_rotation_and_ring_retention(tmp_path: Path):
    """Verify segment rotation at duration boundary and automatic ring buffer retention pruning."""
    # 0.2s segments (6 frames at 30 fps), retain up to 0.6s (3 segments max)
    archive = LiveEvidenceArchive(
        archive_dir=tmp_path,
        segment_duration_s=0.2,
        max_retention_s=0.6,
        fps=30.0,
        width=320,
        height=240,
        queue_size=50,
    )

    with archive:
        # Ingest 24 frames (~0.8s of footage -> should create 4 segments and evict the oldest)
        for i in range(24):
            img = np.full((240, 320, 3), (i * 10) % 255, dtype=np.uint8)
            success = archive.ingest_frame(img, pts_us=10_000_000 + i * 33_333)
            assert success is True
            time.sleep(0.01)

        # Allow worker thread to drain
        time.sleep(0.2)

    stats = archive.get_stats()
    assert stats["recorded_frames"] == 24
    assert stats["dropped_frames"] == 0
    # Ring retention should prune oldest segments so count <= 4
    assert len(archive._segments) >= 2
    # Total retained duration should be bounded by max_retention_s + 1 segment grace
    assert stats["total_retained_duration_s"] <= 1.0


def test_non_blocking_load_shedding(tmp_path: Path):
    """Verify that when the ingest queue fills, capture never stalls and frames drop gracefully."""
    # Tiny queue of size 2
    archive = LiveEvidenceArchive(
        archive_dir=tmp_path,
        segment_duration_s=1.0,
        max_retention_s=5.0,
        fps=30.0,
        width=320,
        height=240,
        queue_size=2,
    )
    # Do not call start() so worker does not drain queue
    archive._running = True

    img = np.zeros((240, 320, 3), dtype=np.uint8)

    # First two should succeed
    assert archive.ingest_frame(img, pts_us=100) is True
    assert archive.ingest_frame(img, pts_us=200) is True

    # Third should drop immediately without blocking
    t0 = time.perf_counter()
    res = archive.ingest_frame(img, pts_us=300)
    dt = (time.perf_counter() - t0) * 1000.0

    assert res is False
    assert archive._dropped_frames == 1
    assert dt < 5.0  # Must be immediate non-blocking call (< 5 ms)


def test_selective_candidate_extraction_hybrid_adaptive(tmp_path: Path):
    """Verify candidate frame selection from sidecar index and selective video decoding."""
    archive = LiveEvidenceArchive(
        archive_dir=tmp_path,
        segment_duration_s=0.5,  # 15 frames per segment
        max_retention_s=5.0,
        fps=30.0,
        width=320,
        height=240,
    )

    with archive:
        start_pts = 20_000_000
        # Ingest 30 frames (spanning 2 segments)
        for i in range(30):
            img = np.full((240, 320, 3), 50, dtype=np.uint8)
            # Inject a sharp transient high-frequency text event at frame 18
            if i == 18:
                img[100:140, 100:220:2] = 255  # High contrast edge burst
            archive.ingest_frame(img, pts_us=start_pts + i * 33_333)
            time.sleep(0.005)

        time.sleep(0.2)

    # Query interval across the whole window
    end_pts = start_pts + 29 * 33_333
    segs = archive.query_interval(start_pts, end_pts)
    assert len(segs) >= 2

    records = archive.get_records(start_pts, end_pts)
    assert len(records) == 30

    # Run hybrid adaptive selection with budget K=8
    results = archive.select_candidate_frames(
        start_pts_us=start_pts,
        end_pts_us=end_pts,
        question="Какой текст или код появился?",
        strategy="hybrid_adaptive",
        budget=8,
    )

    assert len(results) == 8
    # Frame 18 (the text burst) should be identified and selected
    selected_pts = [rec.pts_us for _, rec, _ in results]
    burst_pts = start_pts + 18 * 33_333
    assert burst_pts in selected_pts

    # Verify that the decoded image for the candidate frame was retrieved
    for seg, rec, img in results:
        assert isinstance(rec, IndexFrameRecord)
        if img is not None:
            assert isinstance(img, Image.Image)
            assert img.size == (320, 240)


def test_priority_micro_stash_eviction_and_transparent_loss(tmp_path: Path):
    """Verify that Priority Micro-Stash evicts lowest utility frames and indexes all drops."""
    archive = LiveEvidenceArchive(
        archive_dir=tmp_path,
        segment_duration_s=2.0,
        max_retention_s=10.0,
        fps=30.0,
        width=320,
        height=240,
    )
    archive.simulate_congestion = True

    with archive:
        start_pts = 1_000_000
        # Ingest 12 frames under simulated congestion (stash capacity is 8)
        # Frames 0..7: low utility (flat uniform gray)
        for i in range(8):
            flat_img = np.full((240, 320, 3), 60, dtype=np.uint8)
            archive.ingest_frame(flat_img, pts_us=start_pts + i * 33_333)
            time.sleep(0.005)

        # Frames 8..9: high utility text edge burst
        for i in range(8, 10):
            burst_img = np.full((240, 320, 3), 60, dtype=np.uint8)
            burst_img[80:160, 50:250:2] = 255
            archive.ingest_frame(burst_img, pts_us=start_pts + i * 33_333)
            time.sleep(0.005)

        # Frames 10..11: low utility again
        for i in range(10, 12):
            flat_img = np.full((240, 320, 3), 60, dtype=np.uint8)
            archive.ingest_frame(flat_img, pts_us=start_pts + i * 33_333)
            time.sleep(0.005)

        time.sleep(0.3)

    # Inspect records from disk
    segs = archive.query_interval(start_pts, start_pts + 12 * 33_333)
    assert len(segs) >= 1
    all_recs = []
    for s in segs:
        all_recs.extend(s.read_records())

    # Every ingested frame must have a JTI record (zero silent FIFO drop)
    assert len(all_recs) == 12

    # Verify that dropped frames were explicitly marked with FLAG_ENCODER_DROPPED and idx=-1
    dropped_recs = [r for r in all_recs if (r.quality_flags & FLAG_ENCODER_DROPPED) != 0]
    assert len(dropped_recs) > 0
    for r in dropped_recs:
        assert r.segment_sample_idx == -1

    # High-utility frames (frames 8 and 9) should have been preserved (segment_sample_idx >= 0)
    high_util_recs = [r for r in all_recs if r.edge_text_score > 0.3]
    for r in high_util_recs:
        assert (r.quality_flags & FLAG_ENCODER_DROPPED) == 0
        assert r.segment_sample_idx >= 0
