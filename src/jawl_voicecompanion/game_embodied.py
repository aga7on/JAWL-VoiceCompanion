"""Bounded game embodied layer for H5.

This is an engineering baseline for the three-level game architecture. It keeps
motor commands, voice coordination and strategy/mod planning deterministic and
testable without claiming live game integration, real input injection or
automatic modding approval.
"""

from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import time


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


class GameEmbodiedLayer:
    """Orchestrator for motor, voice, strategy and reviewable mod scaffolds."""

    def __init__(
        self,
        motor: GameMotorController | None = None,
        voice: VoiceCombatCoordinator | None = None,
        strategy: StrategyModPlanner | None = None,
        scaffolder: ModScaffoldWriter | None = None,
    ) -> None:
        self.motor = motor or GameMotorController()
        self.voice = voice or VoiceCombatCoordinator()
        self.strategy = strategy or StrategyModPlanner()
        self.scaffolder = scaffolder or ModScaffoldWriter()
        self.observations: list[GameObservation] = []

    def observe(self, observation: GameObservation, *, now: float | None = None) -> dict[str, Any]:
        self.observations.append(observation)
        self.observations = self.observations[-64:]
        voice = None
        moment = observation.timestamp if observation.timestamp else now
        if observation.health <= 0.25:
            voice = self.voice.handle("low_health", now=moment)
        elif observation.enemies:
            voice = self.voice.handle("enemy_spotted", now=moment)
        return {"observation": observation, "voice": voice, "motor_queue_depth": self.motor.state()["queue_depth"]}

    def handle_event(self, event: str, *, now: float | None = None) -> dict[str, Any]:
        voice = self.voice.handle(event, now=now)
        return {"voice": voice, "motor_queue_depth": self.motor.state()["queue_depth"]}

    def enqueue_motor(self, command: GameMotorCommand) -> dict[str, Any]:
        return self.motor.enqueue(command)

    def tick(self) -> dict[str, Any]:
        return {"motor": self.motor.tick(), "voice": self.voice.state()}

    def plan_mod(self, *, game: str, bridge: str = "memory", goal: str = "") -> dict[str, Any]:
        return self.strategy.plan(game=game, bridge=bridge, goal=goal)

    def scaffold_mod(self, *, game: str, bridge: str = "memory", goal: str = "") -> ModScaffold:
        plan = self.plan_mod(game=game, bridge=bridge, goal=goal)
        return self.scaffolder.scaffold(game=plan["game"], bridge=plan["bridge"], goal=plan["goal"])

    def state(self) -> dict[str, Any]:
        return {
            "motor": self.motor.state(),
            "voice": self.voice.state(),
            "observations": len(self.observations),
        }


__all__ = [
    "GameEmbodiedError",
    "GameEmbodiedLayer",
    "GameInputBridge",
    "GameMotorCommand",
    "GameMotorController",
    "GameObservation",
    "ModScaffold",
    "ModScaffoldFile",
    "ModScaffoldWriter",
    "SimulatedGameInputBridge",
    "StrategyModPlanner",
    "VoiceCombatCoordinator",
]
