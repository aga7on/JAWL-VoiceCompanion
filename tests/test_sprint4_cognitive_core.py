"""Comprehensive unit tests for Sprint 4 (Когнитивное ядро):
1. Multilingual Visual Memory & Visual Recall loop (jina-clip-v1 / SigLIP multilingual)
2. Valence DSP (Spectral Centroid + Autocorrelation HNR) & Music Taste Profile
3. A-MEM Narrative Consolidator (Story line + Character Cards)
4. SenseNova Perception Fusion Closure (Fast backchannel spike vs Proactive turn package)
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image
import pytest

from jawl_voicecompanion.affective_engine import AffectiveEngine
from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory, recall_visual_detail
from jawl_voicecompanion.narrative_consolidator import NarrativeConsolidator
from jawl_voicecompanion.perception_fusion import (
    CognitiveTurnDecision,
    PerceptionFusion,
    SenseNovaPerceptionBridge,
)


@pytest.fixture
def temp_core_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sprint4_core"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 1. Multilingual Visual Memory & Visual Recall
def test_sprint4_multilingual_visual_memory_and_recall(temp_core_dir: Path) -> None:
    db_path = temp_core_dir / "lancedb"
    mem = EpisodicVisualMemory(db_path=db_path)

    # Ingest keyframe with Russian annotations
    frame = Image.new("RGB", (80, 80), color="crimson")
    mem.ingest_keyframe(
        frame,
        scene_id="scene_scar_hero",
        summary="Беловолосый воин со шрамом на лице",
        speech_context="Я защищу эту крепость!",
        valence=0.4,
        arousal=0.8,
    )

    assert mem.count() == 1

    # Visual search with Russian query
    results = mem.search_visual("беловолосый воин", top_k=1)
    assert len(results) == 1
    assert results[0]["scene_id"] == "scene_scar_hero"
    assert "воин" in results[0]["summary"]

    # Visual Recall Loop with mock VLM
    calls = []

    class MockVLM:
        def analyze_images(self, images: list[str], prompt: str) -> str:
            calls.append((images, prompt))
            return f"VLM analysis: {len(images)} images checked. Result: шрам виден на правой щеке."

    vlm = MockVLM()
    recall_resp = mem.recall_visual_detail("какой у него шрам?", vlm_client=vlm, top_k=1)
    assert len(calls) == 1
    assert "шрам виден на правой щеке" in recall_resp

    # Functional recall wrapper
    func_resp = recall_visual_detail("воин со шрамом", vlm, memory=mem)
    assert "шрам виден на правой щеке" in func_resp


# 2. Valence DSP (Centroid + HNR) & Music Taste Profile
def test_sprint4_valence_dsp_and_taste_profile(temp_core_dir: Path) -> None:
    db_path = temp_core_dir / "lancedb_taste"
    mem = EpisodicVisualMemory(db_path=db_path)
    engine = AffectiveEngine(episodic_memory=mem)

    # Clean harmonic signal (1000 Hz) -> Bright/harmonic -> Positive Valence
    t = np.linspace(0, 4096 / 44100, 4096)
    harmonic_pcm = (np.sin(2 * np.pi * 1000 * t) * 22000).astype(np.int16).tobytes()

    st_harm = engine.process_pcm_chunk(harmonic_pcm)
    assert 800.0 <= st_harm["centroid_hz"] <= 3500.0
    assert st_harm["hnr"] > 0.4
    assert st_harm["dsp_valence"] > 0.0
    assert engine.valence >= 0.0

    # Screeching high-frequency harsh noise (> 6000 Hz) -> Negative Valence
    screech_pcm = (np.sin(2 * np.pi * 7000 * t) * 25000 + np.random.uniform(-5000, 5000, 4096)).astype(np.int16).tobytes()
    st_screech = engine.process_pcm_chunk(screech_pcm)
    assert st_screech["centroid_hz"] > 5000.0
    assert st_screech["dsp_valence"] < 0.0

    # Save music taste profile
    taste_sample = engine.sample_music_taste(
        samples=np.frombuffer(harmonic_pcm, dtype=np.int16).astype(np.float32) / 32768.0,
        smtc_info={
            "has_active_playback": True,
            "title": "Starboy",
            "artist": "The Weeknd",
            "album": "Starboy",
        },
        force=True,
    )
    assert taste_sample is not None
    assert taste_sample["status"] == "saved"
    assert taste_sample["track"] == "Starboy"

    records = mem.get_recent_taste_records(limit=5)
    assert len(records) == 1
    assert records[0]["track_title"] == "Starboy"
    assert records[0]["artist"] == "The Weeknd"
    assert len(records[0]["audio_vector"]) == 16


# 3. A-MEM Narrative Consolidator
def test_sprint4_narrative_consolidator() -> None:
    class MockSenseNovaLLM:
        def chat(self, messages: list[dict[str, str]]) -> str:
            return (
                '{"episode_log": "18:05 — Герой победил темного мага в башне.", '
                '"updated_entities": [{"name": "Темный маг", "new_trait": "повержен", "keyframe_id": "frm_boss"}]}'
            )

    nc = NarrativeConsolidator(llm_client=MockSenseNovaLLM(), consolidation_interval_sec=10.0)
    nc.feed_subtitle("Ты заплатишь за всё, маг!", speaker="Hero")
    nc.feed_keyframe("frm_boss", "cache/boss.webp", summary="Темный маг повержен")

    res = nc.consolidate(force=True)
    assert res is not None
    assert "победил темного мага" in res["episode_log"]
    assert len(res["updated_entities"]) == 1

    cards = nc.get_character_cards()
    assert len(cards) == 1
    assert cards[0]["name"] == "Темный маг"
    assert "повержен" in cards[0]["traits"]
    assert nc.get_last_story_line() == "18:05 — Герой победил темного мага в башне."


# 4. Perception Closure on SenseNova (Fast-path backchannel vs Proactive turn)
def test_sprint4_sensenova_perception_bridge() -> None:
    fusion = PerceptionFusion()
    engine = AffectiveEngine()

    llm_calls = []

    class MockSenseNovaClient:
        def complete(self, prompt: str) -> str:
            llm_calls.append(prompt)
            return "Ого, битва в самом разгаре! Держись крепче."

    bridge = SenseNovaPerceptionBridge(
        sensenova_client=MockSenseNovaClient(),
        perception_fusion=fusion,
    )

    # 4a. Fast-Path Backchannel on High Acoustic Spike (delta_arousal >= 0.35)
    # Heavy LLM MUST NOT be invoked!
    spike_decision = fusion.evaluate_cognitive_turn(
        affective_engine=engine,
        delta_arousal=0.45,  # >= 0.35 threshold
    )
    assert spike_decision.action == "backchannel"
    assert spike_decision.backchannel_cue is not None

    res_spike = bridge.process_turn_decision(spike_decision)
    assert res_spike["dispatched"] is True
    assert res_spike["path"] == "fast_backchannel"
    assert res_spike["llm_invoked"] is False
    assert len(llm_calls) == 0
    assert res_spike["speech_output"] == spike_decision.backchannel_cue

    # 4b. Full Proactive Turn Package on Silence Gap (>= 1.5s)
    nc = NarrativeConsolidator()
    nc._episode_logs.append("20:15 — Отряд остановился на ночлег у реки.")

    proactive_decision = fusion.evaluate_cognitive_turn(
        affective_engine=engine,
        narrative_consolidator=nc,
        force_proactive=True,  # Simulate >= 1.5s silence gap
    )
    assert proactive_decision.action == "proactive_turn"
    assert proactive_decision.proactive_packet is not None
    assert "ночлег у реки" in proactive_decision.proactive_packet["prompt"]

    # 4c. Verify TTS Synthesis & Delivery tracking in SenseNovaPerceptionBridge
    synthesized_prompts = []
    delivered_payloads = []
    played_audio = []

    class MockTTS:
        def synthesize(self, text: str, emotion: dict[str, Any] | None = None) -> bytes:
            synthesized_prompts.append(text)
            return b"RIFF....WAVEfmt ...."

    class MockAudioPlayer:
        def play_bytes(self, wav: bytes) -> None:
            played_audio.append(wav)

    def mock_broadcast(payload: dict[str, Any]) -> dict[str, Any]:
        delivered_payloads.append(payload)
        return {
            "accepted": True,
            "enqueued_proactive": True,
            "stream_chat_delivered": False,
            "channels": ["proactive_feed"],
            "errors": [],
        }

    # Case 1: Local audio player configured (local speech owner)
    bridge_with_player = SenseNovaPerceptionBridge(
        sensenova_client=MockSenseNovaClient(),
        perception_fusion=fusion,
        tts_service=MockTTS(),
        audio_player=MockAudioPlayer(),
        broadcast_fn=mock_broadcast,
    )

    res_local_audio = bridge_with_player.process_turn_decision(spike_decision)
    assert res_local_audio["dispatched"] is True
    assert res_local_audio["text_generated"] is True
    assert res_local_audio["audio_synthesized"] is True
    assert res_local_audio["audio_delivered"] is True
    assert res_local_audio["audio_playback_ack"] == "confirmed"
    assert res_local_audio["audio_bytes"] > 0
    assert len(synthesized_prompts) == 1
    assert synthesized_prompts[0] == spike_decision.backchannel_cue
    assert len(played_audio) == 1
    assert len(delivered_payloads) == 1
    assert delivered_payloads[0]["media_type"] == "audio/wav"
    assert delivered_payloads[0]["text"] == spike_decision.backchannel_cue
    assert delivered_payloads[0]["speak"] is False  # Local player handled it, don't re-speak on client!

    # Case 2: No local player -> deferred to client (single speech owner, NO redundant TTS synthesis)
    synthesized_prompts.clear()
    delivered_payloads.clear()

    bridge_client_speech = SenseNovaPerceptionBridge(
        sensenova_client=MockSenseNovaClient(),
        perception_fusion=fusion,
        tts_service=MockTTS(),
        audio_player=None,
        broadcast_fn=mock_broadcast,
    )

    res_client_audio = bridge_client_speech.process_turn_decision(spike_decision)
    assert res_client_audio["dispatched"] is True
    assert res_client_audio["text_generated"] is True
    assert res_client_audio["transport_dispatched"] is True
    assert res_client_audio["queued"] is True
    assert res_client_audio["audio_synthesized"] is False  # No redundant server synthesis!
    assert res_client_audio["audio_delivered"] is False    # Audio playback ACK strictly False
    assert res_client_audio["audio_playback_ack"] == "deferred_to_client"
    assert len(synthesized_prompts) == 0                   # 0 synthesis calls on server!
    assert len(delivered_payloads) == 1
    assert delivered_payloads[0]["type"] == "text"
    assert delivered_payloads[0]["speak"] is True


# 5. SMTC Kernel Playback & Ambient Audio Wiring
def test_sprint4_smtc_ambient_audio_wiring() -> None:
    from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge
    from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer

    fusion = PerceptionFusion()

    # 5a. Direct observe_smtc in PerceptionFusion
    track_payload = {
        "available": True,
        "has_active_playback": True,
        "title": "Nightcall",
        "artist": "Kavinsky",
        "album": "OutRun",
        "app_id": "Spotify.exe",
        "playback_status": "Playing",
    }
    ok = fusion.observe_smtc(track_payload)
    assert ok is True
    music_state = fusion.current_state("music")
    assert music_state["fresh"] is True
    assert music_state["hypothesis"] is False
    assert music_state["metadata"]["verified"] is True
    assert music_state["metadata"]["title"] == "Nightcall"
    assert "Nightcall" in fusion.compose()

    # 5b. AmbientAudioASRBridge integration with mock SMTC adapter
    class MockSMTCAdapter:
        def __init__(self, track: dict[str, Any]):
            self._track = track

        def poll(self, force: bool = False) -> dict[str, Any]:
            return self._track

    class DummyVoiceMem:
        def feed_audio(self, *args: Any, **kwargs: Any) -> None:
            pass

        def end_audio(self, *args: Any, **kwargs: Any) -> None:
            pass

    smtc_adapter = MockSMTCAdapter(track_payload)
    memory = AmbientMemoryBuffer(enabled=True)
    fusion2 = PerceptionFusion()

    bridge = AmbientAudioASRBridge(
        DummyVoiceMem(),
        memory,
        perception_fusion=fusion2,
        smtc_adapter=smtc_adapter,
    )

    polled = bridge.poll_smtc()
    assert polled is not None
    assert polled["title"] == "Nightcall"
    assert fusion2.current_state("music")["fresh"] is True
    assert fusion2.current_state("music")["metadata"]["verified"] is True
    assert "Nightcall" in fusion2.compose()

    # 5c. Strict gating: Paused status MUST NOT be reported as active playback
    paused_payload = dict(track_payload)
    paused_payload["playback_status"] = "Paused"
    paused_payload["has_active_playback"] = False
    paused_payload["is_playing"] = False

    fusion3 = PerceptionFusion()
    ok_paused = fusion3.observe_smtc(paused_payload)
    assert ok_paused is False
    assert fusion3.current_state("music")["fresh"] is False

    # 5d. Test WindowsSMTCAdapter session resolution and status gating
    from jawl_voicecompanion.windows_smtc import WindowsSMTCAdapter
    adapter = WindowsSMTCAdapter()

    class FakeMediaProps:
        title = "Get Lucky"
        artist = "Daft Punk"
        album_title = "Random Access Memories"

    class FakePlaybackInfo:
        def __init__(self, status_code: int):
            self.playback_status = status_code

    class FakeSession:
        def __init__(self, aumid: str, status_code: int):
            self.source_app_user_model_id = aumid
            self._status = status_code

        def get_playback_info(self):
            return FakePlaybackInfo(self._status)

        async def try_get_media_properties_async(self):
            return FakeMediaProps()

    class FakeSessionManager:
        def __init__(self, sessions):
            self._sessions = sessions

        def get_sessions(self):
            return self._sessions

        def get_current_session(self):
            return self._sessions[0] if self._sessions else None

    # Test playing session (status 4)
    playing_session = FakeSession("Spotify.exe", 4)
    fake_mgr = FakeSessionManager([playing_session])

    import asyncio
    import jawl_voicecompanion.windows_smtc as smtc_mod

    orig_win_control = getattr(smtc_mod, "win_media_control", None)
    orig_avail = getattr(smtc_mod, "_WINSDK_SMTC_AVAILABLE", True)

    class FakeWinMediaControl:
        class GlobalSystemMediaTransportControlsSessionManager:
            @staticmethod
            async def request_async():
                return fake_mgr

    try:
        smtc_mod.win_media_control = FakeWinMediaControl
        smtc_mod._WINSDK_SMTC_AVAILABLE = True

        # Playing -> has_active_playback: True
        res_playing = asyncio.run(adapter._async_poll())
        assert res_playing["has_active_playback"] is True
        assert res_playing["is_playing"] is True
        assert res_playing["playback_status"] == "Playing"
        assert res_playing["title"] == "Get Lucky"

        # Paused (status 5) -> has_active_playback: False, even though title is present
        paused_session = FakeSession("Spotify.exe", 5)
        fake_mgr._sessions = [paused_session]
        res_paused = asyncio.run(adapter._async_poll())
        assert res_paused["has_active_playback"] is False
        assert res_paused["is_playing"] is False
        assert res_paused["playback_status"] == "Paused"
        assert res_paused["title"] == "Get Lucky"

        # Target app matching
        browser_session = FakeSession("chrome.exe", 4)
        spotify_paused = FakeSession("Spotify.exe", 5)
        fake_mgr._sessions = [spotify_paused, browser_session]

        # Target spotify -> returns spotify (paused)
        res_target_spotify = asyncio.run(adapter._async_poll(target_app="spotify.exe"))
        assert res_target_spotify["target_app_matched"] is True
        assert res_target_spotify["has_active_playback"] is False
        assert res_target_spotify["app_id"] == "Spotify.exe"

        # Target chrome -> returns chrome (playing)
        res_target_chrome = asyncio.run(adapter._async_poll(target_app="chrome.exe"))
        assert res_target_chrome["target_app_matched"] is True
        assert res_target_chrome["has_active_playback"] is True
        assert res_target_chrome["app_id"] == "chrome.exe"

        # P1 Target unmatched (game.exe with only spotify playing): MUST NOT leak active playback
        fake_mgr._sessions = [FakeSession("Spotify.exe", 4)]
        res_target_game = asyncio.run(adapter._async_poll(target_app="game.exe"))
        assert res_target_game["target_app_matched"] is False
        assert res_target_game["has_active_playback"] is False
        assert res_target_game["is_playing"] is False
        assert res_target_game["system_media"]["has_active_playback"] is True
        assert res_target_game["system_media"]["app_id"] == "Spotify.exe"
    finally:
        smtc_mod.win_media_control = orig_win_control
        smtc_mod._WINSDK_SMTC_AVAILABLE = orig_avail


def test_sprint4_memory_delete_keyframe_boundary_confinement(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside-cache.webp"
    outside.write_bytes(b"canary-payload")

    mem = EpisodicVisualMemory(db_path=tmp_path / "lancedb", image_cache_dir=cache)
    # Attempt to delete file outside cache directory
    result = mem.delete_keyframe(image_path=str(outside))
    assert result is False
    assert outside.exists(), "Outside canary file must NOT be deleted by delete_keyframe"

    # Now verify in-cache deletion works
    inside = cache / "scene1_1000.webp"
    inside.write_bytes(b"inside-payload")
    del_inside = mem.delete_keyframe(image_path=str(inside))
    assert del_inside is True
    assert not inside.exists(), "File inside cache directory should be successfully deleted"


def test_sprint4_perception_bridge_and_companion_server_contract() -> None:
    from jawl_voicecompanion.gateway import TextGateway
    from jawl_voicecompanion.web import CompanionServer

    # CompanionServer must expose broadcast_event
    assert hasattr(CompanionServer, "broadcast_event")

    # Bridge delivery facts
    bridge = SenseNovaPerceptionBridge(sensenova_client=None, tts_service=None)
    decision = CognitiveTurnDecision(action="proactive_turn", proactive_packet={"prompt": "test"})
    res = bridge.process_turn_decision(decision)

    assert res["llm_invoked"] is False
    assert res["audio_synthesized"] is False
    assert res["audio_delivered"] is False
    assert res["audio_bytes"] == 0
    assert res["speech_output"] is None


def test_proactive_does_not_cancel_active_user_turn_and_responder_blocked() -> None:
    from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority
    from jawl_voicecompanion.gateway import TextGateway

    arbiter = TurnArbiter()
    responder_called = []

    class MockResponder:
        def respond(self, text: str) -> str:
            responder_called.append(text)
            return "Ответ на команду"

    gateway = TextGateway(responder=MockResponder(), arbiter=arbiter)

    # 1. User starts speaking / final user turn begins
    user_token = arbiter.begin(TurnPriority.USER_FINAL)
    assert arbiter.is_current(user_token) is True
    assert user_token.cancelled is False

    # 2. Perception bridge attempts proactive turn while USER_FINAL is active
    bridge = SenseNovaPerceptionBridge(sensenova_client=gateway)
    decision = CognitiveTurnDecision(action="proactive_turn", proactive_packet={"prompt": "Привет!"})
    res = bridge.process_turn_decision(decision)

    # 3. CRITICAL: user_token MUST NOT be cancelled!
    assert user_token.cancelled is False, "Active USER_FINAL token was cancelled by proactive turn!"
    assert arbiter.is_current(user_token) is True

    # 4. Responder MUST NOT have been invoked!
    assert len(responder_called) == 0, f"Responder was unexpectedly invoked: {responder_called}"

    # 5. Delivery facts: bridge must report not invoked and not delivered
    assert res["llm_invoked"] is False
    assert res["dispatched"] is False
    assert res["audio_delivered"] is False


def test_dnd_boundary_suppresses_proactive_turn() -> None:
    from jawl_voicecompanion.perception_fusion import PerceptionFusion, SenseNovaPerceptionBridge, CognitiveTurnDecision

    # 1. evaluate_cognitive_turn under dnd=True
    pf = PerceptionFusion()
    dec_dnd = pf.evaluate_cognitive_turn(
        force_proactive=True,
        dnd=True,
    )
    assert dec_dnd.action == "none"
    assert dec_dnd.reason == "dnd_active"

    # 2. Bridge execution under DND
    bridge = SenseNovaPerceptionBridge(sensenova_client=None)
    dec_proactive = CognitiveTurnDecision(action="proactive_turn", proactive_packet={"prompt": "Hello", "dnd": True})
    res = bridge.process_turn_decision(dec_proactive)
    assert res["dispatched"] is False
    assert res["path"] == "suppressed_dnd"
    assert res["reason"] == "dnd_active"
    assert res["llm_invoked"] is False
    assert res["audio_delivered"] is False


def test_single_speech_owner_text_queue_vs_local_audio_player() -> None:
    from jawl_voicecompanion.perception_fusion import SenseNovaPerceptionBridge, CognitiveTurnDecision

    # Dummy client that returns text
    class FakeClient:
        def handle_text(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {"text": "Проактивный ответ", "admitted": True}

    # Tracking TTS
    tts_calls = []
    class FakeTTS:
        def synthesize(self, text: str, emotion: Any = None) -> bytes:
            tts_calls.append(text)
            return b"RIFF....WAVE"

    # Tracking broadcast
    bcast_payloads = []
    def fake_bcast(payload: dict[str, Any]) -> dict[str, Any]:
        bcast_payloads.append(payload)
        return {"accepted": True, "enqueued_proactive": True, "channels": ["proactive_feed"], "errors": []}

    # Tracking player
    player_plays = []
    class FakePlayer:
        def play_bytes(self, data: bytes) -> None:
            player_plays.append(data)

    decision = CognitiveTurnDecision(action="proactive_turn", proactive_packet={"prompt": "Что нового?"})

    # Case A: NO local audio player (Desktop client is speech owner via proactive_feed)
    bridge_client_owner = SenseNovaPerceptionBridge(
        sensenova_client=FakeClient(),
        tts_service=FakeTTS(),
        broadcast_fn=fake_bcast,
        audio_player=None,  # No server player
    )
    res_client = bridge_client_owner.process_turn_decision(decision)

    # Server MUST NOT synthesize TTS when desktop is speech owner
    assert len(tts_calls) == 0, "TTS was synthesized on server when client owns speech!"
    assert res_client["audio_synthesized"] is False
    assert res_client["audio_delivered"] is False, "audio_delivered must not be True without confirmed playback"
    assert res_client["queued"] is True
    assert res_client["transport_dispatched"] is True
    assert res_client["audio_playback_ack"] == "deferred_to_client"
    assert bcast_payloads[-1]["speak"] is True, "Client should be told to speak"

    # Case B: Local audio player present (Server owns speech playback)
    tts_calls.clear()
    bcast_payloads.clear()
    player = FakePlayer()

    bridge_server_owner = SenseNovaPerceptionBridge(
        sensenova_client=FakeClient(),
        tts_service=FakeTTS(),
        broadcast_fn=fake_bcast,
        audio_player=player,
    )
    res_server = bridge_server_owner.process_turn_decision(decision)

    # Server MUST synthesize and play via player
    assert len(tts_calls) == 1
    assert len(player_plays) == 1
    assert res_server["audio_synthesized"] is True
    assert res_server["audio_delivered"] is True
    assert res_server["audio_playback_ack"] == "confirmed"
    # Broadcast to UI must set speak=False to avoid duplicate synthesis in desktop app!
    assert bcast_payloads[-1]["speak"] is False


def test_companion_server_broadcast_event_contract_and_error_propagation() -> None:
    import threading
    from jawl_voicecompanion.web import CompanionServer

    # Subclass with mocked socket/init to test broadcast_event directly
    class TestableCompanionServer(CompanionServer):
        def __init__(self) -> None:
            self.proactive_feed = None
            self.stream_chat_event_sink = None
            self._avatar_audio_lock = threading.Lock()
            self._avatar_audio = {"amplitude": 0.0, "speaking": False}

    srv = TestableCompanionServer()

    # 1. Missing feed and sink -> rejected with accepted=False
    res_empty = srv.broadcast_event({"text": "Привет"})
    assert res_empty["accepted"] is False
    assert len(res_empty["channels"]) == 0

    # 2. Sink raises exception -> captured in errors, accepted=False
    def failing_sink(p: dict[str, Any]) -> None:
        raise RuntimeError("Network socket broken")

    srv.stream_chat_event_sink = failing_sink
    res_err = srv.broadcast_event({"text": "Тест сбоя"})
    assert res_err["accepted"] is False
    assert any("Network socket broken" in err for err in res_err["errors"])

    # 3. Successful feed enqueue -> accepted=True
    enqueued = []
    class FakeFeed:
        def _enqueue(self, item: dict[str, Any]) -> None:
            enqueued.append(item)

    srv.proactive_feed = FakeFeed()
    res_ok = srv.broadcast_event({"text": "Успешное сообщение", "speak": True})
    assert res_ok["accepted"] is True
    assert res_ok["enqueued_proactive"] is True
    assert "proactive_feed" in res_ok["channels"]
    assert len(enqueued) == 1
    assert enqueued[0]["text"] == "Успешное сообщение"
    assert enqueued[0]["speak"] is True


def test_episodic_memory_scene_prefix_isolation_and_ingest_sanitization(tmp_path: Path) -> None:
    from PIL import Image
    db_path = tmp_path / "lancedb_core"
    cache_dir = tmp_path / "cache_core"
    mem = EpisodicVisualMemory(db_path=db_path, image_cache_dir=cache_dir)

    img = Image.new("RGB", (32, 32), color="blue")

    # Ingest scene 'a' and scene 'a_b'
    res_a = mem.ingest_keyframe(img, scene_id="a", summary="Scene A")
    res_ab = mem.ingest_keyframe(img, scene_id="a_b", summary="Scene A_B")

    file_a = Path(res_a["image_path"])
    file_ab = Path(res_ab["image_path"])
    assert file_a.exists()
    assert file_ab.exists()

    # Deleting scene 'a' must NOT delete file of scene 'a_b'
    del_res = mem.delete_keyframe(scene_id="a")
    assert del_res is True
    assert not file_a.exists(), "Scene 'a' file was not deleted"
    assert file_ab.exists(), "Scene 'a' deletion falsely deleted scene 'a_b'!"

    # Traversal sanitization
    res_trav = mem.ingest_keyframe(img, scene_id="../../../etc/passwd", summary="Traversal")
    trav_p = Path(res_trav["image_path"])
    assert trav_p.is_relative_to(cache_dir.resolve())
    assert trav_p.parent == cache_dir.resolve()




