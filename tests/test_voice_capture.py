import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.asr import UtteranceBuffer  # noqa: E402
from jawl_voicecompanion.config_hub import ConfigHub  # noqa: E402
from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient  # noqa: E402
from jawl_voicecompanion.voice_capture import (  # noqa: E402
    CaptureLeaseError,
    VoiceCaptureLease,
    VoiceCaptureSettings,
)
from jawl_voicecompanion.web import create_server  # noqa: E402


class CaptureLeaseTests(unittest.TestCase):
    def test_only_one_concurrent_owner_acquires(self):
        lease = VoiceCaptureLease()
        barrier = threading.Barrier(8)
        results = []

        def acquire(index):
            barrier.wait()
            try:
                lease.acquire("desktop" if index % 2 else "native", str(index))
                results.append("acquired")
            except CaptureLeaseError:
                results.append("busy")

        threads = [threading.Thread(target=acquire, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(results.count("acquired"), 1)
        self.assertEqual(results.count("busy"), 7)

    def test_lease_renews_expires_and_requires_matching_identity(self):
        lease = VoiceCaptureLease()
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=100.0):
            lease.acquire("desktop", "cap-1")
            with self.assertRaises(CaptureLeaseError):
                lease.renew("native", "cap-1")
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=114.0):
            self.assertEqual(lease.state()["owner"], "desktop")
            lease.renew("desktop", "cap-1")
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=130.0):
            self.assertIsNone(lease.state()["owner"])

    def test_stream_authorization_preserves_only_unclaimed_legacy_path(self):
        lease = VoiceCaptureLease()
        lease.authorize_stream({"session_id": "legacy"})
        lease.acquire("native", "native-1")
        for payload in ({}, {"capture_id": "wrong"}):
            with self.subTest(payload=payload), self.assertRaises(CaptureLeaseError):
                lease.authorize_stream(payload)
        lease.authorize_stream({"owner": "native", "capture_id": "native-1"})

    def test_release_cancels_only_the_old_capture_even_if_same_identity_reacquires(self):
        lease = VoiceCaptureLease()
        lease.acquire("desktop", "cap-1")
        old = lease.authorize_stream({"capture_id": "cap-1"})
        self.assertFalse(old.is_set())
        lease.release("desktop", "cap-1")
        self.assertTrue(old.is_set())
        lease.acquire("desktop", "cap-1")
        new = lease.authorize_stream({"capture_id": "cap-1"})
        self.assertIsNot(old, new)
        self.assertFalse(new.is_set())
        self.assertTrue(old.is_set())

    def test_lease_cancellation_expires_without_a_state_poll(self):
        lease = VoiceCaptureLease()
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=100.0):
            lease.acquire("desktop", "cap-1")
            token = lease.authorize_stream({"capture_id": "cap-1"})
            self.assertFalse(token.is_set())
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=115.0):
            self.assertTrue(token.is_set())

    def test_renew_and_idempotent_acquire_extend_the_same_cancellation_token(self):
        lease = VoiceCaptureLease()
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=100.0):
            lease.acquire("desktop", "cap-1")
            token = lease.authorize_stream({"capture_id": "cap-1"})
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=114.0):
            lease.renew("desktop", "cap-1")
            self.assertIs(token, lease.authorize_stream({"capture_id": "cap-1"}))
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=128.0):
            lease.acquire("desktop", "cap-1")
            self.assertFalse(token.is_set())
        with patch("jawl_voicecompanion.voice_capture.time.monotonic", return_value=142.0):
            self.assertFalse(token.is_set())

    def test_config_rejects_nonfinite_and_bounds_numeric_values(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            VoiceCaptureSettings.from_mapping({"gate_open": float("nan")})
        with self.assertRaisesRegex(ValueError, "finite"):
            VoiceCaptureSettings.from_request({"silence_ms": float("inf")})


class _VoiceMemStub(VoiceMemProcessClient):
    def __init__(self):
        pass

    def close(self):
        return None

    def feed_audio(self, *_args, **_kwargs):
        return []

    def end_audio(self, *_args, **_kwargs):
        return []


class CaptureHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_dir = Path(self.tmp.name) / "config"
        self.config_dir.mkdir()
        self.interfaces_file = self.config_dir / "interfaces.yaml"
        self.interfaces_file.write_bytes(
            b"# top comment\r\nvoice:\r\n  enabled: true # keep voice comment\r\n# outside comment\r\nweb:\r\n  enabled: true\r\n"
        )
        self.env_file = Path(self.tmp.name) / ".env"
        self.hub = ConfigHub(self.config_dir, env_file=self.env_file)
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            voice_mem=_VoiceMemStub(),
            config_hub=self.hub,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, path, payload=None, *, headers=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            self.base + path,
            data=body,
            headers={**(self.headers if headers is None else headers), **({"Content-Type": "application/json"} if body else {})},
            method="GET" if body is None else "POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_capture_route_is_session_guarded_and_reports_bounded_config(self):
        status, body = self.request("/api/voice/capture", headers={})
        self.assertEqual(status, 403)
        status, body = self.request("/api/voice/capture")
        self.assertEqual(status, 200)
        self.assertEqual(body["owner"], None)
        self.assertEqual(body["gate_open"], 0.02)
        self.assertEqual(body["gate_close"], 0.012)
        self.assertEqual(body["silence_ms"], 1_200)
        self.assertEqual(body["pre_roll_ms"], 120)
        self.assertEqual(body["settings"], {
            "gate_open": 0.02,
            "gate_close": 0.012,
            "silence_ms": 1_200,
            "pre_roll_ms": 120,
        })
        self.assertTrue(body["settings_writable"])
        self.assertTrue(body["revision"])
        self.assertEqual(body["lease_ttl_ms"], 15_000)
        self.assertNotIn("csrf_token", body)
        self.assertNotIn("session_token", body)

    def test_http_acquire_conflict_release_and_audio_legacy_compatibility(self):
        audio = {"pcm16_base64": "AAA=", "sample_rate": 16000, "channels": 1, "session_id": "legacy"}
        status, body = self.request("/api/voice/audio", audio)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/voice/end", {"session_id": "legacy"})[0], 200)
        status, body = self.request("/api/voice/capture", {"action": "acquire", "owner": "desktop", "capture_id": "desk-1"})
        self.assertEqual(status, 200)
        status, body = self.request("/api/voice/capture", {"action": "acquire", "owner": "native", "capture_id": "native-1"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "capture_busy")
        status, body = self.request("/api/voice/audio", audio)
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "capture_lease_lost")
        audio.update(owner="desktop", capture_id="desk-1")
        self.assertEqual(self.request("/api/voice/audio", audio)[0], 200)
        self.assertEqual(self.request("/api/voice/end", {"session_id": "legacy"})[0], 409)
        end = {"session_id": "legacy", "owner": "desktop", "capture_id": "wrong"}
        self.assertEqual(self.request("/api/voice/end", end)[0], 409)
        end["capture_id"] = "desk-1"
        self.assertEqual(self.request("/api/voice/end", end)[0], 200)
        status, body = self.request("/api/voice/capture", {"action": "release", "owner": "desktop", "capture_id": "desk-1"})
        self.assertEqual(status, 200)

    def test_http_release_cancels_inflight_asr_without_admitting_a_jawl_turn(self):
        entered = threading.Event()
        tokens = []

        class CooperativeTranscriber:
            def transcribe(self, wav_bytes, *, cancel_event):
                tokens.append(cancel_event)
                entered.set()
                for _ in range(400):
                    if cancel_event.is_set():
                        break
                    threading.Event().wait(0.005)
                return "late ASR must not reach JAWL or sensory memory"

        self.server.asr = UtteranceBuffer(CooperativeTranscriber())
        identity = {"owner": "desktop", "capture_id": "desk-cancel"}
        self.assertEqual(self.request("/api/voice/capture", {"action": "acquire", **identity})[0], 200)
        self.assertEqual(self.request("/api/voice/audio", {
            "pcm16_base64": "AAA=", "session_id": "cancellable", **identity,
        })[0], 200)
        results = []
        end = threading.Thread(target=lambda: results.append(self.request(
            "/api/voice/end", {"session_id": "cancellable", **identity},
        )))
        end.start()
        self.addCleanup(end.join, 2)
        self.addCleanup(self.server.asr.close)
        self.assertTrue(entered.wait(1))
        status, _ = self.request("/api/voice/capture", {"action": "release", "owner": "desktop", "capture_id": "wrong"})
        self.assertEqual(status, 409)
        self.assertFalse(tokens[0].is_set())
        status, released = self.request("/api/voice/capture", {"action": "release", **identity})
        self.assertEqual(status, 200)
        self.assertEqual(released["asr"]["cancelled_transcriptions"], 1)
        end.join(2)
        self.assertFalse(end.is_alive())
        self.assertEqual(results[0][0], 200)
        self.assertEqual(results[0][1]["status"], "cancelled")
        self.assertEqual(results[0][1]["events"], [])
        self.assertEqual(results[0][1]["responses"], [])
        self.assertEqual(self.server.asr.state()["inflight_transcriptions"], 0)

    def test_release_before_delayed_feed_cannot_recreate_a_stale_buffer(self):
        self.server.asr = UtteranceBuffer()
        identity = {"owner": "desktop", "capture_id": "desk-race"}
        self.request("/api/voice/capture", {"action": "acquire", **identity})
        entered, release = threading.Event(), threading.Event()
        original_feed = self.server.asr.feed_audio

        def delayed_feed(*args, **kwargs):
            entered.set()
            release.wait(2)
            return original_feed(*args, **kwargs)

        results = []
        with patch.object(self.server.asr, "feed_audio", side_effect=delayed_feed):
            feed = threading.Thread(target=lambda: results.append(self.request("/api/voice/audio", {
                "pcm16_base64": "AAA=", "session_id": "late", **identity,
            })))
            feed.start()
            self.addCleanup(feed.join, 2)
            self.addCleanup(release.set)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.request("/api/voice/capture", {"action": "release", **identity})[0], 200)
            release.set()
            feed.join(2)
        self.assertFalse(feed.is_alive())
        self.assertEqual(results[0][0], 400)
        self.assertEqual(self.server.asr.state()["active_sessions"], 0)

    def test_configure_merges_partial_settings_and_survives_hub_restart(self):
        original_yaml = self.interfaces_file.read_bytes()
        revision = self.hub.read_voice_capture()["revision"]
        status, body = self.request("/api/voice/capture", {
            "action": "configure",
            "settings": {"gate_open": 0.06, "pre_roll_ms": 240},
            "expected_revision": revision,
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["restart_required"])
        self.assertEqual(body["restart_policy"], "next_capture")
        expected = {
            "gate_open": 0.06,
            "gate_close": 0.012,
            "silence_ms": 1_200,
            "pre_roll_ms": 240,
        }
        self.assertEqual(body["settings"], expected)
        restarted_hub = ConfigHub(self.config_dir, env_file=self.env_file)
        self.assertEqual(restarted_hub.read_voice_capture()["settings"], expected)
        self.assertNotEqual(restarted_hub.revision(), revision)
        self.assertEqual(
            (self.config_dir / "interfaces.yaml.pre-save-1.bak").read_bytes(),
            original_yaml,
        )

    def test_configure_revision_conflict_does_not_write(self):
        before = self.hub.read_voice_capture()
        status, body = self.request("/api/voice/capture", {
            "action": "configure",
            "settings": {"silence_ms": 900},
            "expected_revision": "0" * 32,
        })
        self.assertEqual(status, 409)
        self.assertEqual(body["status"], "conflict")
        self.assertEqual(self.hub.read_voice_capture()["settings"], before["settings"])

    def test_configure_inserts_fresh_capture_subtree_and_preserves_comments_crlf(self):
        revision = self.hub.read_voice_capture()["revision"]
        status, body = self.request("/api/voice/capture", {
            "action": "configure",
            "settings": {"gate_open": 0.04},
            "expected_revision": revision,
        })
        self.assertEqual(status, 200)
        content = self.interfaces_file.read_bytes()
        self.assertIn(b"# top comment\r\n", content)
        self.assertIn(b"  enabled: true # keep voice comment\r\n", content)
        self.assertIn(b"# outside comment\r\n", content)
        self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
        self.assertIn(b"  capture:\r\n    gate_open: 0.04\r\n", content)
        self.assertEqual(body["settings"]["gate_open"], 0.04)

    def test_unsupported_voice_yaml_forms_fail_without_changing_original_bytes(self):
        unsupported = [
            b"'voice':\n  enabled: true\n",
            b'"voice":\n  enabled: true\n',
            b"voice: null\n",
            b"voice: {enabled: true}\n",
            b"voice:\n  enabled: true\n  capture: {gate_open: 0.02}\n",
        ]
        for original in unsupported:
            with self.subTest(original=original):
                self.interfaces_file.write_bytes(original)
                revision = self.hub.revision()
                with self.assertRaisesRegex(ValueError, "unsupported|cannot be edited safely|block mapping"):
                    self.hub.write_voice_capture(
                        VoiceCaptureSettings().as_settings_dict(), revision,
                    )
                self.assertEqual(self.interfaces_file.read_bytes(), original)
                self.assertFalse((self.config_dir / "interfaces.yaml.pre-save-1.bak").exists())

    def test_inline_comments_survive_and_block_scalar_path_text_is_untouched(self):
        inline = (
            b"voice: # voice comment\r\n"
            b"  enabled: true # enabled comment\r\n"
            b"  capture: # capture comment\r\n"
            b"    gate_open: 0.02 # threshold comment\r\n"
            b"web:\r\n  enabled: true\r\n"
        )
        self.interfaces_file.write_bytes(inline)
        self.hub.write_voice_capture(
            VoiceCaptureSettings().as_settings_dict(), self.hub.revision(),
        )
        saved = self.interfaces_file.read_bytes()
        self.assertIn(b"voice: # voice comment\r\n", saved)
        self.assertIn(b"  enabled: true # enabled comment\r\n", saved)
        self.assertIn(b"  capture: # capture comment\r\n", saved)
        self.assertIn(b"    gate_open: 0.02 # threshold comment\r\n", saved)

        original_prompt = "capture:\n  gate_open: 0.24\n"
        self.interfaces_file.write_text(
            "voice:\n  prompt: |\n    capture:\n      gate_open: 0.24\n  enabled: true\nweb:\n  enabled: true\n",
            encoding="utf-8",
        )
        self.hub.write_voice_capture(
            {"gate_open": 0.05, "gate_close": 0.012, "silence_ms": 1_200, "pre_roll_ms": 120},
            self.hub.revision(),
        )
        actual = self.hub.cio.load_yaml(self.interfaces_file)
        self.assertEqual(actual["voice"]["prompt"], original_prompt)
        self.assertEqual(actual["voice"]["capture"]["gate_open"], 0.05)

    def test_comment_only_voice_and_capture_headers_are_supported_and_retained(self):
        original = (
            b"voice: # root voice note\r\n"
            b"  enabled: true\r\n"
            b"  capture: # capture note\r\n"
            b"    gate_open: 0.02\r\n"
            b"web:\r\n  enabled: true\r\n"
        )
        self.interfaces_file.write_bytes(original)
        before = self.hub.cio.load_yaml(self.interfaces_file)
        saved = self.hub.write_voice_capture(
            VoiceCaptureSettings().as_settings_dict(), self.hub.revision(),
        )
        self.assertTrue(saved["ok"])
        text = self.interfaces_file.read_bytes()
        self.assertIn(b"voice: # root voice note\r\n", text)
        self.assertIn(b"  capture: # capture note\r\n", text)
        expected = before
        expected["voice"]["capture"].update(VoiceCaptureSettings().as_settings_dict())
        self.assertEqual(self.hub.cio.load_yaml(self.interfaces_file), expected)

    def test_configure_rejects_invalid_partial_update_and_unknown_keys(self):
        revision = self.hub.revision()
        invalid = [
            {"gate_open": float("nan")},
            {"gate_close": 0.02},
            {"silence_ms": 700.0},
            {"surprise": 1},
        ]
        for settings in invalid:
            with self.subTest(settings=settings):
                status, _ = self.request("/api/voice/capture", {
                    "action": "configure", "settings": settings,
                    "expected_revision": revision,
                })
                self.assertEqual(status, 400)
                self.assertEqual(self.hub.revision(), revision)

    def test_settings_unavailable_without_hub_and_invalid_persisted_values_are_visible(self):
        hub = self.server.config_hub
        self.server.config_hub = None
        status, body = self.request("/api/voice/capture")
        self.assertEqual(status, 503)
        self.assertFalse(body["settings_writable"])
        status, body = self.request("/api/voice/capture", {
            "action": "configure", "settings": {"gate_open": 0.05},
            "expected_revision": "revision",
        })
        self.assertEqual(status, 503)
        self.server.config_hub = hub

        self.interfaces_file.write_text(
            "voice:\n  capture:\n    gate_open: .nan\n", encoding="utf-8",
        )
        status, body = self.request("/api/voice/capture")
        self.assertEqual(status, 500)
        self.assertIn("gate_open must be a finite number", body["error"])

    def test_capture_config_failures_never_echo_yaml_contents_or_io_details(self):
        marker = "fixture-private-config-value"
        actions = [None, {"action": "acquire", "owner": "desktop", "capture_id": "redacted"},
                   {"action": "configure", "settings": {}, "expected_revision": "revision"}]
        # Parser messages can include arbitrary neighbouring YAML source lines.
        self.interfaces_file.write_text(f"voice: [\n  token: {marker}\n", encoding="utf-8")
        for action in actions:
            with self.subTest(action=action):
                status, body = self.request("/api/voice/capture", action)
                self.assertEqual(status, 500)
                self.assertNotIn(marker, json.dumps(body))
                self.assertIn("check interfaces.yaml voice.capture", body["error"])
        self.interfaces_file.write_text("voice:\n  enabled: true\n", encoding="utf-8")
        revision = self.hub.revision()
        with patch.object(self.hub, "write_voice_capture", side_effect=OSError(marker)):
            status, body = self.request("/api/voice/capture", {
                "action": "configure", "settings": {}, "expected_revision": revision,
            })
        self.assertEqual(status, 500)
        self.assertNotIn(marker, json.dumps(body))


if __name__ == "__main__":
    unittest.main()
