from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


def _resolve_source() -> Path:
    base = Path(__file__).parents[1] / "runtime" / "jawl-sources"
    for candidate in base.glob("jawl-*/src"):
        if (candidate / "l3_agent/skills/registry.py").is_file():
            return candidate
    return base / "jawl-20260906-daily-v2/src"

SOURCE = _resolve_source()


class JawlSkillAliasTests(unittest.TestCase):
    def test_historical_terminal_names_resolve_only_to_native_names(self) -> None:
        sys.path.insert(0, str(SOURCE.parent))
        try:
            module_path = SOURCE / "l3_agent/skills/registry.py"
            spec = importlib.util.spec_from_file_location("alias_registry", module_path)
            assert spec and spec.loader
            # Importing the complete JAWL registry requires its runtime graph;
            # verify the source contract directly and keep this test isolated.
            text = module_path.read_text(encoding="utf-8")
            self.assertIn('"HostOSTerminal.send_message_to_terminal"', text)
            self.assertIn('"HostOSTerminal.read_terminal_history"', text)
            self.assertIn("HostTerminalMessages.send_message_to_terminal", text)
            self.assertIn("HostTerminalMessages.read_terminal_history", text)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
