"""Execute the pinned completion method in memory, without native imports/I/O."""
import ast
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/jawl-sources/jawl-20260906-daily-v2"))

from jawl_voicecompanion.native_jawl_delivery import install_native_delivery_guard


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2/src/l3_agent/react/loop.py"


def snapshot_completion():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ReactLoop")
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_completion")
    module = ast.Module(body=[method], type_ignores=[])
    scope = {
        "agent_logger": SimpleNamespace(info=lambda _: None),
        "current_trace": lambda: {},
        "current_companion_turn_id": lambda: "turn-snapshot-1",
        "Events": SimpleNamespace(REACT_TICK_SAVED="tick"),
    }
    exec(compile(module, str(SOURCE), "exec"), scope)
    return scope["_handle_completion"]


class NativeDeliverySnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_completion_persists_tick_without_publishing_private_reply(self):
        class Client:
            def __init__(self):
                self.events = []

            async def emit_gateway_event(self, turn_id, event_type, payload):
                event = {"turn_id": turn_id, "type": event_type, "payload": payload}
                self.events.append(event)
                return event

        class Ticks:
            def __init__(self):
                self.saved = []

            async def save_tick(self, **kwargs):
                self.saved.append(kwargs)

        class Bus:
            def __init__(self, client):
                self.client, self.tasks, self.published = client, [], []

            async def publish(self, event, **kwargs):
                self.published.append(kwargs)
                async def deliver():
                    kind = kwargs.get("companion_gateway_type")
                    if kind:
                        await self.client.emit_gateway_event(
                            kwargs["companion_turn_id"], kind,
                            {"text": kwargs.get("companion_text", "")},
                        )
                self.tasks.append(asyncio.create_task(deliver()))

            async def flush(self, timeout=None):
                if self.tasks:
                    await asyncio.gather(*self.tasks)

        class Loop:
            _handle_completion = snapshot_completion()

            def __init__(self, client):
                self.client = client
                self.event_bus = Bus(client)
                self.sql_ticks = Ticks()
                self.last_cycle_outcome = {}
                self.agent_state = SimpleNamespace(current_step=1, max_react_steps=5)

            def _llm_metrics_snapshot(self):
                return {}

            async def run(self, event_name, payload, missed_events):
                await self._handle_completion("PRIVATE_INTERNAL_SENTINEL")

        install_native_delivery_guard(
            Loop,
            Client,
            event_bus_class=Bus,
            terminal_client_resolver=lambda loop: loop.client,
        )
        client = Client()
        loop = Loop(client)
        await loop.run("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-snapshot-1"}, [])
        await loop.event_bus.flush()
        self.assertEqual(len(loop.sql_ticks.saved), 1)
        self.assertEqual(loop.sql_ticks.saved[0]["thoughts"], "PRIVATE_INTERNAL_SENTINEL")
        self.assertEqual([e["type"] for e in client.events], ["turn.error"])
        self.assertNotIn("PRIVATE_INTERNAL_SENTINEL", repr(client.events))
        self.assertNotIn("PRIVATE_INTERNAL_SENTINEL", repr(loop.event_bus.published))


if __name__ == "__main__":
    unittest.main()
