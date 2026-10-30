import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('owned_native_soak_test', ROOT / 'scripts/run_owned_native_soak.py')
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


class OwnedNativeSoakTests(unittest.TestCase):
    def test_queue_evidence_is_payload_free_and_missing_or_invalid_counters_fail(self):
        def buffer():
            return dict(size=1, capacity=100, coalesced_total=2, dropped_total=0, names={'PRIVATE_SENTINEL': 1})
        status = {'heartbeat': {'wake_queue': buffer(), 'react_buffers': {'realtime': buffer(), 'steer': buffer()}},
                  'goal': {'thoughts': 'PRIVATE_SENTINEL'}}
        counts = soak.queue_counters(status)
        self.assertNotIn('PRIVATE_SENTINEL', str(counts))
        self.assertEqual(counts['wake']['size'], 1)
        for invalid in (101, True, '1', -1):
            status['heartbeat']['wake_queue']['size'] = invalid
            with self.assertRaises(ValueError):
                soak.queue_counters(status)
        with self.assertRaises(ValueError):
            soak.queue_counters({})

    def test_cycle_projection_excludes_native_goal_and_ledger_text(self):
        item = {'cycle': 1, 'status': 'passed', 'goal_created': {'objective': 'PRIVATE_SENTINEL'},
                'goal_terminal': {'status': 'complete', 'thoughts': 'PRIVATE_SENTINEL'},
                'terminal_ledger': {'phase': 'completed', 'completed_steps': ['PRIVATE_SENTINEL'],
                                    'last_action_batch': [{'message': 'PRIVATE_SENTINEL'}]}}
        result = soak.project_cycle(item)
        self.assertNotIn('PRIVATE_SENTINEL', str(result))
        self.assertEqual(result['terminal_ledger']['completed_steps_count'], 1)
