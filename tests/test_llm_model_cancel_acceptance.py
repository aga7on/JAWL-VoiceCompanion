"""Pure contract checks for the selected-model cancellation probe helpers."""
from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stderr
import io
import sys
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_llm_model_cancel_acceptance as acceptance  # noqa: E402


class LLMModelCancelAcceptanceTests(unittest.TestCase):
    def test_child_route_cannot_bypass_explicit_model_opt_in(self):
        report = acceptance.ROOT / 'runtime/never-created-cpu-opt-in-test.json'
        stderr = io.StringIO()
        argv = ['probe', '--report', str(report), '--child-root', str(acceptance.ROOT / 'runtime/instances')]
        with patch.object(sys, 'argv', argv), redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            acceptance.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('explicit --allow-cpu-model', stderr.getvalue())
        self.assertFalse(report.exists())

    def test_cpu_command_forces_cpu_only_single_slot_execution(self):
        command = acceptance.cpu_command(
            Path("llama-server.exe"), Path("model.gguf"), "selected-model", 8123, 6
        )

        for flag in (
            "--device",
            "none",
            "--gpu-layers",
            "0",
            "--no-kv-offload",
            "--no-op-offload",
            "--parallel",
            "1",
            "--ctx-size",
            "4096",
            "--slots",
            "--no-warmup",
            "--host",
            "127.0.0.1",
        ):
            self.assertIn(flag, command)

    def test_cpu_command_passes_model_alias_and_runtime_bounds_explicitly(self):
        model = Path("models") / "small.gguf"
        command = acceptance.cpu_command(Path("llama-server.exe"), model, "chosen-alias", 8123, 6)

        self.assertIn(str(model), command)
        self.assertIn("--alias", command)
        self.assertEqual(command[command.index("--alias") + 1], "chosen-alias")
        self.assertEqual(command[command.index("--port") + 1], "8123")
        self.assertEqual(command[command.index("--threads") + 1], "6")

    def test_ram_admission_accepts_exact_model_plus_ten_gib(self):
        required = 3 * acceptance.GIB

        self.assertTrue(acceptance.admit_ram(required + 10 * acceptance.GIB, required))

    def test_ram_admission_rejects_one_byte_below_reserve(self):
        required = 3 * acceptance.GIB

        self.assertFalse(acceptance.admit_ram(required + 10 * acceptance.GIB - 1, required))

    def test_initial_idle_slot_allows_missing_task_and_next_token(self):
        state = acceptance.slot_state([{"is_processing": False, "n_ctx": 4096}])

        self.assertEqual(
            state,
            {"id_task": None, "is_processing": False, "n_decoded": 0, "n_ctx": 4096},
        )
        self.assertEqual(set(state), {"id_task", "is_processing", "n_decoded", "n_ctx"})

    def test_active_slot_reads_decoded_count_from_single_next_token(self):
        state = acceptance.slot_state(
            [{
                "id_task": 17,
                "is_processing": True,
                "n_ctx": 4096,
                "next_token": [{"n_decoded": 23}],
            }]
        )

        self.assertEqual(state, {"id_task": 17, "is_processing": True, "n_decoded": 23, "n_ctx": 4096})

    def test_slot_state_rejects_non_singleton_or_malformed_payloads(self):
        for payload in (None, {}, [], [{"is_processing": False}], [{}, {}], [None]):
            with self.subTest(payload=payload), self.assertRaises((TypeError, ValueError)):
                acceptance.slot_state(payload)

    def test_slot_state_rejects_bool_as_integer_and_invalid_active_token_shapes(self):
        invalid_slots = (
            {"id_task": True, "is_processing": False, "n_ctx": 32},
            {"id_task": 1, "is_processing": False, "n_ctx": True},
            {"id_task": 1, "is_processing": False, "n_ctx": 32, "next_token": [{"n_decoded": True}]},
            {"id_task": 1, "is_processing": True, "n_ctx": 32},
            {"id_task": 1, "is_processing": True, "n_ctx": 32, "next_token": []},
            {"id_task": 1, "is_processing": True, "n_ctx": 32, "next_token": [{"n_decoded": -1}]},
        )
        for slot in invalid_slots:
            with self.subTest(slot=slot), self.assertRaises((TypeError, ValueError)):
                acceptance.slot_state([slot])


if __name__ == "__main__":
    unittest.main()
