import asyncio
import importlib
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class JawlGoalVoiceContinuityTests(unittest.TestCase):
    def test_tts_stop_and_exact_native_turn_cancel_preserve_resumable_goal(self):
        repo = Path(__file__).parents[1]
        snapshot = repo / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
        old_env = {
            key: os.environ.get(key)
            for key in ("JAWL_INSTANCE_ID", "JAWL_LOG_DIR", "PYTHONDONTWRITEBYTECODE")
        }
        old_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        inserted_paths = []
        for path in reversed([repo / "src", snapshot]):
            entry = str(path)
            sys.path.insert(0, entry)
            inserted_paths.append(entry)
        preexisting_handlers = {
            id(handler)
            for logger in [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
            if isinstance(logger, logging.Logger)
            for handler in logger.handlers
        }
        before_modules = set(sys.modules)

        class Writer:
            def __init__(self):
                self.lines = []

            def write(self, value):
                self.lines.append(value)

            async def drain(self):
                return None

        class TTSProvider:
            def __init__(self):
                self.cancelled = 0

            def cancel(self):
                self.cancelled += 1

        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            os.environ.update(
                {
                    "JAWL_INSTANCE_ID": "goal-voice-continuity-test",
                    "JAWL_LOG_DIR": str(temp_root / "logs"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            try:
                AgentState = importlib.import_module(
                    "src.l0_state.agent.state"
                ).AgentState
                goal_module = importlib.import_module("src.l3_agent.goals.manager")
                GoalManager = goal_module.GoalManager
                TaskLedgerPatch = importlib.import_module(
                    "src.l3_agent.goals.ledger"
                ).TaskLedgerPatch
                Heartbeat = importlib.import_module(
                    "src.l3_agent.heartbeat"
                ).Heartbeat
                OperatorControl = importlib.import_module(
                    "src.system.operator_control"
                ).OperatorControl
                chat_module = importlib.import_module("src.web.chat")
                ChatBridge = chat_module.ChatBridge
                TTSService = importlib.import_module(
                    "jawl_voicecompanion.tts"
                ).TTSService

                async def exercise_native_cancellation():
                    store = temp_root / "data" / "goals.json"
                    manager = GoalManager(store, AgentState(), recover_on_start=False)
                    goal = await manager.create("continue the voice-linked native task")
                    await manager.record_ledger_patch(
                        TaskLedgerPatch(
                            phase="inspect",
                            pending_steps=["inspect the existing result"],
                            next_action="read the result and continue",
                        )
                    )

                    # The Companion Stop route is TTS-only. Exercise the real
                    # service cancel method and ensure its provider hook runs.
                    provider = TTSProvider()
                    TTSService(provider).cancel()
                    self.assertEqual(provider.cancelled, 1)
                    self.assertEqual(manager.active_goal.goal_id, goal.goal_id)

                    # Use the real Companion API method to produce its wire
                    # cancel envelope, with only the transport writer isolated.
                    bridge = ChatBridge()
                    writer = Writer()
                    bridge._state = "online"
                    bridge._writer = writer
                    with patch.object(chat_module, "terminal_enabled", return_value=True):
                        sent = await bridge.cancel("turn-older", "superseded")
                    self.assertTrue(sent["ok"])
                    stale_request = json.loads(writer.lines[-1].decode("utf-8"))

                    react_loop = SimpleNamespace(active_companion_turn_id="turn-older")
                    acceleration = SimpleNamespace(
                        queue_max_events=8,
                        coalesce_window_sec=0.0,
                        coalesce_event_names=[],
                        coalesce_payload_samples=1,
                        critical_multiplier=1.0,
                        high_multiplier=1.0,
                        medium_multiplier=1.0,
                        low_multiplier=1.0,
                        background_multiplier=1.0,
                    )
                    heartbeat = Heartbeat(
                        react_loop=react_loop,
                        heartbeat_interval=30,
                        continuous_cycle=False,
                        accel_config=acceleration,
                        timezone=0,
                        goal_manager=manager,
                    )
                    old_task = asyncio.create_task(asyncio.Event().wait())
                    heartbeat._active_react_task = old_task
                    heartbeat._wake_payload = {"_companion_turn_id": "turn-older"}
                    control = OperatorControl(SimpleNamespace(heartbeat=heartbeat))

                    with patch.object(chat_module, "terminal_enabled", return_value=True):
                        matching_sent = await bridge.cancel("turn-older", "user stopped the active turn")
                    self.assertTrue(matching_sent["ok"])
                    matching_request = json.loads(
                        writer.lines[-1].decode("utf-8")
                    )
                    matching_result = await control.handle(
                        "react.cancel", matching_request
                    )
                    self.assertTrue(matching_result["cancelled"])
                    await asyncio.gather(old_task, return_exceptions=True)
                    self.assertTrue(old_task.cancelled())

                    # A matching turn cancel ends its ReAct task only. The
                    # live manager's durable ledger remains available at once.
                    cancelled_cycle_goal = manager.active_goal
                    self.assertIsNotNone(cancelled_cycle_goal)
                    self.assertEqual(cancelled_cycle_goal.goal_id, goal.goal_id)
                    self.assertEqual(cancelled_cycle_goal.status, "active")
                    self.assertTrue(cancelled_cycle_goal.pending_work)
                    self.assertEqual(
                        cancelled_cycle_goal.task_ledger.current_phase, "inspect"
                    )
                    self.assertEqual(
                        cancelled_cycle_goal.task_ledger.next_action,
                        "read the result and continue",
                    )

                    # Once the newer user/goal turn is active, replaying the
                    # completed older turn's cancel must leave it untouched.
                    react_loop.active_companion_turn_id = "turn-newer"
                    new_task = asyncio.create_task(asyncio.Event().wait())
                    heartbeat._active_react_task = new_task
                    heartbeat._wake_payload = {"_companion_turn_id": "turn-newer"}
                    stale_result = await control.handle("react.cancel", stale_request)
                    self.assertFalse(stale_result["cancelled"])
                    self.assertFalse(new_task.cancelling())
                    self.assertFalse(new_task.done())

                    with patch.object(chat_module, "terminal_enabled", return_value=True):
                        matching_new_sent = await bridge.cancel(
                            "turn-newer", "user stopped the active turn"
                        )
                    self.assertTrue(matching_new_sent["ok"])
                    matching_new_request = json.loads(
                        writer.lines[-1].decode("utf-8")
                    )
                    matching_new_result = await control.handle(
                        "react.cancel", matching_new_request
                    )
                    self.assertTrue(matching_new_result["cancelled"])
                    await asyncio.gather(new_task, return_exceptions=True)
                    self.assertTrue(new_task.cancelled())

                    # Cancellation stops that ReAct turn, not the durable
                    # goal. A fresh native manager reloads its ledger and can
                    # schedule the still-pending work on the next heartbeat.
                    resumed = GoalManager(store, AgentState(), recover_on_start=True)
                    current = resumed.active_goal
                    self.assertIsNotNone(current)
                    self.assertEqual(current.goal_id, goal.goal_id)
                    self.assertEqual(current.status, "active")
                    self.assertTrue(current.pending_work)
                    self.assertEqual(current.task_ledger.current_phase, "inspect")
                    self.assertEqual(
                        current.task_ledger.next_action,
                        "read the result and continue",
                    )
                    self.assertTrue(resumed.should_run_heartbeat())

                asyncio.run(exercise_native_cancellation())
            finally:
                for path in inserted_paths:
                    for index, current in enumerate(sys.path):
                        if current is path:
                            sys.path.pop(index)
                            break
                closed_handlers = set()
                loggers = [
                    logging.getLogger(),
                    *logging.Logger.manager.loggerDict.values(),
                ]
                for logger in loggers:
                    if not isinstance(logger, logging.Logger):
                        continue
                    for handler in list(logger.handlers):
                        if id(handler) in preexisting_handlers:
                            continue
                        logger.removeHandler(handler)
                        if id(handler) not in closed_handlers:
                            handler.close()
                            closed_handlers.add(id(handler))
                for name in list(sys.modules):
                    if name not in before_modules and (
                        name == "src" or name.startswith("src.")
                    ):
                        sys.modules.pop(name, None)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                sys.dont_write_bytecode = old_dont_write_bytecode


if __name__ == "__main__":
    unittest.main()
