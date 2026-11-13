"""Audit script for Step 1: verifies JTI1/JTE1 writers, frame index mapping, encoder drops,
and repair_and_finalize behavior on missing or truncated MP4.
"""
import json
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image

from jawl_voicecompanion.temporal_index import (
    IndexSegmentHeader,
    IndexFrameRecord,
    TemporalIndexWriter,
    TemporalIndexReader,
    repair_and_finalize,
    FLAG_VALID,
    FLAG_ENCODER_DROPPED,
)
from jawl_voicecompanion.live_evidence_archive import (
    SegmentWriter,
    EvidenceSegment,
    LiveEvidenceArchive,
)

def run_audit() -> dict:
    findings = {}

    # Audit Item 1: JTI1 vs JTE1 Writers
    # Check if any active code writes JTE1
    import inspect
    from jawl_voicecompanion import temporal_evidence_index
    findings["jte1_writer_exists_in_codebase"] = hasattr(temporal_evidence_index, "TemporalEvidenceIndexWriter")
    findings["live_evidence_archive_writer_format"] = "JTI1" # SegmentWriter uses TemporalIndexWriter

    # Audit Item 2: repair_and_finalize behavior with missing MP4 file
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        jti_p = tmp_p / "test_missing_mp4.jti"
        mp4_p = tmp_p / "test_missing_mp4.mp4" # does not exist

        hdr = IndexSegmentHeader(segment_id=1, source_width=1280, source_height=720)
        writer = TemporalIndexWriter(jti_p, hdr)
        writer.open()
        for i in range(5):
            rec = IndexFrameRecord(
                capture_qpc_us=1000000 + i * 16666,
                video_pts_us=1000000 + i * 16666,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            )
            writer.write_record(rec)
        writer.close()

        # Run repair_and_finalize with non-existent MP4
        res_missing_mp4 = repair_and_finalize(jti_p, mp4_p)
        findings["repair_with_missing_mp4"] = res_missing_mp4
        findings["defect_missing_mp4_accepted_as_valid"] = (
            res_missing_mp4.get("status") == "repaired" and
            res_missing_mp4.get("clean_closed") is True and
            res_missing_mp4.get("valid_records", 0) == 5
        )

    # Audit Item 3: repair_and_finalize behavior with truncated/corrupt 0-byte MP4 file
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        jti_p = tmp_p / "test_corrupt_mp4.jti"
        mp4_p = tmp_p / "test_corrupt_mp4.mp4"
        mp4_p.write_bytes(b"truncated_garbage_data")

        hdr = IndexSegmentHeader(segment_id=2, source_width=1280, source_height=720)
        writer = TemporalIndexWriter(jti_p, hdr)
        writer.open()
        for i in range(5):
            rec = IndexFrameRecord(
                capture_qpc_us=1000000 + i * 16666,
                video_pts_us=1000000 + i * 16666,
                capture_frame_id=i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            )
            writer.write_record(rec)
        writer.close()

        res_corrupt_mp4 = repair_and_finalize(jti_p, mp4_p)
        findings["repair_with_corrupt_mp4"] = res_corrupt_mp4
        findings["defect_corrupt_mp4_accepted_as_valid"] = (
            res_corrupt_mp4.get("status") == "repaired" and
            res_corrupt_mp4.get("clean_closed") is True and
            res_corrupt_mp4.get("valid_records", 0) == 5
        )

    # Audit Item 4: Frame extraction mapping when encoder dropped frames exist
    # If JTI has [0 (sample 0), 1 (sample 1), 2 (dropped, sample -1), 3 (sample 2)]
    # EvidenceSegment.extract_frames uses enumerate index instead of segment_sample_idx
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        writer = SegmentWriter(
            segment_id=3,
            output_dir=tmp_p,
            start_pts_us=1_000_000,
            fps=30.0,
            width=320,
            height=240,
        ).open()

        # Frame 0: normal
        rec0 = IndexFrameRecord(capture_qpc_us=1_000_000, video_pts_us=1_000_000, capture_frame_id=0, quality_flags=FLAG_VALID)
        writer.add_frame(np.full((240, 320, 3), 10, dtype=np.uint8), rec0)

        # Frame 1: normal
        rec1 = IndexFrameRecord(capture_qpc_us=1_033_333, video_pts_us=1_033_333, capture_frame_id=1, quality_flags=FLAG_VALID)
        writer.add_frame(np.full((240, 320, 3), 20, dtype=np.uint8), rec1)

        # Frame 2: DROPPED
        rec2 = IndexFrameRecord(capture_qpc_us=1_066_666, video_pts_us=-1, capture_frame_id=2, quality_flags=FLAG_VALID)
        writer.record_dropped_frame(rec2)

        # Frame 3: normal (encoded as sample 2)
        rec3 = IndexFrameRecord(capture_qpc_us=1_100_000, video_pts_us=1_100_000, capture_frame_id=3, quality_flags=FLAG_VALID)
        writer.add_frame(np.full((240, 320, 3), 40, dtype=np.uint8), rec3)

        seg = writer.close()

        # Test select_candidate_frames mapping
        archive = LiveEvidenceArchive(archive_dir=tmp_p, segment_duration_s=5.0)
        archive._segments = [seg]
        candidates = archive.select_candidate_frames(
            start_pts_us=1_000_000,
            end_pts_us=1_100_000,
            strategy="uniform",
            budget=4,
        )

        extracted_info = []
        for s, r, img in candidates:
            mean_val = float(np.mean(np.array(img))) if img is not None else None
            extracted_info.append({
                "capture_frame_id": r.capture_frame_id,
                "segment_sample_idx": r.segment_sample_idx,
                "img_is_none": img is None,
                "img_mean": mean_val,
            })
        findings["encoder_drop_extraction_test"] = extracted_info

        # Check if dropped frame received an image or if indices shifted
        # In frame 2 (dropped), did it get an image?
        dropped_got_image = any(item["capture_frame_id"] == 2 and not item["img_is_none"] for item in extracted_info)
        findings["defect_dropped_frame_received_image"] = dropped_got_image

    return findings

if __name__ == "__main__":
    report = run_audit()
    out_path = Path("runtime/audit_before.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Audit completed. Written to {out_path}")
    print(json.dumps(report, indent=2))
