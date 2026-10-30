"""Grounding and affordance lane: fuse UIA, OCR and screen regions.

The lane answers one question: which visible/semantic target does a spoken
request refer to, and is it safe to act on it right now? Candidates carry a
bbox, a role, a source and a bounded confidence. Actions are expressed as the
existing strict ``VisionActionPlan`` payload, so execution still goes through
``VisionPlanExecutor`` policy, freshness and postcondition checks.

Nothing here clicks by itself. A candidate below ``MIN_GROUNDING_CONFIDENCE``
or an observation without a live token cannot produce a plan.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .screen_adapter import verify_observation_token
from .vision import VisionActionPlan, VisionPlanError

MIN_GROUNDING_CONFIDENCE = 0.65
MAX_CANDIDATES = 64

# UIA roles that can own a click/focus target. Containers and documents are
# deliberately excluded from OCR fusion: they cover the whole window and would
# hide every text candidate below them.
_ACTIONABLE_ROLES = frozenset({
    "button", "text", "edit", "checkbox", "radiobutton", "tab", "tabitem",
    "listitem", "menuitem", "hyperlink", "combobox", "slider", "treeitem",
    "splitbutton", "calendar", "dataitem", "headeritem", "image",
})
_COORDINATE_ACTIONS = frozenset({"click", "double_click", "right_click", "middle_click", "move"})
_UIA_ACTIONS = frozenset({"click", "focus", "set_value"})

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(str(text or "").casefold().replace("ё", "е")))


def _role_name(control_type: str) -> str:
    value = str(control_type or "").strip().casefold()
    return value[: -len("control")] if value.endswith("control") else value


@dataclass(frozen=True)
class GroundingCandidate:
    source: str
    role: str
    label: str
    bbox: tuple[int, int, int, int]
    confidence: float
    element_ref: str | None = None
    element_sha256: str | None = None

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bbox
        return ((left + right) // 2, (top + bottom) // 2)

    @property
    def actionable(self) -> bool:
        return self.role in _ACTIONABLE_ROLES

    def to_dict(self) -> dict[str, Any]:
        left, top, right, bottom = self.bbox
        payload: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "role": self.role,
            "label": self.label,
            "bbox": [left, top, right, bottom],
            "center": list(self.center),
            "confidence": round(self.confidence, 4),
            "actionable": self.actionable,
        }
        if self.element_ref is not None:
            payload["element_ref"] = self.element_ref
            payload["element_sha256"] = self.element_sha256
        return payload

    @property
    def candidate_id(self) -> str:
        raw = f"{self.source}|{self.role}|{self.label}|{self.bbox}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:12]


def _valid_bbox(value: Any, *, max_edge: int = 100_000) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        return None
    left, top, right, bottom = value
    if left < -max_edge or top < -max_edge or right > max_edge or bottom > max_edge:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _bbox_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


class GroundingService:
    """Build, rank and plan against grounded candidates for the focused window."""

    def __init__(
        self,
        *,
        uia: Any | None = None,
        screen: Any | None = None,
        min_confidence: float = MIN_GROUNDING_CONFIDENCE,
    ) -> None:
        self.uia = uia
        self.screen = screen
        self.min_confidence = max(0.0, min(float(min_confidence), 1.0))

    def observe(self, *, min_confidence: float | None = None) -> dict[str, Any]:
        gate = self.min_confidence if min_confidence is None else float(min_confidence)
        uia_state = self._observe_uia()
        screen_state = self._observe_screen()
        candidates = self._uia_candidates(uia_state)
        candidates.extend(self._ocr_candidates(screen_state))
        candidates = self._fuse(candidates)
        candidates = [item for item in candidates if item.confidence >= 0.0 and item.label]
        candidates.sort(key=lambda item: (item.confidence, item.label), reverse=True)
        candidates = candidates[:MAX_CANDIDATES]
        token = screen_state.get("observation_token") if isinstance(screen_state, Mapping) else None
        digest = screen_state.get("observation_digest") if isinstance(screen_state, Mapping) else None
        fresh = bool(token and digest and verify_observation_token(str(token)) is not None)
        return {
            "status": "verified" if fresh else "unverified",
            "candidates": [item.to_dict() for item in candidates],
            "candidate_count": len(candidates),
            "observation_token": token if fresh else None,
            "observation_digest": digest if fresh else None,
            "min_confidence": round(gate, 4),
            "uia_status": uia_state.get("status") if isinstance(uia_state, Mapping) else "degraded",
            "ocr_items": len(screen_state.get("ocr") or []) if isinstance(screen_state, Mapping) else 0,
            "window": screen_state.get("window") if isinstance(screen_state, Mapping) else None,
            "persisted": False,
        }

    def find(
        self,
        query: str,
        *,
        observation: Mapping[str, Any] | None = None,
        min_confidence: float | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        gate = self.min_confidence if min_confidence is None else float(min_confidence)
        state = observation if isinstance(observation, Mapping) else self.observe()
        raw_query = _normalize(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in state.get("candidates") or []:
            if not isinstance(item, Mapping):
                continue
            confidence = float(item.get("confidence") or 0.0)
            if confidence < gate:
                continue
            text_score = _text_score(raw_query, str(item.get("label") or ""))
            if text_score <= 0:
                continue
            score = 0.65 * confidence + 0.35 * text_score
            enriched = dict(item)
            enriched["match_score"] = round(score, 4)
            enriched["text_score"] = round(text_score, 4)
            ranked.append((score, enriched))
        ranked.sort(key=lambda pair: (pair[0], float(pair[1].get("confidence") or 0.0)), reverse=True)
        return [item for _, item in ranked[: max(1, min(int(limit), 20))]]

    def plan(
        self,
        action: str,
        query: str,
        *,
        observation: Mapping[str, Any] | None = None,
        value: str | None = None,
        postcondition: Mapping[str, Any] | None = None,
        min_confidence: float | None = None,
    ) -> dict[str, Any]:
        """Return ``{status: ok, plan: ...}`` or a bounded denial reason."""
        operation = str(action or "").strip().casefold()
        gate = self.min_confidence if min_confidence is None else float(min_confidence)
        state = observation if isinstance(observation, Mapping) else self.observe()
        token = state.get("observation_token")
        digest = state.get("observation_digest")
        if not token or not digest:
            return {"status": "denied", "reason": "fresh_observation_required"}
        claims = verify_observation_token(str(token))
        if claims is None or str(claims.get("digest") or "").casefold() != str(digest).casefold():
            return {"status": "denied", "reason": "stale_observation"}
        matches = self.find(query, observation=state, min_confidence=0.0, limit=1)
        if not matches:
            return {"status": "denied", "reason": "no_grounded_candidate"}
        top = matches[0]
        confidence = float(top.get("confidence") or 0.0)
        if confidence < gate:
            return {
                "status": "denied",
                "reason": "low_confidence",
                "confidence": round(confidence, 4),
                "required": round(gate, 4),
            }
        target = self._target(top, operation, str(token))
        if target is None:
            return {"status": "denied", "reason": "candidate_not_actionable_for_operation"}
        action_payload: dict[str, Any] = {"operation": operation, "target": target}
        if value is not None:
            action_payload["value"] = str(value)[:5000]
        payload = {
            "schema_version": 1,
            "observation_token": str(token),
            "observation_digest": str(digest),
            "actions": [action_payload],
            "postcondition": dict(postcondition or {"name": "action_result", "timeout_ms": 2500}),
        }
        try:
            VisionActionPlan.from_dict(payload)
        except VisionPlanError as exc:
            return {"status": "denied", "reason": str(exc)[:240]}
        return {"status": "ok", "plan": payload, "candidate": top}

    # ------------------------------------------------------------------
    # observation adapters
    # ------------------------------------------------------------------

    def _observe_uia(self) -> Mapping[str, Any]:
        if self.uia is None:
            return {"status": "degraded", "reason": "uia_unavailable"}
        try:
            state = self.uia.observe()
        except Exception as exc:  # noqa: BLE001 - observation must stay bounded
            return {"status": "degraded", "reason": "uia_observation_failed", "detail": str(exc)[:200]}
        return state if isinstance(state, Mapping) else {"status": "degraded", "reason": "uia_invalid_result"}

    def _observe_screen(self) -> Mapping[str, Any]:
        if self.screen is None:
            return {"status": "degraded", "reason": "screen_unavailable"}
        try:
            state = self.screen.observe(include_image=True)
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "reason": "screen_observation_failed", "detail": str(exc)[:200]}
        return state if isinstance(state, Mapping) else {"status": "degraded", "reason": "screen_invalid_result"}

    def _uia_candidates(self, state: Mapping[str, Any]) -> list[GroundingCandidate]:
        if state.get("status") != "verified":
            return []
        result: list[GroundingCandidate] = []
        for element in state.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            bbox = _valid_bbox(element.get("bounds"))
            if bbox is None:
                continue
            role = _role_name(str(element.get("control_type") or ""))
            label = str(element.get("name") or element.get("automation_id") or "").strip()[:240]
            if not label:
                continue
            ref = element.get("element_ref")
            sha = element.get("element_sha256")
            confidence = 0.98 if role in _ACTIONABLE_ROLES else 0.75
            result.append(
                GroundingCandidate(
                    source="uia",
                    role=role or "unknown",
                    label=label,
                    bbox=bbox,
                    confidence=confidence,
                    element_ref=str(ref) if isinstance(ref, str) and isinstance(sha, str) else None,
                    element_sha256=str(sha) if isinstance(ref, str) and isinstance(sha, str) else None,
                )
            )
        return result

    def _ocr_candidates(self, state: Mapping[str, Any]) -> list[GroundingCandidate]:
        if state.get("status") != "verified":
            return []
        window = state.get("window")
        bounds = _valid_bbox(window.get("bounds")) if isinstance(window, Mapping) else None
        if bounds is None:
            return []
        scale = state.get("coordinate_scale")
        scale_x = scale_y = 1.0
        if isinstance(scale, Mapping):
            try:
                scale_x = float(scale.get("x") or 1.0)
                scale_y = float(scale.get("y") or 1.0)
            except (TypeError, ValueError):
                scale_x = scale_y = 1.0
        left, top, _, _ = bounds
        result: list[GroundingCandidate] = []
        for item in state.get("ocr") or []:
            if not isinstance(item, Mapping):
                continue
            raw_bbox = _valid_bbox(item.get("bbox"))
            text = str(item.get("text") or "").strip()[:240]
            if raw_bbox is None or not text:
                continue
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence > 1.0:
                confidence /= 100.0
            confidence = max(0.0, min(confidence, 1.0))
            translated = (
                left + round(raw_bbox[0] * scale_x),
                top + round(raw_bbox[1] * scale_y),
                left + round(raw_bbox[2] * scale_x),
                top + round(raw_bbox[3] * scale_y),
            )
            result.append(
                GroundingCandidate(
                    source="ocr",
                    role="text",
                    label=text,
                    bbox=translated,
                    confidence=confidence,
                )
            )
        return result

    @staticmethod
    def _fuse(candidates: list[GroundingCandidate]) -> list[GroundingCandidate]:
        """Prefer semantic UIA targets over OCR duplicates inside their bounds."""
        actionable = [item for item in candidates if item.source == "uia" and item.actionable]
        kept: list[GroundingCandidate] = []
        for item in candidates:
            if item.source == "ocr" and any(_bbox_contains(owner.bbox, item.bbox) for owner in actionable):
                continue
            kept.append(item)
        return kept

    @staticmethod
    def _target(candidate: Mapping[str, Any], operation: str, token: str) -> dict[str, Any] | None:
        ref = candidate.get("element_ref")
        sha = candidate.get("element_sha256")
        if (
            operation in _UIA_ACTIONS
            and isinstance(ref, str)
            and isinstance(sha, str)
            and candidate.get("role") in _ACTIONABLE_ROLES
        ):
            return {"element_ref": ref, "element_sha256": sha, "observation_token": token}
        center = candidate.get("center")
        if operation in _COORDINATE_ACTIONS or operation in {"type", "hotkey"}:
            if isinstance(center, (list, tuple)) and len(center) == 2:
                return {
                    "x": int(center[0]),
                    "y": int(center[1]),
                    "coordinate_space": "screen",
                    "observation_token": token,
                }
        return None


def _text_score(query: str, label: str) -> float:
    if not query:
        return 0.0
    normalized = _normalize(label)
    if not normalized:
        return 0.0
    if query == normalized:
        return 1.0
    if query in normalized:
        return 0.9
    if len(normalized) >= 3 and normalized in query:
        return 0.7
    query_words = set(query.split())
    label_words = set(normalized.split())
    if not query_words:
        return 0.0
    overlap = len(query_words & label_words) / len(query_words)
    return round(0.6 * overlap, 4) if overlap else 0.0


__all__ = [
    "MIN_GROUNDING_CONFIDENCE",
    "GroundingCandidate",
    "GroundingService",
]
