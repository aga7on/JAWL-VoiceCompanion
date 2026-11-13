# -*- coding: utf-8 -*-
"""Comprehensive Crash Recovery & Integrity Verification Tests for JTI1 <-> MP4 (Cycle 04).

Compliance:
  - AC-07 (truthful past reconstruction, zero false memories)
  - AC-08 (resilience and crash recovery)
  - AC-09 (controlled local storage)

Covers all 6 required failure topologies:
  1. Full MP4 + full JTI1 (healthy baseline)
  2. Full JTI1 + truncated MP4 (tail video data loss)
  3. Valid JTI1 + missing MP4 (complete video loss / unwritten file)
  4. MP4 with fewer decodable frames than JTI records
  5. Corrupt / truncated trailing JTI1 record (abrupt process termination)
  6. Encoder dropped frames with continuous capture_frame_id & PTS alignment

Guarantees:
  - 100% detection of inaccessible/corrupted frames
  - 0 false references to missing video samples
  - Missing frames flagged as FLAG_SOURCE_FRAME_MISSING
"""

from pathlib import Path
import struct
import numpy as np
import pytest
from PIL import Image

try:
    import av
    _HAS_PYAV = True
except ImportError:
    _HAS_PYAV = False

from jawl_voicecompanion.temporal_index import (
    FLAG_HEADER_CLEAN_CLOSED,
    FLAG_VALID,
    FLAG_ENCODER_DROPPED,
    FLAG_SOURCE_FRAME_MISSING,
    IndexSegmentHeader,
    IndexFrameRecord,
    TemporalIndexWriter,
    TemporalIndexReader,
    repair_and_finalize,
    verify_segment_alignment,
)
from jawl_voicecompanion.live_evidence_archive import (
    EvidenceSegment,
    LiveEvidenceArchive,
    SegmentWriter,
)


def _create_synthetic_mp4(
    path: Path,
    num_frames: int,
    fps: int = 30,
    width: int = 160,
    height: int = 120,
    start_pts_us: int = 1_000_000,
) -> list[int]:
    """Helper to create a valid fragmented MP4 file and return written PTS (us)."""
    if not _HAS_PYAV:
        pytest.skip("PyAV is required for MP4 tests")

    pts_us_list = []
    frame_dur_us = int(1_000_000 / fps)

    with av.open(
        str(path),
        mode="w",
        format="mp4",
        container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"},
    ) as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"preset": "ultrafast", "tune": "zerolatency", "crf": "23"}

        for i in range(num_frames):
            cur_pts = start_pts_us + i * frame_dur_us
            pts_us_list.append(cur_pts)
            # Distinct color per frame for content verification: red channel = (i + 1) * 20
            arr = np.full((height, width, 3), (i + 1) * 20, dtype=np.uint8)
            av_frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            av_frame.pts = i
            for packet in stream.encode(av_frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return pts_us_list


def test_scenario_1_full_mp4_full_jti(tmp_path: Path):
    """Scenario 1: Full MP4 + full JTI1. All frames match, 100% decodable, 0 errors."""
    mp4_path = tmp_path / "seg_000001.mp4"
    jti_path = tmp_path / "seg_000001.jti"
    n_frames = 6

    pts_list = _create_synthetic_mp4(mp4_path, num_frames=n_frames)

    hdr = IndexSegmentHeader(segment_id=1, source_width=160, source_height=120)
    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(n_frames):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=pts_list[i],
                video_pts_us=pts_list[i],
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    # Verify alignment
    alignment = verify_segment_alignment(jti_path, mp4_path)
    assert alignment["aligned"] is True
    assert alignment["mp4_frames"] == n_frames
    assert alignment["jti_records"] == n_frames
    assert alignment["missing_frames_count"] == 0
    assert len(alignment["inaccessible_sample_indices"]) == 0

    # Repair should confirm clean closed without any truncation
    res = repair_and_finalize(jti_path, mp4_path)
    assert res["status"] == "repaired"
    assert res["valid_records"] == n_frames
    assert res["truncated_records"] == 0
    assert res["clean_closed"] is True


def test_scenario_2_full_jti_truncated_mp4(tmp_path: Path):
    """Scenario 2: Full JTI1 (8 records) + truncated MP4 (only 3 frames survive)."""
    mp4_path = tmp_path / "seg_000002.mp4"
    jti_path = tmp_path / "seg_000002.jti"

    pts_list = _create_synthetic_mp4(mp4_path, num_frames=6)
    # Truncate MP4 file to 40% of its size (simulating sudden kill mid-recording)
    raw_mp4 = mp4_path.read_bytes()
    truncated_bytes = raw_mp4[: len(raw_mp4) * 2 // 5]
    mp4_path.write_bytes(truncated_bytes)

    hdr = IndexSegmentHeader(segment_id=2, source_width=160, source_height=120)
    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(8):
            qpc = 1_000_000 + i * 33_333
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=qpc,
                video_pts_us=qpc,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    alignment = verify_segment_alignment(jti_path, mp4_path)
    surviving_mp4_frames = alignment["mp4_frames"]
    assert surviving_mp4_frames < 8
    # 100% of inaccessible frames must be detected
    expected_inaccessible = 8 - surviving_mp4_frames
    assert alignment["missing_frames_count"] == expected_inaccessible
    assert len(alignment["inaccessible_sample_indices"]) == expected_inaccessible

    # Repair synchronizes JTI with surviving MP4 frames
    res = repair_and_finalize(jti_path, mp4_path)
    assert res["status"] == "repaired"
    assert res["valid_records"] == surviving_mp4_frames
    assert res["truncated_records"] == expected_inaccessible

    # Verify no false references exist
    reader = TemporalIndexReader(jti_path)
    repaired_records = reader.read_all_records()
    assert len(repaired_records) == surviving_mp4_frames
    for r in repaired_records:
        assert r.segment_sample_idx < surviving_mp4_frames


def test_scenario_3_valid_jti_missing_mp4(tmp_path: Path):
    """Scenario 3: Valid JTI1 with 5 records, but MP4 file is completely missing."""
    jti_path = tmp_path / "seg_000003.jti"
    mp4_path = tmp_path / "seg_000003.mp4"  # Does NOT exist

    hdr = IndexSegmentHeader(segment_id=3, source_width=160, source_height=120)
    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(5):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=1_000_000 + i * 33_333,
                video_pts_us=1_000_000 + i * 33_333,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    alignment = verify_segment_alignment(jti_path, mp4_path)
    assert alignment["aligned"] is False
    assert alignment["mp4_frames"] == 0
    assert alignment["missing_frames_count"] == 5
    assert alignment["inaccessible_sample_indices"] == [0, 1, 2, 3, 4]

    # Repair with missing MP4 must NOT declare all 5 records valid
    res = repair_and_finalize(jti_path, mp4_path)
    assert res["mp4_frames"] == 0
    assert res["valid_records"] == 0
    assert res["truncated_records"] == 5

    reader = TemporalIndexReader(jti_path)
    repaired_records = reader.read_all_records()
    assert len(repaired_records) == 0


def test_scenario_4_mp4_fewer_frames_than_jti(tmp_path: Path):
    """Scenario 4: MP4 has 3 decodable frames, JTI has 7 records (4 missing frames)."""
    mp4_path = tmp_path / "seg_000004.mp4"
    jti_path = tmp_path / "seg_000004.jti"

    pts_list = _create_synthetic_mp4(mp4_path, num_frames=3)

    hdr = IndexSegmentHeader(segment_id=4, source_width=160, source_height=120)
    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(7):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=1_000_000 + i * 33_333,
                video_pts_us=1_000_000 + i * 33_333,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    alignment = verify_segment_alignment(jti_path, mp4_path)
    assert alignment["mp4_frames"] == 3
    assert alignment["jti_records"] == 7
    assert alignment["missing_frames_count"] == 4
    assert alignment["inaccessible_sample_indices"] == [3, 4, 5, 6]

    res = repair_and_finalize(jti_path, mp4_path)
    assert res["valid_records"] == 3
    assert res["truncated_records"] == 4


def test_scenario_5_corrupt_truncated_jti_tail(tmp_path: Path):
    """Scenario 5: 4 valid records written, followed by 95 bytes of corrupted tail bytes."""
    jti_path = tmp_path / "seg_000005.jti"
    hdr = IndexSegmentHeader(segment_id=5, source_width=160, source_height=120)

    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(4):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=1_000_000 + i * 33_333,
                video_pts_us=1_000_000 + i * 33_333,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    # Append partial corrupt tail (crash during 5th frame write)
    with open(jti_path, "ab") as f:
        f.write(b"\xCC" * 95)

    reader = TemporalIndexReader(jti_path)
    records = reader.read_all_records()
    assert len(records) == 4
    assert reader.is_truncated is True

    # Repair truncates garbage and marks clean closed
    bytes_cut = reader.repair_and_truncate()
    assert bytes_cut == 95

    # Re-read confirmed clean
    reader2 = TemporalIndexReader(jti_path)
    records2 = reader2.read_all_records()
    assert len(records2) == 4
    assert reader2.header.header_flags & FLAG_HEADER_CLEAN_CLOSED != 0
    assert reader2.is_truncated is False


def test_scenario_6_encoder_dropped_frames_alignment_and_pts(tmp_path: Path):
    """Scenario 6: Live stream with encoder drop. Frame 2 dropped (sample_idx=-1).

    Verifies:
      - Continuous capture_frame_id: [0, 1, 2, 3, 4]
      - Sample mapping: Frame 0 -> 0, Frame 1 -> 1, Frame 2 -> -1 (dropped), Frame 3 -> 2, Frame 4 -> 3
      - Decoded frame PTS strictly matches capture_frame_id PTS, never desyncing.
      - Zero false references: dropped Frame 2 never receives sample 2's image.
    """
    writer = SegmentWriter(
        segment_id=6,
        output_dir=tmp_path,
        start_pts_us=1_000_000,
        fps=30.0,
        width=160,
        height=120,
    ).open()

    frames_rgb = []
    for i in range(5):
        # Color encoding: Red = (i + 1) * 30
        arr = np.full((120, 160, 3), (i + 1) * 30, dtype=np.uint8)
        frames_rgb.append(arr)

    # Frame 0: encoded
    rec0 = IndexFrameRecord(capture_qpc_us=1_000_000, video_pts_us=1_000_000, capture_frame_id=0, quality_flags=FLAG_VALID)
    writer.add_frame(frames_rgb[0], rec0)

    # Frame 1: encoded
    rec1 = IndexFrameRecord(capture_qpc_us=1_033_333, video_pts_us=1_033_333, capture_frame_id=1, quality_flags=FLAG_VALID)
    writer.add_frame(frames_rgb[1], rec1)

    # Frame 2: DROPPED BY ENCODER
    rec2 = IndexFrameRecord(capture_qpc_us=1_066_666, video_pts_us=-1, capture_frame_id=2, quality_flags=FLAG_VALID)
    writer.record_dropped_frame(rec2)

    # Frame 3: encoded (MP4 sample 2)
    rec3 = IndexFrameRecord(capture_qpc_us=1_100_000, video_pts_us=1_100_000, capture_frame_id=3, quality_flags=FLAG_VALID)
    writer.add_frame(frames_rgb[3], rec3)

    # Frame 4: encoded (MP4 sample 3)
    rec4 = IndexFrameRecord(capture_qpc_us=1_133_333, video_pts_us=1_133_333, capture_frame_id=4, quality_flags=FLAG_VALID)
    writer.add_frame(frames_rgb[4], rec4)

    seg = writer.close()

    # Verify sidecar records
    records = seg.read_records()
    assert len(records) == 5
    assert [r.segment_sample_idx for r in records] == [0, 1, -1, 2, 3]
    assert records[2].quality_flags & FLAG_ENCODER_DROPPED != 0

    # Test candidate frame extraction via archive
    archive = LiveEvidenceArchive(archive_dir=tmp_path, segment_duration_s=5.0)
    archive._segments = [seg]

    candidates = archive.select_candidate_frames(
        start_pts_us=1_000_000,
        end_pts_us=1_133_333,
        strategy="uniform",
        budget=5,
    )

    assert len(candidates) == 5
    cand_by_fid = {r.capture_frame_id: (r, img) for _, r, img in candidates}

    # Frame 0: image mean == 30
    r0, img0 = cand_by_fid[0]
    assert img0 is not None
    assert abs(np.mean(np.array(img0)) - 30.0) <= 2.0

    # Frame 1: image mean == 60
    r1, img1 = cand_by_fid[1]
    assert img1 is not None
    assert abs(np.mean(np.array(img1)) - 60.0) <= 2.0

    # Frame 2: DROPPED -> MUST BE NONE! Zero false reference!
    r2, img2 = cand_by_fid[2]
    assert img2 is None, "Dropped frame must never receive an image from a different frame"
    assert r2.segment_sample_idx == -1
    assert r2.quality_flags & FLAG_ENCODER_DROPPED != 0

    # Frame 3: image mean == 120 (Frame 3's real content, NOT shifted or None)
    r3, img3 = cand_by_fid[3]
    assert img3 is not None
    assert abs(np.mean(np.array(img3)) - 120.0) <= 2.0

    # Frame 4: image mean == 150
    r4, img4 = cand_by_fid[4]
    assert img4 is not None
    assert abs(np.mean(np.array(img4)) - 150.0) <= 2.0
