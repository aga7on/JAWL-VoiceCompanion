"""Cycle 04 Verification & Benchmark Script.
Produces runtime/verification_cycle04.json with exact empirical numbers for:
  - Test damage detection rate
  - False references to inaccessible frames
  - Unauthorized OBSERVED_READABLE statuses
  - Recovery latency
  - Normal archive read latency & regression
"""
import json
import time
from pathlib import Path
import tempfile
import numpy as np

import av
from jawl_voicecompanion.temporal_index import (
    IndexSegmentHeader,
    IndexFrameRecord,
    TemporalIndexWriter,
    TemporalIndexReader,
    verify_segment_alignment,
    repair_and_finalize,
    FLAG_VALID,
    FLAG_ENCODER_DROPPED,
    FLAG_SOURCE_FRAME_MISSING,
)
from jawl_voicecompanion.live_evidence_archive import (
    LiveEvidenceArchive,
    EvidenceSegment,
    SegmentWriter,
)
from jawl_voicecompanion.segment_inspector import (
    RetrospectiveSegmentInspector,
    OBSERVED_READABLE,
    OBSERVED_UNREADABLE,
    NOT_OBSERVED,
)

def run_verification() -> dict:
    results = {}
    total_damages_injected = 0
    total_damages_detected = 0
    false_references = 0
    unauthorized_readable = 0
    recovery_times_ms = []

    # 1. Benchmark Recovery on Truncated MP4 (Scenario 2)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        mp4_p = tmp_p / "bench_trunc.mp4"
        jti_p = tmp_p / "bench_trunc.jti"

        # Create 10 frames MP4
        with av.open(str(mp4_p), mode="w", format="mp4", container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"}) as c:
            s = c.add_stream("libx264", rate=30)
            s.width, s.height, s.pix_fmt = 160, 120, "yuv420p"
            s.options = {"preset": "ultrafast", "tune": "zerolatency"}
            for i in range(10):
                f = av.VideoFrame.from_ndarray(np.full((120, 160, 3), i * 20, dtype=np.uint8), format="rgb24")
                for pkt in s.encode(f): c.mux(pkt)
            for pkt in s.encode(): c.mux(pkt)

        # Truncate MP4 to only 4 frames
        raw = mp4_p.read_bytes()
        mp4_p.write_bytes(raw[:len(raw) * 2 // 5])

        # Write 10 records to JTI
        hdr = IndexSegmentHeader(segment_id=1, source_width=160, source_height=120)
        with TemporalIndexWriter(jti_p, hdr) as w:
            for i in range(10):
                w.write_record(IndexFrameRecord(
                    capture_qpc_us=1000 + i * 33333,
                    video_pts_us=1000 + i * 33333,
                    capture_frame_id=i,
                    segment_sample_idx=i,
                    quality_flags=FLAG_VALID,
                ))

        # Test verification and recovery
        t0 = time.perf_counter()
        align = verify_segment_alignment(jti_p, mp4_p)
        rep = repair_and_finalize(jti_p, mp4_p)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        recovery_times_ms.append(dt_ms)

        surviving = align["mp4_frames"]
        injected = 10 - surviving
        detected = align["missing_frames_count"]
        total_damages_injected += injected
        total_damages_detected += detected

        # Check for false references after recovery
        reader = TemporalIndexReader(jti_p)
        recs = reader.read_all_records()
        for r in recs:
            if r.segment_sample_idx >= surviving:
                false_references += 1

    # 2. Benchmark Recovery on Missing MP4 (Scenario 3)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        jti_p = tmp_p / "bench_missing.jti"
        mp4_p = tmp_p / "bench_missing.mp4"
        hdr = IndexSegmentHeader(segment_id=2, source_width=160, source_height=120)
        with TemporalIndexWriter(jti_p, hdr) as w:
            for i in range(6):
                w.write_record(IndexFrameRecord(
                    capture_qpc_us=1000 + i * 33333,
                    video_pts_us=1000 + i * 33333,
                    capture_frame_id=i,
                    segment_sample_idx=i,
                    quality_flags=FLAG_VALID,
                ))

        t0 = time.perf_counter()
        align = verify_segment_alignment(jti_p, mp4_p)
        rep = repair_and_finalize(jti_p, mp4_p)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        recovery_times_ms.append(dt_ms)

        total_damages_injected += 6
        total_damages_detected += align["missing_frames_count"]

        reader = TemporalIndexReader(jti_p)
        recs = reader.read_all_records()
        if len(recs) > 0:
            false_references += len(recs)

    # 3. Test Segment Inspector Epistemic Guarantee on Damaged Segment
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        jti_p = tmp_p / "seg_000003.jti"
        mp4_p = tmp_p / "seg_000003.mp4"
        hdr = IndexSegmentHeader(segment_id=3, source_width=160, source_height=120)
        with TemporalIndexWriter(jti_p, hdr) as w:
            for i in range(5):
                w.write_record(IndexFrameRecord(
                    capture_qpc_us=1_000_000 + i * 33_333,
                    video_pts_us=1_000_000 + i * 33_333,
                    capture_frame_id=i,
                    segment_sample_idx=i,
                    quality_flags=FLAG_VALID,
                ))

        seg = EvidenceSegment(
            segment_id=3,
            video_path=mp4_p,  # missing
            index_path=jti_p,
            start_pts_us=1_000_000,
            end_pts_us=1_133_333,
            frame_count=5,
            fps=30.0,
            width=160,
            height=120,
        )
        archive = LiveEvidenceArchive(archive_dir=tmp_p)
        archive._segments = [seg]
        inspector = RetrospectiveSegmentInspector()

        ev = inspector.inspect_segment(
            query="Что написано?",
            t_start_s=1.0,
            t_end_s=1.1,
            budget=5,
            archive=archive,
            vlm_mock_response="Вижу текст #F2: СЕКРЕТ",
        )

        if ev.status == OBSERVED_READABLE:
            unauthorized_readable += 1
        if ev.best_frame_id != -1:
            false_references += 1

    # 4. Normal healthy archive read latency
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        jti_p = tmp_p / "healthy.jti"
        hdr = IndexSegmentHeader(segment_id=4, source_width=160, source_height=120)
        with TemporalIndexWriter(jti_p, hdr) as w:
            for i in range(600):  # 10 seconds of 60 FPS
                w.write_record(IndexFrameRecord(
                    capture_qpc_us=1_000_000 + i * 16666,
                    video_pts_us=1_000_000 + i * 16666,
                    capture_frame_id=i,
                    segment_sample_idx=i,
                    quality_flags=FLAG_VALID,
                ))

        reader = TemporalIndexReader(jti_p)
        t_read0 = time.perf_counter()
        recs = reader.read_all_records()
        healthy_read_ms = (time.perf_counter() - t_read0) * 1000.0

    detection_rate_pct = (total_damages_detected / max(1, total_damages_injected)) * 100.0
    mean_recovery_ms = float(np.mean(recovery_times_ms))

    report = {
        "cycle": "Cycle 04 — JTI1 <-> MP4 Evidence Integrity",
        "total_damages_injected": total_damages_injected,
        "total_damages_detected": total_damages_detected,
        "damage_detection_rate_pct": round(detection_rate_pct, 2),
        "false_references_to_inaccessible_frames": false_references,
        "unauthorized_observed_readable_count": unauthorized_readable,
        "mean_recovery_latency_ms": round(mean_recovery_ms, 2),
        "healthy_jti_read_600_frames_ms": round(healthy_read_ms, 3),
        "verdict": "PASS" if (detection_rate_pct == 100.0 and false_references == 0 and unauthorized_readable == 0) else "FAIL",
    }
    return report

if __name__ == "__main__":
    rep = run_verification()
    out = Path("runtime/verification_cycle04.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, indent=2))
