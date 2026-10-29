from __future__ import annotations

import json

from jawl_voicecompanion.sensory_history import SensoryHistoryStore


class Clock:
    def __init__(self, value: float = 1_800_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_recent_events_coalesce_and_expire_after_one_hour(tmp_path) -> None:
    clock = Clock()
    store = SensoryHistoryStore(tmp_path / "history.json", enabled=True, clock=clock, flush_interval_seconds=1)
    assert store.record("visual", "A character walks through a neon street", observed_at=clock()) ["status"] == "recorded"
    clock.advance(5)
    assert store.record("visual", "A character walks through a neon street", observed_at=clock()) ["status"] == "coalesced"
    assert store.state()["recent_event_count"] == 1
    assert "sample_count" not in store.context_text()
    clock.advance(3610)
    assert "neon street" not in store.context_text()


def test_weekly_compact_history_persists_text_and_provenance_only(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "history.json"
    store = SensoryHistoryStore(path, enabled=True, clock=clock, flush_interval_seconds=1)
    result = store.record("visual", "New gameplay scene: a car turns left", observed_at=clock(),
                          source="display0", scene_id="scene-2", verified=False,
                          metadata={"scene_changed": True})
    assert result["importance"] >= 3
    store.record("music", "Music classifier reports a fast electronic rhythm", observed_at=clock(),
                 source="loopback", metadata={"music_state": "music"})
    store.flush()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["policy"]["raw_audio_persisted"] is False
    assert payload["policy"]["raw_video_persisted"] is False
    assert all("pcm" not in str(event).lower() for event in payload["recent_events"])
    reopened = SensoryHistoryStore(path, enabled=True, clock=clock)
    context = reopened.context_text(seconds=7 * 24 * 3600, include_week=True)
    assert "display0" in context and "car turns left" in context
    assert "loopback" in context


def test_hourly_compaction_preserves_scene_timeline_span_after_restart(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "timeline.json"
    store = SensoryHistoryStore(
        path, enabled=True, clock=clock, flush_interval_seconds=1,
        max_moments_per_hour=10,
    )
    for index in range(20):
        store.record(
            "visual", f"Scene {index:02d} appears", observed_at=clock(),
            source="display0", scene_id=f"scene-{index:02d}",
            metadata={"scene_changed": True},
        )
        clock.advance(180)
    store.flush()

    reopened = SensoryHistoryStore(path, enabled=True, clock=clock, max_moments_per_hour=10)
    context = reopened.context_text(seconds=7 * 24 * 3600, include_week=True)
    moments = [line for line in context.splitlines() if " VISUAL " in line]

    assert len(moments) == 10
    assert "Scene 00 appears" in moments[0]
    assert "Scene 19 appears" in moments[-1]
    assert any("Scene 0" in line or "Scene 1" in line for line in moments[1:-1])


def test_recent_context_compaction_samples_middle_and_keeps_source_order(tmp_path) -> None:
    clock = Clock()
    store = SensoryHistoryStore(tmp_path / "dense.json", enabled=True, clock=clock)
    for index in range(60):
        store.record(
            "visual", f"Timeline marker {index:02d}", observed_at=clock(),
            source="display0", scene_id=f"timeline-{index:02d}",
            metadata={"scene_changed": True},
        )
        clock.advance(55)

    context = store.context_text(seconds=3600, max_chars=1200)
    marker_ids = [int(part.split("Timeline marker ", 1)[1])
                  for part in context.splitlines() if "Timeline marker" in part]

    assert len(context) <= 1200
    assert len(marker_ids) >= 8
    assert marker_ids[0] == 0
    assert marker_ids[-1] == 59
    assert any(20 <= marker <= 39 for marker in marker_ids)
    assert marker_ids == sorted(marker_ids)


def test_recent_context_orders_late_results_by_capture_time(tmp_path) -> None:
    clock = Clock()
    store = SensoryHistoryStore(tmp_path / "out-of-order.json", enabled=True, clock=clock)
    store.record("visual", "Later captured scene", observed_at=clock() - 10)
    store.record("visual", "Earlier captured scene", observed_at=clock() - 20)

    context = store.context_text(seconds=60)

    assert context.index("Earlier captured scene") < context.index("Later captured scene")


def test_relative_time_focus_returns_the_requested_window(tmp_path) -> None:
    clock = Clock()
    store = SensoryHistoryStore(tmp_path / "history.json", enabled=True, clock=clock)
    store.record("visual", "Scene before the requested moment", observed_at=clock() - 205)
    store.record("visual", "Requested two-minute-old scene", observed_at=clock() - 120)
    store.record("speech", "Current unrelated speech", observed_at=clock() - 20)

    context = store.context_text(seconds=300, focus_seconds_ago=120, focus_window_seconds=60)

    assert "Requested two-minute-old scene" in context
    assert "Scene before the requested moment" not in context
    assert "Current unrelated speech" not in context
    assert "around 2 min ago" in context


def test_sensitive_text_and_disabled_store_fail_closed(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "disabled.json"
    disabled = SensoryHistoryStore(path, enabled=False, clock=clock)
    assert disabled.record("speech", "My password is hunter2", observed_at=clock())["status"] == "disabled"
    enabled = SensoryHistoryStore(path, enabled=True, clock=clock)
    assert enabled.record("speech", "My password is hunter2", observed_at=clock())["status"] == "suppressed"
    assert enabled.record("speech", "\u041c\u043e\u0439 \u043f\u0430\u0440\u043e\u043b\u044c 123456", observed_at=clock())["status"] == "suppressed"
    assert enabled.record("speech", "Reach me at person@example.com", observed_at=clock())["status"] == "suppressed"
    assert enabled.state()["recent_event_count"] == 0


def test_unreadable_archive_is_preserved_until_explicit_clear(tmp_path) -> None:
    clock = Clock()
    invalid_archives = (
        ("corrupt.json", "{not valid json", "history_file_unreadable"),
        ("future-schema.json", json.dumps({"schema_version": 99}), "history_schema_unsupported"),
        ("oversized.json", "x" * (8 * 1024 * 1024 + 1), "history_file_too_large"),
    )

    for filename, contents, expected_error in invalid_archives:
        path = tmp_path / filename
        path.write_text(contents, encoding="utf-8")
        original = path.read_bytes()
        store = SensoryHistoryStore(path, enabled=True, clock=clock, flush_interval_seconds=1)

        assert store.state()["last_error"] == expected_error
        assert store.state()["last_error_stage"] == "load"
        assert store.state()["load_blocked"] is True
        assert store.record("visual", "New observation before archive recovery", observed_at=clock())["status"] == "recorded"
        context = store.context_text(seconds=300)
        assert "saved archive unavailable" in context
        assert "New observation before archive recovery" in context
        store.flush()
        assert path.read_bytes() == original
        assert store.state()["last_flush_age_seconds"] is None

        assert store.clear()["status"] == "cleared"
        assert not path.exists()
        store.record("visual", "Fresh observation after explicit clear", observed_at=clock())
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert [event["text"] for event in payload["recent_events"]] == [
            "Fresh observation after explicit clear"
        ]
        assert store.state()["last_error"] is None
        assert store.state()["last_error_stage"] is None
        assert store.state()["load_blocked"] is False
