import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))


class ConnectedNativeActionAcceptanceTests(unittest.TestCase):
    def test_model_identity_is_explicitly_parameterized(self):
        source = (Path(__file__).parents[1] / "scripts" / "run_connected_native_action_acceptance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--expected-model"', source)
        self.assertNotIn('model_id = "jawl-gemma4-it:latest"', source)

    def test_model_identity_argument_is_bounded(self):
        source = (Path(__file__).parents[1] / "scripts" / "run_connected_native_action_acceptance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("len(model_id) > 200", source)
        self.assertIn('"\\n" in model_id', source)


if __name__ == "__main__":
    unittest.main()
