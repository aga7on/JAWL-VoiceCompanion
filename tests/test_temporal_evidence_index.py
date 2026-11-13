# -*- coding: utf-8 -*-
"""Unit tests for JAWL Temporal Evidence Index v1 (Round 11, Step 1)."""

import os
import struct
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from jawl_voicecompanion.temporal_evidence_index import (
    FLAG_METADATA_DROPPED,
    FLAG_OCR_CANDIDATE,
    FLAG_OVEREXPOSED,
    GRID_H_DEFAULT,
    GRID_W_DEFAULT,
    MASK_BYTES_DEFAULT,
    RECORD_FIXED_SIZE,
    IndexFrameRecord,
    NonBlockingAsyncIndexer,
    TemporalEvidenceIndexReader,
    TemporalEvidenceIndexWriter,
)


def test_record_pack_unpack_roundtrip():
    # 21x30 random boolean masks
    rng = np.random.RandomState(42)
    change_mask = rng.rand(21, 30) > 0.8
    ui_mask = rng.rand(21, 30) > 0.9

    rec = IndexFrameRecord.from_masks(
        frame_id=1024,
        segment_id=7,
        pts_us=123_456_789,
        scene_version=3,
        quality_flags=FLAG_OCR_CANDIDATE | FLAG_OVEREXPOSED,
        global_motion=0.45,
        sharpness=128.5,
        edge_text=42.0,
        change_mask_bool=change_mask,
        ui_mask_bool=ui_mask,
        candidate_rois=[(100, 200, 50, 60, 0.92)],
    )

    packed = rec.pack()
    assert len(packed) == RECORD_FIXED_SIZE

    unpacked = IndexFrameRecord.unpack(packed)
    assert unpacked.frame_id == 1024
    assert unpacked.segment_id == 7
    assert unpacked.pts_us == 123_456_789
    assert unpacked.scene_version == 3
    assert unpacked.quality_flags == (FLAG_OCR_CANDIDATE | FLAG_OVEREXPOSED)
    assert abs(unpacked.global_motion_score - 0.45) < 0.01
    assert abs(unpacked.sharpness_score - 128.5) < 0.1
    assert abs(unpacked.edge_text_score - 42.0) < 0.1

    # Check masks
    rec_change = unpacked.unpack_change_mask((21, 30))
    np.testing.assert_array_equal(rec_change, change_mask)

    rec_ui = unpacked.unpack_ui_mask((21, 30))
    np.testing.assert_array_equal(rec_ui, ui_mask)

    # Check ROI
    assert len(unpacked.candidate_rois) == 1
    rx, ry, rw, rh, rc = unpacked.candidate_rois[0]
    assert (rx, ry, rw, rh) == (100, 200, 50, 60)
    assert abs(rc - 0.92) < 0.01


def test_record_crc_validation():
    rec = IndexFrameRecord.from_masks(
        frame_id=1, segment_id=1, pts_us=1000, sharpness=10.0
    )
    packed = bytearray(rec.pack())
    # Corrupt one byte inside payload
    packed[10] ^= 0xFF

    with pytest.raises(ValueError, match="CRC mismatch"):
        IndexFrameRecord.unpack(bytes(packed))


def test_segment_file_writer_and_reader():
    with tempfile.TemporaryDirectory() as tmp_dir:
        seg_path = Path(tmp_dir) / "seg_0001.jte"

        # Write 10 records
        with TemporalEvidenceIndexWriter(seg_path, segment_id=1, start_pts_us=1_000_000) as writer:
            for i in range(10):
                rec = IndexFrameRecord.from_masks(
                    frame_id=i,
                    segment_id=1,
                    pts_us=1_000_000 + i * 16_666,
                    sharpness=float(i * 10),
                )
                writer.write_record(rec)

        assert seg_path.is_file()

        # Read back
        reader = TemporalEvidenceIndexReader(seg_path)
        assert reader.segment_id == 1
        assert reader.start_pts_us == 1_000_000
        assert reader.grid_h == GRID_H_DEFAULT
        assert reader.grid_w == GRID_W_DEFAULT

        all_records = reader.read_all_records()
        assert len(all_records) == 10
        assert all_records[0].frame_id == 0
        assert all_records[9].frame_id == 9

        # Interval query
        mid_records = reader.query_interval(
            1_000_000 + 3 * 16_666, 1_000_000 + 6 * 16_666
        )
        assert len(mid_records) == 4
        assert [r.frame_id for r in mid_records] == [3, 4, 5, 6]


def test_crash_recovery_truncated_file():
    """Simulates an abrupt process crash where the final record was only partially written."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        seg_path = Path(tmp_dir) / "seg_crash.jte"

        with TemporalEvidenceIndexWriter(seg_path, segment_id=2, start_pts_us=2_000_000) as writer:
            for i in range(5):
                rec = IndexFrameRecord.from_masks(frame_id=i, segment_id=2, pts_us=2_000_000 + i * 16_666)
                writer.write_record(rec)

        # Append partial garbage (37 bytes of a 208-byte record)
        with open(seg_path, "ab") as fp:
            fp.write(b"PARTIAL_CRASH_GARBAGE_BYTES_01234567")

        reader = TemporalEvidenceIndexReader(seg_path)
        records = reader.read_all_records()
        # All 5 complete records should be recovered cleanly
        assert len(records) == 5
        assert reader.recovered_records == 5
        assert reader.corrupted_records >= 1


def test_non_blocking_async_indexer_drops_under_load():
    """Verifies that indexer queue does not block the caller when congested."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        seg_path = Path(tmp_dir) / "seg_async.jte"
        writer = TemporalEvidenceIndexWriter(seg_path, segment_id=3, start_pts_us=3_000_000)
        # Very small queue size = 4
        async_indexer = NonBlockingAsyncIndexer(writer, max_queue_size=4)
        async_indexer.start()

        # Submit 10 frames rapidly without sleeping
        accepted = 0
        dropped = 0
        for i in range(15):
            rec = IndexFrameRecord.from_masks(frame_id=i, segment_id=3, pts_us=3_000_000 + i * 16_666)
            if async_indexer.submit_frame(rec):
                accepted += 1
            else:
                dropped += 1

        # Stop and flush
        async_indexer.stop(timeout_s=2.0)

        assert accepted > 0
        # If queue backed up, dropped > 0 without throwing an exception or blocking
        reader = TemporalEvidenceIndexReader(seg_path)
        written = reader.read_all_records()
        assert len(written) == accepted
