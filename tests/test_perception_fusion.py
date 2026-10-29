import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.sensory_history import SensoryHistoryStore  # noqa: E402


class PerceptionFusionTests(unittest.TestCase):
    def test_compose_merges_fresh_channels(self):
        fusion = PerceptionFusion()
        fusion.note("window", "Visual Studio Code - JAWL", now=100.0)
        fusion.note("music", "Музыка: A minor, 92 BPM", now=101.0)
        fusion.note("speech", "проверка связи", now=102.0)
        text = fusion.compose("открыт редактор кода", now=110.0)
        self.assertIn("Текущий экран [непроверенная гипотеза визуальной модели]: открыт редактор кода", text)
        self.assertIn("Окно: Visual Studio Code - JAWL", text)
        self.assertIn("Звук: Музыка: A minor, 92 BPM", text)
        self.assertIn("Слышно: проверка связи", text)

    def test_compose_drops_expired_channels(self):
        fusion = PerceptionFusion()
        fusion.note("window", "старое окно", now=0.0)
        fusion.note("music", "старая музыка", now=0.0)
        text = fusion.compose("новый экран", now=400.0)
        self.assertIn("Текущий экран [непроверенная гипотеза визуальной модели]: новый экран", text)
        self.assertNotIn("старое окно", text)
        self.assertNotIn("старая музыка", text)

    def test_compose_without_screen_uses_other_channels(self):
        fusion = PerceptionFusion()
        fusion.note("music", "тишина", now=10.0)
        self.assertEqual(fusion.compose("", now=11.0), "Звук: тишина")

    def test_state_reports_fresh_items(self):
        fusion = PerceptionFusion()
        fusion.note("window", "код", now=50.0)
        state = fusion.state(now=51.0)
        self.assertIn("window", state["fresh"])
        self.assertIn("код", state["fresh"]["window"]["text"])

    def test_state_uses_current_context_ttl_for_system_speech(self):
        fusion = PerceptionFusion()
        fusion.note("speech", "System-audio transcript: current words", now=100.0)

        self.assertIn("speech", fusion.state(now=119.9)["fresh"])
        self.assertNotIn("speech", fusion.state(now=120.1)["fresh"])
        self.assertFalse(fusion.current_state("speech", now=120.1)["fresh"])

    def test_yamnet_event_hypotheses_are_independent_and_expire_quickly(self):
        fusion = PerceptionFusion()
        fusion.note(
            "audio_event_candidates",
            "Possible YAMNet sound-event class matches, unverified: Explosion (score 0.16; 2/3 windows)",
            now=10.0,
            metadata={
                "source": "system_audio_loopback",
                "detector": "yamnet-onnx-cpu",
                "segment_started_monotonic": 6.0,
                "segment_ended_monotonic": 10.0,
                "verified": False,
                "audio_kind": "sound",
            },
        )
        fusion.note("speech", "Transcript: incoming fire", now=10.0)

        snapshot = fusion.compose_snapshot(now=10.5)
        self.assertIn("Explosion", snapshot["text"])
        self.assertIn("incoming fire", snapshot["text"])
        self.assertTrue(snapshot["channels"]["audio_event_candidates"]["fresh"])
        self.assertEqual(snapshot["channels"]["audio_event_candidates"]["metadata"]["detector"], "yamnet-onnx-cpu")
        self.assertNotIn("audio_event_candidates", fusion.state(now=22.1)["fresh"])

    def test_live_music_context_expires_after_twenty_seconds(self):
        fusion = PerceptionFusion()
        fusion.note("music", "Music detected by independent YAMNet.", now=100.0)

        self.assertTrue(fusion.current_state("music", now=119.9)["fresh"])
        self.assertFalse(fusion.current_state("music", now=120.1)["fresh"])
        self.assertNotIn("independent YAMNet", fusion.compose(now=120.1))

    def test_weak_music_signal_is_a_short_lived_separate_hypothesis(self):
        fusion = PerceptionFusion()
        fusion.note(
            "music",
            "YAMNet не подтвердил присутствие музыки.",
            now=100.0,
            metadata={"music_state": "unknown"},
        )
        fusion.note(
            "music_candidate",
            "Слабый отклик YAMNet на класс Music; возможен музыкальный или тональный фон, не подтверждено.",
            now=100.0,
            metadata={"verified": False, "music_score_max": 0.34},
        )

        current = fusion.compose(now=101.0)
        self.assertIn("Слабый аудиосигнал", current)
        self.assertIn("не подтверждено", current)
        self.assertNotIn("Музыка:", current)
        self.assertTrue(fusion.current_state("music_candidate", now=111.9)["fresh"])
        self.assertFalse(fusion.current_state("music_candidate", now=112.1)["fresh"])

    def test_audio_hypotheses_require_overlapping_yamnet_music_confirmation(self):
        fusion = PerceptionFusion()
        fusion.note(
            "audio_candidates",
            "EG2 uncalibrated ranking: jazz_smooth 0.69 / hip_hop_beat 0.67",
            now=10.0,
            metadata={
                "source": "eg2-audio",
                "audio_kind": "music",
                "segment_started_monotonic": 2.0,
                "segment_ended_monotonic": 10.0,
                "verified": False,
            },
        )

        self.assertNotIn("jazz_smooth", fusion.compose(now=10.1))
        self.assertFalse(fusion.current_state("audio_candidates", now=10.1)["fresh"])

        fusion.note(
            "music",
            "Music detected by independent YAMNet.",
            now=10.05,
            metadata={
                "source": "system_audio_loopback",
                "music_state": "music",
                "segment_started_monotonic": 8.0,
                "segment_ended_monotonic": 10.05,
            },
        )

        self.assertIn("jazz_smooth", fusion.compose(now=10.1))
        self.assertTrue(fusion.current_state("audio_candidates", now=10.1)["fresh"])

        fusion.note(
            "music",
            "YAMNet did not confirm music.",
            now=10.2,
            metadata={
                "source": "system_audio_loopback",
                "music_state": "unknown",
                "segment_started_monotonic": 10.05,
                "segment_ended_monotonic": 10.2,
            },
        )

        self.assertNotIn("jazz_smooth", fusion.compose(now=10.25))
        self.assertFalse(fusion.current_state("audio_candidates", now=10.25)["fresh"])

    def test_older_audio_segment_invalidation_cannot_stale_newer_caption(self):
        fusion = PerceptionFusion()
        fusion.note(
            "audio_description",
            "Captioner: possible music with vocals.",
            now=200.0,
            metadata={"audio_kind": "music", "source": "captioner"},
        )

        fusion.invalidate("audio_description", now=199.0)

        state = fusion.current_state("audio_description", now=200.0)
        self.assertTrue(state["fresh"])
        self.assertIn("possible music with vocals", fusion.compose(now=200.0))

        fusion.invalidate("audio_description", now=201.0)

        self.assertFalse(fusion.current_state("audio_description", now=201.0)["fresh"])
        self.assertNotIn("possible music with vocals", fusion.compose(now=201.0))

    def test_screen_invalidation_also_expires_ocr_but_older_invalidation_does_not(self):
        fusion = PerceptionFusion()
        fusion.note(
            "ocr", "Mission: find the key", now=200.0,
            metadata={"scene_id": "scene-2", "verified": False},
        )

        fusion.invalidate("screen", now=199.0)
        self.assertTrue(fusion.current_state("ocr", now=200.0)["fresh"])
        self.assertIn("Mission: find the key", fusion.compose(now=200.0))

        fusion.invalidate("screen", now=201.0)
        self.assertFalse(fusion.current_state("ocr", now=201.0)["fresh"])
        self.assertNotIn("Mission: find the key", fusion.compose(now=201.0))

    def test_compose_snapshot_keeps_text_and_screen_provenance_from_same_view(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "A yellow-jacketed character stands by a tree.",
            captured_at_monotonic=10.0,
            captured_at_wall=1_800_000_000.0,
            frame_id="qwen-frame-62",
            source="screen:qa:roi=0.1,0.1,0.8,0.8",
            scene_id="scene-7",
            now=10.5,
        )

        snapshot = fusion.compose_snapshot(now=11.0)

        self.assertIn("A yellow-jacketed character stands by a tree.", snapshot["text"])
        self.assertIn("\u043d\u0435\u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u0430\u044f \u0433\u0438\u043f\u043e\u0442\u0435\u0437\u0430 \u0432\u0438\u0437\u0443\u0430\u043b\u044c\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438", snapshot["text"])
        self.assertEqual(snapshot["captured_monotonic"], 11.0)
        self.assertEqual(snapshot["channels"]["screen"]["metadata"]["frame_id"], "qwen-frame-62")
        self.assertEqual(snapshot["channels"]["screen"]["metadata"]["scene_id"], "scene-7")
        self.assertEqual(snapshot["channels"]["screen"]["age_ms"], 1000.0)
        self.assertTrue(snapshot["channels"]["screen"]["fresh"])

    def test_structured_audio_channels_keep_content_beyond_legacy_summary_cap(self):
        fusion = PerceptionFusion()
        transcript = "S" * 1800
        description = "D" * 1400
        fusion.note("speech", transcript, now=10.0)
        fusion.note("audio_description", description, now=10.0)

        snapshot = fusion.compose_snapshot(now=10.0)

        self.assertLessEqual(len(snapshot["text"]), 1200)
        self.assertEqual(snapshot["channels"]["speech"]["text"], transcript)
        self.assertEqual(snapshot["channels"]["audio_description"]["text"], description)

    def test_oversized_audio_channel_is_bounded_by_its_own_limit(self):
        fusion = PerceptionFusion()
        fusion.note("speech", "S" * 5000, now=10.0)

        snapshot = fusion.compose_snapshot(now=10.0)

        self.assertEqual(len(snapshot["channels"]["speech"]["text"]), 2400)

    def test_compose_snapshot_marks_expired_screen_without_rendering_it(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Old scene caption.",
            captured_at_monotonic=10.0,
            captured_at_wall=1_800_000_000.0,
            frame_id="frame-old",
            source="qa",
            scene_id="scene-old",
            now=10.0,
        )

        snapshot = fusion.compose_snapshot(now=15.1)

        self.assertNotIn("Текущий экран [непроверенная гипотеза визуальной модели]: Old scene caption.", snapshot["text"])
        self.assertIn("история, не текущий кадр", snapshot["text"])
        self.assertIn("Old scene caption.", snapshot["text"])
        self.assertFalse(snapshot["channels"]["screen"]["fresh"])
        self.assertEqual(snapshot["recent_visual_events"][0]["frame_id"], "frame-old")

    def test_late_visual_result_is_history_but_never_current_screen(self):
        fusion = PerceptionFusion()
        fusion.record_visual_event(
            "A person enters the room.",
            captured_at_monotonic=100.0,
            captured_at_wall=1_800_000_000.0,
            frame_id="frame-old-scene",
            source="screen:target",
            scene_id="scene-old",
            now=102.0,
        )

        snapshot = fusion.compose_snapshot(now=103.0)

        self.assertNotIn("Текущий экран [непроверенная гипотеза визуальной модели]: A person enters", snapshot["text"])
        self.assertIn("история, не текущий кадр", snapshot["text"])
        self.assertIn("A person enters the room.", snapshot["text"])
        self.assertFalse(fusion.current_state("screen", now=103.0)["fresh"])
        event = snapshot["recent_visual_events"][0]
        self.assertEqual(event["scene_id"], "scene-old")
        self.assertEqual(event["age_ms"], 3000.0)
        self.assertEqual(event["captured_at"], 1_800_000_000.0)

    def test_visual_timeline_deduplicates_scene_and_expires_from_context(self):
        fusion = PerceptionFusion()
        base = {
            "captured_at_wall": 1_800_000_000.0,
            "source": "screen",
            "scene_id": "scene-1",
        }
        fusion.record_visual_event(
            "An older description.", captured_at_monotonic=100.0, frame_id="frame-1", now=100.0, **base
        )
        fusion.record_visual_event(
            "A better description.", captured_at_monotonic=101.0, frame_id="frame-2", now=101.0, **base
        )
        self.assertIn("A better description.", fusion.compose(now=102.0))
        self.assertNotIn("An older description.", fusion.compose(now=102.0))
        self.assertNotIn("A better description.", fusion.compose(now=116.1))

    def test_visual_timeline_keeps_only_five_scene_summaries(self):
        fusion = PerceptionFusion()
        for index in range(7):
            fusion.record_visual_event(
                f"Scene {index}.",
                captured_at_monotonic=100.0 + index,
                captured_at_wall=1_800_000_000.0 + index,
                frame_id=f"frame-{index}",
                source="screen",
                scene_id=f"scene-{index}",
                now=100.0 + index,
            )

        events = fusion.compose_snapshot(now=106.0)["recent_visual_events"]

        self.assertEqual(len(events), 5)
        self.assertEqual([event["scene_id"] for event in events], [f"scene-{index}" for index in range(2, 7)])

    def test_current_caption_is_not_duplicated_in_recent_visual_history(self):
        fusion = PerceptionFusion()
        fusion.record_visual_event(
            "Earlier scene.", captured_at_monotonic=100.0, captured_at_wall=1_000.0,
            frame_id="frame-1", source="screen", scene_id="scene-1", now=100.0,
        )
        fusion.observe_caption(
            "Current scene.", captured_at_monotonic=101.0, captured_at_wall=1_001.0,
            frame_id="frame-2", source="screen", scene_id="scene-2", now=101.0,
        )

        snapshot = fusion.compose_snapshot(now=102.0)

        self.assertIn(
            "Текущий экран [непроверенная гипотеза визуальной модели]: "
            "[наблюдение 1.0 с назад] Current scene.",
            snapshot["text"],
        )
        self.assertIn("Earlier scene.", snapshot["text"])
        self.assertNotIn("Current scene..", snapshot["text"])
        self.assertNotIn("Current scene.", " ".join(item["text"] for item in snapshot["recent_visual_events"]))

    def test_history_only_visual_event_persists_once_without_current_caption_write(self):
        wall_time = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensory-history.json"
            history = SensoryHistoryStore(path, enabled=True, clock=lambda: wall_time)
            fusion = PerceptionFusion(history_store=history)
            fusion.observe_caption(
                "Current scene caption.", captured_at_monotonic=100.0,
                captured_at_wall=wall_time, frame_id="frame-current", source="screen",
                scene_id="scene-current", now=100.0,
            )
            self.assertEqual(history.state()["recent_event_count"], 1)

            self.assertTrue(fusion.record_visual_event(
                "Late scene caption.", captured_at_monotonic=101.0,
                captured_at_wall=wall_time + 1.0, frame_id="frame-late",
                source="screen", scene_id="scene-late", now=102.0,
                persist_history=True,
            ))
            self.assertEqual(history.state()["recent_event_count"], 2)
            history.flush()
            payload = json.loads(path.read_text(encoding="utf-8"))

        visual_text = [event["text"] for event in payload["recent_events"] if event["modality"] == "visual"]
        self.assertEqual(visual_text.count("Current scene caption."), 1)
        self.assertEqual(visual_text.count("Late scene caption."), 1)
        self.assertTrue(any(moment["text"] == "Late scene caption."
                            for bucket in payload["hourly_summaries"]
                            for moment in bucket["moments"]))

    def test_observe_eg2_merges_compact_multimodal_observation(self):
        fusion = PerceptionFusion()

        class Observation:
            def to_dict(self):
                return {
                    "top_label": "code_ide_terminal",
                    "audio_top_label": "human_speech_ru",
                    "vibe_score": 0.42,
                    "reflex": {"emotion": "attentive"},
                }

        text = fusion.observe_eg2(Observation(), now=10.0)
        self.assertIn("EG2: code_ide_terminal", text)
        self.assertIn("audio=human_speech_ru", text)
        self.assertIn("vibe=0.420", text)


class DisplayFusionTests(unittest.TestCase):
    def test_observe_displays_builds_combined_description(self):
        fusion = PerceptionFusion()

        class FakeCortex:
            def describe_displays(self, images):
                return "Дисплей 1: code_ide_terminal (0.90); Дисплей 2: anime_movie_video (0.80)"

            def classify_displays(self, images):
                class Obs:
                    top_label = "code_ide_terminal"

                return [Obs(), Obs()]

        text = fusion.observe_displays([b"img1", b"img2"], cortex=FakeCortex(), now=10.0)
        self.assertIn("Дисплей 1: code_ide_terminal", text)
        self.assertIn("Дисплей 2: anime_movie_video", text)

    def test_observe_displays_degrades_without_cortex(self):
        fusion = PerceptionFusion()
        fusion.eg2 = None
        fusion.eg2_cortex = lambda: None
        text = fusion.observe_displays([b"img1"], cortex=None, now=10.0)
        self.assertIn("Дисплеи: нет данных", text)


    def test_observe_displays_only_fuses_gated_music_or_speech_audio(self):
        class FakeCortex:
            def describe_displays(self, _images):
                return "display scene"

            def classify_displays(self, _images):
                return []

        class FakeDescriber:
            def __init__(self, speech, music, rms=-20):
                self.speech, self.music, self.rms = speech, music, rms
                self.display_audio_args = []

            def describe_displays_detailed(self, _images, **kwargs):
                self.display_audio_args.append(kwargs)
                return "display scene"

            def describe_audio_detailed(self, _wav):
                return SimpleNamespace(
                    level2={"dsp": {"is_speech_likely": self.speech,
                                     "is_music_likely": self.music,
                                     "rms_dbfs": self.rms}},
                    level1={}, description="raw energetic_action_music claim",
                )

        for speech, music, rms, forbidden in (
            (True, True, -20, "energetic_action_music"),
            (False, False, -20, "raw energetic_action_music"),
            (False, False, -80, "Audio event"),
            (False, True, -20, "raw energetic_action_music"),
        ):
            fusion = PerceptionFusion()
            describer = FakeDescriber(speech, music, rms)
            fusion.describer = describer
            text = fusion.observe_displays([b"img"], cortex=FakeCortex(), audio_wav_bytes=b"wav", now=10)
            self.assertNotIn(forbidden, text)
            self.assertEqual(describer.display_audio_args, [{}])


if __name__ == "__main__":
    unittest.main()
