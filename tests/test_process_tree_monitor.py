from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from run_process_tree_monitor import run_monitor


class FakeSampler:
    def __init__(self):
        self.samples = 0

    def sample(self):
        self.samples += 1
        return {"observed_process_count": self.samples, "snapshot_complete": True}


class ProcessTreeMonitorTests(unittest.TestCase):
    def test_writes_jsonl_snapshot_and_returns_after_one_sample(self):
        sampler = FakeSampler()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "resources.jsonl"
            stop = Path(directory) / "stop"

            count = run_monitor(sampler, output, stop, 0.05, max_samples=1)

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(count, 1)
        self.assertEqual(records[0]["schema_version"], 1)
        self.assertEqual(records[0]["sample"]["observed_process_count"], 1)
        self.assertIn("captured_at_utc", records[0])

    def test_rejects_unreasonably_fast_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_monitor(FakeSampler(), Path(directory) / "r.jsonl", Path(directory) / "stop", 0.01)

    def test_stop_request_exits_after_flushing_current_snapshot(self):
        sampler = FakeSampler()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "resources.jsonl"
            count = run_monitor(
                sampler,
                output,
                Path(directory) / "stop",
                0.05,
                stop_requested=lambda: sampler.samples >= 1,
            )
            records = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(count, 1)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
