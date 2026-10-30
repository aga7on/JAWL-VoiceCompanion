import base64
import io
import json
import tempfile
import sys
import time
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.qwen_event_describer import QwenEventDescriber, QwenEventObservation  # noqa: E402
from jawl_voicecompanion.qwen_visual_sensor import QwenVisualSensor  # noqa: E402
from jawl_voicecompanion.sensory_history import SensoryHistoryStore  # noqa: E402


def _jpeg(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeCapture:
    def __init__(self, color=(10, 20, 30)):
        self.color = color
        self.ocr_enabled = False
        self.ocr_calls = []

    def observe(self, *, include_ocr=False):
        self.ocr_calls.append(bool(include_ocr))
        result = {
            "status": "verified",
            "image": {"data_base64": base64.b64encode(_jpeg(self.color)).decode("ascii")},
            "window": {"class_name": "TestWindow"},
        }
        if include_ocr:
            result["ocr"] = [{"text": "Inventory: 12 lives", "confidence": 91.0}]
        return result

    def capture_displays(self, *, max_displays=2, include_ocr=False):
        self.ocr_calls.append(bool(include_ocr))
        results = [
            {
                "status": "verified",
                "bounds": [i * 100, 0, (i + 1) * 100, 80],
                "image": {"data_base64": base64.b64encode(_jpeg((i + 1, 0, 0))).decode("ascii")},
            }
            for i in range(max_displays)
        ]
        if include_ocr:
            results[0]["ocr"] = [{"text": "Display text", "confidence": 90.0}]
        return results


class FakeDescriber:
    def __init__(self, observation):
        self.observation = observation
        self.submits = []
        self.max_age_s = 6.0

    def start(self):
        pass

    def stop(self, timeout=2.0):
        pass

    def submit(self, image_bytes, **kwargs):
        self.submits.append(kwargs)
        return True

    def poll(self):
        return self.observation


class AgingTests(unittest.TestCase):
    def test_repeated_read_does_not_extend_ttl_and_keeps_capture_time(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Earth rotates with city lights",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen:focused:roi=0,0,1,1",
            scene_id="scene-1",
            roi=(0.0, 0.0, 1.0, 1.0),
            now=100.0,
        )
        self.assertIn("Earth rotates", fusion.compose(now=103.0))
        self.assertIn("Earth rotates", fusion.compose(now=104.0))
        expired_text = fusion.compose(now=106.0)
        self.assertNotIn("Экран [непроверенная гипотеза визуальной модели]: Earth rotates", expired_text)
        self.assertIn("история, не текущий кадр", expired_text)
        state = fusion.state(now=104.0)
        self.assertEqual(state["fresh"]["screen"]["metadata"]["frame_id"], "frame-1")
        self.assertEqual(state["fresh"]["screen"]["metadata"]["scene_id"], "scene-1")
        self.assertEqual(state["fresh"]["screen"]["metadata"]["captured_at"], 1_000_000.0)

    def test_same_scene_confirmation_preserves_caption_time_and_expires_without_capture(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Earth rotates",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen",
            scene_id="scene-1",
            now=100.0,
        )
        self.assertTrue(fusion.confirm_caption(
            scene_id="scene-1",
            confirmed_at_monotonic=104.0,
            confirmed_at_wall=1_000_004.0,
        ))
        state = fusion.current_state("screen", now=108.0)
        self.assertTrue(state["fresh"])
        self.assertEqual(state["age_ms"], 4000.0)
        self.assertEqual(state["caption_age_ms"], 8000.0)
        self.assertEqual(state["metadata"]["caption_time"], 1_000_000.0)
        self.assertEqual(state["metadata"]["confirmed_at"], 1_000_004.0)
        self.assertFalse(fusion.current_state("screen", now=109.1)["fresh"])

    def test_confirmation_rejects_other_scenes(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Earth rotates", captured_at_monotonic=100.0, captured_at_wall=1_000_000.0,
            frame_id="frame-1", source="screen", scene_id="scene-1", now=100.0,
        )
        self.assertFalse(fusion.confirm_caption(
            scene_id="scene-2", confirmed_at_monotonic=101.0, confirmed_at_wall=1_000_001.0,
        ))
        self.assertFalse(fusion.confirm_caption(
            scene_id="scene-1", confirmed_at_monotonic=99.0, confirmed_at_wall=1_000_001.0,
        ))


class StableCaptureConfirmationTests(unittest.TestCase):
    def test_identical_capture_keeps_caption_current_without_faking_caption_time(self):
        now = [104.0]
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "A code editor is open", captured_at_monotonic=100.0, captured_at_wall=1_000.0,
            frame_id="frame-1", source="screen", scene_id="scene-1", now=100.0,
        )
        sensor = QwenVisualSensor(
            screen_capture=FakeCapture(),
            describer=FakeDescriber(QwenEventObservation(
                caption="unused", observed_at=1000.0, processed_at=100.0, age_ms=0.0,
                stale=False, source="screen", event_id="old", model="qwen", budget=64,
                truncated=False, frame_id="old", scene_id="scene-1",
                captured_monotonic=100.0,
            )),
            fusion=fusion,
            clock=lambda: now[0],
            wall_clock=lambda: 1_000.0 + now[0],
        )
        _, sensor._signature = sensor._crop(_jpeg())
        sensor._last_processed_at = 100.0
        sensor._last_submit_at = 100.0

        sensor._tick()
        now[0] = 108.0
        state = sensor.state()

        self.assertTrue(state["caption_fresh"])
        self.assertEqual(state["caption_age_ms"], 8000.0)
        self.assertEqual(state["caption_confirmed_age_ms"], 4000.0)
        self.assertIn("A code editor", fusion.compose(now=108.0))

        now[0] = 109.1
        self.assertFalse(sensor.state()["caption_fresh"])


class DeliveryTests(unittest.TestCase):
    def test_selected_display_capture_uses_display_index_and_bounds(self):
        sensor = QwenVisualSensor(
            screen_capture=FakeCapture(),
            describer=FakeDescriber(self._observation()),
            fusion=PerceptionFusion(),
            display_index=0,
        )
        frame = sensor._capture()
        self.assertIsNotNone(frame)
        _, _, source, _, _, _ = frame
        self.assertIn("screen:display:0", source)
        self.assertIn("bounds=0,0,100,80", source)
        self.assertEqual(sensor.state()["display_index"], 0)

    def test_ocr_is_sent_as_separate_fresh_channel_and_not_run_each_poll(self):
        now = [100.0]
        capture = FakeCapture()
        capture.ocr_enabled = True
        fusion = PerceptionFusion()
        sensor = QwenVisualSensor(
            screen_capture=capture,
            describer=FakeDescriber(None),
            fusion=fusion,
            clock=lambda: now[0],
            wall_clock=lambda: 1_000.0 + now[0],
        )

        sensor._tick()
        packet = fusion.compose_snapshot(now=100.0)
        self.assertEqual(packet["channels"]["ocr"]["text"], "Inventory: 12 lives")
        self.assertEqual(packet["channels"]["ocr"]["metadata"]["source"], "windows_ocr")
        self.assertEqual(capture.ocr_calls, [True])

        now[0] = 100.2
        sensor._tick()
        self.assertEqual(capture.ocr_calls, [True, False])

        now[0] = 104.1
        sensor._tick()
        self.assertEqual(capture.ocr_calls, [True, False, True])

    def test_scene_change_schedules_ocr_on_next_capture_even_if_caption_submits(self):
        now = [100.0]
        capture = FakeCapture()
        capture.ocr_enabled = True
        fusion = PerceptionFusion()
        describer = FakeDescriber(None)
        sensor = QwenVisualSensor(
            screen_capture=capture,
            describer=describer,
            fusion=fusion,
            clock=lambda: now[0],
            wall_clock=lambda: 1_000.0 + now[0],
        )

        sensor._tick()
        self.assertEqual(capture.ocr_calls, [True])
        capture.color = (200, 10, 10)
        now[0] = 100.2
        sensor._tick()
        self.assertEqual(capture.ocr_calls, [True, False])
        self.assertEqual(len(describer.submits), 1)

        now[0] = 100.4
        sensor._tick()

        self.assertEqual(capture.ocr_calls, [True, False, True])
        self.assertEqual(
            fusion.compose_snapshot(now=100.4)["channels"]["ocr"]["metadata"]["scene_id"],
            "scene-2",
        )

    def test_selected_display_requests_ocr_and_keeps_ocr_out_of_caption_payload(self):
        capture = FakeCapture()
        capture.ocr_enabled = True
        sensor = QwenVisualSensor(
            screen_capture=capture,
            describer=FakeDescriber(None),
            fusion=PerceptionFusion(),
            display_index=0,
        )

        frame = sensor._capture(include_ocr=True)

        self.assertIsNotNone(frame)
        self.assertEqual(frame[2].split(":")[1], "display")
        self.assertEqual(frame[5][0]["text"], "Display text")
        self.assertEqual(capture.ocr_calls, [True])

    def _observation(self, **overrides):
        payload = {
            "caption": "Earth rotates",
            "observed_at": time.time(),
            "processed_at": time.time(),
            "age_ms": 10.0,
            "stale": False,
            "source": "screen:focused:roi=0,0,1,1",
            "event_id": "frame-1",
            "model": "qwen3.5-0.8b",
            "budget": 64,
            "truncated": False,
            "frame_id": "frame-1",
            "scene_id": "scene-1",
            "roi": (0.0, 0.0, 1.0, 1.0),
            "captured_monotonic": time.monotonic() - float(overrides.get("age_ms", 10.0)) / 1000.0,
        }
        payload.update(overrides)
        return QwenEventObservation(**payload)

    def test_result_is_delivered_once(self):
        fusion = PerceptionFusion()
        observation = self._observation()
        describer = FakeDescriber(observation)
        callback_events = []
        sensor = QwenVisualSensor(
            screen_capture=None,
            describer=describer,
            fusion=fusion,
            on_observation=lambda item: callback_events.append(item),
            clock=time.monotonic,
            wall_clock=time.time,
        )
        sensor._scene_id = "scene-1"
        sensor._deliver()
        sensor._deliver()
        self.assertEqual(sensor.state()["delivered"], 1)
        self.assertEqual(len(callback_events), 1)
        # /api/vision/status returns this state through the ordinary JSON encoder.
        state = sensor.state()
        self.assertEqual(state["last_observation"]["caption"], "Earth rotates")
        json.dumps(state, ensure_ascii=False)
        self.assertEqual(fusion.compose(now=time.monotonic()).count("Earth rotates"), 1)

    def test_state_exposes_current_caption_freshness(self):
        now = [104.0]
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Earth rotates",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen",
            scene_id="scene-1",
        )
        sensor = QwenVisualSensor(
            screen_capture=None,
            describer=FakeDescriber(self._observation()),
            fusion=fusion,
            clock=lambda: now[0],
        )
        fresh = sensor.state()
        self.assertTrue(fresh["caption_fresh"])
        self.assertEqual(fresh["caption_age_ms"], 4000.0)
        self.assertEqual(fresh["caption_ttl_ms"], 5000.0)
        now[0] = 106.0
        stale = sensor.state()
        self.assertFalse(stale["caption_fresh"])
        self.assertEqual(stale["caption_age_ms"], 6000.0)

    def test_qwen_profile_can_hide_eg2_dictionary_from_scene(self):
        fusion = PerceptionFusion(include_eg2_media_in_scene=False)
        fusion.observe_caption(
            "Qwen: Earth",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen",
            scene_id="scene-1",
        )
        fusion.observe_media(
            {"description": "EG2: code_ide_terminal"},
            modality="vision",
            summary="EG2: code_ide_terminal",
            channel="eg2_media",
            now=101.0,
        )
        text = fusion.compose(now=102.0)
        self.assertIn("Qwen: Earth", text)
        self.assertNotIn("EG2: code_ide_terminal", text)
        self.assertIn("eg2_media", fusion.state(now=102.0)["fresh"])

    def test_eg2_dictionary_description_does_not_replace_qwen_caption(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Qwen: Earth rotates",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen",
            scene_id="scene-1",
        )
        fusion.observe_media(
            {"description": "EG2 dictionary: code_ide_terminal"},
            modality="vision",
            summary="EG2 dictionary: code_ide_terminal",
            channel="eg2_media",
            now=101.0,
        )
        text = fusion.compose(now=102.0)
        self.assertIn("Qwen: Earth rotates", text)
        self.assertIn("EG2 dictionary: code_ide_terminal", text)

    def test_previous_scene_result_is_not_current_after_scene_change(self):
        fusion = PerceptionFusion()
        observation = self._observation(scene_id="scene-1")
        describer = FakeDescriber(observation)
        attention_events = []
        sensor = QwenVisualSensor(
            screen_capture=None,
            describer=describer,
            fusion=fusion,
            on_observation=attention_events.append,
            clock=time.monotonic,
            wall_clock=time.time,
        )
        sensor._scene_id = "scene-2"
        sensor._deliver()
        state = sensor.state()
        self.assertEqual(state["dropped_scene_change"], 1)
        self.assertEqual(state["scene_change_history_recorded"], 1)
        self.assertEqual(state["scene_change_history_rejected"], 0)
        composed = fusion.compose(now=time.monotonic())
        self.assertIn("Earth rotates", composed)
        self.assertIn("история, не текущий кадр", composed)
        self.assertNotIn("Экран [непроверенная гипотеза визуальной модели]: Earth rotates", composed)
        self.assertFalse(fusion.current_state("screen")["fresh"])
        self.assertEqual(attention_events, [])

    def test_scene_change_metrics_distinguish_history_rejection(self):
        fusion = PerceptionFusion()
        fusion.record_visual_event = lambda *args, **kwargs: False
        sensor = QwenVisualSensor(
            screen_capture=None,
            describer=FakeDescriber(self._observation(scene_id="scene-1")),
            fusion=fusion,
            clock=time.monotonic,
            wall_clock=time.time,
        )
        sensor._scene_id = "scene-2"

        sensor._deliver()

        state = sensor.state()
        self.assertEqual(state["dropped_scene_change"], 1)
        self.assertEqual(state["scene_change_history_recorded"], 0)
        self.assertEqual(state["scene_change_history_rejected"], 1)

    def test_stale_result_is_archived_but_never_becomes_current_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            history = SensoryHistoryStore(Path(directory) / "history.json", enabled=True)
            fusion = PerceptionFusion(history_store=history)
            observation = self._observation(age_ms=7000.0, stale=True)
            sensor = QwenVisualSensor(
                screen_capture=None,
                describer=FakeDescriber(observation),
                fusion=fusion,
                clock=time.monotonic,
                wall_clock=time.time,
            )
            sensor._scene_id = "scene-1"
            sensor._deliver()
            state = sensor.state()
            self.assertEqual(state["dropped_stale"], 0)
            self.assertEqual(state["stale_history_recorded"], 1)
            self.assertFalse(fusion.current_state("screen")["fresh"])
            text = fusion.compose(now=time.monotonic())
            self.assertIn("история, не текущий кадр", text)
            self.assertIn("Earth rotates", text)
            self.assertEqual(history.state()["recent_event_count"], 1)

    def test_stale_result_older_than_visual_history_is_dropped(self):
        fusion = PerceptionFusion()
        observation = self._observation(age_ms=40_000.0, stale=True)
        sensor = QwenVisualSensor(
            screen_capture=None,
            describer=FakeDescriber(observation),
            fusion=fusion,
            clock=time.monotonic,
            wall_clock=time.time,
        )
        sensor._scene_id = "scene-1"
        sensor._deliver()
        state = sensor.state()
        self.assertEqual(state["dropped_stale"], 1)
        self.assertEqual(state["stale_history_recorded"], 0)
        self.assertNotIn("Earth rotates", fusion.compose(now=time.monotonic()))


class TriggerRateTests(unittest.TestCase):
    def test_default_static_refresh_fits_inside_current_screen_ttl(self):
        sensor = QwenVisualSensor(
            screen_capture=FakeCapture(),
            describer=FakeDescriber(None),
            fusion=PerceptionFusion(),
        )
        self.assertEqual(sensor.static_interval_s, 4.0)
        self.assertEqual(sensor.periodic_s, 4.0)
        self.assertLess(sensor.static_interval_s, 5.0)

    def test_periodic_static_and_active_rate_limits(self):
        now = [100.0]
        capture = FakeCapture((10, 10, 10))
        describer = FakeDescriber(
            QwenEventObservation(
                caption="Earth",
                observed_at=1000.0,
                processed_at=1001.0,
                age_ms=1.0,
                stale=False,
                source="screen",
                event_id="f",
                model="qwen3.5-0.8b",
                budget=64,
                truncated=False,
                frame_id="f",
                scene_id="scene-1",
                captured_monotonic=100.0,
            )
        )
        sensor = QwenVisualSensor(
            screen_capture=capture,
            describer=describer,
            fusion=PerceptionFusion(),
            active_interval_s=1.0,
            static_interval_s=5.0,
            periodic_s=10.0,
            clock=lambda: now[0],
            wall_clock=lambda: 1000.0 + now[0],
        )
        sensor._last_submit_at = 0.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 1)
        self.assertEqual(sensor.state()["last_submit_reason"], "periodic")
        now[0] = 101.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 1)
        capture.color = (200, 10, 10)
        now[0] = 102.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 2)
        capture.color = (10, 200, 10)
        now[0] = 103.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 3)
        capture.color = (10, 10, 200)
        now[0] = 103.5
        sensor._tick()
        self.assertEqual(len(describer.submits), 3)
        capture.color = (200, 200, 10)
        now[0] = 104.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 4)


class PendingSceneTests(unittest.TestCase):
    def test_scene_change_inside_cooldown_sends_latest_frame_after_interval(self):
        now = [100.0]
        capture = FakeCapture((10, 10, 10))
        describer = FakeDescriber(
            QwenEventObservation(
                caption="Earth",
                observed_at=1000.0,
                processed_at=1001.0,
                age_ms=1.0,
                stale=False,
                source="screen",
                event_id="f",
                model="qwen3.5-0.8b",
                budget=64,
                truncated=False,
                frame_id="f",
                scene_id="scene-1",
                captured_monotonic=100.0,
            )
        )
        fusion = PerceptionFusion()
        sensor = QwenVisualSensor(
            screen_capture=capture,
            describer=describer,
            fusion=fusion,
            active_interval_s=1.0,
            static_interval_s=5.0,
            periodic_s=10.0,
            clock=lambda: now[0],
            wall_clock=lambda: 1000.0 + now[0],
        )
        sensor._last_submit_at = 0.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 1)
        fusion.observe_caption(
            "old scene caption",
            captured_at_monotonic=0.0,
            captured_at_wall=0.0,
            frame_id="old-frame",
            source="screen",
            scene_id="scene-1",
            now=0.0,
        )
        self.assertIn("old scene caption", fusion.compose(now=1.0))
        capture.color = (200, 10, 10)
        now[0] = 100.5
        sensor._tick()
        self.assertEqual(len(describer.submits), 1)
        self.assertTrue(sensor.state()["dirty"])
        outdated = fusion.compose(now=1.0)
        self.assertNotIn("Текущий экран", outdated)
        self.assertIn("история, не текущий кадр", outdated)
        self.assertIn("old scene caption", outdated)
        now[0] = 101.0
        sensor._tick()
        self.assertEqual(len(describer.submits), 2)
        self.assertEqual(sensor.state()["last_submit_reason"], "scene_change")
        self.assertFalse(sensor.state()["dirty"])


class RestartTests(unittest.TestCase):
    def test_stop_returns_while_request_is_hung_and_restart_works(self):
        release = __import__("threading").Event()

        def transport(payload):
            release.wait(5.0)
            return "Earth rotates", False

        describer = QwenEventDescriber("http://127.0.0.1:1", transport=transport)
        describer.start()
        describer.submit(b"\xff\xd8fake", observed_at=time.time())
        started = time.monotonic()
        describer.stop(timeout=0.2)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        release.set()
        time.sleep(0.1)
        describer.start()
        describer.submit(b"\xff\xd8fake-2", observed_at=time.time())
        deadline = time.time() + 2.0
        while time.time() < deadline and describer.poll() is None:
            time.sleep(0.02)
        describer.stop(timeout=0.5)
        self.assertIsNotNone(describer.poll())

    def test_sensor_restarts(self):
        describer = FakeDescriber(
            QwenEventObservation(
                caption="Earth",
                observed_at=time.time(),
                processed_at=time.time(),
                age_ms=1.0,
                stale=False,
                source="screen",
                event_id="f",
                model="qwen3.5-0.8b",
                budget=64,
                truncated=False,
                frame_id="f",
                scene_id="scene-1",
                captured_monotonic=time.monotonic(),
            )
        )
        sensor = QwenVisualSensor(
            screen_capture=FakeCapture(),
            describer=describer,
            fusion=PerceptionFusion(),
            poll_interval_s=0.05,
        )
        sensor.start()
        time.sleep(0.1)
        sensor.stop()
        self.assertFalse(sensor.running)
        sensor.start()
        time.sleep(0.1)
        self.assertTrue(sensor.running)
        sensor.stop()


if __name__ == "__main__":
    unittest.main()
