"""Opt-in loopback acceptance probe for native JAWL/OpenAI SDK cancellation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
PINNED_PYTHON = ROOT / "runtime/jawl-daily-venv/Scripts/python.exe"
PINNED_SOURCE = ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2"
CHILD_TIMEOUT_SECONDS = 19


def child_environment(root: Path) -> dict[str, str]:
    """Return a credential-clean environment with all JAWL writes in root."""
    instance = root / "instance"
    paths = {
        "JAWL_INSTANCE_ID": "llm-cancel-acceptance",
        "JAWL_INSTANCE_HOME": str(instance),
        "JAWL_DATA_DIR": str(instance / "data"),
        "JAWL_CONFIG_DIR": str(instance / "config"),
        "JAWL_LOG_DIR": str(instance / "logs"),
        "JAWL_PROMPT_DIR": str(instance / "prompts"),
        "JAWL_SANDBOX_DIR": str(instance / "sandbox"),
        "JAWL_ENV_FILE": str(instance / "unused.env"),
    }
    for name in ("data", "config", "logs", "prompts", "sandbox", "cache", "home", "temp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC")
        if os.environ.get(key)
    }
    env.update(paths)
    env.update(
        OPENAI_API_KEY="jawl-loopback-acceptance-key",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        HOME=str(root / "home"),
        USERPROFILE=str(root / "home"),
        TEMP=str(root / "temp"),
        TMP=str(root / "temp"),
        XDG_CACHE_HOME=str(root / "cache"),
        HF_HOME=str(root / "cache" / "hf"),
        NO_PROXY="*",
        no_proxy="*",
    )
    return env


def child_command(python: Path, script: Path, root: Path, report: Path) -> list[str]:
    return [str(python), "-B", str(script), "--child", "--root", str(root), "--report", str(report)]


def run_parent(report: Path | None) -> int:
    if not PINNED_PYTHON.is_file() or not PINNED_SOURCE.is_dir():
        print("BLOCKED: pinned daily Python or source snapshot is missing", file=sys.stderr)
        return 2
    run_root = Path(tempfile.mkdtemp(prefix="jawl-llm-cancel-acceptance-"))
    report_path = report.resolve() if report else run_root / "report.json"
    if report_path.exists():
        print("BLOCKED: report path already exists", file=sys.stderr)
        return 2
    report_path.parent.mkdir(parents=True, exist_ok=True)
    env = child_environment(run_root)
    sys.path.insert(0, str(ROOT / "src"))
    from jawl_voicecompanion.supervisor import _windows_job_object, _assign_to_job, _close_windows_job
    job = _windows_job_object()
    if sys.platform == "win32" and job is None:
        return _write_report(report_path, {"status": "blocked", "reason": "owned_job_unavailable"}, 2)
    child = None
    stdout = stderr = ""
    code = 1
    try:
        child = subprocess.Popen(
            child_command(PINNED_PYTHON, Path(__file__).resolve(), run_root, report_path),
            cwd=run_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if job is not None:
            _assign_to_job(job, child)
        stdout, stderr = child.communicate(timeout=CHILD_TIMEOUT_SECONDS)
        code = child.returncode
    except subprocess.TimeoutExpired:
        print(f"FAILED: child exceeded {CHILD_TIMEOUT_SECONDS}s; isolated run root: {run_root}", file=sys.stderr)
    except Exception as exc:
        print(f"FAILED: probe launch {type(exc).__name__}", file=sys.stderr)
    finally:
        if job is not None:
            _close_windows_job(job)
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=2)
    if stdout:
        print(stdout.rstrip())
    if stderr:
        print("child stderr:", stderr[-2000:], file=sys.stderr)
    if not report_path.exists():
        _write_report(report_path, {"status": "failed", "reason": "child_did_not_finish"}, code or 1)
        code = code or 1
    receipt = json.loads(report_path.read_text(encoding="utf-8"))
    receipt.update(observed_child_exit_code=child.returncode if child is not None else None,
                   owned_job_closed=job is not None, parent_exit_code=code)
    report_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report={report_path}")
    return code


def _child(root: Path, report_path: Path) -> int:
    report: dict[str, object] = {
        "run_id": uuid.uuid4().hex,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "native pinned JAWL OpenAICompatibleProvider; fake loopback HTTP; no model",
        "python": sys.version.split()[0],
        "source_snapshot": str(PINNED_SOURCE),
        "status": "failed",
    }
    server = None
    server_thread = None
    provider = None
    tasks: list[object] = []
    try:
        os.chdir(root)
        sys.path.insert(0, str(PINNED_SOURCE))
        try:
            import httpx
            import openai
            from src.l3_agent.llm.api_keys.rotator import APIKeyRotator
            from src.l3_agent.llm.client import LLMClient
            from src.l3_agent.llm.providers import LLMMessage, LLMRequest, OpenAICompatibleProvider
        except Exception as exc:
            report.update(status="blocked", reason="pinned_import_failed", error_type=type(exc).__name__)
            return _write_report(report_path, report, 2)

        provider_file = PINNED_SOURCE / "src/l3_agent/llm/providers/openai_compatible.py"
        report.update(
            openai_sdk_version=openai.__version__,
            httpx_version=httpx.__version__,
            provider_source_sha256=hashlib.sha256(provider_file.read_bytes()).hexdigest(),
        )

        state = ProbeState()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), state.handler_type())
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        server_thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        client = LLMClient(endpoint, APIKeyRotator(["jawl-loopback-acceptance-key"]), connect_timeout=2, read_timeout=5)
        provider = OpenAICompatibleProvider(client, request_timeout_seconds=8)

        import asyncio

        async def exercise() -> None:
            async def invoke(label: str):
                request = LLMRequest(
                    model="loopback-fixture",
                    messages=(LLMMessage(role="user", content=label),),
                    stream=True,
                    timeout_seconds=8,
                )
                return await provider.complete(request)

            async def wait_event(event: threading.Event, label: str) -> None:
                if not await asyncio.to_thread(event.wait, 2.0):
                    raise AssertionError(f"server did not reach {label}")

            try:
                for label, phase in (("cancel-before-headers", "preheaders"), ("cancel-mid-stream", "midstream")):
                    task = asyncio.create_task(invoke(label))
                    tasks.append(task)
                    await wait_event(state.event(label, "ready"), f"{phase} request")
                    if phase == "midstream":
                        await wait_event(state.event(label, "chunk_sent"), "first streaming chunk")
                        await asyncio.sleep(0.08)
                    state.cancelled_at[label] = time.perf_counter()
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, 2.0)
                    except asyncio.CancelledError:
                        pass
                    else:
                        raise AssertionError(f"{label} did not propagate task cancellation")
                    await wait_event(state.event(label, "eof"), "client connection EOF")
                    elapsed = state.eof_at[label] - state.cancelled_at[label]
                    if not 0 <= elapsed <= 1.0:
                        raise AssertionError(f"{label} connection EOF took {elapsed:.3f}s")
                    if state.counts[label] != 1:
                        raise AssertionError(f"{label} attempted {state.counts[label]} requests")

                task_a = asyncio.create_task(invoke("concurrent-A"))
                task_b = asyncio.create_task(invoke("concurrent-B"))
                tasks.extend((task_a, task_b))
                await wait_event(state.event("concurrent-A", "ready"), "concurrent A")
                await wait_event(state.event("concurrent-B", "ready"), "concurrent B")
                await wait_event(state.event("concurrent-B", "chunk_sent"), "concurrent B streaming")
                if task_b.done():
                    raise AssertionError("concurrent B finished before A was cancelled")
                state.cancelled_at["concurrent-A"] = time.perf_counter()
                task_a.cancel()
                try:
                    await asyncio.wait_for(task_a, 2.0)
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("cancelling concurrent A did not cancel its task")
                await wait_event(state.event("concurrent-A", "eof"), "concurrent A EOF")
                if not 0 <= state.eof_at["concurrent-A"] - state.cancelled_at["concurrent-A"] <= 1.0:
                    raise AssertionError("concurrent A connection did not close within 1s")
                if state.counts["concurrent-A"] != 1 or state.counts["concurrent-B"] != 1:
                    raise AssertionError("concurrent request was retried")
                state.event("concurrent-B", "release").set()
                result_b = await asyncio.wait_for(task_b, 2.0)
                if result_b.content != "B completed":
                    raise AssertionError("cancelling A prevented concurrent B from completing")

                followup = await asyncio.wait_for(invoke("same-client-followup"), 2.0)
                if followup.content != "follow-up succeeded" or state.counts["same-client-followup"] != 1:
                    raise AssertionError("same SDK client follow-up failed or retried")
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.wait_for(provider.close(), 2.0)

        asyncio.run(exercise())
        report.update(
            status="passed",
            assertions={
                "cancel_before_response_headers_closes_connection_le_1s": True,
                "cancel_mid_stream_closes_connection_le_1s": True,
                "cancelled_requests_not_retried": True,
                "same_client_followup_succeeded": True,
                "cancelling_A_preserved_concurrent_B": True,
                "request_counts": state.counts,
                "connection_eof_ms": {
                    key: round((value - state.cancelled_at[key]) * 1000, 2)
                    for key, value in state.eof_at.items()
                    if key in state.cancelled_at
                },
            },
        )
        return _write_report(report_path, report, 0)
    except Exception as exc:
        report.update(status="failed", reason=type(exc).__name__, detail=str(exc)[:400])
        return _write_report(report_path, report, 1)
    finally:
        import asyncio
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(1.0)


class ProbeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.events: dict[tuple[str, str], threading.Event] = {}
        self.eof_at: dict[str, float] = {}
        self.cancelled_at: dict[str, float] = {}

    def event(self, label: str, phase: str) -> threading.Event:
        with self.lock:
            return self.events.setdefault((label, phase), threading.Event())

    def handler_type(self):
        state = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                label = payload["messages"][-1]["content"]
                with state.lock:
                    state.counts[label] = state.counts.get(label, 0) + 1
                state.event(label, "ready").set()
                if label in {"cancel-before-headers", "concurrent-A"}:
                    state.wait_for_eof(self, label)
                    return
                if label == "cancel-mid-stream":
                    state.start_stream(self)
                    state.write_stream_chunk(self, state.sse_chunk("partial"))
                    state.event(label, "chunk_sent").set()
                    state.wait_for_eof(self, label)
                    return
                if label == "concurrent-B":
                    state.start_stream(self)
                    state.write_stream_chunk(self, state.sse_chunk("B completed"))
                    state.event(label, "chunk_sent").set()
                    if not state.event(label, "release").wait(3.0):
                        return
                    state.write_stream_chunk(self, state.sse_chunk("", finish="stop") + b"data: [DONE]\n\n")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    return
                answer = "follow-up succeeded"
                body = state.sse_chunk(answer) + state.sse_chunk("", finish="stop") + b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

        return Handler

    @staticmethod
    def sse_chunk(content: str, finish: str | None = None) -> bytes:
        choice = {"index": 0, "delta": {"content": content} if content else {}, "finish_reason": finish}
        return ("data: " + json.dumps({"id": "loopback", "model": "loopback-fixture", "choices": [choice]}) + "\n\n").encode()

    @staticmethod
    def start_stream(handler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()

    @staticmethod
    def write_stream_chunk(handler, payload: bytes) -> None:
        handler.wfile.write(f"{len(payload):X}\r\n".encode() + payload + b"\r\n")
        handler.wfile.flush()

    def wait_for_eof(self, handler, label: str) -> None:
        handler.connection.settimeout(4.0)
        try:
            while handler.connection.recv(1):
                pass
        except ConnectionResetError:
            pass
        except socket.timeout:
            return
        except OSError:
            return
        self.eof_at[label] = time.perf_counter()
        self.event(label, "eof").set()


def _write_report(path: Path, report: dict[str, object], code: int) -> int:
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["exit_code"] = code
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-runtime-probe", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        if args.root is None or args.report is None:
            parser.error("child mode requires isolated root and report")
        return _child(args.root.resolve(), args.report.resolve())
    if not args.allow_runtime_probe:
        parser.error("pass --allow-runtime-probe to run the real pinned SDK probe")
    return run_parent(args.report)


if __name__ == "__main__":
    raise SystemExit(main())
