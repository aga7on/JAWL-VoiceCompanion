"""Resource accounting for processes in exact launcher-owned Windows Jobs."""
from __future__ import annotations

import time
import psutil


class OwnedResourceSampler:
    def __init__(self, owners, *, process_iter=psutil.process_iter, clock=time.monotonic):
        if not owners or any(not callable(getattr(owner, "owns_pid", None)) for owner in owners):
            raise ValueError("exact runtime owners are required")
        self.owners = tuple(owners)
        self.process_iter = process_iter
        self.clock = clock
        self.previous = {}

    def owned(self, pid):
        return any(owner.owns_pid(pid) for owner in self.owners)

    def sample(self):
        now = self.clock()
        rows, current = [], {}
        # Enumerate PIDs only: never request process arguments, env, or cwd.
        for process in self.process_iter(["pid"]):
            pid = process.pid
            if not self.owned(pid):
                continue
            try:
                created = process.create_time()
                memory = process.memory_info()
                cpu = process.cpu_times()
                total = float(cpu.user + cpu.system)
                if not process.is_running() or process.create_time() != created or not self.owned(pid):
                    continue
                key = (pid, created)
                prior = self.previous.get(key)
                percent = None
                if prior is not None and now > prior[0]:
                    percent = round(max(0., total - prior[1]) / (now - prior[0]) * 100., 2)
                current[key] = (now, total)
                rows.append({"pid": pid, "process_created_at": created,
                             "rss_bytes": memory.rss, "cpu_percent": percent})
            except (psutil.Error, OSError, ValueError):
                continue
        if len(rows) > 256:
            raise RuntimeError("owned process count exceeds resource bound")
        self.previous = current  # exited identities never accumulate
        return {"monotonic_seconds": now, "processes": rows,
                "process_count": len(rows), "rss_bytes": sum(row["rss_bytes"] for row in rows),
                "cpu_percent": round(sum(row["cpu_percent"] or 0 for row in rows), 2),
                "cpu_interval_valid": any(row["cpu_percent"] is not None for row in rows),
                "ownership": "exact_windows_job_and_creation_time"}
