"""Dependency-free local restart/soak profile for the Companion server."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(base_url: str, path: str, timeout: float) -> dict:
    request = Request(base_url + path, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read(256 * 1024).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} returned a non-object payload")
    return payload


def wait_for_health(process: subprocess.Popen, base_url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited during startup ({process.returncode})")
        try:
            return request_json(base_url, "/api/health", 0.75)
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            last_error = str(exc)[:200]
            time.sleep(0.1)
    raise TimeoutError(last_error)


def port_is_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def stop_process(process: subprocess.Popen, timeout: float) -> str:
    if process.poll() is not None:
        return "already_exited"
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError):
            process.terminate()
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
        return "graceful"
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
        return "forced"


def run_profile(args: argparse.Namespace) -> dict:
    root = Path(__file__).resolve().parents[1]
    python_exe = str(args.python or sys.executable)
    report = {
        "schema_version": 1,
        "profile": "companion_restart_soak",
        "cycles_requested": args.cycles,
        "cycles_completed": 0,
        "health_samples": 0,
        "forced_stops": 0,
        "port_leaks": 0,
        "cycles": [],
        "status": "failed",
    }
    for cycle in range(1, args.cycles + 1):
        port = free_loopback_port()
        presentation_port = free_loopback_port()
        while presentation_port == port:
            presentation_port = free_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        started = time.monotonic()
        item = {"cycle": cycle, "port": port, "presentation_port": presentation_port}
        try:
            process = subprocess.Popen(
                [
                    python_exe,
                    "-m",
                    "jawl_voicecompanion",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--presentation-host",
                    "127.0.0.1",
                    "--presentation-port",
                    str(presentation_port),
                ],
                cwd=root,
                env={**os.environ, "PYTHONPATH": str(root / "src")},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as exc:
            item["error"] = str(exc)[:240]
            item["port_released"] = port_is_closed(port) and port_is_closed(presentation_port)
            report["cycles"].append(item)
            break
        try:
            health = wait_for_health(process, base_url, args.startup_timeout)
            item["health_status"] = str(health.get("status") or "")[:40]
            item["health_samples"] = 1
            report["health_samples"] += 1
            for path in ("/api/resources", "/api/vision/status"):
                request_json(base_url, path, 1.0)
                item["health_samples"] += 1
                report["health_samples"] += 1
            for _ in range(args.probes - 1):
                request_json(base_url, "/api/health", 1.0)
                item["health_samples"] += 1
                report["health_samples"] += 1
            stop_mode = stop_process(process, args.shutdown_timeout)
            item["stop_mode"] = stop_mode
            if stop_mode == "forced":
                report["forced_stops"] += 1
            item["port_released"] = port_is_closed(port) and port_is_closed(presentation_port)
            if not item["port_released"]:
                report["port_leaks"] += 1
            item["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
            report["cycles_completed"] += 1
            report["cycles"].append(item)
            if not item["port_released"]:
                raise RuntimeError("server port was not released after shutdown")
        except Exception as exc:
            item["error"] = str(exc)[:240]
            if process.poll() is None:
                stop_process(process, args.shutdown_timeout)
            item["port_released"] = port_is_closed(port) and port_is_closed(presentation_port)
            report["cycles"].append(item)
            break
    report["status"] = "passed" if report["cycles_completed"] == args.cycles and report["port_leaks"] == 0 else "failed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Companion restart/soak profile")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--probes", type=int, default=3)
    parser.add_argument("--startup-timeout", type=float, default=10.0)
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)
    parser.add_argument("--python", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=Path("runtime/restart-soak.json"))
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100 or not 1 <= args.probes <= 100:
        parser.error("--cycles and --probes must be between 1 and 100")
    result = run_profile(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
