"""Live acceptance profile for JAWL's native correlated Companion Gateway.

The profile deliberately uses only the standard library.  It exercises the
real JAWL HTTP/SSE surface and never executes a local fallback tool.  A live
run is opt-in because every normal turn reaches the configured JAWL model.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4


_PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(_PROJECT_SRC))


_MAX_BODY_BYTES = 128 * 1024
_MAX_SSE_LINE_BYTES = 256 * 1024
_TERMINAL_EVENTS = frozenset({"assistant.final", "turn.cancelled", "turn.error"})
_TOOL_EVENTS = frozenset({"tool.requested", "tool.started", "tool.completed"})
_TURN_SETTLE_DELAY_SEC = 0.25
_REQUIRED_NATIVE_TOOL = "jawl_HostTerminalMessages_send_message_to_terminal_f9f78f702e"


class ProfileFailure(RuntimeError):
    """A release-profile assertion failed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loopback_url(value: str, *, allow_remote: bool = False) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--url must not contain credentials, query parameters or fragments")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("--url has no hostname")
    if not allow_remote and hostname.casefold() != "localhost":
        try:
            if not ipaddress.ip_address(hostname).is_loopback:
                raise ValueError("refusing a non-loopback URL; use --allow-remote explicitly")
        except ValueError as exc:
            if "non-loopback" in str(exc):
                raise
            try:
                addresses = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
            except OSError as dns_exc:
                raise ValueError("cannot resolve --url hostname") from dns_exc
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
                raise ValueError("refusing a non-loopback URL; use --allow-remote explicitly")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _with_after(base_url: str, after: int) -> str:
    parsed = urlsplit(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["after"] = str(max(0, int(after)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _validate_cursor(cursor: Any) -> dict[str, Any]:
    if not isinstance(cursor, dict):
        raise ProfileFailure("SSE packet has no cursor object")
    required = {"schema_version", "after", "oldest_event_seq", "latest_event_seq", "gap"}
    if set(cursor) != required:
        raise ProfileFailure("SSE cursor fields do not match schema v1")
    if cursor["schema_version"] != 1 or isinstance(cursor["schema_version"], bool):
        raise ProfileFailure("unsupported SSE cursor schema")
    for field_name in ("after", "oldest_event_seq", "latest_event_seq"):
        value = cursor[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProfileFailure(f"SSE cursor {field_name} is invalid")
    if not isinstance(cursor["gap"], bool):
        raise ProfileFailure("SSE cursor gap must be boolean")
    return cursor


def _validate_packet(packet: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(packet, dict) or set(packet) != {"events", "cursor"}:
        raise ProfileFailure("SSE packet must contain exactly events and cursor")
    events = packet["events"]
    if not isinstance(events, list):
        raise ProfileFailure("SSE packet events must be an array")
    return events, _validate_cursor(packet["cursor"])


class SseBatchReader:
    """Bounded background reader for the native JSON-over-SSE endpoint."""

    def __init__(self, url: str, headers: dict[str, str], timeout: float):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error: Exception | None = None
        self._batches: queue.Queue[Any] = queue.Queue(maxsize=256)
        self._response: Any = None
        self._connected = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def get(self, timeout: float) -> Any | None:
        try:
            return self._batches.get(timeout=max(0.01, timeout))
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        data_lines: list[str] = []
        try:
            request = Request(self.url, headers=self.headers)
            with urlopen(request, timeout=self.timeout) as response:
                with self._lock:
                    self._response = response
                    self._connected = True
                self.ready.set()
                while not self._stop.is_set():
                    line = response.readline()
                    if not line:
                        break
                    if len(line) > _MAX_SSE_LINE_BYTES:
                        raise ProfileFailure("SSE line exceeds the bounded profile limit")
                    decoded = line.decode("utf-8", errors="strict").rstrip("\r\n")
                    if decoded.startswith(":"):
                        continue
                    if decoded.startswith("data:"):
                        data_lines.append(decoded[5:].lstrip())
                    elif not decoded and data_lines:
                        raw = "\n".join(data_lines)
                        data_lines.clear()
                        try:
                            packet = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise ProfileFailure("JAWL SSE returned invalid JSON") from exc
                        try:
                            self._batches.put(packet, timeout=1.0)
                        except queue.Full as exc:
                            raise ProfileFailure("JAWL SSE reader queue overflowed") from exc
        except HTTPError as exc:
            exc.close()
            if not self._stop.is_set():
                self.error = ProfileFailure(f"JAWL SSE returned HTTP {exc.code}")
        except (URLError, OSError, TimeoutError, socket.timeout) as exc:
            if not self._stop.is_set():
                if self._connected:
                    self.error = ProfileFailure(
                        "JAWL SSE read timed out after connection establishment; "
                        "the server emitted no bounded heartbeat/event in time"
                    )
                else:
                    self.error = ProfileFailure(
                        f"JAWL SSE is not reachable: {type(exc).__name__}"
                    )
        except Exception as exc:  # noqa: BLE001 - reader boundary must report, not crash
            if not self._stop.is_set():
                self.error = exc if isinstance(exc, ProfileFailure) else ProfileFailure(
                    f"JAWL SSE reader failed: {type(exc).__name__}: {str(exc)[:120]}"
                )
        finally:
            self.ready.set()
            self.done.set()


@dataclass
class ProfileReport:
    base_url: str
    requested_turns: int
    cancel_requested: bool
    reconnect_requested: bool
    started_at: str = field(default_factory=_utc_now)
    finished_at: str = ""
    completed_turns: int = 0
    cancelled_turns: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    duplicate_events: int = 0
    sequence_gaps: list[dict[str, int]] = field(default_factory=list)
    reconnect_resumed: bool = False
    cancellation_observed: bool = False
    tool_lifecycle_observed: bool = False
    tool_lifecycle_turns: int = 0
    require_tool_lifecycle: bool = False
    failures: list[str] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = _utc_now()

    def as_dict(self) -> dict[str, Any]:
        self.finish()
        return {
            "schema_version": 1,
            "profile": "native-jawl-companion-gateway",
            "base_url": self.base_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "requested_turns": self.requested_turns,
            "completed_turns": self.completed_turns,
            "cancel_requested": self.cancel_requested,
            "cancelled_turns": self.cancelled_turns,
            "reconnect_requested": self.reconnect_requested,
            "reconnect_resumed": self.reconnect_resumed,
            "cancellation_observed": self.cancellation_observed,
            "tool_lifecycle_observed": self.tool_lifecycle_observed,
            "tool_lifecycle_turns": self.tool_lifecycle_turns,
            "require_tool_lifecycle": self.require_tool_lifecycle,
            "event_counts": dict(sorted(self.event_counts.items())),
            "duplicate_events": self.duplicate_events,
            "sequence_gaps": list(self.sequence_gaps),
            "failures": list(self.failures),
            "pass": not self.failures
            and self.completed_turns == self.requested_turns
            and (not self.cancel_requested or self.cancellation_observed)
            and (not self.reconnect_requested or self.reconnect_resumed)
            and (not self.require_tool_lifecycle or self.tool_lifecycle_observed)
            and not self.sequence_gaps,
        }


class NativeGatewayProfile:
    def __init__(self, args: argparse.Namespace):
        self.base_url = _loopback_url(args.url, allow_remote=bool(args.allow_remote))
        self.stream_url = self.base_url + "/api/companion/stream"
        self.turn_url = self.base_url + "/api/companion/turn"
        self.cancel_url = self.base_url + "/api/companion/cancel"
        self.headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **({"X-Console-Token": args.token} if args.token else {}),
        }
        self.json_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **({"X-Console-Token": args.token} if args.token else {}),
        }
        self.timeout = float(args.timeout)
        self.turn_timeout = float(args.turn_timeout)
        self.cancel_delay = float(args.cancel_delay)
        self.prompt_template = args.prompt_template
        self.report = ProfileReport(
            base_url=self.base_url,
            requested_turns=args.turns,
            cancel_requested=not args.skip_cancel,
            reconnect_requested=not args.skip_reconnect,
            require_tool_lifecycle=not bool(getattr(args, "allow_missing_tool_lifecycle", False)),
        )
        self._seen_sequences: set[int] = set()
        self._last_sequence = 0
        self._turn_types: dict[str, set[str]] = {}
        self._lifecycle_turns: set[str] = set()

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, method="POST", headers=self.json_headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_BODY_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            raise ProfileFailure(f"JAWL POST returned HTTP {exc.code}: {url.rsplit('/', 1)[-1]}") from exc
        except (URLError, OSError, TimeoutError, socket.timeout) as exc:
            raise ProfileFailure(f"JAWL POST is not reachable: {url.rsplit('/', 1)[-1]}") from exc
        if len(raw) > _MAX_BODY_BYTES:
            raise ProfileFailure("JAWL POST response exceeds the bounded profile limit")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileFailure("JAWL POST returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ProfileFailure("JAWL POST returned a non-object")
        return result

    def _open_stream(self, after: int) -> SseBatchReader:
        reader = SseBatchReader(_with_after(self.stream_url, after), self.headers, max(5.0, self.timeout))
        reader.start()
        deadline = time.monotonic() + self.timeout
        while not reader.ready.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        if reader.error:
            reader.stop()
            raise reader.error
        if not reader.ready.is_set():
            reader.stop()
            raise ProfileFailure("JAWL SSE did not establish before timeout")
        return reader

    def _first_packet(self, reader: SseBatchReader) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            packet = reader.get(min(0.1, max(0.01, deadline - time.monotonic())))
            if packet is not None:
                return _validate_packet(packet)
            if reader.error:
                raise reader.error
            if reader.done.is_set():
                raise ProfileFailure("JAWL SSE closed before its first packet")
        raise ProfileFailure("JAWL SSE produced no packet before timeout")

    def _consume(self, packet: Any, expected_turn: str | None = None) -> str | None:
        events, cursor = _validate_packet(packet)
        if cursor["gap"]:
            raise ProfileFailure(
                f"JAWL reported an unrecoverable cursor gap after={cursor['after']} "
                f"oldest={cursor['oldest_event_seq']} latest={cursor['latest_event_seq']}"
            )
        terminal: str | None = None
        for raw_event in events:
            if not isinstance(raw_event, dict):
                raise ProfileFailure("JAWL SSE events must be objects")
            try:
                from jawl_voicecompanion.jawl_gateway_contract import JawlGatewayEvent

                event = JawlGatewayEvent.from_mapping(raw_event)
            except ValueError as exc:
                raise ProfileFailure(f"invalid typed JAWL event: {exc}") from exc
            sequence = event.event_seq
            if sequence in self._seen_sequences:
                self.report.duplicate_events += 1
                continue
            if self._last_sequence and sequence != self._last_sequence + 1:
                self.report.sequence_gaps.append({"expected": self._last_sequence + 1, "actual": sequence})
            self._seen_sequences.add(sequence)
            self._last_sequence = sequence
            self.report.event_counts[event.type] = self.report.event_counts.get(event.type, 0) + 1
            turn_types = self._turn_types.setdefault(event.turn_id, set())
            turn_types.add(event.type)
            if event.type in _TOOL_EVENTS:
                if {"tool.requested", "tool.started", "tool.completed"}.issubset(turn_types):
                    self.report.tool_lifecycle_observed = True
                    if event.turn_id not in self._lifecycle_turns:
                        self._lifecycle_turns.add(event.turn_id)
                        self.report.tool_lifecycle_turns += 1
            if event.turn_id == expected_turn and event.type in _TERMINAL_EVENTS:
                terminal = event.type
        return terminal

    def _wait_for_turn(self, reader: SseBatchReader, turn_id: str) -> str:
        deadline = time.monotonic() + self.turn_timeout
        while time.monotonic() < deadline:
            packet = reader.get(min(0.2, max(0.01, deadline - time.monotonic())))
            if packet is not None:
                terminal = self._consume(packet, expected_turn=turn_id)
                if terminal is not None:
                    turn_types = self._turn_types.get(turn_id, set())
                    if "turn.started" not in turn_types:
                        raise ProfileFailure(f"turn {turn_id} has no turn.started event")
                    return terminal
            if reader.error:
                raise reader.error
            if reader.done.is_set():
                raise ProfileFailure(f"JAWL SSE closed without terminal event for {turn_id}")
        raise ProfileFailure(f"turn {turn_id} exceeded {self.turn_timeout:.1f}s")

    def _require_lifecycle(self, reader: SseBatchReader, turn_id: str) -> None:
        """Drain events after a terminal response because JAWL may emit final first."""

        if not self.report.require_tool_lifecycle:
            return
        deadline = time.monotonic() + min(self.turn_timeout, 15.0)
        while time.monotonic() < deadline:
            if turn_id in self._lifecycle_turns:
                return
            packet = reader.get(min(0.2, max(0.01, deadline - time.monotonic())))
            if packet is not None:
                self._consume(packet, expected_turn=turn_id)
                continue
            if reader.error:
                raise reader.error
            if reader.done.is_set():
                break
        raise ProfileFailure(f"turn {turn_id} has no complete tool lifecycle")

    def _submit(self, reader: SseBatchReader, text: str) -> tuple[str, str]:
        turn_id = f"profile-{uuid4().hex}"
        result = self._post(self.turn_url, {"text": text, "turn_id": turn_id})
        if result.get("ok") is not True or result.get("turn_id") != turn_id:
            raise ProfileFailure("JAWL did not acknowledge the correlated turn")
        terminal = self._wait_for_turn(reader, turn_id)
        self._require_lifecycle(reader, turn_id)
        time.sleep(_TURN_SETTLE_DELAY_SEC)
        return turn_id, terminal

    def _run_reconnect_probe(self, reader: SseBatchReader, baseline: int) -> SseBatchReader:
        turn_id = f"profile-reconnect-{uuid4().hex}"
        result = self._post(
            self.turn_url,
            {"text": self.prompt_template.format(index=0), "turn_id": turn_id},
        )
        if result.get("ok") is not True or result.get("turn_id") != turn_id:
            raise ProfileFailure("JAWL did not acknowledge the reconnect probe")
        reader.stop()
        resumed = self._open_stream(baseline)
        terminal = self._wait_for_turn(resumed, turn_id)
        if terminal != "assistant.final":
            resumed.stop()
            raise ProfileFailure(f"reconnect probe ended with {terminal}")
        self._require_lifecycle(resumed, turn_id)
        time.sleep(_TURN_SETTLE_DELAY_SEC)
        self.report.reconnect_resumed = True
        return resumed

    def _run_cancellation_probe(self, reader: SseBatchReader) -> None:
        turn_id = f"profile-cancel-{uuid4().hex}"
        result = self._post(
            self.turn_url,
            {
                "text": "Cancellation probe: perform no tools and wait for the cancellation request.",
                "turn_id": turn_id,
            },
        )
        if result.get("ok") is not True or result.get("turn_id") != turn_id:
            raise ProfileFailure("JAWL did not acknowledge the cancellation probe")
        time.sleep(self.cancel_delay)
        cancel_result = self._post(self.cancel_url, {"turn_id": turn_id, "reason": "release profile"})
        if cancel_result.get("ok") is not True:
            raise ProfileFailure("JAWL rejected the exact cancellation request")
        terminal = self._wait_for_turn(reader, turn_id)
        if terminal != "turn.cancelled":
            raise ProfileFailure(f"cancellation probe ended with {terminal}, not turn.cancelled")
        self.report.cancelled_turns += 1
        self.report.cancellation_observed = True

    def run(self, *, after: int = 0) -> dict[str, Any]:
        reader: SseBatchReader | None = None
        try:
            reader = self._open_stream(after)
            first_events, cursor = self._first_packet(reader)
            self._consume({"events": first_events, "cursor": cursor})
            baseline = cursor["latest_event_seq"]
            if self.report.reconnect_requested:
                reader = self._run_reconnect_probe(reader, baseline)
            if self.report.cancel_requested:
                self._run_cancellation_probe(reader)
            for index in range(1, self.report.requested_turns + 1):
                turn_id, terminal = self._submit(
                    reader,
                    self.prompt_template.format(index=index),
                )
                if terminal != "assistant.final":
                    raise ProfileFailure(f"normal turn {turn_id} ended with {terminal}")
                self.report.completed_turns += 1
        except Exception as exc:  # noqa: BLE001 - convert one profile into a report
            self.report.failures.append(str(exc)[:500])
        finally:
            if reader is not None:
                reader.stop()
        return self.report.as_dict()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("JAWL_WEB_URL", "http://127.0.0.1:8770"))
    parser.add_argument("--token-env", default="JAWL_CONSOLE_TOKEN")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-loopback URL explicitly")
    parser.add_argument("--allow-live-turns", action="store_true", help="required because turns reach the real model")
    parser.add_argument("--dry-run", action="store_true", help="print the profile plan without connecting")
    parser.add_argument("--turns", type=int, default=100)
    parser.add_argument("--after", type=int, default=0, help="known native event cursor to resume from")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP/SSE connect and keep-alive timeout",
    )
    parser.add_argument("--turn-timeout", type=float, default=120.0)
    parser.add_argument("--cancel-delay", type=float, default=0.01)
    parser.add_argument("--skip-cancel", action="store_true")
    parser.add_argument("--skip-reconnect", action="store_true")
    parser.add_argument(
        "--allow-missing-tool-lifecycle",
        action="store_true",
        help="diagnostic only: do not require requested tool.requested/started/completed",
    )
    parser.add_argument(
        "--prompt-template",
        default=(
            "Gateway profile turn {index}: после завершения ответа вызови только "
            "HostTerminalMessages.send_message_to_terminal с text=OK; не вызывай "
            "другие инструменты и не меняй состояние."
        ),
    )
    parser.add_argument("--report", type=Path, help="write the redacted JSON report to this path")
    parser.set_defaults(
        prompt_template=(
            "Gateway profile turn {index}: call exactly one tool named "
            f"{_REQUIRED_NATIVE_TOOL} with text=OK; do not call any other tool "
            "and do not answer with ordinary text."
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if isinstance(args.turns, bool) or not 1 <= args.turns <= 1000:
        raise SystemExit("--turns must be between 1 and 1000")
    if isinstance(args.after, bool) or args.after < 0:
        raise SystemExit("--after must be non-negative")
    if args.dry_run:
        plan = {
            "profile": "native-jawl-companion-gateway",
            "url": args.url,
            "turns": args.turns,
            "cancel_probe": not args.skip_cancel,
            "reconnect_probe": not args.skip_reconnect,
            "live_turns_enabled": args.allow_live_turns,
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.allow_live_turns:
        raise SystemExit("refusing live turns: pass --allow-live-turns (or use --dry-run)")
    token = os.environ.get(args.token_env, "").strip()
    args.token = token
    report = NativeGatewayProfile(args).run(after=args.after)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
