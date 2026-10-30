"""Append read-only process-tree resource snapshots to a JSONL file."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jawl_voicecompanion.process_tree_sampler import ProcessIdentity, ProcessTreeSampler


def append_snapshot(stream: TextIO, sampler: ProcessTreeSampler) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample": sampler.sample(),
    }
    stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()
    return record


def run_monitor(
    sampler: ProcessTreeSampler,
    output_path: Path,
    stop_path: Path,
    interval_seconds: float,
    *,
    ready_path: Path | None = None,
    stop_requested: Callable[[], bool] | None = None,
    max_samples: int | None = None,
) -> int:
    if interval_seconds < 0.05 or interval_seconds > 60:
        raise ValueError("interval_seconds must be between 0.05 and 60")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stop_requested = stop_requested or (lambda: stop_path.exists())
    samples = 0
    deadline = time.monotonic()
    with output_path.open("a", encoding="utf-8", newline="\n") as stream:
        while not stop_requested() and (max_samples is None or samples < max_samples):
            append_snapshot(stream, sampler)
            samples += 1
            if samples == 1 and ready_path is not None:
                ready_path.parent.mkdir(parents=True, exist_ok=True)
                ready_path.write_text("ready\n", encoding="utf-8")
            deadline += interval_seconds
            if deadline < time.monotonic():
                deadline = time.monotonic() + interval_seconds
            while not stop_requested():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.1))
    return samples


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--root-created-at", type=float, required=True, help="Unix creation time in seconds")
    parser.add_argument("--root-label", default="integrated-profile")
    parser.add_argument("--creation-tolerance-seconds", type=float, default=0.05)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sampler = ProcessTreeSampler(
            [ProcessIdentity(args.root_pid, args.root_created_at, args.root_label)],
            creation_tolerance_seconds=args.creation_tolerance_seconds,
        )
        run_monitor(sampler, args.output, args.stop_file, args.interval_seconds, ready_path=args.ready_file)
        return 0
    except Exception as exc:
        print(f"process tree monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
