"""End-to-end practical scenario for history lifecycle and controlled forgetting.

Scenario:
1. Ingest observations from two independent scenes/sources:
   - Scene A (IDE / work): "Editing sensory history and cognitive core in VSCode"
   - Scene B (Browser / confidential): "Confidential project Orion financial briefing"
2. Triage into episodes and persist in SensoryHistoryStore.
3. Verify both scenes appear in recent context and hourly timeline.
4. Issue forget/redaction for Scene B (Orion confidential data).
5. Reload stores from persistent disk storage (simulating service restart).
6. Query past:
   - Forgotten data (Scene B / Orion) must NEVER return in recent, hour, or week summaries.
   - Replay of redacted event ID must be suppressed.
   - Neighboring scene (Scene A / VSCode) must remain completely intact with full provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from jawl_voicecompanion.sensory_history import SensoryHistoryStore
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory
from jawl_voicecompanion.narrative_consolidator import NarrativeConsolidator
from PIL import Image


class HistoryLifecycleEndToEndTest(unittest.TestCase):
    def test_two_sources_episode_forget_one_reload_and_query_past(self):
        with tempfile.TemporaryDirectory(prefix="jawl-e2e-history-") as temp_dir:
            dir_path = Path(temp_dir)
            history_file = dir_path / "sensory_history.json"

            t0 = 1_700_000_000.0
            clock_time = [t0]

            def clock() -> float:
                return clock_time[0]

            history = SensoryHistoryStore(
                history_file,
                enabled=True,
                clock=clock,
                flush_interval_seconds=1.0,
            )
            ambient = AmbientMemoryBuffer(
                enabled=True,
                episode_window_seconds=300.0,
                max_observations=256,
            )
            visual_db = dir_path / "lancedb"
            visual_cache = dir_path / "cache_img"
            visual_mem = EpisodicVisualMemory(db_path=visual_db, image_cache_dir=visual_cache)
            narrative_file = dir_path / "narrative.json"
            narrative = NarrativeConsolidator(
                episodic_memory=visual_mem,
                storage_path=narrative_file,
            )

            # --- Step 1: Ingest two independent scenes/sources ---
            # Scene A: Work / IDE
            eid_work_1 = "work-evt-001"
            eid_work_2 = "work-evt-002"
            img_work = Image.new("RGB", (32, 32), color="green")
            v_res_work = visual_mem.ingest_keyframe(
                img_work,
                scene_id="scene-work-ide",
                summary="VSCode code editing",
                extra_metadata={"event_id": eid_work_1},
            )
            ambient.ingest_visual(
                "Editing sensory history and cognitive core in VSCode",
                confidence=0.85,
                source_app="vscode",
                event_id=eid_work_1,
                now=clock_time[0],
            )
            history.record(
                "visual",
                "Editing sensory history and cognitive core in VSCode",
                observed_at=clock_time[0],
                source="vscode",
                scene_id="scene-work-ide",
                event_id=eid_work_1,
            )

            clock_time[0] += 10.0
            ambient.ingest_system_audio(
                "Refactoring memory pipeline and cascade redaction",
                confidence=0.9,
                source_app="vscode",
                event_id=eid_work_2,
                now=clock_time[0],
            )
            history.record(
                "speech",
                "Refactoring memory pipeline and cascade redaction",
                observed_at=clock_time[0],
                source="vscode",
                scene_id="scene-work-ide",
                event_id=eid_work_2,
            )
            narrative.feed_subtitle("Рефакторим когнитивное ядро в VSCode", speaker="Developer")
            narrative.feed_keyframe("scene-work-ide", v_res_work["image_path"], summary="VSCode editing")
            narrative._episode_logs.append("12:00 — Разработка и рефакторинг когнитивного ядра в VSCode")
            narrative._character_cards["Разработчик"] = {
                "name": "Разработчик",
                "traits": ["пишет код", "VSCode"],
                "keyframe_id": Path(v_res_work["image_path"]).name,
            }

            # Scene B: Browser / Confidential Orion briefing
            clock_time[0] += 30.0
            eid_conf_1 = "conf-evt-101"
            eid_conf_2 = "conf-evt-102"
            img_conf = Image.new("RGB", (32, 32), color="red")
            v_res_conf = visual_mem.ingest_keyframe(
                img_conf,
                scene_id="scene-private-briefing",
                summary="Confidential project Orion financial briefing document",
                extra_metadata={"event_id": eid_conf_1},
            )
            ambient.ingest_visual(
                "Confidential project Orion financial briefing document",
                confidence=0.88,
                source_app="chrome",
                event_id=eid_conf_1,
                now=clock_time[0],
            )
            history.record(
                "visual",
                "Confidential project Orion financial briefing document",
                observed_at=clock_time[0],
                source="chrome",
                scene_id="scene-private-briefing",
                event_id=eid_conf_1,
            )

            clock_time[0] += 10.0
            ambient.ingest_system_audio(
                "Orion budget allocation discussion and private roadmap",
                confidence=0.92,
                source_app="chrome",
                event_id=eid_conf_2,
                now=clock_time[0],
            )
            history.record(
                "speech",
                "Orion budget allocation discussion and private roadmap",
                observed_at=clock_time[0],
                source="chrome",
                scene_id="scene-private-briefing",
                event_id=eid_conf_2,
            )
            narrative.feed_subtitle("Секретный брифинг по проекту Orion", speaker="Manager")
            narrative.feed_keyframe("scene-private-briefing", v_res_conf["image_path"], summary="Orion Briefing")
            narrative._episode_logs.append("14:00 — Секретный брифинг по проекту Orion (eid: conf-evt-101)")
            narrative._character_cards["Куратор Orion"] = {
                "name": "Куратор Orion",
                "traits": ["бюджет", "секретно"],
                "keyframe_id": Path(v_res_conf["image_path"]).name,
            }
            narrative._save()

            # Flush history to disk
            history.flush()

            # --- Step 2: Ambient triage creates episodes with full provenance ---
            triage_res = ambient.triage(now=clock_time[0], max_items=256)
            self.assertEqual(triage_res["status"], "processed")
            episodes = ambient.episodes(now=clock_time[0])
            self.assertGreaterEqual(len(episodes), 1)

            # Find the episode containing Scene B
            conf_episode = next(
                (ep for ep in episodes if eid_conf_1 in ep["payload"]["source_event_ids"]),
                None,
            )
            self.assertIsNotNone(conf_episode)
            self.assertIn("Orion", conf_episode["payload"]["summary"])

            # --- Step 3: Verify all scenes are visible before redaction ---
            context_recent = history.context_text(seconds=3600)
            self.assertIn("VSCode", context_recent)
            self.assertIn("Orion", context_recent)

            context_week = history.context_text(seconds=7 * 86400, include_week=True)
            self.assertIn("VSCode", context_week)
            self.assertIn("Orion", context_week)

            path_work = Path(v_res_work["image_path"])
            path_conf = Path(v_res_conf["image_path"])
            self.assertTrue(path_work.exists())
            self.assertTrue(path_conf.exists())
            self.assertEqual(visual_mem.count(), 2)

            # --- Step 4: Forget/Redact Scene B (Orion) across all memory stores ---
            # Redact by the confidential event ids
            redact_hist_res = history.redact([eid_conf_1, eid_conf_2], reason="GDPR / privacy request")
            self.assertEqual(redact_hist_res["status"], "redacted")

            # Cascade redaction in ambient memory
            redact_amb_res = ambient.redact([eid_conf_1, eid_conf_2], reason="GDPR / privacy request")
            self.assertEqual(redact_amb_res["status"], "redacted")
            self.assertGreaterEqual(redact_amb_res["episodes"], 1)

            # Cascade redaction in visual memory
            redact_vis_res = visual_mem.redact([eid_conf_1, eid_conf_2], reason="GDPR / privacy request")
            self.assertEqual(redact_vis_res["status"], "redacted")
            self.assertGreaterEqual(redact_vis_res["deleted_files"], 1)
            self.assertFalse(path_conf.exists(), "Confidential image file must be unlinked!")
            self.assertTrue(path_work.exists(), "Work image file must remain intact!")

            # Cascade redaction in narrative consolidator
            redact_narr_res = narrative.redact(
                [eid_conf_1, eid_conf_2, Path(v_res_conf["image_path"]).name, "Orion"],
                reason="GDPR / privacy request",
            )
            self.assertEqual(redact_narr_res["status"], "redacted")
            self.assertGreaterEqual(redact_narr_res["deleted_logs"], 1)
            self.assertGreaterEqual(redact_narr_res["deleted_cards"], 1)

            # Check that ambient memory removed the Orion episode
            episodes_after = ambient.episodes(now=clock_time[0])
            self.assertFalse(any("Orion" in ep["payload"]["summary"] for ep in episodes_after))

            # --- Step 5: Reload all stores from disk (simulate restart) ---
            history.flush()
            reloaded_history = SensoryHistoryStore(
                history_file,
                enabled=True,
                clock=clock,
            )
            reloaded_visual = EpisodicVisualMemory(db_path=visual_db, image_cache_dir=visual_cache)
            reloaded_narrative = NarrativeConsolidator(storage_path=narrative_file)

            # --- Step 6: Query past after reload ---
            # Narrative consolidator logs & cards check
            self.assertEqual(len(reloaded_narrative._episode_logs), 1)
            self.assertIn("VSCode", reloaded_narrative._episode_logs[0])
            self.assertNotIn("Orion", reloaded_narrative._episode_logs[0])
            self.assertIn("Разработчик", reloaded_narrative._character_cards)
            self.assertNotIn("Куратор Orion", reloaded_narrative._character_cards)
            # Recent context check
            reloaded_recent = reloaded_history.context_text(seconds=3600)
            self.assertNotIn("Orion", reloaded_recent, "Forgotten Orion text must NOT appear in recent context!")
            self.assertIn("VSCode", reloaded_recent, "Neighboring VSCode scene must remain in recent context!")

            # Weekly / hourly summary check
            reloaded_week = reloaded_history.context_text(seconds=7 * 86400, include_week=True)
            self.assertNotIn("Orion", reloaded_week, "Forgotten Orion text must NOT appear in week context!")
            self.assertIn("VSCode", reloaded_week, "Neighboring VSCode scene must remain in week context!")

            # Visual memory count and retrieval after reload
            self.assertEqual(reloaded_visual.count(), 1)
            vis_hits = reloaded_visual.search_visual("Orion financial", top_k=5)
            self.assertFalse(any("Orion" in hit.get("summary", "") for hit in vis_hits))
            self.assertTrue(any("VSCode" in hit.get("summary", "") for hit in vis_hits))

            # Focused lookback query
            reloaded_focus = reloaded_history.context_text(
                focus_seconds_ago=30.0,
                focus_window_seconds=120.0,
            )
            self.assertNotIn("Orion", reloaded_focus, "Forgotten Orion text must NOT appear in focused context!")

            # Replay attempt check: re-recording redacted ID must be suppressed
            replay_res = reloaded_history.record(
                "visual",
                "Replaying confidential project Orion financial briefing document",
                observed_at=clock_time[0],
                source="chrome",
                scene_id="scene-private-briefing",
                event_id=eid_conf_1,
            )
            self.assertEqual(replay_res["status"], "suppressed")
            self.assertEqual(replay_res["reason"], "redacted_event")


if __name__ == "__main__":
    unittest.main()
