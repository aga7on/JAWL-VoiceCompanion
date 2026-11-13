import json
import threading
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.echo_guard import EchoGuard, is_self_tts_echo
from jawl_voicecompanion import turn_policy
from jawl_voicecompanion.duplex_cascade import (
    TOKEN_NO_VOICE,
    TOKEN_USER_INTERRUPTION,
    TOKEN_USER_BACKCHANNEL,
)


class EchoGuardUnitTests(unittest.TestCase):
    def test_exact_and_high_overlap_echo(self):
        ref = "Я сейчас проверяю логи и смотрю на состояние системы."
        # Substring / high overlap candidate
        self.assertTrue(is_self_tts_echo("проверяю логи и смотрю", ref))
        self.assertTrue(is_self_tts_echo("состояние системы", ref))

    def test_unrelated_speech_is_not_echo(self):
        ref = "Я сейчас проверяю логи и смотрю на состояние системы."
        self.assertFalse(is_self_tts_echo("какая сейчас погода на улице", ref))
        self.assertFalse(is_self_tts_echo("открой браузер и найди рецепт", ref))

    def test_interruption_keywords_never_suppressed_as_echo(self):
        ref = "Я говорю вам стой и подожди, но это просто фраза."
        # Even if reference contains "стой", user saying "стой" must barge in!
        self.assertFalse(is_self_tts_echo("стой подожди", ref))
        self.assertFalse(is_self_tts_echo("стоп хватит", ref))
        self.assertFalse(is_self_tts_echo("нет не надо", ref))

    def test_questions_never_suppressed_as_echo(self):
        ref = "Мы можем запустить этот процесс прямо сейчас."
        self.assertFalse(is_self_tts_echo("прямо сейчас?", ref))

    def test_short_candidate_is_not_echo(self):
        ref = "Да, конечно, я всё понял."
        # 1-word utterances are handled by backchannel policy, not echo guard
        self.assertFalse(is_self_tts_echo("да", ref))
        self.assertFalse(is_self_tts_echo("понял", ref))

    def test_bigram_consistency_enforced_for_three_words(self):
        ref = "красное яблоко лежало на круглом деревянном столе"
        # Candidate has 3 words from ref, but scrambled order: no bigram match
        self.assertFalse(is_self_tts_echo("столе яблоко деревянном", ref))
        # Candidate has real bigram from ref
        self.assertTrue(is_self_tts_echo("на круглом деревянном", ref))

    def test_echo_guard_lifecycle_and_ttl(self):
        guard = EchoGuard(ttl_seconds=0.2)
        guard.set_speaking_text("Привет, я голосовой помощник.")
        self.assertEqual(guard.get_reference_text(), "Привет, я голосовой помощник.")
        self.assertTrue(guard.is_echo("голосовой помощник"))

        # Wait for TTL to expire
        time.sleep(0.25)
        self.assertEqual(guard.get_reference_text(), "")
        self.assertFalse(guard.is_echo("голосовой помощник"))

        # Clear explicitly
        guard.set_speaking_text("Новая реплика.")
        guard.clear()
        self.assertEqual(guard.get_reference_text(), "")

    def test_echo_guard_counters(self):
        guard = EchoGuard()
        guard.record_suppressed_draft()
        guard.record_suppressed_turn()
        guard.record_suppressed_loopback()
        state = guard.state()
        self.assertEqual(state["suppressed_drafts"], 1)
        self.assertEqual(state["suppressed_turns"], 1)
        self.assertEqual(state["suppressed_loopback_chunks"], 1)


class TurnPolicyEchoTests(unittest.TestCase):
    def test_echo_candidate_during_speech_returns_ignore_echo(self):
        ref = "Я сейчас выполняю анализ вашего кода в проекте."
        candidate = "выполняю анализ вашего кода"

        decision = turn_policy.decide(
            candidate,
            silence_ms=100,
            assistant_speaking=True,
            reference_text=ref,
        )
        self.assertEqual(decision["duplex_action"], "ignore_echo")
        self.assertEqual(decision["duplex_token"], TOKEN_NO_VOICE)
        self.assertTrue(decision["echo_detected"])
        self.assertEqual(decision["action"], "listen")

    def test_barge_in_during_speech_returns_cancel_tts(self):
        ref = "Я сейчас выполняю анализ вашего кода в проекте."
        candidate = "стой, подожди секунду"

        decision = turn_policy.decide(
            candidate,
            silence_ms=100,
            assistant_speaking=True,
            reference_text=ref,
        )
        self.assertEqual(decision["duplex_action"], "cancel_tts")
        self.assertEqual(decision["duplex_token"], TOKEN_USER_INTERRUPTION)
        self.assertFalse(decision.get("echo_detected", False))

    def test_backchannel_during_speech_returns_ignore_backchannel(self):
        ref = "Я сейчас выполняю анализ вашего кода в проекте."
        candidate = "угу"

        decision = turn_policy.decide(
            candidate,
            silence_ms=100,
            assistant_speaking=True,
            reference_text=ref,
        )
        self.assertEqual(decision["duplex_action"], "ignore_backchannel")
        self.assertEqual(decision["duplex_token"], TOKEN_USER_BACKCHANNEL)
        self.assertFalse(decision.get("echo_detected", False))


class WebEchoGuardIntegrationTests(unittest.TestCase):
    def setUp(self):
        from jawl_voicecompanion.web import create_server
        from jawl_voicecompanion.gateway import TextGateway

        self.gateway = TextGateway()
        self.server = create_server(
            port=0,
            gateway=self.gateway,
            frontend_dir=Path(__file__).parents[1] / "frontend",
        )
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2.0)
        self.server.server_close()

    def _post(self, path: str, payload: dict):
        import urllib.request
        req = urllib.request.Request(
            self.base_url + path,
            json.dumps(payload).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "X-Companion-Session": self.server.session_token,
                "X-Companion-CSRF": self.server.csrf_token,
            },
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_draft_endpoint_suppresses_echo_and_returns_ignore_echo(self):
        # Set active speaking text in echo guard
        self.server.echo_guard.set_speaking_text("Я завершил проверку и всё готово к работе.")

        # Simulate streaming ASR snapshot having transcribed echoed words
        class FakeStreamingASR:
            def snapshot(self, **kwargs):
                return {"active": True, "text": "проверку и всё готово", "silence_ms": 150}

        self.server.streaming_asr = FakeStreamingASR()

        status, body = self._post(
            "/api/voice/draft",
            {"assistant_speaking": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body.get("echo_detected"))
        self.assertEqual(body["draft"], "")  # Draft is cleared so user UI doesn't show echo
        self.assertEqual(body["duplex_action"], "ignore_echo")
        self.assertGreaterEqual(self.server.echo_guard.state()["suppressed_drafts"], 1)

    def test_voice_end_suppresses_echo_turn_without_sending_to_brain(self):
        # Set active speaking text
        self.server.echo_guard.set_speaking_text("Файл успешно сохранён на диск.")

        # Simulate ASR returning echoed transcript
        class FakeASR:
            def finish_microphone(self, *args, **kwargs):
                return {"status": "ok", "text": "успешно сохранён на диск"}
            def finish(self, *args, **kwargs):
                return {"status": "ok", "text": "успешно сохранён на диск"}
            def close(self):
                pass

        class FakeVoiceMem:
            def close(self):
                pass

        self.server.voice_mem = FakeVoiceMem()
        self.server.asr = FakeASR()

        status, body = self._post(
            "/api/voice/end",
            {"session_id": "echo-test", "correlation_id": "c1"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body.get("filtered"), "self_tts_echo")
        self.assertEqual(body.get("transcript"), "")
        self.assertEqual(body.get("responses"), [])
        self.assertGreaterEqual(self.server.echo_guard.state()["suppressed_turns"], 1)


if __name__ == "__main__":
    unittest.main()
