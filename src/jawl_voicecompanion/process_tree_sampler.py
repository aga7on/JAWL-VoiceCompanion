"""Read-only process-tree resource sampler anchored to exact root identities.

The sampler follows PPID links from explicitly supplied PID/creation-time roots.
It never reads command lines, environments, or working directories. Lifecycle
events mean a process appeared/disappeared between two samples; a process that
starts and exits wholly between polls requires an OS event/job-accounting source
and is intentionally not claimed as observable here.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable

import psutil

RECOMMENDED_SAMPLE_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created_at: float
    label: str = "root"


class ProcessTreeSampler:
    """Sample the live descendants of one or more exact process generations."""

    def __init__(
        self,
        roots: Iterable[ProcessIdentity],
        *,
        process_iter: Callable[..., Iterable[Any]] = psutil.process_iter,
        clock: Callable[[], float] = time.monotonic,
        max_processes: int = 512,
        creation_tolerance_seconds: float = 0.001,
    ) -> None:
        self.roots = tuple(roots)
        if not self.roots or any(
            isinstance(root.pid, bool) or not isinstance(root.pid, int) or root.pid <= 0
            or root.created_at < 0 or not root.label
            for root in self.roots
        ):
            raise ValueError("at least one valid exact root identity is required")
        if len({root.pid for root in self.roots}) != len(self.roots):
            raise ValueError("root PIDs must be unique")
        if not 1 <= max_processes <= 4096:
            raise ValueError("max_processes must be between 1 and 4096")
        if creation_tolerance_seconds < 0:
            raise ValueError("creation tolerance cannot be negative")
        self.process_iter = process_iter
        self.clock = clock
        self.max_processes = max_processes
        self.creation_tolerance_seconds = creation_tolerance_seconds
        # Keyed by PID and process creation time: a reused PID starts a new CPU
        # interval and generates an exit+appearance pair rather than inheriting
        # the previous process's counters.
        self.previous: dict[tuple[int, float], tuple[float, float, dict[str, Any]]] = {}
        self._sampled_once = False

    @staticmethod
    def _ppid(process: Any) -> int:
        info = getattr(process, "info", None)
        if isinstance(info, dict) and info.get("ppid") is not None:
            return int(info["ppid"])
        return int(process.ppid())

    def _root_matches(self, process: Any, identity: ProcessIdentity) -> bool:
        try:
            return abs(float(process.create_time()) - identity.created_at) <= self.creation_tolerance_seconds
        except (psutil.Error, OSError, TypeError, ValueError):
            return False

    def sample(self) -> dict[str, Any]:
        now = self.clock()
        all_processes: dict[int, Any] = {}
        children_by_parent: dict[int, list[Any]] = {}
        enumeration_errors = 0
        topology_errors = 0
        topology_rejected = 0
        resource_read_errors = 0
        private_bytes_errors = 0
        handle_count_errors = 0
        try:
            # Only PID/PPID are requested system-wide; resource details are read
            # only after a process has been proven to descend from a root.
            iterator = self.process_iter(["pid", "ppid"])
            for process in iterator:
                try:
                    pid = int(process.pid)
                    parent_pid = self._ppid(process)
                except (psutil.Error, OSError, TypeError, ValueError):
                    enumeration_errors += 1
                    continue
                all_processes[pid] = process
                children_by_parent.setdefault(parent_pid, []).append(process)
                if len(all_processes) > self.max_processes * 16:
                    raise RuntimeError("system process enumeration exceeds safety bound")
        except (psutil.Error, OSError, ValueError):
            enumeration_errors += 1

        reached: dict[int, tuple[Any, float, int, str, bool]] = {}
        missing_roots: list[dict[str, Any]] = []
        for root in self.roots:
            process = all_processes.get(root.pid)
            if process is None or not self._root_matches(process, root):
                missing_roots.append({"pid": root.pid, "created_at": root.created_at, "label": root.label})
                continue
            try:
                created = float(process.create_time())
                parent_pid = self._ppid(process)
                reached[root.pid] = (process, created, parent_pid, root.label, True)
            except (psutil.Error, OSError, TypeError, ValueError):
                topology_errors += 1
                missing_roots.append({"pid": root.pid, "created_at": root.created_at, "label": root.label})

        # Traverse only current PPID edges. Require each child generation to be
        # no older than its current parent generation, preventing PID-reuse
        # attachment to a newer unrelated parent.
        pending = list(reached)
        while pending:
            parent_pid = pending.pop()
            parent_node = reached[parent_pid]
            parent_created, root_label = parent_node[1], parent_node[3]
            for process in children_by_parent.get(parent_pid, ()):
                pid = int(process.pid)
                if pid in reached:
                    continue
                try:
                    if self._ppid(process) != parent_pid:
                        topology_errors += 1
                        continue
                    created = float(process.create_time())
                    if created + self.creation_tolerance_seconds < parent_created:
                        topology_rejected += 1
                        continue
                except (psutil.Error, OSError, TypeError, ValueError):
                    topology_errors += 1
                    continue
                reached[pid] = (process, created, parent_pid, root_label, False)
                pending.append(pid)
                if len(reached) > self.max_processes:
                    raise RuntimeError("owned process tree exceeds configured safety bound")

        current: dict[tuple[int, float], tuple[float, float, dict[str, Any]]] = {}
        rows: list[dict[str, Any]] = []
        for pid, (process, created, parent_pid, root_label, is_root) in reached.items():
            try:
                memory = process.memory_info()
                cpu = process.cpu_times()
                total_cpu = float(cpu.user + cpu.system)
                threads = int(process.num_threads())
                handles: int | None
                try:
                    handle_reader = getattr(process, "num_handles", None)
                    handles = int(handle_reader()) if callable(handle_reader) else None
                    if handles is None:
                        handle_count_errors += 1
                except (psutil.Error, OSError, AttributeError, NotImplementedError, TypeError, ValueError):
                    handles = None
                    handle_count_errors += 1
                # Recheck identity and parent edge after reading counters. This
                # excludes rows sampled across exit/reuse or parent replacement.
                if not process.is_running() or abs(float(process.create_time()) - created) > self.creation_tolerance_seconds:
                    resource_read_errors += 1
                    continue
                if self._ppid(process) != parent_pid:
                    topology_errors += 1
                    continue
                if not is_root:
                    parent = all_processes.get(parent_pid)
                    if parent is None or abs(float(parent.create_time()) - reached[parent_pid][1]) > self.creation_tolerance_seconds:
                        topology_errors += 1
                        continue
                key = (pid, created)
                prior = self.previous.get(key)
                cpu_percent = None
                if prior is not None and now > prior[0]:
                    cpu_percent = round(max(0.0, total_cpu - prior[1]) / (now - prior[0]) * 100.0, 2)
                private = getattr(memory, "private", None)
                row = {
                    "pid": pid,
                    "process_created_at": created,
                    "parent_pid": parent_pid,
                    "root_label": root_label,
                    "is_root": is_root,
                    "cpu_time_seconds": round(total_cpu, 4),
                    "cpu_percent": cpu_percent,
                    "working_set_bytes": int(memory.rss),
                    "private_bytes": int(private) if private is not None else None,
                    "thread_count": threads,
                    "handle_count": handles,
                }
                if private is None:
                    private_bytes_errors += 1
                current[key] = (now, total_cpu, row)
                rows.append(row)
            except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
                resource_read_errors += 1
                continue

        if len(rows) > self.max_processes:
            raise RuntimeError("sampled process tree exceeds configured safety bound")
        events: list[dict[str, Any]] = []
        if self._sampled_once:
            for key in current.keys() - self.previous.keys():
                events.append({"event": "appeared_since_previous_sample", **current[key][2]})
            for key in self.previous.keys() - current.keys():
                events.append({"event": "disappeared_since_previous_sample", **self.previous[key][2]})
        events.sort(key=lambda event: (event["event"], event["root_label"], event["pid"]))
        self.previous = current
        self._sampled_once = True
        rows.sort(key=lambda row: (row["root_label"], row["parent_pid"], row["pid"]))
        snapshot_complete = not (
            enumeration_errors or topology_errors or topology_rejected or resource_read_errors or missing_roots
        )
        observed_working_set = sum(row["working_set_bytes"] for row in rows)
        observed_private = sum(row["private_bytes"] for row in rows if row["private_bytes"] is not None)
        observed_threads = sum(row["thread_count"] for row in rows)
        cpu_values = [row["cpu_percent"] for row in rows if row["cpu_percent"] is not None]
        observed_cpu = round(sum(cpu_values), 2) if cpu_values else None
        cpu_complete = snapshot_complete and bool(rows) and len(cpu_values) == len(rows)
        private_complete = snapshot_complete and private_bytes_errors == 0 and bool(rows)
        observed_handles = sum(row["handle_count"] for row in rows if row["handle_count"] is not None)
        handles_complete = snapshot_complete and handle_count_errors == 0 and bool(rows)
        return {
            "monotonic_seconds": now,
            "processes": rows,
            "process_count": len(rows) if snapshot_complete else None,
            "observed_process_count": len(rows),
            "working_set_bytes": observed_working_set if snapshot_complete else None,
            "observed_working_set_bytes": observed_working_set,
            "private_bytes": observed_private if private_complete else None,
            "observed_private_bytes": observed_private,
            "private_bytes_complete": private_complete,
            "thread_count": observed_threads if snapshot_complete else None,
            "observed_thread_count": observed_threads,
            "handle_count": observed_handles if handles_complete else None,
            "observed_handle_count": observed_handles,
            "handle_count_complete": handles_complete,
            "cpu_percent": observed_cpu if cpu_complete else None,
            "observed_cpu_percent": observed_cpu,
            "cpu_interval_valid": any(row["cpu_percent"] is not None for row in rows),
            "cpu_percent_complete": cpu_complete,
            "snapshot_complete": snapshot_complete,
            "aggregates_complete": snapshot_complete,
            "root_identities_missing": missing_roots,
            "lifecycle_events": events,
            "lifecycle_semantics": "observed_between_samples_not_os_process_notifications",
            "recommended_sample_interval_seconds": RECOMMENDED_SAMPLE_INTERVAL_SECONDS,
            "enumeration_errors": enumeration_errors,
            "topology_errors": topology_errors,
            "topology_rejected_candidates": topology_rejected,
            "resource_read_errors": resource_read_errors,
            "private_bytes_errors": private_bytes_errors,
            "handle_count_errors": handle_count_errors,
            "error_counts": {
                "enumeration": enumeration_errors,
                "topology": topology_errors,
                "resource_read": resource_read_errors,
                "private_bytes_unavailable": private_bytes_errors,
                "handle_count_unavailable": handle_count_errors,
            },
            "ownership": "exact_root_pid_creation_time_and_current_ppid_descendants",
        }
