"""Unit tests for IncrementalSpatialMatrix (VLMCache / EP-ViT / STC-Cacher 2026)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from jawl_voicecompanion.visual_stream import (
    FoveatedVisionProcessor,
    IncrementalSpatialMatrix,
)


def test_incremental_spatial_matrix_init_and_keyframe() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64, keyframe_interval=10)
    assert ism.grid_h == 21
    assert ism.grid_w == 30
    assert ism.feature_dim == 64

    # 1. Initial frame -> forces keyframe, 100% tiles dirty
    f1 = np.ones((720, 1280, 3), dtype=np.uint8) * 128
    changed, dirty_cnt, bbox = ism.update(f1)
    assert changed is True
    assert dirty_cnt == 21 * 30  # 630 tiles
    assert bbox == [0.0, 0.0, 1.0, 1.0]

    matrix = ism.get_matrix()
    assert matrix.shape == (21, 30, 64)
    assert not np.all(matrix == 0.0)

    # 2. Check global embedding
    glob = ism.get_global_embedding()
    assert glob.shape == (64,)
    assert np.isclose(np.linalg.norm(glob), 1.0, atol=1e-3)


def test_incremental_spatial_matrix_static_cache_hit() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    f = np.ones((720, 1280, 3), dtype=np.uint8) * 100
    ism.update(f)

    # Static frame identical to baseline
    changed, dirty_cnt, bbox = ism.update(f)
    assert changed is False
    assert dirty_cnt == 0
    assert bbox is None
    assert ism.should_awaken_vlm(threshold=0.10) is False

    st = ism.state()
    assert st["last_dirty_count"] == 0
    assert st["cache_hit_rate_pct"] > 0.0


def test_incremental_spatial_matrix_localized_dirty_bbox() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    f1 = np.zeros((1080, 1920, 3), dtype=np.uint8)
    ism.update(f1)

    # Add a bright corner notification in top-right: rows 50..200, cols 1600..1900
    f2 = f1.copy()
    f2[50:200, 1600:1900, :] = 255
    changed, dirty_cnt, bbox = ism.update(f2)

    assert changed is True
    assert 0 < dirty_cnt < (21 * 30)  # Only a small fraction of tiles changed
    assert bbox is not None
    ymin, xmin, ymax, xmax = bbox
    # Must be located in upper-right quadrant
    assert ymin < 0.3
    assert ymax <= 0.35
    assert xmin > 0.75
    assert xmax <= 1.0


def test_incremental_spatial_matrix_hardware_dirty_rects() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    f = np.ones((1000, 1000, 3), dtype=np.uint8) * 50
    ism.update(f)

    # Explicit dirty rect: (x1=100, y1=100, x2=300, y2=400)
    dirty_rects = [(100, 100, 300, 400)]
    f_mod = f.copy()
    changed, dirty_cnt, bbox = ism.update(f_mod, dirty_rects=dirty_rects)

    assert changed is True
    assert dirty_cnt > 0
    assert dirty_cnt < 21 * 30
    assert bbox is not None
    ymin, xmin, ymax, xmax = bbox
    assert 0.05 <= ymin <= 0.20
    assert 0.05 <= xmin <= 0.20


def test_incremental_spatial_matrix_ep_vit_motion_compensation() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    f = np.ones((720, 1280, 3), dtype=np.uint8) * 80
    ism.update(f)
    orig_matrix = ism.get_matrix()

    # Simulate downward scrolling by 2 tiles
    exposed_cnt, exposed_bbox = ism.apply_motion(dy_tiles=2, dx_tiles=0)
    assert exposed_cnt == 2 * 30  # Exactly top 2 rows exposed
    assert exposed_bbox is not None
    assert exposed_bbox[0] == 0.0  # ymin at top
    assert np.isclose(exposed_bbox[2], 2.0 / 21.0, atol=1e-2)  # ymax = 2/21

    shifted_matrix = ism.get_matrix()
    # Rows 2..20 of shifted_matrix should match rows 0..18 of orig_matrix!
    np.testing.assert_allclose(shifted_matrix[2:], orig_matrix[:-2], atol=1e-5)


def test_incremental_spatial_matrix_synergy_with_foveated_vision() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    fovea = FoveatedVisionProcessor(coarse_resolution=(640, 360), foveal_crop_size=256)

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    ism.update(frame)

    # Localized text target in bottom-left
    frame_mod = frame.copy()
    frame_mod[800:900, 100:300, :] = 220
    changed, dirty_cnt, bbox = ism.update(frame_mod)

    assert changed is True
    assert bbox is not None

    # Pass bbox directly to FoveatedVisionProcessor
    fov_res = fovea.process(frame_mod, saliency_bbox=bbox)
    assert fov_res["coarse_img"].size == (640, 360)
    assert fov_res["foveal_crop"].size == (256, 256)
    x0, y0, x1, y1 = fov_res["crop_coords"]
    # Verify foveal crop encompasses the dirty region (cols 100..300, rows 800..900)
    assert x0 <= 200 <= x1
    assert y0 <= 850 <= y1


def test_incremental_spatial_matrix_spatial_zones() -> None:
    ism = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64)
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    ism.update(frame)

    zones = ism.get_spatial_zones()
    assert set(zones.keys()) == {"top", "bottom", "left", "right", "center"}
    for z_name, z_vec in zones.items():
        assert z_vec.shape == (64,)
        assert np.isclose(np.linalg.norm(z_vec), 1.0, atol=1e-3)
