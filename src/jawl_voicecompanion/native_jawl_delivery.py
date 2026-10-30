"""Owned guard for correlated native JAWL cycle completion.

The extension confirms one native terminal delivery per active correlated cycle
without changing its payload, suppressing repeated terminal broadcasts.
If a correlated ReAct cycle returns without a terminal event, it emits one
bounded ``turn.error``.  It never turns private tick/thought content into reply
text and never changes native goal state.

The per-turn cycle state lives natively in ``src.l3_agent.companion_gateway``
(``CompanionCycleState``); this module only wires the guard installation over
the native classes. Policy denial and companion-turn queries are kernel
concerns (``goals.policy_completion``, ``CompanionTurnState``).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib
import re
import sys
from typing import Any, Callable


_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MISSING_REPLY_REASON = (
    "Native ReAct cycle ended without a correlated terminal response."
)
_DEFAULT_EMIT_TIMEOUT_SECONDS = 1.0
_MAX_EMIT_TIMEOUT_SECONDS = 5.0
_INSTALL_ATTR = "__jawl_native_delivery_guard_installation__"


def _cycle_module():
    """Resolve the kernel cycle-state module lazily (no native import at load)."""
    module = sys.modules.get("src.l3_agent.companion_gateway")
    if module is None:
        from src.l3_agent import companion_gateway as module
    return module


def _cycle_state_cls():
    return _cycle_module().CompanionCycleState


def _active_state(turn_id: Any):
    return _cycle_module().find_active_cycle(turn_id)


def _valid_turn_id(value: Any) -> str:
    return _cycle_module().valid_cycle_turn_id(value)


def _cycle_turn_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = kwargs.get("payload")
    if payload is None and len(args) >= 2:
        payload = args[1]
    if not isinstance(payload, dict):
        return ""
    return _valid_turn_id(payload.get("_companion_turn_id"))


def _record_terminal_event(
    client: Any, turn_id: Any, event_type: Any, result: Any
) -> None:
    _cycle_module().record_cycle_terminal_event(client, turn_id, event_type, result)


def _remember_terminal_client(client: Any, turn_id: Any) -> None:
    _cycle_module().remember_cycle_terminal_client(client, turn_id)


def _default_terminal_client_resolver(
    loop: Any, terminal_client_class: type
) -> Any:
    """Resolve the client already attached to the loop's terminal event hook."""

    event_bus = getattr(loop, "event_bus", None)
    listeners = getattr(event_bus, "listeners", None)
    if not isinstance(listeners, dict):
        raise RuntimeError("native terminal event listener is unavailable")

    clients: dict[int, Any] = {}
    for handlers in listeners.values():
        if not isinstance(handlers, (list, tuple)):
            continue
        for handler in handlers:
            owner = getattr(handler, "__self__", None)
            client = getattr(owner, "client", None)
            if isinstance(client, terminal_client_class):
                clients[id(client)] = client

    if len(clients) != 1:
        raise RuntimeError("native terminal client resolution is ambiguous")
    return next(iter(clients.values()))


@dataclass
class NativeDeliveryGuardInstallation:
    """Handle returned by :func:`install_native_delivery_guard`."""

    react_loop_class: type
    terminal_client_class: type
    event_bus_class: type
    terminal_client_resolver: Callable[[Any], Any]
    emit_timeout_seconds: float


def _load_native_classes() -> tuple[type, type, type]:
    """Import pinned native classes only when the owned launcher installs us."""

    loop_module = importlib.import_module("src.l3_agent.react.loop")
    terminal_module = importlib.import_module(
        "src.l2_interfaces.host.terminal.client"
    )
    bus_module = importlib.import_module("src.utils.event.bus")
    return (
        loop_module.ReactLoop,
        terminal_module.HostTerminalClient,
        bus_module.EventBus,
    )


def install_native_delivery_guard(
    react_loop_class: type | None = None,
    terminal_client_class: type | None = None,
    *,
    event_bus_class: type | None = None,
    terminal_client_resolver: Callable[[Any], Any] | None = None,
    emit_timeout_seconds: float = _DEFAULT_EMIT_TIMEOUT_SECONDS,
) -> NativeDeliveryGuardInstallation:
    """Install the owned completion guard on the native JAWL classes.

    With no arguments, native classes are imported lazily for the owned
    launcher.  Tests may inject fake classes and a resolver that maps a loop
    instance to its fake terminal client.  The default resolver follows the
    existing bound terminal event listener on ``loop.event_bus``.
    """

    if (
        isinstance(emit_timeout_seconds, bool)
        or not isinstance(emit_timeout_seconds, (int, float))
        or not 0 < emit_timeout_seconds <= _MAX_EMIT_TIMEOUT_SECONDS
    ):
        raise ValueError("emit_timeout_seconds must be within (0, 5]")

    if (
        react_loop_class is None
        or terminal_client_class is None
        or event_bus_class is None
    ):
        loaded_loop, loaded_client, loaded_bus = _load_native_classes()
        react_loop_class = react_loop_class or loaded_loop
        terminal_client_class = terminal_client_class or loaded_client
        event_bus_class = event_bus_class or loaded_bus

    if not isinstance(react_loop_class, type) or not isinstance(
        terminal_client_class, type
    ) or not isinstance(event_bus_class, type):
        raise TypeError("native delivery guard requires class objects")

    resolver = terminal_client_resolver or (
        lambda loop: _default_terminal_client_resolver(
            loop, terminal_client_class
        )
    )
    existing_loop = vars(react_loop_class).get(_INSTALL_ATTR)
    existing_client = vars(terminal_client_class).get(_INSTALL_ATTR)
    existing_bus = vars(event_bus_class).get(_INSTALL_ATTR)
    if existing_loop is not None or existing_client is not None or existing_bus is not None:
        if (
            existing_loop is not None
            and existing_loop is existing_client
            and existing_loop.react_loop_class is react_loop_class
            and existing_loop.terminal_client_class is terminal_client_class
            and existing_loop.event_bus_class is event_bus_class
            and existing_bus is existing_loop
        ):
            return existing_loop
        raise RuntimeError("native delivery guard is partially or differently installed")

    original_run = getattr(react_loop_class, "run", None)
    original_completion = getattr(react_loop_class, "_handle_completion", None)
    original_emit = getattr(terminal_client_class, "emit_gateway_event", None)
    original_broadcast = getattr(terminal_client_class, "broadcast_message", None)
    original_publish = getattr(event_bus_class, "publish", None)
    if not all(
        callable(method)
        for method in (
            original_run,
            original_completion,
            original_emit,
            original_publish,
        )
    ):
        raise TypeError(
            "native classes do not expose required completion, run, emit, and publish methods"
        )

    installation = NativeDeliveryGuardInstallation(
        react_loop_class=react_loop_class,
        terminal_client_class=terminal_client_class,
        event_bus_class=event_bus_class,
        terminal_client_resolver=resolver,
        emit_timeout_seconds=float(emit_timeout_seconds),
    )

    async def observed_emit(
        client: Any, turn_id: str, event_type: str, payload: dict[str, Any]
    ) -> Any:
        async def emit():
            _remember_terminal_client(client, turn_id)
            result = await original_emit(client, turn_id, event_type, payload)
            _record_terminal_event(client, turn_id, event_type, result)
            return result

        state = _active_state(turn_id)
        if state is None or event_type not in {"assistant.final", "turn.error", "turn.cancelled"}:
            return await emit()
        async with state.emit_lock:
            if state.terminal_event:
                return state.terminal_result
            return await emit()

    async def guarded_broadcast(client, text, turn_id=None, response=None):
        # Native tool batches may contain several terminal actions even though
        # terminate_loop ends the cycle only after the whole batch. Suppress
        # repeats before native history/legacy writers as well as typed SSE.
        current = _cycle_module().current_companion_cycle()
        effective_turn = turn_id or (current.turn_id if current is not None else "")
        state = _active_state(effective_turn)
        if state is None:
            return await original_broadcast(client, text, turn_id=turn_id, response=response)
        async with state.broadcast_lock:
            if state.terminal_event:
                return None
            return await original_broadcast(client, text, turn_id=turn_id, response=response)

    async def guarded_completion(
        loop: Any, thoughts: str, status: str = "completed"
    ) -> Any:
        current = _cycle_module().current_companion_cycle()
        if current is None or status != "completed":
            return await original_completion(loop, thoughts, status)
        # The pinned native method persists thoughts to sql_ticks, then asks the
        # event bus to publish them as assistant.final. Keep the persistence and
        # native status transition, but strip only that correlated gateway
        # envelope at the EventBus boundary below.
        current.suppress_private_completion = True
        return await original_completion(loop, thoughts, status)

    async def guarded_publish(
        bus: Any, event: Any, *args: Any, **kwargs: Any
    ) -> Any:
        current = _cycle_module().current_companion_cycle()
        if (
            current is not None
            and current.suppress_private_completion
            and _valid_turn_id(kwargs.get("companion_turn_id")) == current.turn_id
            and kwargs.get("companion_gateway_type") == "assistant.final"
        ):
            kwargs = dict(kwargs)
            kwargs.pop("companion_turn_id", None)
            kwargs.pop("companion_gateway_type", None)
            kwargs.pop("companion_text", None)
        return await original_publish(bus, event, *args, **kwargs)

    async def emit_missing_terminal(
        loop: Any, state: Any, *, preserve_error: bool
    ) -> None:
        if state.terminal_event:
            return
        outcome = getattr(loop, "last_cycle_outcome", None)
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if status == "cancelled":
            return

        try:
            from src.l3_agent.goals.policy_completion import NATIVE_POLICY_DENIAL_REASON
            client = state.terminal_client
            if not isinstance(client, terminal_client_class):
                client = installation.terminal_client_resolver(loop)
            emit = getattr(client, "emit_gateway_event", None)
            if not callable(emit):
                raise RuntimeError("native terminal gateway emitter is unavailable")
            result = await asyncio.wait_for(
                emit(
                    state.turn_id,
                    "turn.error",
                    {"reason": NATIVE_POLICY_DENIAL_REASON if state.policy_denied else _MISSING_REPLY_REASON},
                ),
                timeout=installation.emit_timeout_seconds,
            )
        except Exception:
            if preserve_error:
                return
            raise
        if not (
            isinstance(result, dict)
            and result.get("turn_id") == state.turn_id
            and result.get("type") == "turn.error"
        ):
            error = RuntimeError("native turn.error delivery was not confirmed")
            if not preserve_error:
                raise error

    async def guarded_run(loop: Any, *args: Any, **kwargs: Any) -> Any:
        turn_id = _cycle_turn_id(args, kwargs)
        if not turn_id:
            return await original_run(loop, *args, **kwargs)

        gateway = _cycle_module()
        state = _cycle_state_cls()(
            turn_id=turn_id, parent=gateway.current_companion_cycle(), native_loop=loop
        )
        payload = kwargs.get("payload")
        if payload is None and len(args) >= 2:
            payload = args[1]
        if isinstance(payload, dict):
            state.user_message = str(payload.get("message") or "")[:2000]
        token = gateway.bind_companion_cycle(state)
        try:
            try:
                result = await original_run(loop, *args, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception:
                await emit_missing_terminal(loop, state, preserve_error=True)
                raise
            await emit_missing_terminal(loop, state, preserve_error=False)
            return result
        finally:
            state.closed = True
            gateway.reset_companion_cycle(token)

    observed_emit.__name__ = getattr(original_emit, "__name__", "emit_gateway_event")
    guarded_run.__name__ = getattr(original_run, "__name__", "run")
    guarded_run.__doc__ = getattr(original_run, "__doc__", None)
    guarded_completion.__name__ = getattr(
        original_completion, "__name__", "_handle_completion"
    )
    guarded_publish.__name__ = getattr(original_publish, "__name__", "publish")
    setattr(terminal_client_class, "emit_gateway_event", observed_emit)
    setattr(react_loop_class, "run", guarded_run)
    setattr(react_loop_class, "_handle_completion", guarded_completion)
    setattr(event_bus_class, "publish", guarded_publish)
    if callable(original_broadcast):
        setattr(terminal_client_class, "broadcast_message", guarded_broadcast)
    setattr(terminal_client_class, _INSTALL_ATTR, installation)
    setattr(react_loop_class, _INSTALL_ATTR, installation)
    setattr(event_bus_class, _INSTALL_ATTR, installation)
    return installation


async def emit_active_delta(text: str, *, event_format: str = "speech") -> bool:
    """Emit one bounded ``assistant.delta`` for the active correlated cycle.

    Delegates to the kernel implementation in ``companion_gateway`` (the reply
    sentence is already extracted from the partially generated JSON envelope,
    so the Companion can start speaking before the envelope closes).  Never
    raises into the model path.
    """
    return await _cycle_module().emit_active_delta(text, event_format=event_format)


__all__ = ["NativeDeliveryGuardInstallation", "emit_active_delta", "install_native_delivery_guard"]
