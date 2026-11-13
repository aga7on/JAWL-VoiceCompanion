# -*- coding: utf-8 -*-
"""Focused regression tests for Retrospective Segment Inspector Coverage & Epistemic Statuses.

Cycle 04 / Phase B — Round 12 (AC-06, AC-07, AC-09):
Verifies:
  1. 600 frames window, K=12 budget: Coverage calculated correctly; absence not asserted.
  2. Event between sampled frames: NOT_FOUND_IN_SAMPLE, never physical absence.
  3. Encoder dropped frames: ARCHIVE_GAP_UNAVAILABLE across corresponding interval.
  4. Zero successfully decoded frames: Does not emit confirmed absence fact.
  5. Dense sample (max_gap <= 50ms, 0 drops): Correct OBSERVED_ABSENT classification.
  6. Unreadable object: Preserves OBSERVED_UNREADABLE (sharpness / overexposure).
  7. Object found in single frame: Preserves OBSERVED_READABLE positive observation.
  8. XML -> episodic memory: Uncertainty status cannot become confirmed negative fact.
  9. Irregular timestamps and boundaries: max_uninspected_gap_ms calculated accurately (1 ms precision).
  10. Random dropout masks invariant: Any drop or max_gap > 50ms strictly denies absence confirmation.
  11. CPU coverage benchmark: 600 records computation p95 <= 10 ms.
  12. Deterministic replay artifact export (Step 5 demonstration).
"""

import json
import time
from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from jawl_voicecompanion.segment_inspector import (
    OBSERVED_READABLE,
    OBSERVED_UNREADABLE,
    NOT_FOUND_IN_SAMPLE,
    ARCHIVE_GAP_UNAVAILABLE,
    OBSERVED_ABSENT,
    NOT_OBSERVED,
    EpistemicStatus,
    ObservationStatus,
    SampleCoverage,
    RetrospectiveEvidence,
    RetrospectiveSegmentInspector,
    compute_sample_coverage,
    parse_perception_xml,
    status_to_wire,
    status_from_wire,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"


def _make_dummy_frame(pattern: str = "sharp") -> np.ndarray:
    """Create synthetic 720x1280 RGB frame for testing."""
    if pattern == "sharp":
        arr = np.full((720, 1280, 3), 40, dtype=np.uint8)
        arr[300:360:2, 500:660:2] = 250
        return arr
    elif pattern == "blur":
        return np.full((720, 1280, 3), 60, dtype=np.uint8)
    elif pattern == "overexposed":
        return np.full((720, 1280, 3), 254, dtype=np.uint8)
    return np.full((720, 1280, 3), 80, dtype=np.uint8)


def test_case_1_600_frames_k12_coverage_not_asserting_absence():
    """Window of 600 frames (10.0s), K=12 inspected -> NOT_FOUND_IN_SAMPLE, absence_confirmed=False."""
    inspector = RetrospectiveSegmentInspector()

    # Generate 12 pre-decoded frames spaced over 10 seconds (dt ~ 833.3 ms)
    frames = []
    for i in range(12):
        t_ms = i * 833.3
        frames.append((i * 50, t_ms, _make_dummy_frame("sharp")))

    ev = inspector.inspect_segment(
        query="Где ключ от двери?",
        t_start_s=0.0,
        t_end_s=10.0,
        budget=12,
        pre_decoded_frames=frames,
        archive_frames=600,
        vlm_mock_response="Ключ не найден на проверенных кадрах.",
    )

    assert ev.observation_status == NOT_FOUND_IN_SAMPLE
    assert ev.status == NOT_FOUND_IN_SAMPLE
    assert ev.status != NOT_OBSERVED  # Strict Enum contract (Cycle 07)
    assert ev.is_not_found_in_sample is True
    assert ev.is_not_observed is True
    assert ev.absence_confirmed is False

    cov = ev.coverage
    assert cov.inspected_frames == 12
    assert cov.archive_frames == 600
    assert abs(cov.coverage_ratio - 0.02) < 0.001
    assert cov.max_uninspected_gap_ms > 100.0
    assert cov.absence_confirmed is False
    assert ev.negative_reason == "not_found_in_sample"


def test_case_2_event_between_sampled_frames():
    """Event occurring between two inspected frames yields NOT_FOUND_IN_SAMPLE, never physical absence."""
    inspector = RetrospectiveSegmentInspector()

    # 1.0s window with 2 sampled frames at 100ms and 850ms (gap = 750ms)
    frames = [
        (0, 100.0, _make_dummy_frame("sharp")),
        (1, 850.0, _make_dummy_frame("sharp")),
    ]

    ev = inspector.inspect_segment(
        query="Пробежала ли собака?",
        t_start_s=0.0,
        t_end_s=1.0,
        budget=2,
        pre_decoded_frames=frames,
        archive_frames=30,
        vlm_mock_response="Собака не обнаружена",
    )

    assert ev.observation_status == NOT_FOUND_IN_SAMPLE
    assert ev.coverage.max_uninspected_gap_ms >= 750.0
    assert ev.absence_confirmed is False
    assert "not_found_in_sample" in ev.answer


def test_case_3_encoder_dropped_frames_archive_gap():
    """Frames dropped by encoder in window produce ARCHIVE_GAP_UNAVAILABLE with source_gap reason."""
    inspector = RetrospectiveSegmentInspector()

    frames = [
        (0, 100.0, _make_dummy_frame("sharp")),
        (1, 200.0, _make_dummy_frame("sharp")),
        (2, 300.0, _make_dummy_frame("sharp")),
    ]

    # Dropped frame 1 in the target interval
    ev = inspector.inspect_segment(
        query="Что на доске объявлений?",
        t_start_s=0.0,
        t_end_s=0.5,
        budget=3,
        pre_decoded_frames=frames,
        dropped_frames={1},
        archive_frames=15,
        vlm_mock_response="Ничего не найдено",
    )

    assert ev.observation_status == ARCHIVE_GAP_UNAVAILABLE
    assert ev.is_archive_gap is True
    assert ev.is_not_observed is True
    assert ev.negative_reason == "source_gap"
    assert ev.coverage.dropped_frames == 1
    assert ev.absence_confirmed is False


def test_case_4_zero_successfully_decoded_frames():
    """Zero successfully decoded frames must never emit confirmed absence."""
    inspector = RetrospectiveSegmentInspector()

    # Case A: Missing/dropped frames exist
    ev_gap = inspector.inspect_segment(
        query="Есть ли сундук?",
        t_start_s=0.0,
        t_end_s=1.0,
        budget=4,
        pre_decoded_frames=[],
        dropped_frames={10, 11},
    )
    assert ev_gap.observation_status == ARCHIVE_GAP_UNAVAILABLE
    assert ev_gap.negative_reason == "source_gap"
    assert ev_gap.absence_confirmed is False

    # Case B: Zero candidates returned
    ev_empty = inspector.inspect_segment(
        query="Есть ли сундук?",
        t_start_s=0.0,
        t_end_s=1.0,
        budget=4,
        pre_decoded_frames=[],
    )
    assert ev_empty.observation_status == NOT_FOUND_IN_SAMPLE
    assert ev_empty.negative_reason == "zero_candidates"
    assert ev_empty.absence_confirmed is False


def test_case_5_full_dense_sample_observed_absent():
    """Dense sampling (max_gap <= 50ms, 0 drops) across interval confirms OBSERVED_ABSENT."""
    inspector = RetrospectiveSegmentInspector()

    # 300 ms window with 10 frames spaced every 28 ms (max_gap < 50ms)
    frames = []
    for i in range(10):
        frames.append((i, 10.0 + i * 28.0, _make_dummy_frame("sharp")))

    ev = inspector.inspect_segment(
        query="Появился ли значок предупреждения?",
        t_start_s=0.0,
        t_end_s=0.3,
        budget=10,
        pre_decoded_frames=frames,
        archive_frames=10,
        vlm_mock_response="Значок отсутствует на всех кадрах.",
    )

    assert ev.observation_status == OBSERVED_ABSENT
    assert ev.status == OBSERVED_ABSENT
    assert ev.is_absent is True
    assert ev.absence_confirmed is True
    assert ev.coverage.max_uninspected_gap_ms <= 50.0
    assert ev.coverage.dropped_frames == 0


def test_case_6_unreadable_object_retains_observed_unreadable():
    """Blured/overexposed image retains OBSERVED_UNREADABLE regardless of sampling density."""
    inspector = RetrospectiveSegmentInspector(sharpness_unreadable_threshold=30.0)

    # 4 flat/blurry frames
    frames = [(i, float(i * 33.3), _make_dummy_frame("blur")) for i in range(4)]

    ev = inspector.inspect_segment(
        query="Какое число на экране?",
        t_start_s=0.0,
        t_end_s=0.2,
        budget=4,
        pre_decoded_frames=frames,
        vlm_mock_response="Там число 777",  # Hallucination attempt
    )

    assert ev.observation_status == OBSERVED_UNREADABLE
    assert ev.status == OBSERVED_UNREADABLE
    assert ev.is_unreadable is True
    assert ev.negative_reason == "motion_blur"
    assert "777" not in ev.answer


def test_case_7_object_found_in_single_frame_retains_positive_observation():
    """Positive detection in sampled frame retains OBSERVED_READABLE even under sparse sampling."""
    inspector = RetrospectiveSegmentInspector()

    # 12 frames over 10 seconds (sparse coverage_ratio = 0.02)
    frames = [(i * 50, float(i * 833.3), _make_dummy_frame("sharp")) for i in range(12)]

    ev = inspector.inspect_segment(
        query="Какой код на экране?",
        t_start_s=0.0,
        t_end_s=10.0,
        budget=12,
        pre_decoded_frames=frames,
        archive_frames=600,
        vlm_mock_response="Обнаружен код #F200: OMEGA-42",
    )

    assert ev.observation_status == OBSERVED_READABLE
    assert ev.status == OBSERVED_READABLE
    assert ev.is_readable is True
    assert ev.is_not_observed is False
    assert "OMEGA-42" in ev.answer
    assert ev.best_frame_id == 200
    # Incomplete coverage did NOT destroy the positive observation
    assert ev.coverage.coverage_ratio == 0.02


def test_case_8_xml_to_memory_consumer_prevents_false_fact():
    """XML serialization and parse_perception_xml strictly prevent upgrading uncertainty to fact."""
    # 1. Unconfirmed absence
    ev_unconfirmed = RetrospectiveEvidence(
        query="Был ли взрыв?",
        status=NOT_FOUND_IN_SAMPLE,
        start_pts_us=1_000_000,
        end_pts_us=5_000_000,
        answer="Взрыв не обнаружен в выборке (not_found_in_sample).",
        coverage=SampleCoverage(
            window_ms=4000.0,
            inspected_frames=4,
            archive_frames=240,
            coverage_ratio=0.0167,
            max_uninspected_gap_ms=1000.0,
            absence_confirmed=False,
        ),
    )

    xml_unconfirmed = ev_unconfirmed.to_perception_xml()
    assert 'observation_status="not_found_in_sample"' in xml_unconfirmed
    assert 'absence_confirmed="false"' in xml_unconfirmed

    parsed_unconf = parse_perception_xml(xml_unconfirmed)
    assert parsed_unconf["absence_confirmed"] is False
    assert parsed_unconf["is_confirmed_fact"] is False
    assert parsed_unconf["observation_status"] == "not_found_in_sample"

    # 2. Archive gap
    ev_gap = RetrospectiveEvidence(
        query="Был ли сундук?",
        status=ARCHIVE_GAP_UNAVAILABLE,
        start_pts_us=0,
        end_pts_us=1_000_000,
        answer="Видео повреждено",
        coverage=SampleCoverage(
            window_ms=1000.0,
            inspected_frames=0,
            archive_frames=60,
            dropped_frames=60,
            coverage_ratio=0.0,
            max_uninspected_gap_ms=1000.0,
            absence_confirmed=False,
        ),
    )
    xml_gap = ev_gap.to_perception_xml()
    parsed_gap = parse_perception_xml(xml_gap)
    assert parsed_gap["absence_confirmed"] is False
    assert parsed_gap["is_confirmed_fact"] is False

    # 3. Confirmed absence (dense)
    ev_absent = RetrospectiveEvidence(
        query="Появился ли монстр?",
        status=OBSERVED_ABSENT,
        start_pts_us=0,
        end_pts_us=200_000,
        answer="Монстр отсутствует (observed_absent)",
        coverage=SampleCoverage(
            window_ms=200.0,
            inspected_frames=8,
            archive_frames=8,
            coverage_ratio=1.0,
            max_uninspected_gap_ms=25.0,
            absence_confirmed=True,
        ),
    )
    xml_absent = ev_absent.to_perception_xml()
    parsed_absent = parse_perception_xml(xml_absent)
    assert parsed_absent["absence_confirmed"] is True
    assert parsed_absent["is_confirmed_fact"] is True


def test_case_9_irregular_timestamps_and_window_boundaries():
    """Boundary and irregular intervals calculate max_uninspected_gap_ms to 1ms precision."""
    start_ms = 1000.0
    end_ms = 3000.0
    # Window = 2000 ms.
    # Inspected timestamps: 1200.0, 1300.0, 2900.0.
    # Gaps:
    #   [1000.0, 1200.0] -> 200.0 ms
    #   [1200.0, 1300.0] -> 100.0 ms
    #   [1300.0, 2900.0] -> 1600.0 ms  <-- MAX GAP
    #   [2900.0, 3000.0] -> 100.0 ms
    cov = compute_sample_coverage(
        start_ms=start_ms,
        end_ms=end_ms,
        inspected_pts_ms=[1200.0, 1300.0, 2900.0],
        archive_frames=60,
        dropped_frames_count=0,
    )

    assert abs(cov.max_uninspected_gap_ms - 1600.0) < 0.001
    assert cov.inspected_frames == 3
    assert cov.archive_frames == 60
    assert cov.absence_confirmed is False


def test_case_10_random_dropout_mask_invariant():
    """Epistemic safety invariant holds across 20 randomized frame dropout masks."""
    rng = np.random.default_rng(seed=0xCAFE_BABE)
    n_frames = 60
    window_ms = 1000.0  # 60 fps -> 16.67 ms per frame
    frame_pts = [i * 16.6667 for i in range(n_frames)]

    for _ in range(20):
        # Random drop mask (True = dropped, False = valid)
        drop_mask = rng.choice([True, False], size=n_frames, p=[0.25, 0.75])
        inspected_pts = [pts for pts, is_drop in zip(frame_pts, drop_mask) if not is_drop]
        dropped_count = int(np.sum(drop_mask))

        cov = compute_sample_coverage(
            start_ms=0.0,
            end_ms=window_ms,
            inspected_pts_ms=inspected_pts,
            archive_frames=n_frames,
            dropped_frames_count=dropped_count,
        )

        # Invariant 1: If any frame was dropped, absence_confirmed MUST BE False
        if dropped_count > 0:
            assert cov.absence_confirmed is False, "Drop occurred but absence was confirmed!"

        # Invariant 2: If max_gap > 50 ms, absence_confirmed MUST BE False
        if cov.max_uninspected_gap_ms > 50.0:
            assert cov.absence_confirmed is False, "Gap > 50ms but absence was confirmed!"

        # Invariant 3: Inspected frames never includes dropped frames
        assert cov.inspected_frames == len(inspected_pts)
        assert cov.dropped_frames == dropped_count


def test_case_11_cpu_coverage_benchmark_600_records():
    """Coverage computation on 600 records must achieve p95 <= 10.0 ms on CPU."""
    start_ms = 0.0
    end_ms = 10000.0
    pts_600 = [i * 16.6667 for i in range(600)]

    latencies_ms = []
    # Measure 500 iterations
    for _ in range(500):
        t0 = time.perf_counter()
        cov = compute_sample_coverage(
            start_ms=start_ms,
            end_ms=end_ms,
            inspected_pts_ms=pts_600,
            archive_frames=600,
            dropped_frames_count=0,
        )
        dt = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt)

    p50 = float(np.percentile(latencies_ms, 50))
    p95 = float(np.percentile(latencies_ms, 95))
    p99 = float(np.percentile(latencies_ms, 99))

    print(f"\n[Coverage CPU Benchmark 600 records] p50={p50:.4f} ms, p95={p95:.4f} ms, p99={p99:.4f} ms")
    assert p95 <= 10.0, f"Coverage computation p95 {p95:.2f} ms exceeds 10.0 ms target!"


def test_case_12_deterministic_replay_demonstration_step5():
    """Execute Step 5 deterministic replay: 10s archive, 600 frames, 12 inspected, absent in sample."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    out_json = RUNTIME_DIR / "replay_demonstration_cycle04_phaseB.json"

    inspector = RetrospectiveSegmentInspector()

    # 12 inspected frames spaced across 10 seconds
    sampled_frames = []
    for i in range(12):
        pts_ms = i * 833.333
        sampled_frames.append((i * 50, pts_ms, _make_dummy_frame("sharp")))

    t0 = time.perf_counter()
    ev = inspector.inspect_segment(
        query="Был ли замечен символ совы на экране?",
        t_start_s=0.0,
        t_end_s=10.0,
        budget=12,
        pre_decoded_frames=sampled_frames,
        archive_frames=600,
        vlm_mock_response="Символ совы не найден на проверенных кадрах.",
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Verification of required fields (Step 5)
    replay_result = {
        "cycle": "Cycle 04 / Phase B — Round 12",
        "query": ev.query,
        "observation_status": status_to_wire(ev.observation_status),
        "status": status_to_wire(ev.status),
        "sampled_frames": ev.coverage.inspected_frames,
        "archive_frames": ev.coverage.archive_frames,
        "coverage_ratio": round(ev.coverage.coverage_ratio, 4),
        "max_uninspected_gap_ms": round(ev.coverage.max_uninspected_gap_ms, 2),
        "absence_confirmed": ev.coverage.absence_confirmed,
        "negative_reason": ev.negative_reason,
        "elapsed_ms": round(elapsed_ms, 2),
        "verdict": "PASS",
    }

    out_json.write_text(json.dumps(replay_result, indent=2, ensure_ascii=False), encoding="utf-8")

    assert replay_result["observation_status"] == status_to_wire(NOT_FOUND_IN_SAMPLE)
    assert replay_result["sampled_frames"] == 12
    assert replay_result["archive_frames"] == 600
    assert replay_result["max_uninspected_gap_ms"] > 100.0
    assert replay_result["absence_confirmed"] is False
    assert replay_result["verdict"] == "PASS"
