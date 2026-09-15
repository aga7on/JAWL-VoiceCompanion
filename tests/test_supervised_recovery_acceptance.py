import unittest
from pathlib import Path


class SupervisedRecoveryAcceptanceTests(unittest.TestCase):
    def test_live_harness_is_lease_gated_and_does_not_claim_checkpoint_reconciliation(self):
        source = (
            Path(__file__).parents[1] / "scripts" / "run_supervised_recovery_acceptance.py"
        ).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--live"', source)
        self.assertIn("ROOT autonomy lease", source)
        self.assertIn("no_third_child_after_revoke", source)
        self.assertIn("does not claim checkpoint", source)
