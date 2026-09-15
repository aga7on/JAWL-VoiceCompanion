from types import SimpleNamespace
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


class JawlReactPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
        )
        cls._old_bytecode = os.environ.get("PYTHONDONTWRITEBYTECODE")
        cls._old_log_dir = os.environ.get("JAWL_LOG_DIR")
        cls._temp = tempfile.TemporaryDirectory()
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["JAWL_LOG_DIR"] = cls._temp.name
        sys.path.insert(0, str(snapshot))
        loop_module = importlib.import_module("src.l3_agent.react.loop")
        cls.policy = staticmethod(loop_module._empty_goal_action_policy)
        cls.ledger_completion = staticmethod(
            loop_module._ledger_completion_eligible
        )
        cls._logger_module = importlib.import_module("src.utils.logger")

    @classmethod
    def tearDownClass(cls):
        if cls._old_bytecode is None:
            os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
        else:
            os.environ["PYTHONDONTWRITEBYTECODE"] = cls._old_bytecode
        if cls._old_log_dir is None:
            os.environ.pop("JAWL_LOG_DIR", None)
        else:
            os.environ["JAWL_LOG_DIR"] = cls._old_log_dir
        for handler in list(cls._logger_module._file_handlers_registry):
            handler.close()
        cls._temp.cleanup()

    def _goal(self, continuations=1, next_action="write_file"):
        return SimpleNamespace(
            status="active",
            continuation_count=continuations,
            task_ledger=SimpleNamespace(next_action=next_action),
        )

    def test_pending_next_action_gets_bounded_repair(self):
        self.assertEqual(self.policy(self._goal(1)), "continue")

    def test_pending_next_action_eventually_blocks(self):
        self.assertEqual(self.policy(self._goal(3)), "blocked")

    def test_missing_next_action_gets_bounded_repair(self):
        self.assertEqual(self.policy(self._goal(1, "")), "continue")

    def test_missing_next_action_eventually_blocks(self):
        self.assertEqual(self.policy(self._goal(3, "")), "blocked")

    def test_empty_legacy_response_needs_durable_terminal_evidence(self):
        goal = self._goal(1, "")
        goal.task_ledger = SimpleNamespace(
            current_phase="done",
            pending_steps=[],
            next_action="none",
            blockers=[],
            last_action_batch=[],
        )
        self.assertFalse(self.ledger_completion(goal))

    def test_empty_legacy_response_can_finish_verified_terminal_ledger(self):
        goal = self._goal(1, "")
        goal.task_ledger = SimpleNamespace(
            current_phase="done",
            pending_steps=[],
            next_action="none",
            blockers=[],
            last_action_batch=[SimpleNamespace(status="success")],
        )
        self.assertTrue(self.ledger_completion(goal))

    def test_terminal_ledger_with_pending_work_is_not_completion(self):
        goal = self._goal(1, "")
        goal.task_ledger = SimpleNamespace(
            current_phase="done",
            pending_steps=["publish"],
            next_action="none",
            blockers=[],
            last_action_batch=[SimpleNamespace(status="success")],
        )
        self.assertFalse(self.ledger_completion(goal))

    def test_provider_done_without_action_evidence_is_not_completion(self):
        goal = self._goal(1, "")
        goal.task_ledger = SimpleNamespace(
            current_phase="completed",
            pending_steps=[],
            next_action="none",
            blockers=[],
            last_action_batch=[],
        )
        self.assertFalse(self.ledger_completion(goal))

    def test_terminal_message_wrapper_is_not_action_evidence(self):
        goal = self._goal(1, "")
        goal.task_ledger = SimpleNamespace(
            current_phase="completed",
            pending_steps=[],
            next_action="none",
            blockers=[],
            last_action_batch=[
                SimpleNamespace(
                    tool="HostTerminalMessages.send_message_to_terminal",
                    status="success",
                )
            ],
        )
        self.assertFalse(self.ledger_completion(goal))


if __name__ == "__main__":
    unittest.main()
