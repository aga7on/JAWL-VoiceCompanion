import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.native_jawl_delivery import (  # noqa: E402
    install_native_delivery_guard,
)


def _classes(run_impl=None):
    class FakeTerminalClient:
        def __init__(self):
            self.events = []
            self.fail_final = False
            self.history = []

        async def broadcast_message(self, text, turn_id=None, response=None):
            self.history.append(text)
            await asyncio.sleep(0)
            await self.emit_gateway_event(turn_id or "turn-batch", "assistant.final", {"response": {"text": text}})

        async def emit_gateway_event(self, turn_id, event_type, payload):
            event = {
                "turn_id": turn_id,
                "type": event_type,
                "payload": dict(payload),
            }
            self.events.append(event)
            if event_type == "assistant.final" and self.fail_final:
                return None
            return event

    class FakeEventBus:
        def __init__(self, client):
            self.client = client
            self.listeners = {}
            self.tasks = set()
            self.published = []

        async def publish(self, event, **kwargs):
            self.published.append((event, dict(kwargs)))

            async def deliver():
                kind = kwargs.get("companion_gateway_type")
                if kind:
                    await self.client.emit_gateway_event(
                        kwargs["companion_turn_id"], kind,
                        {"text": kwargs.get("companion_text", "")},
                    )

            task = asyncio.create_task(deliver())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        async def flush(self, timeout=None):
            while self.tasks:
                await asyncio.gather(*tuple(self.tasks))

    class FakeReactLoop:
        def __init__(self, client, behavior=None):
            self.client = client
            self.behavior = behavior or run_impl
            self.last_cycle_outcome = {"status": "running"}
            self.private_tick_thoughts = ""
            self.sql_ticks = []
            self.event_bus = FakeEventBus(client)
            self.active_turn_id = ""

        async def _handle_completion(self, thoughts, status="completed"):
            self.last_cycle_outcome["status"] = status
            self.sql_ticks.append({"thoughts": thoughts, "status": status})
            if status == "completed":
                await self.event_bus.publish(
                    "react_tick_saved",
                    companion_turn_id=self.active_turn_id,
                    companion_gateway_type="assistant.final",
                    companion_text=thoughts.strip()[:16000],
                )
                await self.event_bus.flush(timeout=3.0)

        async def run(self, event_name, payload, missed_events):
            self.active_turn_id = payload.get("_companion_turn_id", "")
            if self.behavior is not None:
                return await self.behavior(self, event_name, payload, missed_events)
            self.last_cycle_outcome["status"] = "duplicate_success_concluded"
            return None

    return FakeReactLoop, FakeTerminalClient, FakeEventBus


def _install(loop_class, client_class, bus_class, *, timeout=1.0):
    return install_native_delivery_guard(
        loop_class,
        client_class,
        event_bus_class=bus_class,
        terminal_client_resolver=lambda loop: loop.client,
        emit_timeout_seconds=timeout,
    )


class NativeJawlDeliveryGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_batch_broadcasts_are_suppressed_before_history_and_sse(self):
        async def batch(loop, _event, payload, _missed):
            await asyncio.gather(*(loop.client.broadcast_message(text, payload["_companion_turn_id"])
                                   for text in ("first", "second", "third")))
        loop_class, client_class, bus_class = _classes(batch)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        await loop_class(client).run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-batch"}, [])
        self.assertEqual(client.history, ["first"])
        self.assertEqual([event["type"] for event in client.events], ["assistant.final"])
        # Uncorrelated legacy broadcasts retain their behavior outside a cycle.
        await client.broadcast_message("legacy", "other-turn")
        self.assertEqual(client.history, ["first", "legacy"])

    async def test_direct_concurrent_terminal_emits_confirm_once_and_allow_failed_retry(self):
        async def batch(loop, _event, payload, _missed):
            turn = payload["_companion_turn_id"]
            loop.client.fail_final = True
            self.assertIsNone(await loop.client.emit_gateway_event(turn, "assistant.final", {}))
            loop.client.fail_final = False
            results = await asyncio.gather(*(loop.client.emit_gateway_event(turn, "assistant.final", {}) for _ in range(3)))
            self.assertTrue(all(result is results[0] for result in results))
        loop_class, client_class, bus_class = _classes(batch)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        await loop_class(client).run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-batch"}, [])
        self.assertEqual(len(client.events), 2)  # failed attempt, one confirmed retry

    async def test_cycle_without_terminal_gets_one_correlated_fixed_error(self):
        loop_class, client_class, bus_class = _classes()
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        await loop.run(
            "HOST_TERMINAL_MESSAGE",
            {"_companion_turn_id": "turn-missing-1"},
            [],
        )

        self.assertEqual(len(client.events), 1)
        self.assertEqual(client.events[0]["turn_id"], "turn-missing-1")
        self.assertEqual(client.events[0]["type"], "turn.error")
        self.assertEqual(
            client.events[0]["payload"],
            {
                "reason": (
                    "Native ReAct cycle ended without a correlated terminal response."
                )
            },
        )

    async def test_successful_terminal_delivery_is_unchanged_and_has_no_error(self):
        response = {"turn_id": "turn-success-1", "text": "Ответ"}

        async def success(loop, _event_name, payload, _missed):
            loop.last_cycle_outcome["status"] = "yielded"
            await loop.client.emit_gateway_event(
                payload["_companion_turn_id"],
                "assistant.final",
                {"response": response},
            )

        loop_class, client_class, bus_class = _classes(success)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-success-1"}, [])

        self.assertEqual(len(client.events), 1)
        self.assertEqual(client.events[0]["type"], "assistant.final")
        self.assertEqual(client.events[0]["payload"], {"response": response})

    async def test_cancelled_cycle_does_not_receive_a_guard_error(self):
        async def cancel(loop, _event_name, _payload, _missed):
            loop.last_cycle_outcome["status"] = "cancelled"
            raise asyncio.CancelledError

        loop_class, client_class, bus_class = _classes(cancel)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        with self.assertRaises(asyncio.CancelledError):
            await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-cancel-1"}, [])

        self.assertEqual(client.events, [])

    async def test_concurrent_turns_keep_delivery_state_isolated(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def behavior(loop, _event_name, payload, _missed):
            turn_id = payload["_companion_turn_id"]
            if turn_id == "turn-concurrent-a":
                entered.set()
                await release.wait()
                await loop.client.emit_gateway_event(
                    turn_id, "assistant.final", {"response": {"text": "A"}}
                )
            else:
                await entered.wait()
                loop.last_cycle_outcome["status"] = "duplicate_success_concluded"

        loop_class, client_class, bus_class = _classes(behavior)
        _install(loop_class, client_class, bus_class)
        client_a, client_b = client_class(), client_class()
        loop_a, loop_b = loop_class(client_a), loop_class(client_b)
        task_a = asyncio.create_task(
            loop_a.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-concurrent-a"}, [])
        )
        task_b = asyncio.create_task(
            loop_b.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-concurrent-b"}, [])
        )
        await entered.wait()
        await task_b
        release.set()
        await task_a

        self.assertEqual([event["type"] for event in client_a.events], ["assistant.final"])
        self.assertEqual([event["type"] for event in client_b.events], ["turn.error"])
        self.assertEqual(client_b.events[0]["turn_id"], "turn-concurrent-b")

    async def test_failed_final_emission_is_not_counted_as_success(self):
        async def failed_delivery(loop, _event_name, payload, _missed):
            loop.last_cycle_outcome["status"] = "duplicate_success_concluded"
            loop.client.fail_final = True
            await loop.client.emit_gateway_event(
                payload["_companion_turn_id"],
                "assistant.final",
                {"response": {"text": "not delivered"}},
            )

        loop_class, client_class, bus_class = _classes(failed_delivery)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-failed-send"}, [])

        self.assertEqual([event["type"] for event in client.events], ["assistant.final", "turn.error"])
        self.assertEqual(client.events[-1]["turn_id"], "turn-failed-send")

    async def test_private_completion_content_never_enters_error_payload(self):
        private_thought = "private thought must stay in native tick storage"

        async def private_completion(loop, _event_name, _payload, _missed):
            loop.private_tick_thoughts = private_thought
            await loop._handle_completion(private_thought)

        loop_class, client_class, bus_class = _classes(private_completion)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-private-1"}, [])

        self.assertEqual(loop.private_tick_thoughts, private_thought)
        self.assertEqual(loop.sql_ticks[0]["thoughts"], private_thought)
        self.assertEqual(loop.last_cycle_outcome["status"], "completed")
        self.assertEqual(client.events[0]["type"], "turn.error")
        self.assertNotIn(private_thought, repr(client.events[0]["payload"]))
        self.assertNotIn(private_thought, repr(loop.event_bus.published))

    async def test_uncorrelated_background_cycle_is_unchanged(self):
        loop_class, client_class, bus_class = _classes()
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        await loop.run("HEARTBEAT", {}, [])

        self.assertEqual(client.events, [])
        self.assertEqual(loop.last_cycle_outcome["status"], "duplicate_success_concluded")

    async def test_install_is_idempotent(self):
        loop_class, client_class, bus_class = _classes()
        first = _install(loop_class, client_class, bus_class)
        wrapped_run = loop_class.run
        wrapped_emit = client_class.emit_gateway_event
        wrapped_completion = loop_class._handle_completion
        wrapped_publish = bus_class.publish
        second = _install(loop_class, client_class, bus_class)

        self.assertIs(first, second)
        self.assertIs(wrapped_run, loop_class.run)
        self.assertIs(wrapped_emit, client_class.emit_gateway_event)
        self.assertIs(wrapped_completion, loop_class._handle_completion)
        self.assertIs(wrapped_publish, bus_class.publish)

    async def test_default_resolver_uses_existing_terminal_event_listener(self):
        loop_class, client_class, bus_class = _classes()
        install_native_delivery_guard(loop_class, client_class, event_bus_class=bus_class)
        client = client_class()

        class TerminalEventOwner:
            def __init__(self, native_client):
                self.client = native_client

            async def handle(self, **_kwargs):
                return None

        class EventBus:
            def __init__(self, handler):
                self.listeners = {"react_tick_saved": [handler]}

        loop = loop_class(client)
        owner = TerminalEventOwner(client)
        loop.event_bus.listeners = {"react_tick_saved": [owner.handle]}

        await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-resolver-1"}, [])

        self.assertEqual([event["type"] for event in client.events], ["turn.error"])
        self.assertEqual(client.events[0]["turn_id"], "turn-resolver-1")

    async def test_unexpected_native_exception_is_propagated(self):
        async def explode(loop, _event_name, _payload, _missed):
            loop.last_cycle_outcome["status"] = "failed"
            raise ValueError("native failure")

        loop_class, client_class, bus_class = _classes(explode)
        _install(loop_class, client_class, bus_class)
        client = client_class()
        loop = loop_class(client)

        with self.assertRaisesRegex(ValueError, "native failure"):
            await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-exception-1"}, [])

        self.assertEqual([event["type"] for event in client.events], ["turn.error"])


if __name__ == "__main__":
    unittest.main()
