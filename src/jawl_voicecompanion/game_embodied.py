"""Bounded game embodied layer for H5.

This is an engineering baseline for the three-level game architecture. It keeps
motor commands, voice coordination and strategy/mod planning deterministic and
testable without claiming live game integration, real input injection or
automatic modding approval.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import enum
from pathlib import Path
import time
from typing import Any, Callable, Iterable


class GameEmbodiedError(ValueError):
    """Raised for invalid game-layer requests."""


@dataclass(frozen=True)
class GameMotorCommand:
    """One bounded motor action for a game input bridge."""

    action: str
    x: int = 0
    y: int = 0
    buttons: tuple[str, ...] = ()
    duration_ms: int = 50
    issued_at: float = 0.0

    def __post_init__(self) -> None:
        if self.action not in {"move", "look", "press", "release", "tap"}:
            raise GameEmbodiedError("unsupported game motor action")
        if not -10000 <= self.x <= 10000 or not -10000 <= self.y <= 10000:
            raise GameEmbodiedError("game motor coordinates are out of bounds")
        if any(not isinstance(button, str) or not button or len(button) > 32 for button in self.buttons):
            raise GameEmbodiedError("game motor buttons must be short strings")
        if not 1 <= self.duration_ms <= 1000:
            raise GameEmbodiedError("game motor duration must be between 1 and 1000 ms")


@dataclass(frozen=True)
class GameObservation:
    """Bounded snapshot from a game or mod bridge."""

    game: str
    scene: str = ""
    health: float = 1.0
    enemies: int = 0
    objective: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.game or len(self.game) > 80:
            raise GameEmbodiedError("game name must be a non-empty string of at most 80 characters")
        if not 0.0 <= self.health <= 1.0:
            raise GameEmbodiedError("health must be between 0 and 1")
        if self.enemies < 0 or self.enemies > 1000:
            raise GameEmbodiedError("enemy count must be between 0 and 1000")
        if len(self.scene) > 120 or len(self.objective) > 240:
            raise GameEmbodiedError("game observation text is too long")


class GameInputBridge:
    """Small interface for a game-specific input/mod bridge."""

    def send(self, command: GameMotorCommand) -> dict[str, Any]:
        raise NotImplementedError

    def __call__(self, command: GameMotorCommand) -> dict[str, Any]:
        return self.send(command)


class SimulatedGameInputBridge(GameInputBridge):
    """Deterministic in-memory bridge used for tests and dry runs."""

    def __init__(self) -> None:
        self.sent: list[GameMotorCommand] = []

    def send(self, command: GameMotorCommand) -> dict[str, Any]:
        self.sent.append(command)
        return {"bridge": "simulated", "accepted": True, "action": command.action}


class GameMotorController:
    """Queue and dispatch bounded motor commands at a configured tick rate."""

    def __init__(
        self,
        *,
        tick_rate_hz: float = 30.0,
        max_queue: int = 64,
        bridge: Callable[[GameMotorCommand], dict[str, Any]] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tick_rate_hz = max(10.0, min(60.0, float(tick_rate_hz)))
        self.max_queue = max(1, min(int(max_queue), 256))
        self.bridge = bridge
        self._now = now
        self._queue: list[GameMotorCommand] = []
        self._dispatched: list[dict[str, Any]] = []
        self._last_tick_at = 0.0
        self._dropped = 0
        self._emergency_stop = False

    @property
    def tick_interval_ms(self) -> float:
        return 1000.0 / self.tick_rate_hz

    def enqueue(self, command: GameMotorCommand) -> dict[str, Any]:
        if self._emergency_stop:
            return {"status": "rejected", "reason": "game_motor_emergency_stop"}
        if len(self._queue) >= self.max_queue:
            self._dropped += 1
            return {"status": "dropped", "reason": "game_motor_queue_full"}
        stamped = GameMotorCommand(
            action=command.action,
            x=command.x,
            y=command.y,
            buttons=command.buttons,
            duration_ms=command.duration_ms,
            issued_at=self._now(),
        )
        self._queue.append(stamped)
        return {"status": "queued", "queue_depth": len(self._queue)}

    def tick(self) -> dict[str, Any]:
        if self._emergency_stop:
            self._queue.clear()
            return {"status": "stopped", "dispatched": 0, "queue_depth": 0}
        now = self._now()
        if self._queue and now - self._last_tick_at < self.tick_interval_ms / 1000.0:
            return {"status": "throttled", "dispatched": 0, "queue_depth": len(self._queue)}
        command = self._queue.pop(0) if self._queue else None
        self._last_tick_at = now
        if command is None:
            return {"status": "idle", "dispatched": 0, "queue_depth": 0}
        result = {"status": "dispatched", "action": command.action, "queue_depth": len(self._queue)}
        if self.bridge is not None:
            try:
                bridged = self.bridge(command)
                if isinstance(bridged, dict):
                    result.update(bridged)
            except Exception as exc:  # noqa: BLE001 - motor bridge failures stay bounded
                result = {"status": "degraded", "reason": str(exc)[:160], "queue_depth": len(self._queue)}
        self._dispatched.append(result)
        self._dispatched = self._dispatched[-64:]
        return result

    def emergency_stop(self) -> dict[str, Any]:
        self._emergency_stop = True
        cleared = len(self._queue)
        self._queue.clear()
        return {"status": "stopped", "cleared": cleared}

    def reset(self) -> None:
        self._emergency_stop = False
        self._queue.clear()

    def state(self) -> dict[str, Any]:
        return {
            "tick_rate_hz": self.tick_rate_hz,
            "tick_interval_ms": round(self.tick_interval_ms, 3),
            "queue_depth": len(self._queue),
            "dropped": self._dropped,
            "emergency_stop": self._emergency_stop,
            "dispatched": len(self._dispatched),
        }


class VoiceCombatCoordinator:
    """Map game events to bounded voice/emotion intents without speaking directly."""

    _EVENTS = {
        "enemy_spotted": ("alert", "warning", 2),
        "taking_damage": ("focus", "urgent", 3),
        "low_health": ("warning", "urgent", 3),
        "victory": ("celebrate", "positive", 2),
        "defeat": ("comfort", "negative", 2),
        "objective_complete": ("report", "positive", 1),
    }

    def __init__(self, *, cooldown_seconds: float = 2.0, dnd: bool = False) -> None:
        self.cooldown_seconds = max(0.0, min(float(cooldown_seconds), 60.0))
        self.dnd = bool(dnd)
        self._last_intent_at = 0.0
        self._events = 0

    def handle(self, event: str, *, now: float | None = None) -> dict[str, Any]:
        moment = time.monotonic() if now is None else float(now)
        if event not in self._EVENTS:
            return {"status": "ignored", "reason": "unknown_game_event"}
        if self.dnd:
            return {"status": "suppressed", "reason": "dnd_active"}
        if self._last_intent_at and moment - self._last_intent_at < self.cooldown_seconds:
            return {"status": "coalesced", "reason": "voice_combat_cooldown_active"}
        emotion, priority_name, significance = self._EVENTS[event]
        self._last_intent_at = moment
        self._events += 1
        return {
            "status": "proposed",
            "event": event,
            "emotion": emotion,
            "priority": significance,
            "priority_name": priority_name,
            "speak": True,
        }

    def state(self) -> dict[str, Any]:
        return {"cooldown_seconds": self.cooldown_seconds, "dnd": self.dnd, "events": self._events}


class StrategyModPlanner:
    """Produce bounded, reviewable mod/bridge plans; never execute them directly."""

    def plan(self, *, game: str, bridge: str = "memory", goal: str = "") -> dict[str, Any]:
        clean_game = str(game or "").strip()[:80]
        clean_bridge = str(bridge or "").strip()[:40]
        clean_goal = str(goal or "").strip()[:240]
        if not clean_game:
            raise GameEmbodiedError("game name is required")
        if clean_bridge not in {"memory", "input", "hostos", "mod"}:
            raise GameEmbodiedError("unsupported game bridge")
        return {
            "status": "planned",
            "game": clean_game,
            "bridge": clean_bridge,
            "goal": clean_goal,
            "layers": ["motor", "voice", "strategy"],
            "steps": [
                "observe game state through the configured bridge",
                "queue bounded motor commands through GameMotorController",
                "emit voice/emotion intents through VoiceCombatCoordinator",
                "review any mod or memory write before HostOS execution",
            ],
            "hostos_required": True,
            "raw_game_memory_persisted": False,
        }


@dataclass(frozen=True)
class ModScaffoldFile:
    """One reviewable file in a generated mod/bridge scaffold."""

    path: str
    content: str

    def __post_init__(self) -> None:
        if not self.path or "\\" in self.path or self.path.startswith("/") or ".." in self.path.split("/"):
            raise GameEmbodiedError("mod scaffold path must be a safe relative path")
        if len(self.content) > 64 * 1024:
            raise GameEmbodiedError("mod scaffold content is too large")


class ModScaffold:
    """Bounded scaffold that can be reviewed before any HostOS write."""

    def __init__(self, files: Iterable[ModScaffoldFile]) -> None:
        self.files = tuple(files)
        if not self.files or len(self.files) > 32:
            raise GameEmbodiedError("mod scaffold must contain 1 to 32 files")

    def write_under(self, root: Path) -> list[str]:
        """Write files under root after path and size checks; never escapes root."""
        root = Path(root).resolve()
        written: list[str] = []
        for item in self.files:
            target = (root / item.path).resolve()
            if root not in target.parents and target != root:
                raise GameEmbodiedError("mod scaffold path escapes the target root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
            written.append(str(target.relative_to(root)).replace("\\", "/"))
        return written


class ModScaffoldWriter:
    """Build deterministic mod/bridge scaffolds for later HostOS review."""

    def scaffold(self, *, game: str, bridge: str, goal: str = "") -> ModScaffold:
        clean_game = str(game or "").strip()[:80]
        if not clean_game:
            raise GameEmbodiedError("game name is required")
        if bridge not in {"memory", "input", "hostos", "mod"}:
            raise GameEmbodiedError("unsupported game bridge")
        files = [
            ModScaffoldFile("README.md", f"# {clean_game} bridge\n\nGoal: {goal.strip()[:240]}\n"),
            ModScaffoldFile("bridge.py", "def handle_game_event(event):\n    return {\"status\": \"observed\", \"event\": event}\n"),
            ModScaffoldFile("motor.py", "def motor_tick(commands):\n    return {\"status\": \"queued\", \"count\": len(commands)}\n"),
        ]
        return ModScaffold(files)


class CompanionRole(str, enum.Enum):
    """Tactical posture for autonomous Player 2 companion."""

    SUPPORT = "support"
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"

    @classmethod
    def normalize(cls, value: CompanionRole | str) -> CompanionRole:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            for member in cls:
                if member.value == clean:
                    return member
        raise GameEmbodiedError(
            f"Unsupported companion role: {value!r}. Valid roles: support, aggressive, defensive"
        )


@dataclass
class TacticalTelemetry:
    """Rich tactical telemetry parsed from game observations or live memory bridges."""

    game: str = "game"
    scene: str = ""
    health: float = 1.0
    player_health: float = 1.0
    enemies: int = 0
    target_distance: float = 10.0
    target_x: float = 0.0
    target_y: float = 0.0
    is_under_fire: bool = False
    ammo_ratio: float = 1.0
    objective: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.health = max(0.0, min(1.0, float(self.health)))
        self.player_health = max(0.0, min(1.0, float(self.player_health)))
        self.enemies = max(0, int(self.enemies))
        self.target_distance = max(0.0, float(self.target_distance))
        self.target_x = max(-1.0, min(1.0, float(self.target_x)))
        self.target_y = max(-1.0, min(1.0, float(self.target_y)))
        self.ammo_ratio = max(0.0, min(1.0, float(self.ammo_ratio)))

    @classmethod
    def from_input(cls, source: GameObservation | TacticalTelemetry | dict[str, Any] | None) -> TacticalTelemetry:
        if source is None:
            return cls()
        if isinstance(source, TacticalTelemetry):
            return source
        if isinstance(source, GameObservation):
            return cls(
                game=source.game,
                scene=source.scene,
                health=source.health,
                player_health=source.health,
                enemies=source.enemies,
                objective=source.objective,
                timestamp=source.timestamp,
            )
        if isinstance(source, dict):
            return cls(
                game=str(source.get("game") or "game"),
                scene=str(source.get("scene") or ""),
                health=float(source.get("health", 1.0)),
                player_health=float(source.get("player_health", source.get("teammate_health", 1.0))),
                enemies=int(source.get("enemies", 0)),
                target_distance=float(source.get("target_distance", 10.0)),
                target_x=float(source.get("target_x", 0.0)),
                target_y=float(source.get("target_y", 0.0)),
                is_under_fire=bool(source.get("is_under_fire", False)),
                ammo_ratio=float(source.get("ammo_ratio", 1.0)),
                objective=str(source.get("objective") or ""),
                timestamp=float(source.get("timestamp", 0.0)),
                metadata=dict(source.get("metadata") or {}),
            )
        raise GameEmbodiedError(f"Unsupported telemetry source type: {type(source).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "scene": self.scene,
            "health": round(self.health, 3),
            "player_health": round(self.player_health, 3),
            "enemies": self.enemies,
            "target_distance": round(self.target_distance, 2),
            "target_x": round(self.target_x, 3),
            "target_y": round(self.target_y, 3),
            "is_under_fire": self.is_under_fire,
            "ammo_ratio": round(self.ammo_ratio, 3),
            "objective": self.objective,
            "timestamp": round(self.timestamp, 3),
            "metadata": dict(self.metadata),
        }


@dataclass
class Player2Decision:
    """Record of an autonomous tactical decision by Player 2."""

    tick_id: int
    role: CompanionRole
    emotional_state: str
    stick_move: tuple[float, float]
    stick_look: tuple[float, float]
    tapped_buttons: list[str] = field(default_factory=list)
    pressed_buttons: list[str] = field(default_factory=list)
    released_buttons: list[str] = field(default_factory=list)
    triggers: dict[str, float] = field(default_factory=dict)
    speech_text: str | None = None
    speech_urgency: str | None = None
    action_type: str = "idle"
    rationale: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "role": self.role.value,
            "emotional_state": self.emotional_state,
            "stick_move": [round(self.stick_move[0], 3), round(self.stick_move[1], 3)],
            "stick_look": [round(self.stick_look[0], 3), round(self.stick_look[1], 3)],
            "tapped_buttons": list(self.tapped_buttons),
            "pressed_buttons": list(self.pressed_buttons),
            "released_buttons": list(self.released_buttons),
            "triggers": {k: round(v, 3) for k, v in self.triggers.items()},
            "speech_text": self.speech_text,
            "speech_urgency": self.speech_urgency,
            "action_type": self.action_type,
            "rationale": self.rationale,
            "timestamp": round(self.timestamp, 3),
        }


class Player2CompanionController:
    """Autonomous Player 2 companion executing role-driven tactics and coordinated voice."""

    def __init__(
        self,
        *,
        controller: Any | None = None,
        speech_coordinator: Any | None = None,
        role: CompanionRole | str = CompanionRole.SUPPORT,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        from jawl_voicecompanion.game_controller import GameControllerAdapter

        self._controller = controller or GameControllerAdapter()
        self._speech_coordinator = speech_coordinator
        self._role = CompanionRole.normalize(role)
        self._now = now

        self._emotional_state = "calm"
        self._is_paused = False
        self._is_stopped = False
        self._tick_id = 0
        self._prev_enemies = 0
        self._history: deque[Player2Decision] = deque(maxlen=64)

    @property
    def role(self) -> CompanionRole:
        return self._role

    @property
    def controller(self) -> Any:
        return self._controller

    @property
    def speech_coordinator(self) -> Any | None:
        return self._speech_coordinator

    def set_role(self, role: CompanionRole | str) -> CompanionRole:
        self._role = CompanionRole.normalize(role)
        return self._role

    def get_role(self) -> CompanionRole:
        return self._role

    def pause(self) -> None:
        self._is_paused = True
        self._controller.reset()

    def resume(self) -> None:
        self._is_paused = False
        self._is_stopped = False

    def is_paused(self) -> bool:
        return self._is_paused

    def emergency_stop(self) -> dict[str, Any]:
        self._is_stopped = True
        self._is_paused = False
        return self._controller.emergency_stop()

    def reset(self) -> None:
        self._is_paused = False
        self._is_stopped = False
        self._emotional_state = "calm"
        self._prev_enemies = 0
        self._history.clear()
        self._controller.reset()

    def tactical_tick(
        self, observation: GameObservation | TacticalTelemetry | dict[str, Any] | None = None
    ) -> Player2Decision:
        from jawl_voicecompanion.game_controller import (
            CommentaryUrgency,
            GamepadStick,
            VirtualGamepadButton,
        )

        current_time = self._now()
        telemetry = TacticalTelemetry.from_input(observation)
        if telemetry.timestamp <= 0.0:
            telemetry.timestamp = current_time

        if self._is_stopped:
            decision = Player2Decision(
                tick_id=self._tick_id,
                role=self._role,
                emotional_state="calm",
                stick_move=(0.0, 0.0),
                stick_look=(0.0, 0.0),
                action_type="stopped",
                rationale="Player 2 is stopped",
                timestamp=telemetry.timestamp,
            )
            self._history.append(decision)
            self._tick_id += 1
            return decision

        if self._is_paused:
            decision = Player2Decision(
                tick_id=self._tick_id,
                role=self._role,
                emotional_state=self._emotional_state,
                stick_move=(0.0, 0.0),
                stick_look=(0.0, 0.0),
                action_type="paused",
                rationale="Player 2 is paused",
                timestamp=telemetry.timestamp,
            )
            self._history.append(decision)
            self._tick_id += 1
            return decision

        # 1. Emotional state evaluation
        if telemetry.health <= 0.20 or (telemetry.is_under_fire and telemetry.enemies >= 4):
            self._emotional_state = "panicked"
        elif telemetry.player_health <= 0.35:
            self._emotional_state = "protective"
        elif telemetry.enemies == 0 and self._prev_enemies > 0:
            self._emotional_state = "triumphant"
        elif telemetry.enemies > 0:
            self._emotional_state = "aggressive" if self._role == CompanionRole.AGGRESSIVE else "focused"
        else:
            self._emotional_state = "calm"

        # 2. Tactical decision by role
        stick_move: tuple[float, float] = (0.0, 0.0)
        stick_look: tuple[float, float] = (0.0, 0.0)
        tapped_buttons: list[str] = []
        pressed_buttons: list[str] = []
        released_buttons: list[str] = []
        triggers: dict[str, float] = {}
        speech_text: str | None = None
        speech_urgency: CommentaryUrgency | None = None
        action_type: str = "idle"
        rationale: str = ""

        if self._role == CompanionRole.SUPPORT:
            if telemetry.player_health <= 0.35:
                action_type = "heal_player"
                tapped_buttons.append(VirtualGamepadButton.Y.value)
                stick_move = (0.0, 0.2)
                speech_text = "Heads up, patching you up!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Player health critical, deploying support ability"
            elif telemetry.health <= 0.25:
                action_type = "retreat"
                tapped_buttons.append(VirtualGamepadButton.B.value)
                stick_move = (-telemetry.target_x * 0.5, -0.8)
                speech_text = "Taking heavy damage, falling back to cover!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Self health critical, evading threat"
            elif telemetry.ammo_ratio <= 0.15:
                action_type = "reload"
                tapped_buttons.append(VirtualGamepadButton.X.value)
                speech_text = "Reloading, cover me!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Ammo depleted, reloading weapon"
            elif telemetry.enemies > 0:
                action_type = "covering_fire"
                stick_look = (telemetry.target_x, telemetry.target_y)
                tapped_buttons.append(VirtualGamepadButton.RB.value)
                if telemetry.target_distance > 6.0:
                    stick_move = (0.0, 0.3)
                elif telemetry.target_distance < 3.0:
                    stick_move = (0.0, -0.3)
                speech_text = "Laying down covering fire!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Enemies detected, providing suppressive support"
            elif telemetry.enemies == 0 and self._prev_enemies > 0:
                action_type = "victory"
                speech_text = "Area secure. Nicely done!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Enemies eliminated, celebrating victory"
            else:
                action_type = "follow"
                stick_move = (0.0, 0.2)
                rationale = "Following player formation"

        elif self._role == CompanionRole.AGGRESSIVE:
            if telemetry.health <= 0.20:
                action_type = "evade"
                tapped_buttons.append(VirtualGamepadButton.B.value)
                stick_move = (-telemetry.target_x, -0.6)
                speech_text = "Critical damage! Repositioning!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Critically injured, quick repositioning"
            elif telemetry.ammo_ratio <= 0.15:
                action_type = "reload"
                tapped_buttons.append(VirtualGamepadButton.X.value)
                speech_text = "Switching mags, keep pressure on!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Quick magazine swap"
            elif telemetry.enemies > 0:
                stick_look = (telemetry.target_x, telemetry.target_y)
                stick_move = (telemetry.target_x * 0.6, 1.0)
                if telemetry.target_distance <= 2.5:
                    action_type = "melee_strike"
                    tapped_buttons.append(VirtualGamepadButton.B.value)
                    speech_text = "Too close! Taking them down in melee!"
                    rationale = "Close-quarters combat, delivering melee strike"
                else:
                    action_type = "full_assault"
                    triggers["RT"] = 1.0
                    if telemetry.is_under_fire:
                        tapped_buttons.append(VirtualGamepadButton.A.value)
                    speech_text = "Target locked, pushing hard!"
                    rationale = "Closing distance and firing full assault"
                speech_urgency = CommentaryUrgency.TACTICAL
            elif telemetry.enemies == 0 and self._prev_enemies > 0:
                action_type = "victory"
                speech_text = "Hostiles down! That was too easy!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Enemy threat wiped out"
            else:
                action_type = "scout"
                stick_move = (0.0, 0.5)
                rationale = "Scouting forward for targets"

        elif self._role == CompanionRole.DEFENSIVE:
            if telemetry.is_under_fire or telemetry.health <= 0.40:
                action_type = "shield_and_retreat"
                triggers["LT"] = 1.0
                pressed_buttons.append(VirtualGamepadButton.LB.value)
                tapped_buttons.append(VirtualGamepadButton.B.value)
                stick_move = (-telemetry.target_x * 0.5, -0.6)
                speech_text = "Shields up! Taking defensive stance!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Under direct fire, raising barriers and retreating"
            elif telemetry.player_health <= 0.35:
                action_type = "bodyguard"
                triggers["LT"] = 1.0
                pressed_buttons.append(VirtualGamepadButton.LB.value)
                stick_move = (telemetry.target_x * 0.3, 0.3)
                speech_text = "Get behind me, I'll draw their fire!"
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Teammate in peril, providing body shield"
            elif telemetry.ammo_ratio <= 0.15:
                action_type = "reload"
                tapped_buttons.append(VirtualGamepadButton.X.value)
                speech_text = "Covering behind shield while reloading."
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Safe reload behind cover"
            elif telemetry.enemies > 0:
                action_type = "hold_perimeter"
                stick_look = (telemetry.target_x, telemetry.target_y)
                tapped_buttons.append(VirtualGamepadButton.RB.value)
                stick_move = (0.0, 0.0)
                speech_text = "Holding defensive perimeter."
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Holding fortified perimeter"
            elif telemetry.enemies == 0 and self._prev_enemies > 0:
                action_type = "victory"
                triggers["LT"] = 0.0
                released_buttons.append(VirtualGamepadButton.LB.value)
                speech_text = "Defensive perimeter held. All clear."
                speech_urgency = CommentaryUrgency.TACTICAL
                rationale = "Threat repelled successfully"
            else:
                action_type = "guard"
                stick_move = (0.0, 0.0)
                rationale = "Guarding defensive perimeter"

        # 3. Dispatch motor inputs to controller
        self._controller.move_stick(GamepadStick.LEFT, stick_move[0], stick_move[1])
        self._controller.move_stick(GamepadStick.RIGHT, stick_look[0], stick_look[1])
        for btn in tapped_buttons:
            self._controller.tap_button(btn)
        for btn in pressed_buttons:
            self._controller.press_button(btn)
        for btn in released_buttons:
            self._controller.release_button(btn)
        for trig, val in triggers.items():
            self._controller.set_trigger(trig, val)

        # 4. Dispatch speech commentary if coordinator is configured
        if speech_text and self._speech_coordinator is not None:
            self._speech_coordinator.propose_action_commentary(
                action=action_type,
                text=speech_text,
                urgency=speech_urgency or CommentaryUrgency.TACTICAL,
            )

        self._controller.tick()

        decision = Player2Decision(
            tick_id=self._tick_id,
            role=self._role,
            emotional_state=self._emotional_state,
            stick_move=stick_move,
            stick_look=stick_look,
            tapped_buttons=tapped_buttons,
            pressed_buttons=pressed_buttons,
            released_buttons=released_buttons,
            triggers=triggers,
            speech_text=speech_text,
            speech_urgency=speech_urgency.value if speech_urgency else None,
            action_type=action_type,
            rationale=rationale,
            timestamp=telemetry.timestamp,
        )
        self._history.append(decision)
        self._prev_enemies = telemetry.enemies
        self._tick_id += 1
        return decision

    def tick(
        self, observation: GameObservation | TacticalTelemetry | dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute one autonomous decision tick and return dict representation."""
        return self.tactical_tick(observation).to_dict()

    def get_recent_decisions(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, len(self._history)))
        items = list(self._history)[-safe_limit:]
        return [d.to_dict() for d in items]

    def state(self) -> dict[str, Any]:
        return {
            "role": self._role.value,
            "emotional_state": self._emotional_state,
            "is_paused": self._is_paused,
            "is_stopped": self._is_stopped,
            "tick_id": self._tick_id,
            "decision_count": len(self._history),
            "last_decision": self._history[-1].to_dict() if self._history else None,
            "gamepad": self._controller.get_gamepad_state(),
        }


class GameEmbodiedLayer:
    """Orchestrator for motor, voice, strategy, reviewable mod scaffolds, and autonomous Player 2."""

    def __init__(
        self,
        motor: GameMotorController | None = None,
        voice: VoiceCombatCoordinator | None = None,
        strategy: StrategyModPlanner | None = None,
        scaffolder: ModScaffoldWriter | None = None,
        player2: Player2CompanionController | None = None,
    ) -> None:
        self.motor = motor or GameMotorController()
        self.voice = voice or VoiceCombatCoordinator()
        self.strategy = strategy or StrategyModPlanner()
        self.scaffolder = scaffolder or ModScaffoldWriter()
        self.player2 = player2
        self.observations: list[GameObservation] = []

    def enable_player2(
        self,
        *,
        role: CompanionRole | str = CompanionRole.SUPPORT,
        controller: Any | None = None,
        speech_coordinator: Any | None = None,
    ) -> Player2CompanionController:
        from jawl_voicecompanion.game_controller import GameControllerAdapter

        p2_ctrl = controller or GameControllerAdapter(motor_controller=self.motor)
        self.player2 = Player2CompanionController(
            controller=p2_ctrl,
            speech_coordinator=speech_coordinator,
            role=role,
        )
        return self.player2

    def observe(self, observation: GameObservation, *, now: float | None = None) -> dict[str, Any]:
        self.observations.append(observation)
        self.observations = self.observations[-64:]
        voice = None
        moment = observation.timestamp if observation.timestamp else now
        if observation.health <= 0.25:
            voice = self.voice.handle("low_health", now=moment)
        elif observation.enemies:
            voice = self.voice.handle("enemy_spotted", now=moment)
        res = {"observation": observation, "voice": voice, "motor_queue_depth": self.motor.state()["queue_depth"]}
        if self.player2 is not None:
            res["player2"] = self.player2.tick(observation)
        return res

    def handle_event(self, event: str, *, now: float | None = None) -> dict[str, Any]:
        voice = self.voice.handle(event, now=now)
        return {"voice": voice, "motor_queue_depth": self.motor.state()["queue_depth"]}

    def enqueue_motor(self, command: GameMotorCommand) -> dict[str, Any]:
        return self.motor.enqueue(command)

    def tick(self) -> dict[str, Any]:
        res = {"motor": self.motor.tick(), "voice": self.voice.state()}
        if self.player2 is not None:
            res["player2"] = self.player2.tick()
        return res

    def plan_mod(self, *, game: str, bridge: str = "memory", goal: str = "") -> dict[str, Any]:
        return self.strategy.plan(game=game, bridge=bridge, goal=goal)

    def scaffold_mod(self, *, game: str, bridge: str = "memory", goal: str = "") -> ModScaffold:
        plan = self.plan_mod(game=game, bridge=bridge, goal=goal)
        return self.scaffolder.scaffold(game=plan["game"], bridge=plan["bridge"], goal=plan["goal"])

    def state(self) -> dict[str, Any]:
        res = {
            "motor": self.motor.state(),
            "voice": self.voice.state(),
            "observations": len(self.observations),
        }
        if self.player2 is not None:
            res["player2"] = self.player2.state()
        return res


__all__ = [
    "CompanionRole",
    "GameEmbodiedError",
    "GameEmbodiedLayer",
    "GameInputBridge",
    "GameMotorCommand",
    "GameMotorController",
    "GameObservation",
    "ModScaffold",
    "ModScaffoldFile",
    "ModScaffoldWriter",
    "Player2CompanionController",
    "Player2Decision",
    "SimulatedGameInputBridge",
    "StrategyModPlanner",
    "TacticalTelemetry",
    "VoiceCombatCoordinator",
]
