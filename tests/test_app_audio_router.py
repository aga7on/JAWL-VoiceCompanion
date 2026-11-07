import os
import time
import pytest
from jawl_voicecompanion.app_audio_router import (
    AppAudioRouter,
    AppAudioSession,
    MODE_ALL,
    MODE_ALL_EXCEPT_SELF,
    MODE_TARGET_APP,
)


def test_classify_application_domains():
    router = AppAudioRouter()
    assert router.classify_application("firefox.exe", "Rick Astley - Never Gonna Give You Up (Official Music Video) - YouTube") == "browser_youtube"
    assert router.classify_application("chrome.exe", "Dota 2 Finals - Twitch") == "browser_twitch"
    assert router.classify_application("msedge.exe", "Google Search") == "browser"
    assert router.classify_application("discord.exe", "#general | JAWL VoiceCompanion") == "chat_voip"
    assert router.classify_application("telegram.exe", "Voice Chat") == "chat_voip"
    assert router.classify_application("spotify.exe", "Spotify Free") == "media_player"
    assert router.classify_application("vlc.exe", "movie.mkv - VLC media player") == "media_player"
    assert router.classify_application("python.exe", "companion", is_self=True) == "companion_self"


def test_self_pid_detection():
    router = AppAudioRouter(exclude_pids={99999})
    self_pids = router.get_self_pids()
    assert os.getpid() in self_pids
    assert 99999 in self_pids
    assert router.is_self_session(os.getpid(), "python.exe") is True
    assert router.is_self_session(12345, "discord.exe") is False


def test_self_audio_suppression_mock():
    router = AppAudioRouter(mode=MODE_ALL_EXCEPT_SELF, peak_threshold=0.01)
    my_pid = os.getpid()

    # Create mock sessions: one self (speaking), one discord (speaking)
    self_session = AppAudioSession(
        pid=my_pid,
        name="python.exe",
        display_name="Companion TTS",
        window_title="JAWL",
        category="companion_self",
        is_self=True,
        peak_level=0.15,
        active=True,
        last_active_monotonic=time.monotonic(),
    )
    discord_session = AppAudioSession(
        pid=5555,
        name="discord.exe",
        display_name="Discord",
        window_title="Voice Channel",
        category="chat_voip",
        is_self=False,
        peak_level=0.08,
        active=True,
        last_active_monotonic=time.monotonic(),
    )

    # Monkeypatch scan_sessions to return our mock sessions
    router.scan_sessions = lambda now=None: [self_session, discord_session]

    allow, sess, reason = router.filter_and_attribute()
    assert allow is False
    assert sess.is_self is True
    assert reason == "self_audio_suppressed"
    assert router.state()["stats"]["suppressed_self_chunks"] == 1


def test_external_app_attribution_mock():
    router = AppAudioRouter(mode=MODE_ALL_EXCEPT_SELF, peak_threshold=0.01)
    my_pid = os.getpid()

    # Self is quiet, YouTube on Firefox is active
    self_session = AppAudioSession(
        pid=my_pid,
        name="python.exe",
        display_name="Companion",
        window_title="",
        category="companion_self",
        is_self=True,
        peak_level=0.0,
        active=False,
        last_active_monotonic=0.0,
    )
    youtube_session = AppAudioSession(
        pid=33436,
        name="firefox.exe",
        display_name="Firefox",
        window_title="Lecture on Deep Learning - YouTube",
        category="browser_youtube",
        is_self=False,
        peak_level=0.35,
        active=True,
        last_active_monotonic=time.monotonic(),
    )

    router.scan_sessions = lambda now=None: [self_session, youtube_session]

    allow, sess, reason = router.filter_and_attribute()
    assert allow is True
    assert sess.name == "firefox.exe"
    assert sess.category == "browser_youtube"
    assert "YouTube" in sess.window_title
    assert reason == "accepted_non_self_audio"


def test_target_app_filtering():
    router = AppAudioRouter(mode=MODE_TARGET_APP, target_app="discord.exe", peak_threshold=0.01)

    youtube_session = AppAudioSession(
        pid=33436,
        name="firefox.exe",
        display_name="Firefox",
        window_title="Video - YouTube",
        category="browser_youtube",
        is_self=False,
        peak_level=0.25,
        active=True,
        last_active_monotonic=time.monotonic(),
    )
    router.scan_sessions = lambda now=None: [youtube_session]

    # Target is discord.exe, but active is firefox.exe -> should filter out
    allow, sess, reason = router.filter_and_attribute()
    assert allow is False
    assert "target_app_mismatch" in reason

    # Now simulate discord active
    discord_session = AppAudioSession(
        pid=5555,
        name="discord.exe",
        display_name="Discord",
        window_title="General Call",
        category="chat_voip",
        is_self=False,
        peak_level=0.40,
        active=True,
        last_active_monotonic=time.monotonic(),
    )
    router.scan_sessions = lambda now=None: [discord_session]

    allow, sess, reason = router.filter_and_attribute()
    assert allow is True
    assert sess.name == "discord.exe"
    assert reason == "target_app_match"


def test_mixed_sessions_are_not_attributed_to_loudest_app():
    def session(pid, name, peak):
        return AppAudioSession(pid, name, name, "", "desktop_app", False, peak, True, time.monotonic())

    router = AppAudioRouter(mode=MODE_ALL_EXCEPT_SELF)
    router.scan_sessions = lambda now=None: [session(1, "video.exe", .8), session(2, "game.exe", .2)]
    allowed, app, _ = router.filter_and_attribute()
    assert allowed is True
    assert app is None
    assert router.state()["capture_semantics"] == "mixed_output_loopback_not_separate_app_streams"

    router.set_mode(MODE_TARGET_APP)
    router.set_target_app("video.exe")
    allowed, app, reason = router.filter_and_attribute()
    assert (allowed, app, reason) == (False, None, "target_app_mixed_loopback")


def test_silent_session_does_not_reuse_previous_app():
    router = AppAudioRouter()
    active = AppAudioSession(1, "video.exe", "", "", "desktop_app", False, .2, True, time.monotonic())
    router.scan_sessions = lambda now=None: [active]
    assert router.filter_and_attribute()[1] is active
    router.scan_sessions = lambda now=None: []
    assert router.filter_and_attribute()[1] is None
