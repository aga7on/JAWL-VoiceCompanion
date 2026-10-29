"""Kernel terminal history compaction for the native JAWL terminal.

Spec lineage: the retired product extension ``native_terminal_context_compaction``
(ADR-049 slice 6). ``HostTerminalClient.get_context_block`` compacts natively
through ``compaction.compact_context_block``; recent turns stay verbatim.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-compact-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l2_interfaces.host.terminal import compaction  # noqa: E402


def item(text, sender="User", time="2026-10-29 10:00:00"):
    return {"time": time, "sender": sender, "text": text}


class TerminalCompactionKernelTests(unittest.TestCase):
    def test_short_history_is_rendered_verbatim_without_compaction(self):
        history = [item("привет"), item("здравствуйте", "Assistant", "10:01")]
        text, stats = compaction.compact_terminal_history(history)
        self.assertFalse(stats["compacted"])
        self.assertIn("[User]: привет", text)
        self.assertIn("10:01", text)
        self.assertNotIn("Earlier conversation", text)
        self.assertEqual(stats["summarized_messages"], 0)

    def test_invalid_limits_raise(self):
        with self.assertRaises(ValueError):
            compaction.compact_terminal_history([], keep_recent=1)
        with self.assertRaises(ValueError):
            compaction.compact_terminal_history([], target_chars=999)

    def test_long_history_compacts_older_turns_and_keeps_recent_verbatim(self):
        history = [item(f"старое сообщение номер {index} " + "x" * 200, time=f"10:{index:02d}") for index in range(20)]
        history += [item(f"свежее {index}", "Assistant", f"11:{index:02d}") for index in range(12)]
        text, stats = compaction.compact_terminal_history(history, keep_recent=12, target_chars=3000)
        self.assertTrue(stats["compacted"])
        self.assertEqual(stats["summarized_messages"], 20)
        self.assertIn("Earlier conversation", text)
        self.assertIn("Recent conversation", text)
        self.assertIn("свежее 0", text)
        # Older turns are excerpts: the long tail is gone, the head remains.
        self.assertNotIn("x" * 50, text)
        self.assertIn("старое сообщение номер 0", text)

    def test_sensor_appendix_is_stripped_from_message_text(self):
        message = item("сделай отчёт\n\n[ФОН ВОСПРИЯТИЯ · сцена: комната]")
        self.assertEqual(compaction._message_text(message), "сделай отчёт")

    def test_compact_excerpt_keeps_head_and_tail(self):
        text = "начало " + "x" * 200 + " конец"
        excerpt = compaction._compact_excerpt(text, 50)
        self.assertLessEqual(len(excerpt), 52)
        self.assertTrue(excerpt.startswith("начало"))
        self.assertTrue(excerpt.endswith("конец"))
        self.assertIn(" … ", excerpt)

    def test_perception_block_is_removed_inside_excerpts(self):
        text = "важная реплика\n\n[ФОН ВОСПРИЯТИЯ · сцена: сад]" + "y" * 200
        excerpt = compaction._compact_excerpt(text, 60)
        self.assertNotIn("ФОН ВОСПРИЯТИЯ", excerpt)

    def test_sender_letters_map_user_assistant_and_other(self):
        senders = ("User", "Assistant", "System", "human")
        history = [
            item(f"реплика {index} " + "z" * 200, sender=senders[index % 4])
            for index in range(10)
        ]
        history += [item("короткое", sender) for sender in senders]
        text, _stats = compaction.compact_terminal_history(history, keep_recent=4, target_chars=1500)
        self.assertIn("U: реплика 0", text)
        self.assertIn("A: реплика 1", text)
        self.assertIn("O: реплика 2", text)

    def test_safety_valve_recompacts_recent_turns_when_over_target(self):
        history = [item("старый контекст " + "w" * 300, time="09:00")]
        history += [item("свежий длинный ответ " + "v" * 500, "Assistant", f"10:{index:02d}") for index in range(12)]
        text, stats = compaction.compact_terminal_history(history, keep_recent=12, target_chars=2000)
        self.assertTrue(stats["compacted"])
        self.assertIn("sensory appendices removed", text)
        self.assertLessEqual(len(text), 2000 + 280 * 12 + 200)

    def test_declared_context_window_scales_the_target(self):
        with patch.dict(os.environ, {"JAWL_CONTEXT_WINDOW_TOKENS": "65536"}):
            self.assertEqual(compaction.declared_target_chars(18000), 98304)
        with patch.dict(os.environ, {"JAWL_CONTEXT_WINDOW_TOKENS": "8192"}):
            self.assertEqual(compaction.declared_target_chars(18000), 18000)
        with patch.dict(os.environ, {"JAWL_CONTEXT_WINDOW_TOKENS": "invalid"}):
            self.assertEqual(compaction.declared_target_chars(18000), 18000)

    def test_client_context_block_routes_through_compaction(self):
        history = [item(f"давняя строка {index} " + "q" * 700) for index in range(30)]

        class Client:
            def _read_history_file(self):
                return history

        block = (
            "### HOST TERMINAL [ON]\nDescription: Direct CLI chat with the system operator/user.\n"
            "Status: The terminal window is opened.\n\nRecent messages:\n[stale inline state]"
        )
        out = compaction.compact_context_block(block, Client())
        self.assertIn("Recent messages:\nEarlier conversation", out)
        self.assertNotIn("stale inline state", out)
        # Blocks without a history section pass through untouched.
        self.assertEqual(compaction.compact_context_block("### X\n", Client()), "### X\n")
        # A client without a reader passes through untouched.
        self.assertEqual(compaction.compact_context_block(block, object()), block)


if __name__ == "__main__":
    unittest.main()
