"""Memory ownership: JAWL decides, the companion only observes and forgets.

These tests pin the boundary the redesign introduced:

* the companion can *offer* a candidate (JAWL's own event intake) but never
  writes ``structured_memories`` on its own;
* a candidate that does reach JAWL keeps honest provenance - trust level,
  evidence ids, observation class, retention tier, confidence as measured;
* when JAWL forgets or archives a record, the observations behind it are
  retired from the sensory history and from the ambient buffer, and stay
  retired after a restart.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.jawl_events import JawlEventFileSink  # noqa: E402
from jawl_voicecompanion.memory_policy import (  # noqa: E402
    RETENTION_TIERS,
    TRUST_OWNER_STATED,
    TRUST_UNVERIFIED,
    candidate_provenance,
    handoff_event,
    memory_key_for,
    observation_class,
    predicate_for,
    retention_tier_for,
)
from jawl_voicecompanion.sensory_history import SensoryHistoryStore  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


def _stop(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("test HTTP server thread did not stop")
    server.server_close()


class _FakeJawl:
    """Native control stub: records what the companion asked of JAWL."""

    token = "native-token"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.forgotten: list[tuple[str, str]] = []
        self.archived: list[tuple[str, str]] = []
        self.check_calls = 0

    def remember_memory(self, **payload):
        self.calls.append(payload)
        return {"status": "synchronized", "memory": {"is_success": True}}

    def forget_memory(self, memory_key: str, reason: str = ""):
        self.forgotten.append((memory_key, reason))
        return {"status": "synchronized"}

    def archive_memory(self, memory_key: str, reason: str = ""):
        self.archived.append((memory_key, reason))
        return {"status": "synchronized"}

    def structured_memory(self, kind=None, limit=50):
        self.check_calls += 1
        return {"configured": True, "status": "ok", "memory": {"memories": []}}


class MemoryPolicyTests(unittest.TestCase):
    def test_model_observation_never_becomes_a_fact_by_itself(self):
        provenance = candidate_provenance(
            {"summary": "на экране погоня", "confidence": 0.82, "source": "visual"},
            memory_key="ambient.episode.x",
            episode_id="x",
        )
        self.assertFalse(provenance["verified"])
        self.assertEqual(provenance["trust"], TRUST_UNVERIFIED)
        self.assertEqual(provenance["observation_class"], "screen_description")
        # JAWL's prompt shows "subject — predicate = value"; the caveat has to
        # live in the predicate or the agent would read a guess as a fact.
        self.assertEqual(predicate_for(verified=False), "episode_summary_unverified")
        self.assertEqual(predicate_for(verified=True), "episode_summary")

    def test_owner_confirmed_observation_keeps_long_retention(self):
        provenance = candidate_provenance(
            {"summary": "владелец просил напоминать про отчёт", "verified": True, "confidence": 1.0},
            memory_key="ambient.episode.y",
            episode_id="y",
        )
        self.assertEqual(provenance["trust"], TRUST_OWNER_STATED)
        self.assertEqual(
            retention_tier_for(verified=True, confidence=1.0, observation="ambient_speech"), "long"
        )
        self.assertEqual(
            retention_tier_for(verified=False, confidence=0.95, observation="screen_description"),
            "short",
        )
        self.assertIn(
            retention_tier_for(verified=False, confidence=0.4, observation="ambient_speech"),
            RETENTION_TIERS,
        )

    def test_observation_class_names_the_channel_not_the_meaning(self):
        self.assertEqual(observation_class({"stream": "screen"}), "screen_description")
        self.assertEqual(observation_class({"source": "visual"}), "screen_description")
        self.assertEqual(observation_class({"stream": "system_audio", "audio_kind": "music"}),
                         "music_observation")
        self.assertEqual(observation_class({"stream": "system_audio", "audio_kind": "speech"}),
                         "ambient_speech")
        self.assertEqual(observation_class({}), "ambient_observation")

    def test_handoff_event_is_a_proposal_with_evidence(self):
        episode = {
            "event_id": "ep-1",
            "payload": {
                "summary": "на экране погоня",
                "confidence": 0.82,
                "verified": False,
                "source": "visual",
                "source_event_ids": ["ev-1", "ev-2"],
                "observed_from": "2026-11-01T10:00:00Z",
                "observed_until": "2026-11-01T10:00:20Z",
            },
        }
        candidate = handoff_event(episode, memory_key=memory_key_for("ep-1"))
        self.assertEqual(candidate["type"], "MEMORY_CANDIDATE")
        payload = candidate["payload"]
        self.assertEqual(payload["memory_key"], "ambient.episode.ep-1")
        self.assertEqual(payload["source_event_ids"], ["ev-1", "ev-2"])
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["retention_tier"], "short")
        self.assertNotIn("remember", json.dumps(payload))  # a proposal, not a write


class SensoryHistoryRedactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "weekly-history.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_redaction_removes_events_and_moments(self):
        store = SensoryHistoryStore(self.path, enabled=True)
        first = store.record("visual", "на экране погоня", confidence=0.8, scene_id="s1")
        second = store.record("speech", "обсуждали отчёт", confidence=0.9)
        result = store.redact([first["event_id"]], reason="forgotten:ambient.episode.ep-1")
        self.assertEqual(result["status"], "redacted")
        text = store.context_text(seconds=3600)
        self.assertNotIn("погоня", text)
        self.assertIn("обсуждали отчёт", text)
        self.assertEqual(store.state()["redacted_event_count"], 1)
        self.assertNotEqual(second["event_id"], first["event_id"])

    def test_redaction_survives_a_reload(self):
        store = SensoryHistoryStore(self.path, enabled=True)
        recorded = store.record("visual", "переписка в личном окне", confidence=0.8, scene_id="s2")
        store.redact([recorded["event_id"]], reason="forgotten")
        reopened = SensoryHistoryStore(self.path, enabled=True)
        self.assertEqual(reopened.state()["redacted_event_count"], 1)
        self.assertNotIn("переписка в личном окне", reopened.context_text(seconds=3600))
        self.assertEqual(reopened.state()["recent_event_count"], 0)

    def test_shared_evidence_id_is_kept_verbatim(self):
        store = SensoryHistoryStore(self.path, enabled=True)
        recorded = store.record("visual", "смена сцены", event_id="evidence-42")
        self.assertEqual(recorded["event_id"], "evidence-42")


class AmbientRedactionTests(unittest.TestCase):
    def test_redact_drops_observations_and_derived_episodes(self):
        memory = AmbientMemoryBuffer(enabled=True)
        memory.ingest_visual("Важный дедлайн, запомни", confidence=0.95, event_id="ev-1")
        memory.triage()
        self.assertEqual(len(memory.episodes()), 1)
        result = memory.redact(["ev-1"], reason="forgotten:ambient.episode.ep-1")
        self.assertEqual(result["status"], "redacted")
        self.assertEqual(result["observations"], 1)
        self.assertEqual(result["episodes"], 1)
        self.assertEqual(memory.episodes(), [])
        self.assertEqual(memory.state()["observation_count"], 0)
        self.assertEqual(memory.state()["buffer_bytes"], 0)


class MemoryOwnershipHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.event_dir = root / "events"
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            jawl_event_dir=self.event_dir,
        )
        self.server.sensory_history = SensoryHistoryStore(
            root / "weekly-history.json", enabled=True, flush_interval_seconds=1
        )
        self.server.ambient_memory = AmbientMemoryBuffer(enabled=True)
        self.native = _FakeJawl()
        self.server.gateway.jawl_web = self.native
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
            "Content-Type": "application/json",
        }

    def tearDown(self):
        _stop(self.server, self.thread)
        self.tmp.cleanup()

    def post(self, path: str, payload: dict):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=self.headers,
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def get(self, path: str):
        request = Request(self.base + path, headers=self.headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def _candidate(self, text: str = "Важный дедлайн, запомни эту цель.") -> tuple[str, str]:
        evidence = f"ev-{time.time_ns()}"
        self.server.ambient_memory.ingest_visual(
            text, confidence=0.95, event_id=evidence, now=time.time()
        )
        self.server.sensory_history.record(
            "visual", text, confidence=0.95, event_id=evidence, verified=False
        )
        triaged = self.server.ambient_memory.triage()
        episode_id = triaged["episodes"][0]["event_id"]
        return episode_id, evidence

    def test_handoff_offers_a_candidate_and_never_writes_memory(self):
        episode_id, evidence = self._candidate()
        status, result = self.post(
            "/api/ambient-memory/handoff", {"episode_id": episode_id, "confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "handed_off")
        self.assertTrue(result["episode"]["payload"]["handed_off"])
        # JAWL was not asked to store anything: the agent decides.
        self.assertEqual(self.native.calls, [])

        written = list(self.event_dir.glob("*.json"))
        self.assertEqual(len(written), 1)
        event = json.loads(written[0].read_text(encoding="utf-8"))
        payload = event["payload"]
        self.assertEqual(payload["event_type"], "MEMORY_CANDIDATE")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["trust"], TRUST_UNVERIFIED)
        self.assertEqual(payload["source_event_ids"], [evidence])
        self.assertEqual(payload["memory_key"], memory_key_for(episode_id))
        self.assertIn("not a confirmed fact", event["message"])

        _, repeated = self.post(
            "/api/ambient-memory/handoff", {"episode_id": episode_id, "confirm": True}
        )
        self.assertEqual(repeated["status"], "already_handed_off")
        self.assertEqual(len(list(self.event_dir.glob("*.json"))), 1)

    def test_handoff_requires_confirmation(self):
        episode_id, _ = self._candidate()
        with self.assertRaises(HTTPError) as context:
            self.post("/api/ambient-memory/handoff", {"episode_id": episode_id})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_handoff_reports_when_jawl_intake_is_missing(self):
        self.server.candidate_sink = None
        episode_id, _ = self._candidate()
        with self.assertRaises(HTTPError) as context:
            self.post("/api/ambient-memory/handoff", {"episode_id": episode_id, "confirm": True})
        self.assertEqual(context.exception.code, 503)
        body = json.loads(context.exception.read().decode("utf-8"))
        context.exception.close()
        self.assertEqual(body["status"], "not_delivered")
        self.assertFalse(body["candidate"]["payload"]["verified"])
        # The candidate is still in the buffer and still unremembered.
        self.assertEqual(self.native.calls, [])
        self.assertFalse(
            self.server.ambient_memory.episode(episode_id)["payload"].get("handed_off", False)
        )

    def test_owner_override_keeps_honest_provenance(self):
        episode_id, evidence = self._candidate()
        _, result = self.post(
            "/api/ambient-memory/promote", {"episode_id": episode_id, "confirm": True}
        )
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["trust"], TRUST_UNVERIFIED)
        call = self.native.calls[0]
        self.assertEqual(call["predicate"], "episode_summary_unverified")
        self.assertEqual(call["retention_tier"], "short")
        self.assertAlmostEqual(call["confidence"], 0.95)
        provenance = call["provenance"]
        self.assertFalse(provenance["verified"])
        self.assertEqual(provenance["trust"], TRUST_UNVERIFIED)
        self.assertEqual(provenance["source_event_ids"], [evidence])
        self.assertEqual(provenance["ambient_episode_id"], episode_id)
        self.assertEqual(provenance["origin"], "jawl_voicecompanion.ambient")

    def test_forget_retires_the_observations_behind_the_record(self):
        episode_id, evidence = self._candidate()
        self.post("/api/ambient-memory/promote", {"episode_id": episode_id, "confirm": True})
        memory_key = memory_key_for(episode_id)
        self.assertIn("Важный дедлайн", self.server.sensory_history.context_text(seconds=3600))

        _, result = self.post(
            "/api/jawl/memory", {"operation": "forget", "memory_key": memory_key, "reason": "owner"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.native.forgotten[0][0], memory_key)
        redacted = result["redacted"]
        self.assertEqual(redacted["status"], "redacted")
        self.assertEqual(redacted["sensory_history"]["recent_events"], 1)
        self.assertGreaterEqual(redacted["ambient_memory"]["episodes"], 1)
        self.assertNotIn("Важный дедлайн", self.server.sensory_history.context_text(seconds=3600))
        self.assertEqual(self.server.ambient_memory.episodes(), [])
        self.assertTrue(evidence)

    def test_archive_uses_the_same_cascade(self):
        episode_id, _ = self._candidate()
        self.post("/api/ambient-memory/promote", {"episode_id": episode_id, "confirm": True})
        memory_key = memory_key_for(episode_id)
        _, result = self.post(
            "/api/jawl/memory", {"operation": "archive", "memory_key": memory_key}
        )
        self.assertEqual(self.native.archived[0][0], memory_key)
        self.assertEqual(result["redacted"]["status"], "redacted")

    def test_ambient_payload_declares_ownership_and_handoff_state(self):
        status, payload = self.get("/api/ambient-memory")
        self.assertEqual(status, 200)
        self.assertTrue(payload["handoff"]["available"])
        self.assertFalse(payload["handoff"]["writes_memory"])
        self.assertEqual(payload["memory_policy"]["writer"], "jawl")
        self.assertEqual(payload["memory_policy"]["handoff_event_type"], "MEMORY_CANDIDATE")


class JailEventSinkTests(unittest.TestCase):
    def test_candidate_sink_writes_a_bounded_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = JawlEventFileSink(directory)
            candidate = handoff_event(
                {"event_id": "ep-9", "payload": {"summary": "музыка: lofi", "confidence": 0.5,
                                                "source": "system_audio", "source_event_ids": ["ev-9"]}},
                memory_key=memory_key_for("ep-9"),
            )
            result = sink.publish_candidate(candidate)
            self.assertEqual(result["status"], "delivered")
            event = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(event["payload"]["source"], "jawl_voicecompanion")
            self.assertEqual(event["payload"]["event_type"], "MEMORY_CANDIDATE")
            self.assertFalse(event["payload"]["raw_audio_persisted"])

    def test_candidate_sink_rejects_anything_else(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = JawlEventFileSink(directory)
            with self.assertRaises(ValueError):
                sink.publish_candidate({"type": "CHAT_MESSAGE", "payload": {"summary": "x"}})


if __name__ == "__main__":
    unittest.main()
