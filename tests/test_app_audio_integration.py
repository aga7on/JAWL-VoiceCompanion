import json
import time
import threading
import pytest
from unittest.mock import MagicMock
from jawl_voicecompanion.app_audio_router import (
    AppAudioRouter,
    AppAudioSession,
    MODE_ALL_EXCEPT_SELF,
    MODE_TARGET_APP,
    MODE_ALL,
)
from jawl_voicecompanion.ambient_segments import AmbientSegmenter, AmbientSegment
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge
from jawl_voicecompanion.web import create_server
from urllib.request import Request, urlopen
from http import HTTPStatus


def test_segmenter_attribution():
    emitted = []
    def on_segment(seg: AmbientSegment):
        emitted.append(seg)

    segmenter = AmbientSegmenter(on_segment, max_segment_bytes=1024, max_segment_seconds=0.1)
    segmenter.start("test-session")
    pcm = b"\x01\x00" * 1600
    res = segmenter.submit(
        pcm, 16000, 1,
        app_name="firefox.exe",
        app_category="browser_youtube",
        app_title="Rick Astley - Never Gonna Give You Up - YouTube",
        app_pid=1234
    )
    assert res["status"] == "accepted"
    segmenter.stop(flush=True)

    assert len(emitted) >= 1
    seg = emitted[0]
    assert seg.app_name == "firefox.exe"
    assert seg.app_category == "browser_youtube"
    assert "YouTube" in seg.app_title
    assert seg.app_pid == 1234


def test_ambient_bridge_with_app_router_external_app():
    router = AppAudioRouter(exclude_pids={9999})
    router.classify_session = MagicMock(return_value="browser_youtube")
    router.scan_sessions = MagicMock(return_value=[
        AppAudioSession(
            pid=5555,
            name="chrome.exe",
            display_name="Google Chrome",
            window_title="Lofi Hip Hop Radio - YouTube - Google Chrome",
            category="browser_youtube",
            is_self=False,
            peak_level=0.85,
            active=True,
            last_active_monotonic=time.monotonic(),
        )
    ])

    memory = AmbientMemoryBuffer(enabled=True)
    voice_mem = MagicMock()
    voice_mem.feed_audio.return_value = {"status": "ok"}
    voice_mem.end_audio.return_value = {"status": "ok"}

    fusion = MagicMock()
    bridge = AmbientAudioASRBridge(
        voice_mem,
        memory,
        target_sample_rate=16000,
        app_router=router,
        perception_fusion=fusion,
    )

    pcm = b"\x00\x01" * 1600
    res = bridge.consume(pcm, 16000, 1, "session-test")
    assert res["status"] == "accepted"

    test_seg = AmbientSegment(
        segment_id="seg-1",
        session_id="ambient-audio",
        generation="gen-1",
        sequence=0,
        pcm16=pcm,
        sample_rate=16000,
        channels=1,
        started_at=10.0,
        ended_at=10.1,
        app_name="chrome.exe",
        app_category="browser_youtube",
        app_title="Lofi Hip Hop Radio - YouTube - Google Chrome",
        app_pid=5555,
        source_isolated=True,
    )
    bridge._session_id = "ambient-audio"
    bridge._generation = "gen-1"

    commit_res = bridge._commit_transcript(test_seg, "привет это ютуб стрим", confidence=0.9, event_id="ev-1")
    assert commit_res is not None
    assert commit_res["status"] == "retained"

    assert fusion.note.called
    call_args = fusion.note.call_args
    assert call_args[0][0] == "speech"
    assert "[chrome.exe [browser_youtube] (Lofi Hip Hop Radio - YouTube - Google Chrome)]" in call_args[0][1]
    assert call_args[1]["metadata"]["source"] == "app:chrome.exe"
    assert call_args[1]["metadata"]["source_app"] == "chrome.exe"
    assert call_args[1]["metadata"]["app_category"] == "browser_youtube"
    assert call_args[1]["metadata"]["app_pid"] == 5555


def test_mixed_loopback_does_not_claim_active_app_as_confirmed_source():
    memory = AmbientMemoryBuffer(enabled=True)
    fusion = MagicMock()
    voice_mem = MagicMock()
    bridge = AmbientAudioASRBridge(voice_mem, memory, perception_fusion=fusion)
    bridge._session_id, bridge._generation = "ambient-audio", "gen"
    now = time.monotonic()
    segment = AmbientSegment(segment_id="mixed", session_id="ambient-audio", generation="gen",
        sequence=0, pcm16=b"\0\0", sample_rate=16000, channels=1, started_at=now - 1, ended_at=now,
        app_name="chrome.exe", app_pid=5555, source_isolated=False)
    assert bridge._commit_transcript(segment, "В игре начинается новый квест", confidence=0, event_id="mixed")["status"] == "retained"
    args, kwargs = fusion.note.call_args
    assert args[0] == "speech"
    assert "chrome.exe" not in args[1]
    assert kwargs["metadata"]["source"] == "system_audio_loopback"
    assert kwargs["metadata"]["source_app"] is None
    assert kwargs["metadata"]["candidate_app"] == "chrome.exe"
    assert kwargs["metadata"]["source_attribution"] == "mixed_loopback_unconfirmed"
    assert "source_app" not in memory.observations()[0]["payload"]


def test_ambient_bridge_suppresses_self_companion_audio():
    router = AppAudioRouter(exclude_pids={1111})
    router.scan_sessions = MagicMock(return_value=[
        AppAudioSession(
            pid=1111,
            name="python.exe",
            display_name="Python",
            window_title="JAWL Companion TTS Output",
            category="companion_self",
            is_self=True,
            peak_level=0.95,
            active=True,
            last_active_monotonic=time.monotonic(),
        )
    ])

    memory = AmbientMemoryBuffer(enabled=True)
    voice_mem = MagicMock()
    bridge = AmbientAudioASRBridge(
        voice_mem,
        memory,
        target_sample_rate=16000,
        app_router=router,
    )

    pcm = b"\x00\x01" * 1600
    res = bridge.consume(pcm, 16000, 1, "session-test")
    assert res["status"] == "suppressed"
    assert res["reason"] == "self_tts_playback"
    assert bridge.state()["suppressed_self_tts"] >= 1


def test_ambient_bridge_filters_target_app():
    router = AppAudioRouter(exclude_pids={1111})
    router.set_mode(MODE_TARGET_APP)
    router.set_target_app("discord.exe")

    router.scan_sessions = MagicMock(return_value=[
        AppAudioSession(
            pid=2222,
            name="spotify.exe",
            display_name="Spotify",
            window_title="Spotify Free",
            category="media_player",
            is_self=False,
            peak_level=0.8,
            active=True,
            last_active_monotonic=time.monotonic(),
        )
    ])

    memory = AmbientMemoryBuffer(enabled=True)
    voice_mem = MagicMock()
    bridge = AmbientAudioASRBridge(
        voice_mem,
        memory,
        target_sample_rate=16000,
        app_router=router,
    )

    pcm = b"\x00\x01" * 1600
    res = bridge.consume(pcm, 16000, 1, "session-test")
    assert res["status"] == "suppressed"
    assert "target_app_mismatch" in res["reason"]
    assert bridge.state()["suppressed_app_filtered"] >= 1


def test_filtered_app_does_not_leak_to_soundscape_or_streaming_tap():
    router = AppAudioRouter(mode=MODE_TARGET_APP, target_app="discord.exe")
    router.scan_sessions = MagicMock(return_value=[
        AppAudioSession(2222, "spotify.exe", "Spotify", "", "media_player", False, .8, True, time.monotonic())
    ])
    detector = MagicMock()
    bridge = AmbientAudioASRBridge(MagicMock(), AmbientMemoryBuffer(enabled=True),
                                   app_router=router, soundscape_detector=detector)
    tap = MagicMock()
    bridge.stream_tap = tap
    result = bridge.consume(b"\x00\x01" * 1600, 16000, 1, "session-test")
    assert result["status"] == "suppressed"
    tap.assert_not_called()
    assert bridge.state()["soundscape_count"] == 0


def test_web_audio_router_endpoints():
    router = AppAudioRouter(exclude_pids={1111})
    router.scan_sessions = MagicMock(return_value=[
        AppAudioSession(
            pid=3333,
            name="discord.exe",
            display_name="Discord",
            window_title="Discord - Voice Channel",
            category="chat_voip",
            is_self=False,
            peak_level=0.6,
            active=True,
            last_active_monotonic=time.monotonic(),
        )
    ])

    server = create_server(host="127.0.0.1", port=0, app_audio_router=router)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    headers = {
        "X-Companion-Session": server.session_token,
        "X-Companion-CSRF": server.csrf_token,
    }

    try:
        # 1. GET /api/audio/sessions
        req = Request(f"http://127.0.0.1:{port}/api/audio/sessions", headers=headers)
        with urlopen(req, timeout=5) as resp:
            assert resp.status == HTTPStatus.OK
            data = json.loads(resp.read().decode("utf-8"))
            assert data["configured"] is True
            assert data["active_count"] == 1
            assert data["sessions"][0]["name"] == "discord.exe"
            assert data["sessions"][0]["category"] == "chat_voip"

        # 2. GET /api/audio/router
        req = Request(f"http://127.0.0.1:{port}/api/audio/router", headers=headers)
        with urlopen(req, timeout=5) as resp:
            assert resp.status == HTTPStatus.OK
            data = json.loads(resp.read().decode("utf-8"))
            assert data["mode"] == "all_except_self"

        # 3. POST /api/audio/router
        post_headers = dict(headers)
        post_headers["Content-Type"] = "application/json"
        post_data = json.dumps({"mode": "target_app", "target_app": "discord.exe"}).encode("utf-8")
        req = Request(f"http://127.0.0.1:{port}/api/audio/router", data=post_data, headers=post_headers)
        with urlopen(req, timeout=5) as resp:
            assert resp.status == HTTPStatus.OK
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["router"]["mode"] == "target_app"
            assert data["router"]["target_app"] == "discord.exe"
            assert router.mode == MODE_TARGET_APP
            assert router.target_app == "discord.exe"

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_target_pid_calls_live_source_selector():
    router = AppAudioRouter()
    server = create_server(host="127.0.0.1", port=0, app_audio_router=router)
    service = MagicMock()
    service.select_source.return_value = {"capture": {"running": True, "pid": 3333}}
    server.ambient_audio = service
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        headers = {"X-Companion-Session": server.session_token,
                   "X-Companion-CSRF": server.csrf_token,
                   "Content-Type": "application/json"}
        payload = json.dumps({"target_pid": 3333}).encode("utf-8")
        request = Request(f"http://127.0.0.1:{server.server_port}/api/audio/router",
                          data=payload, headers=headers)
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
        service.select_source.assert_called_once_with(3333)
        assert result["ambient_audio"]["capture"]["pid"] == 3333
    finally:
        server.ambient_audio = None
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
