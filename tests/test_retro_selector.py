# -*- coding: utf-8 -*-
"""Unit tests for RetrospectiveFrameSelector (Round 11, Step 1)."""

import json
from pathlib import Path
import numpy as np
import pytest

from jawl_voicecompanion.retro_selector import (
    FrameCandidate,
    FrameSelectionResult,
    RetrospectiveFrameSelector,
)

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "runtime" / "instances" / "retro_bench"
VIDEO_PATH = BENCH_DIR / "stimuli_60fps.mp4"
GT_PATH = BENCH_DIR / "retro_bench_ground_truth.json"


@pytest.fixture(scope="module")
def selector():
    return RetrospectiveFrameSelector(grid_shape=(21, 30))


@pytest.fixture(scope="module")
def sample_events():
    if not GT_PATH.is_file():
        pytest.skip("Benchmark GT not generated")
    data = json.loads(GT_PATH.read_text(encoding="utf-8"))
    return data["events"]


def test_selector_initialization(selector):
    assert selector.grid_h == 21
    assert selector.grid_w == 30
    assert selector.spatial_matrix is not None


def test_uniform_strategy_contract(selector, sample_events):
    if not VIDEO_PATH.is_file():
        pytest.skip("Stimuli video not found")

    ev = sample_events[0]
    res = selector.select_frames(
        video_path=VIDEO_PATH,
        start_ms=ev["start_ms"],
        end_ms=ev["start_ms"] + 3000.0,
        question=ev["question"],
        strategy="uniform",
        budget_frames=8,
    )

    assert isinstance(res, FrameSelectionResult)
    assert res.strategy == "uniform"
    assert res.budget == 8
    assert len(res.selected_frames) == 8
    assert res.target_status in ("observed_present", "not_found_in_sample")
    assert res.decode_ms > 0
    # Chronological order
    pts = res.pts_list_ms()
    assert pts == sorted(pts)


def test_spatial_strategy_contract(selector, sample_events):
    if not VIDEO_PATH.is_file():
        pytest.skip("Stimuli video not found")

    ev = sample_events[0]
    res = selector.select_frames(
        video_path=VIDEO_PATH,
        start_ms=ev["start_ms"],
        end_ms=ev["start_ms"] + 3000.0,
        question=ev["question"],
        strategy="spatial",
        budget_frames=8,
    )

    assert isinstance(res, FrameSelectionResult)
    assert res.strategy == "spatial"
    assert len(res.selected_frames) <= 8
    for f in res.selected_frames:
        assert "dirty_tiles" in f.features


def test_hybrid_adaptive_strategy_contract(selector, sample_events):
    if not VIDEO_PATH.is_file():
        pytest.skip("Stimuli video not found")

    ev = sample_events[1]  # T-Motion
    res = selector.select_frames(
        video_path=VIDEO_PATH,
        start_ms=max(0.0, ev["start_ms"] - 2000.0),
        end_ms=ev["start_ms"] + 3000.0,
        question=ev["question"],
        strategy="hybrid_adaptive",
        budget_frames=12,
    )

    assert isinstance(res, FrameSelectionResult)
    assert res.strategy == "hybrid_adaptive"
    assert len(res.selected_frames) <= 12
    assert res.detail_status in ("observed_readable", "observed_unreadable", "unknown")
    assert "expansion_mode" in res.metadata


def test_hybrid_adaptive_strict_subset_nesting(selector, sample_events):
    """Property test: S4 ⊂ S8 ⊂ S12 ⊂ S16 must hold strictly for any search window."""
    if not VIDEO_PATH.is_file():
        pytest.skip("Stimuli video not found")

    ev = sample_events[1]
    w_start = max(0.0, ev["start_ms"] - 1500.0)
    w_end = ev["start_ms"] + 2500.0

    res4 = selector.select_frames(
        video_path=VIDEO_PATH, start_ms=w_start, end_ms=w_end,
        question=ev["question"], strategy="hybrid_adaptive", budget_frames=4,
    )
    res8 = selector.select_frames(
        video_path=VIDEO_PATH, start_ms=w_start, end_ms=w_end,
        question=ev["question"], strategy="hybrid_adaptive", budget_frames=8,
    )
    res12 = selector.select_frames(
        video_path=VIDEO_PATH, start_ms=w_start, end_ms=w_end,
        question=ev["question"], strategy="hybrid_adaptive", budget_frames=12,
    )
    res16 = selector.select_frames(
        video_path=VIDEO_PATH, start_ms=w_start, end_ms=w_end,
        question=ev["question"], strategy="hybrid_adaptive", budget_frames=16,
    )

    s4 = set(res4.frame_indices())
    s8 = set(res8.frame_indices())
    s12 = set(res12.frame_indices())
    s16 = set(res16.frame_indices())

    assert len(s4) == 4
    assert len(s8) == 8
    assert len(s12) == 12
    assert len(s16) == 16

    # Strict subset hierarchy
    assert s4.issubset(s8), f"S4 is not a subset of S8: {s4 - s8}"
    assert s8.issubset(s12), f"S8 is not a subset of S12: {s8 - s12}"
    assert s12.issubset(s16), f"S12 is not a subset of S16: {s12 - s16}"


def test_oracle_strategy_contract(selector, sample_events):
    if not VIDEO_PATH.is_file():
        pytest.skip("Stimuli video not found")

    ev = sample_events[0]
    res = selector.select_frames(
        video_path=VIDEO_PATH,
        start_ms=ev["start_ms"],
        end_ms=ev["start_ms"] + ev["duration_ms"],
        question=ev["question"],
        strategy="oracle",
        budget_frames=1,
        oracle_gt=ev,
    )

    assert res.strategy == "oracle"
    assert len(res.selected_frames) == 1
    hit_f = res.selected_frames[0].frame_index
    assert ev["start_frame"] <= hit_f <= ev["end_frame"]
    assert res.target_status == "observed_present"
