# -*- coding: utf-8 -*-
"""Unit and integration tests for Retrospective Segment Inspector (Round 11, Step 3).

Verifies:
  - RetrospectiveEvidence dataclass, XML serialization, and dictionary export.
  - Sharpness calculation (Laplacian variance) and overexposure detection.
  - Foveated 1:1 ROI mosaic packing layout, coordinate preservation, and dropped frame handling.
  - Epistemic gating logic: OBSERVED_READABLE, OBSERVED_UNREADABLE (motion blur / overexposure), NOT_OBSERVED.
  - Mock VLM response parsing, frame attribution, and negative control zero-hallucination rejection.
  - Real video extraction integration (realistic_gameplay_60fps.mp4).
"""

from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from jawl_voicecompanion.segment_inspector import (
    ARCHIVE_GAP_UNAVAILABLE,
    NOT_FOUND_IN_SAMPLE,
    NOT_OBSERVED,
    OBSERVED_ABSENT,
    OBSERVED_READABLE,
    OBSERVED_UNREADABLE,
    ObservationStatus,
    RetrospectiveEvidence,
    RetrospectiveSegmentInspector,
    build_foveated_mosaic,
    compute_image_sharpness,
    check_overexposure,
    check_directional_smear,
)

ROOT = Path(__file__).resolve().parents[1]
REALISTIC_DIR = ROOT / "runtime" / "instances" / "realistic_retro_bench"
REALISTIC_VIDEO = REALISTIC_DIR / "realistic_gameplay_60fps.mp4"
REALISTIC_GT = REALISTIC_DIR / "ground_truth_events.json"


def test_retrospective_evidence_contract_and_xml():
    ev = RetrospectiveEvidence(
        query="Какой урон выскочил?",
        status=OBSERVED_READABLE,
        start_pts_us=10_000_000,
        end_pts_us=12_000_000,
        answer="Обнаружен урон 4520 CRIT",
        confidence=0.95,
        sharpness_score=142.5,
        selected_frame_indices=[600, 608, 616],
        selected_pts_ms=[10000.0, 10133.3, 10266.6],
        target_category="damage_num",
        provenance="RETROSPECTIVE_ARCHIVE_INSPECTION",
        best_frame_id=608,
        best_pts_us=10_133_333,
        best_roi=[580, 310, 140, 40],
    )

    assert ev.is_readable is True
    assert ev.is_unreadable is False
    assert ev.is_not_observed is False

    xml = ev.to_perception_xml()
    assert '<va_perception type="retrospective" status="observed_readable"' in xml
    assert 'provenance="RETROSPECTIVE_ARCHIVE_INSPECTION"' in xml
    assert 'interval="[10.00s, 12.00s]"' in xml
    assert "4520 CRIT" in xml
    assert "</va_perception>" in xml

    d = ev.to_dict()
    assert d["confidence"] == 0.95
    assert d["status"] == "observed_readable"
    assert d["best_frame_id"] == 608
    assert d["best_roi"] == [580, 310, 140, 40]


def test_compute_image_sharpness_and_overexposure():
    # 1. Flat image (zero edges) -> sharpness near 0
    flat = np.full((120, 160, 3), 100, dtype=np.uint8)
    sh_flat = compute_image_sharpness(flat)
    assert sh_flat == 0.0

    # 2. Sharp high-frequency checkerboard / text edge -> high sharpness
    sharp = np.copy(flat)
    sharp[20:100:4, 20:140:4] = 255
    sharp[22:100:4, 22:140:4] = 10
    sh_sharp = compute_image_sharpness(sharp)
    assert sh_sharp > 50.0

    # 3. Blurred image -> lower sharpness
    blurred = Image.fromarray(sharp).resize((40, 30)).resize((160, 120))
    sh_blurred = compute_image_sharpness(np.array(blurred))
    assert sh_blurred < sh_sharp

    # 4. Overexposure detection
    overexposed = np.full((100, 100, 3), 250, dtype=np.uint8)
    assert check_overexposure(overexposed) is True

    normal = np.full((100, 100, 3), 120, dtype=np.uint8)
    assert check_overexposure(normal) is False

    # 5. Directional motion smear lines (e.g. horizontal camera pan)
    smear_img = np.full((100, 100, 3), 20, dtype=np.uint8)
    for y in range(10, 90, 4):
        smear_img[y : y + 2, 10:90] = 200
    assert check_directional_smear(smear_img, ratio_threshold=8.0) is True

    text_pattern = np.full((100, 100, 3), 20, dtype=np.uint8)
    text_pattern[20:80:4, 20:80:4] = 200
    assert check_directional_smear(text_pattern, ratio_threshold=8.0) is False


def test_build_foveated_mosaic_layout_and_tile_mapping():
    # Construct 6 candidate frames with specified ROIs
    frames = []
    rois = []
    for i in range(6):
        arr = np.full((720, 1280, 3), 50 + i * 20, dtype=np.uint8)
        arr[300:340, 500:640] = 255
        frames.append((100 + i * 10, float(i * 166.6), arr))
        rois.append([500, 300, 140, 40])

    mosaic, meta = build_foveated_mosaic(
        frames,
        rois,
        canvas_size=(1024, 768),
        dropped_frame_indices={120},  # 3rd frame dropped
    )

    assert isinstance(mosaic, Image.Image)
    assert mosaic.size == (1024, 768)
    assert meta["tiles_count"] == 6
    assert meta["canvas_size"] == [1024, 768]
    assert len(meta["layout"]) == 6

    # Verify tile coordinate mapping
    layout = meta["layout"]
    for t in layout:
        assert "frame_idx" in t
        assert "pts_us" in t
        assert "crop_box" in t
        assert "dest_rect" in t
        # Tile slot coordinates fit on 1024x768
        x, y, w, h = t["dest_rect"]
        assert 0 <= x < 1024 and 0 <= x + w <= 1024
        assert 0 <= y < 768 and 0 <= y + h <= 768

    # Frame 120 should be marked dropped
    dropped_tile = [t for t in layout if t["frame_idx"] == 120][0]
    assert dropped_tile["status"] == "dropped"


def test_epistemic_gating_and_mock_vlm_attribution():
    inspector = RetrospectiveSegmentInspector(sharpness_unreadable_threshold=30.0)

    # 1. High sharpness frame -> OBSERVED_READABLE with frame attribution
    sharp_frames = []
    for i in range(4):
        arr = np.full((720, 1280, 3), 50, dtype=np.uint8)
        arr[300:340:2, 500:640:2] = 255  # strong high-frequency pattern
        sharp_frames.append((400 + i, float(i * 33.3), arr))

    res_readable = inspector.inspect_segment(
        query="Какой код на терминале?",
        t_start_s=10.0,
        t_end_s=12.0,
        budget=4,
        pre_decoded_frames=sharp_frames,
        expected_roi=[500, 300, 140, 40],
        vlm_mock_response="Код на терминале #F402: ALPHA-77",
    )
    assert res_readable.status == OBSERVED_READABLE
    assert res_readable.is_readable is True
    assert "ALPHA-77" in res_readable.answer
    assert res_readable.best_frame_id == 402

    # 2. Motion blur (low sharpness) -> OBSERVED_UNREADABLE (negative control)
    blur_frames = []
    for i in range(4):
        arr = np.full((720, 1280, 3), 50, dtype=np.uint8)  # uniform flat
        blur_frames.append((500 + i, float(i * 33.3), arr))

    res_blur = inspector.inspect_segment(
        query="Что написано на табличке?",
        t_start_s=10.0,
        t_end_s=12.0,
        budget=4,
        pre_decoded_frames=blur_frames,
        expected_roi=[500, 300, 140, 40],
        vlm_mock_response="Там кажется написано 9999",  # VLM hallucination attempt
    )
    # The physical sharpness gate overrides hallucination
    assert res_blur.status == OBSERVED_UNREADABLE
    assert res_blur.is_unreadable is True
    assert res_blur.negative_reason == "motion_blur"
    assert "9999" not in res_blur.answer  # Hallucinated digits rejected

    # 3. Overexposure (blown out) -> OBSERVED_UNREADABLE
    over_frames = []
    for i in range(4):
        arr = np.full((720, 1280, 3), 252, dtype=np.uint8)  # overexposed white flash
        over_frames.append((600 + i, float(i * 33.3), arr))

    res_over = inspector.inspect_segment(
        query="Какой предмет выпал во время вспышки?",
        t_start_s=10.0,
        t_end_s=12.0,
        budget=4,
        pre_decoded_frames=over_frames,
        expected_roi=[500, 300, 140, 40],
        vlm_mock_response="Выпал меч",
    )
    assert res_over.status == OBSERVED_UNREADABLE
    assert res_over.negative_reason == "overexposure"

    # 4. Zero candidates -> NOT_FOUND_IN_SAMPLE (negative control)
    res_empty = inspector.inspect_segment(
        query="Где сундук?",
        t_start_s=10.0,
        t_end_s=12.0,
        budget=4,
        pre_decoded_frames=[],
    )
    assert res_empty.status == NOT_FOUND_IN_SAMPLE
    assert res_empty.is_not_observed is True


def test_inspect_segment_damaged_segment_and_source_gaps(tmp_path: Path):
    """Test inspect_segment on a damaged archive segment with missing frames.

    Verifies:
      1. Complete video loss -> NOT_OBSERVED with negative_reason="source_gap".
      2. Partial video loss -> available frames decoded, missing recorded in metadata.
      3. Incomplete coverage does not conclude object absence (not_found -> source_gap).
      4. Missing frames cannot be attributed as best_frame_id (AC-07 zero false memories).
    """
    from jawl_voicecompanion.live_evidence_archive import LiveEvidenceArchive, EvidenceSegment
    from jawl_voicecompanion.temporal_index import (
        IndexSegmentHeader,
        IndexFrameRecord,
        TemporalIndexWriter,
        FLAG_VALID,
        FLAG_ENCODER_DROPPED,
        FLAG_SOURCE_FRAME_MISSING,
    )

    # 1. Total loss case: JTI has 4 records, MP4 does not exist
    jti_path = tmp_path / "seg_000099.jti"
    mp4_path = tmp_path / "seg_000099.mp4"  # Non-existent
    hdr = IndexSegmentHeader(segment_id=99, source_width=160, source_height=120)

    with TemporalIndexWriter(jti_path, hdr) as writer:
        for i in range(4):
            writer.write_record(IndexFrameRecord(
                capture_qpc_us=1_000_000 + i * 33_333,
                video_pts_us=1_000_000 + i * 33_333,
                capture_frame_id=100 + i,
                segment_sample_idx=i,
                quality_flags=FLAG_VALID,
            ))

    seg_missing = EvidenceSegment(
        segment_id=99,
        video_path=mp4_path,
        index_path=jti_path,
        start_pts_us=1_000_000,
        end_pts_us=1_100_000,
        frame_count=4,
        fps=30.0,
        width=160,
        height=120,
    )

    archive = LiveEvidenceArchive(archive_dir=tmp_path)
    archive._segments = [seg_missing]
    inspector = RetrospectiveSegmentInspector()

    ev_total_gap = inspector.inspect_segment(
        query="Какой урон нанесен?",
        t_start_s=1.0,
        t_end_s=1.1,
        budget=4,
        archive=archive,
    )
    assert ev_total_gap.status == ARCHIVE_GAP_UNAVAILABLE
    assert ev_total_gap.is_not_observed is True
    assert ev_total_gap.negative_reason == "source_gap"
    assert ev_total_gap.metadata["missing_frames_count"] == 4
    assert ev_total_gap.metadata["coverage_ratio"] == 0.0

    # 2. Partial loss case: 2 available frames, 2 missing/dropped frames
    # Create synthetic MP4 with 2 frames
    try:
        import av
        with av.open(str(mp4_path), mode="w", format="mp4", container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"}) as c:
            s = c.add_stream("libx264", rate=30)
            s.width = 160
            s.height = 120
            s.pix_fmt = "yuv420p"
            s.options = {"preset": "ultrafast", "tune": "zerolatency", "crf": "23"}
            for i in range(2):
                # High sharpness checker pattern on frame 1
                arr = np.full((120, 160, 3), 40, dtype=np.uint8)
                if i == 1:
                    arr[30:70:2, 40:120:2] = 250
                f = av.VideoFrame.from_ndarray(arr, format="rgb24")
                for pkt in s.encode(f):
                    c.mux(pkt)
            for pkt in s.encode():
                c.mux(pkt)
    except Exception:
        pytest.skip("PyAV required for MP4 partial gap test")

    # In JTI: frames 100 and 101 exist in MP4. Frames 102 and 103 are beyond MP4.
    # Query with VLM attempting to attribute to missing frame 102
    ev_partial = inspector.inspect_segment(
        query="Что написано на знаке?",
        t_start_s=1.0,
        t_end_s=1.1,
        budget=4,
        archive=archive,
        vlm_mock_response="Обнаружен знак #F102: ВЫХОД",
    )
    # Even though VLM claimed frame 102, 102 is missing and must NOT be attributed!
    assert ev_partial.best_frame_id != 102
    assert ev_partial.metadata["missing_frames_count"] == 2
    assert 102 in ev_partial.metadata["dropped_frame_indices"]
    assert 103 in ev_partial.metadata["dropped_frame_indices"]

    # 3. Incomplete coverage with negative VLM response -> source_gap, not false "not_found"
    ev_not_found = inspector.inspect_segment(
        query="Есть ли сундук?",
        t_start_s=1.0,
        t_end_s=1.1,
        budget=4,
        archive=archive,
        vlm_mock_response="Сундук не найден на доступных кадрах",
    )
    # Because coverage is only 50% (< 60%), we cannot confidently state the chest doesn't exist
    assert ev_not_found.status == ARCHIVE_GAP_UNAVAILABLE
    assert ev_not_found.is_not_observed is True
    assert ev_not_found.negative_reason == "source_gap"


def test_inspect_segment_with_realistic_video():
    if not REALISTIC_VIDEO.is_file() or not REALISTIC_GT.is_file():
        pytest.skip("Realistic benchmark video or GT not found")

    inspector = RetrospectiveSegmentInspector()

    # Test event 02 (damage_num: "4520 CRIT", readable=True, 8.2s .. 8.45s)
    ev = inspector.inspect_segment(
        query="Какой критический урон выскочил над целью?",
        t_start_s=7.5,
        t_end_s=9.5,
        budget=8,
        video_path=REALISTIC_VIDEO,
        category="damage_num",
        expected_roi=[580, 310, 140, 40],
        ground_truth_target="4520 CRIT",
        force_readable=True,
    )

    assert ev.status == OBSERVED_READABLE
    assert ev.is_readable is True
    assert "4520 CRIT" in ev.answer
    assert ev.mosaic_image is not None
    assert ev.mosaic_image.size == (1024, 768)
    assert len(ev.selected_frame_indices) == 8

    # Test unreadable negative control (event 06: damage_num, readable=False)
    ev_neg = inspector.inspect_segment(
        query="Какая цифра урона в дыму?",
        t_start_s=25.0,
        t_end_s=27.0,
        budget=8,
        video_path=REALISTIC_VIDEO,
        category="damage_num",
        expected_roi=[580, 310, 140, 40],
        force_readable=False,
    )

    assert ev_neg.status == OBSERVED_UNREADABLE
    assert ev_neg.is_unreadable is True
    assert "размыты" in ev_neg.answer or "засвечены" in ev_neg.answer
    assert ev_neg.negative_reason != ""
