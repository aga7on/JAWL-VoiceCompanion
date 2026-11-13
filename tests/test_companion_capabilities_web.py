import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jawl_voicecompanion.cowatch_engine import CoWatchEngine, CharacterOpinionTracker, MediaNarrativeTracker
from jawl_voicecompanion.game_embodied import CompanionRole, GameEmbodiedLayer, Player2CompanionController
from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.memory_consolidation import (
    OfflineConsolidator,
    SocialGraphConsolidator,
    UserPersonaHypothesisEngine,
)
from jawl_voicecompanion.music_perception import (
    DynamicMusicFlowTracker,
    MusicCritiqueEngine,
    MusicPerceptionAnalyzer,
)
from jawl_voicecompanion.web import create_server


def _stop_test_http_server(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("test HTTP server thread did not stop")
    server.server_close()


class CompanionWebUnconfiguredTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.session_headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }
    def tearDown(self):
        _stop_test_http_server(self.server, self.thread)

    def _get_json(self, path, headers=None):
        hdr = self.session_headers if headers is None else headers
        req = Request(f"{self.base}{path}", headers=hdr)
        with urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path, payload, headers=None):
        hdr = {"Content-Type": "application/json", **(self.session_headers if headers is None else headers)}
        req = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=hdr,
        )
        with urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    def test_music_endpoints_unconfigured(self):
        status = self._get_json("/api/music/status")
        self.assertFalse(status["configured"])
        self.assertFalse(status["active"])

        critique = self._get_json("/api/music/critique")
        self.assertFalse(critique["configured"])
        self.assertIsNone(critique["critique"])

        with self.assertRaises(HTTPError) as ctx:
            self._post_json("/api/music/feed", {"rms_dbfs": -20.0})
        self.assertEqual(ctx.exception.code, 503)

    def test_cowatch_endpoints_unconfigured(self):
        narrative = self._get_json("/api/cowatch/narrative")
        self.assertFalse(narrative["configured"])

        opinions = self._get_json("/api/cowatch/opinion")
        self.assertFalse(opinions["configured"])
        self.assertEqual(opinions["opinions"], {})

        with self.assertRaises(HTTPError) as ctx:
            self._post_json("/api/cowatch/opinion", {"character": "Alice", "act": "Betrayal"})
        self.assertEqual(ctx.exception.code, 503)

    def test_persona_endpoints_unconfigured(self):
        hyp = self._get_json("/api/persona/hypotheses")
        self.assertFalse(hyp["configured"])
        self.assertEqual(hyp["hypotheses"], [])

        sg = self._get_json("/api/persona/social-graph")
        self.assertFalse(sg["configured"])

        with self.assertRaises(HTTPError) as ctx:
            self._post_json("/api/persona/hypotheses", {"trait_key": "coding_style", "inferred_value": "pythonic"})
        self.assertEqual(ctx.exception.code, 503)

        with self.assertRaises(HTTPError) as ctx:
            self._post_json(
                "/api/persona/social-graph",
                {"source": "user", "target": "Bob", "relation_type": "friend"},
            )
        self.assertEqual(ctx.exception.code, 503)

    def test_player2_endpoints_unconfigured(self):
        p2 = self._get_json("/api/game/player2")
        self.assertFalse(p2["configured"])
        self.assertFalse(p2["active"])

        with self.assertRaises(HTTPError) as ctx:
            self._post_json("/api/game/player2/role", {"role": "wingman"})
        self.assertEqual(ctx.exception.code, 503)

        with self.assertRaises(HTTPError) as ctx:
            self._post_json("/api/game/player2/step", {"player_hp": 80.0})
        self.assertEqual(ctx.exception.code, 503)
    def test_endpoints_require_session(self):
        for path in (
            "/api/music/status",
            "/api/music/critique",
            "/api/cowatch/narrative",
            "/api/cowatch/opinion",
            "/api/persona/hypotheses",
            "/api/persona/social-graph",
            "/api/game/player2",
        ):
            with self.subTest(path=path):
                req = Request(f"{self.base}{path}")
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(req, timeout=3)
                self.assertEqual(ctx.exception.code, 403)


class CompanionWebConfiguredTests(unittest.TestCase):
    def setUp(self):
        music = MusicPerceptionAnalyzer()
        cowatch = CoWatchEngine()
        consolidator = OfflineConsolidator()
        embodied = GameEmbodiedLayer()
        embodied.enable_player2(role="wingman")

        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            music_analyzer=music,
            cowatch_engine=cowatch,
            offline_consolidator=consolidator,
            game_embodied=embodied,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.session_headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }
    def tearDown(self):
        _stop_test_http_server(self.server, self.thread)

    def _get_json(self, path, headers=None):
        hdr = self.session_headers if headers is None else headers
        req = Request(f"{self.base}{path}", headers=hdr)
        with urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path, payload, headers=None):
        hdr = {"Content-Type": "application/json", **(self.session_headers if headers is None else headers)}
        req = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=hdr,
        )
        with urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    def test_music_flow_feed_and_critique(self):
        status = self._get_json("/api/music/status")
        self.assertTrue(status["configured"])

        status_code, feed_res = self._post_json(
            "/api/music/feed",
            {
                "timestamp": 1.0,
                "rms_dbfs": -12.0,
                "spectral_centroid_hz": 2400.0,
                "valence": 0.6,
                "arousal": 0.8,
                "harmonicity": 0.7,
                "key": "G#m",
                "bpm": 128.0,
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(feed_res["ok"])

        critique = self._get_json("/api/music/critique")
        self.assertTrue(critique["configured"])
        self.assertIn("critique", critique)

    def test_cowatch_opinion_and_narrative(self):
        status_code, op_res = self._post_json(
            "/api/cowatch/opinion",
            {
                "character": "Levi",
                "act": "Takes out Beast Titan with pinpoint blades",
                "valence_delta": 0.8,
                "morality": 0.5,
                "competence_delta": 0.4,
                "voice_remark": "Absolute perfection!",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(op_res["ok"])
        self.assertEqual(op_res["opinion"]["character_name"], "Levi")
        self.assertAlmostEqual(op_res["opinion"]["competence"], 0.9, places=2)

        opinions = self._get_json("/api/cowatch/opinion")
        self.assertTrue(opinions["configured"])
        self.assertIn("Levi", opinions["opinions"])

        narrative = self._get_json("/api/cowatch/narrative")
        self.assertTrue(narrative["configured"])
        self.assertIn("context", narrative)

    def test_persona_hypotheses_and_social_graph(self):
        status_code, hyp_res = self._post_json(
            "/api/persona/hypotheses",
            {
                "trait_key": "taste_in_music",
                "inferred_value": "Synthwave & Melodic Cyberpunk",
                "confidence": 0.88,
                "evidence_count": 4,
                "rationale": "Consistently plays Kavinsky and Perturbator at high energy.",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(hyp_res["ok"])
        self.assertEqual(hyp_res["hypothesis"]["trait_key"], "taste_in_music")

        hyp_list = self._get_json("/api/persona/hypotheses")
        self.assertTrue(hyp_list["configured"])
        self.assertEqual(len(hyp_list["hypotheses"]), 1)
        self.assertEqual(hyp_list["hypotheses"][0]["trait_key"], "taste_in_music")

        status_code, rel_res = self._post_json(
            "/api/persona/social-graph",
            {
                "source": "user",
                "target": "Mentor_Elena",
                "relation_type": "mentor",
                "affinity_delta": 0.5,
                "trust_delta": 0.4,
                "note": "Guided architectural review",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(rel_res["ok"])
        self.assertEqual(rel_res["relation"]["target"], "Mentor_Elena")

        sg = self._get_json("/api/persona/social-graph")
        self.assertTrue(sg["configured"])
        self.assertIn("entities", sg["graph"])
        self.assertIn("relationships", sg["graph"])
        self.assertEqual(len(sg["graph"]["relationships"]), 1)

    def test_player2_controller_role_and_step(self):
        p2_state = self._get_json("/api/game/player2")
        self.assertTrue(p2_state["configured"])
        self.assertEqual(p2_state["role"], "wingman")

        status_code, role_res = self._post_json("/api/game/player2/role", {"role": "guardian"})
        self.assertEqual(status_code, 200)
        self.assertEqual(role_res["role"], "guardian")

        status_code, step_res = self._post_json(
            "/api/game/player2/step",
            {
                "player_hp": 30.0,
                "player_max_hp": 100.0,
                "companion_hp": 90.0,
                "companion_max_hp": 100.0,
                "target_threat": 0.85,
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(step_res["ok"])
        self.assertIn("decision", step_res)
        self.assertEqual(step_res["decision"]["role"], "guardian")
        self.assertIsNotNone(step_res["decision"]["speech_callout"])
