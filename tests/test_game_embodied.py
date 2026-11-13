import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.game_embodied import (  # noqa: E402
    CompanionRole,
    GameEmbodiedError,
    GameEmbodiedLayer,
    GameInputBridge,
    GameMotorCommand,
    GameMotorController,
    GameObservation,
    ModScaffold,
    ModScaffoldFile,
    ModScaffoldWriter,
    Player2CompanionController,
    Player2Decision,
    SimulatedGameInputBridge,
    StrategyModPlanner,
    TacticalTelemetry,
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


class Player2CompanionControllerTests(unittest.TestCase):
    def test_companion_role_normalize_and_validation(self):
        self.assertEqual(CompanionRole.normalize(CompanionRole.SUPPORT), CompanionRole.SUPPORT)
        self.assertEqual(CompanionRole.normalize("support"), CompanionRole.SUPPORT)
        self.assertEqual(CompanionRole.normalize("AGGRESSIVE"), CompanionRole.AGGRESSIVE)
        self.assertEqual(CompanionRole.normalize("defensive"), CompanionRole.DEFENSIVE)
        with self.assertRaises(GameEmbodiedError):
            CompanionRole.normalize("unsupported_role")

    def test_tactical_telemetry_normalization(self):
        telemetry = TacticalTelemetry(
            health=1.5,
            player_health=-0.5,
            enemies=-3,
            target_distance=-10.0,
            target_x=2.5,
            target_y=-3.0,
            ammo_ratio=2.0,
        )
        self.assertEqual(telemetry.health, 1.0)
        self.assertEqual(telemetry.player_health, 0.0)
        self.assertEqual(telemetry.enemies, 0)
        self.assertEqual(telemetry.target_distance, 0.0)
        self.assertEqual(telemetry.target_x, 1.0)
        self.assertEqual(telemetry.target_y, -1.0)
        self.assertEqual(telemetry.ammo_ratio, 1.0)

        d_telemetry = TacticalTelemetry.from_input({
            "game": "EldenRing",
            "health": 0.8,
            "player_health": 0.9,
            "enemies": 2,
            "target_distance": 5.0,
        })
        self.assertEqual(d_telemetry.game, "EldenRing")
        self.assertEqual(d_telemetry.enemies, 2)

        obs = GameObservation(game="Shooter", health=0.5, enemies=1)
        obs_telemetry = TacticalTelemetry.from_input(obs)
        self.assertEqual(obs_telemetry.game, "Shooter")
        self.assertEqual(obs_telemetry.health, 0.5)

        data = d_telemetry.to_dict()
        self.assertEqual(data["game"], "EldenRing")
        self.assertEqual(data["enemies"], 2)

    def test_player2_support_tactics(self):
        controller = Player2CompanionController(role=CompanionRole.SUPPORT)
        
        decision = controller.tactical_tick({
            "health": 0.8,
            "player_health": 0.2,
            "enemies": 1,
        })
        self.assertEqual(decision.action_type, "heal_player")
        self.assertIn("Y", decision.tapped_buttons)
        self.assertEqual(decision.emotional_state, "protective")
        self.assertIn("patching you up", decision.speech_text)

        decision = controller.tactical_tick({
            "health": 0.15,
            "player_health": 0.8,
            "enemies": 2,
            "target_x": 0.5,
        })
        self.assertEqual(decision.action_type, "retreat")
        self.assertIn("B", decision.tapped_buttons)
        self.assertLess(decision.stick_move[1], 0)

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.9,
            "ammo_ratio": 0.1,
            "enemies": 1,
        })
        self.assertEqual(decision.action_type, "reload")
        self.assertIn("X", decision.tapped_buttons)

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.9,
            "ammo_ratio": 0.8,
            "enemies": 2,
            "target_distance": 8.0,
        })
        self.assertEqual(decision.action_type, "covering_fire")
        self.assertIn("RB", decision.tapped_buttons)
        self.assertEqual(decision.emotional_state, "focused")

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.9,
            "enemies": 0,
        })
        self.assertEqual(decision.action_type, "victory")
        self.assertEqual(decision.emotional_state, "triumphant")
        self.assertIn("secure", decision.speech_text.lower())

    def test_player2_aggressive_tactics(self):
        controller = Player2CompanionController(role=CompanionRole.AGGRESSIVE)

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.9,
            "enemies": 2,
            "target_distance": 5.0,
            "target_x": 0.2,
            "target_y": 0.8,
        })
        self.assertEqual(decision.action_type, "full_assault")
        self.assertEqual(decision.triggers.get("RT"), 1.0)
        self.assertGreater(decision.stick_move[1], 0.5)
        self.assertEqual(decision.emotional_state, "aggressive")

        decision = controller.tactical_tick({
            "health": 0.7,
            "player_health": 0.9,
            "enemies": 2,
            "target_distance": 4.0,
            "is_under_fire": True,
        })
        self.assertEqual(decision.action_type, "full_assault")
        self.assertIn("A", decision.tapped_buttons)

        decision = controller.tactical_tick({
            "health": 0.7,
            "player_health": 0.9,
            "enemies": 1,
            "target_distance": 2.0,
        })
        self.assertEqual(decision.action_type, "melee_strike")
        self.assertIn("B", decision.tapped_buttons)

    def test_player2_defensive_tactics(self):
        controller = Player2CompanionController(role=CompanionRole.DEFENSIVE)

        decision = controller.tactical_tick({
            "health": 0.6,
            "player_health": 0.8,
            "is_under_fire": True,
            "enemies": 2,
        })
        self.assertEqual(decision.action_type, "shield_and_retreat")
        self.assertEqual(decision.triggers.get("LT"), 1.0)
        self.assertIn("LB", decision.pressed_buttons)
        self.assertIn("B", decision.tapped_buttons)
        self.assertLess(decision.stick_move[1], 0)

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.2,
            "enemies": 2,
        })
        self.assertEqual(decision.action_type, "bodyguard")
        self.assertEqual(decision.triggers.get("LT"), 1.0)
        self.assertIn("LB", decision.pressed_buttons)
        self.assertEqual(decision.emotional_state, "protective")

        decision = controller.tactical_tick({
            "health": 0.9,
            "player_health": 0.8,
            "is_under_fire": False,
            "enemies": 1,
        })
        self.assertEqual(decision.action_type, "hold_perimeter")
        self.assertIn("RB", decision.tapped_buttons)

    def test_player2_speech_coordination(self):
        from jawl_voicecompanion.game_controller import ActionSpeechCoordinator

        coordinator = ActionSpeechCoordinator()
        controller = Player2CompanionController(
            role=CompanionRole.SUPPORT,
            speech_coordinator=coordinator,
        )

        decision = controller.tactical_tick({
            "health": 0.8,
            "player_health": 0.2,
            "enemies": 1,
        })
        self.assertIsNotNone(decision.speech_text)
        state = coordinator.state()
        self.assertEqual(state["total_generated"], 1)

    def test_player2_pause_resume_emergency_stop_and_reset(self):
        controller = Player2CompanionController(role=CompanionRole.SUPPORT)
        controller.tactical_tick({"health": 0.9, "enemies": 1})

        controller.pause()
        self.assertTrue(controller.is_paused())
        paused_decision = controller.tactical_tick({"health": 0.9, "enemies": 1})
        self.assertEqual(paused_decision.action_type, "paused")
        self.assertEqual(paused_decision.stick_move, (0.0, 0.0))

        controller.resume()
        self.assertFalse(controller.is_paused())
        resumed_decision = controller.tactical_tick({"health": 0.9, "enemies": 1})
        self.assertNotEqual(resumed_decision.action_type, "paused")

        stopped = controller.emergency_stop()
        self.assertEqual(stopped["status"], "stopped")
        stopped_decision = controller.tactical_tick({"health": 0.9, "enemies": 1})
        self.assertEqual(stopped_decision.action_type, "stopped")

        controller.reset()
        self.assertFalse(controller.is_paused())
        self.assertEqual(controller.state()["decision_count"], 0)

    def test_game_embodied_layer_player2_integration(self):
        layer = GameEmbodiedLayer()
        self.assertIsNone(layer.player2)

        layer.enable_player2(role="aggressive")
        self.assertIsNotNone(layer.player2)
        self.assertEqual(layer.player2.role, CompanionRole.AGGRESSIVE)

        obs_res = layer.observe(GameObservation(game="TestGame", health=0.8, enemies=2))
        self.assertIn("player2", obs_res)
        self.assertEqual(obs_res["player2"]["role"], "aggressive")

        tick_res = layer.tick()
        self.assertIn("player2", tick_res)

        state = layer.state()
        self.assertIn("player2", state)
        self.assertEqual(state["player2"]["role"], "aggressive")
if __name__ == "__main__":
    unittest.main()
