"""Cheap harness checks; deliberately do not import the pinned SDK or JAWL."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_llm_cancel_acceptance.py"
SPEC = importlib.util.spec_from_file_location("llm_cancel_acceptance", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class LLMCancelAcceptanceHarnessTests(unittest.TestCase):
    def test_real_probe_requires_explicit_opt_in(self):
        with patch.object(probe, "run_parent") as run_parent:
            with self.assertRaises(SystemExit) as caught:
                probe.main([])
        self.assertEqual(caught.exception.code, 2)
        run_parent.assert_not_called()

    def test_child_command_uses_pinned_style_no_bytecode_invocation(self):
        command = probe.child_command(Path("python.exe"), SCRIPT, Path("isolated"), Path("report.json"))
        self.assertEqual(command[1], "-B")
        self.assertIn("--child", command)
        self.assertLessEqual(probe.CHILD_TIMEOUT_SECONDS, 20)

    def test_child_environment_cannot_inherit_credentials_or_proxy_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "external-secret-must-not-pass",
                "HTTPS_PROXY": "http://proxy.invalid",
                "JAWL_LOG_DIR": "G:/protected/logs",
            }):
                env = probe.child_environment(root)
        self.assertEqual(env["OPENAI_API_KEY"], "jawl-loopback-acceptance-key")
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotEqual(env["JAWL_LOG_DIR"], "G:/protected/logs")
        for key in ("JAWL_DATA_DIR", "JAWL_CONFIG_DIR", "JAWL_LOG_DIR", "JAWL_PROMPT_DIR", "JAWL_SANDBOX_DIR"):
            self.assertTrue(Path(env[key]).is_relative_to(root))

    def test_report_creation_is_exclusive_and_keeps_exit_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.json"
            code = probe._write_report(report, {"status": "passed"}, 0)
            self.assertEqual(code, 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 0)
            with self.assertRaises(FileExistsError):
                probe._write_report(report, {}, 0)

    def test_server_fixture_has_no_model_path_and_tracks_peer_eof(self):
        state = probe.ProbeState()
        self.assertEqual(state.counts, {})
        self.assertIn(b"data: ", state.sse_chunk("fixture"))
        self.assertIn("OpenAICompatibleProvider", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("127.0.0.1", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
