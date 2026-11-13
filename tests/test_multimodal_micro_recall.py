"""Unit tests for multimodal scene memory and zero-loss micro recall."""

import time
import pytest

from jawl_voicecompanion.scene_memory import (
    AcousticEvent,
    BoundingBox,
    EpistemicStatus,
    MicroDetailMatch,
    MicroRecallResult,
    MultimodalSceneFrame,
    MultimodalSceneGraph,
    OCRItem,
    SceneGraphEdge,
    SceneGraphNode,
    SceneMemoryManager,
    SpeechTurn,
    VisualDetection,
)


def test_bounding_box_geometry() -> None:
    # Standard box
    box1 = BoundingBox(0.1, 0.2, 0.5, 0.6)
    assert box1.width == pytest.approx(0.4)
    assert box1.height == pytest.approx(0.4)
    assert box1.area == pytest.approx(0.16)
    assert box1.center == (pytest.approx(0.3), pytest.approx(0.4))
    assert box1.contains_point(0.2, 0.3)
    assert not box1.contains_point(0.6, 0.7)

    # Inverted coordinates auto-normalized
    box_inv = BoundingBox(0.5, 0.6, 0.1, 0.2)
    assert box_inv.x1 == 0.1
    assert box_inv.y1 == 0.2
    assert box_inv.x2 == 0.5
    assert box_inv.y2 == 0.6

    # Containment
    inner = BoundingBox(0.2, 0.3, 0.4, 0.5)
    assert box1.contains_bbox(inner)
    assert not inner.contains_bbox(box1)

    # IoU
    box2 = BoundingBox(0.3, 0.2, 0.7, 0.6)
    # intersection: x in [0.3, 0.5] (0.2), y in [0.2, 0.6] (0.4) => area = 0.08
    # box1 area = 0.16, box2 area = 0.16 => union = 0.24 => iou = 0.08 / 0.24 = 1/3
    assert box1.iou(box2) == pytest.approx(1.0 / 3.0)


def test_multimodal_scene_frame_creation_and_search() -> None:
    frame = MultimodalSceneFrame(frame_id="f_001", timestamp=100.0)
    det1 = VisualDetection(
        track_id="player_1",
        label="CyberSamurai",
        bbox=BoundingBox(0.2, 0.3, 0.4, 0.8),
        confidence=0.98,
        attributes={"hp": 100.0, "stance": "defensive"},
    )
    det2 = VisualDetection(
        track_id="enemy_drone",
        label="ReconDrone",
        bbox=BoundingBox(0.7, 0.1, 0.9, 0.3),
        confidence=0.91,
        attributes={"shield": 45.5},
    )
    ocr = OCRItem(
        text="WARNING: HIGH VOLTAGE",
        bbox=BoundingBox(0.05, 0.05, 0.35, 0.12),
        confidence=0.99,
        region_tag="ui",
    )
    acoustic = AcousticEvent(
        label="Gunshot",
        category="sfx",
        confidence=0.88,
        start_time=99.8,
        end_time=100.2,
    )
    speech = SpeechTurn(
        turn_id="turn_42",
        speaker="user",
        transcript="Watch out for the drone!",
        start_time=100.0,
        end_time=101.5,
    )

    frame.add_detection(det1)
    frame.add_detection(det2)
    frame.add_ocr(ocr)
    frame.add_acoustic(acoustic)
    frame.add_speech(speech)

    # Retrieval assertions
    assert frame.get_detection("player_1") == det1
    assert frame.get_detection("non_existent") is None

    assert len(frame.find_detections_by_label("drone")) == 1
    assert frame.find_detections_by_label("drone")[0].track_id == "enemy_drone"

    assert len(frame.search_ocr("voltage")) == 1
    assert frame.search_ocr("voltage")[0].text == "WARNING: HIGH VOLTAGE"
    assert len(frame.search_ocr("voltage", exact=True)) == 0
    assert len(frame.search_ocr("WARNING: HIGH VOLTAGE", exact=True)) == 1

    assert len(frame.get_acoustic_events("gunshot")) == 1
    assert len(frame.get_acoustic_events("explosion")) == 0

    # Serialization roundtrip
    serialized = frame.to_dict()
    restored = MultimodalSceneFrame.from_dict(serialized)
    assert restored.frame_id == frame.frame_id
    assert len(restored.visual_detections) == 2
    assert restored.visual_detections[0].attributes["hp"] == 100.0


def test_zero_loss_entity_attribute_recall() -> None:
    current_time = 1000.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    # Frame 1: player observed with health 87.5
    f1 = MultimodalSceneFrame(frame_id="f1", timestamp=current_time - 5.0)
    f1.add_detection(VisualDetection(
        track_id="boss_01",
        label="TitanMech",
        bbox=BoundingBox(0.1, 0.1, 0.6, 0.8),
        confidence=0.96,
        attributes={"core_temp": 1042.85, "phase": 2, "weak_spot": "left_shoulder"},
    ))
    mem.ingest_frame(f1)

    # Query exact float attribute
    res = mem.query_entity_attribute(track_id="boss_01", attribute_key="core_temp", time_window=10.0)
    assert res.status == EpistemicStatus.OBSERVED_PRESENT
    assert res.is_present
    assert not res.is_absent
    assert not res.is_unobserved
    assert len(res.matches) == 1
    # Zero-loss precision check: exactly 1042.85, no rounding
    assert res.matches[0].value == 1042.85
    assert res.matches[0].key == "core_temp"
    assert res.matches[0].confidence == 0.96
    assert res.matches[0].bbox == [0.1, 0.1, 0.6, 0.8]

    # Query phase int attribute
    res_phase = mem.query_entity_attribute(track_id="boss_01", attribute_key="phase", time_window=10.0)
    assert res_phase.status == EpistemicStatus.OBSERVED_PRESENT
    assert res_phase.matches[0].value == 2


def test_epistemic_observed_absent() -> None:
    current_time = 1000.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    frame = MultimodalSceneFrame(frame_id="f1", timestamp=current_time - 2.0)
    frame.add_detection(VisualDetection(
        track_id="ally_tank",
        label="HoverTank",
        bbox=BoundingBox(0.2, 0.2, 0.5, 0.5),
        confidence=0.95,
        attributes={"armor": 80.0},
    ))
    mem.ingest_frame(frame)

    # Track ally_tank was actively observed, but does NOT possess attribute 'stealth_cloak'
    res = mem.query_entity_attribute(track_id="ally_tank", attribute_key="stealth_cloak", time_window=10.0)
    assert res.status == EpistemicStatus.OBSERVED_ABSENT
    assert res.is_absent
    assert not res.is_present
    assert len(res.matches) == 0
    assert "actively observed" in res.epistemic_reason


def test_epistemic_not_observed() -> None:
    current_time = 1000.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    # No frames for ghost_entity
    res = mem.query_entity_attribute(track_id="ghost_entity", attribute_key="health", time_window=10.0)
    assert res.status == EpistemicStatus.NOT_OBSERVED
    assert res.is_unobserved
    assert not res.is_present
    assert len(res.matches) == 0
    assert "has not been observed" in res.epistemic_reason


def test_ocr_exact_and_substring_recall() -> None:
    current_time = 500.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    frame = MultimodalSceneFrame(frame_id="f1", timestamp=current_time - 1.0)
    frame.add_ocr(OCRItem(
        text="MISSION OBJECTIVE: PURGE SECTOR 7",
        bbox=BoundingBox(0.1, 0.8, 0.9, 0.95),
        confidence=0.995,
        region_tag="objective_hud",
    ))
    mem.ingest_frame(frame)

    # Substring search
    res = mem.query_ocr_text("SECTOR 7", exact=False, time_window=10.0)
    assert res.status == EpistemicStatus.OBSERVED_PRESENT
    assert len(res.matches) == 1
    assert res.matches[0].value == "MISSION OBJECTIVE: PURGE SECTOR 7"
    assert res.matches[0].bbox == [0.1, 0.8, 0.9, 0.95]

    # Missing text
    res_missing = mem.query_ocr_text("GAMEOVER", exact=False, time_window=10.0)
    assert res_missing.status == EpistemicStatus.OBSERVED_ABSENT


def test_acoustic_event_query() -> None:
    current_time = 500.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    frame = MultimodalSceneFrame(frame_id="f1", timestamp=current_time - 3.0)
    frame.add_acoustic(AcousticEvent(
        label="Alarm Siren",
        category="sfx",
        confidence=0.92,
        start_time=496.5,
        end_time=499.0,
        channel="system",
    ))
    frame.add_acoustic(AcousticEvent(
        label="Footsteps",
        category="sfx",
        confidence=0.75,
        start_time=497.0,
        end_time=498.0,
        channel="system",
    ))
    mem.ingest_frame(frame)

    # Query Siren
    res_siren = mem.query_acoustic_events(label="siren", time_window=10.0)
    assert res_siren.status == EpistemicStatus.OBSERVED_PRESENT
    assert len(res_siren.matches) == 1
    assert res_siren.matches[0].value["label"] == "Alarm Siren"
    assert res_siren.matches[0].value["start_time"] == 496.5

    # Query non-existent
    res_none = mem.query_acoustic_events(label="thunder", time_window=10.0)
    assert res_none.status == EpistemicStatus.OBSERVED_ABSENT


def test_spatial_region_query() -> None:
    current_time = 100.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    frame = MultimodalSceneFrame(frame_id="f1", timestamp=current_time - 1.0)
    # Entity in top-left
    frame.add_detection(VisualDetection(
        track_id="radar_blip",
        label="HostileRadar",
        bbox=BoundingBox(0.05, 0.05, 0.25, 0.25),
        confidence=0.9,
    ))
    # Entity in bottom-right
    frame.add_detection(VisualDetection(
        track_id="distant_building",
        label="Building",
        bbox=BoundingBox(0.7, 0.7, 0.95, 0.95),
        confidence=0.8,
    ))
    mem.ingest_frame(frame)

    # Query top-left region
    top_left_region = BoundingBox(0.0, 0.0, 0.3, 0.3)
    res = mem.query_spatial_region(top_left_region, time_window=5.0)
    assert res.status == EpistemicStatus.OBSERVED_PRESENT
    assert len(res.matches) == 1
    assert res.matches[0].entity_id == "radar_blip"

    # Query center empty region
    center_region = BoundingBox(0.4, 0.4, 0.6, 0.6)
    res_empty = mem.query_spatial_region(center_region, time_window=5.0)
    assert res_empty.status == EpistemicStatus.OBSERVED_ABSENT


def test_multimodal_scene_graph_construction() -> None:
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: 100.0)

    frame = MultimodalSceneFrame(frame_id="f_graph", timestamp=100.0)
    # Detection 1
    frame.add_detection(VisualDetection(
        track_id="turret_1",
        label="AutoTurret",
        bbox=BoundingBox(0.2, 0.2, 0.5, 0.5),
        confidence=0.95,
    ))
    # OCR contained within Turret's bounding box
    frame.add_ocr(OCRItem(
        text="TURRET LOCKED",
        bbox=BoundingBox(0.25, 0.25, 0.45, 0.35),
        confidence=0.99,
        region_tag="in_game",
    ))
    # Speech turn referencing AutoTurret
    frame.add_speech(SpeechTurn(
        turn_id="sp_1",
        speaker="assistant",
        transcript="The AutoTurret is aiming directly at us!",
        start_time=100.0,
        end_time=102.0,
    ))
    mem.ingest_frame(frame)

    graph = mem.graph
    assert len(graph.nodes) >= 3  # turret entity, ocr text, speech turn

    # Find the OCR node
    ocr_nodes = graph.find_nodes_by_type("ocr")
    assert len(ocr_nodes) == 1
    assert ocr_nodes[0].label == "TURRET LOCKED"

    # Check that OCR has an edge connecting to the turret entity ('referenced_in')
    ocr_neighbors = graph.get_neighbors(ocr_nodes[0].node_id, edge_type="referenced_in", direction="out")
    assert len(ocr_neighbors) == 1
    target_node, edge = ocr_neighbors[0]
    assert target_node.node_type == "entity"
    assert target_node.label == "AutoTurret"


def test_multimodal_cooccurrence() -> None:
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: 100.0)

    frame = MultimodalSceneFrame(frame_id="f_cooccur", timestamp=100.0)
    frame.add_detection(VisualDetection(
        track_id="laser_beam",
        label="LaserWeapon",
        bbox=BoundingBox(0.4, 0.4, 0.6, 0.6),
        confidence=0.9,
    ))
    frame.add_acoustic(AcousticEvent(
        label="Laser Blast",
        category="sfx",
        confidence=0.95,
        start_time=99.9,
        end_time=100.3,
    ))
    mem.ingest_frame(frame)

    co_events = mem.query_multimodal_cooccurrence(
        visual_label="laser",
        acoustic_label="blast",
        time_window=10.0,
    )
    assert len(co_events) == 1
    assert co_events[0]["frame_id"] == "f_cooccur"
    assert co_events[0]["entity"]["label"] == "LaserWeapon"
    assert co_events[0]["acoustic"]["label"] == "Laser Blast"


def test_format_micro_recall_context() -> None:
    current_time = 200.0
    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: current_time)

    frame = MultimodalSceneFrame(frame_id="f_ctx", timestamp=current_time - 1.0)
    frame.add_ocr(OCRItem(
        text="DOOR CODE: 481516",
        bbox=BoundingBox(0.2, 0.3, 0.5, 0.4),
        confidence=0.98,
    ))
    mem.ingest_frame(frame)

    ctx = mem.format_micro_recall_context("481516", time_window=10.0)
    assert "[SceneMemory]" in ctx
    assert "481516" in ctx
    assert "DOOR CODE: 481516" in ctx

    # Unobserved query
    missing_ctx = mem.format_micro_recall_context("non_existent_key_999", time_window=10.0)
    assert "NOT OBSERVED" in missing_ctx


def test_pruning_and_ttl() -> None:
    current_time = 100.0
    mem = SceneMemoryManager(max_frames=5, retention_seconds=10.0, clock=lambda: current_time)

    # Ingest 3 frames from t=80 to t=85 (older than retention_seconds=10 at current_time=100)
    f_old1 = MultimodalSceneFrame(frame_id="old1", timestamp=85.0)
    mem.ingest_frame(f_old1)

    f_old2 = MultimodalSceneFrame(frame_id="old2", timestamp=88.0)
    mem.ingest_frame(f_old2)

    # Now ingest frame at t=100.0
    f_new = MultimodalSceneFrame(frame_id="new1", timestamp=100.0)
    mem.ingest_frame(f_new)

    # At t=100, min_time = 90.0. old1 (85.0) and old2 (88.0) must be pruned!
    assert mem.get_frame("old1") is None
    assert mem.get_frame("old2") is None
    assert mem.get_frame("new1") is not None
    assert len(mem.get_frames()) == 1
def test_perception_fusion_scene_memory_integration() -> None:
    from jawl_voicecompanion.perception_fusion import PerceptionFusion

    mem = SceneMemoryManager(max_frames=10, retention_seconds=60.0, clock=lambda: 100.0)
    fusion = PerceptionFusion(scene_memory=mem)

    # 1. Observe screen caption
    fusion.observe_screen("The player enters the ancient ruins.")
    frames = mem.get_frames()
    assert len(frames) == 1
    assert len(frames[0].visual_detections) == 1
    assert frames[0].visual_detections[0].label == "screen"
    assert "ancient ruins" in frames[0].visual_detections[0].attributes["caption"]

    # 2. Record visual event with ROI
    fusion.record_visual_event(
        "Health bar showing 42 HP",
        captured_at_monotonic=100.0,
        captured_at_wall=100.0,
        frame_id="frame_hud_1",
        source="game_stream",
        scene_id="level_3",
        roi=(0.1, 0.1, 0.2, 0.05),
    )
    assert len(mem.get_frames()) == 2
    f2 = mem.get_frame("frame_hud_1")
    assert f2 is not None
    assert len(f2.visual_detections) == 1
    det = f2.visual_detections[0]
    assert det.label == "Health bar showing 42 HP"
    assert det.bbox is not None
    assert det.bbox.x == 0.1
    assert det.bbox.y == 0.1
    assert det.bbox.width == 0.2
    assert det.bbox.height == 0.05
