"""Tests for GameControllerAdapter, ActionSpeechCoordinator, and GameEmbodimentAdapter."""

from __future__ import annotations

import pytest

from jawl_voicecompanion.game_controller import (
    ActionSpeechCoordinator,
    CommentaryCandidate,
    CommentaryUrgency,
    GamepadConfig,
    GamepadState,
    GamepadStick,
    GameControllerAdapter,
    GameEmbodimentAdapter,
    VirtualGamepadButton,
    apply_stick_deadzone,
    apply_trigger_deadzone,
)
from jawl_voicecompanion.game_embodied import (
    GameEmbodiedError,
    GameMotorController,
    GameObservation,
    SimulatedGameInputBridge,
)
from jawl_voicecompanion.moss_coordinator import (
    NaturalPauseInjectionItem,
    NaturalPauseInjectionQueue,
)


def test_button_normalization() -> None:
    assert VirtualGamepadButton.normalize("a") == VirtualGamepadButton.A
    assert VirtualGamepadButton.normalize("Cross") == VirtualGamepadButton.A
    assert VirtualGamepadButton.normalize("CIRCLE") == VirtualGamepadButton.B
    assert VirtualGamepadButton.normalize("square") == VirtualGamepadButton.X
    assert VirtualGamepadButton.normalize("TRIANGLE") == VirtualGamepadButton.Y
    assert VirtualGamepadButton.normalize("l1") == VirtualGamepadButton.LB
    assert VirtualGamepadButton.normalize("r1") == VirtualGamepadButton.RB
    assert VirtualGamepadButton.normalize("l2") == VirtualGamepadButton.LT
    assert VirtualGamepadButton.normalize("r2") == VirtualGamepadButton.RT
    assert VirtualGamepadButton.normalize("l3") == VirtualGamepadButton.LEFT_THUMB
    assert VirtualGamepadButton.normalize("r3") == VirtualGamepadButton.RIGHT_THUMB
    assert VirtualGamepadButton.normalize("select") == VirtualGamepadButton.BACK
    assert VirtualGamepadButton.normalize("menu") == VirtualGamepadButton.START
    assert VirtualGamepadButton.normalize("dpad_up") == VirtualGamepadButton.DPAD_UP
    assert VirtualGamepadButton.normalize("up") == VirtualGamepadButton.DPAD_UP

    with pytest.raises(GameEmbodiedError, match="Unsupported virtual gamepad button"):
        VirtualGamepadButton.normalize("keyboard_f12")


def test_stick_normalization() -> None:
    assert GamepadStick.normalize("left") == GamepadStick.LEFT
    assert GamepadStick.normalize("ls") == GamepadStick.LEFT
    assert GamepadStick.normalize("move") == GamepadStick.LEFT
    assert GamepadStick.normalize("right") == GamepadStick.RIGHT
    assert GamepadStick.normalize("rs") == GamepadStick.RIGHT
    assert GamepadStick.normalize("look") == GamepadStick.RIGHT

    with pytest.raises(GameEmbodiedError, match="Unsupported gamepad stick"):
        GamepadStick.normalize("throttle")


def test_stick_deadzone() -> None:
    # Inner deadzone: tiny vector below threshold (0.10)
    assert apply_stick_deadzone(0.04, 0.04, inner=0.10) == (0.0, 0.0)

    # Outer deadzone: magnitude >= 0.95 clamped to 1.0 length
    x, y = apply_stick_deadzone(0.9, 0.9, outer=0.95)
    assert pytest.approx((x * x + y * y) ** 0.5, rel=1e-3) == 1.0

    # Intermediate value rescaled
    x_mid, y_mid = apply_stick_deadzone(0.5, 0.0, inner=0.10, outer=0.95)
    assert 0.0 < x_mid < 0.6
    assert y_mid == 0.0


def test_trigger_deadzone() -> None:
    # Below deadzone
    assert apply_trigger_deadzone(0.03, deadzone=0.05) == 0.0
    # Fully engaged
    assert apply_trigger_deadzone(1.0, deadzone=0.05) == 1.0
    # Scaled properly
    scaled = apply_trigger_deadzone(0.525, deadzone=0.05)
    assert pytest.approx(scaled, rel=1e-2) == 0.5


def test_game_controller_adapter_input_tracking() -> None:
    bridge = SimulatedGameInputBridge()
    motor = GameMotorController(bridge=bridge)
    adapter = GameControllerAdapter(motor_controller=motor)

    # Press button
    res_press = adapter.press_button("A")
    assert res_press["status"] == "queued"
    state = adapter.get_gamepad_state()
    assert "A" in state["buttons"]

    # Release button
    adapter.release_button("A")
    state = adapter.get_gamepad_state()
    assert "A" not in state["buttons"]

    # Tap button
    res_tap = adapter.tap_button("X")
    assert res_tap["status"] == "queued"

    # Move stick
    adapter.move_stick("left", 0.6, -0.6)
    state = adapter.get_gamepad_state()
    assert state["left_stick"][0] > 0.0
    assert state["left_stick"][1] < 0.0

    # Trigger
    adapter.set_trigger("RT", 0.8)
    state = adapter.get_gamepad_state()
    assert state["right_trigger"] > 0.7
    assert "RT" in state["buttons"]

    # Tick motor
    tick_res = adapter.tick()
    assert tick_res["motor"]["status"] == "dispatched"

    # Emergency stop
    stop_res = adapter.emergency_stop()
    assert stop_res["status"] == "stopped"
    state_after_stop = adapter.get_gamepad_state()
    assert state_after_stop["buttons"] == []
    assert state_after_stop["left_stick"] == [0.0, 0.0]
    assert state_after_stop["right_stick"] == [0.0, 0.0]
    assert state_after_stop["left_trigger"] == 0.0
    assert state_after_stop["right_trigger"] == 0.0


def test_game_controller_execute_sequence() -> None:
    bridge = SimulatedGameInputBridge()
    motor = GameMotorController(bridge=bridge)
    adapter = GameControllerAdapter(motor_controller=motor)

    sequence = [
        {"type": "tap", "button": "A"},
        {"type": "press", "button": "LB"},
        {"type": "stick", "stick": "left", "x": 0.8, "y": 0.0},
        {"type": "trigger", "trigger": "RT", "value": 1.0},
        {"type": "release", "button": "LB"},
    ]
    results = adapter.execute_sequence(sequence)
    assert len(results) == 5
    assert all(r["status"] == "queued" for r in results)


def test_action_speech_coordinator_cooldowns_and_pause_queue() -> None:
    current_time = 100.0
    queue = NaturalPauseInjectionQueue()
    coordinator = ActionSpeechCoordinator(
        injection_queue=queue,
        tactical_cooldown_sec=2.0,
        ambient_cooldown_sec=5.0,
        now=lambda: current_time,
    )

    # First commentary should succeed
    c1 = coordinator.propose_action_commentary("jump", "Отличный прыжок!", urgency=CommentaryUrgency.AMBIENT)
    assert c1 is not None
    assert c1.text == "Отличный прыжок!"
    assert queue.qsize() == 1

    # Immediate duplicate action commentary should be suppressed
    c2 = coordinator.propose_action_commentary("jump", "Еще прыжок!", urgency=CommentaryUrgency.AMBIENT)
    assert c2 is None
    assert queue.qsize() == 1

    # After cooldown expires
    current_time += 6.0
    c3 = coordinator.propose_action_commentary("jump", "И снова в воздухе!", urgency=CommentaryUrgency.AMBIENT)
    assert c3 is not None
    assert queue.qsize() == 2

    # Check state
    state = coordinator.state()
    assert state["total_generated"] == 2
    assert state["total_suppressed"] == 1
    assert state["history_depth"] == 2


def test_action_speech_coordinator_tactical_alerts_from_observation() -> None:
    queue = NaturalPauseInjectionQueue()
    coordinator = ActionSpeechCoordinator(injection_queue=queue)

    # Low health trigger
    obs_danger = GameObservation(
        game="SpaceShooter",
        scene="BossArena",
        health=0.15,
        enemies=3,
        objective="Survive",
        timestamp=100.0,
    )
    alert = coordinator.observe_game(obs_danger)
    assert alert is not None
    assert alert.urgency == CommentaryUrgency.TACTICAL
    assert "здоровье на исходе" in alert.text
    assert queue.qsize() == 1

    item = queue.pop()
    assert item is not None
    assert item.priority == 8
    assert item.structured_data["health"] == 0.15


def test_game_embodiment_adapter_text_parsing_and_execution() -> None:
    bridge = SimulatedGameInputBridge()
    motor = GameMotorController(bridge=bridge)
    queue = NaturalPauseInjectionQueue()
    speech = ActionSpeechCoordinator(injection_queue=queue)
    controller = GameControllerAdapter(motor_controller=motor, speech_coordinator=speech)
    adapter = GameEmbodimentAdapter(controller=controller)

    prompt = (
        "Tactical situation:\n"
        "ACTION: TAP A\n"
        "ACTION: MOVE 0.7 0.7\n"
        "COMMENTARY: Идем на штурм!"
    )
    output = adapter.generate(prompt=prompt)
    assert "Dispatched" in output
    assert "tap A" in output
    assert "left stick" in output
    assert "Commentary proposed" in output

    assert queue.qsize() == 1
    queued_item = queue.pop()
    assert queued_item is not None
    assert queued_item.content == "Идем на штурм!"

    # Dispatch structured action plan
    plan = {
        "button": "X",
        "action": "tap",
        "commentary": "Удар мечом!",
        "tactical": True,
    }
    plan_res = adapter.dispatch_action_plan(plan)
    assert plan_res["status"] == "executed"
    assert len(plan_res["actions"]) == 1
    assert plan_res["actions"][0]["status"] == "queued"
    assert plan_res["commentary"]["text"] == "Удар мечом!"

    # Health check
    hc = adapter.health_check()
    assert hc["status"] == "healthy"
    assert hc["adapter"] == "game-embodiment-engine"
