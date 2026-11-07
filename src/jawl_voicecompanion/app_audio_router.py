"""Smart Windows Application-Aware Audio Router and Session Tracker.

Enables selective listening across applications with automatic self-exclusion
(companion/TTS/runtime suppression) and fine-grained application attribution
(e.g., distinguishing YouTube in a browser, Discord voice chats, media players).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
import sys
import threading
import time
from typing import Any, Callable

try:
    import psutil
except ImportError:
    psutil = None

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

try:
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    _PYCAW_AVAILABLE = True
except Exception:
    _PYCAW_AVAILABLE = False


MODE_ALL_EXCEPT_SELF = "all_except_self"
MODE_TARGET_APP = "target_app"
MODE_ALL = "all"

_VOIP_APPS = {
    "discord.exe", "discordcanary.exe", "discordptb.exe",
    "telegram.exe", "telegramdesktop.exe",
    "slack.exe", "teams.exe", "zoom.exe", "skype.exe",
    "element.exe", "viber.exe", "whatsapp.exe",
}

_BROWSER_APPS = {
    "firefox.exe", "chrome.exe", "msedge.exe", "brave.exe",
    "opera.exe", "operagx.exe", "vivaldi.exe", "yandex.exe",
}

_MEDIA_APPS = {
    "spotify.exe", "vlc.exe", "wmplayer.exe", "foobar2000.exe",
    "aimp.exe", "musicbee.exe", "itunes.exe", "tidal.exe",
    "groove.exe", "audacity.exe",
}

_KNOWN_SELF_NAMES = {
    "python.exe", "pythonw.exe", "node.exe",
    "llama-server.exe", "crispasr.exe", "omnivoice_server.py",
}


@dataclass
class AppAudioSession:
    """Snapshot of a live Windows audio session."""
    pid: int | None
    name: str
    display_name: str
    window_title: str
    category: str
    is_self: bool
    peak_level: float
    active: bool
    last_active_monotonic: float

    @property
    def title(self) -> str:
        return self.window_title

    @property
    def peak_volume(self) -> float:
        return self.peak_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "display_name": self.display_name,
            "window_title": self.window_title,
            "category": self.category,
            "is_self": self.is_self,
            "peak_level": round(float(self.peak_level), 4),
            "active": self.active,
            "last_active_monotonic": round(float(self.last_active_monotonic), 3),
        }


class AppAudioRouter:
    """Discovers, filters, and attributes audio streams to Windows applications."""

    def __init__(
        self,
        *,
        mode: str = MODE_ALL_EXCEPT_SELF,
        target_app: str | None = None,
        target_pid: int | None = None,
        exclude_apps: set[str] | None = None,
        exclude_pids: set[int] | None = None,
        peak_threshold: float = 0.002,
        title_cache_ttl: float = 1.0,
        clock_monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.RLock()
        self.mode = mode if mode in (MODE_ALL_EXCEPT_SELF, MODE_TARGET_APP, MODE_ALL) else MODE_ALL_EXCEPT_SELF
        self.target_app = str(target_app or "").strip().lower() or None
        self.target_pid = int(target_pid) if target_pid is not None else None
        self.peak_threshold = max(0.0001, min(float(peak_threshold), 0.5))
        self.title_cache_ttl = max(0.2, min(float(title_cache_ttl), 10.0))
        self._clock_monotonic = clock_monotonic

        self._user_exclude_apps = {str(a).strip().lower() for a in (exclude_apps or set()) if str(a).strip()}
        self._user_exclude_pids = {int(p) for p in (exclude_pids or set()) if p is not None}

        # Cached window titles: pid -> (titles, timestamp)
        self._window_title_cache: dict[int, tuple[list[str], float]] = {}
        self._last_title_scan = 0.0

        # Native process loopback session tracking
        self._process_loopback: Any | None = None
        self._process_loopback_executable: str | Path | None = None
        self.default_loopback_device = "Game-Audeze Maxwell"

        # Stats
        self._inspected_chunks = 0
        self._suppressed_self_chunks = 0
        self._filtered_mismatch_chunks = 0
        self._attributed_chunks = 0
        self._app_chunk_counts: dict[str, int] = {}
        self._last_active_app: AppAudioSession | None = None
        self._last_scan_sessions: list[AppAudioSession] = []

    def configure(
        self,
        *,
        mode: str | None = None,
        target_app: str | None = None,
        target_pid: int | None = None,
        exclude_apps: list[str] | set[str] | None = None,
        exclude_pids: list[int] | set[int] | None = None,
        peak_threshold: float | None = None,
        executable: str | Path | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if mode is not None and mode in (MODE_ALL_EXCEPT_SELF, MODE_TARGET_APP, MODE_ALL):
                if self.mode == MODE_TARGET_APP and mode != MODE_TARGET_APP and self._process_loopback:
                    self._process_loopback.stop()
                    self._process_loopback = None
                self.mode = mode
            if target_app is not None:
                self.target_app = str(target_app).strip().lower() or None
            if target_pid is not None:
                new_pid = int(target_pid) if target_pid > 0 else None
                if self._process_loopback and self._process_loopback.pid != new_pid:
                    self._process_loopback.stop()
                    self._process_loopback = None
                self.target_pid = new_pid
            if executable is not None:
                self._process_loopback_executable = executable
            if exclude_apps is not None:
                self._user_exclude_apps = {str(a).strip().lower() for a in exclude_apps if str(a).strip()}
            if exclude_pids is not None:
                self._user_exclude_pids = {int(p) for p in exclude_pids if p is not None}
            if peak_threshold is not None:
                self.peak_threshold = max(0.0001, min(float(peak_threshold), 0.5))
            return self.state()

    def set_mode(self, mode: str) -> None:
        if mode not in (MODE_ALL_EXCEPT_SELF, MODE_TARGET_APP, MODE_ALL):
            raise ValueError(f"Invalid mode: {mode}")
        with self._lock:
            if self.mode == MODE_TARGET_APP and mode != MODE_TARGET_APP and self._process_loopback:
                self._process_loopback.stop()
                self._process_loopback = None
            self.mode = mode

    def set_target_app(self, target_app: str | None) -> None:
        with self._lock:
            self.target_app = str(target_app).strip().lower() if target_app else None

    def get_self_pids(self) -> set[int]:
        """Dynamically discover companion process hierarchy."""
        pids = {os.getpid()}
        if psutil is not None:
            try:
                curr = psutil.Process(os.getpid())
                for child in curr.children(recursive=True):
                    try:
                        pids.add(child.pid)
                    except Exception:
                        pass
            except Exception:
                pass
        with self._lock:
            pids.update(self._user_exclude_pids)
        return pids

    def is_self_session(self, pid: int | None, name: str) -> bool:
        """Check if an audio session belongs to the companion or excluded set."""
        if pid is not None and pid in self.get_self_pids():
            return True
        norm_name = str(name or "").strip().lower()
        if norm_name in self._user_exclude_apps:
            return True
        # If the process is a python/node script running in our working tree
        if norm_name in _KNOWN_SELF_NAMES and pid is not None and psutil is not None:
            try:
                p = psutil.Process(pid)
                cwd = p.cwd().lower() if hasattr(p, "cwd") else ""
                exe = p.exe().lower() if hasattr(p, "exe") else ""
                repo_marker = "jawl-voicecompanion"
                if repo_marker in cwd or repo_marker in exe:
                    return True
            except Exception:
                pass
        return False

    def _refresh_window_titles(self, now: float) -> dict[int, list[str]]:
        if win32gui is None or win32process is None:
            return {}
        if now - self._last_title_scan < self.title_cache_ttl and self._window_title_cache:
            return {pid: item[0] for pid, item in self._window_title_cache.items()}

        mapping: dict[int, list[str]] = {}

        def _enum_callback(hwnd: int, _extra: Any) -> None:
            try:
                if win32gui.IsWindowVisible(hwnd):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid:
                        title = win32gui.GetWindowText(hwnd)
                        if title and str(title).strip():
                            mapping.setdefault(pid, []).append(str(title).strip())
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_enum_callback, None)
        except Exception:
            pass

        self._window_title_cache = {pid: (titles, now) for pid, titles in mapping.items()}
        self._last_title_scan = now
        return mapping

    @staticmethod
    def classify_application(name: str, window_title: str, is_self: bool = False) -> str:
        """Categorize application domain from process name and window title."""
        if is_self:
            return "companion_self"
        norm_name = str(name or "").lower()
        norm_title = str(window_title or "").lower()

        # VoIP / Communications
        if norm_name in _VOIP_APPS or any(app.removesuffix(".exe") in norm_name for app in _VOIP_APPS):
            return "chat_voip"

        # Browsers with domain extraction
        if norm_name in _BROWSER_APPS or any(app.removesuffix(".exe") in norm_name for app in _BROWSER_APPS):
            if "youtube" in norm_title or "ютуб" in norm_title:
                return "browser_youtube"
            if "twitch" in norm_title:
                return "browser_twitch"
            if "soundcloud" in norm_title:
                return "browser_music"
            if any(k in norm_title for k in ("zoom", "meet.google", "discord", "telemost")):
                return "browser_call"
            return "browser"

        # Standalone Media Players
        if norm_name in _MEDIA_APPS or any(app.removesuffix(".exe") in norm_name for app in _MEDIA_APPS):
            return "media_player"

        # System / Shell
        if norm_name in ("system", "audiodg.exe", "shellexperiencehost.exe", "explorer.exe"):
            return "system"

        return "desktop_app"

    def scan_sessions(self, now: float | None = None) -> list[AppAudioSession]:
        """Enumerate active Windows audio sessions with peak volumes and app info."""
        if not _PYCAW_AVAILABLE:
            return []
        now_mono = self._clock_monotonic() if now is None else float(now)
        title_map = self._refresh_window_titles(now_mono)
        self_pids = self.get_self_pids()

        sessions_out: list[AppAudioSession] = []
        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except Exception:
            return []

        for s in raw_sessions:
            try:
                proc = s.Process
                pid = proc.pid if proc else None
                name = proc.name() if proc else "System"
                display_name = str(s.DisplayName or "").strip()
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                peak = float(meter.GetPeakValue()) if meter else 0.0

                w_titles = title_map.get(pid, []) if pid else []
                window_title = " | ".join(w_titles) if w_titles else display_name

                is_self = self.is_self_session(pid, name)
                category = self.classify_application(name, window_title, is_self=is_self)
                active = peak >= self.peak_threshold

                sessions_out.append(AppAudioSession(
                    pid=pid,
                    name=name,
                    display_name=display_name,
                    window_title=window_title,
                    category=category,
                    is_self=is_self,
                    peak_level=peak,
                    active=active,
                    last_active_monotonic=now_mono if active else 0.0,
                ))
            except Exception:
                continue

        with self._lock:
            self._last_scan_sessions = sessions_out
            active_non_self = [s for s in sessions_out if not s.is_self and s.active]
            if active_non_self:
                loudest = max(active_non_self, key=lambda s: s.peak_level)
                self._last_active_app = loudest
        return sessions_out

    def is_self_audio_active(self, sessions: list[AppAudioSession] | None = None) -> bool:
        """Return True if any companion/self process is currently emitting audio."""
        sess_list = sessions if sessions is not None else self.scan_sessions()
        for s in sess_list:
            if s.is_self and s.peak_level >= self.peak_threshold:
                return True
        return False

    def get_active_app(self, sessions: list[AppAudioSession] | None = None) -> AppAudioSession | None:
        """Attribute a mixed loopback only when one external session is active."""
        sess_list = sessions if sessions is not None else self.scan_sessions()
        active = [s for s in sess_list if not s.is_self and s.active]
        if len(active) != 1:
            return None
        single = active[0]
        with self._lock:
            self._last_active_app = single
        return single

    def filter_and_attribute(
        self,
        *,
        now_mono: float | None = None,
    ) -> tuple[bool, AppAudioSession | None, str]:
        """Decide whether to capture current audio and attribute to an application.

        Returns:
            (should_capture: bool, session: AppAudioSession | None, reason: str)
        """
        now = self._clock_monotonic() if now_mono is None else float(now_mono)
        sessions = self.scan_sessions(now=now)

        with self._lock:
            self._inspected_chunks += 1

            # 1. Self-exclusion invariant: companion must NEVER listen to its own voice
            for s in sessions:
                if s.is_self and s.peak_level >= self.peak_threshold:
                    self._suppressed_self_chunks += 1
                    return False, s, "self_audio_suppressed"

            active_app = self.get_active_app(sessions=sessions)
            active_external = [s for s in sessions if not s.is_self and s.active]

            # 2. Mode dispatch
            if self.mode == MODE_ALL:
                self._attributed_chunks += 1
                if active_app:
                    self._app_chunk_counts[active_app.name] = self._app_chunk_counts.get(active_app.name, 0) + 1
                return True, active_app, "accepted_all_mode"

            if self.mode == MODE_TARGET_APP:
                if self.is_using_process_loopback():
                    matching_sess = next((s for s in sessions if s.pid == self.target_pid), None)
                    if matching_sess is None:
                        target_name = self.target_app or f"PID-{self.target_pid}"
                        matching_sess = AppAudioSession(
                            pid=self.target_pid,
                            name=target_name,
                            display_name=target_name,
                            window_title="",
                            category="target_app",
                            is_self=False,
                            peak_level=1.0,
                            active=True,
                            last_active_monotonic=now,
                        )
                    self._attributed_chunks += 1
                    self._app_chunk_counts[matching_sess.name] = self._app_chunk_counts.get(matching_sess.name, 0) + 1
                    return True, matching_sess, "target_app_match"

                if len(active_external) > 1:
                    self._filtered_mismatch_chunks += 1
                    return False, None, "target_app_mixed_loopback"
                if not active_app:
                    self._filtered_mismatch_chunks += 1
                    return False, None, "target_app_no_active_session"
                target = self.target_app or ""
                matches_name = target and (target == active_app.name.lower() or target in active_app.name.lower())
                matches_pid = self.target_pid and (self.target_pid == active_app.pid)
                if matches_name or matches_pid:
                    self._attributed_chunks += 1
                    self._app_chunk_counts[active_app.name] = self._app_chunk_counts.get(active_app.name, 0) + 1
                    return True, active_app, "target_app_match"
                else:
                    self._filtered_mismatch_chunks += 1
                    return False, active_app, f"target_app_mismatch (active: {active_app.name})"

            # MODE_ALL_EXCEPT_SELF: default smart mode
            self._attributed_chunks += 1
            if active_app:
                self._app_chunk_counts[active_app.name] = self._app_chunk_counts.get(active_app.name, 0) + 1
            return True, active_app, "accepted_non_self_audio"

    def get_process_loopback(self) -> Any | None:
        """Return the active ProcessLoopbackBridge instance, if one is currently tracked."""
        with self._lock:
            return self._process_loopback

    def attach_process_loopback(self, bridge: Any) -> None:
        """Attach an existing ProcessLoopbackBridge instance."""
        with self._lock:
            if self._process_loopback is not None and self._process_loopback is not bridge:
                self._process_loopback.stop()
            self._process_loopback = bridge

    def create_or_get_process_loopback(
        self,
        pid: int | None = None,
        *,
        executable: str | Path | None = None,
    ) -> Any | None:
        """Create or return tracked ProcessLoopbackBridge for target PID when in MODE_TARGET_APP.

        If not in MODE_TARGET_APP, or if no target PID can be determined, returns None,
        signaling fallback to general SystemAudioLoopback on Game-Audeze Maxwell.
        """
        with self._lock:
            if self.mode != MODE_TARGET_APP:
                return None

            effective_pid = pid if pid is not None else self.target_pid
            if not effective_pid and self.target_app:
                # Try resolving target PID from active audio sessions
                active = self.get_active_app()
                if active and active.pid:
                    target = self.target_app.lower()
                    if target == active.name.lower() or target in active.name.lower():
                        effective_pid = active.pid
            if not effective_pid:
                return None

            if self._process_loopback is not None:
                if self._process_loopback.pid is None or self._process_loopback.pid == effective_pid:
                    return self._process_loopback
                self._process_loopback.stop()
                self._process_loopback = None

            from .process_loopback import ProcessLoopbackBridge

            exe = executable or self._process_loopback_executable
            self._process_loopback = ProcessLoopbackBridge(executable=exe)
            return self._process_loopback

    def start_process_loopback(
        self,
        consumer: Callable[[bytes, int, int], None] | None = None,
        *,
        pid: int | None = None,
        executable: str | Path | None = None,
    ) -> dict[str, Any] | None:
        """Start process loopback if in MODE_TARGET_APP with target PID.

        Returns bridge state dictionary on success, or None if fallback to SystemAudioLoopback
        is appropriate (e.g. not in MODE_TARGET_APP or no target PID found).
        """
        bridge = self.create_or_get_process_loopback(pid=pid, executable=executable)
        if bridge is None:
            return None

        effective_pid = pid if pid is not None else (self.target_pid or bridge.pid)
        if effective_pid is None:
            active = self.get_active_app()
            if active and active.pid:
                effective_pid = active.pid
        if effective_pid is None:
            return None

        return bridge.start(effective_pid, consumer=consumer)

    def stop_process_loopback(self) -> dict[str, Any] | None:
        """Stop and detach any active ProcessLoopbackBridge."""
        with self._lock:
            if self._process_loopback is not None:
                res = self._process_loopback.stop()
                self._process_loopback = None
                return res
            return None

    def is_using_process_loopback(self) -> bool:
        """Return True if an isolated process-tree loopback bridge is currently capturing."""
        with self._lock:
            return bool(
                self.mode == MODE_TARGET_APP
                and self._process_loopback is not None
                and self._process_loopback.running
            )

    def resolve_capture_source(self, default_device: str | None = None) -> dict[str, Any]:
        """Determine whether audio capture uses process loopback or falls back to system loopback.

        When targeting a specific PID in MODE_TARGET_APP, process loopback is selected.
        Otherwise, falls back to general SystemAudioLoopback on Game-Audeze Maxwell.
        """
        with self._lock:
            fallback = default_device or self.default_loopback_device
            if self.mode == MODE_TARGET_APP and self._process_loopback is not None:
                eff_pid = self.target_pid or (
                    self._process_loopback.pid if self._process_loopback else None
                )
                return {
                    "backend": "process_loopback",
                    "target_pid": eff_pid,
                    "device_name": None,
                    "mode": self.mode,
                    "isolated": bool(self._process_loopback.running),
                    "fallback_device": fallback,
                }
            return {
                "backend": "system_loopback",
                "target_pid": None,
                "device_name": fallback,
                "mode": self.mode,
                "isolated": False,
                "fallback_device": fallback,
            }

    def state(self) -> dict[str, Any]:
        with self._lock:
            last_app_dict = self._last_active_app.to_dict() if self._last_active_app else None
            using_proc = self.is_using_process_loopback()
            capture_source = self.resolve_capture_source()
            proc_state = self._process_loopback.state() if self._process_loopback else None
            return {
                "available": _PYCAW_AVAILABLE,
                "capture_semantics": (
                    "isolated_process_tree_loopback"
                    if using_proc
                    else "mixed_output_loopback_not_separate_app_streams"
                ),
                "mode": self.mode,
                "target_app": self.target_app,
                "target_pid": self.target_pid,
                "peak_threshold": self.peak_threshold,
                "exclude_apps": sorted(list(self._user_exclude_apps)),
                "exclude_pids": sorted(list(self._user_exclude_pids)),
                "self_pids": sorted(list(self.get_self_pids())),
                "active_sessions_count": len(self._last_scan_sessions),
                "last_active_app": last_app_dict,
                "process_loopback": proc_state,
                "using_process_loopback": using_proc,
                "capture_source": capture_source,
                "fallback_device": self.default_loopback_device,
                "stats": {
                    "inspected_chunks": self._inspected_chunks,
                    "suppressed_self_chunks": self._suppressed_self_chunks,
                    "filtered_mismatch_chunks": self._filtered_mismatch_chunks,
                    "attributed_chunks": self._attributed_chunks,
                    "app_chunk_counts": dict(self._app_chunk_counts),
                },
            }


__all__ = [
    "AppAudioRouter",
    "AppAudioSession",
    "MODE_ALL",
    "MODE_ALL_EXCEPT_SELF",
    "MODE_TARGET_APP",
]
