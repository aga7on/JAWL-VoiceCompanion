import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.game_embodied import (  # noqa: E402
    GameEmbodiedError,
    GameEmbodiedLayer,
    GameInputBridge,
    GameMotorCommand,
    GameMotorController,
    GameObservation,
    ModScaffold,
    ModScaffoldFile,
    ModScaffoldWriter,
    SimulatedGameInputBridge,
    StrategyModPlanner,
    VoiceCombatCoordinator,
)


class GameMotorControllerTests(unittest.TestCase):
    def test_queue_is_bounded_and_emergency_stop_clears_it(self):
        controller = GameMotorController(tick_rate_hz=60.0, max_queue=1, bridge=lambda cmd: {"bridged": True})
        self.assertEqual(controller.enqueue(GameMotorCommand("tap", buttons=("left",))).get("status"), "queued")
        self.assertEqual(controller.enqueue(GameMotorCommand("tap")).get("reason"), "game_motor_queue_full")
        stopped = controller.emergency_stop()
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["cleared"], 1)
        self.assertEqual(controller.enqueue(GameMotorCommand("tap")).get("reason"), "game_motor_emergency_stop")

    def test_tick_rate_and_bridge_result_are_bounded(self):
        calls = []
        controller = GameMotorController(tick_rate_hz=10.0, bridge=lambda cmd: (calls.append(cmd.action) or {"bridged": True}))
        controller.enqueue(GameMotorCommand("move", x=10, y=20, duration_ms=25))
        self.assertEqual(controller.tick()["status"], "dispatched")
        self.assertEqual(calls, ["move"])
        state = controller.state()
        self.assertEqual(state["tick_rate_hz"], 10.0)
        self.assertEqual(state["queue_depth"], 0)

    def test_invalid_command_is_rejected(self):
        with self.assertRaises(GameEmbodiedError):
            GameMotorCommand("jump")
        with self.assertRaises(GameEmbodiedError):
            GameMotorCommand("move", x=20000)


class VoiceCombatCoordinatorTests(unittest.TestCase):
    def test_known_events_propose_bounded_intents(self):
        coordinator = VoiceCombatCoordinator(cooldown_seconds=0, dnd=False)
        result = coordinator.handle("enemy_spotted", now=1.0)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["emotion"], "alert")
        self.assertTrue(result["speak"])

    def test_dnd_and_cooldown_suppress_intents(self):
        coordinator = VoiceCombatCoordinator(cooldown_seconds=10.0, dnd=True)
        self.assertEqual(coordinator.handle("victory", now=1.0)["status"], "suppressed")
        coordinator.dnd = False
        self.assertEqual(coordinator.handle("victory", now=2.0)["status"], "proposed")
        self.assertEqual(coordinator.handle("victory", now=3.0)["status"], "coalesced")

    def test_unknown_event_is_ignored(self):
        coordinator = VoiceCombatCoordinator()
        self.assertEqual(coordinator.handle("idle")["status"], "ignored")


class StrategyModPlannerTests(unittest.TestCase):
    def test_plan_is_bounded_and_requires_hostos_review(self):
        planner = StrategyModPlanner()
        plan = planner.plan(game="Test Game", bridge="memory", goal="assist")
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["game"], "Test Game")
        self.assertTrue(plan["hostos_required"])
        self.assertFalse(plan["raw_game_memory_persisted"])

    def test_invalid_plan_inputs_are_rejected(self):
        planner = StrategyModPlanner()
        with self.assertRaises(GameEmbodiedError):
            planner.plan(game="", bridge="memory")
        with self.assertRaises(GameEmbodiedError):
            planner.plan(game="Game", bridge="telepathy")


class GameObservationTests(unittest.TestCase):
    def test_observation_is_bounded(self):
        observation = GameObservation(game="Game", scene="menu", health=0.5, enemies=2, objective="assist")
        self.assertEqual(observation.game, "Game")
        self.assertEqual(observation.enemies, 2)

    def test_invalid_observation_is_rejected(self):
        with self.assertRaises(GameEmbodiedError):
            GameObservation(game="", health=0.5)
        with self.assertRaises(GameEmbodiedError):
            GameObservation(game="Game", health=1.5)


class GameInputBridgeTests(unittest.TestCase):
    def test_simulated_bridge_records_command(self):
        bridge = SimulatedGameInputBridge()
        result = bridge.send(GameMotorCommand("tap", buttons=("left",)))
        self.assertTrue(result["accepted"])
        self.assertEqual(len(bridge.sent), 1)


class ModScaffoldTests(unittest.TestCase):
    def test_scaffold_writes_only_under_root(self):
        import tempfile
        from pathlib import Path

        writer = ModScaffoldWriter()
        scaffold = writer.scaffold(game="Game", bridge="hostos", goal="assist")
        with tempfile.TemporaryDirectory() as directory:
            written = scaffold.write_under(Path(directory))
            self.assertEqual(len(written), 3)
            self.assertTrue((Path(directory) / "README.md").is_file())
            self.assertTrue((Path(directory) / "bridge.py").is_file())

    def test_unsafe_scaffold_path_is_rejected(self):
        with self.assertRaises(GameEmbodiedError):
            ModScaffoldFile("../escape.txt", "x")
        with self.assertRaises(GameEmbodiedError):
            ModScaffold([])


class GameObservationLayerTests(unittest.TestCase):
    def test_observe_records_bounded_history_and_voice_intent(self):
        layer = GameEmbodiedLayer()
        result = layer.observe(GameObservation(game="Game", health=0.1, enemies=1), now=1.0)
        self.assertEqual(result["voice"]["status"], "proposed")
        self.assertEqual(result["voice"]["emotion"], "warning")
        self.assertEqual(layer.state()["observations"], 1)

    def test_scaffold_mod_delegates_to_strategy_and_writer(self):
        layer = GameEmbodiedLayer()
        scaffold = layer.scaffold_mod(game="Game", bridge="memory", goal="assist")
        self.assertEqual(scaffold.files[0].path, "README.md")


class GameEmbodiedLayerTests(unittest.TestCase):
    def test_handle_event_and_tick_are_bounded(self):
        layer = GameEmbodiedLayer()
        result = layer.handle_event("objective_complete", now=1.0)
        self.assertEqual(result["voice"]["status"], "proposed")
        self.assertEqual(layer.tick()["motor"]["status"], "idle")
        state = layer.state()
        self.assertIn("motor", state)
        self.assertIn("voice", state)

    def test_plan_mod_delegates_to_strategy(self):
        layer = GameEmbodiedLayer()
        plan = layer.plan_mod(game="Game", bridge="hostos", goal="mod")
        self.assertEqual(plan["bridge"], "hostos")


if __name__ == "__main__":
    unittest.main()
