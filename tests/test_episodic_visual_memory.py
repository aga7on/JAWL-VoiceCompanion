"""Tests for DXGIScreenCapture, SceneDeltaDetector, and EpisodicVisualMemory."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from typing import Iterator

import numpy as np
from PIL import Image
import pytest

from jawl_voicecompanion.visual_stream import DXGIScreenCapture, SceneDeltaDetector
from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory


@pytest.fixture
def temp_memory_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="test_vis_mem_") as tmp:
        yield Path(tmp)


def test_visual_capture_init_and_state() -> None:
    capture = DXGIScreenCapture()
    st = capture.state()
    assert st["running"] is True
    assert "is_dxgi" in st
    assert "frames_captured" in st
    assert st["output_idx"] == 0
    capture.stop()
    assert capture.running is False


def test_visual_capture_fallback_and_grab_pil() -> None:
    # Test capture with forced fallback to ImageGrab
    capture = DXGIScreenCapture(force_fallback=True)
    assert capture.is_dxgi is False
    assert capture.running is True

    frame = capture.grab()
    if frame is not None:
        assert isinstance(frame, np.ndarray)
        assert len(frame.shape) == 3
        assert frame.shape[2] == 3

    pil_img = capture.grab_pil(max_dimension=320)
    if pil_img is not None:
        assert isinstance(pil_img, Image.Image)
        assert max(pil_img.size) <= 320

    capture.stop()


def test_scene_delta_detector_gating() -> None:
    detector = SceneDeltaDetector(grid_size=32, change_threshold=0.10)

    # Frame 1: Initial black frame
    black = np.zeros((100, 100, 3), dtype=np.uint8)
    d1, c1, sid1 = detector.compute_delta(black)
    assert d1 == 1.0
    assert c1 is True
    assert sid1 == "scene_0"

    # Frame 2: Identical black frame -> no scene change
    d2, c2, sid2 = detector.compute_delta(black)
    assert d2 == 0.0
    assert c2 is False
    assert sid2 == "scene_0"

    # Frame 3: Minor noise below threshold (e.g. 5% brightness increase)
    subtle = np.full((100, 100, 3), 10, dtype=np.uint8)  # 10/255 ~= 0.039 < 0.10
    d3, c3, sid3 = detector.compute_delta(subtle)
    assert d3 < 0.10
    assert c3 is False
    assert sid3 == "scene_0"

    # Frame 4: Major scene change (pure white frame)
    white = np.full((100, 100, 3), 255, dtype=np.uint8)
    d4, c4, sid4 = detector.compute_delta(white)
    assert d4 >= 0.10
    assert c4 is True
    assert sid4 == "scene_1"


def test_episodic_visual_memory_ingest(temp_memory_dir: Path) -> None:
    db_path = temp_memory_dir / "lancedb"
    cache_dir = temp_memory_dir / "cache"

    mem = EpisodicVisualMemory(
        db_path=db_path,
        image_cache_dir=cache_dir,
        max_image_dimension=256,
        webp_quality=75,
    )
    assert mem.count() == 0
    st = mem.state()
    assert st["total_keyframes"] == 0
    assert st["vector_dimension"] in (512, 768)

    # Ingest a synthetic frame with metadata
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:, :, 0] = 200  # Reddish
    res = mem.ingest_keyframe(
        frame,
        scene_id="scene_test_42",
        app_name="vlc.exe",
        window_title="Anime Episode 1",
        speech_context="Взгляни на этот замок!",
        summary="Вид на красный замок на закате",
        valence=0.7,
        arousal=0.5,
        extra_metadata={"episode": 1, "character": "Hero"},
    )

    assert res["status"] == "ingested"
    assert res["scene_id"] == "scene_test_42"
    assert res["vector_dim"] in (512, 768)
    assert Path(res["image_path"]).is_file()
    assert mem.count() == 1


def test_episodic_visual_memory_multimodal_search(temp_memory_dir: Path) -> None:
    db_path = temp_memory_dir / "lancedb"
    mem = EpisodicVisualMemory(db_path=db_path)

    # Ingest two distinct visual frames
    red_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    red_frame[:, :, 0] = 255  # Solid Red

    blue_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    blue_frame[:, :, 2] = 255  # Solid Blue

    mem.ingest_keyframe(
        red_frame,
        scene_id="scene_red",
        app_name="anime_player",
        window_title="Crimson Blade",
        summary="Боец в красных доспехах у костра",
        valence=0.3,
        arousal=0.6,
    )
    mem.ingest_keyframe(
        blue_frame,
        scene_id="scene_blue",
        app_name="anime_player",
        window_title="Azure Ocean",
        summary="Океанский бриз и синие волны",
        valence=0.6,
        arousal=-0.2,
    )

    assert mem.count() == 2

    # Multimodal natural language search for red
    results_red = mem.search_visual("bright red fiery armor and fire", top_k=2)
    assert len(results_red) == 2
    assert results_red[0]["scene_id"] == "scene_red"
    assert results_red[0]["similarity"] > results_red[1]["similarity"]
    assert results_red[0]["valence"] == pytest.approx(0.3, rel=1e-2)
    assert results_red[0]["arousal"] == pytest.approx(0.6, rel=1e-2)

    # Multimodal natural language search for blue
    results_blue = mem.search_visual("deep blue ocean water sea", top_k=2)
    assert len(results_blue) == 2
    assert results_blue[0]["scene_id"] == "scene_blue"
    assert results_blue[0]["similarity"] > results_blue[1]["similarity"]


def test_episodic_visual_memory_edge_cases(temp_memory_dir: Path) -> None:
    db_path = temp_memory_dir / "lancedb"
    mem = EpisodicVisualMemory(db_path=db_path)

    # Empty query handling
    assert mem.search_visual("") == []
    assert mem.search_visual("   ") == []

    # Value clamping test for valence and arousal (-1.0 to 1.0)
    frame = Image.new("RGB", (64, 64), color="green")
    mem.ingest_keyframe(
        frame,
        scene_id="clamped_scene",
        valence=5.0,   # exceeds 1.0
        arousal=-9.0,  # below -1.0
    )
    res = mem.search_visual("green foliage tree", top_k=1)
    assert len(res) == 1
    assert res[0]["valence"] == 1.0
    assert res[0]["arousal"] == -1.0


def test_episodic_visual_recall_and_taste_profile(temp_memory_dir: Path) -> None:
    from jawl_voicecompanion.episodic_visual_memory import recall_visual_detail

    db_path = temp_memory_dir / "lancedb_recall"
    mem = EpisodicVisualMemory(db_path=db_path)

    # 1. Recall on empty database
    empty_ans = mem.recall_visual_detail("какой-то меч")
    assert empty_ans == "В памяти нет подходящих кадров."

    # 2. Ingest a red frame
    frame = Image.new("RGB", (64, 64), color="red")
    mem.ingest_keyframe(
        frame,
        scene_id="scene_sword",
        summary="Мечник с огненным клинком",
        speech_context="Берегись меча!",
    )

    # Mock VLM client
    class MockVLM:
        def analyze_images(self, images: list[str], prompt: str) -> str:
            return f"VLM_ANSWER: Found {len(images)} images for prompt '{prompt}'"

    vlm = MockVLM()
    ans = mem.recall_visual_detail("огненный клинок", vlm_client=vlm, top_k=1)
    assert "VLM_ANSWER" in ans
    assert "огненный клинок" in ans

    # Functional recall hook
    ans_func = recall_visual_detail("огненный клинок", vlm, memory=mem)
    assert "VLM_ANSWER" in ans_func

    # 3. Test taste profile storage
    taste_res = mem.save_taste_record(
        track_info={"title": "Nightcall", "artist": "Kavinsky", "album": "OutRun"},
        audio_vector=[0.1] * 16,
        time_of_day="ночь",
        valence=0.4,
        arousal=0.7,
    )
    assert taste_res["status"] == "saved"
    assert taste_res["track"] == "Nightcall"
    assert taste_res["time_of_day"] == "ночь"

    recent = mem.get_recent_taste_records(limit=5)
    assert len(recent) == 1
    assert recent[0]["track_title"] == "Nightcall"
    assert recent[0]["artist"] == "Kavinsky"


def test_episodic_visual_memory_cache_management(temp_memory_dir: Path) -> None:
    db_path = temp_memory_dir / "lancedb_cache_test"
    mem = EpisodicVisualMemory(
        db_path=db_path,
        max_cached_keyframes=3,
        max_cache_mb=1.0,
        retention_seconds=3600.0,
    )

    # Ingest 4 keyframes
    for i in range(4):
        frame = Image.new("RGB", (32, 32), color=(i * 40, i * 40, i * 40))
        mem.ingest_keyframe(frame, scene_id=f"scene_{i}", summary=f"Test scene {i}")

    # Files should exist
    cached_files = list(mem.image_cache_dir.glob("*.webp"))
    assert len(cached_files) == 4

    # Run cleanup with max_count=2
    res = mem.cleanup_old_keyframes(max_count=2)
    assert res["deleted_files"] == 2
    assert res["remaining_files"] == 2
    assert len(list(mem.image_cache_dir.glob("*.webp"))) == 2

    # Explicit deletion of a keyframe
    # Ingest one more
    frame = Image.new("RGB", (32, 32), color="blue")
    mem.ingest_keyframe(frame, scene_id="explicit_del_target")
    del_ok = mem.delete_keyframe("explicit_del_target")
    assert del_ok is True
    # Verify no file matches target
    assert len(list(mem.image_cache_dir.glob("explicit_del_target_*.webp"))) == 0

    # Test taste records prune
    mem.save_taste_record(
        track_info={"title": "Old Song", "artist": "Old Artist"},
        audio_vector=[0.0] * 16,
        time_of_day="день",
    )
    # Prune with 0s retention to remove all
    pruned = mem.prune_taste_records(retention_seconds=0.0)
    assert pruned >= 1
    assert len(mem.get_recent_taste_records()) == 0

    # Clear cache completely
    clear_res = mem.clear_cache()
    assert clear_res["deleted_files"] >= 0
    assert len(list(mem.image_cache_dir.glob("*.webp"))) == 0


def test_episodic_visual_memory_multi_frame_scene_cleanup(temp_memory_dir: Path) -> None:
    db_path = temp_memory_dir / "lancedb_multiframe"
    mem = EpisodicVisualMemory(
        db_path=db_path,
        max_cached_keyframes=10,
        max_cache_mb=10.0,
    )

    # Ingest 3 frames for the same scene_id at advancing timestamps
    base_t = time.time() - 1000.0
    ingest1 = mem.ingest_keyframe(
        Image.new("RGB", (32, 32), color="red"),
        scene_id="boss_fight",
        timestamp=base_t + 10.0,
        summary="Начало битвы с боссом",
    )
    ingest2 = mem.ingest_keyframe(
        Image.new("RGB", (32, 32), color="orange"),
        scene_id="boss_fight",
        timestamp=base_t + 20.0,
        summary="Середина битвы с боссом",
    )
    ingest3 = mem.ingest_keyframe(
        Image.new("RGB", (32, 32), color="yellow"),
        scene_id="boss_fight",
        timestamp=base_t + 30.0,
        summary="Кульминация битвы с боссом",
    )
    # Ingest 1 frame for a different scene
    ingest4 = mem.ingest_keyframe(
        Image.new("RGB", (32, 32), color="green"),
        scene_id="village_peace",
        timestamp=base_t + 40.0,
        summary="Мирная деревня",
    )

    assert mem.count() == 4
    assert len(list(mem.image_cache_dir.glob("*.webp"))) == 4

    # Prune keeping only the 2 newest files (should delete frame 1 and 2 of boss_fight)
    res = mem.cleanup_old_keyframes(max_count=2)
    assert res["deleted_files"] == 2
    assert res["remaining_files"] == 2
    assert len(list(mem.image_cache_dir.glob("*.webp"))) == 2

    # CRITICAL: LanceDB must still retain frame 3 of boss_fight and frame 4 of village_peace!
    # Earlier bug deleted ALL rows with scene_id = 'boss_fight', resulting in count == 1.
    assert mem.count() == 2

    # Verify search still finds the remaining boss_fight keyframe
    results = mem.search_visual("кульминация битвы", top_k=2)
    assert len(results) >= 1
    assert any(r["scene_id"] == "boss_fight" for r in results)

    # Test single-file deletion by image_path
    path_to_del = ingest3["image_path"]
    del_ok = mem.delete_keyframe(image_path=path_to_del)
    assert del_ok is True
    assert mem.count() == 1
    assert not Path(path_to_del).exists()


def test_scene_prefix_isolation_a_does_not_delete_a_b(tmp_path: Path) -> None:
    db_path = tmp_path / "lancedb_prefix"
    cache_dir = tmp_path / "cache_prefix"
    mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)

    img_a = Image.new("RGB", (32, 32), color="red")
    img_ab = Image.new("RGB", (32, 32), color="blue")

    ingest_a = mem.ingest_keyframe(img_a, scene_id="a", summary="Scene A")
    ingest_ab = mem.ingest_keyframe(img_ab, scene_id="a_b", summary="Scene A_B")

    assert mem.count() == 2
    path_a = Path(ingest_a["image_path"])
    path_ab = Path(ingest_ab["image_path"])
    assert path_a.exists()
    assert path_ab.exists()

    # Deleting scene "a" MUST NOT delete frames belonging to "a_b"
    res = mem.delete_keyframe(scene_id="a")
    assert res is True

    # Frame for scene "a" must be deleted
    assert not path_a.exists()
    # Frame for scene "a_b" MUST STILL EXIST
    assert path_ab.exists(), "Scene 'a' deletion leaked and deleted frame of scene 'a_b'!"

    # In LanceDB, count should be exactly 1 (for scene a_b)
    assert mem.count() == 1
    remaining = mem.search_visual("Scene", top_k=5)
    assert len(remaining) == 1
    assert remaining[0]["scene_id"] == "a_b"


def test_ingest_path_traversal_and_symlink_canary(tmp_path: Path) -> None:
    db_path = tmp_path / "lancedb_sec"
    cache_dir = tmp_path / "cache_sec"
    cache_dir.mkdir(parents=True, exist_ok=True)
    outside_canary = tmp_path / "canary_payload.webp"
    outside_canary.write_bytes(b"canary-data-protected")

    mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)

    # 1. Ingest traversal attempt with relative dots
    img = Image.new("RGB", (32, 32), color="magenta")
    ingest_res = mem.ingest_keyframe(img, scene_id="../../escape_sid", summary="Escape attempt")
    # Sanitization must ensure it stays strictly inside cache_dir
    created_path = Path(ingest_res["image_path"])
    assert created_path.is_relative_to(cache_dir.resolve())
    assert created_path.parent == cache_dir.resolve()
    assert outside_canary.read_bytes() == b"canary-data-protected"

    # 2. Symlink canary protection in delete_keyframe
    symlink_path = cache_dir / "symlink_to_canary.webp"
    try:
        symlink_path.symlink_to(outside_canary)
        # Attempt to delete via symlink pointing outside cache
        del_sym = mem.delete_keyframe(image_path=str(symlink_path))
        # Canary outside MUST NOT be deleted
        assert outside_canary.exists()
        assert outside_canary.read_bytes() == b"canary-data-protected"
    except (OSError, NotImplementedError):
        # On Windows without SeCreateSymbolicLinkPrivilege, symlinks might require admin/developer mode
        pass


def test_redact_cascades_event_id_and_scene_id(tmp_path: Path) -> None:
    db_path = tmp_path / "lancedb_redact"
    cache_dir = tmp_path / "cache_redact"
    mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)

    img = Image.new("RGB", (32, 32), color="blue")
    res1 = mem.ingest_keyframe(
        img,
        scene_id="scene_confidential",
        summary="Secret frame",
        extra_metadata={"event_id": "evt_confidential_42", "source_event_ids": ["src_99"]},
    )
    res2 = mem.ingest_keyframe(
        img,
        scene_id="scene_public",
        summary="Public frame",
        extra_metadata={"event_id": "evt_public_43"},
    )

    path1 = Path(res1["image_path"])
    path2 = Path(res2["image_path"])
    assert path1.exists()
    assert path2.exists()
    assert mem.count() == 2

    # Redact by event_id matching metadata
    redact_res = mem.redact(["evt_confidential_42"], reason="user requested forget")
    assert redact_res["status"] == "redacted"
    assert redact_res["deleted_files"] >= 1
    assert not path1.exists(), "Target file must be unlinked"
    assert path2.exists(), "Public file must remain intact"

    # Verify LanceDB table count
    assert mem.count() == 1
    remaining = mem.search_visual("frame", top_k=5)
    assert len(remaining) == 1
    assert remaining[0]["scene_id"] == "scene_public"

    # Redact by scene_id
    redact_res2 = mem.redact(["scene_public"], reason="clear scene")
    assert redact_res2["status"] == "redacted"
    assert not path2.exists()
    assert mem.count() == 0


def test_redact_traversal_safety(tmp_path: Path) -> None:
    db_path = tmp_path / "lancedb_redact_sec"
    cache_dir = tmp_path / "cache_redact_sec"
    cache_dir.mkdir(parents=True, exist_ok=True)
    outside_canary = tmp_path / "canary_file.webp"
    outside_canary.write_bytes(b"canary-protected-data")

    mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)
    res = mem.redact(["../../canary_file.webp", "canary_file.webp"], reason="malicious attempt")
    assert res["status"] == "redacted"
    assert outside_canary.exists()
    assert outside_canary.read_bytes() == b"canary-protected-data"


def test_web_forget_memory_sources_cascades_to_visual_memory(tmp_path: Path) -> None:
    from jawl_voicecompanion.web import CompanionServer
    from jawl_voicecompanion.sensory_history import SensoryHistoryStore
    from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
    from jawl_voicecompanion.narrative_consolidator import NarrativeConsolidator

    db_path = tmp_path / "lancedb_web_cascade"
    cache_dir = tmp_path / "cache_web_cascade"
    vis_mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)

    img = Image.new("RGB", (32, 32), color="purple")
    ingest_res = vis_mem.ingest_keyframe(
        img,
        scene_id="doc_scene",
        event_id="evt-doc-secret-01",
        summary="Confidential Document",
    )
    frame_path = Path(ingest_res["image_path"])
    assert frame_path.exists()
    assert vis_mem.count() == 1

    history_store = SensoryHistoryStore(tmp_path / "history.json")
    ambient_buffer = AmbientMemoryBuffer()
    narrative = NarrativeConsolidator(storage_path=tmp_path / "narrative.json")
    narrative._episode_logs = ["12:00 — Обсуждался конфиденциальный документ evt-doc-secret-01"]
    narrative._character_cards = {
        "Архивариус": {"name": "Архивариус", "traits": ["хранитель"], "keyframe_id": frame_path.name}
    }
    narrative._save()

    import threading

    class MinimalServer(CompanionServer):
        def __init__(self) -> None:
            self.gateway = None
            self._memory_sources_lock = threading.Lock()
            self._memory_sources = [("user:secret_doc", ["evt-doc-secret-01", frame_path.name])]
            self.sensory_history = history_store
            self.ambient_memory = ambient_buffer
            self.visual_memory = vis_mem
            self.narrative_consolidator = narrative

    server = MinimalServer()

    result = server.forget_memory_sources("user:secret_doc", reason="forget_request")

    assert result["status"] == "redacted"
    assert "visual_memory" in result
    assert result["visual_memory"]["status"] == "redacted"
    assert result["visual_memory"]["deleted_files"] == 1
    assert result["visual_memory"]["deleted_rows"] == 1

    assert "narrative_consolidator" in result
    assert result["narrative_consolidator"]["status"] == "redacted"
    assert result["narrative_consolidator"]["deleted_logs"] == 1
    assert result["narrative_consolidator"]["deleted_cards"] == 1

    # Keyframe on disk and LanceDB row must be permanently forgotten
    assert not frame_path.exists()
    assert vis_mem.count() == 0
    assert len(narrative._episode_logs) == 0
    assert len(narrative._character_cards) == 0





