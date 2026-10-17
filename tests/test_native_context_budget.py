"""Declared server capacity scales native context without accepting arbitrary edits."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.native_context_budget import BASE_BUDGET, RECEIPT_NAME, approved_profile_budget, budget_for_window


class NativeContextBudgetTests(unittest.TestCase):
    def test_unknown_window_preserves_config_and_large_windows_remain_bounded(self):
        self.assertEqual(budget_for_window(0), {})
        self.assertEqual(budget_for_window(16384), BASE_BUDGET)
        self.assertEqual(budget_for_window(65536)["max_dynamic_chars"], 48000)
        self.assertEqual(budget_for_window(1048576)["max_dynamic_chars"], 96000)
        for invalid in (True, -1, 1048577, "65536", 65536.0):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                budget_for_window(invalid)

    def test_provenance_accepts_only_exact_deterministic_fields_and_bounded_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / RECEIPT_NAME
            good = {"schema_version": 1, "context_window_tokens": 65536, "budget": budget_for_window(65536)}
            path.write_text(json.dumps(good))
            self.assertEqual(approved_profile_budget(root), good["budget"])
            for bad in (dict(good, schema_version=True), dict(good, context_window_tokens=0),
                        dict(good, budget=dict(good["budget"], max_dynamic_chars=999999))):
                path.write_text(json.dumps(bad))
                self.assertEqual(approved_profile_budget(root), {})
            path.write_bytes(b" " * 4097)
            self.assertEqual(approved_profile_budget(root), {})


if __name__ == "__main__":
    unittest.main()
