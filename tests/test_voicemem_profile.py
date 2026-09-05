import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_voicemem_profile", ROOT / "scripts" / "run_voicemem_profile.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class VoiceMemProfileTests(unittest.TestCase):
    def test_live_model_requires_explicit_opt_in_and_writes_bounded_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "profile.json"
            args = MODULE._build_parser().parse_args([
                "--python", "python", "--wav", str(Path(directory) / "missing.wav"),
                "--report", str(report_path),
            ])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.run(args)
            self.assertEqual(result, 2)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report, {
                "profile": "voicemem",
                "status": "refused",
                "reason": "allow_live_model_required",
            })

    def test_dry_run_does_not_require_model_or_wav(self):
        args = MODULE._build_parser().parse_args([
            "--python", "python", "--wav", "missing.wav", "--dry-run",
            "--warmup", "text", "--local-memory",
        ])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = MODULE.run(args)
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["profile"], "voicemem")
        self.assertEqual(payload["warmup"], "text")
        self.assertTrue(payload["local_memory"])
        self.assertFalse(payload["allow_live_model"])


if __name__ == "__main__":
    unittest.main()
