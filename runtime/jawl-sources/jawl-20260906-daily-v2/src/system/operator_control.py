"""Bounded localhost operator controls used by the CLI without an LLM round trip."""

from __future__ import annotations

import re
from typing import Any, Dict

from src.l3_agent.goals.ledger import TaskLedgerPatch
from src.l3_agent.skills.schema import ActionCall
from src.l3_agent.skills.registry import (
    call_skill,
    execute_action_plan,
    get_skill_catalog,
)
from src.system.container import SystemContainer
from src.utils.event.registry import EventLevel


class OperatorControl:
    """Expose a small allowlisted runtime/Goal control surface."""

    def __init__(self, container: SystemContainer) -> None:
        self.container = container

    def _manager(self):
        manager = self.container.goal_manager
        if manager is None:
            raise ValueError("Goal Mode is not initialized.")
        return manager

    def _host_os(self):
        host_os = getattr(self.container, "l2_clients", {}).get("host_os")
        if host_os is None:
            raise ValueError("HostOS is not initialized.")
        return host_os

    def _wake_goal(self, goal_id: str) -> None:
        heartbeat = self.container.heartbeat
        if heartbeat is not None:
            heartbeat.answer_to_event(
                EventLevel.CRITICAL,
                "GOAL_OPERATOR_CONTROL",
                {"goal_id": str(goal_id)[:64]},
            )

    async def _call_registered_skill(
        self, skill_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run a native skill through the shared journal/lifecycle boundary."""

        outcomes = await execute_action_plan(
            [ActionCall(tool_name=skill_name, parameters=arguments)],
            lambda action: call_skill(skill_name, action.parameters),
        )
        outcome = outcomes[0]
        return {
            "skill": skill_name,
            "is_success": outcome.is_success,
            "message": outcome.message,
            "action_id": outcome.action_id,
        }

    def _status(self) -> Dict[str, Any]:
        state = self.container.agent_state
        manager = self.container.goal_manager
        heartbeat = self.container.heartbeat
        return {
            "agent": {
                "instance_id": getattr(
                    self.container, "instance_id", "default"
                ),
                "state": (
                    getattr(getattr(state, "state", None), "value", None)
                    if state is not None
                    else "starting"
                ),
                "model": getattr(state, "llm_model", "unknown"),
                "step": getattr(state, "current_step", 0),
                "max_steps": getattr(state, "max_react_steps", 0),
                "uptime": state.get_uptime() if state is not None else "",
                "last_input_tokens": getattr(state, "last_input_tokens", 0),
                "last_action_error": str(
                    getattr(state, "last_action_error", "")
                )[:1000],
            },
            "modes": {
                "provider": {
                    "kind": self.container.settings.llm.provider.kind,
                    "name": (
                        self.container.settings.llm.provider.display_name
                        or self.container.settings.llm.provider.kind
                    ),
                    "capabilities": (
                        getattr(self.container, "llm_provider").capabilities.public()
                        if getattr(self.container, "llm_provider", None) is not None
                        else self.container.settings.llm.provider.resolved_capabilities()
                    ),
                },
                "thinking_policy": self.container.settings.llm.thinking_policy,
                "tool_transport": self.container.settings.llm.tool_transport,
                "continuous_cycle": (
                    self.container.settings.system.continuous_cycle
                ),
                "heartbeat_interval": (
                    self.container.settings.system.heartbeat_interval
                ),
                "goal_mode": self.container.settings.system.goal_mode.model_dump(),
                "idle_heartbeat_backoff": (
                    self.container.settings.system.idle_heartbeat_backoff.model_dump()
                ),
                "event_policy": (
                    self.container.settings.system.event_acceleration.active_cycle_policy
                ),
                "mcp_enabled": self.container.interfaces_config.mcp.enabled,
                "debug_broker": (
                    self.container.interfaces_config.debug_broker.model_dump()
                ),
                "media": (
                    self.container.interfaces_config.multimodality.model_dump()
                ),
            },
            "goal": manager.view() if manager is not None else None,
            "heartbeat": (
                heartbeat.get_queue_snapshot() if heartbeat is not None else None
            ),
            "host_os": (
                self.container.l2_clients["host_os"].policy_snapshot()
                if "host_os" in getattr(self.container, "l2_clients", {})
                else None
            ),
        }

    async def handle(
        self, action: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(action, str) or len(action) > 100:
            raise ValueError("Invalid control action.")
        if not isinstance(params, dict):
            raise ValueError("Control params must be an object.")

        if action == "status.get":
            return self._status()
        if action == "skills.catalog":
            raw_prefixes = params.get(
                "prefixes", ["HostOS", "HostTerminal", "DebugBroker"]
            )
            if not isinstance(raw_prefixes, list) or not raw_prefixes:
                raise ValueError("skills.catalog prefixes must be a non-empty array")
            prefixes = []
            for prefix in raw_prefixes:
                if not isinstance(prefix, str) or prefix not in {
                    "HostOS", "HostTerminal", "DebugBroker"
                }:
                    raise ValueError("skills.catalog contains an unsupported namespace")
                if prefix not in prefixes:
                    prefixes.append(prefix)
            limit = params.get("limit", 256)
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("skills.catalog limit must be an integer")
            return {
                "schema_version": 1,
                "prefixes": prefixes,
                "skills": get_skill_catalog(prefixes=prefixes, limit=limit),
            }
        if action == "agent.journal":
            journal = getattr(self.container, "action_journal", None)
            if journal is None:
                raise ValueError("Action journal is not initialized.")
            raw_limit = params.get("limit", 20)
            if (
                isinstance(raw_limit, bool)
                or not isinstance(raw_limit, int)
                or not 1 <= raw_limit <= 50
            ):
                raise ValueError("journal limit must be an integer from 1 to 50.")
            state = str(params.get("state") or "").strip() or None
            allowed_states = {
                None, "completed", "failed", "cancelled", "error",
                "in_progress", "interrupted", "reconciled",
            }
            if state not in allowed_states:
                raise ValueError("Unsupported journal state.")
            return {
                "source": "jawl.action_journal",
                "plans": await journal.recent_plans(
                    limit=raw_limit, state=state, include_events=False
                ),
            }
        if action == "react.cancel":
            turn_id = str(params.get("turn_id", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", turn_id):
                raise ValueError("Invalid Companion turn ID.")
            heartbeat = self.container.heartbeat
            if heartbeat is None:
                raise ValueError("Heartbeat is not initialized.")
            return heartbeat.cancel_companion_turn(
                turn_id,
                str(params.get("reason") or "Companion requested cancellation.")[:2000],
            )
        if action == "hostos.policy.get":
            return self._host_os().policy_snapshot()
        if action == "hostos.autonomy.issue":
            if params.get("confirm") is not True:
                raise ValueError("Issuing unattended ROOT access requires confirm=true.")
            return self._host_os().issue_autonomy_lease(
                int(params.get("ttl_seconds", 3600)),
                actor=str(params.get("actor") or "operator"),
            )
        if action == "hostos.autonomy.revoke":
            return self._host_os().revoke_autonomy_lease(
                actor=str(params.get("actor") or "operator"),
                reason=str(params.get("reason") or "Operator revoked autonomy"),
            )
        if action == "hostos.emergency_stop":
            host_os = self._host_os()
            result = host_os.set_emergency_stop(
                True,
                actor=str(params.get("actor") or "operator"),
                reason=str(params.get("reason") or "Operator emergency stop"),
            )
            # Stop exact managed script handles as part of the same native
            # authority.  Other subprocess classes are still governed by
            # their own bounded timeout/shutdown paths.
            sessions = getattr(self.container, "host_os_process_sessions", None)
            if sessions is not None:
                await sessions.stop()
            execution = getattr(self.container, "host_os_execution", None)
            if execution is not None:
                result["terminated_execution_processes"] = await execution.stop_active_processes()
            return result
        if action == "hostos.emergency_stop.reset":
            if params.get("confirm") is not True:
                raise ValueError("Clearing emergency stop requires confirm=true.")
            return self._host_os().set_emergency_stop(
                False,
                actor=str(params.get("actor") or "operator"),
                reason="Operator cleared emergency stop",
            )
        if action == "hostos.skill":
            skill_name = str(params.get("skill") or "").strip()
            if not re.fullmatch(r"Host(?:OS|Terminal)[A-Za-z0-9_.-]{1,120}", skill_name):
                raise ValueError("Only registered native HostOS/HostTerminal skills are allowed.")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("HostOS skill arguments must be an object.")
            return await self._call_registered_skill(skill_name, arguments)
        if action.startswith("memory."):
            sql = getattr(self.container, "sql", None)
            memory = getattr(sql, "structured_memory", None) if sql is not None else None
            if memory is None:
                raise ValueError("Structured memory is not initialized.")
            if action == "memory.list":
                return {"memories": await memory.read_active(
                    str(params.get("kind") or "").strip() or None,
                    int(params.get("limit", 50)),
                )}
            if action in {"memory.remember", "memory.revise", "memory.forget", "memory.archive"}:
                names = {
                    "memory.remember": "SQLStructuredMemory.remember",
                    "memory.revise": "SQLStructuredMemory.revise_memory",
                    "memory.forget": "SQLStructuredMemory.forget_memory",
                    "memory.archive": "SQLStructuredMemory.archive_memory",
                }
                return await self._call_registered_skill(names[action], params)
            raise ValueError(f"Unsupported control action '{action}'.")
        if action.startswith("debug."):
            broker = self.container.l2_clients.get("debug_broker")
            if broker is None:
                raise ValueError("Debug Broker is not initialized.")
            if action == "debug.get":
                session_id = str(params.get("session_id", "")).strip() or None
                if session_id is not None and not re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,128}", session_id
                ):
                    raise ValueError("Invalid debug session ID.")
                return broker.session_snapshot(session_id)
            if action == "debug.search":
                query = str(params.get("query", ""))
                provider = str(params.get("provider", "")).strip() or None
                limit = int(params.get("limit", 12))
                return broker.search_operations(query, provider, limit)
            if action == "debug.start":
                options = params.get("options", {})
                if not isinstance(options, dict):
                    raise ValueError("Debug session options must be an object.")
                target = str(params.get("target", "")).strip() or None
                return await broker.start_session(
                    str(params.get("provider", "")),
                    target,
                    options,
                )
            if action == "debug.stop":
                session_id = str(params.get("session_id", "")).strip()
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", session_id):
                    raise ValueError("Invalid debug session ID.")
                return await broker.stop_session(session_id)
            if action == "debug.skill":
                skill_name = str(params.get("skill", ""))
                allowed = {
                    "DebugBroker.list_providers",
                    "DebugBroker.search_operations",
                    "DebugBroker.start_session",
                    "DebugBroker.call_operation",
                    "DebugBroker.wait_session",
                    "DebugBroker.session_snapshot",
                    "DebugBroker.stop_session",
                }
                if skill_name not in allowed:
                    raise ValueError("Only DebugBroker skills are allowed here.")
                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("Debug skill arguments must be an object.")
                return await self._call_registered_skill(skill_name, arguments)
            raise ValueError(f"Unsupported control action '{action}'.")
        manager = self._manager()
        if action == "goal.get":
            goal = manager.view(str(params.get("goal_id", "")))
            if goal is None:
                raise ValueError("Goal not found.")
            return goal
        if action == "goal.list":
            return {"goals": manager.list_views(int(params.get("limit", 20)))}
        if action == "goal.create":
            goal = await manager.create(
                str(params.get("objective", "")),
                token_budget=params.get("token_budget"),
                linked_task_id=str(params.get("linked_task_id", "")),
                verification_policy=str(
                    params.get("verification_policy", "auto")
                ),
            )
            # Tests and an operator may create the durable record before the
            # triggering turn. The default remains the native heartbeat wake;
            # opting out is explicit and local-only.
            if params.get("wake", True) is not False:
                self._wake_goal(goal.goal_id)
            return manager.view(goal.goal_id)
        if action == "goal.update":
            status = str(params.get("status", ""))
            goal = await manager.update(
                status=status,
                summary=str(params.get("summary", "")),
                goal_id=str(params.get("goal_id", "")),
                token_budget=params.get("token_budget"),
            )
            if status == "active":
                self._wake_goal(goal.goal_id)
            return manager.view(goal.goal_id)
        if action == "goal.wakeup":
            seconds = params.get("wake_after_seconds")
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int)
                or seconds < 1
                or seconds > 86400
            ):
                raise ValueError(
                    "wake_after_seconds must be between 1 and 86400."
                )
            goal = await manager.finish_cycle(
                state="waiting",
                summary=str(params.get("summary", "")),
                wake_after_seconds=seconds,
            )
            if goal is None:
                raise ValueError("No active goal.")
            return manager.view(goal.goal_id)
        if action == "goal.ledger.update":
            patch = TaskLedgerPatch.model_validate(params.get("patch", {}))
            goal = await manager.record_ledger_patch(patch)
            if goal is None:
                raise ValueError("No active goal.")
            return manager.view(goal.goal_id)
        raise ValueError(f"Unsupported control action '{action}'.")
