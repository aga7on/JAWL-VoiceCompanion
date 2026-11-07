"""Tests for CompanionServer.broadcast_event return contract, speech ownership,
and SenseNovaPerceptionBridge delivery acknowledgement.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from jawl_voicecompanion.arbiter import TurnPriority
from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.perception_fusion import CognitiveTurnDecision, PerceptionFusion, SenseNovaPerceptionBridge
from jawl_voicecompanion.web import CompanionServer


class DummyFeed:
    def __init__(self, should_fail: bool = False) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.should_fail = should_fail

    def _enqueue(self, item: dict[str, Any]) -> None:
        if self.should_fail:
            raise RuntimeError("DummyFeed enqueue failed")
        self.enqueued.append(item)


class DummySink:
    def __init__(self, should_fail: bool = False) -> None:
        self.delivered: list[dict[str, Any]] = []
        self.should_fail = should_fail

    def __call__(self, payload: dict[str, Any]) -> None:
        if self.should_fail:
            raise RuntimeError("DummySink failed")
        self.delivered.append(payload)


def test_companion_server_broadcast_event_non_dict_payload() -> None:
    server = CompanionServer.__new__(CompanionServer)
    server.proactive_feed = None
    server.stream_chat_event_sink = None

    res = server.broadcast_event("not a dict")  # type: ignore[arg-type]
    assert res["accepted"] is False
    assert res["enqueued_proactive"] is False
    assert res["stream_chat_delivered"] is False
    assert res["channels"] == []
    assert len(res["errors"]) > 0


def test_companion_server_broadcast_event_no_channels() -> None:
    server = CompanionServer.__new__(CompanionServer)
    server.proactive_feed = None
    server.stream_chat_event_sink = None

    res = server.broadcast_event({"text": "Hello world"})
    assert res["accepted"] is False
    assert res["enqueued_proactive"] is False
    assert res["stream_chat_delivered"] is False
    assert res["channels"] == []


def test_companion_server_broadcast_event_proactive_feed_success() -> None:
    server = CompanionServer.__new__(CompanionServer)
    feed = DummyFeed()
    server.proactive_feed = feed
    server.stream_chat_event_sink = None

    payload = {"text": "Проактивное сообщение", "speak": False}
    res = server.broadcast_event(payload)

    assert res["accepted"] is True
    assert res["enqueued_proactive"] is True
    assert res["stream_chat_delivered"] is False
    assert res["channels"] == ["proactive_feed"]
    assert res["errors"] == []

    assert len(feed.enqueued) == 1
    assert feed.enqueued[0]["text"] == "Проактивное сообщение"
    assert feed.enqueued[0]["speak"] is False


def test_companion_server_broadcast_event_proactive_feed_failure() -> None:
    server = CompanionServer.__new__(CompanionServer)
    feed = DummyFeed(should_fail=True)
    server.proactive_feed = feed
    server.stream_chat_event_sink = None

    res = server.broadcast_event({"text": "Сообщение"})
    assert res["accepted"] is False
    assert res["enqueued_proactive"] is False
    assert len(res["errors"]) == 1
    assert "DummyFeed enqueue failed" in res["errors"][0]


def test_companion_server_broadcast_event_sink_failure_unaccepted() -> None:
    server = CompanionServer.__new__(CompanionServer)
    server.proactive_feed = None
    sink = DummySink(should_fail=True)
    server.stream_chat_event_sink = sink

    res = server.broadcast_event({"text": "Событие для чата"})
    assert res["accepted"] is False
    assert res["stream_chat_delivered"] is False
    assert len(res["errors"]) == 1
    assert "DummySink failed" in res["errors"][0]


def test_companion_server_broadcast_event_both_channels() -> None:
    server = CompanionServer.__new__(CompanionServer)
    feed = DummyFeed()
    sink = DummySink()
    server.proactive_feed = feed
    server.stream_chat_event_sink = sink

    res = server.broadcast_event({"text": "Двойная доставка"})
    assert res["accepted"] is True
    assert res["enqueued_proactive"] is True
    assert res["stream_chat_delivered"] is True
    assert set(res["channels"]) == {"proactive_feed", "stream_chat_event_sink"}


def test_companion_server_broadcast_event_no_false_speaking() -> None:
    import threading
    server = CompanionServer.__new__(CompanionServer)
    server._avatar_audio_lock = threading.Lock()
    server._avatar_audio = {
        "schema_version": 1,
        "amplitude": 0.0,
        "speaking": False,
        "timestamp_ms": 0,
        "updated_at": 0.0,
    }
    server.proactive_feed = DummyFeed()
    server.stream_chat_event_sink = None

    # Even with data_base64 and type=audio, speaking must NOT be True without active playback!
    payload_without_playback = {
        "text": "Сообщение с аудио",
        "type": "audio",
        "data_base64": "UklGRg==",
        "amplitude": 0.6,
    }
    server.broadcast_event(payload_without_playback)
    assert server.avatar_audio()["speaking"] is False

    # Only when playback is explicitly confirmed active (e.g. playback_active=True or is_playing=True)
    payload_with_playback = {
        "text": "Реальное воспроизведение",
        "type": "audio",
        "playback_active": True,
        "is_playing": True,
        "amplitude": 0.7,
    }
    server.broadcast_event(payload_with_playback)
    assert server.avatar_audio()["speaking"] is True
    assert server.avatar_audio()["amplitude"] == 0.7


def test_bridge_single_speech_owner_client_deferred() -> None:
    """When no local player is provided, bridge MUST NOT do redundant TTS synthesis,
    and MUST report audio_delivered=False with audio_playback_ack='deferred_to_client'."""
    tts_mock = MagicMock()
    broadcast_mock = MagicMock()
    broadcast_mock.return_value = {
        "accepted": True,
        "enqueued_proactive": True,
        "stream_chat_delivered": False,
        "channels": ["proactive_feed"],
        "errors": [],
    }

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=None,
        tts_service=tts_mock,
        audio_player=None,
        broadcast_fn=broadcast_mock,
    )

    decision = CognitiveTurnDecision(
        action="backchannel",
        backchannel_cue="Да, слушаю",
    )

    result = bridge.process_turn_decision(decision)

    assert result["dispatched"] is True
    assert result["text_generated"] is True
    assert result["transport_dispatched"] is True
    assert result["queued"] is True
    # Zero TTS calls on server!
    assert tts_mock.synthesize.call_count == 0
    assert result["audio_synthesized"] is False
    # Strictly False audio_delivered
    assert result["audio_delivered"] is False
    assert result["audio_playback_ack"] == "deferred_to_client"
    assert result["audio_bytes"] == 0

    # Ensure broadcast_mock was called with speak=True and type=text
    call_payload = broadcast_mock.call_args[0][0]
    assert call_payload["text"] == "Да, слушаю"
    assert call_payload["type"] == "text"
    assert call_payload["speak"] is True


def test_bridge_single_speech_owner_local_player_confirmed() -> None:
    """When a local player is provided, server synthesizes and plays audio.
    Client broadcast gets speak=False so Electron doesn't duplicate speech."""
    tts_mock = MagicMock()
    tts_mock.synthesize.return_value = b"RIFF1234WAVE"
    player_mock = MagicMock()
    broadcast_mock = MagicMock()
    broadcast_mock.return_value = {
        "accepted": True,
        "enqueued_proactive": True,
        "stream_chat_delivered": False,
        "channels": ["proactive_feed"],
        "errors": [],
    }

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=None,
        tts_service=tts_mock,
        audio_player=player_mock,
        broadcast_fn=broadcast_mock,
    )

    decision = CognitiveTurnDecision(
        action="backchannel",
        backchannel_cue="Локальное воспроизведение",
    )

    result = bridge.process_turn_decision(decision)

    assert result["dispatched"] is True
    assert result["text_generated"] is True
    assert tts_mock.synthesize.call_count == 1
    assert player_mock.play_bytes.call_count == 1
    assert result["audio_synthesized"] is True
    assert result["audio_delivered"] is True
    assert result["audio_playback_ack"] == "confirmed"
    assert result["audio_bytes"] == len(b"RIFF1234WAVE")

    # Broadcast payload instructs client NOT to synthesize
    call_payload = broadcast_mock.call_args[0][0]
    assert call_payload["speak"] is False
    assert call_payload["playback_active"] is True


def test_bridge_broadcast_failure_unaccepted() -> None:
    """When broadcast_fn reports accepted=False, bridge sets transport_dispatched=False."""
    broadcast_mock = MagicMock()
    broadcast_mock.return_value = {
        "accepted": False,
        "enqueued_proactive": False,
        "stream_chat_delivered": False,
        "channels": [],
        "errors": ["No active channels"],
    }

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=None,
        tts_service=None,
        audio_player=None,
        broadcast_fn=broadcast_mock,
    )

    decision = CognitiveTurnDecision(
        action="backchannel",
        backchannel_cue="Текст без получателя",
    )

    result = bridge.process_turn_decision(decision)
    assert result["dispatched"] is True
    assert result["transport_dispatched"] is False
    assert result["queued"] is False
    assert result["audio_delivered"] is False
    assert result["audio_playback_ack"] == "none"


def test_bridge_dnd_active_suppression() -> None:
    """When DND is active, turn must be suppressed with path='suppressed_dnd' and reason='dnd_active'."""
    fusion = PerceptionFusion()
    fusion.dnd = True

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=None,
        perception_fusion=fusion,
    )

    decision = CognitiveTurnDecision(
        action="proactive_turn",
        proactive_packet={"prompt": "Привет в режиме 'не беспокоить'"},
    )

    result = bridge.process_turn_decision(decision)
    assert result["dispatched"] is False
    assert result["path"] == "suppressed_dnd"
    assert result["reason"] == "dnd_active"
    assert result["speech_output"] is None
    assert result["audio_delivered"] is False


def test_bridge_priority_proactive_passed_and_unadmitted_handled() -> None:
    """SenseNovaPerceptionBridge passes priority=TurnPriority.PROACTIVE to client.handle_text,
    and respects admitted=False."""
    client_mock = MagicMock()
    client_mock.handle_text.return_value = {
        "admitted": False,
        "text": "Ignored text",
    }

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=client_mock,
    )

    decision = CognitiveTurnDecision(
        action="proactive_turn",
        proactive_packet={"prompt": "Хорошая погода"},
    )

    result = bridge.process_turn_decision(decision)
    assert client_mock.handle_text.call_count == 1
    call_kwargs = client_mock.handle_text.call_args[1]
    assert call_kwargs.get("priority") == TurnPriority.PROACTIVE

    # Since admitted was False, no text should be generated
    assert result["llm_invoked"] is False
    assert result["text_generated"] is False
    assert result["dispatched"] is False
    assert result["speech_output"] is None
