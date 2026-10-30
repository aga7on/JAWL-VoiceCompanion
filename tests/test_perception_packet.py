import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from jawl_voicecompanion.perception_packet import attach_packet, make_packet, render_packet, split_packet, strip_appendix
from jawl_voicecompanion.perception_fusion import PerceptionFusion


class PerceptionPacketTests(unittest.TestCase):
    def test_packet_renders_full_bounded_transcript_after_short_summary(self):
        fusion = PerceptionFusion()
        transcript = "ASR:" + (" recognized phrase." * 100)
        fusion.note("speech", transcript, now=10.0)
        snapshot = fusion.compose_snapshot(now=10.0)
        packet = make_packet(snapshot)

        rendered = render_packet(packet, now=packet["generated_at"])

        self.assertLessEqual(len(snapshot["text"]), 1200)
        self.assertIn(transcript, rendered)

    def test_ocr_is_a_distinct_hypothesis_channel_in_brain_packet(self):
        fusion = PerceptionFusion()
        fusion.note(
            "ocr", "QUEST: Find the red key", now=10.0,
            metadata={"source": "windows_ocr", "verified": False, "scene_id": "scene-4"},
        )
        packet = make_packet(fusion.compose_snapshot(now=10.0))

        self.assertIn("ocr", packet["channels"])
        self.assertTrue(packet["channels"]["ocr"]["hypothesis"])
        rendered = render_packet(packet, now=packet["generated_at"])
        self.assertIn("QUEST: Find the red key", rendered)
        self.assertIn("OCR", rendered)

    def test_yamnet_sound_events_reach_brain_as_unverified_hypotheses(self):
        packet = make_packet({"channels": {"audio_event_candidates": {
            "text": "Possible YAMNet sound-event class matches, unverified: Explosion (score 0.16; 2/3 windows)",
            "age_ms": 1000,
            "ttl_ms": 12000,
            "metadata": {"verified": False, "source": "system_audio_loopback"},
        }}})

        self.assertTrue(packet["channels"]["audio_event_candidates"]["hypothesis"])
        self.assertIn("Explosion", render_packet(packet, now=packet["generated_at"]))

    def test_full_av_channels_survive_fusion_and_brain_packet_serialization(self):
        fusion = PerceptionFusion()
        fusion.note("screen", "A character runs through a game corridor", now=10.0)
        fusion.note(
            "ocr", "Quest: Find the exit", now=10.0,
            metadata={"source": "windows_ocr", "verified": False},
        )
        fusion.note("speech", "Player says: watch the door", now=10.0, metadata={"verified": False})
        fusion.note(
            "audio_description", "A tense orchestral cue rises under the dialogue", now=10.0,
            metadata={"source": "eg2-audio", "audio_kind": "music", "verified": False},
        )
        fusion.note(
            "audio_candidates", "Possible style: cinematic orchestral", now=10.0,
            metadata={
                "source": "eg2-audio", "audio_kind": "music", "verified": False,
                "segment_started_monotonic": 2.0, "segment_ended_monotonic": 10.0,
            },
        )
        fusion.note(
            "music", "Music detected by independent YAMNet", now=10.0,
            metadata={
                "source": "system_audio_loopback", "music_state": "music",
                "segment_started_monotonic": 8.0, "segment_ended_monotonic": 10.0,
            },
        )
        fusion.note(
            "audio_event_candidates", "Possible sound event: door impact", now=10.0,
            metadata={"source": "yamnet-onnx-cpu", "verified": False},
        )

        packet = make_packet(fusion.compose_snapshot(now=10.0))
        rendered = render_packet(packet, now=packet["generated_at"])

        expected = {
            "screen", "ocr", "speech", "audio_description", "audio_candidates",
            "music", "audio_event_candidates",
        }
        self.assertEqual(set(packet["channels"]), expected)
        for evidence in (
            "game corridor", "Quest: Find the exit", "watch the door",
            "orchestral cue", "cinematic orchestral", "independent YAMNet",
            "door impact",
        ):
            self.assertIn(evidence, rendered)
        self.assertIn("гипотеза модели", rendered)

    def test_unknown_music_state_is_not_repeated_as_a_description(self):
        packet = make_packet({"channels": {"music": {
            "text": "detector did not confirm music", "age_ms": 0, "ttl_ms": 20000,
            "metadata": {"music_state": "unknown"},
        }}}, fallback="detector did not confirm music")
        self.assertEqual(render_packet(packet), "")

    def test_weak_music_candidate_reaches_brain_as_an_uncalibrated_hypothesis(self):
        fusion = PerceptionFusion()
        fusion.note(
            "music",
            "YAMNet did not confirm music.",
            now=10.0,
            metadata={"music_state": "unknown"},
        )
        fusion.note(
            "music_candidate",
            "Possible musical or tonal background; YAMNet Music in 1/3 windows (raw max=0.3822, not a probability); multi-window gate not passed.",
            now=10.0,
            metadata={
                "verified": False,
                "confidence_calibrated": False,
                "score_type": "uncalibrated_raw_model_score",
            },
        )
        packet = make_packet(fusion.compose_snapshot(now=10.0))

        self.assertNotIn("music", packet["channels"])
        self.assertTrue(packet["channels"]["music_candidate"]["hypothesis"])
        rendered = render_packet(packet, now=packet["generated_at"])
        self.assertIn("Possible musical or tonal background", rendered)
        self.assertIn("1/3 windows", rendered)
        self.assertIn("not a probability", rendered)

    def test_text_is_separate_and_diagnostics_do_not_enter_packet(self):
        snapshot = {"channels": {
            "screen": {"text": "Two cars on a road", "age_ms": 1200, "ttl_ms": 5000,
                       "metadata": {"frame_id": "internal-frame", "rms_dbfs": -12}},
            "music": {"text": "Music is audible", "age_ms": 2000, "ttl_ms": 20000,
                      "metadata": {"candidate_tags": ["Jazz"], "candidate_tags_calibrated": False,
                                   "music_score_median": .7, "duration_ms": 4000}},
        }}
        packet = make_packet(snapshot)
        raw = attach_packet("What happened?", packet)
        clean, decoded = split_packet(raw)
        self.assertEqual(clean, "What happened?")
        self.assertEqual(strip_appendix(raw), clean)
        flattened = raw.replace("\n", " ")
        self.assertEqual(split_packet(flattened)[0], clean)
        self.assertEqual(strip_appendix(flattened), clean)
        self.assertEqual(split_packet(flattened)[1], decoded)
        self.assertNotIn("internal-frame", raw)
        self.assertNotIn("rms_dbfs", raw)
        self.assertNotIn("music_score_median", raw)
        rendered = render_packet(decoded, now=packet["generated_at"])
        self.assertIn("1.2", rendered)
        self.assertIn("Jazz", rendered)
        self.assertIn("гипотеза", rendered)

    def test_stale_audio_expires_and_old_scene_never_becomes_current(self):
        packet = make_packet({"channels": {
            "screen": {"text": "car", "age_ms": 0, "ttl_ms": 5000},
            "speech": {"text": "old words", "age_ms": 0, "ttl_ms": 20000},
        }})
        text = render_packet(packet, now=packet["generated_at"] + 30)
        self.assertIn("последнее наблюдение", text)
        self.assertNotIn("old words", text)
        self.assertEqual(render_packet(packet, now=packet["generated_at"] + 100), "")

    def test_live_fusion_publishes_atomic_handoff_and_invalidates_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "current-perception.json"
            fusion = PerceptionFusion(prompt_snapshot_path=path)
            fusion.note("screen", "new scene")
            first = json.loads(path.read_text("utf-8"))
            self.assertEqual(first["channels"]["screen"]["text"], "new scene")
            fusion.invalidate("screen")
            second = json.loads(path.read_text("utf-8"))
            self.assertTrue(second["channels"]["screen"]["possibly_outdated"])
            self.assertIn("сцена могла измениться", render_packet(second))

    def test_legacy_appendices_removed_whole_including_nested_metadata(self):
        old = 'Do the task.\n\n[ФОН ВОСПРИЯТИЯ СЕЙЧАС: [timing age_ms=1]\nscene [guess]]'
        self.assertEqual(strip_appendix(old), "Do the task.")
        self.assertEqual(strip_appendix("Keep [my brackets] in the message"), "Keep [my brackets] in the message")
