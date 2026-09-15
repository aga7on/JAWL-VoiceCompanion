import asyncio
import inspect
from typing import Any, Callable

from src.utils.event.registry import EventConfig
from src.utils.logger import main_logger


class EventBus:
    """
    Asynchronous Local Event Bus (Pub/Sub).
    Enables loose coupling between modules.
    Supports both synchronous and asynchronous listeners.
    """

    def __init__(self) -> None:
        self.listeners: dict[str, list[Callable[..., Any]]] = {}
        self.background_tasks: set[asyncio.Task] = set()

    async def _run_handlers(self, tasks: list[Any], event_name: str) -> None:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                main_logger.error(
                    f"[System] Error in event listener for '{event_name}': {res}"
                )

    def subscribe(self, event: EventConfig, handler: Callable[..., Any]) -> None:
        """Binds a callable listener to an event."""

        if event.name not in self.listeners:
            self.listeners[event.name] = []

        self.listeners[event.name].append(handler)
        main_logger.debug(f"[System] Subscription: '{handler.__name__}' -> '{event.name}'")

    async def publish(self, event: EventConfig, *args: Any, **kwargs: Any) -> None:
        """Publishes an event to the bus."""

        if event.name not in self.listeners:
            main_logger.debug(f"[System] Event '{event.name}' has no active subscriptions.")
            return

        handlers = self.listeners[event.name]
        tasks = []

        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                coro = handler(*args, **kwargs)
                tasks.append(coro)
            else:
                tasks.append(asyncio.to_thread(handler, *args, **kwargs))

        if tasks:
            background_task = asyncio.create_task(self._run_handlers(tasks, event.name))
            self.background_tasks.add(background_task)
            background_task.add_done_callback(self.background_tasks.discard)

    def unsubscribe(self, event: EventConfig, handler: Callable[..., Any]) -> None:
        """Removes a subscription listener from an event."""

        if event.name in self.listeners:
            try:
                self.listeners[event.name].remove(handler)
            except ValueError:
                pass

    async def stop(self) -> None:
        """Awaits completion of all background task event executions."""

        await self.flush(timeout=5.0)

    async def flush(self, timeout: float | None = None) -> None:
        """Drain scheduled handlers before a lifecycle/turn context is released.

        Most events are intentionally fire-and-forget. A terminal Companion
        event is different: losing it leaves the browser waiting until its
        outer timeout. Callers that publish such an event can explicitly
        drain the already scheduled handlers without changing ordinary event
        latency. The bound is a safety valve: a broken listener must not keep
        the ReAct task alive forever after the durable action has committed.
        """

        bound = None if timeout is None else max(0.1, float(timeout))
        deadline = None if bound is None else asyncio.get_running_loop().time() + bound
        while self.background_tasks:
            tasks = tuple(self.background_tasks)
            wait = None if deadline is None else max(0.0, deadline - asyncio.get_running_loop().time())
            if wait is not None and wait <= 0.0:
                main_logger.warning(
                    "[System] EventBus flush timed out; terminal context was released."
                )
                return
            try:
                if wait is None:
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True), timeout=wait
                    )
            except asyncio.TimeoutError:
                main_logger.warning(
                    "[System] EventBus flush timed out; terminal context was released."
                )
                return
