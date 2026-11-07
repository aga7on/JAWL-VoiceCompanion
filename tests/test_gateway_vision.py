"""Tests for Top-Down Visual Perception, Epistemic Provenance, and Gateway Intent (Step 2.6)."""

import time
from typing import Any
from unittest.mock import MagicMock
from PIL import Image
import numpy as np
import pytest

from jawl_voicecompanion.event_policy import EventPolicy
from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.perception_fusion import PerceptionFusion
from jawl_voicecompanion.scene_state import EpistemicObservationState, SceneState


def _make_dummy_frame(color=(128, 128, 128)) -> Image.Image:
    arr = np.full((120, 160, 3), color, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


class DummyCapture:
    def __init__(self, frame=None, capture_time=None):
        self._frame = frame if frame is not None else _make_dummy_frame()
        self._last_frame_time = capture_time if capture_time is not None else time.monotonic()

    def grab_pil(self, max_dimension=None):
        return self._frame

    def grab_pil_with_timestamp(self, max_dimension=None):
        return self._frame, self._last_frame_time


class DummyVisualWorker:
    def __init__(self, capture=None):
        self.capture = capture or DummyCapture()

    def get_latest_frame_with_timestamp(self, max_dimension=None):
        return self.capture.grab_pil_with_timestamp(max_dimension=max_dimension)


class DummyDescriber:
    def __init__(self, response_text="Девушка в белой блузке сидит за столом"):
        self.response_text = response_text
        self.last_prompt = ""
        self.call_count = 0

    def describe(self, prompt: str, observation: dict[str, Any]) -> str:
        self.last_prompt = prompt
        self.call_count += 1
        return self.response_text


def test_visual_intent_detection():
    policy = EventPolicy()

    # Visual queries
    assert policy.is_visual_query("Что сейчас на экране?") is True
    assert policy.is_visual_query("Посмотри на задний план") is True
    assert policy.is_visual_query("Во что она одета?") is True
    assert policy.is_visual_query("Кто сидит в кадре?") is True
    assert policy.is_visual_query("look at the background") is True

    # Non-visual queries
    assert policy.is_visual_query("Который час?") is False
    assert policy.is_visual_query("Привет, как твои дела?") is False
    assert policy.is_visual_query("Напиши функцию на питоне") is False
    assert policy.is_visual_query("покажи редактор") is False
    assert policy.is_visual_query("покажи, что на экране") is True

    # Target and region extraction
    target_bg, region_bg = policy.extract_visual_target("Посмотри на задний план")
    assert "задний план" in target_bg
    assert region_bg == "background"

    target_attire, region_attire = policy.extract_visual_target("Во что она одета?")
    assert "одежда" in target_attire
    assert region_attire == "attire"


def test_top_down_vision_fresh_look_present():
    """Verify that a positive visual detection preserves capture timestamp and updates SceneState."""
    t_cap = time.monotonic() - 0.250  # Captured 250ms ago
    capture = DummyCapture(capture_time=t_cap)
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Девушка в темной куртке пьет кофе")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Кто в кадре?", target="персонажи в кадре", region="foreground")

    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT
    assert obs["captured_at"] == t_cap
    assert obs["semantic_age_ms"] >= 200.0  # Accounts for capture age
    assert "куртке" in obs["details"]
    assert obs["needs_visual_refresh"] is False

    # Verify unlocalized presence and inspection in SceneState
    assert len(scene_state.unlocalized_presences) == 1
    assert "куртке" in scene_state.unlocalized_presences[0]["traits"]["appearance"]
    assert len(scene_state.active_inspections) == 1
    assert scene_state.active_inspections[0]["verified_absent"] is False


def test_top_down_vision_bounded_absence():
    """Verify that absent detection records bounded negative observation (not absolute ontologic absence)."""
    t_cap = time.monotonic() - 0.100
    capture = DummyCapture(capture_time=t_cap)
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="В коридоре никого нет, курьер отсутствует")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Курьер в коридоре?", target="курьер", region="corridor")

    assert obs["status"] == EpistemicObservationState.OBSERVED_ABSENT
    assert obs["captured_at"] == t_cap
    assert obs["inspection_quality"] >= 0.70
    assert "not detected" in obs["reason"]
    assert "bounded quality" in obs["reason"]

    # Verify that SceneState records the inspection record
    assert len(scene_state.active_inspections) == 1
    insp = scene_state.active_inspections[0]
    assert insp["target"] == "курьер"
    assert insp["region"] == "corridor"
    assert insp["verified_absent"] is True
    assert insp["inspection_quality"] >= 0.70


def test_top_down_vision_low_quality_degrades_to_not_observed():
    """Vague or low-quality negative inspection (<0.70) must safely degrade to NOT_OBSERVED."""
    t_cap = time.monotonic()
    capture = DummyCapture(capture_time=t_cap)
    worker = DummyVisualWorker(capture=capture)
    # Very short / error-like response yielding low quality
    describer = DummyDescriber(response_text="нет")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Есть ли курьер?", target="курьер")

    # Degrades to not_observed because quality < 0.70
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["needs_visual_refresh"] is True
    assert "too low" in obs["reason"]


def test_top_down_vision_failure_fallback_to_not_observed():
    """When capture or describer fails/times out, result MUST be explicit NOT_OBSERVED (no hallucination)."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)

    class FailingDescriber:
        def describe(self, prompt, observation):
            raise TimeoutError("Qwen VL server timed out after 3.0s")

    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)
    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=FailingDescriber(),
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Что на экране?", target="full_frame")

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["needs_visual_refresh"] is True
    assert "failed or timed out" in obs["reason"]
    assert "TimeoutError" in obs["reason"]


def test_gateway_orchestrates_top_down_vision_and_informs_responder():
    """End-to-end: Gateway identifies visual query, performs top-down look, and passes epistemic context."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Красная чашка стоит справа на столе")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)
    policy = EventPolicy()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    received_prompts = []

    def mock_responder(prompt: str) -> str:
        received_prompts.append(prompt)
        assert "[EPISTEMIC SCENE OBSERVATION]" in prompt
        assert "Status: observed_present" in prompt
        assert "Красная чашка" in prompt
        return "Я вижу красную чашку на столе справа."

    gateway = TextGateway(
        responder=mock_responder,
        event_policy=policy,
        perception_fusion=fusion,
        scene_state=scene_state,
    )

    response = gateway.handle_text("Что на экране?")

    assert len(received_prompts) == 1
    assert "Я вижу красную чашку" in response["text"]
    assert response["speak"] is True
    assert describer.call_count == 1


def test_gateway_not_observed_instructs_responder_not_to_hallucinate():
    """When visual observation fails, responder receives explicit NOT_OBSERVED instruction."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)

    class BrokenDescriber:
        def describe(self, prompt, observation):
            raise ConnectionError("Qwen port 8994 offline")

    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)
    policy = EventPolicy()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=BrokenDescriber(),
        scene_state=scene_state,
    )

    received_prompts = []

    def honest_responder(prompt: str) -> str:
        received_prompts.append(prompt)
        assert "[EPISTEMIC SCENE OBSERVATION]" in prompt
        assert "Status: not_observed" in prompt
        assert "NEVER invent" in prompt
        return "К сожалению, изображение сейчас недоступно, и я не могу увидеть, что на экране."

    gateway = TextGateway(
        responder=honest_responder,
        event_policy=policy,
        perception_fusion=fusion,
        scene_state=scene_state,
    )

    response = gateway.handle_text("Посмотри на экран, кто там?")

    assert len(received_prompts) == 1
    assert "не могу увидеть" in response["text"]


def test_uncertain_vlm_response_degrades_to_not_observed():
    """Hedging or uncertainty in VLM response must NOT be treated as verified fact."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Я не уверен, что изображено на снимке, возможно человек.")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Кто в кадре?", target="человек")

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["inspection_quality"] <= 0.45
    assert "uncertain" in obs["reason"]
    # Verify fusion channel does not mark it verified
    item = fusion.current_state("top_down_vision")
    assert item is not None
    assert item.get("metadata", {}).get("verified") is False


def test_pre_inference_staleness_rejection():
    """Frames captured beyond max_staleness_ms must be immediately rejected without VLM call."""
    t_stale = time.monotonic() - 15.0  # Captured 15 seconds ago
    capture = DummyCapture(capture_time=t_stale)
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Текст на экране")
    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Что на экране?", target="экран", max_staleness_ms=4000.0)

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["source"] == "stale_frame"
    assert "stale" in obs["reason"]
    assert obs["details"] == ""
    assert describer.call_count == 0  # No wasted VLM call


def test_post_inference_staleness_rejection():
    """If inference takes longer than freshness TTL, observation must expire."""
    t_cap = time.monotonic() - 0.8
    capture = DummyCapture(capture_time=t_cap)
    worker = DummyVisualWorker(capture=capture)

    class SlowDescriber:
        def describe(self, prompt, obs):
            time.sleep(0.3)
            return "Объект на столе"

    scene_state = SceneState(timestamp_ms=time.monotonic() * 1000.0)
    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=SlowDescriber(),
        scene_state=scene_state,
    )

    # Max staleness set to 900ms, while capture age + 300ms sleep > 1000ms
    obs = fusion.fetch_top_down_observation("Что на столе?", target="стол", max_staleness_ms=900.0)

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "expired" in obs["reason"]


def test_scene_change_during_inference_invalidates_observation():
    """Scene transition during VLM call must invalidate observation for current scene."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    scene_state = SceneState(scene_id="scene_intro", timestamp_ms=time.monotonic() * 1000.0)

    class SceneChangingDescriber:
        def describe(self, prompt, obs):
            # Simulate external event transitioning scene during inference
            scene_state.transition_scene("scene_gameplay")
            return "Игрок бежит по коридору"

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=SceneChangingDescriber(),
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Что происходит?", target="сцена")

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "Scene changed" in obs["reason"]
    assert "scene_intro" in obs["reason"]
    assert "scene_gameplay" in obs["reason"]


def test_timeout_enforcement_aborts_hanging_describer():
    """Strict timeout enforcement must abort hanging describer and release execution."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)

    class HangingDescriber:
        def describe(self, prompt, obs):
            time.sleep(0.35)
            return "Слишком поздний ответ"

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=HangingDescriber(),
        scene_state=SceneState(),
    )

    t0 = time.monotonic()
    obs = fusion.fetch_top_down_observation("Что на экране?", timeout_s=0.06)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.20  # Must not wait 0.35s
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "timed out" in obs["reason"]


def test_user_turn_cancellation_aborts_observation():
    """Cancellation event must immediately abort visual inspection and return NOT_OBSERVED."""
    import threading

    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    cancel_evt = threading.Event()

    class CancellableDescriber:
        def describe(self, prompt, obs):
            time.sleep(0.3)
            return "Ответ"

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=CancellableDescriber(),
        scene_state=SceneState(),
    )

    # Cancel after 30ms
    timer = threading.Timer(0.03, cancel_evt.set)
    timer.start()

    t0 = time.monotonic()
    obs = fusion.fetch_top_down_observation("Что на экране?", timeout_s=1.0, cancel_event=cancel_evt)
    elapsed = time.monotonic() - t0
    timer.join()

    assert elapsed < 0.20
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "cancelled" in obs["reason"]


def test_sensory_disabled_or_paused_returns_no_frame_and_no_fallback():
    """When sensory is disabled/paused, worker returns no frame and fusion does not create rogue capture."""
    from jawl_voicecompanion.visual_stream import VisualStreamWorker

    is_enabled = False
    worker = VisualStreamWorker(
        capture=DummyCapture(),
        enabled_fn=lambda: is_enabled,
    )
    worker.start()

    try:
        frame, t_cap = worker.get_latest_frame_with_timestamp()
        assert frame is None
        assert t_cap == 0.0

        fusion = PerceptionFusion(
            visual_stream_worker=worker,
            vision_describer=DummyDescriber(),
            scene_state=SceneState(),
        )

        obs = fusion.fetch_top_down_observation("Что на экране?")
        assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
        assert obs["source"] == "capture_unavailable"
    finally:
        worker.stop()


def test_describer_source_and_model_tracked_accurately():
    """Vision source name and model must be accurately tracked (no confusing EG2 with Qwen)."""
    from jawl_voicecompanion.eg2_describer import Eg2VisionDescriber

    class MockDetailedDescriber:
        def describe_screen_detailed(self, image_bytes, prompt=""):
            class Obs:
                description = "Рабочий стол Windows"
            return Obs()

    eg2_describer = Eg2VisionDescriber(MockDetailedDescriber())
    scene_state = SceneState()
    fusion = PerceptionFusion(
        visual_stream_worker=DummyVisualWorker(),
        vision_describer=eg2_describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Что видно?", target="окно")

    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT
    assert obs["source"] == "embeddinggemma-2"
    assert len(scene_state.active_inspections) == 1
    assert scene_state.active_inspections[0]["source"] == "embeddinggemma-2"


def test_unrelated_negative_response_not_attributed_to_target():
    """Unrelated negative statement (e.g. 'не ем яблоки' for target 'курьер') must degrade to NOT_OBSERVED."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Я не ем яблоки и не пью кофе.")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Курьер в коридоре?", target="курьер", region="corridor")

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "not clearly confirm" in obs["reason"] or "unverified" in obs["reason"]


def test_bounded_admission_queue_saturation_and_recovery():
    """Executor capacity=2: saturated permits immediately drop with describer_busy; recovered pool accepts work."""
    import threading

    block_event = threading.Event()
    active_count = 0
    active_lock = threading.Lock()

    class BlockingDescriber:
        def describe(self, prompt, obs):
            nonlocal active_count
            with active_lock:
                active_count += 1
            block_event.wait(timeout=3.0)
            return "Объект на месте"

    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=BlockingDescriber(),
        scene_state=SceneState(),
    )

    t1 = threading.Thread(target=lambda: fusion.fetch_top_down_observation("q1", timeout_s=4.0))
    t2 = threading.Thread(target=lambda: fusion.fetch_top_down_observation("q2", timeout_s=4.0))
    t1.start()
    t2.start()

    time.sleep(0.05)
    with active_lock:
        assert active_count == 2

    # 3rd and 4th callers should immediately fail with describer_busy without queueing
    obs3 = fusion.fetch_top_down_observation("q3", timeout_s=1.0)
    assert obs3["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "busy" in obs3["reason"]

    obs4 = fusion.fetch_top_down_observation("q4", timeout_s=1.0)
    assert obs4["status"] == EpistemicObservationState.NOT_OBSERVED
    assert "busy" in obs4["reason"]

    # Release blocked workers
    block_event.set()
    t1.join()
    t2.join()

    # Recovery: 5th caller now succeeds
    fusion.vision_describer = DummyDescriber(response_text="Объект на месте")
    obs5 = fusion.fetch_top_down_observation("Что на экране?", timeout_s=1.0)
    assert obs5["status"] == EpistemicObservationState.OBSERVED_PRESENT


def test_screen_capture_adapter_reuse_and_pause():
    """ScreenCaptureAdapter is reused when visual_stream_worker is absent, and respects user pause."""
    paused = False

    class MockScreenCaptureAdapter:
        def __init__(self):
            self.enabled = True
            self.display_index = 1
            self.enabled_fn = lambda: not paused
            self._frame = _make_dummy_frame()

        def grab_pil_with_timestamp(self, max_dimension=None):
            if not self.enabled or not self.enabled_fn():
                return None, 0.0
            return self._frame, time.monotonic()

    cap = MockScreenCaptureAdapter()
    fusion = PerceptionFusion(
        visual_stream_worker=None,
        vision_describer=DummyDescriber(response_text="Кнопка ОК видна"),
        scene_state=SceneState(),
    )
    fusion.screen_capture = cap

    # Active capture
    obs = fusion.fetch_top_down_observation("Где кнопка?")
    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT

    # User pauses sensory capture
    paused = True
    obs_paused = fusion.fetch_top_down_observation("Где кнопка?")
    assert obs_paused["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs_paused["source"] == "capture_unavailable"


def test_composition_wiring_qwen_vs_eg2_isolation():
    """When visual_describer is qwen without url, it must not secretly fall back to eg2."""
    from jawl_voicecompanion.eg2_describer import Eg2VisionDescriber

    class MockDetailedDescriber:
        def describe_screen_detailed(self, image_bytes, prompt=""):
            class Obs:
                description = "EG2 описание"
            return Obs()

    eg2_obj = Eg2VisionDescriber(MockDetailedDescriber())
    fusion = PerceptionFusion(
        visual_stream_worker=DummyVisualWorker(),
        scene_state=SceneState(),
    )
    # When vision_describer is unconfigured (None), it must NOT use perception_fusion.describer fallback
    fusion.describer = MockDetailedDescriber()
    fusion.vision_describer = None

    obs = fusion.fetch_top_down_observation("Что на экране?")
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["source"] == "not_configured"
    assert "not configured" in obs["reason"]


def test_scene_transition_propagation_worker_to_gateway():
    """VisualStreamWorker delta detector transitions canonical SceneState, which degrades in-flight inspection."""
    scene_state = SceneState(scene_id="scene_0")
    assert scene_state.scene_version == 0

    # Simulate mid-inspection scene change
    class SlowDescriber:
        def describe(self, prompt, obs):
            # Worker commits scene change while describer is running
            scene_state.transition_scene("scene_1")
            return "Окно браузера открыто"

    fusion = PerceptionFusion(
        visual_stream_worker=DummyVisualWorker(),
        vision_describer=SlowDescriber(),
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Что на экране?")
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["source"] == "scene_changed"
    assert "Scene changed" in obs["reason"] and "during" in obs["reason"]
    assert scene_state.scene_version == 1
    assert scene_state.scene_id == "scene_1"


def test_gateway_enrich_visual_context_cancellation():
    """Cancel event during top-down visual inspection cleanly cancels without hanging or leaks."""
    import threading

    cancel_evt = threading.Event()
    block_evt = threading.Event()

    class CancellableDescriber:
        def describe(self, prompt, obs, cancel_event=None):
            block_evt.set()
            # Describer waits until cancelled
            for _ in range(50):
                if cancel_event is not None and cancel_event.is_set():
                    break
                time.sleep(0.01)
            return "Старый ответ"

    gateway = TextGateway(policy=None)
    scene_state = SceneState()
    fusion = PerceptionFusion(
        visual_stream_worker=DummyVisualWorker(),
        vision_describer=CancellableDescriber(),
        scene_state=scene_state,
    )
    gateway.perception_fusion = fusion
    gateway.scene_state = scene_state

    # Cancel while in-flight
    def _cancel_after_start():
        block_evt.wait(timeout=2.0)
        cancel_evt.set()

    t = threading.Thread(target=_cancel_after_start)
    t.start()

    text, obs = gateway._enrich_visual_context(
        "Что видно на экране?", cancel_event=cancel_evt
    )
    t.join()

    assert obs is not None
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["source"] == "cancelled" or "cancelled" in obs.get("reason", "").lower()


@pytest.mark.parametrize("method_name", ["describe", "look"])
@pytest.mark.parametrize("error_type", [TypeError, TimeoutError])
def test_visual_inspection_does_not_retry_internal_errors(method_name, error_type):
    """A failing model call must not be repeated without its cancellation token."""
    import threading

    calls = []

    def fail(*args, cancel_event=None):
        calls.append(cancel_event)
        raise error_type("internal model failure")

    class Describer:
        pass

    describer = Describer()
    setattr(describer, method_name, fail)
    fusion = PerceptionFusion(
        visual_stream_worker=DummyVisualWorker(),
        vision_describer=describer,
    )
    cancelled = threading.Event()
    obs = fusion.fetch_top_down_observation(
        "Что видно на экране?", target="экран", cancel_event=cancelled
    )
    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert calls == [cancelled]


def test_on_demand_screen_change_invalidates_inflight_observation():
    """The default capture path must not present a previous scene as current."""
    import threading

    started, release = threading.Event(), threading.Event()

    class Capture:
        color = "black"

        def grab_pil_with_timestamp(self, max_dimension=None):
            return Image.new("RGB", (32, 32), self.color), time.monotonic()

    class Describer:
        def describe(self, prompt, observation):
            started.set()
            assert release.wait(2)
            return "A person is sitting at a table."

    capture = Capture()
    fusion = PerceptionFusion(scene_state=SceneState(), vision_describer=Describer())
    fusion.screen_capture = capture
    result = {}
    thread = threading.Thread(
        target=lambda: result.update(fusion.fetch_top_down_observation(
            "What is visible?", target="person", timeout_s=1.5
        ))
    )
    thread.start()
    try:
        assert started.wait(2)
        capture.color = "white"
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert result["status"] == EpistemicObservationState.NOT_OBSERVED
    assert result["source"] == "scene_changed"


def test_screen_capture_adapter_decoupled_from_ambient_memory():
    """Disabling ambient memory (--ambient-memory=False) must NOT disable screen capture or perception."""
    from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
    from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter

    ambient_mem = AmbientMemoryBuffer(enabled=False)
    assert ambient_mem.enabled is False
    assert ambient_mem.paused is False

    # Simulate composition wiring: screen capture enabled_fn checks paused, not memory buffer enabled
    adapter = ScreenCaptureAdapter(
        enabled=True,
        enabled_fn=lambda: not getattr(ambient_mem, "paused", False),
    )

    # Frame capture allowed even with memory disabled
    if hasattr(adapter, "enabled_fn"):
        assert adapter.enabled_fn() is True

    # When user explicitly pauses, capture is revoked
    ambient_mem.paused = True
    assert adapter.enabled_fn() is False


def test_qwen_visual_sensor_transitions_canonical_scene_state():
    """QwenVisualSensor detecting a scene transition must advance canonical SceneState version and ID."""
    from jawl_voicecompanion.qwen_visual_sensor import QwenVisualSensor

    scene_state = SceneState(scene_id="scene-init")
    assert scene_state.scene_version == 0

    class DummyQwenDescriber:
        def submit(self, *args, **kwargs):
            return True

    class DummyFusion:
        scene_state = None
        def note(self, *args, **kwargs):
            pass
        def invalidate(self, *args, **kwargs):
            pass

    fusion = DummyFusion()
    sensor = QwenVisualSensor(
        screen_capture=DummyCapture(),
        describer=DummyQwenDescriber(),
        fusion=fusion,
        scene_state=scene_state,
    )
    assert sensor._scene_id == "scene-init"

    # Simulate scene change detection in sensor
    sensor._scene_counter += 1
    sensor._scene_id = f"scene-{sensor._scene_counter}"
    sc = sensor.scene_state
    sc.transition_scene(sensor._scene_id)

    assert scene_state.scene_version == 1
    assert scene_state.scene_id == "scene-2"


def test_epistemic_calibration_marks_unverified_hypothesis():
    """VLM top-down visual output is a hypothesis: marked verified=False, hypothesis=True, with calibrated confidence."""
    t_cap = time.monotonic()
    capture = DummyCapture(capture_time=t_cap)
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="На столе стоит белая чашка с горячим чаем")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation("Есть ли чашка на столе?", target="чашка на столе", region="table")

    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT
    assert obs["verified"] is False
    assert obs["hypothesis"] is True
    assert obs["provenance"]["verified"] is False
    assert obs["provenance"]["hypothesis"] is True
    assert "чашка" in obs["details"]
    # Calibrated confidence: not blindly 0.85
    assert 0.50 <= obs["inspection_quality"] <= 0.80


def test_open_query_bare_absence_answer_is_not_observed():
    """Regression (independent test): open query 'что сейчас видно на экране?' with target
    'содержимое экрана' answered by a bare 'Отсутствует' must NOT become observed_absent
    with quality 0.7: a non-informative negative is not a proof of whole-scene absence."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Отсутствует")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Что сейчас видно на экране?", target="содержимое экрана", region="full_frame"
    )

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["inspection_quality"] == 0.0
    assert "not proven" in obs["reason"] or "remains unknown" in obs["reason"]
    assert obs["needs_visual_refresh"] is True
    # Crucially: SceneState must NOT record a verified_absent inspection for the whole scene
    for insp in scene_state.active_inspections:
        assert insp.get("verified_absent") is not True or insp.get("inspection_quality", 0.0) < 0.70


@pytest.mark.parametrize(
    "response_text",
    [
        "ничего не видно",
        "Ничего нет",
        "кадр пуст",
        "There is nothing on the screen",
        "The frame is empty",
    ],
)
def test_open_query_global_absence_phrases_stay_not_observed(response_text):
    """Regression: global absence phrases on an OPEN query must degrade to NOT_OBSERVED
    (unknown scene state), never observed_absent with high quality."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text=response_text)
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Что сейчас видно на экране?", target="содержимое экрана", region="full_frame"
    )

    assert obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert obs["inspection_quality"] < 0.70


def test_targeted_query_absence_remains_observed_absent():
    """Explicit targeted question about a concrete object must still produce a bounded
    observed_absent when the VLM confirms the target is not detected."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="Искомый объект отсутствует в кадре")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Есть ли курьер в коридоре?", target="курьер", region="corridor"
    )

    assert obs["status"] == EpistemicObservationState.OBSERVED_ABSENT
    assert obs["inspection_quality"] >= 0.70
    assert "bounded quality" in obs["reason"]
    insp = scene_state.active_inspections[-1]
    assert insp["verified_absent"] is True


def test_open_query_positive_description_with_people_absence_is_present():
    """Regression (independent test): 'На экране виден дом, никого не видно' is a POSITIVE
    description with a partial-subject negative (no people). Absence of people is not
    absence of scene contents: must be observed_present, not observed_absent."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="На экране виден дом, никого не видно")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Что сейчас видно на экране?", target="содержимое экрана", region="full_frame"
    )

    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT
    assert "дом" in obs["details"]
    assert 0.50 <= obs["inspection_quality"] <= 0.70
    assert "not scene absence" in obs["reason"]
    # SceneState records a positive (not verified_absent) inspection
    insp = scene_state.active_inspections[-1]
    assert insp["verified_absent"] is False


@pytest.mark.parametrize(
    "response_text",
    [
        "На экране виден дом, никого не видно",
        "Виден пустой офис, людей не видно",
        "A house is visible in the frame, no people are visible",
        "There is a landscape on screen, nobody is visible",
    ],
)
def test_partial_subject_absence_keeps_positive_status(response_text):
    """Regression variants (RU/EN): scene description + 'no people' clause stays observed_present."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text=response_text)
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Что сейчас видно на экране?", target="содержимое экрана", region="full_frame"
    )

    assert obs["status"] == EpistemicObservationState.OBSERVED_PRESENT


def test_targeted_people_query_absence_stays_observed_absent():
    """A TARGETED question about people specifically ('кто в кадре?') answered with
    'никого не видно' remains a bounded observed_absent for that target."""
    capture = DummyCapture()
    worker = DummyVisualWorker(capture=capture)
    describer = DummyDescriber(response_text="В кадре никого не видно")
    scene_state = SceneState()

    fusion = PerceptionFusion(
        visual_stream_worker=worker,
        vision_describer=describer,
        scene_state=scene_state,
    )

    obs = fusion.fetch_top_down_observation(
        "Есть ли люди в кадре?", target="человек", region="foreground"
    )

    assert obs["status"] == EpistemicObservationState.OBSERVED_ABSENT
    assert obs["inspection_quality"] >= 0.70


