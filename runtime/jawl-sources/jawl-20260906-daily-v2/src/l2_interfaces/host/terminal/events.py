"""
Terminal events orchestrator.

Acts as a bridge (Consumer) between the internal async queue of the TCP server
and the global EventBus of the agent.
"""

import asyncio
import re
from typing import Any
from src.utils.logger import main_logger
from src.utils.event.bus import EventBus
from src.utils.event.registry import Events
from src.l2_interfaces.host.terminal.client import HostTerminalClient


class HostTerminalEvents:
    """Background worker: forwards messages and connection events from the socket queue to EventBus."""

    def __init__(self, client: HostTerminalClient, event_bus: EventBus):
        self.client = client
        self.bus = event_bus
        self._task = None
        self._is_running = False
        self._gateway_event_lock = asyncio.Lock()
        self.bus.subscribe(Events.REACT_TICK_SAVED, self._handle_react_tick)

    @staticmethod
    def _safe_gateway_id(value: Any, fallback: str) -> str:
        candidate = str(value or "").strip()[:128]
        return candidate if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", candidate) else fallback

    async def _emit_action_lifecycle(
        self,
        turn_id: str,
        actions: Any,
        *,
        status: str = "completed",
        summary: str = "JAWL reasoning step completed.",
    ) -> None:
        """Serialize safe tool lifecycle summaries for one correlated turn."""

        raw_actions = actions if isinstance(actions, list) else []
        async with self._gateway_event_lock:
            if not raw_actions:
                await self.client.emit_gateway_event(
                    turn_id,
                    "tool.completed",
                    {"status": status, "summary": summary[:2000]},
                )
                return
            for index, raw_action in enumerate(raw_actions):
                if not isinstance(raw_action, dict):
                    continue
                action_id = self._safe_gateway_id(
                    raw_action.get("action_id"), f"action-{index + 1}"
                )
                tool = self._safe_gateway_id(raw_action.get("tool"), "unknown_tool")
                action_status = str(raw_action.get("status") or status).strip().lower()
                if action_status not in {"completed", "failed", "cancelled", "blocked"}:
                    action_status = (
                        status
                        if status in {"completed", "failed", "cancelled", "blocked"}
                        else "failed"
                    )
                identity = {"action_id": action_id, "tool": tool}
                await self.client.emit_gateway_event(
                    turn_id, "tool.requested", {**identity, "status": "requested"}
                )
                await self.client.emit_gateway_event(
                    turn_id, "tool.started", {**identity, "status": "started"}
                )
                await self.client.emit_gateway_event(
                    turn_id,
                    "tool.completed",
                    {**identity, "status": action_status, "summary": summary[:2000]},
                )

    async def _handle_react_tick(self, **kwargs: Any) -> None:
        """Publish a bounded tool lifecycle summary to native gateway clients."""

        turn_id = kwargs.get("companion_turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            return
        gateway_type = kwargs.get("companion_gateway_type")
        if gateway_type == "turn.cancelled":
            payload = {
                "reason": str(
                    kwargs.get("companion_gateway_reason")
                    or "JAWL cancelled the turn."
                )[:2000]
            }
            async with self._gateway_event_lock:
                await self.client.emit_gateway_event(turn_id, "turn.cancelled", payload)
            return
        if gateway_type == "turn.error":
            payload = {
                "reason": str(
                    kwargs.get("companion_gateway_reason")
                    or "JAWL failed to produce a terminal response."
                )[:2000]
            }
            async with self._gateway_event_lock:
                await self.client.emit_gateway_event(turn_id, "turn.error", payload)
            return
        if gateway_type == "assistant.final":
            text = str(kwargs.get("companion_text") or "").strip()
            internal = re.search(
                r"^\s*(?:\[(?:thoughts?|observation|reasoning|reflection|action|tool)\]|"
                r"(?:thoughts?|observation|reasoning|reflection|action|tool)\s*:|"
                r"</?(?:think|analysis|reasoning|reflection|tool_call|tool_result)\b)",
                text,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            if text and internal is None:
                async with self._gateway_event_lock:
                    await self.client.broadcast_message(text, turn_id=turn_id)
            else:
                async with self._gateway_event_lock:
                    await self.client.emit_gateway_event(
                        turn_id,
                        "turn.error",
                        {"reason": "JAWL completed without a safe user-facing response."},
                    )
            return
        await self._emit_action_lifecycle(
            turn_id,
            kwargs.get("companion_actions"),
            status=str(kwargs.get("companion_action_status") or "completed")[:64],
            summary=str(kwargs.get("companion_action_summary") or "JAWL reasoning step completed."),
        )

    async def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._is_running = False
        if self._task:
            self._task.cancel()
            self._task = None

    @staticmethod
    def _format_status(status: dict[str, Any]) -> str:
        agent = status.get("agent") or {}
        goal = status.get("goal") or {}
        heartbeat = status.get("heartbeat") or {}
        lines = [
            "### JAWL runtime status",
            (
                f"Agent: {agent.get('state', 'unknown')} · "
                f"step {agent.get('step', 0)}/{agent.get('max_steps', 0)} · "
                f"model {agent.get('model', 'unknown')}"
            ),
        ]
        if goal:
            ledger = goal.get("task_ledger") or {}
            lines.extend(
                [
                    (
                        f"Goal: {goal.get('status', 'unknown')} · "
                        f"{goal.get('last_cycle_status', '')}"
                    ),
                    f"Phase: {ledger.get('current_phase', '—')}",
                    f"Next: {ledger.get('next_action') or '—'}",
                ]
            )
        lines.append(
            "Active cycle: "
            + ("yes" if heartbeat.get("active_cycle") else "no")
            + (" · status request did not interrupt it" if heartbeat.get("active_cycle") else "")
        )
        return "\n".join(lines)

    async def _handle_local_command(self, payload: str) -> bool:
        """Serve exact slash commands without steering the active ReAct cycle."""

        command = str(payload or "").strip().casefold()
        if command not in {"/status", "/goal", "/goal status"}:
            return False
        if self.client.control_handler is None:
            await self.client.broadcast_message("Runtime controls are unavailable.")
            return True
        try:
            status = await self.client.control_handler("status.get", {})
            await self.client.broadcast_message(self._format_status(status))
        except Exception as exc:
            await self.client.broadcast_message(
                f"Unable to read runtime status: {str(exc)[:500]}"
            )
        return True

    async def _loop(self):
        while self._is_running:
            try:
                # Await data from the TCP server
                action, payload = await self.client.incoming_queue.get()

                # Publish the corresponding event
                if action == "_CONNECTION_OPENED":
                    await self.bus.publish(
                        Events.HOST_TERMINAL_OPENED,
                        message="Chat terminal opened.",
                    )
                elif action == "_CONNECTION_CLOSED":
                    await self.bus.publish(
                        Events.HOST_TERMINAL_CLOSED,
                        message="Chat terminal closed.",
                    )
                elif action == "_CANCEL":
                    cancel_payload = payload if isinstance(payload, dict) else {}
                    turn_id = str(cancel_payload.get("turn_id", ""))
                    if self.client.control_handler is None:
                        await self.client.emit_gateway_event(
                            turn_id,
                            "turn.error",
                            {"reason": "JAWL runtime controls are unavailable."},
                        )
                        continue
                    try:
                        result = await self.client.control_handler(
                            "react.cancel",
                            cancel_payload,
                        )
                    except Exception as exc:
                        await self.client.emit_gateway_event(
                            turn_id,
                            "turn.error",
                            {"reason": f"Cancellation failed: {str(exc)[:1800]}"},
                        )
                        continue
                    if not result.get("cancelled", False):
                        await self.client.emit_gateway_event(
                            turn_id,
                            "turn.error",
                            {
                                "reason": str(
                                    result.get("reason")
                                    or "No active JAWL turn matched the request."
                                )[:2000]
                            },
                        )
                elif action == "_MESSAGE":
                    turn_id = ""
                    message = payload
                    if isinstance(payload, dict):
                        message = payload.get("text", "")
                        turn_id = str(payload.get("turn_id", ""))[:128]
                    if await self._handle_local_command(str(message)):
                        continue
                    if turn_id:
                        await self.client.emit_gateway_event(
                            turn_id,
                            "turn.started",
                            {"source": "host_terminal", "mode": "react"},
                        )
                    event_kwargs = {"sender_name": "User", "message": str(message)}
                    if turn_id:
                        # Keep transport correlation metadata private to the
                        # ReAct payload.  The loop deliberately consumes the
                        # underscored key so the ID is not rendered as user
                        # context or exposed to the model as ordinary data.
                        event_kwargs["_companion_turn_id"] = turn_id
                    await self.bus.publish(Events.HOST_TERMINAL_MESSAGE, **event_kwargs)

            except asyncio.CancelledError:
                break
            except Exception as e:
                main_logger.error(f"[Host OS] Error processing terminal: {e}")
