"""
Local TCP server of the terminal (user CLI interface).

Provides bi-directional communication between the command line interface (UI)
and the agent's EventBus. Protected by a Handshake mechanism that
ignores OS and IDE port scanners (which like to knock on all open sockets).
"""

import asyncio
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, Optional

from src.utils.logger import main_logger
from src.utils.dtime import get_now_formatted
from src.utils.settings import HostTerminalConfig
from src.l2_interfaces.host.terminal.state import HostTerminalState
from src.l3_agent.companion_gateway import (
    current_companion_turn_id,
    default_response,
    validate_response_envelope,
)


_COMPANION_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_GATEWAY_EVENT_TYPES = frozenset({
    "turn.started",
    "assistant.delta",
    "tool.requested",
    "tool.started",
    "tool.completed",
    "assistant.final",
    "turn.cancelled",
    "turn.error",
})
_GATEWAY_EVENT_BUFFER_SIZE = 512
_GATEWAY_EVENT_MAX_BYTES = 2 * 1024 * 1024
_GATEWAY_DRAIN_TIMEOUT_SECONDS = 2.0


def _valid_companion_turn_id(value: Any) -> str:
    candidate = str(value or "").strip()[:128]
    return candidate if _COMPANION_TURN_ID.fullmatch(candidate) else ""


class HostTerminalClient:
    """
    Local terminal TCP server.
    Manages CLI chat connections and message delivery.
    """

    def __init__(
        self,
        state: HostTerminalState,
        config: HostTerminalConfig,
        data_dir: Path,
        agent_name: str,
        timezone: int,
        control_handler: Optional[
            Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
        ] = None,
    ) -> None:
        """
        Initializes the terminal TCP server.

        Args:
            state: Terminal L0 state.
            config: Configuration.
            data_dir: JAWL local data root directory.
            agent_name: Agent name to display in the UI.
            timezone: Timezone offset.
        """
        self.state = state
        self.config = config
        self.agent_name = agent_name
        self.timezone = timezone
        self.control_handler = control_handler

        self.host = "127.0.0.1"
        self.port = 0  # 0 means the OS will issue any free port automatically

        # Interface state files
        self.history_file = data_dir / "interfaces" / "host" / "terminal" / "history.json"
        self.gateway_events_file = data_dir / "interfaces" / "host" / "terminal" / "gateway_events.json"
        self.port_file = (
            data_dir / "interfaces" / "host" / "terminal" / "terminal.port"
        )  # Port file

        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        self.server: Optional[asyncio.AbstractServer] = None
        self.active_writers: set[asyncio.StreamWriter] = set()
        self._gateway_writers: set[asyncio.StreamWriter] = set()

        # Queue to pass incoming messages/signals to events.py
        # Format: (action_type, payload)
        self.incoming_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._gateway_events: Deque[dict[str, Any]] = deque(maxlen=_GATEWAY_EVENT_BUFFER_SIZE)
        self._gateway_event_seq = 0
        self._gateway_replay_unavailable = False
        self._load_gateway_events()

    async def start(self) -> None:
        """Starts the TCP server and saves the OS-issued port to a file for the UI."""
        self._load_history()

        # OS will issue a free port on its own
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)

        # Retrieve the actual issued port number
        actual_port = self.server.sockets[0].getsockname()[1]
        self.port = actual_port

        # Save it to a file so that the CLI knows where to connect
        self.port_file.write_text(str(actual_port))
        self.state.is_online = True

        main_logger.info(f"[Host OS] Terminal server started ({self.host}:{actual_port})")

    async def stop(self) -> None:
        """Correctly closes all active sockets."""
        self.state.is_online = False

        # Delete port file since it is no longer needed
        if self.port_file.exists():
            try:
                self.port_file.unlink()
            except Exception:
                pass

        for writer in list(self.active_writers):
            writer.close()
            await writer.wait_closed()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        main_logger.info("[Host OS] Terminal server stopped.")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        Coroutine of handling new TCP connection.
        Awaits 'JAWL_HANDSHAKE' password (spam protection) and transmits
        incoming text streams into the queue for processing by the Events module.
        """

        gateway_after: int | None = None
        try:
            # Wait for the handshake password for a maximum of 2 seconds
            handshake = await asyncio.wait_for(reader.readline(), timeout=2.0)
            handshake_text = handshake.decode("utf-8").strip()
            if handshake_text == "JAWL_CONTROL":
                await self._handle_control_client(reader, writer)
                return
            if handshake_text.startswith("JAWL_GATEWAY"):
                parts = handshake_text.split()
                if parts[0] != "JAWL_GATEWAY" or len(parts) > 2:
                    raise ValueError("Invalid gateway handshake.")
                try:
                    gateway_after = max(0, int(parts[1])) if len(parts) == 2 else 0
                except ValueError as exc:
                    raise ValueError("Invalid gateway cursor.") from exc
            elif handshake_text != "JAWL_HANDSHAKE":
                writer.close()
                await writer.wait_closed()
                return
        except Exception:
            # If a port scanner connected and remains silent - drop it
            writer.close()
            return

        # If password is correct - let it in
        self.active_writers.add(writer)
        if gateway_after is not None:
            self._gateway_writers.add(writer)
            await self._send_gateway_replay(writer, gateway_after)

        # A native Companion Gateway is a machine client, not an operator CLI
        # session. It must not wake the agent or make Heartbeat believe a user
        # is watching the terminal.
        if gateway_after is None and not self.state.is_ui_connected:
            self.state.is_ui_connected = True
            main_logger.info("[Host OS] CLI chat connected to the terminal.")
            await self.incoming_queue.put(("_CONNECTION_OPENED", ""))

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break  # Disconnected

                text = data.decode("utf-8").strip()
                if text:
                    # Extract JSON payload
                    try:
                        parsed = json.loads(text)
                        if not isinstance(parsed, dict):
                            parsed = {}
                        if parsed.get("type") == "cancel":
                            turn_id = _valid_companion_turn_id(parsed.get("turn_id"))
                            if turn_id:
                                await self.incoming_queue.put(
                                    (
                                        "_CANCEL",
                                        {
                                            "turn_id": turn_id,
                                            "reason": str(parsed.get("reason") or "")[:2000],
                                        },
                                    )
                                )
                            continue
                        msg_text = parsed.get("text", text)
                        turn_id = _valid_companion_turn_id(parsed.get("turn_id"))
                    except json.JSONDecodeError:
                        msg_text = text
                        turn_id = ""

                    if msg_text:
                        time_str = get_now_formatted(self.timezone, "%Y-%m-%d %H:%M:%S")
                        self._record_message("User", msg_text, time_str)
                        payload: Any = msg_text
                        if turn_id:
                            payload = {"text": msg_text, "turn_id": turn_id}
                        await self.incoming_queue.put(("_MESSAGE", payload))

        except asyncio.CancelledError:
            pass

        except Exception as e:
            main_logger.warning(f"[Host OS] Terminal connection error: {e}")

        finally:
            self.active_writers.discard(writer)
            self._gateway_writers.discard(writer)

            # Check if there are any active sessions left
            legacy_writers = any(
                active not in self._gateway_writers for active in self.active_writers
            )
            if not legacy_writers and self.state.is_ui_connected:
                self.state.is_ui_connected = False
                main_logger.info("[Host OS] CLI chat disconnected from the terminal.")
                await self.incoming_queue.put(("_CONNECTION_CLOSED", ""))

            try:
                writer.close()
                await writer.wait_closed()

            except Exception as e:
                main_logger.debug(f"[Host Terminal] Error closing client session: {e}")

    async def _handle_control_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one bounded operator command without creating a chat event."""

        request_id = ""
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=3.0)
            if len(raw) > 65536:
                raise ValueError("Control request exceeds 64 KiB.")
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Control request must be an object.")
            request_id = str(request.get("id", ""))[:100]
            if request.get("type") != "control":
                raise ValueError("Unsupported control envelope.")
            if self.control_handler is None:
                raise ValueError("Operator controls are unavailable.")
            result = await self.control_handler(
                str(request.get("action", "")),
                request.get("params", {}),
            )
            response = {
                "type": "control_result",
                "id": request_id,
                "ok": True,
                "result": result,
            }
        except Exception as exc:
            response = {
                "type": "control_result",
                "id": request_id,
                "ok": False,
                "error": str(exc)[:2000],
            }
        try:
            writer.write(
                (json.dumps(response, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def broadcast_message(
        self,
        text: str,
        turn_id: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        """
        Asynchronous broadcasting of a message from the agent to all active TCP sessions (open consoles).
        Packs the text into JSON with a timestamp for parsing on the CLI widgets side.

        Args:
            text: Agent message text (supports Markdown).
        """

        time_str = get_now_formatted(self.timezone, "%Y-%m-%d %H:%M:%S")
        self._record_message(self.agent_name, text, time_str)

        turn_id = _valid_companion_turn_id(turn_id or current_companion_turn_id())
        payload_dict: dict[str, Any] = {"text": text, "time": time_str}
        if turn_id:
            response = (
                dict(response)
                if response is not None
                else default_response(text, turn_id)
            )
            validate_response_envelope(response, expected_turn_id=turn_id)
            if response["text"] != str(text):
                raise ValueError("response text must match terminal message text")
            event = await self.emit_gateway_event(
                turn_id,
                "assistant.final",
                {"response": response},
            )
            payload_dict = {"text": text, "time": time_str}
            # emit_gateway_event already sent the typed event. The legacy
            # broadcast remains separate so old CLI clients keep working.
            _ = event
        if not self.active_writers:
            return
        payload = json.dumps(payload_dict, ensure_ascii=False) + "\n"
        data = payload.encode("utf-8")

        for writer in list(self.active_writers):
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                self.active_writers.discard(writer)

    async def emit_gateway_event(
        self, turn_id: str, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Send one bounded, correlated event to native Companion clients."""

        turn_id = _valid_companion_turn_id(turn_id)
        if not turn_id or event_type not in _GATEWAY_EVENT_TYPES or not isinstance(payload, dict):
            return None
        next_event_seq = self._gateway_event_seq + 1
        event = {
            "schema_version": 1,
            "event_seq": next_event_seq,
            "turn_id": turn_id,
            "type": event_type,
            "payload": dict(payload),
        }
        data = (json.dumps({"gateway_event": event}, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        if len(data) > 128 * 1024:
            return None
        self._gateway_events.append(event)
        self._gateway_event_seq = next_event_seq
        self._persist_gateway_events()
        for writer in list(self._gateway_writers):
            try:
                writer.write(data)
                # A terminal event is persisted before it is written, but a
                # wedged local socket must not hold ReAct's terminal path
                # forever after a provider failure.  The Companion can replay
                # the persisted event after reconnecting.
                await asyncio.wait_for(
                    writer.drain(), timeout=_GATEWAY_DRAIN_TIMEOUT_SECONDS
                )
            except Exception:
                self._gateway_writers.discard(writer)
                self.active_writers.discard(writer)
        return event

    def gateway_since(self, after: int = 0) -> list[dict[str, Any]]:
        """Return the bounded native event journal after one cursor."""

        cursor = max(0, int(after))
        return [event for event in self._gateway_events if event["event_seq"] > cursor]

    def gateway_cursor(self, after: int = 0) -> dict[str, Any]:
        """Describe replay availability without silently dropping old events."""

        cursor = max(0, int(after))
        oldest = (
            self._gateway_events[0]["event_seq"]
            if self._gateway_events
            else self._gateway_event_seq + 1
        )
        return {
            "schema_version": 1,
            "after": cursor,
            "oldest_event_seq": oldest,
            "latest_event_seq": self._gateway_event_seq,
            "gap": self._gateway_replay_unavailable or bool(
                self._gateway_events and cursor < oldest - 1
            ),
        }

    async def _send_gateway_replay(self, writer: asyncio.StreamWriter, after: int) -> None:
        packets: list[dict[str, Any]] = [{"gateway_cursor": self.gateway_cursor(after)}]
        packets.extend({"gateway_event": event} for event in self.gateway_since(after))
        try:
            for packet in packets:
                writer.write((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
        except Exception:
            self._gateway_writers.discard(writer)
            self.active_writers.discard(writer)

    def _load_gateway_events(self) -> None:
        try:
            if self.gateway_events_file.stat().st_size > _GATEWAY_EVENT_MAX_BYTES:
                self._gateway_replay_unavailable = True
                return
            payload = json.loads(self.gateway_events_file.read_text(encoding="utf-8"))
            events = payload.get("events") if isinstance(payload, dict) else None
            if not isinstance(events, list):
                self._gateway_replay_unavailable = True
                return
        except (OSError, ValueError, TypeError):
            if self.gateway_events_file.exists():
                self._gateway_replay_unavailable = True
            return
        last = 0
        for event in events[-_GATEWAY_EVENT_BUFFER_SIZE:]:
            if not isinstance(event, dict):
                self._gateway_replay_unavailable = True
                break
            sequence = event.get("event_seq")
            if (
                event.get("schema_version") != 1
                or not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= last
                or not _valid_companion_turn_id(event.get("turn_id"))
                or event.get("type") not in _GATEWAY_EVENT_TYPES
                or not isinstance(event.get("payload"), dict)
            ):
                self._gateway_replay_unavailable = True
                break
            if last and sequence != last + 1:
                self._gateway_replay_unavailable = True
                break
            self._gateway_events.append(dict(event))
            last = sequence
        self._gateway_event_seq = last

    def _persist_gateway_events(self) -> None:
        payload = {"schema_version": 1, "events": list(self._gateway_events)}
        temporary = self.gateway_events_file.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.gateway_events_file)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            main_logger.warning("[Host OS] Native gateway journal unavailable: %s", exc)

    def _record_message(self, sender: str, text: str, time_str: str = "") -> None:
        """Writes message to L0 State and the physical history file."""
        if not time_str:
            time_str = get_now_formatted(self.timezone, "%Y-%m-%d %H:%M:%S")

        self.state.add_message(sender, text, time_str)

        history = self._read_history_file()
        history.append({"time": time_str, "sender": sender, "text": text})

        if len(history) > self.config.history_limit:
            history = history[-self.config.history_limit :]

        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)

    def _read_history_file(self) -> list:
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _load_history(self) -> None:
        """
        Pulls context history from the file on server restart.
        """

        history = self._read_history_file()
        recent = history[-self.config.context_limit :]
        for msg in recent:
            self.state.add_message(msg["sender"], msg["text"], msg.get("time", ""))

    async def get_context_block(self, **kwargs: Any) -> str:
        """Context provider for ContextRegistry."""
        desc = "Description: Direct CLI chat with the system operator/user."
        if not self.state.is_online:
            return f"### HOST TERMINAL [OFF] \n{desc}\nThe interface is disabled."

        ui_status = (
            "The terminal window is opened."
            if self.state.is_ui_connected
            else "The terminal window is closed."
        )
        return f"### HOST TERMINAL [ON]\n{desc}\nStatus: {ui_status}\n\nRecent messages:\n{self.state.formatted_messages}"
