"""Tests for DXGIScreenCapture, SceneDeltaDetector, and VisualStreamWorker."""

from __future__ import annotations

import time
import sys
import types
from unittest.mock import patch
from typing import Any
import numpy as np
from PIL import Image
import pytest

from jawl_voicecompanion.visual_stream import (
    DXGIScreenCapture,
    SceneDeltaDetector,
    VisualStreamWorker,
)


def test_scene_delta_detector_static_vs_dynamic() -> None:
    detector = SceneDeltaDetector(grid_size=32, change_threshold=0.10)
    
    # First frame establishes baseline
    f1 = np.zeros((100, 100, 3), dtype=np.uint8)
    delta1, change1, sid1 = detector.compute_delta(f1)
    assert delta1 == 1.0
    assert change1 is True
    assert sid1 == "scene_0"

    # Static identical frame
    f2 = np.zeros((100, 100, 3), dtype=np.uint8)
    delta2, change2, sid2 = detector.compute_delta(f2)
    assert delta2 == 0.0
    assert change2 is False
    assert sid2 == "scene_0"

    # Slightly different frame below threshold
    f3 = np.ones((100, 100, 3), dtype=np.uint8) * 10
    delta3, change3, sid3 = detector.compute_delta(f3)
    assert delta3 < 0.10
    assert change3 is False
    assert sid3 == "scene_0"

    # Major change above threshold
    f4 = np.ones((100, 100, 3), dtype=np.uint8) * 200
    delta4, change4, sid4 = detector.compute_delta(f4)
    assert delta4 >= 0.10
    assert change4 is True
    assert sid4 == "scene_1"


def test_visual_stream_worker_pipeline() -> None:
    class MockCapture:
        def __init__(self):
            self.frame = np.zeros((100, 100, 3), dtype=np.uint8)
            self.calls = 0

        def grab(self):
            self.calls += 1
            return self.frame

        def state(self):
            return {"mock": True, "calls": self.calls}

        def stop(self):
            pass

    class MockEpisodicMemory:
        def __init__(self):
            self.ingested = []

        def ingest_keyframe(self, image, scene_id, summary):
            self.ingested.append({"scene_id": scene_id, "summary": summary})
            return {"image_path": f"cache/{scene_id}.webp", "summary": summary}

    class MockConsolidator:
        def __init__(self):
            self.keyframes = []

        def feed_keyframe(self, scene_id, webp_path, summary, timestamp):
            self.keyframes.append({"scene_id": scene_id, "webp_path": webp_path})

    mock_cap = MockCapture()
    mock_mem = MockEpisodicMemory()
    mock_cons = MockConsolidator()

    worker = VisualStreamWorker(
        capture=mock_cap,
        episodic_memory=mock_mem,
        narrative_consolidator=mock_cons,
        poll_interval_s=0.05,
        min_ingest_interval_s=0.1,
    )

    worker.start()
    time.sleep(0.15)

    # First frame should trigger baseline scene_0
    assert len(mock_mem.ingested) == 1
    assert len(mock_cons.keyframes) == 1
    assert mock_mem.ingested[0]["scene_id"] == "scene_0"

    # Next frames static - should NOT trigger new ingestion
    time.sleep(0.15)
    assert len(mock_mem.ingested) == 1

    # Inject visual scene change
    mock_cap.frame = np.ones((100, 100, 3), dtype=np.uint8) * 255
    time.sleep(0.2)

    assert len(mock_mem.ingested) >= 2
    assert mock_mem.ingested[-1]["scene_id"] == "scene_1"
    assert len(mock_cons.keyframes) >= 2

    st = worker.state()
    assert st["running"] is True
    assert st["frames_checked"] > 2
    assert st["keyframes_ingested"] >= 2
    assert st["errors"] == 0

    worker.stop()
    assert worker.state()["running"] is False


def test_visual_stream_worker_fault_injection_resilience() -> None:
    class FailingCapture:
        def __init__(self):
            self.mode = "none"

        def grab(self):
            if self.mode == "none":
                return None
            if self.mode == "error":
                raise RuntimeError("DXGI device lost")
            return np.ones((50, 50, 3), dtype=np.uint8) * 128

        def stop(self):
            pass

    cap = FailingCapture()
    worker = VisualStreamWorker(capture=cap, poll_interval_s=0.05)
    worker.start()

    # Mode 1: grab returns None (e.g. screen sleep / minimized)
    time.sleep(0.1)
    assert worker.state()["running"] is True
    assert worker.state()["errors"] == 0

    # Mode 2: grab raises exception (e.g. DXGI surface reset)
    cap.mode = "error"
    time.sleep(0.15)
    assert worker.state()["running"] is True
    assert worker.state()["errors"] > 0
    assert "device lost" in worker.state()["last_error"]

    # Mode 3: recovery
    cap.mode = "normal"
    time.sleep(0.15)
    assert worker.state()["frames_checked"] > 0

    worker.stop()


def test_stream_consumes_redacted_adapter_frame_not_raw_screen() -> None:
    from PIL import ImageGrab
    from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter

    api = types.SimpleNamespace(EnumDisplayMonitors=lambda: [(1, None, (0, 0, 64, 64))])
    gui = types.SimpleNamespace(GetForegroundWindow=lambda: 0)
    adapter = ScreenCaptureAdapter(enabled=True, redaction_rects=[(0, 0, 16, 16)])
    stored = []

    class Memory:
        def ingest_keyframe(self, image, **_kwargs):
            stored.append(image.copy())
            return {}

    worker = VisualStreamWorker(capture=adapter, episodic_memory=Memory(), min_ingest_interval_s=0.01)
    with patch.dict(sys.modules, {"win32api": api, "win32gui": gui}), patch.object(
        ImageGrab, "grab", return_value=Image.new("RGB", (64, 64), (255, 0, 0))
    ):
        worker._poll_once(time.monotonic())
    assert len(stored) == 1
    assert stored[0].getpixel((8, 8)) == (0, 0, 0)
    assert stored[0].getpixel((32, 32)) == (255, 0, 0)


def test_stream_enable_failure_fails_closed_without_capture() -> None:
    class Capture:
        calls = 0
        def grab(self):
            self.calls += 1
            return np.zeros((8, 8, 3), dtype=np.uint8)

    def failed_policy():
        raise RuntimeError("policy unavailable")

    capture = Capture()
    worker = VisualStreamWorker(capture=capture, enabled_fn=failed_policy, poll_interval_s=0.01)
    worker.start()
    time.sleep(0.06)
    assert worker.get_latest_frame_with_timestamp() == (None, 0.0)
    worker.stop()
    assert capture.calls == 0


def test_stream_respects_adapter_sensitive_window_denial() -> None:
    from PIL import ImageGrab
    from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter

    api = types.SimpleNamespace(EnumDisplayMonitors=lambda: [(1, None, (0, 0, 64, 64))])
    gui = types.SimpleNamespace(
        GetForegroundWindow=lambda: 1, IsWindowVisible=lambda _hwnd: True,
        IsIconic=lambda _hwnd: False, GetWindowRect=lambda _hwnd: (0, 0, 64, 64),
        GetWindowText=lambda _hwnd: "Password manager", GetClassName=lambda _hwnd: "Window",
    )
    worker = VisualStreamWorker(capture=ScreenCaptureAdapter(enabled=True))
    with patch.dict(sys.modules, {"win32api": api, "win32gui": gui}), patch.object(ImageGrab, "grab") as grab:
        worker._poll_once(time.monotonic())
        grab.assert_not_called()
    assert worker.state()["frames_checked"] == 0


def test_stream_pause_during_capture_discards_frame_and_denial_has_no_stale_fallback() -> None:
    allowed = [True]

    class Capture:
        def grab_pil_with_timestamp(self, **_kwargs):
            allowed[0] = False
            return Image.new("RGB", (32, 32), "red"), time.monotonic()

    worker = VisualStreamWorker(capture=Capture(), enabled_fn=lambda: allowed[0])
    worker._poll_once(time.monotonic())
    assert worker.state()["frames_checked"] == 0
    assert worker._latest_frame_pil is None
    worker._running = True
    worker._latest_frame_pil = Image.new("RGB", (32, 32), "blue")
    allowed[0] = True
    assert worker.get_latest_frame_with_timestamp() == (None, 0.0)


def test_scene_delta_detector_localized_saliency_and_preflight() -> None:
    detector = SceneDeltaDetector(
        grid_size=64,
        change_threshold=0.12,
        saliency_cell_threshold=0.25,
        min_active_cells=2,
    )

    base = np.full((128, 128, 3), 50, dtype=np.uint8)
    d0, ch0, sid0 = detector.compute_delta(base, commit=True)
    assert ch0 is True
    assert sid0 == "scene_0"

    # Subtle localized change (e.g. 20x20 patch on 128x128)
    # Global MAE is ~0.018 (well below global 0.12 threshold), but localized saliency should trigger!
    patch_frame = base.copy()
    patch_frame[50:75, 50:75, :] = 240

    d1, ch1, sid1 = detector.compute_delta(patch_frame, commit=False)
    assert d1 < 0.05  # global delta is tiny
    assert ch1 is True  # but detected via localized saliency!
    assert detector.last_change_bbox is not None
    ymin, xmin, ymax, xmax = detector.last_change_bbox
    assert 0.35 <= ymin <= 0.65
    assert 0.35 <= xmin <= 0.65
    assert detector.last_saliency_delta > 0.5

    # Test pre-flight freshness verification
    assert detector.verify_preflight_freshness(base, tolerance=0.02) is True
    assert detector.verify_preflight_freshness(patch_frame, tolerance=0.001) is False


def test_foveated_vision_processor() -> None:
    from jawl_voicecompanion.visual_stream import FoveatedVisionProcessor

    processor = FoveatedVisionProcessor(coarse_resolution=(640, 360), foveal_crop_size=256)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[500:550, 800:850, :] = 255  # Distinct bright target

    # 1. Process with explicit focus point (e.g. mouse cursor)
    res = processor.process(frame, focus_point=(825, 525))
    assert res["coarse_img"].size == (640, 360)
    assert res["foveal_crop"].size == (256, 256)
    assert res["composite"].size == (640 + 256, 360)
    x0, y0, x1, y1 = res["crop_coords"]
    assert x0 <= 825 <= x1
    assert y0 <= 525 <= y1

    # 2. Process with saliency bounding box [ymin, xmin, ymax, xmax]
    res_bbox = processor.process(frame, saliency_bbox=[0.46, 0.41, 0.51, 0.45])
    assert res_bbox["foveal_crop"].size == (256, 256)


def test_storyboard_grid_assembler() -> None:
    from jawl_voicecompanion.visual_stream import StoryboardGridAssembler

    assembler = StoryboardGridAssembler(quadrant_size=128)
    assert assembler.ready is False
    assert assembler.assemble() is None

    # Add 4 frames
    for i in range(4):
        f = np.full((128, 128, 3), i * 60, dtype=np.uint8)
        assembler.add_keyframe(f, f"scene_{i}", time.monotonic())

    assert assembler.ready is True
    collage = assembler.assemble()
    assert collage is not None
    assert collage.size == (256, 256)  # 2 * 128

    assembler.clear()
    assert assembler.ready is False


def test_async_visual_ring_buffer() -> None:
    from jawl_voicecompanion.visual_stream import AsyncVisualRingBuffer

    ring = AsyncVisualRingBuffer(maxlen=3)
    frame = np.ones((50, 50, 3), dtype=np.uint8)

    # Push 5 frames into queue of maxlen 3
    for i in range(5):
        ring.push(frame, f"scene_{i}", delta=0.2)

    assert ring.dropped_frames == 2
    item = ring.pop_latest()
    assert item is not None
    assert item["scene_id"] == "scene_4"
    assert len(ring.queue) == 0
    assert ring.pop_latest() is None


