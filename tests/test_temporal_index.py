"""Unit and integration tests for JAWL Temporal Evidence Index v1 (.jti).

Tests format invariants, CRC32C non-zero seed integrity, crash recovery,
bitflip detection, null-byte rejection, and truncation repairs.
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from jawl_voicecompanion.temporal_index import (
    CRC32_SEED,
    FLAG_CAPTURE_GAP,
    FLAG_ENCODER_DROPPED,
    FLAG_FEATURES_SKIPPED,
    FLAG_HEADER_CLEAN_CLOSED,
    FLAG_VALID,
    HEADER_SIZE_V1,
    MAGIC_V1,
    RECORD_SIZE_V1,
    ROI_KIND_OBJECT_DELTA,
    ROI_KIND_TEXT_LIKE,
    VERSION_V1,
    IndexFrameRecord,
    IndexROI,
    IndexSegmentHeader,
    TemporalIndexReader,
    TemporalIndexWriter,
    repair_and_finalize,
)


def test_header_pack_unpack_and_crc() -> None:
    header = IndexSegmentHeader(
        segment_id=42,
        source_width=2560,
        source_height=1440,
        qpc_freq_hz=10_000_000,
        first_capture_qpc_us=100_000_000,
        audio_start_qpc_us=100_000_050,
    )
    packed = header.pack()
    assert len(packed) == HEADER_SIZE_V1
    assert packed[:4] == MAGIC_V1

    unpacked = IndexSegmentHeader.unpack(packed)
    assert unpacked.segment_id == 42
    assert unpacked.source_width == 2560
    assert unpacked.source_height == 1440
    assert unpacked.first_capture_qpc_us == 100_000_000
    assert unpacked.audio_start_qpc_us == 100_000_050
    assert not unpacked.is_clean_closed

    # Test CRC corruption detection
    corrupted = bytearray(packed)
    corrupted[10] ^= 0xFF
    with pytest.raises(ValueError, match="Header CRC32 mismatch"):
        IndexSegmentHeader.unpack(bytes(corrupted))


def test_record_pack_unpack_roundtrip() -> None:
    # Create sample masks
    change_mask_arr = np.zeros((21, 30), dtype=bool)
    change_mask_arr[5, 10] = True
    change_mask_arr[20, 29] = True
    packed_change = IndexFrameRecord.from_bool_mask(change_mask_arr)

    ui_mask_arr = np.zeros((21, 30), dtype=bool)
    ui_mask_arr[0, :] = True  # Top HUD bar
    packed_ui = IndexFrameRecord.from_bool_mask(ui_mask_arr)

    rois = [
        IndexROI(x_px=100, y_px=200, w_px=300, h_px=50, score_q8=240, kind=ROI_KIND_TEXT_LIKE),
        IndexROI(x_px=640, y_px=360, w_px=80, h_px=80, score_q8=180, kind=ROI_KIND_OBJECT_DELTA),
    ]

    rec = IndexFrameRecord(
        capture_qpc_us=123456789,
        video_pts_us=123456000,
        capture_frame_id=1001,
        segment_sample_idx=45,
        scene_version=3,
        dirty_tile_count=2,
        quality_flags=FLAG_VALID,
        global_motion_score=1.25,
        sharpness_score=45.5,
        edge_text_score=8.75,
        mean_luma=128.0,
        local_change_mask=packed_change,
        ui_static_mask=packed_ui,
        candidate_rois=rois,
        audio_rms_q16=12000,
        vad_state_flags=1,
    )

    packed = rec.pack()
    assert len(packed) == RECORD_SIZE_V1

    unpacked = IndexFrameRecord.unpack(packed)
    assert unpacked.capture_qpc_us == 123456789
    assert unpacked.video_pts_us == 123456000
    assert unpacked.capture_frame_id == 1001
    assert unpacked.segment_sample_idx == 45
    assert unpacked.scene_version == 3
    assert unpacked.dirty_tile_count == 2
    assert unpacked.quality_flags == FLAG_VALID
    assert pytest.approx(unpacked.global_motion_score, 1e-4) == 1.25
    assert pytest.approx(unpacked.sharpness_score, 1e-4) == 45.5
    assert pytest.approx(unpacked.edge_text_score, 1e-4) == 8.75
    assert pytest.approx(unpacked.mean_luma, 1e-4) == 128.0
    assert unpacked.audio_rms_q16 == 12000
    assert unpacked.vad_state_flags == 1

    # Verify ROIs
    assert len(unpacked.candidate_rois) == 2
    assert unpacked.candidate_rois[0].as_tuple() == (100, 200, 300, 50, 240, ROI_KIND_TEXT_LIKE)
    assert unpacked.candidate_rois[1].as_tuple() == (640, 360, 80, 80, 180, ROI_KIND_OBJECT_DELTA)

    # Verify bitmask roundtrip
    restored_change = unpacked.unpack_local_change_mask()
    assert bool(restored_change[5, 10]) is True
    assert bool(restored_change[20, 29]) is True
    assert bool(restored_change[0, 0]) is False

    restored_ui = unpacked.unpack_ui_static_mask()
    assert np.all(restored_ui[0, :])
    assert not np.any(restored_ui[1:, :])


def test_null_bytes_and_bitflip_rejection() -> None:
    # 1. Null-bytes must fail CRC due to seed 0xA5A5A5A5
    null_record = b"\x00" * RECORD_SIZE_V1
    with pytest.raises(ValueError, match="Record CRC32 mismatch"):
        IndexFrameRecord.unpack(null_record)

    # 2. Bitflip in valid record must fail CRC
    rec = IndexFrameRecord(capture_qpc_us=1000)
    packed = bytearray(rec.pack())
    packed[50] ^= 0x01
    with pytest.raises(ValueError, match="Record CRC32 mismatch"):
        IndexFrameRecord.unpack(bytes(packed))


def test_writer_and_clean_close(tmp_path: Path) -> None:
    index_file = tmp_path / "test_seg_001.jti"
    header = IndexSegmentHeader(segment_id=1, source_width=1920, source_height=1080)

    writer = TemporalIndexWriter(index_file, header)
    writer.open()

    for i in range(10):
        rec = IndexFrameRecord(
            capture_qpc_us=1_000_000 + i * 16_666,
            video_pts_us=i * 16_666,
            capture_frame_id=i,
            segment_sample_idx=i,
        )
        writer.write_record(rec)

    writer.close()

    assert index_file.stat().st_size == HEADER_SIZE_V1 + 10 * RECORD_SIZE_V1

    reader = TemporalIndexReader(index_file)
    records = reader.read_all_records()

    assert reader.header is not None
    assert reader.header.is_clean_closed
    assert len(records) == 10
    assert reader.valid_records_count == 10
    assert reader.corrupted_records == 0
    assert not reader.is_truncated


def test_crash_recovery_truncated_tail_and_repair(tmp_path: Path) -> None:
    index_file = tmp_path / "crashed_seg.jti"
    header = IndexSegmentHeader(segment_id=2)

    with TemporalIndexWriter(index_file, header) as writer:
        for i in range(5):
            writer.write_record(IndexFrameRecord(capture_qpc_us=1000 + i * 100))

    # Simulate abrupt power crash during 6th record write (append 120 bytes of partial data)
    partial_bytes = b"\x42" * 120
    with open(index_file, "ab") as f:
        f.write(partial_bytes)

    expected_valid_size = HEADER_SIZE_V1 + 5 * RECORD_SIZE_V1
    assert index_file.stat().st_size == expected_valid_size + 120

    reader = TemporalIndexReader(index_file)
    records = reader.read_all_records()

    assert len(records) == 5
    assert reader.is_truncated is True
    assert reader.valid_bytes_offset == expected_valid_size

    # Repair and truncate
    truncated_bytes = reader.repair_and_truncate()
    assert truncated_bytes == 120
    assert index_file.stat().st_size == expected_valid_size

    # Re-read repaired file
    records_repaired = reader.read_all_records()
    assert len(records_repaired) == 5
    assert not reader.is_truncated


def test_non_monotonic_capture_qpc_recovery(tmp_path: Path) -> None:
    index_file = tmp_path / "non_monotonic.jti"
    header = IndexSegmentHeader(segment_id=3)

    with TemporalIndexWriter(index_file, header) as writer:
        writer.write_record(IndexFrameRecord(capture_qpc_us=1000))
        writer.write_record(IndexFrameRecord(capture_qpc_us=2000))
        # Non-monotonic jump backward
        writer.write_record(IndexFrameRecord(capture_qpc_us=1500))
        writer.write_record(IndexFrameRecord(capture_qpc_us=3000))

    reader = TemporalIndexReader(index_file)
    records = reader.read_all_records(stop_on_error=True)

    # Must stop at the jump backward
    assert len(records) == 2
    assert reader.corrupted_records == 1
    assert reader.valid_bytes_offset == HEADER_SIZE_V1 + 2 * RECORD_SIZE_V1


def test_encoder_dropped_and_features_skipped_flags(tmp_path: Path) -> None:
    index_file = tmp_path / "flags_test.jti"
    header = IndexSegmentHeader(segment_id=4)

    with TemporalIndexWriter(index_file, header) as writer:
        # Normal frame
        writer.write_record(IndexFrameRecord(capture_qpc_us=1000, segment_sample_idx=0))
        # Frame dropped by encoder
        writer.write_record(IndexFrameRecord(
            capture_qpc_us=2000,
            segment_sample_idx=-1,
            video_pts_us=-1,
            quality_flags=FLAG_VALID | FLAG_ENCODER_DROPPED,
        ))
        # Heavy load frame with features skipped
        writer.write_record(IndexFrameRecord(
            capture_qpc_us=3000,
            segment_sample_idx=1,
            quality_flags=FLAG_VALID | FLAG_FEATURES_SKIPPED,
        ))

    reader = TemporalIndexReader(index_file)
    records = reader.read_all_records()
    assert len(records) == 3
    assert records[1].segment_sample_idx == -1
    assert (records[1].quality_flags & FLAG_ENCODER_DROPPED) != 0
    assert (records[2].quality_flags & FLAG_FEATURES_SKIPPED) != 0


def test_synchronized_repair_and_finalize(tmp_path: Path) -> None:
    """Verify repair_and_finalize synchronizes JTI records with decodable MP4 frames."""
    jti_file = tmp_path / "sync_repair.jti"
    mp4_file = tmp_path / "sync_repair.mp4"
    header = IndexSegmentHeader(segment_id=7)

    # 1. Create a dummy fragmented MP4 with exactly 3 decodable frames
    try:
        import av
        with av.open(str(mp4_file), mode="w", format="mp4", container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"}) as c:
            s = c.add_stream("libx264", rate=30)
            s.width = 160
            s.height = 120
            s.pix_fmt = "yuv420p"
            for i in range(3):
                frame = av.VideoFrame.from_ndarray(np.full((120, 160, 3), i * 40, dtype=np.uint8), format="rgb24")
                for packet in s.encode(frame):
                    c.mux(packet)
            for packet in s.encode():
                c.mux(packet)
    except Exception:
        pytest.skip("PyAV / libx264 unavailable for MP4 test")

    # 2. Write 5 records to .jti (so 2 records reference non-existent MP4 frames 3 and 4)
    with TemporalIndexWriter(jti_file, header) as writer:
        for i in range(5):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=1000 + i * 1000,
                segment_sample_idx=i,
                video_pts_us=i * 33333,
            ))

    # 3. Append 85 bytes of partial garbage (crash truncation)
    with open(jti_file, "ab") as f:
        f.write(b"\xFE" * 85)

    # 4. Run synchronized repair
    res = repair_and_finalize(jti_file, mp4_file)

    assert res["status"] == "repaired"
    assert res["valid_records"] == 3
    assert res["truncated_records"] == 2
    assert res["clean_closed"] is True

    # 5. Verify index file contains exactly 3 records, clean closed, matching MP4 frames
    reader = TemporalIndexReader(jti_file)
    repaired_records = reader.read_all_records()
    assert len(repaired_records) == 3
    assert [r.segment_sample_idx for r in repaired_records] == [0, 1, 2]
    assert reader.header.header_flags & FLAG_HEADER_CLEAN_CLOSED != 0
    assert not reader.is_truncated
