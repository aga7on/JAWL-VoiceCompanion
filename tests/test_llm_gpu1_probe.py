"""Cheap CLI, admission, and command checks for the opt-in GPU1 probe."""
from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_llm_model_cancel_acceptance as acceptance  # noqa: E402


class LLMGpu1ProbeTests(unittest.TestCase):
    def test_gpu_env_adds_only_machine_path_not_credentials_or_profile(self):
        with patch.object(acceptance, 'child_environment', side_effect=lambda _root: {'PATH': 'fixture'}), \
                patch.dict(acceptance.os.environ, {'ProgramFiles': 'machine-path',
                    'OPENAI_API_KEY': 'must-not-inherit', 'USERPROFILE': 'must-not-inherit'}, clear=True):
            self.assertEqual(acceptance.probe_environment(Path('fixture'), 'gpu1'),
                             {'PATH': 'fixture', 'ProgramFiles': 'machine-path'})
            self.assertEqual(acceptance.probe_environment(Path('fixture'), 'cpu'), {'PATH': 'fixture'})

    def test_gpu1_command_uses_canonical_full_context_and_one_slot(self):
        command = acceptance.gpu1_command(
            Path("llama-server.exe"), Path("brain.gguf"), "local-bonsai2", 8123,
            threads=12, context_size=65536, gpu_layers=99, device="CUDA1",
        )

        self.assertEqual(command[command.index("--ctx-size") + 1], "65536")
        self.assertEqual(command[command.index("--threads") + 1], "12")
        self.assertEqual(command[command.index("--gpu-layers") + 1], "99")
        self.assertEqual(command[command.index("--device") + 1], "CUDA1")
        self.assertEqual(command[command.index("--parallel") + 1], "1")
        self.assertIn("--slots", command)
        self.assertEqual(command[command.index("--fit") + 1], "off")
        self.assertNotIn("--no-kv-offload", command)
        self.assertNotIn("--no-op-offload", command)

    def test_gpu1_command_rejects_other_device_and_zero_layers(self):
        with self.assertRaisesRegex(ValueError, "requires device CUDA1"):
            acceptance.gpu1_command(
                Path("llama-server.exe"), Path("brain.gguf"), "local-bonsai2", 8123,
                threads=12, context_size=65536, gpu_layers=99, device="CUDA0",
            )
        with self.assertRaisesRegex(ValueError, "positive GPU layers"):
            acceptance.gpu1_command(
                Path("llama-server.exe"), Path("brain.gguf"), "local-bonsai2", 8123,
                threads=12, context_size=65536, gpu_layers=0, device="CUDA1",
            )

    def test_gpu1_admission_requires_model_plus_two_gib(self):
        model_bytes = 7 * acceptance.GIB

        self.assertTrue(acceptance.admit_gpu1(model_bytes + 2 * acceptance.GIB, model_bytes))
        self.assertFalse(acceptance.admit_gpu1(model_bytes + 2 * acceptance.GIB - 1, model_bytes))

    def test_gpu1_free_memory_reads_physical_index_one_in_mib(self):
        completed = type("Completed", (), {"stdout": "9000\n"})()
        with patch.object(acceptance.subprocess, "run", return_value=completed) as run:
            self.assertEqual(acceptance.gpu1_free_bytes(), 9000 * 1024 ** 2)

        args = run.call_args.args[0]
        self.assertIn("--id=1", args)
        self.assertIn("--query-gpu=memory.free", args)

    def test_gpu_memory_probe_failure_is_redacted_and_closed(self):
        failure = acceptance.subprocess.CalledProcessError(1, "nvidia-smi", stderr="private host detail")
        with patch.object(acceptance.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "GPU1 memory admission unavailable") as caught:
                acceptance.gpu1_free_bytes()
        self.assertNotIn("private host detail", str(caught.exception))

    def test_cpu_and_gpu1_opt_ins_are_mutually_exclusive(self):
        report = acceptance.ROOT / "runtime/gpu1-mutual-exclusion-test.json"
        stderr = io.StringIO()
        argv = ["probe", "--report", str(report), "--allow-cpu-model", "--allow-gpu1-model"]
        with patch.object(sys, "argv", argv), redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            acceptance.main()

        self.assertEqual(caught.exception.code, 2)
        self.assertIn("not allowed with argument", stderr.getvalue())
        self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
