from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_desktop_voice_e2e as harness  # noqa: E402


class DesktopVoiceDiagnosticsTests(unittest.TestCase):
    def test_browser_transcriber_fixture_accepts_the_cancellable_buffer_contract(self):
        transcriber = harness.SyntheticFinalTranscriber()
        buffer = harness.UtteranceBuffer(transcriber)
        buffer.feed_audio(b"\x01\x00" * 32, sample_rate=16000, channels=1, session_id="browser")
        result = buffer.finish("browser")
        self.assertEqual(result["status"], "transcribed")
        self.assertEqual(result["text"], "synthetic utterance 1")
        self.assertEqual(len(transcriber.calls), 1)

    def test_diagnostic_text_is_redacted_and_bounded(self):
        messages = [
            "TypeError: Failed to fetch Authorization: Bearer fixture-sensitive",
            "fetch http://user:fixture-sensitive@127.0.0.1:1234/api/voice/capture?token=fixture-sensitive",
            "failure at C:/Users/fixture-sensitive/config.json",
            "access_token=fixture-sensitive",
            'console {"payload":"fixture-sensitive"}',
            'console {\n"payload":"fixture-sensitive"}',
            'headers=\nfixture-sensitive\nfixture-sensitive',
            "file:///tmp/fixture-sensitive",
        ]
        for message in messages:
            with self.subTest(message=message):
                result = harness._redact_diagnostic_text(message)
                self.assertNotIn("fixture-sensitive", result)
                self.assertLessEqual(len(result), 256)
        self.assertEqual(len(harness._redact_diagnostic_text("x" * 500)), 256)
        self.assertEqual(harness._redact_diagnostic_text("TypeError: Failed to fetch"), "TypeError: Failed to fetch")

    def test_failure_snapshot_keeps_identity_and_timings_but_drops_bodies_and_headers(self):
        snapshot = {
            "fetches": [
                {"path": "/api/voice/capture", "capture_id": f"fixture-{i}", "owner": "desktop",
                 "startedAt": 10, "failedAt": 11, "status": None,
                 "error": {"name": "TypeError", "message": "Failed to fetch token=fixture-sensitive",
                           "stack": "fixture-sensitive"},
                 "body": "fixture-sensitive", "headers": "fixture-sensitive", "result": {"raw": "fixture-sensitive"}}
                for i in range(80)
            ],
            "fetches_total": 80,
            "mic_ui": {"text": "Микрофон недоступен: Failed to fetch", "starting": False,
                       "active": False, "button_disabled": False, "body": "fixture-sensitive"},
        }
        logs = [{"level": "SEVERE", "message": "Failed to fetch headers=fixture-sensitive", "timestamp": i}
                for i in range(40)] + [{"level": "INFO", "message": "fixture-sensitive"}]
        driver = SimpleNamespace(execute_script=Mock(return_value=snapshot), get_log=Mock(return_value=logs))

        result = harness._collect_failure_diagnostics(driver)

        self.assertEqual(len(result["fetches"]), 64)
        self.assertEqual(result["fetches_total"], 80)
        self.assertEqual(result["fetches"][-1]["capture_id"], "fixture-79")
        self.assertEqual(result["fetches"][-1]["failedAt"], 11)
        self.assertEqual(result["fetches"][-1]["error"]["name"], "TypeError")
        self.assertEqual(result["mic_ui"]["active"], False)
        self.assertEqual(len(result["console_errors"]), 32)
        self.assertEqual(result["console_errors_total"], 40)
        self.assertEqual(result["console_errors"][-1]["timestamp"], 39)
        self.assertNotIn("fixture-sensitive", json.dumps(result))
        for row in result["fetches"]:
            self.assertFalse({"body", "headers", "result"} & row.keys())
            self.assertEqual(set(row["error"]), {"name", "message"})

    def test_console_errors_are_collected_even_when_snapshot_fails(self):
        driver = SimpleNamespace(
            execute_script=Mock(side_effect=ValueError("fixture-sensitive")),
            get_log=Mock(return_value=[{"level": "SEVERE", "message": "net::ERR_EMPTY_RESPONSE"}]),
        )
        result = harness._collect_failure_diagnostics(driver)
        self.assertEqual(result["snapshot_error"], "ValueError")
        self.assertEqual(result["console_errors"][0]["message"], "net::ERR_EMPTY_RESPONSE")
        self.assertNotIn("fixture-sensitive", json.dumps(result))

    def test_fetch_exception_metadata_is_bounded_and_original_error_is_rethrown(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required to exercise the browser instrumentation fixture")
        setup = """
global.window = globalThis;
global.location = {href: 'http://127.0.0.1:1234/app'};
global.AudioContext = class {decodeAudioData() {} createBufferSource() {}};
global.AudioBufferSourceNode = class {start() {} stop() {}};
global.addEventListener = () => {};
const originalError = new TypeError('Failed to fetch ' + 'x'.repeat(500));
global.fetch = async () => {throw originalError;};
"""
        exercise = """
(async () => {
  let sameError = false;
  try {await fetch('/api/voice/capture', {body: JSON.stringify({action: 'acquire', owner: 'desktop', capture_id: 'fixture-id'})});}
  catch (error) {sameError = error === originalError;}
  const state = window.__desktopVoiceE2E;
  console.log(JSON.stringify({sameError, item: state.fetches[0], event: state.timeline[0]}));
})();
"""
        completed = subprocess.run([node], input=setup + harness._install_observability() + exercise,
                                   text=True, capture_output=True, timeout=10, check=True)
        result = json.loads(completed.stdout)
        self.assertTrue(result["sameError"])
        self.assertEqual(result["item"]["error"]["name"], "TypeError")
        self.assertEqual(len(result["item"]["error"]["message"]), 256)
        self.assertIsNone(result["item"]["status"])
        self.assertGreaterEqual(result["item"]["failedAt"], result["item"]["startedAt"])
        self.assertEqual(result["item"]["error"], result["event"]["error"])
        self.assertEqual(result["event"]["capture_id"], "fixture-id")
        self.assertEqual(set(result["item"]["error"]), {"name", "message"})


if __name__ == "__main__":
    unittest.main()
