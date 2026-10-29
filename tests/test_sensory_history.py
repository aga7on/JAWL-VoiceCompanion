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
