from types import SimpleNamespace
import unittest

from jawl_voicecompanion.owned_resource_sampler import OwnedResourceSampler


class ResourceSamplerTests(unittest.TestCase):
    def test_foreign_process_metadata_never_read_and_cpu_uses_elapsed_interval(self):
        class Process:
            def __init__(self, pid, created=10):
                self.pid, self.created, self.total = pid, created, 0

            def create_time(self):
                if self.pid == 99:
                    raise AssertionError('foreign metadata read')
                return self.created

            def memory_info(self):
                return SimpleNamespace(rss=100)

            def cpu_times(self):
                return SimpleNamespace(user=self.total, system=0)

            def is_running(self):
                return True

        owned, foreign = Process(10), Process(99)
        ticks = iter([0, 2, 4, 6])
        def processes(attrs):
            self.assertEqual(attrs, ['pid'])
            return [owned, foreign]
        sampler = OwnedResourceSampler([SimpleNamespace(owns_pid=lambda pid: pid == 10)],
                                       process_iter=processes, clock=lambda: next(ticks))
        self.assertIsNone(sampler.sample()['processes'][0]['cpu_percent'])
        owned.total = 1
        self.assertEqual(sampler.sample()['cpu_percent'], 50)
        owned.created = 20  # reused PID starts a new CPU interval
        self.assertIsNone(sampler.sample()['processes'][0]['cpu_percent'])
        self.assertEqual(len(sampler.previous), 1)
        sampler.owners = [SimpleNamespace(owns_pid=lambda pid: False)]
        self.assertEqual(sampler.sample()['process_count'], 0)
        self.assertEqual(sampler.previous, {})

    def test_job_membership_loss_during_sample_discards_process(self):
        checks = iter([True, False])
        process = SimpleNamespace(pid=1, create_time=lambda: 10,
                                  memory_info=lambda: SimpleNamespace(rss=10),
                                  cpu_times=lambda: SimpleNamespace(user=0, system=0), is_running=lambda: True)
        sampler = OwnedResourceSampler([SimpleNamespace(owns_pid=lambda pid: next(checks))],
                                       process_iter=lambda attrs: [process])
        self.assertEqual(sampler.sample()['process_count'], 0)
