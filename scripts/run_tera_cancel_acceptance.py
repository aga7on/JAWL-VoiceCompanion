"""Opt-in, RAM-guarded CPU Tera service cancellation and WAV follow-up probe.

Starts an isolated, supervised worker on an ephemeral loopback port. Never
uses the daily worker, microphone, speakers, GPU, or protected upstream writes.
"""
from __future__ import annotations

import argparse
from array import array
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.resources import ResourceGovernor  # noqa: E402
from jawl_voicecompanion.runtime_manifest import load_runtime_manifest  # noqa: E402
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec  # noqa: E402
from jawl_voicecompanion.tts import TeraTTSHttpClient, TTSService, TTSCancelled  # noqa: E402

GIB = 1024 ** 3
TEXTS = (
    "Привет, я снова могу говорить после остановки.",
    "Сегодня проверяем русский голос на процессоре.",
    "Следующий ответ не должен содержать остатки прошлой реплики.",
)


def free_ram() -> int:
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    *[(name, ctypes.c_ulonglong) for name in
                      ("total", "available", "page_total", "page_available",
                       "virtual_total", "virtual_available", "extended")]]
    if sys.platform != "win32":
        raise RuntimeError("this guarded probe requires Windows memory accounting")
    state = Memory()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise OSError("memory accounting failed")
    return int(state.available)


class RamGuard:
    def __init__(self, stop, *, floor: int, seconds: float = 120.0):
        self.stop = stop
        self.floor = floor
        self.deadline = time.monotonic() + seconds
        self.minimum = free_ram()
        self.reason = None
        self.stop_error = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self):
        while not self.done.wait(0.05):
            try:
                available = free_ram()
                self.minimum = min(self.minimum, available)
                reason = "ram_floor" if available < self.floor else None
                if time.monotonic() >= self.deadline:
                    reason = "probe_deadline"
            except Exception:
                reason = "ram_accounting_failed"
            if reason or self.reason:
                self.reason = self.reason or reason
                try:
                    self.stop()  # only the supervisor's owned Job/process
                except Exception as exc:
                    self.stop_error = type(exc).__name__
                # start() clears its stop flag on entry. Keep signalling until
                # cleanup joins us, so a guard/start race cannot lose Stop and
                # leave a newly started worker without a watchdog.

    def check(self):
        if self.reason:
            raise RuntimeError("resource guard stopped the probe")

    def close(self):
        self.done.set()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("resource guard failed to join")


def listener_pids(port: int) -> set[int]:
    # Read-only OS evidence, not a scan of process command lines or credentials.
    command = (f"@(Get-NetTCPConnection -State Listen -LocalPort {int(port)} "
               "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess "
               "-Unique) | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=8, check=True)
    value = json.loads(result.stdout) if result.stdout.strip() else []
    return set(value if isinstance(value, list) else [value])


def wav_info(data: bytes) -> dict:
    if not isinstance(data, bytes) or not 44 < len(data) <= 8 * 1024 * 1024:
        raise ValueError("invalid WAV size")
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() <= 0:
            raise ValueError("expected mono PCM16")
        duration = wav.getnframes() / wav.getframerate()
        rate = wav.getframerate()
        pcm = array("h", wav.readframes(wav.getnframes()))
    if sys.byteorder != "little":
        pcm.byteswap()
    rms = (sum(value * value for value in pcm) / max(1, len(pcm))) ** 0.5 / 32768
    if duration <= 0 or rms <= 0.00001:
        raise ValueError("empty or silent WAV")
    return {"bytes": len(data), "sample_rate": rate, "duration_seconds": duration,
            "rms": round(rms, 6), "sha256": hashlib.sha256(data).hexdigest()}


def wait_until(predicate, guard: RamGuard, seconds: float):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        guard.check()
        if predicate():
            return
        guard.done.wait(0.025)
    raise TimeoutError("bounded probe condition was not observed")


def probe(report: dict, report_path: Path):
    available = free_ram()
    report["available_ram_before_start_bytes"] = available
    if available < 4 * GIB:
        report.update(status="skipped", reason="requires_4_GiB_available_before_start")
        return
    manifest = load_runtime_manifest()
    python = Path(manifest["models"]["tera_python"])
    release = Path(manifest["models"]["tera_release"])
    if not python.is_file() or not release.is_dir():
        raise ValueError("selected Tera inputs are missing")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({})).open  # never send localhost via inherited proxy
    client = TeraTTSHttpClient(url, timeout_seconds=10, opener=opener)

    def health():
        with opener(url + "/health", timeout=0.4) as response:
            return json.loads(response.read(16384))

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    supervisor = RuntimeSupervisor([WorkerSpec(
        "tera-probe", [str(python), "-B", str(ROOT / "scripts/teratts_server.py"),
                       "--release-dir", str(release), "--voice", "ru_f1",
                       "--model", "distilled", "--threads", "24",
                       "--host", "127.0.0.1", "--port", str(port)],
        probe=lambda: health().get("status") == "ok", cwd=str(ROOT), env=environment,
        startup_timeout_seconds=45, max_restarts=0, stop_timeout_seconds=2,
    )])
    guard = RamGuard(supervisor.stop, floor=int(1.5 * GIB))
    governor = ResourceGovernor()
    service = TTSService(client, governor)
    consumer = None
    owned_pid = None
    proven_listeners = set()
    guard.thread.start()
    try:
        guard.check()
        started = time.perf_counter()
        startup = supervisor.start()
        report["startup_seconds"] = round(time.perf_counter() - started, 3)
        guard.check()
        if not startup.ok:
            report["startup"] = startup.workers
            raise RuntimeError("owned Tera worker did not start")
        owned_pid = startup.worker_summary("tera-probe")["pid"]
        report.update(worker_pid=owned_pid, ephemeral_port=port,
                      provider="CPUExecutionProvider", voice="ru_f1", model="distilled", threads=24)
        # Close the port-selection race before any inference/cancel mutation.
        observed = listener_pids(port)
        report["listener_pids_before_inference"] = sorted(observed)
        if not observed or not all(supervisor.owns_pid(pid) for pid in observed):
            raise RuntimeError("listener ownership could not be proven")
        proven_listeners = observed
        report["health"] = health()
        if report["health"].get("cancel_capability") != "scoped_onnx_run_options":
            raise RuntimeError("selected cancellation capability is unavailable")
        outcome = {"chunks": 0, "result": "running"}

        def consume():
            try:
                text = ("Это длинная тестовая реплика для проверки остановки синтеза " * 35).strip()
                for _audio in service.stream(text, voice="ru_f1", request_id="tera-probe-cancel"):
                    outcome["chunks"] += 1
                outcome["result"] = "completed_without_cancel"
            except Exception as exc:
                outcome["result"] = type(exc).__name__

        consumer = threading.Thread(target=consume, daemon=True)
        consumer.start()
        wait_until(lambda: health().get("running") is True, guard, 5)
        cancel_started = time.perf_counter()
        service.cancel(request_id="tera-probe-cancel")
        wait_until(lambda: not consumer.is_alive(), guard, 3)
        consumer.join(0)
        report["cancel_client_ms"] = round((time.perf_counter() - cancel_started) * 1000, 3)
        wait_until(lambda: health().get("pending") == 0 and not governor.state()["active"], guard, 3)
        report["cancel_worker_and_lease_idle_ms"] = round((time.perf_counter() - cancel_started) * 1000, 3)
        report["cancel_outcome"] = outcome
        if outcome["result"] != TTSCancelled.__name__:
            raise AssertionError("cancelled stream did not report TTSCancelled")
        sample_dir = report_path.parent / (report_path.stem + "-samples")
        sample_dir.mkdir(exist_ok=False)
        report["samples"] = []
        for index, text in enumerate(TEXTS, 1):
            guard.check()
            started = time.perf_counter()
            chunks = list(service.stream(text, voice="ru_f1", request_id=f"tera-probe-followup-{index}"))
            elapsed = time.perf_counter() - started
            if len(chunks) != 1:
                raise AssertionError("short follow-up must contain one WAV")
            info = wav_info(chunks[0])
            sample_path = sample_dir / f"ru-{index}.wav"
            with sample_path.open("xb") as audio:
                audio.write(chunks[0])
            info.update(text=text, path=str(sample_path.relative_to(ROOT)),
                        complete_wav_seconds=round(elapsed, 3), rtf=round(elapsed / info["duration_seconds"], 3))
            report["samples"].append(info)
        wait_until(lambda: health().get("pending") == 0 and not governor.state()["active"], guard, 3)
        report["status"] = "passed"
    finally:
        errors = []

        def cleanup_step(name, action):
            try:
                return action()
            except Exception as exc:
                errors.append({"stage": name, "error_type": type(exc).__name__})
                return None

        # One failed cleanup must not skip the other owned resources/evidence.
        cleanup_step("service_close", service.close)
        cleanup_step("supervisor_stop", supervisor.stop)
        cleanup_step("guard_close", guard.close)
        if consumer is not None:
            cleanup_step("consumer_join", lambda: consumer.join(12))
            report["consumer_joined"] = not consumer.is_alive()
            if consumer.is_alive():
                report.update(status="failed", reason="consumer_did_not_join")
        report["minimum_available_ram_bytes"] = guard.minimum
        report["guard_reason"] = guard.reason
        report["guard_stop_error"] = guard.stop_error
        cleanup = cleanup_step("supervisor_health", supervisor.health)
        if cleanup is not None:
            report["cleanup"] = cleanup.workers
        if owned_pid is not None:
            listeners = cleanup_step("listener_evidence", lambda: listener_pids(port))
            report["owned_listener_gone"] = listeners is not None and not (
                {owned_pid, *proven_listeners} & listeners)
            if not report["owned_listener_gone"]:
                report.update(status="failed", reason="owned_listener_remained_or_unverified")
        if guard.reason:
            report.update(status="failed", reason=guard.reason)
        if errors or guard.stop_error:
            report.update(status="failed", reason="cleanup_error", cleanup_errors=errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-tera", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_real_tera:
        parser.error("explicit --allow-real-tera is required")
    path = args.report.resolve()
    if not path.is_relative_to((ROOT / "runtime").resolve()):
        parser.error("report must be a new file under this repository's runtime directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "status": "running", "scope": "actual_tera_cpu_service_probe",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "limitations": ["No microphone, playback, ASR, LLM or acoustic quality acceptance",
                              "Health proves admitted inference, not the precise native-kernel cancel instant",
                              "Three WAVs are not a p95 or whole-profile real-time SLA"],
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  "scripts/teratts_server.py", "src/jawl_voicecompanion/tts.py",
                  "src/jawl_voicecompanion/supervisor.py", "src/jawl_voicecompanion/onnx_cancellation.py",
                  "scripts/run_tera_cancel_acceptance.py")}}
    # Reserve unique output before loading weights; preserve terminal evidence.
    with path.open("x+", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.flush()
        try:
            probe(report, path)
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
        report["ended_at"] = datetime.now(timezone.utc).isoformat()
        report["exit_code"] = 0 if report["status"] == "passed" else 2 if report["status"] == "skipped" else 1
        output.seek(0)
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.truncate()
    print(json.dumps(report, ensure_ascii=True))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
