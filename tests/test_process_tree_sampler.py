from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.process_tree_sampler import ProcessIdentity, ProcessTreeSampler


class FakeProcess:
    def __init__(self, pid, ppid, created, *, cpu=0.0, rss=100, private=70, threads=2, handles=8):
        self.pid = pid
        self.info = {"pid": pid, "ppid": ppid}
        self.created = created
        self.cpu = cpu
        self.rss = rss
        self.private = private
        self.threads = threads
        self.handles = handles
        self.running = True
        self.resource_reads = 0

    def create_time(self):
        return self.created

    def ppid(self):
        return self.info["ppid"]

    def memory_info(self):
        self.resource_reads += 1
        return SimpleNamespace(rss=self.rss, private=self.private)

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu, system=0.0)

    def num_threads(self):
        return self.threads

    def num_handles(self):
        return self.handles

    def is_running(self):
        return self.running


class ProcessTreeSamplerTests(unittest.TestCase):
    def test_exact_root_and_descendants_include_private_memory_threads_and_cpu_delta(self):
        root = FakeProcess(10, 1, 100.0, cpu=1.0, rss=500, private=300, threads=4)
        child = FakeProcess(11, 10, 101.0, cpu=0.5, rss=200, private=120, threads=3)
        grandchild = FakeProcess(12, 11, 101.2, cpu=0.25, rss=100, private=80, threads=2)
        foreign = FakeProcess(90, 1, 1.0)
        ticks = iter([0.0, 0.25, 0.5])
        process_sets = [
            [root, foreign],
            [root, child, grandchild, foreign],
            [root, child, grandchild, foreign],
        ]

        def process_iter(attrs):
            self.assertEqual(attrs, ["pid", "ppid"])
            return process_sets.pop(0)

        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0, "companion")],
            process_iter=process_iter,
            clock=lambda: next(ticks),
        )
        sampler.sample()  # establish initial CPU counters
        appeared = sampler.sample()
        self.assertEqual([event["pid"] for event in appeared["lifecycle_events"]], [11, 12])
        child.cpu += 0.5
        grandchild.cpu += 0.25
        result = sampler.sample()
        rows = {row["pid"]: row for row in result["processes"]}

        self.assertEqual(set(rows), {10, 11, 12})
        self.assertEqual(result["working_set_bytes"], 800)
        self.assertEqual(result["private_bytes"], 500)
        self.assertEqual(result["thread_count"], 9)
        self.assertEqual(result["handle_count"], 24)
        self.assertTrue(result["handle_count_complete"])
        self.assertEqual(rows[11]["cpu_percent"], 200.0)
        self.assertEqual(rows[12]["root_label"], "companion")
        self.assertEqual(result["lifecycle_events"], [])
        self.assertEqual(foreign.resource_reads, 0)

    def test_child_exit_is_reported_with_last_sampled_resources(self):
        root = FakeProcess(10, 1, 100.0)
        child = FakeProcess(11, 10, 101.0, cpu=0.75, rss=250, private=180, threads=5)
        ticks = iter([0.0, 0.5, 1.0])
        process_sets = [[root], [root, child], [root]]
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: process_sets.pop(0),
            clock=lambda: next(ticks),
        )
        sampler.sample()
        appeared = sampler.sample()
        self.assertEqual(appeared["lifecycle_events"][0]["event"], "appeared_since_previous_sample")
        self.assertEqual(appeared["lifecycle_events"][0]["private_bytes"], 180)

        disappeared = sampler.sample()
        child_exit = next(event for event in disappeared["lifecycle_events"] if event["pid"] == 11)
        self.assertEqual(child_exit["event"], "disappeared_since_previous_sample")
        self.assertEqual(child_exit["working_set_bytes"], 250)
        self.assertEqual(child_exit["thread_count"], 5)

    def test_root_pid_reuse_does_not_attach_replacement_or_children(self):
        replacement = FakeProcess(10, 1, 200.0)
        child = FakeProcess(11, 10, 201.0)
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: [replacement, child],
        )
        result = sampler.sample()
        self.assertEqual(result["processes"], [])
        self.assertEqual(result["root_identities_missing"][0]["pid"], 10)
        self.assertEqual(replacement.resource_reads, 0)
        self.assertEqual(child.resource_reads, 0)

    def test_reused_child_pid_is_a_new_generation_and_resets_cpu_delta(self):
        root = FakeProcess(10, 1, 100.0)
        child = FakeProcess(11, 10, 101.0, cpu=1.0)
        ticks = iter([0.0, 1.0, 2.0])
        process_sets = [[root], [root, child], [root, FakeProcess(11, 10, 201.0, cpu=9.0)]]
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: process_sets.pop(0),
            clock=lambda: next(ticks),
        )
        sampler.sample()
        sampler.sample()
        reused = sampler.sample()
        child_events = [event for event in reused["lifecycle_events"] if event["pid"] == 11]
        self.assertEqual({event["event"] for event in child_events}, {
            "appeared_since_previous_sample", "disappeared_since_previous_sample"
        })
        new_row = next(row for row in reused["processes"] if row["pid"] == 11)
        self.assertEqual(new_row["process_created_at"], 201.0)
        self.assertIsNone(new_row["cpu_percent"])

    def test_child_created_before_current_parent_generation_is_not_attached(self):
        root = FakeProcess(10, 1, 100.0)
        current_parent = FakeProcess(11, 10, 200.0)
        child_from_old_parent_generation = FakeProcess(12, 11, 150.0)
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: [root, current_parent, child_from_old_parent_generation],
        )
        result = sampler.sample()
        self.assertEqual({row["pid"] for row in result["processes"]}, {10, 11})
        self.assertEqual(child_from_old_parent_generation.resource_reads, 0)

    def test_partial_reads_and_enumeration_errors_never_publish_complete_totals(self):
        root = FakeProcess(10, 1, 100.0, rss=500, private=300)
        unreadable_child = FakeProcess(11, 10, 101.0)
        unreadable_child.memory_info = lambda: (_ for _ in ()).throw(OSError("access denied"))
        unreadable_topology = FakeProcess(12, 10, 102.0)
        unreadable_topology.create_time = lambda: (_ for _ in ()).throw(OSError("process vanished"))

        def process_iter(_attrs):
            yield root
            yield unreadable_child
            yield unreadable_topology
            raise OSError("partial process enumeration")

        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=process_iter,
        )
        result = sampler.sample()

        self.assertEqual(result["observed_process_count"], 1)
        self.assertEqual(result["enumeration_errors"], 1)
        self.assertEqual(result["topology_errors"], 1)
        self.assertEqual(result["resource_read_errors"], 1)
        self.assertFalse(result["snapshot_complete"])
        self.assertFalse(result["aggregates_complete"])
        self.assertIsNone(result["working_set_bytes"])
        self.assertEqual(result["observed_working_set_bytes"], 500)
        self.assertIsNone(result["private_bytes"])

    def test_missing_private_metric_does_not_invalidate_other_complete_aggregates(self):
        root = FakeProcess(10, 1, 100.0, rss=500, private=None, threads=4)
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: [root],
        )

        result = sampler.sample()

        self.assertTrue(result["snapshot_complete"])
        self.assertTrue(result["aggregates_complete"])
        self.assertEqual(result["working_set_bytes"], 500)
        self.assertEqual(result["thread_count"], 4)
        self.assertIsNone(result["private_bytes"])
        self.assertFalse(result["private_bytes_complete"])
        self.assertEqual(result["private_bytes_errors"], 1)
        self.assertEqual(result["resource_read_errors"], 0)

    def test_missing_handle_metric_only_invalidates_handle_aggregate(self):
        root = FakeProcess(10, 1, 100.0, rss=500, private=300, threads=4)
        root.num_handles = None
        sampler = ProcessTreeSampler(
            [ProcessIdentity(10, 100.0)],
            process_iter=lambda _attrs: [root],
        )

        result = sampler.sample()

        self.assertTrue(result["snapshot_complete"])
        self.assertEqual(result["working_set_bytes"], 500)
        self.assertEqual(result["thread_count"], 4)
        self.assertIsNone(result["handle_count"])
        self.assertEqual(result["observed_handle_count"], 0)
        self.assertFalse(result["handle_count_complete"])
        self.assertEqual(result["handle_count_errors"], 1)


if __name__ == "__main__":
    unittest.main()
