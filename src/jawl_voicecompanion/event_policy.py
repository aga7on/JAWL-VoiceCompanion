"""EventPolicy: Conversational Initiative & Grounded Commentary Arbitration for JAWL.

Governs when JAWL should speak autonomously during video/screen watching:
1. Grounded Evidence: remarks must point to verified evidence_id (keyframe/speech turn).
2. Salience Scoring: suppresses trivial diffs (e.g. 15% movement, lighting flicker) while
   admitting narrative turns, character appearances, emotional dialogue, and user queries.
3. Social Courtesy: respects cooldowns, avoids repetitive commentary, and never interrupts
   active user speech.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .scene_state import NarrativeSpeechEvent, SceneState

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PolicyDecision:
    """Represents arbitration outcome for a cognitive perception event."""
    should_speak: bool
    decision_type: str  # "commentary", "interactive_answer", "suppressed_cooldown", etc.
    salience_score: float
    evidence_id: str = ""
    confidence: float = 0.85
    character_id: str | None = None
    prompt_context: dict[str, Any] = dataclasses.field(default_factory=dict)
    reason: str = ""
    timestamp_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_speak": self.should_speak,
            "decision_type": self.decision_type,
            "salience_score": round(self.salience_score, 3),
            "evidence_id": self.evidence_id,
            "confidence": round(self.confidence, 3),
            "character_id": self.character_id,
            "prompt_context": dict(self.prompt_context),
            "reason": self.reason,
            "timestamp_sec": round(self.timestamp_sec, 2),
        }


class EventPolicy:
    """Evaluates SceneState semantic deltas and decides whether companion should speak."""

    def __init__(
        self,
        *,
        min_salience_threshold: float = 0.60,
        commentary_cooldown_sec: float = 8.0,
        anti_repetition_window_sec: float = 25.0,
        require_grounded_evidence: bool = True,
    ) -> None:
        self.min_salience_threshold = float(min_salience_threshold)
        self.commentary_cooldown_sec = float(commentary_cooldown_sec)
        self.anti_repetition_window_sec = float(anti_repetition_window_sec)
        self.require_grounded_evidence = bool(require_grounded_evidence)

        self._last_spoken_time_sec: float = -999.0
        self._spoken_topics: collections.deque[tuple[str, float]] = collections.deque(maxlen=50)

    def record_spoken(self, topic_key: str, timestamp_sec: float) -> None:
        """Records that the companion spoke about a topic at timestamp."""
        self._last_spoken_time_sec = float(timestamp_sec)
        self._spoken_topics.append((str(topic_key), float(timestamp_sec)))

    def is_topic_recent(self, topic_key: str, timestamp_sec: float) -> bool:
        """Checks if a topic was commented on recently within anti-repetition window."""
        t_now = float(timestamp_sec)
        for key, t_past in self._spoken_topics:
            if key == topic_key and (t_now - t_past) < self.anti_repetition_window_sec:
                return True
        return False

    @staticmethod
    def is_visual_query(query: str) -> bool:
        """Detects whether a user query expresses visual intent about current screen or scene."""
        q = str(query or "").lower().strip()
        if not q:
            return False

        # Exclude queries explicitly about retrospective memory / past timeline
        # unless an explicit present command demands inspecting the live screen right now.
        retrospective_patterns = [
            r"было.*?(раньше|ранее|до этого)",
            r"происходило.*?(до этого|ранее)",
            r"(видел|видели).*?(раньше|ранее)",
            r"только что видели",
            r"показывали.*?(раньше|ранее)",
            r"в памяти сенсоров",
            r"сенсорной памяти",
            r"в истории",
            r"минуту назад",
        ]
        present_imperatives = ["посмотри сейчас", "взгляни сейчас", "глянь сейчас", "что прямо сейчас"]
        if any(re.search(p, q, re.IGNORECASE) for p in retrospective_patterns) and not any(p in q for p in present_imperatives):
            return False

        # Exclude queries explicitly about spoken dialogue / memory unless they demand looking at screen
        dialogue_markers = [
            "говорили", "сказал", "сказала", "речь в разговоре", "разговор", "спорили",
            "звонил", "по домофону", "в начале серии", "минуту назад", "в предыдущей сцене",
            "как зовут", "напомни, куда", "что ответила", "истории",
        ]
        visual_imperatives = ["посмотри", "взгляни", "глянь", "погляди", "на экране", "в кадре"]
        if any(d in q for d in dialogue_markers) and not any(v in q for v in visual_imperatives):
            return False

        patterns = [
            r"(что|кто|кого|чего|где|куда|откуда).*?(на экране|в кадре|ты видишь|видно|сидит|стоит|происходит|висит|лежит|находится)",
            r"(посмотри|взгляни|глянь|погляди|видишь|опиши)",
            r"(есть ли|виден ли|видно ли|стоит ли|сидит ли|лежит ли|бегает ли|находится ли)",
            r"(во что|какого цвета|какая одежда|одет|одета|платье|костюм|шлем|очки)",
            r"(что за предмет|что написано|что за вещь|кто там)",
            r"(в коридоре|на заднем плане|на экране|в кадре)",
            r"\b(screen|frame|background|look at|see now|what do you see|who is on screen|wearing|is there|can you see)\b",
        ]
        return any(re.search(pat, q, re.IGNORECASE) for pat in patterns)

    @staticmethod
    def extract_visual_target(query: str) -> tuple[str, str]:
        """Extracts target focus and region from user query."""
        q = str(query or "").lower().strip()

        # Specific object / subject checks
        if "собак" in q:
            return "собака", "full_frame"
        if "курьер" in q:
            return "курьер", "corridor"
        if "автомобил" in q or "машин" in q:
            return "автомобиль", "background"
        if "чашк" in q or "кофе" in q:
            return "чашка кофе", "desk"
        if "ребенок" in q or "дети" in q:
            return "ребенок", "foreground"
        if "пистолет" in q or "оружи" in q:
            return "оружие", "full_frame"
        if "кот" in q or "кошк" in q:
            return "кот", "foreground"
        if "свеч" in q:
            return "свеча", "background"
        if "шкаф" in q:
            return "за шкафом", "room"
        if "окно" in q or "погод" in q:
            return "окно погода", "window"
        if "текст" in q or "бумаг" in q or "листк" in q:
            return "текст бумага", "document"
        if "полк" in q:
            return "верхняя полка", "shelf"
        if "двер" in q:
            return "за дверью", "door"
        if "стол" in q:
            return "стол предметы", "desk"
        if "стен" in q:
            return "стена", "background"

        if "задн" in q or "фон" in q or "background" in q:
            return "задний план", "background"
        if "коридор" in q or "corridor" in q:
            return "коридор", "corridor"
        if "одежд" in q or "одет" in q or "плать" in q or "костюм" in q or "шлем" in q or "wearing" in q:
            return "одежда и предметы", "attire"
        if "кто" in q or "человек" in q or "персонаж" in q or "девушк" in q or "парен" in q or "who" in q:
            return "персонажи в кадре", "foreground"
        if "экран" in q or "screen" in q or "кадр" in q or "frame" in q or "что видно" in q or "что происходит" in q:
            return "содержимое экрана", "full_frame"
        return q[:80], "full_frame"

    def should_refresh_vision(
        self,
        query: str,
        scene_state: SceneState | None = None,
        max_age_ms: float = 4000.0,
    ) -> tuple[bool, str, str]:
        """Decides whether to trigger an active Top-Down Visual Refresh to Qwen.

        Returns (should_refresh, target, reason).
        """
        if not self.is_visual_query(query):
            return False, "", "Not a visual query"

        target, region = self.extract_visual_target(query)
        if scene_state is None:
            return True, target, "No SceneState available; Top-Down inspection required"

        q_lower = query.lower()
        # Direct user visual queries always trigger a fresh top-down look
        # to ensure epistemic grounding on the current screen/frame
        if any(w in q_lower for w in ["посмотри", "взгляни", "глянь", "покажи", "что", "кто", "есть ли", "виден ли", "видно", "стоит ли", "сидит ли", "look at", "see now"]):
            return True, target, f"Direct interactive visual query for '{target}' in '{region}'"

        obs_status = scene_state.evaluate_observation_status(target, max_staleness_ms=max_age_ms)
        status = obs_status.get("status")

        if status == "observed_present":
            return False, target, f"Target '{target}' already observed with freshness {obs_status.get('freshness_ms')}ms"
        if status == "observed_absent":
            return False, target, f"Target '{target}' recently inspected and confirmed bounded absent"

        # status == "not_observed" or expired
        return True, target, f"Target '{target}' in '{region}' is not_observed; visual refresh required"

    def evaluate_salience(
        self,
        *,
        scene_state: SceneState,
        semantic_diff: dict[str, Any],
        user_query: str | None = None,
        speech_event: NarrativeSpeechEvent | None = None,
    ) -> tuple[float, str, str]:
        """Calculates salience score in [0.0, 1.0], topic key, and primary reason."""
        if user_query and user_query.strip():
            return 1.0, "user_query", "Direct user interactive query"

        # Check dialogue / speech events on screen
        sp = speech_event or scene_state.active_dialogue
        if sp and sp.text:
            text = sp.text.lower()
            # Narrative emotional or conflict triggers
            high_emotion_words = [
                "не пойду", "отец узнает", "лучшее платье", "девочк", "девчонк",
                "танц", "почему", "зачем", "ты что", "стой", "подожди", "слушаю",
            ]
            if any(w in text for w in high_emotion_words):
                return 0.85, f"dialogue_{sp.visual_identity_id or sp.audio_speaker_id or 'unknown'}", f"High narrative salience dialogue: '{sp.text}'"
            return 0.65, "dialogue_general", f"Dialogue turn: '{sp.text}'"

        # Check unlocalized presence of narrative character
        if semantic_diff.get("unlocalized_presences"):
            unloc = semantic_diff["unlocalized_presences"][0]
            traits = unloc.get("traits", {})
            return 0.70, "character_presence", f"VLM observed narrative presence: {traits.get('appearance', 'персонаж')}"

        # Check confirmed Re-ID hypothesis
        confirmed_hyp = [h for h in scene_state.hypotheses if h.status == "confirmed" and (scene_state.timestamp_ms - h.created_ms) < 2000.0]
        if confirmed_hyp:
            h = confirmed_hyp[0]
            return 0.75, f"reid_{h.target_track_id}", f"Re-ID continuity confirmed: {h.candidate_id} -> {h.target_track_id}"

        # Check newly added entities
        if semantic_diff.get("entities_added"):
            new_id = semantic_diff["entities_added"][0]
            ent = scene_state.entities.get(new_id)
            label = ent.label if ent else "объект"
            return 0.60, f"entity_added_{label}", f"New entity appeared in frame: {label}"

        # Check major spatial movement (>15% screen shift)
        if semantic_diff.get("entities_modified"):
            mod = semantic_diff["entities_modified"][0]
            if "movement" in mod.get("change", ""):
                # Spatial movement alone has low salience
                return 0.20, f"movement_{mod.get('track_id')}", f"Entity moved across frame: {mod.get('change')}"
            if "state" in mod.get("change", ""):
                return 0.50, f"state_{mod.get('track_id')}", f"State change: {mod.get('change')}"

        # Check spatial matrix dirty ratio
        if scene_state.spatial.dirty_ratio > 0.40:
            return 0.55, "scene_transition", f"Large visual shift (dirty_ratio={scene_state.spatial.dirty_ratio:.2f})"

        return 0.10, "idle", "Minor idle change"

    def arbitrate(
        self,
        *,
        scene_state: SceneState,
        semantic_diff: dict[str, Any],
        timestamp_sec: float,
        evidence_id: str = "",
        is_user_speaking: bool = False,
        user_query: str | None = None,
        speech_event: NarrativeSpeechEvent | None = None,
    ) -> PolicyDecision:
        """Arbitrates whether to speak, producing a PolicyDecision."""
        t_now = float(timestamp_sec)

        # 1. Interactive User Query (Highest Priority)
        if user_query and user_query.strip():
            context = {
                "user_query": user_query.strip(),
                "scene_id": scene_state.scene_id,
                "timestamp_sec": t_now,
                "entities": [e.to_dict() for e in scene_state.entities.values()],
                "active_dialogue": scene_state.active_dialogue.to_dict() if scene_state.active_dialogue else None,
                "unlocalized_presences": list(scene_state.unlocalized_presences[-3:]),
            }
            return PolicyDecision(
                should_speak=True,
                decision_type="interactive_answer",
                salience_score=1.0,
                evidence_id=evidence_id or f"query_{int(t_now * 1000)}",
                confidence=0.95,
                prompt_context=context,
                reason="User asked direct question; answering with current SceneState evidence",
                timestamp_sec=t_now,
            )

        # 2. Courtesy: Never interrupt active user speech
        if is_user_speaking:
            return PolicyDecision(
                should_speak=False,
                decision_type="suppressed_user_active",
                salience_score=0.0,
                evidence_id=evidence_id,
                reason="User is speaking; suppressing autonomous commentary",
                timestamp_sec=t_now,
            )

        # 3. Grounded evidence check
        if self.require_grounded_evidence and not evidence_id and not (speech_event and speech_event.text):
            return PolicyDecision(
                should_speak=False,
                decision_type="suppressed_ungrounded",
                salience_score=0.0,
                reason="No grounded visual/acoustic evidence_id available",
                timestamp_sec=t_now,
            )

        # 4. Salience evaluation
        salience, topic_key, salience_reason = self.evaluate_salience(
            scene_state=scene_state,
            semantic_diff=semantic_diff,
            user_query=user_query,
            speech_event=speech_event,
        )

        if salience < self.min_salience_threshold:
            return PolicyDecision(
                should_speak=False,
                decision_type="suppressed_low_salience",
                salience_score=salience,
                evidence_id=evidence_id,
                reason=f"Salience {salience:.2f} below threshold {self.min_salience_threshold:.2f} ({salience_reason})",
                timestamp_sec=t_now,
            )

        # 5. Anti-chatter cooldown check
        time_since_speech = t_now - self._last_spoken_time_sec
        if time_since_speech < self.commentary_cooldown_sec:
            return PolicyDecision(
                should_speak=False,
                decision_type="suppressed_cooldown",
                salience_score=salience,
                evidence_id=evidence_id,
                reason=f"In speech cooldown ({time_since_speech:.1f}s < {self.commentary_cooldown_sec:.1f}s)",
                timestamp_sec=t_now,
            )

        # 6. Anti-repetition check
        if self.is_topic_recent(topic_key, t_now):
            return PolicyDecision(
                should_speak=False,
                decision_type="suppressed_repetition",
                salience_score=salience,
                evidence_id=evidence_id,
                reason=f"Topic '{topic_key}' was commented on recently within {self.anti_repetition_window_sec}s",
                timestamp_sec=t_now,
            )

        # Passed all filters -> Approve autonomous grounded commentary
        context = {
            "topic": topic_key,
            "salience": round(salience, 3),
            "salience_reason": salience_reason,
            "scene_id": scene_state.scene_id,
            "timestamp_sec": t_now,
            "active_speech": speech_event.to_dict() if speech_event else (scene_state.active_dialogue.to_dict() if scene_state.active_dialogue else None),
            "entities": [e.to_dict() for e in scene_state.entities.values()],
            "unlocalized_presences": list(scene_state.unlocalized_presences[-2:]),
            "evidence_id": evidence_id,
        }

        # Identify character if applicable
        char_id = None
        if speech_event and speech_event.visual_identity_id:
            char_id = speech_event.visual_identity_id
        elif scene_state.active_dialogue and scene_state.active_dialogue.visual_identity_id:
            char_id = scene_state.active_dialogue.visual_identity_id

        return PolicyDecision(
            should_speak=True,
            decision_type="commentary",
            salience_score=salience,
            evidence_id=evidence_id,
            confidence=0.88,
            character_id=char_id,
            prompt_context=context,
            reason=f"Approved commentary: {salience_reason}",
            timestamp_sec=t_now,
        )
