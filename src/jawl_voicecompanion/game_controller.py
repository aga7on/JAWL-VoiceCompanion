"""Game Controller Adapter and Action-to-Speech Coordination.

Provides:
1. Virtual gamepad mapping (Xbox / PlayStation DirectInput compatible layout,
   deadzone filtering, stick/trigger scaling to motor bounds).
2. Action-to-speech coordination (tactical alerts, ambient observations,
   repetition suppression, and NaturalPauseInjectionQueue integration).
3. GameControllerAdapter: High-level controller bridge over GameMotorController.
4. GameEmbodimentAdapter: ModelAdapter implementation for ModelSlot.GAME_EMBODIMENT.
"""

from __future__ import annotations

import enum
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from jawl_voicecompanion.game_embodied import (
    GameEmbodiedError,
    GameMotorCommand,
    GameMotorController,
    GameObservation,
)
from jawl_voicecompanion.model_slots import (
    ModelAdapter,
    ModelCapabilities,
    ModelCancelled,
)
from jawl_voicecompanion.moss_coordinator import (
    NaturalPauseInjectionItem,
    NaturalPauseInjectionQueue,
)


class VirtualGamepadButton(str, enum.Enum):
    """Standardized virtual gamepad button identifiers."""

    A = "A"
    B = "B"
    X = "X"
    Y = "Y"
    LB = "LB"
    RB = "RB"
    LT = "LT"
    RT = "RT"
    BACK = "BACK"
    START = "START"
    GUIDE = "GUIDE"
    LEFT_THUMB = "LEFT_THUMB"
    RIGHT_THUMB = "RIGHT_THUMB"
    DPAD_UP = "DPAD_UP"
    DPAD_DOWN = "DPAD_DOWN"
    DPAD_LEFT = "DPAD_LEFT"
    DPAD_RIGHT = "DPAD_RIGHT"

    @classmethod
    def normalize(cls, val: str | VirtualGamepadButton) -> VirtualGamepadButton:
        """Normalize arbitrary case, whitespace, and common controller aliases."""
        if isinstance(val, cls):
            return val
        clean = str(val or "").strip().upper().replace(" ", "_").replace("-", "_")
        alias_map = {
            "CROSS": cls.A,
            "CIRCLE": cls.B,
            "SQUARE": cls.X,
            "TRIANGLE": cls.Y,
            "L1": cls.LB,
            "R1": cls.RB,
            "L2": cls.LT,
            "R2": cls.RT,
            "L3": cls.LEFT_THUMB,
            "R3": cls.RIGHT_THUMB,
            "SELECT": cls.BACK,
            "MENU": cls.START,
            "OPTIONS": cls.START,
            "SHARE": cls.BACK,
            "HOME": cls.GUIDE,
            "UP": cls.DPAD_UP,
            "DOWN": cls.DPAD_DOWN,
            "LEFT": cls.DPAD_LEFT,
            "RIGHT": cls.DPAD_RIGHT,
            "DPADUP": cls.DPAD_UP,
            "DPADDOWN": cls.DPAD_DOWN,
            "DPADLEFT": cls.DPAD_LEFT,
            "DPADRIGHT": cls.DPAD_RIGHT,
            "THUMB_L": cls.LEFT_THUMB,
            "THUMB_R": cls.RIGHT_THUMB,
        }
        if clean in alias_map:
            return alias_map[clean]
        try:
            return cls(clean)
        except ValueError:
            raise GameEmbodiedError(f"Unsupported virtual gamepad button: {val!r}")


class GamepadStick(str, enum.Enum):
    """Stick identifier for dual-stick gamepads."""

    LEFT = "left"
    RIGHT = "right"

    @classmethod
    def normalize(cls, val: str | GamepadStick) -> GamepadStick:
        if isinstance(val, cls):
            return val
        clean = str(val or "").strip().lower()
        if clean in {"left", "l", "ls", "left_stick", "move"}:
            return cls.LEFT
        if clean in {"right", "r", "rs", "right_stick", "look", "aim"}:
            return cls.RIGHT
        raise GameEmbodiedError(f"Unsupported gamepad stick: {val!r}")


def apply_stick_deadzone(
    x: float,
    y: float,
    *,
    inner: float = 0.10,
    outer: float = 0.95,
) -> tuple[float, float]:
    """Apply radial deadzone and clamping to 2D stick coordinates.

    Coordinates must be in [-1.0, 1.0]. Returns smoothed (x, y) in [-1.0, 1.0].
    """
    x = max(-1.0, min(1.0, float(x)))
    y = max(-1.0, min(1.0, float(y)))
    inner = max(0.0, min(0.5, float(inner)))
    outer = max(inner + 0.05, min(1.0, float(outer)))

    magnitude = math.hypot(x, y)
    if magnitude < inner:
        return 0.0, 0.0

    if magnitude >= outer:
        scale = 1.0 / magnitude
        return round(x * scale, 4), round(y * scale, 4)

    # Linearly rescale the active range [inner, outer] -> [0.0, 1.0]
    normalized_mag = (magnitude - inner) / (outer - inner)
    scale = normalized_mag / magnitude
    return round(x * scale, 4), round(y * scale, 4)


def apply_trigger_deadzone(val: float, *, deadzone: float = 0.05) -> float:
    """Apply deadzone and clamping to analog trigger value [0.0, 1.0]."""
    val = max(0.0, min(1.0, float(val)))
    deadzone = max(0.0, min(0.5, float(deadzone)))
    if val < deadzone:
        return 0.0
    scaled = (val - deadzone) / (1.0 - deadzone)
    return round(min(1.0, scaled), 4)


@dataclass
class GamepadConfig:
    """Configuration for deadzones, scaling and timing."""

    inner_deadzone: float = 0.10
    outer_deadzone: float = 0.95
    trigger_deadzone: float = 0.05
    axis_max_int: int = 10000
    default_duration_ms: int = 50


@dataclass
class GamepadState:
    """Current state snapshot of virtual controller inputs."""

    buttons: set[str] = field(default_factory=set)
    left_stick: tuple[float, float] = (0.0, 0.0)
    right_stick: tuple[float, float] = (0.0, 0.0)
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "buttons": sorted(list(self.buttons)),
            "left_stick": list(self.left_stick),
            "right_stick": list(self.right_stick),
            "left_trigger": self.left_trigger,
            "right_trigger": self.right_trigger,
            "updated_at": round(self.updated_at, 4),
        }


class CommentaryUrgency(str, enum.Enum):
    """Urgency level of game-to-speech commentary."""

    TACTICAL = "tactical"
    REACTION = "reaction"
    AMBIENT = "ambient"

SpeechUrgency = CommentaryUrgency

@dataclass
class CommentaryCandidate:
    """A generated speech candidate derived from gameplay events or actions."""

    commentary_id: str = field(default_factory=lambda: f"com_{uuid.uuid4().hex[:8]}")
    text: str = ""
    urgency: CommentaryUrgency = CommentaryUrgency.AMBIENT
    priority: int = 5
    category: str = "gameplay_commentary"
    action_type: str = ""
    created_at: float = field(default_factory=time.time)
    ttl_sec: float = 15.0
    structured_data: dict[str, Any] = field(default_factory=dict)

    def to_injection_item(self) -> NaturalPauseInjectionItem:
        """Convert to MOSS NaturalPauseInjectionItem for pause queueing."""
        return NaturalPauseInjectionItem(
            item_id=self.commentary_id,
            task_id=f"game_{self.action_type or 'comment'}",
            content=self.text,
            structured_data={
                "urgency": self.urgency.value,
                "action_type": self.action_type,
                **self.structured_data,
            },
            priority=self.priority,
            category=self.category,
            ready_at=self.created_at,
            ttl_sec=self.ttl_sec,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "commentary_id": self.commentary_id,
            "text": self.text,
            "urgency": self.urgency.value,
            "priority": self.priority,
            "category": self.category,
            "action_type": self.action_type,
            "created_at": round(self.created_at, 3),
            "ttl_sec": self.ttl_sec,
            "structured_data": self.structured_data,
        }


class ActionSpeechCoordinator:
    """Maps gameplay actions and tactical events to bounded voice commentary.

    Enforces:
    - Cooldowns between comments to prevent voice spamming.
    - Repetitive action suppression (e.g. continuous moving/looking won't trigger commentary).
    - Tactical priority elevation for danger, low health, or boss spikes.
    - Seamless queueing into NaturalPauseInjectionQueue for silence injection.
    """

    _TACTICAL_TEMPLATES = {
        "low_health": "Осторожно, здоровье на исходе!",
        "taking_damage": "Принимаем урон, держи дистанцию!",
        "enemy_spotted": "Впереди контакт, готовься!",
        "heavy_swarm": "Нас окружает толпа противников!",
        "boss_encounter": "Внимание, босс в поле зрения!",
        "victory": "Отличная работа, цель зачищена!",
        "defeat": "Не страшно, перегруппируемся и повторим.",
        "objective_complete": "Задача выполнена, двигаемся дальше.",
    }

    def __init__(
        self,
        *,
        injection_queue: NaturalPauseInjectionQueue | None = None,
        tactical_cooldown_sec: float = 3.0,
        ambient_cooldown_sec: float = 8.0,
        repetitive_action_cooldown_sec: float = 5.0,
        dnd: bool = False,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.injection_queue = injection_queue
        self.tactical_cooldown_sec = max(0.5, float(tactical_cooldown_sec))
        self.ambient_cooldown_sec = max(1.0, float(ambient_cooldown_sec))
        self.repetitive_action_cooldown_sec = max(1.0, float(repetitive_action_cooldown_sec))
        self.dnd = bool(dnd)
        self._now = now

        self._lock = threading.Lock()
        self._last_comment_at: dict[str, float] = {}
        self._last_action_at: dict[str, float] = {}
        self._history: list[CommentaryCandidate] = []
        self._total_generated = 0
        self._total_suppressed = 0

    def propose_action_commentary(
        self,
        action: str,
        text: str,
        *,
        urgency: CommentaryUrgency = CommentaryUrgency.AMBIENT,
        priority: int = 5,
        structured_data: dict[str, Any] | None = None,
    ) -> CommentaryCandidate | None:
        """Propose speech commentary based on player/bot action with repetition suppression."""
        if self.dnd or not text.strip():
            self._total_suppressed += 1
            return None

        now = self._now()
        with self._lock:
            # Check repetition cooldown for same action
            last_act = self._last_action_at.get(action, 0.0)
            cooldown = (
                self.tactical_cooldown_sec
                if urgency == CommentaryUrgency.TACTICAL
                else self.ambient_cooldown_sec
            )
            if (now - last_act) < cooldown:
                self._total_suppressed += 1
                return None

            self._last_action_at[action] = now
            candidate = CommentaryCandidate(
                text=text.strip(),
                urgency=urgency,
                priority=priority,
                action_type=action,
                created_at=time.time(),
                structured_data=structured_data or {},
            )
            self._history.append(candidate)
            self._history = self._history[-64:]
            self._total_generated += 1

            if self.injection_queue is not None:
                self.injection_queue.push(candidate.to_injection_item())

            return candidate

    def propose_tactical_alert(
        self,
        event: str,
        *,
        custom_text: str = "",
        observation: GameObservation | None = None,
    ) -> CommentaryCandidate | None:
        """Propose an urgent tactical alert for combat and critical events."""
        if self.dnd:
            self._total_suppressed += 1
            return None

        text = custom_text or self._TACTICAL_TEMPLATES.get(event)
        if not text:
            return None

        now = self._now()
        with self._lock:
            last_event_time = self._last_comment_at.get(event, 0.0)
            if (now - last_event_time) < self.tactical_cooldown_sec:
                self._total_suppressed += 1
                return None

            self._last_comment_at[event] = now
            structured: dict[str, Any] = {"event": event}
            if observation is not None:
                structured.update({
                    "health": observation.health,
                    "enemies": observation.enemies,
                    "game": observation.game,
                })

            candidate = CommentaryCandidate(
                text=text,
                urgency=CommentaryUrgency.TACTICAL,
                priority=8,
                action_type=f"alert_{event}",
                created_at=time.time(),
                structured_data=structured,
            )
            self._history.append(candidate)
            self._history = self._history[-64:]
            self._total_generated += 1

            if self.injection_queue is not None:
                self.injection_queue.push(candidate.to_injection_item())

            return candidate

    def observe_game(self, observation: GameObservation) -> CommentaryCandidate | None:
        """Inspect game snapshot and trigger appropriate alerts if thresholds breached."""
        if observation.health <= 0.25:
            return self.propose_tactical_alert("low_health", observation=observation)
        if observation.enemies >= 6:
            return self.propose_tactical_alert("heavy_swarm", observation=observation)
        if observation.enemies > 0:
            return self.propose_tactical_alert("enemy_spotted", observation=observation)
        return None

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [c.to_dict() for c in self._history]

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "dnd": self.dnd,
                "tactical_cooldown_sec": self.tactical_cooldown_sec,
                "ambient_cooldown_sec": self.ambient_cooldown_sec,
                "total_generated": self._total_generated,
                "total_suppressed": self._total_suppressed,
                "history_depth": len(self._history),
                "has_injection_queue": self.injection_queue is not None,
            }


class GameControllerAdapter:
    """Virtual gamepad adapter coordinating with GameMotorController and voice."""

    def __init__(
        self,
        *,
        motor_controller: GameMotorController | None = None,
        speech_coordinator: ActionSpeechCoordinator | None = None,
        config: GamepadConfig | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.motor = motor_controller or GameMotorController()
        self.speech = speech_coordinator
        self.config = config or GamepadConfig()
        self._now = now
        self._lock = threading.Lock()
        self._gamepad_state = GamepadState()

    def press_button(
        self,
        button: VirtualGamepadButton | str,
        *,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Press a virtual button down."""
        btn = VirtualGamepadButton.normalize(button)
        dur = max(1, min(1000, duration_ms or self.config.default_duration_ms))
        cmd = GameMotorCommand(action="press", buttons=(btn.value,), duration_ms=dur)

        with self._lock:
            self._gamepad_state.buttons.add(btn.value)
            self._gamepad_state.updated_at = time.time()
            return self.motor.enqueue(cmd)

    def release_button(self, button: VirtualGamepadButton | str) -> dict[str, Any]:
        """Release a pressed virtual button."""
        btn = VirtualGamepadButton.normalize(button)
        cmd = GameMotorCommand(action="release", buttons=(btn.value,), duration_ms=10)

        with self._lock:
            self._gamepad_state.buttons.discard(btn.value)
            self._gamepad_state.updated_at = time.time()
            return self.motor.enqueue(cmd)

    def tap_button(
        self,
        button: VirtualGamepadButton | str,
        *,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Tap (pulse) a virtual button."""
        btn = VirtualGamepadButton.normalize(button)
        dur = max(1, min(1000, duration_ms or self.config.default_duration_ms))
        cmd = GameMotorCommand(action="tap", buttons=(btn.value,), duration_ms=dur)

        with self._lock:
            self._gamepad_state.updated_at = time.time()
            return self.motor.enqueue(cmd)

    def move_stick(
        self,
        stick: GamepadStick | str,
        x: float,
        y: float,
        *,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Set analog stick coordinates with deadzone filtering and bounding."""
        stk = GamepadStick.normalize(stick)
        clean_x, clean_y = apply_stick_deadzone(
            x,
            y,
            inner=self.config.inner_deadzone,
            outer=self.config.outer_deadzone,
        )
        int_x = int(clean_x * self.config.axis_max_int)
        int_y = int(clean_y * self.config.axis_max_int)
        dur = max(1, min(1000, duration_ms or self.config.default_duration_ms))
        action = "move" if stk == GamepadStick.LEFT else "look"
        cmd = GameMotorCommand(action=action, x=int_x, y=int_y, duration_ms=dur)

        with self._lock:
            if stk == GamepadStick.LEFT:
                self._gamepad_state.left_stick = (clean_x, clean_y)
            else:
                self._gamepad_state.right_stick = (clean_x, clean_y)
            self._gamepad_state.updated_at = time.time()
            return self.motor.enqueue(cmd)

    def set_trigger(
        self,
        trigger: str,
        value: float,
        *,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Set analog trigger value (0.0 to 1.0) with deadzone application."""
        clean_name = str(trigger or "").strip().upper()
        if clean_name in {"LEFT", "LT", "L2"}:
            btn_name = "LT"
            is_left = True
        elif clean_name in {"RIGHT", "RT", "R2"}:
            btn_name = "RT"
            is_left = False
        else:
            raise GameEmbodiedError(f"Unsupported trigger identifier: {trigger!r}")

        clean_val = apply_trigger_deadzone(value, deadzone=self.config.trigger_deadzone)
        dur = max(1, min(1000, duration_ms or self.config.default_duration_ms))

        with self._lock:
            if is_left:
                self._gamepad_state.left_trigger = clean_val
            else:
                self._gamepad_state.right_trigger = clean_val

            if clean_val > 0.0:
                self._gamepad_state.buttons.add(btn_name)
                action = "press"
            else:
                self._gamepad_state.buttons.discard(btn_name)
                action = "release"

            cmd = GameMotorCommand(
                action=action,
                buttons=(btn_name,),
                duration_ms=dur,
            )
            self._gamepad_state.updated_at = time.time()
            return self.motor.enqueue(cmd)

    def execute_sequence(self, sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Dispatch a bounded sequence of button or stick commands."""
        results: list[dict[str, Any]] = []
        for step in sequence[:32]:
            kind = str(step.get("type") or "tap").lower()
            if kind == "tap":
                results.append(self.tap_button(step["button"], duration_ms=step.get("duration_ms")))
            elif kind == "press":
                results.append(self.press_button(step["button"], duration_ms=step.get("duration_ms")))
            elif kind == "release":
                results.append(self.release_button(step["button"]))
            elif kind == "stick":
                results.append(
                    self.move_stick(
                        step.get("stick", "left"),
                        float(step.get("x", 0.0)),
                        float(step.get("y", 0.0)),
                        duration_ms=step.get("duration_ms"),
                    )
                )
            elif kind == "trigger":
                results.append(
                    self.set_trigger(
                        step.get("trigger", "RT"),
                        float(step.get("value", 1.0)),
                        duration_ms=step.get("duration_ms"),
                    )
                )
        return results

    def tick(self) -> dict[str, Any]:
        """Advance the motor controller by one tick and update speech coordinator."""
        tick_res = self.motor.tick()
        if tick_res.get("status") == "dispatched" and self.speech is not None:
            action = tick_res.get("action", "")
            if action in {"press", "tap"}:
                # Optional ambient trigger if requested
                pass
        return {
            "motor": tick_res,
            "gamepad": self.get_gamepad_state(),
        }

    def emergency_stop(self) -> dict[str, Any]:
        """Emergency stop: clears motor queue and releases all virtual inputs."""
        motor_res = self.motor.emergency_stop()
        with self._lock:
            self._gamepad_state.buttons.clear()
            self._gamepad_state.left_stick = (0.0, 0.0)
            self._gamepad_state.right_stick = (0.0, 0.0)
            self._gamepad_state.left_trigger = 0.0
            self._gamepad_state.right_trigger = 0.0
            self._gamepad_state.updated_at = time.time()
        return {
            "status": "stopped",
            "cleared_queue": motor_res.get("cleared", 0),
            "released_inputs": True,
        }

    def reset(self) -> None:
        """Reset motor controller and gamepad state to neutral."""
        self.motor.reset()
        with self._lock:
            self._gamepad_state = GamepadState()

    def get_gamepad_state(self) -> dict[str, Any]:
        with self._lock:
            return self._gamepad_state.to_dict()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "motor": self.motor.state(),
                "gamepad": self._gamepad_state.to_dict(),
                "speech": self.speech.state() if self.speech is not None else None,
            }


class GameEmbodimentAdapter(ModelAdapter):
    """Cognitive model slot adapter for ModelSlot.GAME_EMBODIMENT.

    Translates cognitive/ReAct planning into deterministic virtual controller commands
    and coordinated voice commentary proposals.
    """

    _ACTION_PATTERN = re.compile(
        r"(?:ACTION|CMD):\s*(TAP|PRESS|RELEASE|MOVE|LOOK|TRIGGER)\s*([^;\n]+)",
        re.IGNORECASE,
    )
    _COMMENTARY_PATTERN = re.compile(
        r"(?:COMMENTARY|SAY|VOICE):\s*([^\n]+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        name: str = "game-embodiment-engine",
        *,
        controller: GameControllerAdapter | None = None,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        caps = capabilities or ModelCapabilities(
            supports_streaming=False,
            supports_tools=True,
            supports_vision=True,
            supports_audio=False,
            context_window=8192,
            max_output_tokens=512,
            provider_type="game_embodiment",
        )
        super().__init__(name=name, capabilities=caps)
        self.controller = controller or GameControllerAdapter()

    def generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Evaluate gameplay intention or prompt, execute parsed actions, and emit commentary."""
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Game embodiment generation cancelled")

        input_text = prompt
        if not input_text and messages:
            last_msg = messages[-1]
            input_text = str(last_msg.get("content") or "")

        # Look for explicit ACTION / COMMENTARY commands in prompt/messages
        actions_found: list[str] = []
        for match in self._ACTION_PATTERN.finditer(input_text):
            cmd_type = match.group(1).upper()
            args = match.group(2).strip().split()
            try:
                if cmd_type == "TAP" and args:
                    res = self.controller.tap_button(args[0])
                    actions_found.append(f"tap {args[0]} ({res.get('status')})")
                elif cmd_type == "PRESS" and args:
                    res = self.controller.press_button(args[0])
                    actions_found.append(f"press {args[0]} ({res.get('status')})")
                elif cmd_type == "RELEASE" and args:
                    res = self.controller.release_button(args[0])
                    actions_found.append(f"release {args[0]} ({res.get('status')})")
                elif cmd_type in {"MOVE", "LOOK"} and len(args) >= 2:
                    stk = "left" if cmd_type == "MOVE" else "right"
                    res = self.controller.move_stick(stk, float(args[0]), float(args[1]))
                    actions_found.append(f"{stk} stick ({args[0]}, {args[1]}) ({res.get('status')})")
                elif cmd_type == "TRIGGER" and len(args) >= 2:
                    res = self.controller.set_trigger(args[0], float(args[1]))
                    actions_found.append(f"trigger {args[0]}={args[1]} ({res.get('status')})")
            except Exception as exc:
                actions_found.append(f"failed {cmd_type}: {exc}")

        # Check for voice commentary
        commentary_match = self._COMMENTARY_PATTERN.search(input_text)
        commentary_text = commentary_match.group(1).strip() if commentary_match else ""
        if commentary_text and self.controller.speech is not None:
            self.controller.speech.propose_action_commentary(
                action="embodiment_planned",
                text=commentary_text,
                urgency=CommentaryUrgency.AMBIENT,
            )

        if actions_found:
            status_desc = "; ".join(actions_found)
            if commentary_text:
                return f"Dispatched: {status_desc}. Commentary proposed: '{commentary_text}'"
            return f"Dispatched game actions: {status_desc}."

        # Default fallback ReAct response
        return "GameEmbodiment active. Waiting for actionable motor intent or game observation."

    def dispatch_action_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Direct structured execution of an action plan."""
        actions: list[dict[str, Any]] = []
        if "sequence" in plan and isinstance(plan["sequence"], list):
            actions = self.controller.execute_sequence(plan["sequence"])

        button = plan.get("button")
        if button:
            action_type = str(plan.get("action") or "tap").lower()
            dur = plan.get("duration_ms")
            if action_type == "tap":
                actions.append(self.controller.tap_button(button, duration_ms=dur))
            elif action_type == "press":
                actions.append(self.controller.press_button(button, duration_ms=dur))
            elif action_type == "release":
                actions.append(self.controller.release_button(button))

        commentary = plan.get("commentary")
        comment_res = None
        if commentary and self.controller.speech is not None:
            urgency = (
                CommentaryUrgency.TACTICAL
                if plan.get("tactical")
                else CommentaryUrgency.AMBIENT
            )
            candidate = self.controller.speech.propose_action_commentary(
                action=str(plan.get("action_type") or "planned"),
                text=str(commentary),
                urgency=urgency,
            )
            comment_res = candidate.to_dict() if candidate else None

        return {
            "status": "executed",
            "actions": actions,
            "commentary": comment_res,
            "gamepad_state": self.controller.get_gamepad_state(),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "adapter": self.name,
            "controller": self.controller.state(),
        }

    health_check = health

__all__ = [
    "ActionSpeechCoordinator",
    "CommentaryCandidate",
    "CommentaryUrgency",
    "SpeechUrgency",
    "GamepadConfig",
    "GamepadState",
    "GamepadStick",
    "GameControllerAdapter",
    "GameEmbodimentAdapter",
    "VirtualGamepadButton",
    "apply_stick_deadzone",
    "apply_trigger_deadzone",
]
