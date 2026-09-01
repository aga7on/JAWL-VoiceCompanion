import asyncio
import base64
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from services.voicemem_sidecar import VoiceMemSidecar  # noqa: E402
from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient  # noqa: E402


class VoiceMemSidecarTests(unittest.TestCase):
    def test_partial_and_final_events_are_bounded_and_correlated(self):
        streams = []

        class FakeStream:
            async def feed_partial(self, text, ended=False):
                return SimpleNamespace(
                    text=text,
                    turn=SimpleNamespace(text=text) if ended else None,
                    memory_context="memory hint",
                    emotion="спокойствие",
                    speaker_id="user-1",
                )

        def factory(_session_id):
            stream = FakeStream()
            streams.append(stream)
            return stream

        sidecar = VoiceMemSidecar(factory)
        partial = asyncio.run(sidecar.handle({
            "request_id": "r1", "type": "feed_partial", "session_id": "s1",
            "text": "проверь", "ended": False,
        }))
        final = asyncio.run(sidecar.handle({
            "request_id": "r2", "type": "feed_partial", "session_id": "s1",
            "text": "проверь редактор", "ended": True,
        }))
        self.assertEqual(partial[0]["type"], "USER_PARTIAL")
        self.assertEqual(final[0]["type"], "USER_PARTIAL")
        self.assertEqual(final[1]["type"], "VOICE_TURN")
        self.assertEqual(final[1]["request_id"], "r2")
        self.assertEqual(final[1]["payload"]["affect"], {"label": "спокойствие"})
        self.assertEqual(sidecar.health()["streams"], 1)
        self.assertEqual(len(streams), 1)

    def test_invalid_request_degrades_without_exception(self):
        sidecar = VoiceMemSidecar(lambda _session_id: None)
        result = asyncio.run(sidecar.handle({"type": "feed_partial", "ended": "yes"}))
        self.assertEqual(result[0]["type"], "VOICE_DEGRADED")
        self.assertEqual(result[0]["payload"]["reason"], "ended_must_be_boolean")

    def test_pcm16_audio_produces_partial_and_final_events(self):
        class FakeStream:
            async def feed(self, pcm_bytes):
                text = "голосовой e2e"
                return SimpleNamespace(
                    text=text,
                    turn=SimpleNamespace(text=text) if pcm_bytes == b"final!" else None,
                    memory_context="",
                    emotion="",
                    speaker_id="",
                )

        sidecar = VoiceMemSidecar(lambda _session_id: FakeStream())
        result = asyncio.run(sidecar.handle({
            "request_id": "audio-1", "type": "feed_audio", "session_id": "s1",
            "sample_rate": 16000, "channels": 1,
            "pcm16_base64": base64.b64encode(b"final!").decode("ascii"),
        }))
        self.assertEqual([event["type"] for event in result], ["USER_PARTIAL", "VOICE_TURN"])
        self.assertEqual(result[1]["payload"]["text"], "голосовой e2e")

    def test_pcm16_audio_rejects_wrong_rate(self):
        sidecar = VoiceMemSidecar(lambda _session_id: None)
        result = asyncio.run(sidecar.handle({
            "request_id": "audio-2", "type": "feed_audio", "session_id": "s1",
            "sample_rate": 24000, "pcm16_base64": base64.b64encode(b"12").decode("ascii"),
        }))
        self.assertEqual(result[0]["type"], "VOICE_DEGRADED")
        self.assertEqual(result[0]["payload"]["reason"], "sample_rate does not match the sidecar input rate")

    def test_missing_runtime_is_a_degraded_event(self):
        def unavailable(_session_id):
            raise ImportError("VoiceMem is not installed")

        sidecar = VoiceMemSidecar(unavailable)
        result = asyncio.run(sidecar.handle({
            "type": "feed_partial", "session_id": "s1", "text": "проверка", "ended": True,
        }))
        self.assertEqual(result[0]["type"], "VOICE_DEGRADED")
        self.assertEqual(sidecar.health()["status"], "degraded")

    def test_stdio_test_stub_runs_as_a_process(self):
        root = Path(__file__).parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        proc = subprocess.Popen(
            [sys.executable, str(root / "services" / "voicemem_sidecar.py"), "--test-stub"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            proc.stdin.write(json.dumps({"type": "health"}) + "\n")
            proc.stdin.write(json.dumps({
                "request_id": "r1", "type": "feed_partial", "session_id": "s1",
                "text": "тест", "ended": True,
            }) + "\n")
            proc.stdin.flush()
            health = json.loads(proc.stdout.readline())
            health_complete = json.loads(proc.stdout.readline())
            partial = json.loads(proc.stdout.readline())
            final = json.loads(proc.stdout.readline())
            self.assertEqual(health["type"], "health")
            self.assertEqual(health_complete["type"], "request_complete")
            self.assertEqual(partial["type"], "USER_PARTIAL")
            self.assertEqual(final["type"], "VOICE_TURN")
        finally:
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.terminate()
            proc.wait(timeout=3)

    def test_client_recovers_after_sidecar_restart(self):
        client = VoiceMemProcessClient(sys.executable, args=("--test-stub",), timeout_seconds=2)
        try:
            self.assertEqual(client.feed_partial("первый")[0]["type"], "USER_PARTIAL")
            process = client._process
            self.assertIsNotNone(process)
            process.terminate()
            process.wait(timeout=3)
            if process.stdin is not None:
                process.stdin.close()
            if client._reader is not None:
                client._reader.join(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
            self.assertEqual(client.feed_partial("второй")[0]["type"], "USER_PARTIAL")
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
