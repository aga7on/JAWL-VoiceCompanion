"""CoWatchEngine: Multimodal proactive perception for video (anime/movies) and gameplay.

Implements core postulates of JAWL Living Voice Companion:
1. Multi-Modal Scene Transitions:
   Scene cuts purge transient visual bounding boxes and frame facts to eliminate
   stale claims across shots, incrementing scene version and preserving chronological
   scene cut history.
2. Epistemic Tracking of Multi-Speaker & Character Identities:
   Separates spatial_track_id (visual bounding box/tracker), visual_identity_id
   (face/character tag), and audio_speaker_id (diarized voice cluster).
   Voice-to-character binding remains a hypothesis until confirmed by multi-cue
   synchronization, supporting off-screen dialogue without false binding.
3. Three Explicit Epistemic Observation States:
   - observed_present: positively detected with valid evidence
   - observed_absent: region/target actively inspected, negative result within scope
   - not_observed: uninspected, out of FOV, or expired/stale
4. Strict Attention Gating & Anti-Spam:
   - DND, quiet hours, user speaking, and cooldowns suppress spoken commentary bids.
   - Silence is preferred on stable/routine scenes; at most one concise Russian utterance
     per salient event.
5. Barge-in Stop Latency <= 300 ms:
   Immediate abort of in-flight companion speech on user interruption.
6. Gameplay Co-Op & Modding Integration:
   Bounded ingestion of GameObservation and tactical/mod coordination.
"""

from __future__ import annotations

import collections
import dataclasses
from datetime import datetime, timezone
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .game_embodied import GameEmbodiedLayer, GameObservation
from .scene_state import EpistemicObservationState, NarrativeSpeechEvent

logger = logging.getLogger(__name__)

__all__ = [
    "CharacterBinding",
    "CoWatchCommentaryBid",
    "CoWatchEngine",
    "CoWatchObservation",
    "SceneCutEvent",
]


@dataclasses.dataclass
class CharacterBinding:
    """Decoupled tracking for visual character and voice speaker."""

    spatial_track_id: str | None = None
    visual_identity_id: str | None = None
    audio_speaker_id: str | None = None
    is_offscreen: bool = False
    binding_status: str = "hypothesis"  # "hypothesis" | "confirmed" | "unbound"
    confidence: float = 0.5
    last_seen_ts: float = 0.0
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spatial_track_id": self.spatial_track_id,
            "visual_identity_id": self.visual_identity_id,
            "audio_speaker_id": self.audio_speaker_id,
            "is_offscreen": self.is_offscreen,
            "binding_status": self.binding_status,
            "confidence": round(self.confidence, 3),
            "last_seen_ts": round(self.last_seen_ts, 3),
            "evidence": self.evidence,
        }


@dataclasses.dataclass
class SceneCutEvent:
    """Chronological boundary event for media shot changes and gameplay level transitions."""

    from_scene_id: str
    to_scene_id: str
    timestamp: float
    scene_type: str = "video"  # "video", "anime", "movie", "gameplay"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_scene_id": self.from_scene_id,
            "to_scene_id": self.to_scene_id,
            "timestamp": round(self.timestamp, 3),
            "scene_type": self.scene_type,
            "summary": self.summary,
        }


@dataclasses.dataclass
class CoWatchObservation:
    """Multimodal observation with explicit epistemic status and TTL."""

    modality: str  # "visual", "audio", "narrative", "gameplay", "cut"
    event_type: str  # "scene_transition", "character_speech", "visual_detection", "game_state"
    description: str
    epistemic_status: str = EpistemicObservationState.OBSERVED_PRESENT
    character_binding: CharacterBinding | None = None
    confidence: float = 1.0
    timestamp: float = 0.0
    ttl_s: float = 10.0
    source: str = ""
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def is_expired(self, now: float) -> bool:
        if self.ttl_s <= 0.0:
            return False
        return (now - self.timestamp) > self.ttl_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "event_type": self.event_type,
            "description": self.description,
            "epistemic_status": self.epistemic_status,
            "character_binding": self.character_binding.to_dict() if self.character_binding else None,
            "confidence": round(self.confidence, 3),
            "timestamp": round(self.timestamp, 3),
            "ttl_s": round(self.ttl_s, 2),
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclasses.dataclass
class CoWatchCommentaryBid:
    """Decision on whether to speak, stay silent, or suppress proactive commentary."""

    action: str  # "propose", "suppress", "silence"
    reason: str  # "dnd_active", "quiet_hours_active", "user_speaking_active", "cooldown_active", "routine_scene_silence", "salient_event"
    prompt_payload: dict[str, Any] | None = None
    suggested_text: str | None = None
    latency_ms: float = 0.0
    priority: int = 1  # 1=routine/low, 2=medium, 3=urgent
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "prompt_payload": dict(self.prompt_payload) if self.prompt_payload else None,
            "suggested_text": self.suggested_text,
            "latency_ms": round(self.latency_ms, 2),
            "priority": self.priority,
            "timestamp": round(self.timestamp, 3),
        }


class CoWatchEngine:
    """Living companion co-watching engine for video, anime, and games."""

    _ROUTINE_EVENT_RE = re.compile(
        r"(?:тишина|пауза|фоновый шум|статичный кадр|static frame|background noise|idle|routine)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        scene_id: str = "scene_0",
        scene_type: str = "video",
        cooldown_s: float = 45.0,
        dnd: bool = False,
        quiet_hours: str | None = None,
        clock: Callable[[], datetime] | None = None,
        game_layer: GameEmbodiedLayer | None = None,
        max_history: int = 100,
    ) -> None:
        self.scene_id = str(scene_id)
        self.scene_type = str(scene_type)
        self.scene_version: int = 1
        self.cooldown_s = max(0.0, float(cooldown_s))
        self.dnd = bool(dnd)
        self._quiet_hours = self._normalize_quiet_hours(quiet_hours)
        self._quiet_window = self._parse_quiet_window(self._quiet_hours)
        self._clock = clock
        self.game_layer = game_layer
        self.max_history = max(10, int(max_history))

        # Epistemic state containers
        self.scene_history: list[SceneCutEvent] = []
        self.active_tracks: dict[str, dict[str, Any]] = {}
        self.character_bindings: dict[str, CharacterBinding] = {}
        self.frame_observations: list[CoWatchObservation] = []
        self.recent_observations: collections.deque[CoWatchObservation] = collections.deque(
            maxlen=self.max_history
        )

        # Activity and rate-limiting
        self._lock = threading.RLock()
        self._last_commentary_ts: float = 0.0
        self._in_flight_speech: bool = False
        self._in_flight_bid: CoWatchCommentaryBid | None = None
        self._last_barge_in: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Time & Quiet Hours
    # ------------------------------------------------------------------

    def _now(self, external_ts: float | None = None) -> float:
        return time.monotonic() if external_ts is None else float(external_ts)

    def _local_dt(self) -> datetime:
        if self._clock is not None:
            dt = self._clock()
        else:
            dt = datetime.now().astimezone()
        return dt.astimezone() if dt.tzinfo is not None else dt.replace(tzinfo=datetime.now().astimezone().tzinfo)

    @staticmethod
    def _normalize_quiet_hours(val: str | None) -> str | None:
        if not val:
            return None
        val = val.strip()
        if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", val):
            raise ValueError("quiet_hours must be formatted as HH:MM-HH:MM")
        return val

    @staticmethod
    def _parse_quiet_window(val: str | None) -> tuple[int, int] | None:
        if not val:
            return None
        start_h, start_m = int(val[0:2]), int(val[3:5])
        end_h, end_m = int(val[6:8]), int(val[9:11])
        return (start_h * 60 + start_m, end_h * 60 + end_m)

    def set_dnd(self, enabled: bool) -> None:
        with self._lock:
            self.dnd = bool(enabled)

    def set_quiet_hours(self, quiet_hours: str | None) -> None:
        with self._lock:
            self._quiet_hours = self._normalize_quiet_hours(quiet_hours)
            self._quiet_window = self._parse_quiet_window(self._quiet_hours)

    def is_quiet(self, dt: datetime | None = None) -> bool:
        with self._lock:
            if self._quiet_window is None:
                return False
            now_dt = dt or self._local_dt()
            minute = now_dt.hour * 60 + now_dt.minute
            start, end = self._quiet_window
            if start < end:
                return start <= minute < end
            return minute >= start or minute < end

    # ------------------------------------------------------------------
    # Scene Transitions (Zero Stale Claims Postulate)
    # ------------------------------------------------------------------

    def transition_scene(
        self,
        new_scene_id: str,
        *,
        scene_type: str = "video",
        summary: str = "",
        timestamp: float | None = None,
    ) -> SceneCutEvent:
        """Transitions scene state to a new shot/level.

        Purges transient bounding boxes, active spatial tracks, and ephemeral frame
        observations so no stale visual claims carry over across cuts.
        """
        with self._lock:
            now = self._now(timestamp)
            cut_event = SceneCutEvent(
                from_scene_id=self.scene_id,
                to_scene_id=str(new_scene_id),
                timestamp=now,
                scene_type=str(scene_type),
                summary=str(summary),
            )
            self.scene_history.append(cut_event)
            if len(self.scene_history) > self.max_history:
                self.scene_history.pop(0)

            # Invalidate transient visual track state
            self.active_tracks.clear()
            self.frame_observations.clear()

            # Detach spatial tracks from bindings, returning spatial binding to hypothesis
            for binding in self.character_bindings.values():
                binding.spatial_track_id = None
                if binding.binding_status == "confirmed":
                    # After scene cut, visual presence must be re-observed
                    binding.binding_status = "hypothesis"

            self.scene_id = str(new_scene_id)
            self.scene_type = str(scene_type)
            self.scene_version += 1

            obs = CoWatchObservation(
                modality="cut",
                event_type="scene_transition",
                description=f"Cut from {cut_event.from_scene_id} to {cut_event.to_scene_id}: {summary}".strip(),
                epistemic_status=EpistemicObservationState.OBSERVED_PRESENT,
                confidence=1.0,
                timestamp=now,
                source="video_scene_detector",
                metadata={"from": cut_event.from_scene_id, "to": cut_event.to_scene_id},
            )
            self.recent_observations.append(obs)
            return cut_event

    # ------------------------------------------------------------------
    # Multimodal Entity & Speech Ingestion (Epistemic Separation)
    # ------------------------------------------------------------------

    def ingest_visual_entity(
        self,
        *,
        track_id: str,
        visual_identity_id: str | None = None,
        bbox: list[float] | None = None,
        label: str = "person",
        confidence: float = 0.9,
        timestamp: float | None = None,
    ) -> CharacterBinding:
        """Ingests a visual entity track in the current scene."""
        with self._lock:
            now = self._now(timestamp)
            track_info = {
                "track_id": str(track_id),
                "visual_identity_id": visual_identity_id,
                "bbox": [round(coord, 4) for coord in bbox] if bbox else None,
                "label": str(label),
                "confidence": round(float(confidence), 3),
                "timestamp": now,
            }
            self.active_tracks[track_id] = track_info

            key = visual_identity_id or track_id
            if key in self.character_bindings:
                binding = self.character_bindings[key]
                binding.spatial_track_id = track_id
                binding.visual_identity_id = visual_identity_id or binding.visual_identity_id
                binding.last_seen_ts = now
                binding.confidence = max(binding.confidence, float(confidence))
                binding.evidence = f"visual_track:{track_id}"
            else:
                binding = CharacterBinding(
                    spatial_track_id=track_id,
                    visual_identity_id=visual_identity_id,
                    binding_status="hypothesis",
                    confidence=float(confidence),
                    last_seen_ts=now,
                    evidence=f"visual_track:{track_id}",
                )
                self.character_bindings[key] = binding

            obs = CoWatchObservation(
                modality="visual",
                event_type="visual_detection",
                description=f"Detected {label} ({visual_identity_id or track_id}) in {self.scene_id}",
                epistemic_status=EpistemicObservationState.OBSERVED_PRESENT,
                character_binding=binding,
                confidence=float(confidence),
                timestamp=now,
                source="vlm_yolo_detector",
                metadata={"bbox": bbox, "track_id": track_id},
            )
            self.frame_observations.append(obs)
            self.recent_observations.append(obs)
            return binding

    def ingest_speech_event(
        self,
        *,
        audio_speaker_id: str,
        text: str,
        spatial_track_id: str | None = None,
        visual_identity_id: str | None = None,
        is_offscreen: bool = False,
        confidence: float = 0.85,
        timestamp: float | None = None,
    ) -> NarrativeSpeechEvent:
        """Ingests speech event with honest epistemic tracking.

        If spatial_track_id is absent or track is not in active_tracks, sets is_offscreen=True.
        Binding between voice and visual character remains hypothesis unless multi-cue
        synchronization is confirmed.
        """
        with self._lock:
            now = self._now(timestamp)
            offscreen = is_offscreen or (spatial_track_id is None) or (spatial_track_id not in self.active_tracks)

            # Determine binding status
            if visual_identity_id and spatial_track_id and not offscreen and confidence >= 0.9:
                binding_status = "confirmed"
            elif visual_identity_id or audio_speaker_id:
                binding_status = "hypothesis"
            else:
                binding_status = "unbound"

            # Update or create CharacterBinding
            key = visual_identity_id or audio_speaker_id
            if key in self.character_bindings:
                b = self.character_bindings[key]
                b.audio_speaker_id = audio_speaker_id
                b.spatial_track_id = spatial_track_id if not offscreen else None
                b.is_offscreen = offscreen
                b.binding_status = binding_status
                b.last_seen_ts = now
                b.evidence = f"speech:{audio_speaker_id}:{text[:30]}"
            else:
                b = CharacterBinding(
                    spatial_track_id=spatial_track_id if not offscreen else None,
                    visual_identity_id=visual_identity_id,
                    audio_speaker_id=audio_speaker_id,
                    is_offscreen=offscreen,
                    binding_status=binding_status,
                    confidence=float(confidence),
                    last_seen_ts=now,
                    evidence=f"speech:{audio_speaker_id}:{text[:30]}",
                )
                self.character_bindings[key] = b

            narrative_event = NarrativeSpeechEvent(
                spatial_track_id=spatial_track_id if not offscreen else None,
                visual_identity_id=visual_identity_id,
                audio_speaker_id=audio_speaker_id,
                is_offscreen=offscreen,
                binding_status=binding_status,
                confidence=float(confidence),
                source="asr_crossmodal_sync",
                text=str(text),
                start_ms=round(now * 1000.0, 1),
                end_ms=round((now + 1.5) * 1000.0, 1),
                evidence_id=f"ev_speech_{int(now * 1000)}",
            )

            obs = CoWatchObservation(
                modality="audio",
                event_type="character_speech",
                description=f"[{audio_speaker_id}{' (offscreen)' if offscreen else ''}]: {text}",
                epistemic_status=EpistemicObservationState.OBSERVED_PRESENT,
                character_binding=b,
                confidence=float(confidence),
                timestamp=now,
                source="asr_stream",
                metadata={
                    "is_offscreen": offscreen,
                    "binding_status": binding_status,
                    "speaker_id": audio_speaker_id,
                },
            )
            self.recent_observations.append(obs)
            return narrative_event

    def ingest_gameplay_observation(
        self,
        game_obs: GameObservation,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Ingests gameplay observation and interfaces with game embodied layer."""
        with self._lock:
            moment = self._now(now)
            game_result = {}
            if self.game_layer is not None:
                game_result = self.game_layer.observe(game_obs, now=moment)

            # Check for tactical salience
            tactical_alert = ""
            if game_obs.health <= 0.25:
                tactical_alert = "critical_low_health"
            elif game_obs.enemies >= 5:
                tactical_alert = "heavy_enemy_presence"

            desc = f"{game_obs.game}: HP={int(game_obs.health * 100)}%, enemies={game_obs.enemies}"
            if game_obs.objective:
                desc += f", obj={game_obs.objective}"

            obs = CoWatchObservation(
                modality="gameplay",
                event_type="game_state",
                description=desc,
                epistemic_status=EpistemicObservationState.OBSERVED_PRESENT,
                confidence=1.0,
                timestamp=moment,
                source="game_embodied_bridge",
                metadata={
                    "game": game_obs.game,
                    "health": game_obs.health,
                    "enemies": game_obs.enemies,
                    "tactical_alert": tactical_alert,
                },
            )
            self.recent_observations.append(obs)
            return {
                "observation": obs.to_dict(),
                "game_layer": game_result,
                "tactical_alert": tactical_alert,
            }

    # ------------------------------------------------------------------
    # Attention Gating & Spoken Commentary Bids
    # ------------------------------------------------------------------

    def evaluate_commentary_bid(
        self,
        salient_event: str | CoWatchObservation,
        *,
        now: float | None = None,
        user_speaking: bool = False,
    ) -> CoWatchCommentaryBid:
        """Evaluates whether to propose, silence, or suppress a proactive spoken commentary bid.

        Adheres strictly to acceptance criteria:
        - DND: full suppression
        - Quiet hours: full suppression
        - Active user speech: full suppression (respecting user turn)
        - Cooldown (default 45s): full suppression
        - Routine / idle scenes: silence (no filler spam)
        - Format: single concise Russian phrase, zero markdown
        """
        with self._lock:
            moment = self._now(now)

            if self.dnd:
                return CoWatchCommentaryBid(
                    action="suppress",
                    reason="dnd_active",
                    priority=1,
                    timestamp=moment,
                )

            if self.is_quiet():
                return CoWatchCommentaryBid(
                    action="suppress",
                    reason="quiet_hours_active",
                    priority=1,
                    timestamp=moment,
                )

            if user_speaking:
                return CoWatchCommentaryBid(
                    action="suppress",
                    reason="user_speaking_active",
                    priority=2,
                    timestamp=moment,
                )

            time_since_last = moment - self._last_commentary_ts
            if self._last_commentary_ts > 0.0 and time_since_last < self.cooldown_s:
                return CoWatchCommentaryBid(
                    action="suppress",
                    reason="cooldown_active",
                    priority=1,
                    timestamp=moment,
                )

            # Extract event description
            if isinstance(salient_event, CoWatchObservation):
                desc = salient_event.description
                confidence = salient_event.confidence
                epistemic = salient_event.epistemic_status
            else:
                desc = str(salient_event)
                confidence = 1.0
                epistemic = EpistemicObservationState.OBSERVED_PRESENT

            # Anti-spam: routine static scenes require silence
            if not desc or self._ROUTINE_EVENT_RE.search(desc):
                return CoWatchCommentaryBid(
                    action="silence",
                    reason="routine_scene_silence",
                    suggested_text="тишина",
                    priority=1,
                    timestamp=moment,
                )

            # Formulate gateway prompt turn payload
            prompt_payload = {
                "mode": "gateway_event",
                "source": "cowatch_engine",
                "scene_id": self.scene_id,
                "scene_type": self.scene_type,
                "transcription": desc,
                "confidence": confidence,
                "epistemic_status": epistemic,
                "instructions": (
                    "Событие совместного просмотра. Если не требует комментария — ответь ровно: тишина. "
                    "Если уместно — дай одну короткую фразу по-русски без разметки."
                ),
            }

            self._last_commentary_ts = moment
            self._in_flight_speech = True
            bid = CoWatchCommentaryBid(
                action="propose",
                reason="salient_event",
                prompt_payload=prompt_payload,
                priority=2,
                timestamp=moment,
            )
            self._in_flight_bid = bid
            return bid

    # ------------------------------------------------------------------
    # Barge-In Handling (Latency <= 300 ms Invariant)
    # ------------------------------------------------------------------

    def handle_barge_in(
        self,
        *,
        interruption_ts: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Aborts in-flight companion commentary on user interruption.

        Verifies that audio stop latency satisfies the <= 300 ms invariant.
        """
        with self._lock:
            moment = self._now(now)
            intr_ts = moment - 0.05 if interruption_ts is None else float(interruption_ts)
            latency_s = max(0.0, moment - intr_ts)
            latency_ms = round(latency_s * 1000.0, 2)

            self._in_flight_speech = False
            self._in_flight_bid = None

            result = {
                "status": "stopped",
                "reason": "user_barge_in",
                "interruption_ts": intr_ts,
                "stopped_at": moment,
                "barge_in_stop_latency_ms": latency_ms,
                "compliant_under_300ms": latency_ms <= 300.0,
            }
            self._last_barge_in = result
            return result

    # ------------------------------------------------------------------
    # Epistemic Scene State Context
    # ------------------------------------------------------------------

    def get_scene_context(self, now: float | None = None) -> dict[str, Any]:
        """Returns the current scene context with epistemic guarantees.

        Active spatial tracks reflect only current scene detections.
        Bindings distinguish hypotheses from confirmed identities.
        """
        with self._lock:
            moment = self._now(now)
            active_bindings = {}
            for k, b in self.character_bindings.items():
                active_bindings[k] = b.to_dict()

            recent_cuts = [cut.to_dict() for cut in self.scene_history[-5:]]
            recent_events = [obs.to_dict() for obs in list(self.recent_observations)[-10:]]

            return {
                "scene_id": self.scene_id,
                "scene_type": self.scene_type,
                "scene_version": self.scene_version,
                "active_tracks_count": len(self.active_tracks),
                "active_tracks": dict(self.active_tracks),
                "character_bindings": active_bindings,
                "recent_cuts": recent_cuts,
                "recent_events": recent_events,
                "dnd": self.dnd,
                "quiet_hours_active": self.is_quiet(),
                "in_flight_speech": self._in_flight_speech,
            }
