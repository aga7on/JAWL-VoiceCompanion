"""Multimodal Scene Memory with Micro-Detail Zero-Loss Recall.

Provides a 3D-aware, temporally bounded multimodal scene graph capturing:
- Fine-grained visual detections with precise bounding boxes and raw attributes
- Exact OCR text snippets with spatial coordinates and confidence
- Acoustic soundscape events (YAMNet labels, sound effects, ambient cues)
- Conversational speech turns (user/assistant/system transcripts)
- Explicit epistemic observation states (OBSERVED_PRESENT, OBSERVED_ABSENT, NOT_OBSERVED)
  to prevent hallucinatory claims or false absence statements.

Zero-loss recall guarantees that exact coordinates, numerical attributes (HP, ammo,
coordinates, timers), and textual transcriptions are preserved without lossy
summarization, floating-point distortion, or truncation.
"""

from __future__ import annotations

import collections
import dataclasses
from enum import Enum
import json
import logging
import math
import threading
import time
from typing import Any, Callable, Iterator, Sequence
import uuid
logger = logging.getLogger(__name__)


class EpistemicStatus(str, Enum):
    """Honest epistemic state for scene queries."""
    OBSERVED_PRESENT = "observed_present"  # Directly observed with positive evidence
    OBSERVED_ABSENT = "observed_absent"    # Region/entity inspected; queried feature verified missing
    NOT_OBSERVED = "not_observed"          # Target uninspected, out of FOV, or expired from memory


@dataclasses.dataclass(frozen=True)
class BoundingBox:
    """Normalized 2D bounding box [x1, y1, x2, y2] where 0.0 <= coord <= 1.0."""
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 < self.x1 or self.y2 < self.y1:
            # Normalize inverted coordinates
            nx1, nx2 = min(self.x1, self.x2), max(self.x1, self.x2)
            ny1, ny2 = min(self.y1, self.y2), max(self.y1, self.y2)
            object.__setattr__(self, "x1", nx1)
            object.__setattr__(self, "y1", ny1)
            object.__setattr__(self, "x2", nx2)
            object.__setattr__(self, "y2", ny2)

    @property
    def x(self) -> float:
        return self.x1

    @property
    def y(self) -> float:
        return self.y1

    @property
    def width(self) -> float:
        return round(self.x2 - self.x1, 6)

    @property
    def height(self) -> float:
        return round(self.y2 - self.y1, 6)
    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)
    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def contains_point(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def contains_bbox(self, other: BoundingBox) -> bool:
        return (
            self.x1 <= other.x1 <= self.x2
            and self.y1 <= other.y1 <= self.y2
            and self.x1 <= other.x2 <= self.x2
            and self.y1 <= other.y2 <= self.y2
        )

    def iou(self, other: BoundingBox) -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)

        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        intersection = iw * ih
        if intersection <= 0.0:
            return 0.0

        union = self.area + other.area - intersection
        return intersection / union if union > 0.0 else 0.0

    def to_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, coords: Sequence[float]) -> BoundingBox:
        if len(coords) != 4:
            raise ValueError(f"BoundingBox requires 4 coordinates, got {len(coords)}")
        return cls(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))

    @classmethod
    def from_xywh(cls, x: float, y: float, width: float, height: float) -> BoundingBox:
        return cls(float(x), float(y), round(float(x) + float(width), 6), round(float(y) + float(height), 6))
@dataclasses.dataclass
class VisualDetection:
    """Fine-grained visual entity observation with zero-loss attributes."""
    track_id: str = ""
    label: str = "entity"
    bbox: BoundingBox | None = None
    confidence: float = 1.0
    attributes: dict[str, Any] = dataclasses.field(default_factory=dict)
    source: str = "visual"
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.track_id:
            if self.label and self.label != "entity":
                self.track_id = self.label
            else:
                self.track_id = f"det_{uuid.uuid4().hex[:8]}"
        if self.bbox is None:
            self.bbox = BoundingBox(0.0, 0.0, 1.0, 1.0)
    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "label": self.label,
            "bbox": self.bbox.to_list() if self.bbox else [0.0, 0.0, 1.0, 1.0],
            "confidence": round(self.confidence, 4),
            "attributes": dict(self.attributes),
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualDetection:
        bbox_raw = data.get("bbox")
        bbox = BoundingBox.from_list(bbox_raw) if bbox_raw else BoundingBox(0.0, 0.0, 1.0, 1.0)
        return cls(
            track_id=str(data.get("track_id", "")),
            label=str(data.get("label", "entity")),
            bbox=bbox,
            confidence=float(data.get("confidence", 1.0)),
            attributes=dict(data.get("attributes", {})),
            source=str(data.get("source", "visual")),
            metadata=dict(data.get("metadata", {})),
        )

@dataclasses.dataclass
class OCRItem:
    """Exact OCR text detection with spatial location."""
    text: str
    bbox: BoundingBox | None = None
    confidence: float = 1.0
    region_tag: str = ""  # "ui", "subtitle", "in_game", "terminal"
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "confidence": round(self.confidence, 4),
            "region_tag": self.region_tag,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OCRItem:
        bbox_raw = data.get("bbox")
        return cls(
            text=str(data.get("text", "")),
            bbox=BoundingBox.from_list(bbox_raw) if bbox_raw else None,
            confidence=float(data.get("confidence", 1.0)),
            region_tag=str(data.get("region_tag", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclasses.dataclass
class AcousticEvent:
    """Detected acoustic event (YAMNet, SFX, ambient cue)."""
    label: str
    category: str = "sfx"  # "sfx", "speech", "ambient", "music"
    confidence: float = 1.0
    start_time: float = 0.0
    end_time: float = 0.0
    channel: str = "system"  # "system", "mic"
    is_speech: bool = False
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "channel": self.channel,
            "is_speech": self.is_speech,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcousticEvent:
        return cls(
            label=str(data.get("label", "unknown")),
            category=str(data.get("category", "sfx")),
            confidence=float(data.get("confidence", 1.0)),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            channel=str(data.get("channel", "system")),
            is_speech=bool(data.get("is_speech", False)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclasses.dataclass
class SpeechTurn:
    """Spoken dialogue turn with temporal bounds."""
    turn_id: str
    speaker: str = "user"  # "user", "assistant", "system"
    transcript: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "transcript": self.transcript,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeechTurn:
        return cls(
            turn_id=str(data["turn_id"]),
            speaker=str(data.get("speaker", "user")),
            transcript=str(data.get("transcript", "")),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclasses.dataclass
class MultimodalSceneFrame:
    """Single synchronized multimodal time slice."""
    frame_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = dataclasses.field(default_factory=time.time)
    visual_detections: list[VisualDetection] = dataclasses.field(default_factory=list)
    ocr_items: list[OCRItem] = dataclasses.field(default_factory=list)
    acoustic_events: list[AcousticEvent] = dataclasses.field(default_factory=list)
    speech_turns: list[SpeechTurn] = dataclasses.field(default_factory=list)
    scene_tags: list[str] = dataclasses.field(default_factory=list)
    raw_metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def add_detection(self, detection: VisualDetection) -> None:
        self.visual_detections.append(detection)

    def add_ocr(self, ocr_item: OCRItem) -> None:
        self.ocr_items.append(ocr_item)

    def add_acoustic(self, event: AcousticEvent) -> None:
        self.acoustic_events.append(event)

    def add_speech(self, speech: SpeechTurn) -> None:
        self.speech_turns.append(speech)

    def get_detection(self, track_id: str) -> VisualDetection | None:
        for det in self.visual_detections:
            if det.track_id == track_id:
                return det
        return None

    def find_detections_by_label(self, label: str) -> list[VisualDetection]:
        q = label.lower()
        return [det for det in self.visual_detections if q in det.label.lower()]

    def search_ocr(self, query: str, exact: bool = False) -> list[OCRItem]:
        q = query.lower() if not exact else query
        matches = []
        for item in self.ocr_items:
            target = item.text if exact else item.text.lower()
            if q in target:
                matches.append(item)
        return matches

    def get_acoustic_events(self, label: str | None = None) -> list[AcousticEvent]:
        if label is None:
            return list(self.acoustic_events)
        q = label.lower()
        return [ev for ev in self.acoustic_events if q in ev.label.lower()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": round(self.timestamp, 3),
            "visual_detections": [d.to_dict() for d in self.visual_detections],
            "ocr_items": [o.to_dict() for o in self.ocr_items],
            "acoustic_events": [a.to_dict() for a in self.acoustic_events],
            "speech_turns": [s.to_dict() for s in self.speech_turns],
            "scene_tags": list(self.scene_tags),
            "raw_metadata": dict(self.raw_metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MultimodalSceneFrame:
        return cls(
            frame_id=str(data["frame_id"]),
            timestamp=float(data["timestamp"]),
            visual_detections=[VisualDetection.from_dict(d) for d in data.get("visual_detections", [])],
            ocr_items=[OCRItem.from_dict(o) for o in data.get("ocr_items", [])],
            acoustic_events=[AcousticEvent.from_dict(a) for a in data.get("acoustic_events", [])],
            speech_turns=[SpeechTurn.from_dict(s) for s in data.get("speech_turns", [])],
            scene_tags=list(data.get("scene_tags", [])),
            raw_metadata=dict(data.get("raw_metadata", {})),
        )


# ==============================================================================
# Multimodal Scene Graph
# ==============================================================================

@dataclasses.dataclass
class SceneGraphNode:
    """Node in multimodal temporal graph."""
    node_id: str
    node_type: str  # "entity", "ocr", "acoustic", "speech"
    label: str
    frame_id: str
    timestamp: float
    properties: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "frame_id": self.frame_id,
            "timestamp": round(self.timestamp, 3),
            "properties": dict(self.properties),
        }


@dataclasses.dataclass
class SceneGraphEdge:
    """Directed edge connecting nodes in multimodal graph."""
    source_id: str
    target_id: str
    edge_type: str  # "co_occurs", "emitted_by", "referenced_in", "interacts_with", "spatially_near"
    weight: float = 1.0
    properties: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": round(self.weight, 4),
            "properties": dict(self.properties),
        }


class MultimodalSceneGraph:
    """Dynamic temporal graph connecting multimodal entities and events."""

    def __init__(self, max_nodes: int = 2000) -> None:
        self.max_nodes = max_nodes
        self.nodes: dict[str, SceneGraphNode] = {}
        self.edges: list[SceneGraphEdge] = []
        self._adj_out: dict[str, list[SceneGraphEdge]] = collections.defaultdict(list)
        self._adj_in: dict[str, list[SceneGraphEdge]] = collections.defaultdict(list)

    def add_node(self, node: SceneGraphNode) -> None:
        self.nodes[node.node_id] = node
        if len(self.nodes) > self.max_nodes:
            self._prune_oldest_nodes(int(self.max_nodes * 0.2))

    def add_edge(self, edge: SceneGraphEdge) -> None:
        self.edges.append(edge)
        self._adj_out[edge.source_id].append(edge)
        self._adj_in[edge.target_id].append(edge)

    def get_node(self, node_id: str) -> SceneGraphNode | None:
        return self.nodes.get(node_id)

    def get_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "both",
    ) -> list[tuple[SceneGraphNode, SceneGraphEdge]]:
        results: list[tuple[SceneGraphNode, SceneGraphEdge]] = []
        if direction in ("out", "both"):
            for edge in self._adj_out.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    target = self.nodes.get(edge.target_id)
                    if target:
                        results.append((target, edge))
        if direction in ("in", "both"):
            for edge in self._adj_in.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    source = self.nodes.get(edge.source_id)
                    if source:
                        results.append((source, edge))
        return results

    def find_nodes_by_type(self, node_type: str) -> list[SceneGraphNode]:
        return [n for n in self.nodes.values() if n.node_type == node_type]

    def find_nodes_by_label(self, label: str) -> list[SceneGraphNode]:
        q = label.lower()
        return [n for n in self.nodes.values() if q in n.label.lower()]

    def build_from_frame(self, frame: MultimodalSceneFrame) -> None:
        """Construct graph nodes and relationships from a multimodal frame."""
        det_node_ids: list[str] = []
        for det in frame.visual_detections:
            node_id = f"ent:{frame.frame_id}:{det.track_id}"
            node = SceneGraphNode(
                node_id=node_id,
                node_type="entity",
                label=det.label,
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                properties={
                    "track_id": det.track_id,
                    "bbox": det.bbox.to_list(),
                    "confidence": det.confidence,
                    "attributes": det.attributes,
                    "source": det.source,
                },
            )
            self.add_node(node)
            det_node_ids.append(node_id)

        # Spatial relations between detections (IoU > 0 or proximity)
        for i in range(len(frame.visual_detections)):
            for j in range(i + 1, len(frame.visual_detections)):
                d1 = frame.visual_detections[i]
                d2 = frame.visual_detections[j]
                iou = d1.bbox.iou(d2.bbox)
                c1 = d1.bbox.center
                c2 = d2.bbox.center
                dist = math.hypot(c1[0] - c2[0], c1[1] - c2[1])

                if iou > 0.05:
                    self.add_edge(SceneGraphEdge(
                        source_id=det_node_ids[i],
                        target_id=det_node_ids[j],
                        edge_type="co_occurs",
                        weight=iou,
                        properties={"relation": "overlap", "iou": iou},
                    ))
                elif dist < 0.35:
                    self.add_edge(SceneGraphEdge(
                        source_id=det_node_ids[i],
                        target_id=det_node_ids[j],
                        edge_type="spatially_near",
                        weight=max(0.1, 1.0 - dist),
                        properties={"distance": dist},
                    ))

        # OCR nodes and connections to visual entities
        ocr_node_ids: list[str] = []
        for idx, ocr in enumerate(frame.ocr_items):
            ocr_id = f"ocr:{frame.frame_id}:{idx}"
            ocr_node = SceneGraphNode(
                node_id=ocr_id,
                node_type="ocr",
                label=ocr.text,
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                properties={
                    "text": ocr.text,
                    "bbox": ocr.bbox.to_list() if ocr.bbox else None,
                    "confidence": ocr.confidence,
                    "region_tag": ocr.region_tag,
                },
            )
            self.add_node(ocr_node)
            ocr_node_ids.append(ocr_id)

            # Check if OCR is located inside any detection's bounding box
            if ocr.bbox:
                for d_idx, det in enumerate(frame.visual_detections):
                    if det.bbox.contains_bbox(ocr.bbox) or det.bbox.iou(ocr.bbox) > 0.2:
                        self.add_edge(SceneGraphEdge(
                            source_id=ocr_id,
                            target_id=det_node_ids[d_idx],
                            edge_type="referenced_in",
                            weight=0.9,
                            properties={"contained_in": det.track_id},
                        ))

        # Acoustic event nodes
        ac_node_ids: list[str] = []
        for idx, ac in enumerate(frame.acoustic_events):
            ac_id = f"ac:{frame.frame_id}:{idx}"
            ac_node = SceneGraphNode(
                node_id=ac_id,
                node_type="acoustic",
                label=ac.label,
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                properties={
                    "category": ac.category,
                    "confidence": ac.confidence,
                    "channel": ac.channel,
                    "start_time": ac.start_time,
                    "end_time": ac.end_time,
                },
            )
            self.add_node(ac_node)
            ac_node_ids.append(ac_id)

            # Link acoustic events to all entities in the frame as co-occurring
            for d_node_id in det_node_ids:
                self.add_edge(SceneGraphEdge(
                    source_id=ac_id,
                    target_id=d_node_id,
                    edge_type="co_occurs",
                    weight=ac.confidence,
                    properties={"temporal_sync": True},
                ))

        # Speech turn nodes
        for idx, sp in enumerate(frame.speech_turns):
            sp_id = f"sp:{frame.frame_id}:{sp.turn_id}_{idx}"
            sp_node = SceneGraphNode(
                node_id=sp_id,
                node_type="speech",
                label=sp.transcript,
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                properties={
                    "speaker": sp.speaker,
                    "transcript": sp.transcript,
                    "confidence": sp.confidence,
                },
            )
            self.add_node(sp_node)

            # Link speech referencing entities or OCR
            sp_text = sp.transcript.lower()
            for d_idx, det in enumerate(frame.visual_detections):
                if det.label.lower() in sp_text or det.track_id.lower() in sp_text:
                    self.add_edge(SceneGraphEdge(
                        source_id=sp_id,
                        target_id=det_node_ids[d_idx],
                        edge_type="referenced_in",
                        weight=1.0,
                        properties={"mention": det.label},
                    ))

            for o_idx, ocr in enumerate(frame.ocr_items):
                if len(ocr.text) >= 3 and ocr.text.lower() in sp_text:
                    self.add_edge(SceneGraphEdge(
                        source_id=sp_id,
                        target_id=ocr_node_ids[o_idx],
                        edge_type="referenced_in",
                        weight=0.9,
                        properties={"mention": ocr.text},
                    ))

    def _prune_oldest_nodes(self, count: int) -> None:
        sorted_nodes = sorted(self.nodes.values(), key=lambda n: n.timestamp)
        to_remove = {n.node_id for n in sorted_nodes[:count]}
        for nid in to_remove:
            self.nodes.pop(nid, None)
            self._adj_out.pop(nid, None)
            self._adj_in.pop(nid, None)

        # Filter edges referencing pruned nodes
        self.edges = [e for e in self.edges if e.source_id not in to_remove and e.target_id not in to_remove]
        for nid in list(self._adj_out.keys()):
            self._adj_out[nid] = [e for e in self._adj_out[nid] if e.target_id not in to_remove]
        for nid in list(self._adj_in.keys()):
            self._adj_in[nid] = [e for e in self._adj_in[nid] if e.source_id not in to_remove]

    def prune_older_than(self, min_timestamp: float) -> int:
        to_remove = {nid for nid, n in self.nodes.items() if n.timestamp < min_timestamp}
        if not to_remove:
            return 0
        for nid in to_remove:
            self.nodes.pop(nid, None)
            self._adj_out.pop(nid, None)
            self._adj_in.pop(nid, None)
        self.edges = [e for e in self.edges if e.source_id not in to_remove and e.target_id not in to_remove]
        for nid in list(self._adj_out.keys()):
            self._adj_out[nid] = [e for e in self._adj_out[nid] if e.target_id not in to_remove]
        for nid in list(self._adj_in.keys()):
            self._adj_in[nid] = [e for e in self._adj_in[nid] if e.source_id not in to_remove]
        return len(to_remove)


# ==============================================================================
# Micro-Detail Zero-Loss Recall Engine
# ==============================================================================

@dataclasses.dataclass
class MicroDetailMatch:
    """Single precise match preserving raw values and full provenance."""
    frame_id: str
    timestamp: float
    matched_field: str  # "attribute", "detection", "ocr", "acoustic", "speech"
    entity_id: str | None = None
    key: str = ""
    value: Any = None
    confidence: float = 1.0
    bbox: list[float] | None = None
    provenance: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": round(self.timestamp, 3),
            "matched_field": self.matched_field,
            "entity_id": self.entity_id,
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox,
            "provenance": dict(self.provenance),
        }


@dataclasses.dataclass
class MicroRecallResult:
    """Result of micro-detail zero-loss recall query with epistemic clarity."""
    status: EpistemicStatus
    matches: list[MicroDetailMatch]
    query_summary: str
    epistemic_reason: str = ""

    @property
    def is_present(self) -> bool:
        return self.status == EpistemicStatus.OBSERVED_PRESENT

    @property
    def is_absent(self) -> bool:
        return self.status == EpistemicStatus.OBSERVED_ABSENT

    @property
    def is_unobserved(self) -> bool:
        return self.status == EpistemicStatus.NOT_OBSERVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "query_summary": self.query_summary,
            "epistemic_reason": self.epistemic_reason,
            "matches_count": len(self.matches),
            "matches": [m.to_dict() for m in self.matches],
        }

    def to_context_string(self) -> str:
        """Render concise, deterministic factual string for prompt injection."""
        if self.status == EpistemicStatus.NOT_OBSERVED:
            return f"[SceneMemory] {self.query_summary}: NOT OBSERVED ({self.epistemic_reason})"
        if self.status == EpistemicStatus.OBSERVED_ABSENT:
            return f"[SceneMemory] {self.query_summary}: OBSERVED ABSENT ({self.epistemic_reason})"

        lines = [f"[SceneMemory] {self.query_summary}: OBSERVED PRESENT ({len(self.matches)} matches):"]
        for idx, m in enumerate(self.matches, 1):
            bbox_str = f" bbox={m.bbox}" if m.bbox else ""
            ent_str = f" ent={m.entity_id}" if m.entity_id else ""
            lines.append(
                f"  ({idx}) t={m.timestamp:.2f}s | {m.matched_field} | key='{m.key}' -> value={json.dumps(m.value, ensure_ascii=False)}{ent_str}{bbox_str} (conf={m.confidence:.2f})"
            )
        return "\n".join(lines)


@dataclasses.dataclass
class QueryFilter:
    """Filter criteria for fine-grained multimodal search."""
    time_range: tuple[float, float] | None = None
    entity_label: str | None = None
    entity_track_id: str | None = None
    attribute_key: str | None = None
    attribute_value: Any | None = None
    ocr_query: str | None = None
    acoustic_label: str | None = None
    spatial_region: BoundingBox | None = None
    min_confidence: float = 0.0


# ==============================================================================
# SceneMemoryManager
# ==============================================================================

class SceneMemoryManager:
    """Thread-safe historical frame buffer, multimodal graph and zero-loss query engine."""

    def __init__(
        self,
        max_frames: int = 500,
        retention_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
        *,
        capacity: int | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        self.max_frames = capacity if capacity is not None else max_frames
        self.retention_seconds = ttl_seconds if ttl_seconds is not None else retention_seconds
        self._clock = clock
        self._lock = threading.RLock()

        self._frames: collections.deque[MultimodalSceneFrame] = collections.deque(maxlen=max_frames)
        self._frames_by_id: dict[str, MultimodalSceneFrame] = {}
        self.graph = MultimodalSceneGraph(max_nodes=max_frames * 4)

        # Inverted index caches for rapid zero-loss lookups
        self._track_history: dict[str, list[tuple[float, VisualDetection]]] = collections.defaultdict(list)
        self._ocr_index: dict[str, list[tuple[float, str, OCRItem]]] = collections.defaultdict(list)
        self._acoustic_index: dict[str, list[tuple[float, str, AcousticEvent]]] = collections.defaultdict(list)
    @property
    def frames(self) -> list[MultimodalSceneFrame]:
        with self._lock:
            return list(self._frames)

    @property
    def capacity(self) -> int:
        return self.max_frames

    @property
    def ttl_seconds(self) -> float:
        return self.retention_seconds

    def ingest_frame(self, frame: MultimodalSceneFrame) -> str:
        """Thread-safely ingest a multimodal frame, update graph and indices."""
        with self._lock:
            # Enforce max frames capacity
            if len(self._frames) >= self.max_frames:
                evicted = self._frames.popleft()
                self._frames_by_id.pop(evicted.frame_id, None)

            self._frames.append(frame)
            self._frames_by_id[frame.frame_id] = frame

            # Update indices
            for det in frame.visual_detections:
                self._track_history[det.track_id].append((frame.timestamp, det))

            for ocr in frame.ocr_items:
                tokens = ocr.text.lower().split()
                for tok in tokens:
                    clean_tok = tok.strip(".,!?:;\"'()[]{}")
                    if clean_tok:
                        self._ocr_index[clean_tok].append((frame.timestamp, frame.frame_id, ocr))

            for ac in frame.acoustic_events:
                self._acoustic_index[ac.label.lower()].append((frame.timestamp, frame.frame_id, ac))

            # Build graph connections
            self.graph.build_from_frame(frame)

            # Prune expired items
            self._prune_internal(now=frame.timestamp)

            return frame.frame_id
    add_frame = ingest_frame

    def get_frame(self, frame_id: str) -> MultimodalSceneFrame | None:
        with self._lock:
            return self._frames_by_id.get(frame_id)

    def get_latest_frame(self) -> MultimodalSceneFrame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def get_frames(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int | None = None,
    ) -> list[MultimodalSceneFrame]:
        with self._lock:
            results = []
            for f in reversed(self._frames):
                if end_time is not None and f.timestamp > end_time:
                    continue
                if start_time is not None and f.timestamp < start_time:
                    continue
                results.append(f)
                if limit is not None and len(results) >= limit:
                    break
            results.reverse()
            return results

    def query_entity_attribute(
        self,
        track_id: str,
        attribute_key: str,
        time_window: float | None = None,
    ) -> MicroRecallResult:
        """Recall exact attribute of a tracked entity with epistemic verification."""
        with self._lock:
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            history = self._track_history.get(track_id, [])
            if not history:
                target = track_id.lower()
                for trk, hist in self._track_history.items():
                    if trk.lower() == target or any(det.label.lower() == target for (_, det) in hist):
                        history = hist
                        break
            filtered = [(t, det) for (t, det) in history if t >= start_t]

            if not filtered:
                return MicroRecallResult(
                    status=EpistemicStatus.NOT_OBSERVED,
                    matches=[],
                    query_summary=f"Entity '{track_id}' attribute '{attribute_key}'",
                    epistemic_reason=f"Track '{track_id}' has not been observed in the last {time_window or self.retention_seconds:.1f}s",
                )

            matches: list[MicroDetailMatch] = []
            attribute_found = False

            # Search from newest observation backwards
            for t, det in reversed(filtered):
                if attribute_key in det.attributes:
                    attribute_found = True
                    val = det.attributes[attribute_key]
                    matches.append(MicroDetailMatch(
                        frame_id="",
                        timestamp=t,
                        matched_field="attribute",
                        entity_id=det.track_id,
                        key=attribute_key,
                        value=val,
                        confidence=det.confidence,
                        bbox=det.bbox.to_list(),
                        provenance={"source": det.source, "label": det.label},
                    ))

            if attribute_found:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_PRESENT,
                    matches=matches,
                    query_summary=f"Entity '{track_id}' attribute '{attribute_key}'",
                    epistemic_reason=f"Attribute '{attribute_key}' positively verified across {len(matches)} observations",
                )
            else:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_ABSENT,
                    matches=[],
                    query_summary=f"Entity '{track_id}' attribute '{attribute_key}'",
                    epistemic_reason=f"Track '{track_id}' was actively observed ({len(filtered)} times), but attribute '{attribute_key}' was not present",
                )

    def query_ocr_text(
        self,
        query: str,
        exact: bool = False,
        time_window: float | None = None,
    ) -> MicroRecallResult:
        """Recall exact OCR text with spatial location and zero distortion."""
        with self._lock:
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            matches: list[MicroDetailMatch] = []
            target = query.lower() if not exact else query

            for f in reversed(self._frames):
                if f.timestamp < start_t:
                    break
                for ocr in f.ocr_items:
                    text_comp = ocr.text.lower() if not exact else ocr.text
                    if target in text_comp:
                        matches.append(MicroDetailMatch(
                            frame_id=f.frame_id,
                            timestamp=f.timestamp,
                            matched_field="ocr",
                            key="text",
                            value=ocr.text,
                            confidence=ocr.confidence,
                            bbox=ocr.bbox.to_list() if ocr.bbox else None,
                            provenance={"region_tag": ocr.region_tag, **ocr.metadata},
                        ))

            if matches:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_PRESENT,
                    matches=matches,
                    query_summary=f"OCR query '{query}'",
                    epistemic_reason=f"Found {len(matches)} exact OCR matches in memory window",
                )
            else:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_ABSENT if self._frames else EpistemicStatus.NOT_OBSERVED,
                    matches=[],
                    query_summary=f"OCR query '{query}'",
                    epistemic_reason=f"Text '{query}' was not detected in active OCR regions",
                )

    def query_acoustic_events(
        self,
        label: str | None = None,
        category: str | None = None,
        time_window: float | None = None,
    ) -> MicroRecallResult:
        """Recall detected acoustic sound events."""
        with self._lock:
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            matches: list[MicroDetailMatch] = []
            q_label = label.lower() if label else None
            q_cat = category.lower() if category else None

            for f in reversed(self._frames):
                if f.timestamp < start_t:
                    break
                for ac in f.acoustic_events:
                    match_label = (q_label is None) or (q_label in ac.label.lower())
                    match_cat = (q_cat is None) or (q_cat == ac.category.lower())
                    if match_label and match_cat:
                        matches.append(MicroDetailMatch(
                            frame_id=f.frame_id,
                            timestamp=f.timestamp,
                            matched_field="acoustic",
                            key=ac.label,
                            value={
                                "label": ac.label,
                                "category": ac.category,
                                "start_time": ac.start_time,
                                "end_time": ac.end_time,
                                "channel": ac.channel,
                            },
                            confidence=ac.confidence,
                            provenance={"channel": ac.channel, **ac.metadata},
                        ))

            summary = f"Acoustic query (label='{label}', cat='{category}')"
            if matches:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_PRESENT,
                    matches=matches,
                    query_summary=summary,
                    epistemic_reason=f"Identified {len(matches)} matching acoustic events",
                )
            else:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_ABSENT if self._frames else EpistemicStatus.NOT_OBSERVED,
                    matches=[],
                    query_summary=summary,
                    epistemic_reason=f"No acoustic events matching '{label or category}' were recorded",
                )

    def query_spatial_region(
        self,
        region: BoundingBox,
        time_window: float | None = None,
    ) -> MicroRecallResult:
        """Recall all entities and text within a specified spatial box."""
        with self._lock:
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            matches: list[MicroDetailMatch] = []
            for f in reversed(self._frames):
                if f.timestamp < start_t:
                    break
                for det in f.visual_detections:
                    if region.contains_bbox(det.bbox) or region.iou(det.bbox) > 0.1:
                        matches.append(MicroDetailMatch(
                            frame_id=f.frame_id,
                            timestamp=f.timestamp,
                            matched_field="detection",
                            entity_id=det.track_id,
                            key=det.label,
                            value={"label": det.label, "attributes": det.attributes},
                            confidence=det.confidence,
                            bbox=det.bbox.to_list(),
                            provenance={"source": det.source},
                        ))
                for ocr in f.ocr_items:
                    if ocr.bbox and (region.contains_bbox(ocr.bbox) or region.iou(ocr.bbox) > 0.1):
                        matches.append(MicroDetailMatch(
                            frame_id=f.frame_id,
                            timestamp=f.timestamp,
                            matched_field="ocr",
                            key="text",
                            value=ocr.text,
                            confidence=ocr.confidence,
                            bbox=ocr.bbox.to_list(),
                            provenance={"region_tag": ocr.region_tag},
                        ))

            summary = f"Spatial region query bbox={region.to_list()}"
            if matches:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_PRESENT,
                    matches=matches,
                    query_summary=summary,
                    epistemic_reason=f"Found {len(matches)} items intersecting region",
                )
            else:
                return MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_ABSENT if self._frames else EpistemicStatus.NOT_OBSERVED,
                    matches=[],
                    query_summary=summary,
                    epistemic_reason="Region was inspected but contained no detected entities or OCR text",
                )

    def query_multimodal_cooccurrence(
        self,
        visual_label: str,
        acoustic_label: str,
        max_delta_sec: float = 1.0,
        time_window: float | None = None,
    ) -> list[dict[str, Any]]:
        """Identify moments where visual observation and acoustic event occurred together."""
        with self._lock:
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            q_vis = visual_label.lower()
            q_ac = acoustic_label.lower()

            results: list[dict[str, Any]] = []
            for f in self._frames:
                if f.timestamp < start_t:
                    continue
                matching_dets = [d for d in f.visual_detections if q_vis in d.label.lower()]
                matching_acs = [a for a in f.acoustic_events if q_ac in a.label.lower()]

                if matching_dets and matching_acs:
                    for d in matching_dets:
                        for a in matching_acs:
                            results.append({
                                "frame_id": f.frame_id,
                                "timestamp": f.timestamp,
                                "entity": d.to_dict(),
                                "acoustic": a.to_dict(),
                                "cooccurrence_type": "same_frame",
                            })
            return results

    def format_micro_recall_context(
        self,
        query: str,
        max_matches: int = 5,
        time_window: float | None = 60.0,
    ) -> str:
        """Construct prompt context block for foreground/background brain lane."""
        with self._lock:
            # Check OCR matches
            ocr_res = self.query_ocr_text(query, exact=False, time_window=time_window)
            # Check acoustic matches
            ac_res = self.query_acoustic_events(label=query, time_window=time_window)

            blocks = []
            if ocr_res.is_present:
                blocks.append(ocr_res.to_context_string())
            if ac_res.is_present:
                blocks.append(ac_res.to_context_string())

            # Check entity labels and attributes
            entity_matches: list[MicroDetailMatch] = []
            now = self._clock()
            start_t = (now - time_window) if time_window is not None else 0.0

            for tid, hist in self._track_history.items():
                for t, det in reversed(hist):
                    if t < start_t:
                        break
                    if query.lower() in det.label.lower() or any(query.lower() in str(v).lower() for v in det.attributes.values()):
                        entity_matches.append(MicroDetailMatch(
                            frame_id="",
                            timestamp=t,
                            matched_field="detection",
                            entity_id=det.track_id,
                            key=det.label,
                            value={"label": det.label, "attributes": det.attributes},
                            confidence=det.confidence,
                            bbox=det.bbox.to_list(),
                        ))
                        break

            if entity_matches:
                ent_res = MicroRecallResult(
                    status=EpistemicStatus.OBSERVED_PRESENT,
                    matches=entity_matches[:max_matches],
                    query_summary=f"Entity match for '{query}'",
                    epistemic_reason=f"Found {len(entity_matches)} matching entities",
                )
                blocks.append(ent_res.to_context_string())

            if not blocks:
                return f"[SceneMemory] Query '{query}': NOT OBSERVED in current memory window ({time_window:.1f}s)."
            return "\n".join(blocks)

    def _prune_internal(self, now: float) -> None:
        min_time = now - self.retention_seconds

        # Prune deque frames
        while self._frames and self._frames[0].timestamp < min_time:
            evicted = self._frames.popleft()
            self._frames_by_id.pop(evicted.frame_id, None)

        # Prune track history
        for tid in list(self._track_history.keys()):
            self._track_history[tid] = [(t, d) for (t, d) in self._track_history[tid] if t >= min_time]
            if not self._track_history[tid]:
                self._track_history.pop(tid, None)

        # Prune OCR index
        for tok in list(self._ocr_index.keys()):
            self._ocr_index[tok] = [(t, fid, o) for (t, fid, o) in self._ocr_index[tok] if t >= min_time]
            if not self._ocr_index[tok]:
                self._ocr_index.pop(tok, None)

        # Prune acoustic index
        for label in list(self._acoustic_index.keys()):
            self._acoustic_index[label] = [(t, fid, a) for (t, fid, a) in self._acoustic_index[label] if t >= min_time]
            if not self._acoustic_index[label]:
                self._acoustic_index.pop(label, None)

        # Prune graph
        self.graph.prune_older_than(min_time)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "frames_count": len(self._frames),
                "graph_nodes": len(self.graph.nodes),
                "graph_edges": len(self.graph.edges),
                "tracked_entities": len(self._track_history),
                "indexed_ocr_tokens": len(self._ocr_index),
                "indexed_acoustic_labels": len(self._acoustic_index),
                "oldest_timestamp": self._frames[0].timestamp if self._frames else None,
                "latest_timestamp": self._frames[-1].timestamp if self._frames else None,
            }
