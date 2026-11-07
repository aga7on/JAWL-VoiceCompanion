"""Windows System Media Transport Controls (SMTC) Adapter.

Extracts real-time music and media playback metadata (Title, Artist, Album,
Source App, Playback Status) directly from the OS kernel/WinRT session manager
without screen scraping or audio fingerpriting.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import winsdk.windows.media.control as win_media_control
    _WINSDK_SMTC_AVAILABLE = True
except Exception:
    win_media_control = None
    _WINSDK_SMTC_AVAILABLE = False


class WindowsSMTCAdapter:
    """Queries Windows Global System Media Transport Controls Session Manager."""

    def __init__(self, *, cache_ttl_sec: float = 1.0) -> None:
        self.cache_ttl_sec = max(0.1, float(cache_ttl_sec))
        self._lock = threading.RLock()
        self._last_poll_time = 0.0
        self._last_cache_key: Optional[tuple] = None
        self._worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._cached_state: Dict[str, Any] = {
            "available": _WINSDK_SMTC_AVAILABLE,
            "has_active_playback": False,
            "is_playing": False,
            "title": "",
            "artist": "",
            "album": "",
            "app_id": "",
            "target_app_matched": False,
            "playback_status": "Closed",
            "last_updated": 0.0,
        }

    def _get_worker_loop(self) -> asyncio.AbstractEventLoop:
        if self._worker_loop is None or self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_loop = asyncio.new_event_loop()
            self._worker_thread = threading.Thread(
                target=self._run_worker_loop,
                args=(self._worker_loop,),
                name="SMTCWinRTWorker",
                daemon=True,
            )
            self._worker_thread.start()
        return self._worker_loop

    @staticmethod
    def _run_worker_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    @property
    def is_available(self) -> bool:
        return _WINSDK_SMTC_AVAILABLE

    async def _async_poll(
        self,
        *,
        target_app: str | None = None,
        target_pid: int | None = None,
    ) -> Dict[str, Any]:
        if not _WINSDK_SMTC_AVAILABLE or win_media_control is None:
            return {
                "available": False,
                "has_active_playback": False,
                "is_playing": False,
                "title": "",
                "artist": "",
                "album": "",
                "app_id": "",
                "target_app_matched": False,
                "playback_status": "Unavailable",
                "last_updated": time.time(),
            }

        try:
            manager = await win_media_control.GlobalSystemMediaTransportControlsSessionManager.request_async()
            if not manager:
                return {
                    "available": True,
                    "has_active_playback": False,
                    "is_playing": False,
                    "title": "",
                    "artist": "",
                    "album": "",
                    "app_id": "",
                    "target_app_matched": False,
                    "playback_status": "NoManager",
                    "last_updated": time.time(),
                }

            all_sessions = []
            try:
                raw_sessions = manager.get_sessions()
                if raw_sessions:
                    all_sessions = list(raw_sessions)
            except Exception:
                all_sessions = []

            # 1. Resolve target app from PID if provided
            target_proc_name = None
            if target_pid is not None:
                try:
                    import psutil
                    target_proc_name = psutil.Process(int(target_pid)).name().lower()
                except Exception:
                    target_proc_name = None

            target_app_lower = str(target_app or "").strip().lower() or None
            is_targeted = bool(target_app_lower or target_proc_name)

            target_session = None
            global_playing_session = None
            any_session_fallback = None

            for s in all_sessions:
                try:
                    s_aumid = str(getattr(s, "source_app_user_model_id", "") or "").lower()
                    if not s_aumid:
                        continue
                    p_info = None
                    try:
                        p_info = s.get_playback_info()
                    except Exception:
                        pass
                    
                    s_is_playing = bool(p_info and int(p_info.playback_status) == 4)

                    if is_targeted and target_session is None:
                        matched = False
                        if target_app_lower:
                            s_stem = s_aumid.rsplit(".", 1)[0]
                            t_stem = target_app_lower.rsplit(".", 1)[0]
                            if (target_app_lower in s_aumid or s_aumid in target_app_lower or
                                t_stem in s_aumid or s_stem in target_app_lower):
                                matched = True
                        if target_proc_name and not matched:
                            p_stem = target_proc_name.rsplit(".", 1)[0]
                            if target_proc_name in s_aumid or p_stem in s_aumid:
                                matched = True
                        if matched:
                            target_session = s

                    if s_is_playing and global_playing_session is None:
                        global_playing_session = s

                    if any_session_fallback is None:
                        any_session_fallback = s
                except Exception:
                    continue

            async def _extract_session_data(session_obj) -> dict[str, Any]:
                if not session_obj:
                    return {
                        "has_active_playback": False,
                        "is_playing": False,
                        "title": "",
                        "artist": "",
                        "album": "",
                        "app_id": "",
                        "playback_status": "Idle",
                        "playback_type": "unknown",
                    }
                app_id = str(getattr(session_obj, "source_app_user_model_id", "") or "")
                title, artist, album, p_type_str = "", "", "", "unknown"
                try:
                    media_props = await session_obj.try_get_media_properties_async()
                    if media_props:
                        title = str(getattr(media_props, "title", "") or "")
                        artist = str(getattr(media_props, "artist", "") or "")
                        album = str(getattr(media_props, "album_title", "") or "")
                        pt_code = getattr(media_props, "playback_type", 0)
                        p_type_map = {1: "music", 2: "video", 3: "image"}
                        p_type_str = p_type_map.get(int(pt_code) if pt_code is not None else 0, "unknown")
                except Exception:
                    pass

                status_str = "Unknown"
                is_playing = False
                try:
                    p_info = session_obj.get_playback_info()
                    if p_info:
                        status_map = {0: "Closed", 1: "Opened", 2: "Changing", 3: "Stopped", 4: "Playing", 5: "Paused"}
                        status_enum = int(p_info.playback_status)
                        status_str = status_map.get(status_enum, str(status_enum))
                        is_playing = (status_enum == 4)
                except Exception:
                    pass

                has_active = bool(is_playing and (title or artist))
                return {
                    "has_active_playback": has_active,
                    "is_playing": is_playing,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "app_id": app_id,
                    "playback_status": status_str,
                    "playback_type": p_type_str,
                }

            global_session_obj = global_playing_session or manager.get_current_session() or any_session_fallback
            system_media = await _extract_session_data(global_session_obj)

            if is_targeted:
                if target_session is not None:
                    target_data = await _extract_session_data(target_session)
                    return {
                        "available": True,
                        "has_active_playback": target_data["has_active_playback"],
                        "is_playing": target_data["is_playing"],
                        "title": target_data["title"],
                        "artist": target_data["artist"],
                        "album": target_data["album"],
                        "app_id": target_data["app_id"],
                        "playback_status": target_data["playback_status"],
                        "playback_type": target_data["playback_type"],
                        "target_app_matched": True,
                        "system_media": system_media,
                        "last_updated": time.time(),
                    }
                else:
                    return {
                        "available": True,
                        "has_active_playback": False,
                        "is_playing": False,
                        "title": "",
                        "artist": "",
                        "album": "",
                        "app_id": target_app_lower or target_proc_name or "",
                        "playback_status": "NotRunning",
                        "playback_type": "unknown",
                        "target_app_matched": False,
                        "system_media": system_media,
                        "last_updated": time.time(),
                    }

            return {
                "available": True,
                "has_active_playback": system_media["has_active_playback"],
                "is_playing": system_media["is_playing"],
                "title": system_media["title"],
                "artist": system_media["artist"],
                "album": system_media["album"],
                "app_id": system_media["app_id"],
                "playback_status": system_media["playback_status"],
                "playback_type": system_media["playback_type"],
                "target_app_matched": False,
                "system_media": system_media,
                "last_updated": time.time(),
            }
        except Exception as exc:
            logger.debug("Failed to query SMTC session: %s", exc)
            return {
                "available": True,
                "has_active_playback": False,
                "is_playing": False,
                "title": "",
                "artist": "",
                "album": "",
                "app_id": "",
                "playback_status": f"Error: {exc}",
                "target_app_matched": False,
                "last_updated": time.time(),
            }

    def poll(
        self,
        *,
        force: bool = False,
        target_app: str | None = None,
        target_pid: int | None = None,
    ) -> Dict[str, Any]:
        """Synchronously query SMTC state with TTL-based caching and optional app/PID targeting."""
        with self._lock:
            now = time.monotonic()
            cache_key = (str(target_app or "").lower(), target_pid)
            if not force and (now - self._last_poll_time < self.cache_ttl_sec) and self._last_cache_key == cache_key:
                return dict(self._cached_state)

            try:
                loop = self._get_worker_loop()
                fut = asyncio.run_coroutine_threadsafe(
                    self._async_poll(target_app=target_app, target_pid=target_pid),
                    loop,
                )
                self._cached_state = fut.result(timeout=2.0)
                self._last_poll_time = now
                self._last_cache_key = cache_key
            except Exception as exc:
                logger.debug("SMTC poll failed: %s", exc)

            return dict(self._cached_state)
            return dict(self._cached_state)
