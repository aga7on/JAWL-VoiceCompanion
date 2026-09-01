"""HostOS tool registry and bounded filesystem/process adapters.

The executor is intentionally dry-run by default. Real execution is an
explicit construction choice made by the backend, never by model output.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .hostos_policy import HostOSPolicy
from .models import AccessLevel, RiskClass, ToolDecision, ToolRequest


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk: RiskClass
    description: str
    minimum_level: AccessLevel
    mutating: bool = False


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("sandbox.read", RiskClass.OBSERVE, "Read a bounded file inside the companion sandbox.", AccessLevel.SANDBOX),
    ToolSpec("sandbox.write", RiskClass.WORKSPACE_WRITE, "Write a file inside the companion sandbox.", AccessLevel.SANDBOX, True),
    ToolSpec("filesystem.read", RiskClass.OBSERVE, "Read a bounded file under configured host roots.", AccessLevel.OBSERVER),
    ToolSpec("filesystem.write", RiskClass.WORKSPACE_WRITE, "Write a file under configured workspace roots.", AccessLevel.OPERATOR, True),
    ToolSpec("filesystem.delete", RiskClass.DESTRUCTIVE, "Delete one file under configured host roots.", AccessLevel.ROOT, True),
    ToolSpec("process.inspect", RiskClass.OBSERVE, "Inspect a bounded list of processes.", AccessLevel.OBSERVER),
    ToolSpec("process.managed", RiskClass.PROCESS, "Start a configured executable without a shell.", AccessLevel.OPERATOR, True),
    ToolSpec("process.stop", RiskClass.PROCESS, "Stop a process owned by this executor.", AccessLevel.OPERATOR, True),
    ToolSpec("shell.exec", RiskClass.SHELL, "Run an explicit argv vector on the host.", AccessLevel.ROOT, True),
    ToolSpec("desktop.observe", RiskClass.OBSERVE, "Read a bounded desktop/UI observation.", AccessLevel.OBSERVER),
    ToolSpec("screen.observe", RiskClass.OBSERVE, "Capture one bounded focused-window snapshot.", AccessLevel.OBSERVER),
    ToolSpec("desktop.act", RiskClass.INTERACTIVE, "Perform a bounded desktop UI action.", AccessLevel.OPERATOR, True),
    ToolSpec("desktop.pointer", RiskClass.INTERACTIVE, "Click or move within a fresh foreground-window target.", AccessLevel.OPERATOR, True),
    ToolSpec("desktop.keyboard", RiskClass.INTERACTIVE, "Type bounded text or a hotkey in a fresh foreground window.", AccessLevel.OPERATOR, True),
    ToolSpec("browser.act", RiskClass.INTERACTIVE, "Perform a bounded browser action.", AccessLevel.OPERATOR, True),
)


_SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".git-credentials",
    "id_rsa",
    "id_ed25519",
}


def _within(candidate: Path, roots: Iterable[Path]) -> bool:
    return any(candidate == root or root in candidate.parents for root in roots)


def _sensitive(path: Path) -> bool:
    name = path.name.casefold()
    return name in _SENSITIVE_NAMES or name.endswith((".pem", ".key", ".p12", ".pfx"))


@dataclass
class HostOSExecutor:
    """Dispatch policy-checked tools without leaking raw model arguments."""

    policy: HostOSPolicy
    sandbox_root: Path
    workspace_roots: tuple[Path, ...] = ()
    host_roots: tuple[Path, ...] = ()
    dry_run: bool = True
    allow_sensitive: bool = False
    allowed_executables: frozenset[str] = frozenset()
    ui_automation: Any | None = None
    pointer: Any | None = None
    keyboard: Any | None = None
    browser: Any | None = None
    screen_capture: Any | None = None
    max_read_chars: int = 100_000
    max_output_chars: int = 20_000
    _processes: dict[int, subprocess.Popen] = field(default_factory=dict, repr=False)
    _process_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: set[int] = field(default_factory=set, repr=False)
    _specs: dict[str, ToolSpec] = field(
        default_factory=lambda: {spec.name: spec for spec in TOOL_SPECS}, repr=False
    )

    def __post_init__(self) -> None:
        self.sandbox_root = Path(self.sandbox_root).resolve()
        self.workspace_roots = tuple(Path(root).resolve() for root in self.workspace_roots)
        self.host_roots = tuple(Path(root).resolve() for root in self.host_roots)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "risk": spec.risk.value,
                "description": spec.description,
                "minimum_level": int(spec.minimum_level),
                "mutating": spec.mutating,
            }
            for spec in self._specs.values()
        ]

    def canonicalize(self, request: ToolRequest) -> ToolRequest:
        """Return a request whose risk comes from the registry, not the model."""
        spec = self._specs.get(request.tool)
        return replace(request, risk=spec.risk) if spec else request

    def execute(self, request: ToolRequest, has_approval: bool = False) -> dict[str, Any]:
        spec = self._specs.get(request.tool)
        if spec is None:
            decision = ToolDecision(
                status="denied",
                allowed=False,
                reason="unknown_tool",
                effective_level=self.policy.active_level,
            )
            self.policy.record_tool_decision(request, decision)
            return self._denied(request, decision)

        # Risk is canonical registry data, not a model-controlled field.
        canonical_request = self.canonicalize(request)
        decision = self.policy.authorize(canonical_request, has_approval=has_approval)
        self.policy.record_tool_decision(canonical_request, decision)
        if not decision.allowed:
            return self._denied(canonical_request, decision)

        if self.dry_run:
            return {
                "schema_version": 1,
                "request_id": request.request_id,
                "status": "degraded",
                "tool": request.tool,
                "reason": "dry_run_executor_no_os_side_effects",
                "effective_level": int(decision.effective_level),
                "result": {"summary": "Политика разрешила запрос; реальное действие отключено."},
            }

        try:
            result = self._dispatch(canonical_request)
        except PermissionError as exc:
            return self._failure(canonical_request, "denied", str(exc))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return self._failure(canonical_request, "failed", str(exc)[:500])
        return {
            "schema_version": 1,
            "request_id": request.request_id,
            "status": result.pop("status", "verified"),
            "tool": request.tool,
            "effective_level": int(decision.effective_level),
            "result": result,
        }

    def activate_emergency_stop(self, actor: str = "user") -> dict[str, Any]:
        state = self.policy.set_emergency_stop(True, actor=actor)
        state["stopped_processes"] = self.stop_all()
        return state

    def reset_emergency_stop(self, actor: str = "user") -> dict[str, Any]:
        return self.policy.set_emergency_stop(False, actor=actor)

    def stop_all(self) -> list[int]:
        with self._process_lock:
            items = list(self._processes.items())
            self._cancelled.update(pid for pid, process in items if process.poll() is None)
        stopped = []
        for pid, process in items:
            if process.poll() is None:
                try:
                    process.terminate()
                    stopped.append(pid)
                except OSError:
                    pass
        for _pid, process in items:
            try:
                process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                    process.wait(timeout=0.5)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        with self._process_lock:
            for pid, _process in items:
                self._processes.pop(pid, None)
        return stopped

    def _dispatch(self, request: ToolRequest) -> dict[str, Any]:
        if request.tool in {"sandbox.read", "filesystem.read"}:
            return self._read_file(request)
        if request.tool in {"sandbox.write", "filesystem.write"}:
            return self._write_file(request)
        if request.tool == "filesystem.delete":
            return self._delete_file(request)
        if request.tool == "process.inspect":
            return self._inspect_processes()
        if request.tool == "process.managed":
            return self._start_process(request)
        if request.tool == "process.stop":
            return self._stop_process(request)
        if request.tool == "shell.exec":
            return self._execute_argv(request)
        if request.tool == "desktop.observe":
            if self.ui_automation is None:
                raise PermissionError("Windows UI Automation adapter is unavailable")
            return self.ui_automation.observe()
        if request.tool == "screen.observe":
            if self.screen_capture is None:
                raise PermissionError("screen capture adapter is unavailable")
            include_image = request.arguments.get("include_image", True)
            if not isinstance(include_image, bool):
                raise ValueError("include_image must be boolean")
            return self.screen_capture.observe(include_image=include_image)
        if request.tool == "desktop.act":
            if self.ui_automation is None:
                raise PermissionError("Windows UI Automation adapter is unavailable")
            target = dict(request.target or request.arguments)
            return self.ui_automation.act(
                str(request.arguments.get("operation", "")),
                target,
                request.arguments.get("value"),
            )
        if request.tool == "desktop.pointer":
            if self.pointer is None:
                raise PermissionError("Windows pointer adapter is unavailable")
            target = dict(request.arguments)
            target.update(dict(request.target or {}))
            return self.pointer.act(
                str(request.arguments.get("operation", "")),
                target,
                request.arguments.get("value"),
            )
        if request.tool == "desktop.keyboard":
            if self.keyboard is None:
                raise PermissionError("Windows keyboard adapter is unavailable")
            target = dict(request.arguments)
            target.update(dict(request.target or {}))
            return self.keyboard.act(
                str(request.arguments.get("operation", "")),
                target,
                request.arguments.get("value"),
            )
        if request.tool == "browser.act":
            if self.browser is None:
                raise PermissionError("browser adapter is unavailable")
            target = dict(request.target or request.arguments)
            return self.browser.act(
                str(request.arguments.get("operation", "")),
                target,
                request.arguments.get("value"),
            )
        raise PermissionError("tool adapter is not implemented")

    def _resolve_path(self, request: ToolRequest) -> Path:
        raw = request.arguments.get("path")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("path is required")
        candidate = Path(raw)
        if not candidate.is_absolute():
            if request.tool.startswith("sandbox."):
                candidate = self.sandbox_root / candidate
            else:
                raise PermissionError("relative host paths are not accepted")
        resolved = candidate.resolve(strict=False)
        if _sensitive(resolved) and not self.allow_sensitive:
            raise PermissionError("sensitive path is blocked by policy")

        if request.tool.startswith("sandbox."):
            roots = (self.sandbox_root,)
        elif request.tool == "filesystem.write":
            roots = self.workspace_roots
        else:
            roots = self.host_roots
        if not _within(resolved, roots):
            raise PermissionError("path is outside configured HostOS roots")
        return resolved

    def _read_file(self, request: ToolRequest) -> dict[str, Any]:
        path = self._resolve_path(request)
        if not path.is_file():
            raise ValueError("path is not a file")
        with path.open("rb") as source:
            raw = source.read(self.max_read_chars * 4 + 1)
        truncated = len(raw) > self.max_read_chars * 4
        text = raw.decode("utf-8", errors="replace")[: self.max_read_chars]
        result = {"path": str(path), "text": text, "truncated": truncated}
        if not truncated:
            result["sha256"] = hashlib.sha256(raw).hexdigest()
        return result

    def _write_file(self, request: ToolRequest) -> dict[str, Any]:
        path = self._resolve_path(request)
        text = request.arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("text is required")
        if len(text) > self.max_read_chars:
            raise ValueError("text exceeds bounded write size")
        expected = request.arguments.get("expected_sha256")
        if expected is not None:
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
            if not path.is_file():
                return {"status": "stale_file", "reason": "file_missing_before_conditional_write"}
            actual = self._file_sha256(path)
            if actual is None:
                return {"status": "stale_file", "reason": "file_cannot_be_compared_safely"}
            if actual.casefold() != expected.casefold():
                return {"status": "stale_file", "reason": "file_changed_since_read"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return {"path": str(path), "bytes": len(text.encode("utf-8"))}

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def _delete_file(self, request: ToolRequest) -> dict[str, Any]:
        path = self._resolve_path(request)
        if not path.exists():
            return {"path": str(path), "already_absent": True}
        if not path.is_file():
            raise PermissionError("recursive directory deletion is not supported")
        path.unlink()
        return {"path": str(path), "deleted": True}

    @staticmethod
    def _inspect_processes() -> dict[str, Any]:
        try:
            import psutil
        except ImportError:
            return {"status": "degraded", "summary": "psutil is not installed"}
        rows = []
        for process in psutil.process_iter(["pid", "name", "username", "status"]):
            try:
                info = process.info
                rows.append({
                    "pid": info.get("pid"),
                    "name": str(info.get("name") or "")[:120],
                    "username": str(info.get("username") or "")[:120],
                    "status": str(info.get("status") or "")[:40],
                })
            except (psutil.Error, OSError):
                continue
            if len(rows) >= 100:
                break
        return {"processes": rows, "truncated": len(rows) >= 100}

    def _start_process(self, request: ToolRequest) -> dict[str, Any]:
        executable = request.arguments.get("executable")
        argv = request.arguments.get("argv", [])
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable is required")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be a list of strings")
        if len(argv) > 64:
            raise ValueError("argv is too long")
        executable_path = Path(executable).expanduser().resolve(strict=False)
        allowed = {
            str(Path(item).expanduser().resolve(strict=False)).casefold()
            for item in self.allowed_executables
        }
        if str(executable_path).casefold() not in allowed:
            raise PermissionError("executable path is not in the managed allowlist")
        cwd = request.arguments.get("cwd")
        cwd_path = None
        if cwd is not None:
            if not isinstance(cwd, str):
                raise ValueError("cwd must be a string")
            cwd_request = replace(request, arguments={"path": cwd})
            cwd_path = self._resolve_workspace_path(cwd_request)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(executable_path), *argv],
            cwd=str(cwd_path) if cwd_path else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )
        with self._process_lock:
            self._processes[process.pid] = process
        if self.policy.emergency_stop:
            self.stop_all()
            raise PermissionError("emergency_stop_active")
        return {"status": "dispatched", "pid": process.pid, "verified": False}

    def _stop_process(self, request: ToolRequest) -> dict[str, Any]:
        pid = request.arguments.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise ValueError("pid must be an integer")
        with self._process_lock:
            process = self._processes.get(pid)
        if process is None:
            raise PermissionError("only processes started by this executor can be stopped")
        if process.poll() is None:
            process.terminate()
        with self._process_lock:
            self._processes.pop(pid, None)
        return {"status": "dispatched", "pid": pid, "terminated": True}

    def _execute_argv(self, request: ToolRequest) -> dict[str, Any]:
        argv = request.arguments.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be a non-empty list of strings")
        if len(argv) > 64:
            raise ValueError("argv is too long")
        timeout = request.arguments.get("timeout_sec", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout_sec must be numeric")
        timeout = max(1.0, min(float(timeout), 60.0))
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        with self._process_lock:
            self._processes[process.pid] = process
        if self.policy.emergency_stop:
            self.stop_all()
            raise PermissionError("emergency_stop_active")
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            with self._process_lock:
                cancelled = process.pid in self._cancelled
                self._cancelled.discard(process.pid)
            if cancelled:
                return {"status": "cancelled", "pid": process.pid, "exit_code": process.returncode}
            return {
                "status": "verified" if process.returncode == 0 else "failed",
                "exit_code": process.returncode,
                "stdout": stdout[: self.max_output_chars],
                "stderr": stderr[: self.max_output_chars],
                "truncated": len(stdout) > self.max_output_chars or len(stderr) > self.max_output_chars,
            }
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            finally:
                stdout, stderr = process.communicate()
            return {
                "status": "timeout",
                "pid": process.pid,
                "exit_code": process.returncode,
                "stdout": stdout[: self.max_output_chars],
                "stderr": stderr[: self.max_output_chars],
                "truncated": len(stdout) > self.max_output_chars or len(stderr) > self.max_output_chars,
            }
        finally:
            with self._process_lock:
                self._processes.pop(process.pid, None)

    def _resolve_workspace_path(self, request: ToolRequest) -> Path:
        raw = request.arguments.get("path")
        if not isinstance(raw, str):
            raise ValueError("path is required")
        candidate = Path(raw).resolve(strict=False)
        if not _within(candidate, self.workspace_roots):
            raise PermissionError("working directory is outside configured workspace roots")
        return candidate

    @staticmethod
    def _denied(request: ToolRequest, decision: ToolDecision) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "request_id": request.request_id,
            "status": decision.status,
            "tool": request.tool,
            "reason": decision.reason,
            "effective_level": int(decision.effective_level),
        }

    @staticmethod
    def _failure(request: ToolRequest, status: str, reason: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "request_id": request.request_id,
            "status": status,
            "tool": request.tool,
            "reason": reason,
        }
