"""Report scalar-only WASAPI loopback levels for the current output device.

This diagnostic never writes PCM or transcript content. Leave the terminal
visible, run the probe, and play a short known stimulus through the already
selected Windows output while it is sampling.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.system_audio import SystemAudioLoopback  # noqa: E402


def _emit(kind: str, state: dict[str, object]) -> None:
    keys = (
        "backend", "device", "device_index", "host_api_index", "sample_rate", "channels",
        "running", "chunks", "consumer_chunks", "last_chunk_age_ms",
        "last_consumer_chunk_age_ms", "last_chunk_peak_abs", "last_chunk_rms",
        "signal_window_state", "signal_window_duration_ms", "signal_window_wall_span_ms",
        "signal_window_peak_abs", "signal_window_rms", "last_consumer_lag_ms",
        "queue_depth", "queue_high_water", "dropped_chunks", "last_error", "raw_persisted",
    )
    print(json.dumps({"kind": kind, **{key: state.get(key) for key in keys}}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0, help="sampling time in seconds (max 120)")
    parser.add_argument("--interval", type=float, default=0.25, help="scalar polling interval in seconds")
    parser.add_argument(
        "--device-name", default="",
        help="exact output device name; omitted uses the WASAPI default output",
    )
    args = parser.parse_args()
    if not 1 <= args.duration <= 120:
        parser.error("--duration must be between 1 and 120 seconds")
    if not 0.1 <= args.interval <= 2:
        parser.error("--interval must be between 0.1 and 2 seconds")

    capture = SystemAudioLoopback(
        lambda *_: None,
        session_id="loopback-level-probe",
        output_device_name=args.device_name or None,
    )
    try:
        _emit("started", capture.start())
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            time.sleep(min(args.interval, max(0.0, deadline - time.monotonic())))
            _emit("sample", capture.state())
    except KeyboardInterrupt:
        _emit("interrupted", capture.state())
    except Exception as exc:
        _emit("error", {"last_error": f"{type(exc).__name__}: {str(exc)[:180]}", "raw_persisted": False})
        return 1
    finally:
        _emit("stopped", capture.stop(timeout=4.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
