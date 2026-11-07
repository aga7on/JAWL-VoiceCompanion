from pathlib import Path
from tempfile import TemporaryDirectory

from jawl_voicecompanion.perception_fusion import PerceptionFusion
from jawl_voicecompanion.sensory_history import SensoryHistoryStore
from jawl_voicecompanion.web import CompanionServer, _history_focus_seconds_ago


class _Arbiter:
    def state(self):
        return {"active": None}


class _Gateway:
    arbiter = _Arbiter()

    def __init__(self, prior=()):
        self.prior = prior

    def turn_history(self, limit):
        return self.prior


def _server(history, prior=()):
    class Context:
        gateway = _Gateway(prior)
        perception_fusion = PerceptionFusion()
        sensory_history = history
        _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

    return Context()


def test_natural_music_and_two_hour_recall_survive_reload():
    with TemporaryDirectory() as directory:
        clock = [1_700_000_000.0]
        path = Path(directory) / "history.json"
        history = SensoryHistoryStore(path, enabled=True, clock=lambda: clock[0])
        history.record("music", "an earlier jazz trio", source="player", observed_at=clock[0], metadata={"music_state": "music"})
        clock[0] += 5400
        history.record("music", "a recent guitar track", source="player", observed_at=clock[0])
        clock[0] += 1800
        history.flush()
        history = SensoryHistoryStore(path, enabled=True, clock=lambda: clock[0])
        server = _server(history)

        for query in ("Помнишь, какую песню мы слушали?", "Какая музыка играла?"):
            result = CompanionServer.enrich_turn_text(server, query)
            assert "a recent guitar track" in result
            assert "player" in result
        result = CompanionServer.enrich_turn_text(server, "Что было два часа назад?")
        assert "an earlier jazz trio" in result
        assert "a recent guitar track" not in result
        assert "unverified model observation" in result


def test_current_turn_alone_controls_history_intent_and_focus():
    class History:
        calls = []

        def context_text(self, **kwargs):
            self.calls.append(kwargs)
            return "HISTORY-MARKER"

    history = History()
    server = _server(history, prior=[{"user": "Что было два часа назад за неделю?", "response": {"text": "не знаю"}}])
    result = CompanionServer.enrich_turn_text(server, "Привет, как дела?")
    assert "HISTORY-MARKER" not in result
    assert not history.calls
    result = CompanionServer.enrich_turn_text(server, "Что было две минуты назад?")
    assert "HISTORY-MARKER" in result
    assert history.calls[-1]["focus_seconds_ago"] == 120
    assert history.calls[-1]["include_week"] is False


def test_hours_minutes_and_non_temporal_questions():
    assert _history_focus_seconds_ago("два часа назад") == 7200
    assert _history_focus_seconds_ago("полтора часа назад") == 5400
    assert _history_focus_seconds_ago("two hours ago") == 7200
    assert _history_focus_seconds_ago("две минуты назад") == 120
    assert _history_focus_seconds_ago("играем два часа") is None
