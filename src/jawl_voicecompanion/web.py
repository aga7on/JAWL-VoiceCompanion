"""Minimal loopback web control plane for the Phase 1 vertical slice."""

from __future__ import annotations

import json
import base64
import hmac
import ipaddress
import os
import re
import secrets
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from math import isfinite
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

from .approvals import ApprovalStore
from .ambient_audio import AmbientAudioDisabled, AmbientAudioService, PlaybackSuppression
from .ambient_memory import AmbientMemoryBuffer, AmbientTriageScheduler
from .asr import ASRUnavailable, ExternalASRService
from .audit import AuditLog
from .attention import AttentionPresence
from .avatar import AvatarAssetStore
from .doctor import build_doctor_report
from .event_log import log_event
from .gateway import TextGateway
from .hostos_tools import HostOSExecutor
from .jawl_events import JawlEventFileSink
from .jawl_web import JawlWebUnavailable
from .models import ToolRequest
from .presence import ScreenDeltaWatcher
from .resources import ResourceGovernor
from .tts import TTSService, TTSUnavailable, TTSCancelled
from . import turn_policy
from .vision import JawlNativeVisionExecutor, VisionLookService
from .voicemem_client import VoiceMemAsyncIngest, VoiceMemProcessClient, VoiceMemUnavailable
from .ws_server import WebSocketConnection, WebSocketError, is_websocket_upgrade, send_handshake_response
from .system_audio import SystemAudioUnavailable
from .stream_chat import StreamChatIngestor


MAX_BODY_BYTES = 64 * 1024
AVATAR_AUDIO_STALE_SECONDS = 0.75
LAN_AUTH_MIN_TOKEN_LENGTH = 16
LAN_AUTH_REALM = "JAWL VoiceCompanion LAN"


def require_loopback_host(host: str) -> str:
    """Reject wildcard/remote binds before a privileged HTTP server starts."""
    value = str(host or "").strip()
    if value.casefold() == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("HTTP services must bind to loopback (127.0.0.1, ::1 or localhost)") from exc
    if not address.is_loopback:
        raise ValueError("HTTP services must bind to loopback; remote binds are disabled")
    return value


def is_loopback_host(host: str) -> bool:
    """Return whether *host* is an explicit loopback address or localhost."""
    value = str(host or "").strip()
    if value.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


# ASR hallucination on noise/silence must never become a user turn: the model
# can echo its own transcription prompt, emit single filler characters, switch
# to a foreign script (throat clearing turns into CJK filler characters) or
# just stutter one character many times on keyboard noise. These are technical
# artifacts, not user speech.
_ASR_PROMPT_ECHO_MARKERS = ("transcribe the audio exactly as spoken", "транскрибируй аудио")
_MIN_MEANINGFUL_TRANSCRIPT_CHARS = 2

# CJK/Hangul ranges: a Russian transcription should never contain these. When
# Qwen3-ASR receives non-speech noise it often switches languages and emits CJK
# filler characters ("嗯嗯嗯"), which is a hard technical-artifact signal.
_ASR_FOREIGN_SCRIPT_RANGES = (
    (0x2E80, 0x2EFF),  # CJK Radicals Supplement
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana Phonetic Extensions
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFF5F),  # Fullwidth Forms
    (0xAC00, 0xD7AF),  # Hangul Syllables
)


def _contains_foreign_script(text: str) -> bool:
    for char in text:
        code = ord(char)
        for start, end in _ASR_FOREIGN_SCRIPT_RANGES:
            if start <= code <= end:
                return True
    return False


def is_meaningful_transcript(text: str) -> bool:
    """Keep real utterances (including short ones like «Ок»), drop ASR noise."""
    cleaned = re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE)
    if not cleaned:
        return False
    if len(cleaned) < _MIN_MEANINGFUL_TRANSCRIPT_CHARS:
        return False
    lowered = cleaned.casefold()
    for marker in _ASR_PROMPT_ECHO_MARKERS:
        if re.sub(r"[\W_]+", "", marker, flags=re.UNICODE).casefold() in lowered:
            return False
    if _contains_foreign_script(cleaned):
        # Russian speech never contains CJK/Hangul; this is an ASR language
        # switch on noise (throat clearing, keyboard, silence).
        return False
    if len(set(lowered)) == 1:
        # Single repeated character is a filler/stutter ("嗯嗯嗯", "ммм", "ааа"),
        # not an utterance. Real short words use more than one character.
        return False
    return True


def require_bind_host(host: str, *, lan_mode: bool = False) -> str:
    """Validate a bind target, requiring explicit LAN mode for non-loopback."""
    value = str(host or "").strip()
    if is_loopback_host(value):
        return value
    if not lan_mode:
        raise ValueError("remote HTTP binds require explicit LAN mode (--lan)")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(
            "LAN HTTP services must bind to an IP address (use a private LAN address or 0.0.0.0)"
        ) from exc
    if not (address.is_unspecified or address.is_private or address.is_link_local):
        raise ValueError("LAN HTTP services may bind only to private, link-local or unspecified addresses")
    return value


def create_tls_context(
    cert_file: str | os.PathLike[str] | None,
    key_file: str | os.PathLike[str] | None,
) -> ssl.SSLContext | None:
    """Load a server TLS identity without ever logging its private key."""
    if (cert_file is None) != (key_file is None):
        raise ValueError("TLS certificate and private key must be supplied together")
    if cert_file is None:
        return None
    certificate = Path(cert_file)
    private_key = Path(key_file)
    if not certificate.is_file() or not private_key.is_file():
        raise ValueError("TLS certificate and private key files must exist")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=str(certificate), keyfile=str(private_key))
    except (OSError, ssl.SSLError) as exc:
        raise ValueError("TLS certificate and private key could not be loaded") from exc
    return context


def _validate_lan_access_token(token: str | None) -> str:
    value = str(token or "")
    if len(value) < LAN_AUTH_MIN_TOKEN_LENGTH:
        raise ValueError(
            f"LAN access token must be at least {LAN_AUTH_MIN_TOKEN_LENGTH} characters and supplied via the environment"
        )
    return value


def _host_header_parts(value: str | None, scheme: str) -> tuple[str, int] | None:
    """Parse Host without accepting credentials or a mismatched port."""
    if not value:
        return None
    try:
        parsed = urlsplit("//" + str(value).strip())
        if parsed.username or parsed.password or not parsed.hostname:
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.hostname.casefold().rstrip("."), port


def _security_headers(handler: BaseHTTPRequestHandler, *, presentation: bool = False) -> None:
    """Apply a conservative policy to both control and presentation responses."""
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    if presentation:
        # The avatar page is the OBS source and is embedded by the loopback
        # control panel. OBS loads it top-level, so framing stays restricted
        # to loopback control origins; LAN origins must load it top-level.
        handler.send_header("Content-Security-Policy", (
            "default-src 'self'; object-src 'none'; base-uri 'none'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors http://127.0.0.1:* http://localhost:* "
            "https://127.0.0.1:* https://localhost:*"
        ))
        handler.send_header("Cross-Origin-Opener-Policy", "same-origin")
        handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
        return
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Cross-Origin-Opener-Policy", "same-origin")
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
    handler.send_header("Content-Security-Policy", (
        "default-src 'self'; object-src 'none'; base-uri 'none'; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
        "frame-src http://127.0.0.1:* http://localhost:* https://127.0.0.1:* https://localhost:*; "
        "frame-ancestors 'none'"
    ))


class CompanionServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        frontend_dir: Path,
        gateway: TextGateway,
        hostos_executor: HostOSExecutor,
        vision_service: VisionLookService,
        screen_watcher: ScreenDeltaWatcher | None = None,
        voice_mem: VoiceMemProcessClient | None = None,
        tts_service: TTSService | None = None,
        avatar_assets: AvatarAssetStore | None = None,
        attention: AttentionPresence | None = None,
        ambient_memory: AmbientMemoryBuffer | None = None,
        sensory_ingestor: Any | None = None,
        ambient_audio: AmbientAudioService | None = None,
        ambient_scheduler: AmbientTriageScheduler | None = None,
        jawl_hostos_control: bool = False,
        audit_log: AuditLog | None = None,
        asr_service: ExternalASRService | None = None,
        streaming_asr: Any | None = None,
        gigaam_transcriber: Any | None = None,
        helper_urls: dict[str, str] | None = None,
        proactive_feed: Any | None = None,
        perception_fusion: Any | None = None,
        legacy_presentation: bool = True,
        resource_governor: ResourceGovernor | None = None,
        presence_file: Path | None = None,
        stream_chat: StreamChatIngestor | None = None,
        stream_chat_event_sink: Callable[[dict[str, Any]], Any] | None = None,
        lan_mode: bool = False,
        lan_access_token: str | None = None,
        lan_auth_user: str = "tablet",
        tls_context: ssl.SSLContext | None = None,
    ):
        bind_host = str(server_address[0])
        if not is_loopback_host(bind_host) and not lan_mode:
            raise ValueError("remote HTTP binds require explicit LAN mode (--lan)")
        if not is_loopback_host(bind_host) and tls_context is None:
            raise ValueError("non-loopback LAN control requires a trusted TLS certificate and private key")
        if lan_mode:
            lan_access_token = _validate_lan_access_token(lan_access_token)
            lan_auth_user = str(lan_auth_user or "").strip()
            if not lan_auth_user or ":" in lan_auth_user or len(lan_auth_user) > 64:
                raise ValueError("LAN auth username must be non-empty, contain no colon and be at most 64 characters")
        self.frontend_dir = frontend_dir.resolve()
        self.gateway = gateway
        self.hostos = hostos_executor
        self.vision = vision_service
        self.screen_watcher = screen_watcher
        self.voice_mem = voice_mem
        self.voice_mem_async = VoiceMemAsyncIngest(voice_mem) if voice_mem is not None else None
        self.tts = tts_service
        self.avatar_assets = avatar_assets
        self.attention = attention or AttentionPresence()
        self.presence_file = Path(presence_file).resolve() if presence_file else None
        self._load_presence_preferences()
        self.ambient_memory = ambient_memory or AmbientMemoryBuffer()
        self.sensory_ingestor = sensory_ingestor
        self.ambient_audio = ambient_audio
        self.ambient_scheduler = ambient_scheduler
        self.resources = resource_governor or ResourceGovernor()
        if self.tts is not None:
            self.tts.set_governor(self.resources)
        if self.ambient_scheduler is not None:
            self.ambient_scheduler.governor = self.resources
        self.playback_suppression = PlaybackSuppression()
        if self.ambient_audio is not None:
            self.ambient_audio.bridge.set_playback_suppression(self.playback_suppression)
        self.asr = asr_service
        self.streaming_asr = streaming_asr
        self.gigaam_transcriber = gigaam_transcriber
        self.helper_urls = dict(helper_urls or {})
        self.proactive_feed = proactive_feed
        self.perception_fusion = perception_fusion
        self.jawl_hostos_control = jawl_hostos_control
        self.audit_log = audit_log
        self.legacy_presentation = bool(legacy_presentation)
        self.lan_mode = bool(lan_mode)
        self.lan_access_token = str(lan_access_token or "")
        self.lan_auth_user = str(lan_auth_user or "tablet")
        self.tls_enabled = tls_context is not None
        self.url_scheme = "https" if self.tls_enabled else "http"
        self._stream_chat_events = deque(maxlen=100)
        self.stream_chat_event_sink = stream_chat_event_sink
        self.stream_chat = stream_chat or StreamChatIngestor(
            downstream=self._accept_stream_chat_event,
        )
        self.presentation_url: str | None = None
        # A fresh process must invalidate browser-side speech buffers.  This is
        # deliberately a runtime identity, not a persisted session identifier:
        # after a restart any in-flight audio belongs to the old process.
        self.runtime_instance_id = uuid4().hex
        self.approvals = ApprovalStore(hostos_executor)
        self.session_token = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        self._avatar_audio_lock = threading.Lock()
        self._avatar_audio = {
            "schema_version": 1,
            "amplitude": 0.0,
            "speaking": False,
            "timestamp_ms": 0,
            "updated_at": 0.0,
        }
        super().__init__(server_address, CompanionRequestHandler)
        self._fixed_origin_hosts = {
            ("127.0.0.1", self.server_port),
            ("localhost", self.server_port),
            ("::1", self.server_port),
        }
        if tls_context is not None:
            self.socket = tls_context.wrap_socket(self.socket, server_side=True)

    def origin_allowed(self, origin: str | None, host_header: str | None) -> bool:
        """Require an exact same-origin request, including scheme and port."""
        if not origin:
            return True
        try:
            parsed = urlsplit(str(origin).strip())
            if (
                parsed.scheme.casefold() != self.url_scheme
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or not parsed.hostname
            ):
                return False
            origin_host = parsed.hostname.casefold().rstrip(".")
            origin_port = parsed.port or (443 if self.url_scheme == "https" else 80)
        except ValueError:
            return False
        if (origin_host, origin_port) in self._fixed_origin_hosts:
            return True
        if not self.lan_mode:
            return False
        return (origin_host, origin_port) == _host_header_parts(host_header, self.url_scheme)

    def set_presentation_url(self, url: str) -> None:
        self.presentation_url = str(url).strip() or None

    def _load_presence_preferences(self) -> None:
        if self.presence_file is None or not self.presence_file.exists():
            return
        try:
            payload = json.loads(self.presence_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            values = {
                key: payload[key]
                for key in ("dnd", "min_significance", "cooldown_seconds", "budget_per_hour", "quiet_hours")
                if key in payload
            }
            if values:
                self.attention.configure(**values)
        except (OSError, ValueError, TypeError):
            return

    def _persist_presence_preferences(self) -> None:
        if self.presence_file is None:
            return
        state = self.attention.state()
        payload = {
            key: state[key]
            for key in ("dnd", "min_significance", "cooldown_seconds", "budget_per_hour", "quiet_hours")
        }
        temporary = self.presence_file.with_suffix(".tmp")
        try:
            self.presence_file.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.presence_file)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def presentation_state(self) -> dict[str, Any]:
        """Return only the ephemeral state allowed on the unprivileged origin."""
        state = self.gateway.state()
        turn = state.get("last_turn") if isinstance(state, dict) else None
        response = turn.get("response") if isinstance(turn, dict) else None
        if not isinstance(response, dict):
            response = {}
        emotion = response.get("emotion")
        avatar = response.get("avatar")
        if not isinstance(emotion, dict):
            emotion = {"id": "neutral", "intensity": 0.0, "confidence": 1.0}
        if not isinstance(avatar, dict):
            avatar = {"expression": "neutral", "motion": "idle", "state": "idle"}
        return {
            "schema_version": 1,
            "response_id": str(response.get("response_id") or ""),
            "turn_id": str(response.get("turn_id") or ""),
            "subtitle": str(response.get("text") or "")[:280] if response.get("speak") else "",
            "speak": bool(response.get("speak", False)),
            "emotion": {
                "id": str(emotion.get("id") or "neutral")[:128],
                "intensity": max(0.0, min(1.0, float(emotion.get("intensity", 0.0) or 0.0))),
            },
            "avatar": {
                "expression": str(avatar.get("expression") or "neutral")[:128],
                "motion": str(avatar.get("motion") or "idle")[:128],
                "state": str(avatar.get("state") or "idle")[:32],
            },
            "avatar_audio": self.avatar_audio(),
        }

    def set_avatar_audio(self, amplitude: float, speaking: bool, timestamp_ms: int) -> dict[str, Any]:
        """Keep only a short-lived presentation signal; never persist audio."""
        with self._avatar_audio_lock:
            if timestamp_ms >= int(self._avatar_audio["timestamp_ms"]):
                self._avatar_audio.update({
                    "amplitude": max(0.0, min(1.0, float(amplitude))),
                    "speaking": bool(speaking),
                    "timestamp_ms": int(timestamp_ms),
                    "updated_at": time.monotonic(),
                })
            return self._avatar_audio_snapshot_locked()

    def avatar_audio(self) -> dict[str, Any]:
        with self._avatar_audio_lock:
            return self._avatar_audio_snapshot_locked()

    def _avatar_audio_snapshot_locked(self) -> dict[str, Any]:
        snapshot = {
            "schema_version": 1,
            "amplitude": float(self._avatar_audio["amplitude"]),
            "speaking": bool(self._avatar_audio["speaking"]),
            "timestamp_ms": int(self._avatar_audio["timestamp_ms"]),
        }
        if time.monotonic() - float(self._avatar_audio["updated_at"]) > AVATAR_AUDIO_STALE_SECONDS:
            snapshot["amplitude"] = 0.0
            snapshot["speaking"] = False
        return snapshot

    _SCREEN_QUERY = re.compile(
        r"(экран|скрин|монитор|что\s+(сейчас\s+)?(происходит|видно)|опиши\s+(что|экран|кадр))",
        re.IGNORECASE,
    )

    def enrich_turn_text(self, text: str) -> str:
        """Ground turn text: mid-turn note + freshest perception observation."""
        clean = str(text or "").strip()
        if not clean:
            return clean
        prefix = ""
        try:
            active = self.gateway.arbiter.state().get("active")
        except Exception:  # noqa: BLE001 - enrichment is best-effort
            active = None
        if isinstance(active, dict) and active.get("priority") == "USER_FINAL" and not active.get("cancelled"):
            prefix = (
                "[Примечание: это сообщение пришло, пока предыдущий ответ ещё готовился; "
                "предыдущая реплика и это сообщение — один контекст.]\n"
            )
        fusion = self.perception_fusion
        if fusion is None or not self._SCREEN_QUERY.search(clean):
            return prefix + clean
        try:
            observation = fusion.compose()
        except Exception:  # noqa: BLE001 - enrichment is best-effort
            observation = ""
        if not observation:
            return prefix + clean + "\n\n[Свежих наблюдений восприятия нет: экран не наблюдался в последние минуты.]"
        return prefix + clean + "\n\n[ВНУТРЕННИЕ НАБЛЮДЕНИЯ ВОСПРИЯТИЯ (фон, не цитировать дословно): " + observation[:900] + "]"

    def voice_preface(self, partial: str) -> str:
        """Build a short speakable provisional line from fresh perception.

        The voice lane can say this while the JAWL turn is still running, so
        the first audible reaction no longer waits for the full model answer.
        Only screen-shaped questions qualify and the line stays bounded.
        """
        clean = str(partial or "").strip()
        fusion = self.perception_fusion
        if not clean or fusion is None or not self._SCREEN_QUERY.search(clean):
            return ""
        try:
            observation = str(fusion.compose() or "").strip()
        except Exception:  # noqa: BLE001 - a missing hint never blocks the turn
            return ""
        if not observation:
            return ""
        clause = observation.split(". ", 1)[0].strip()
        clause = re.sub(r"^(?:Экран|Окно|Звук|Музыка|Слышно)\s*:\s*", "", clause, flags=re.IGNORECASE).strip()
        clause = clause.strip("«»\"' .;:,-")
        if not clause:
            return ""
        if len(clause) > 140:
            clause = clause[:140].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return f"Смотрю: {clause}."

    def server_close(self) -> None:
        errors: list[str] = []

        def step(name: str, action: Any) -> None:
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - shutdown stays best-effort
                errors.append(f"{name}: {type(exc).__name__}")

        responder_close = getattr(self.gateway.responder, "close", None)
        if callable(responder_close):
            step("responder", responder_close)
        if self.screen_watcher is not None:
            step("screen_watcher", self.screen_watcher.stop)
        if self.ambient_audio is not None:
            step("ambient_audio", self.ambient_audio.stop)
        step("playback_suppression", self.playback_suppression.end)
        if self.ambient_scheduler is not None:
            step("ambient_scheduler", self.ambient_scheduler.stop)
        if self.sensory_ingestor is not None:
            step("sensory_ingestor", self.sensory_ingestor.stop)
        step("hostos", self.hostos.stop_all)
        if self.voice_mem_async is not None:
            step("voice_mem_async", self.voice_mem_async.close)
        if self.voice_mem is not None:
            step("voice_mem", self.voice_mem.close)
        if self.asr is not None:
            step("asr", self.asr.close)
        if self.stream_chat is not None:
            step("stream_chat", self.stream_chat.close)
        if self.tts is not None:
            step("tts", self.tts.close)
        try:
            super().server_close()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"control_server: {type(exc).__name__}")
        if errors:
            raise RuntimeError("companion shutdown issues: " + ", ".join(errors))

    def _accept_stream_chat_event(self, event: dict[str, Any]) -> None:
        """Keep only bounded observations before optional JAWL delivery."""
        self._stream_chat_events.append(dict(event))
        if self.stream_chat_event_sink is not None:
            self.stream_chat_event_sink(event)

    def stream_chat_state(self) -> dict[str, Any]:
        return {
            **self.stream_chat.state(),
            "recent_events": [dict(event) for event in self._stream_chat_events],
        }


class CompanionRequestHandler(BaseHTTPRequestHandler):
    server: CompanionServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authenticate_network_request():
            return
        if is_websocket_upgrade(self.headers):
            self._serve_websocket()
            return
        if self._proxy_jawl_console():
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            health = self.server.gateway.health()
            health["runtime_instance_id"] = self.server.runtime_instance_id
            health["resources"] = self.server.resources.state()
            self._json(health)
            return
        if path == "/api/resources":
            self._json(self.server.resources.state())
            return
        if path == "/api/doctor":
            self._json(build_doctor_report(
                gateway=self.server.gateway,
                hostos=self.server.hostos,
                vision=self.server.vision,
                voice_mem=self.server.voice_mem,
                asr=self.server.asr,
                tts=self.server.tts,
                avatar_assets=self.server.avatar_assets,
                ambient_memory=self.server.ambient_memory,
                ambient_audio=self.server.ambient_audio,
                resource_governor=self.server.resources,
                streaming_asr=self.server.streaming_asr,
                helper_urls=self.server.helper_urls,
                sensory_ingestor=self.server.sensory_ingestor,
                gigaam_transcriber=getattr(self.server, "gigaam_transcriber", None),
            ))
            return
        if path == "/api/proactive":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            feed = self.server.proactive_feed
            if feed is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            self._json(feed.poll_state())
            return
        if path == "/api/perception/now":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            fusion = self.server.perception_fusion
            if fusion is None:
                self._json({"configured": False, "draft": ""})
                return
            try:
                draft = fusion.compose()
            except Exception:  # noqa: BLE001 - the hint is best-effort
                draft = ""
            self._json({"configured": True, "draft": draft[:1200]})
            return
        if path == "/api/session":
            self._json(
                {"schema_version": 1, "csrf_token": self.server.csrf_token},
                set_session_cookie=True,
            )
            return
        if path == "/api/state":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            state = self.server.gateway.state()
            state["avatar_audio"] = self.server.avatar_audio()
            self._json(state)
            return
        if path == "/api/history":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            history = self.server.gateway.turn_history(limit=200)
            self._json({"ok": True, "turns": history, "count": len(history)})
            return
        if path == "/api/audit":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            events = self.server.audit_log.events() if self.server.audit_log else self.server.gateway.audit()
            self._json({"events": events})
            return
        if path == "/api/hostos/tools":
            self._json({"dry_run": self.server.hostos.dry_run, "tools": self.server.hostos.list_tools()})
            return
        if path == "/api/vision/status":
            status = self.server.vision.status()
            if self.server.screen_watcher is not None:
                status["watcher"] = self.server.screen_watcher.state()
            status["attention"] = self.server.attention.state()
            self._json(status)
            return
        if path == "/api/vision/events":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            events = self.server.screen_watcher.events() if self.server.screen_watcher else []
            self._json({"events": events})
            return
        if path == "/api/vision/intents":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            self._json({"intents": self.server.attention.intents()})
            return
        if path == "/api/attention":
            self._json(self.server.attention.state())
            return
        if path == "/api/stream-chat":
            self._json(self.server.stream_chat_state())
            return
        if path == "/api/ambient-memory":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            state = self.server.ambient_memory.state()
            if self.server.ambient_scheduler is not None:
                state["scheduler"] = self.server.ambient_scheduler.state()
            if self.server.sensory_ingestor is not None:
                state["sensory"] = self.server.sensory_ingestor.state()
            self._json({
                "state": state,
                "observations": self.server.ambient_memory.observations(),
                "episodes": self.server.ambient_memory.episodes(),
            })
            return
        if path == "/api/ambient-audio":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            if self.server.ambient_audio is None:
                self._json({"configured": False, "status": "not_configured"})
            else:
                state = self.server.ambient_audio.state()
                state["playback_suppression"] = self.server.playback_suppression.state()
                self._json(state)
            return
        if path == "/api/voice/status":
            if self.server.voice_mem is None and self.server.asr is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            result: dict[str, Any] = {"configured": True}
            if self.server.voice_mem is not None:
                try:
                    voicemem = self.server.voice_mem.health()
                except VoiceMemUnavailable as exc:
                    voicemem = {"status": "degraded", "reason": str(exc)}
                result.update(voicemem)
                result["voicemem"] = voicemem
                if self.server.voice_mem_async is not None:
                    result["memory_ingest"] = self.server.voice_mem_async.state()
            if self.server.asr is not None:
                result["asr"] = self.server.asr.health()
                result["mode"] = "external_final_utterance"
            else:
                result["mode"] = "voicemem_streaming"
            self._json(result)
            return
        if path == "/api/tts/status":
            if self.server.tts is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            self._json(self.server.tts.health())
            return
        if path == "/api/avatar/config":
            config = self.server.avatar_assets.config() if self.server.avatar_assets else {
                "enabled": False, "runtime_url": None, "model_url": None, "adapter": None,
            }
            config["presentation_url"] = self.server.presentation_url
            self._json(config)
            return
        if path in {
            "/api/jawl/status", "/api/jawl/overview", "/api/jawl/memory",
            "/api/jawl/persona", "/api/jawl/hostos", "/api/jawl/journal",
        }:
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            adapter = self.server.gateway.jawl_web
            if adapter is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            try:
                if path == "/api/jawl/status":
                    self._json({"configured": True, "status": adapter.status()})
                elif path == "/api/jawl/memory":
                    self._json(adapter.memory())
                elif path == "/api/jawl/persona":
                    self._json(adapter.persona())
                elif path == "/api/jawl/hostos":
                    self._json({**adapter.hostos(), "control_enabled": self.server.jawl_hostos_control})
                elif path == "/api/jawl/journal":
                    values = parse_qs(
                        urlsplit(self.path).query, keep_blank_values=True
                    )
                    try:
                        limit = int(values.get("limit", ["20"])[0])
                    except ValueError:
                        self._json(
                            {"error": "journal limit must be an integer"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if limit < 1 or limit > 50:
                        self._json(
                            {"error": "journal limit must be between 1 and 50"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    state_values = values.get("state", [""])
                    state = state_values[0] or None
                    if state not in {
                        None, "completed", "failed", "cancelled", "error",
                        "in_progress", "interrupted", "reconciled",
                    }:
                        self._json(
                            {"error": "unsupported journal state"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._json(adapter.autonomy_journal(limit=limit, state=state))
                else:
                    self._json(adapter.overview())
            except JawlWebUnavailable as exc:
                self._json({"configured": True, "status": "offline", "error": str(exc)})
            return
        asset_prefix = "/avatar-assets/"
        if self.server.legacy_presentation and path.startswith(asset_prefix) and self.server.avatar_assets is not None:
            asset = self.server.avatar_assets.resolve_public(path[len(asset_prefix):])
            if asset is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                body = asset.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            _security_headers(self)
            self.send_header("Content-Type", self.server.avatar_assets.content_type(asset))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/hostos/approvals":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            self._json({"approvals": self.server.approvals.list(self.server.session_token)})
            return
        if path == "/mic-processor.js":
            # AudioWorklet modules are loaded as a separate browser request;
            # serve only the pinned frontend worker, never arbitrary files.
            worker_path = self.server.frontend_dir / "mic-processor.js"
            try:
                body = worker_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "microphone worker is not installed")
                return
            self.send_response(HTTPStatus.OK)
            _security_headers(self)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html", "/avatar", "/avatar.html"):
            if path in ("/avatar", "/avatar.html") and not self.server.legacy_presentation:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            filename = "avatar.html" if path in ("/avatar", "/avatar.html") else "index.html"
            index_path = self.server.frontend_dir / filename
            try:
                body = index_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "frontend is not installed")
                return
            self.send_response(HTTPStatus.OK)
            _security_headers(self)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authenticate_network_request():
            return
        try:
            if self._proxy_jawl_console():
                return
            self._require_browser_session()
            payload = self._read_json()
            if self.path == "/api/avatar/audio":
                if payload.get("schema_version", 1) != 1:
                    raise ValueError("unsupported avatar audio schema")
                amplitude = payload.get("amplitude", 0.0)
                speaking = payload.get("speaking", False)
                timestamp_ms = payload.get("timestamp_ms", int(time.time() * 1000))
                if isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)) or not isfinite(float(amplitude)):
                    raise ValueError("amplitude must be a finite number")
                if not 0.0 <= float(amplitude) <= 1.0:
                    raise ValueError("amplitude must be between 0 and 1")
                if not isinstance(speaking, bool):
                    raise ValueError("speaking must be boolean")
                if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
                    raise ValueError("timestamp_ms must be an integer")
                self._json({"ok": True, "avatar_audio": self.server.set_avatar_audio(
                    float(amplitude), speaking, timestamp_ms,
                )})
                return
            if self.path == "/api/chat":
                self._json(self.server.gateway.handle_text(
                    self.server.enrich_turn_text(payload.get("text", "")),
                    session_id=str(payload.get("session_id") or self.server.session_token)[:200],
                    correlation_id=self._correlation_id(payload),
                ))
                return
            if self.path == "/api/chat/stream":
                self._stream_chat(payload.get("text", ""), self._correlation_id(payload))
                return
            if self.path == "/api/proactive/settings":
                feed = self.server.proactive_feed
                if feed is None:
                    self._json({"error": "proactive feed is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                feed.update_settings(muted=payload.get("muted"), speak=payload.get("speak"))
                self._json({"ok": True, "state": feed.state()})
                return
            if self.path == "/api/proactive/feedback":
                feed = self.server.proactive_feed
                if feed is None:
                    self._json({"error": "proactive feed is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json(feed.note_feedback(
                    payload.get("item_id", ""), payload.get("verdict", ""),
                ))
                return
            if self.path == "/api/stream-chat":
                event = payload.get("event", payload)
                if not isinstance(event, dict):
                    raise ValueError("stream chat event must be an object")
                result = self.server.stream_chat.accept(event, payload.get("url_metadata"))
                status = {
                    "accepted": HTTPStatus.ACCEPTED,
                    "invalid": HTTPStatus.BAD_REQUEST,
                    "stopped": HTTPStatus.CONFLICT,
                }.get(result.get("status"), HTTPStatus.OK)
                self._json({"ok": result.get("status") == "accepted", "result": result}, status=status)
                return
            if self.path == "/api/voice/partial":
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                text = payload.get("text", "")
                ended = payload.get("ended", False)
                if not isinstance(text, str) or not isinstance(ended, bool):
                    raise ValueError("text must be string and ended must be boolean")
                session_id = str(payload.get("session_id") or self.server.session_token)[:200]
                correlation_id = self._correlation_id(payload)
                events = self.server.voice_mem.feed_partial(text, ended=ended, session_id=session_id)
                responses = self._voice_turn_responses(events, session_id, correlation_id)
                self._json({
                    "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
                    "correlation_id": correlation_id,
                    "events": events,
                    "responses": responses,
                })
                return
            if self.path == "/api/voice/audio":
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json(self._feed_voice_chunk(payload))
                return
            if self.path == "/api/voice/draft":
                if self.server.asr is None and self.server.streaming_asr is None:
                    self._json({"ok": False, "draft": "", "error": "ASR is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                session_id = str(payload.get("session_id") or self.server.session_token)[:200]
                # Streaming lane first: sub-second partials + adaptive endpoint
                # policy. Falls back to the slower draft re-transcription.
                if self.server.streaming_asr is not None:
                    snapshot = self.server.streaming_asr.snapshot()
                    text = str(snapshot.get("text") or "").strip()
                    if snapshot.get("active") and text:
                        if not is_meaningful_transcript(text):
                            self._json({"ok": True, "draft": "", "mode": "streaming", "hold": False,
                                        "silence_ms": snapshot.get("silence_ms"), "required_ms": turn_policy.BASE_SILENCE_MS})
                            return
                        decision = turn_policy.decide(text, float(snapshot.get("silence_ms") or 0.0))
                        self._json({
                            "ok": True, "draft": text, "mode": "streaming",
                            "hold": bool(decision["hold"]),
                            "silence_ms": snapshot.get("silence_ms"),
                            "required_ms": decision["required_ms"],
                        })
                        return
                if self.server.asr is None:
                    self._json({"ok": True, "draft": "", "mode": "streaming"})
                    return
                try:
                    draft = self.server.asr.draft(session_id)
                except Exception as exc:  # noqa: BLE001 - drafts never break capture
                    self._json({"ok": False, "draft": "", "error": str(exc)[:300]})
                    return
                text = str(draft.get("text") or "").strip()
                if not is_meaningful_transcript(text):
                    self._json({"ok": True, "draft": "", "mode": "external_final_utterance"})
                    return
                decision = turn_policy.decide(text, 0.0)
                self._json({"ok": True, "draft": text, "mode": "external_final_utterance",
                            "hold": bool(decision["hold"]), "required_ms": decision["required_ms"]})
                return
            if self.path == "/api/voice/preface":
                # A short provisional phrase (no LLM) that can be spoken while
                # the JAWL turn is still thinking; the authoritative answer
                # follows it. Screen-shaped questions only, best-effort.
                partial = ""
                if self.server.streaming_asr is not None:
                    try:
                        snapshot = self.server.streaming_asr.snapshot()
                    except Exception:  # noqa: BLE001 - the preface is optional
                        snapshot = {}
                    if isinstance(snapshot, dict) and snapshot.get("active"):
                        partial = str(snapshot.get("text") or "").strip()
                self._json({"ok": True, "text": self.server.voice_preface(partial)})
                return
            if self.path == "/api/reflection/note":
                # Reflection write path: consolidation summaries enter VoiceMem
                # through the live sidecar (it owns the local vector store, so
                # a second process cannot open it concurrently).
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                text = str(payload.get("text") or "").strip()[:4000]
                if not text:
                    raise ValueError("text must be non-empty")
                events = self.server.voice_mem.feed_partial(text, ended=True, session_id="reflection")
                self._json({"ok": True, "mode": "reflection", "events": len(events or [])})
                return
            if self.path == "/api/voice/end":
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json(self._finish_voice_turn(payload))
                return
            if self.path == "/api/tts/synthesize":
                if self.server.tts is None:
                    self._json({"error": "TTS provider is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                text = payload.get("text", "")
                voice = payload.get("voice")
                speed = payload.get("speed", 1.0)
                emotion = payload.get("emotion")
                if not isinstance(text, str) or voice is not None and not isinstance(voice, str):
                    raise ValueError("text must be string and voice must be string or null")
                if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                    raise ValueError("speed must be a number")
                if emotion is not None and not isinstance(emotion, dict):
                    raise ValueError("emotion must be an object or null")
                audio = self.server.tts.synthesize(
                    text, voice=voice, speed=float(speed), emotion=emotion
                )
                self._audio(audio)
                return
            if self.path == "/api/tts/stream":
                if self.server.tts is None:
                    self._json({"error": "TTS provider is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                text = payload.get("text", "")
                voice = payload.get("voice")
                speed = payload.get("speed", 1.0)
                emotion = payload.get("emotion")
                if not isinstance(text, str) or voice is not None and not isinstance(voice, str):
                    raise ValueError("text must be string and voice must be string or null")
                if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                    raise ValueError("speed must be a number")
                if emotion is not None and not isinstance(emotion, dict):
                    raise ValueError("emotion must be an object or null")
                self._stream_tts(text, voice=voice, speed=float(speed), emotion=emotion)
                return
            if self.path == "/api/tts/cancel":
                if self.server.tts is not None:
                    self.server.tts.cancel()
                self._json({"ok": True, "status": "cancelled"})
                return
            if self.path == "/api/hostos/execute":
                raw_request = payload.get("request", payload)
                if not isinstance(raw_request, dict):
                    raise ValueError("request must be an object")
                if self.server.jawl_hostos_control:
                    adapter = self.server.gateway.jawl_web
                    if adapter is None:
                        raise JawlWebUnavailable("JAWL HostOS control is not configured")
                    native = adapter.execute_hostos_skill(
                        str(raw_request.get("skill") or raw_request.get("tool") or ""),
                        raw_request.get("arguments", {}),
                    )
                    self._json({"ok": True, "native": True, "result": native["result"]})
                    return
                request = ToolRequest.from_dict(raw_request)
                approval_id = payload.get("approval_id")
                approval = self.server.approvals.consume(
                    str(approval_id) if approval_id else None,
                    request,
                    self.server.session_token,
                )
                result = self.server.hostos.execute(request, has_approval=bool(approval["approved"]))
                self._json({"ok": result["status"] in {"verified", "dispatched", "degraded"}, "result": result})
                return
            if self.path == "/api/debug/skill":
                if not self.server.jawl_hostos_control:
                    raise JawlWebUnavailable("native JAWL control is not enabled")
                adapter = self.server.gateway.jawl_web
                if adapter is None:
                    raise JawlWebUnavailable("JAWL control is not configured")
                skill = str(payload.get("skill") or "").strip()
                arguments = payload.get("arguments", {})
                result = adapter.execute_debug_skill(skill, arguments)
                self._json({"ok": True, "native": True, "result": result["result"]})
                return
            if self.path == "/api/hostos/approvals/request":
                raw_request = payload.get("request", payload)
                if not isinstance(raw_request, dict):
                    raise ValueError("request must be an object")
                result = self.server.approvals.request(
                    ToolRequest.from_dict(raw_request),
                    self.server.session_token,
                )
                self._json({"ok": result["status"] == "approval_required", "result": result})
                return
            if self.path == "/api/vision/look":
                prompt = payload.get("prompt", "")
                force = payload.get("force", False)
                if not isinstance(force, bool):
                    raise ValueError("force must be boolean")
                result = self.server.vision.look(
                    prompt,
                    force=force,
                    session_id=self.server.session_token,
                )
                self._json({"ok": result["status"] in {"ok", "unchanged"}, "result": result})
                return
            if self.path == "/api/vision/execute":
                if payload.get("confirm") is not True:
                    raise ValueError("confirm=true is required for vision actions")
                plan = payload.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("plan must be an object")
                result = self.server.vision.execute_plan(
                    plan,
                    session_id=self.server.session_token,
                )
                self._json({"ok": result["status"] == "verified", "result": result})
                return
            if self.path == "/api/jawl/memory":
                adapter = self.server.gateway.jawl_web
                if adapter is None:
                    raise JawlWebUnavailable("JAWL memory control is not configured")
                operation = str(payload.get("operation") or "").strip()
                allowed = {
                    key: payload[key]
                    for key in (
                        "memory_key", "kind", "subject", "predicate", "value",
                        "source", "confidence", "provenance", "reason",
                        "valid_from", "valid_until", "retention_tier",
                    )
                    if key in payload
                }
                if operation == "remember":
                    result = adapter.remember_memory(**allowed)
                elif operation == "revise":
                    memory_key = str(allowed.pop("memory_key", "")).strip()
                    result = adapter.revise_memory(memory_key, **allowed)
                elif operation == "forget":
                    result = adapter.forget_memory(
                        str(allowed.get("memory_key") or ""),
                        str(allowed.get("reason") or "browser request"),
                    )
                elif operation == "archive":
                    result = adapter.archive_memory(
                        str(allowed.get("memory_key") or ""),
                        str(allowed.get("reason") or "browser request"),
                    )
                else:
                    raise ValueError("unsupported JAWL memory operation")
                self._json({"ok": True, "native": True, "result": result})
                return
            if self.path == "/api/jawl/restart":
                adapter = self.server.gateway.jawl_web
                if adapter is None:
                    raise JawlWebUnavailable("JAWL lifecycle control is not configured")
                result = adapter.restart_agent(wait_for_memory=True)
                self._json({"ok": True, "native": True, "result": result})
                return
            parts = urlsplit(self.path)
            prefix = "/api/hostos/approvals/"
            if parts.path.startswith(prefix) and parts.path.endswith("/execute"):
                approval_id = parts.path[len(prefix) : -len("/execute")]
                result = self.server.approvals.execute(approval_id, self.server.session_token)
                self._json({"ok": result.get("status") in {"verified", "dispatched", "degraded"}, "result": result})
                return
            if parts.path.startswith(prefix) and parts.path.endswith("/approve"):
                approval_id = parts.path[len(prefix) : -len("/approve")]
                self._json({"result": self.server.approvals.decide(approval_id, self.server.session_token, True)})
                return
            if parts.path.startswith(prefix) and parts.path.endswith("/deny"):
                approval_id = parts.path[len(prefix) : -len("/deny")]
                self._json({"result": self.server.approvals.decide(approval_id, self.server.session_token, False)})
                return
            if self.path == "/api/hostos/level":
                if "level" not in payload:
                    raise ValueError("level is required")
                jawl_hostos = None
                if self.server.jawl_hostos_control:
                    adapter = self.server.gateway.jawl_web
                    if adapter is None:
                        raise JawlWebUnavailable("JAWL HostOS control is not configured")
                    jawl_hostos = adapter.set_hostos_level(payload["level"])
                state = self.server.gateway.policy.set_access_level(payload["level"], actor="browser")
                result = {"ok": True, "policy": state}
                if jawl_hostos is not None:
                    result["jawl_hostos"] = jawl_hostos
                self._json(result)
                return
            if self.path == "/api/hostos/unattended":
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be boolean")
                ttl_seconds = payload.get("ttl_seconds", 3600)
                if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
                    raise ValueError("ttl_seconds must be an integer")
                jawl_lease = None
                adapter = self.server.gateway.jawl_web
                # Enabling is native-first: if JAWL cannot issue its bounded
                # lease, the compatibility executor must not silently remain
                # autonomous.  Disabling is local-first so a lost native link
                # always fails closed on this process too.
                if self.server.jawl_hostos_control and enabled:
                    if adapter is None:
                        raise JawlWebUnavailable("JAWL HostOS control is not configured")
                    jawl_lease = adapter.set_unattended(
                        True, ttl_seconds=ttl_seconds, actor="browser"
                    )
                state = self.server.gateway.policy.set_unattended(
                    enabled, actor="browser", ttl_seconds=ttl_seconds
                )
                if self.server.jawl_hostos_control and not enabled:
                    if adapter is None:
                        raise JawlWebUnavailable("JAWL HostOS control is not configured")
                    jawl_lease = adapter.set_unattended(
                        False, ttl_seconds=ttl_seconds, actor="browser"
                    )
                result = {"ok": True, "policy": state}
                if jawl_lease is not None:
                    result["jawl_hostos"] = jawl_lease
                self._json(result)
                return
            if self.path == "/api/hostos/denylist":
                state = self.server.gateway.policy.set_denylist(
                    tools=payload.get("tools"), risks=payload.get("risks"), actor="browser"
                )
                self._json({"ok": True, "policy": state})
                return
            if self.path == "/api/emergency-stop":
                state = self.server.hostos.activate_emergency_stop(actor="browser")
                native_required = bool(self.server.jawl_hostos_control)
                native_ok = not native_required
                result = {"ok": native_ok, "policy": state}
                if native_required and self.server.gateway.jawl_web is not None:
                    native_ok = True
                    try:
                        result["jawl_policy"] = self.server.gateway.jawl_web.emergency_stop(
                            actor="browser", reason="Companion emergency stop"
                        )
                        native_ok = native_ok and result["jawl_policy"].get("status") == "stopped"
                    except JawlWebUnavailable as exc:
                        result["jawl_policy"] = {"status": "offline", "error": str(exc)}
                        native_ok = False
                    try:
                        result["jawl_agent"] = self.server.gateway.jawl_web.stop_agent()
                        native_ok = native_ok and result["jawl_agent"].get("status") == "stopped"
                    except JawlWebUnavailable as exc:
                        result["jawl_agent"] = {"status": "offline", "error": str(exc)}
                        native_ok = False
                elif native_required:
                    result["jawl_policy"] = {"status": "offline", "error": "JAWL control is unavailable"}
                    result["jawl_agent"] = {"status": "offline", "error": "JAWL control is unavailable"}
                result["ok"] = native_ok
                self._json(result, status=HTTPStatus.OK if native_ok else HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if self.path == "/api/emergency-stop/reset":
                native_required = bool(self.server.jawl_hostos_control)
                native_ok = not native_required
                result: dict[str, Any] = {"ok": native_ok}
                if native_required and self.server.gateway.jawl_web is not None:
                    # Start while the native latch is still set; only clear the
                    # latch after the agent is confirmed to have started.
                    native_ok = True
                    try:
                        result["jawl_agent"] = self.server.gateway.jawl_web.start_agent()
                        native_ok = native_ok and result["jawl_agent"].get("status") == "started"
                    except JawlWebUnavailable as exc:
                        result["jawl_agent"] = {"status": "offline", "error": str(exc)}
                        native_ok = False
                    if native_ok:
                        try:
                            result["jawl_policy"] = self.server.gateway.jawl_web.reset_emergency_stop(
                                actor="browser"
                            )
                            native_ok = result["jawl_policy"].get("status") == "reset"
                        except JawlWebUnavailable as exc:
                            result["jawl_policy"] = {"status": "offline", "error": str(exc)}
                            native_ok = False
                elif native_required:
                    result["jawl_agent"] = {"status": "offline", "error": "JAWL control is unavailable"}
                    result["jawl_policy"] = {"status": "offline", "error": "JAWL control is unavailable"}
                result["ok"] = native_ok
                result["policy"] = (
                    self.server.hostos.reset_emergency_stop(actor="browser")
                    if native_ok else self.server.hostos.policy.snapshot()
                )
                self._json(result, status=HTTPStatus.OK if native_ok else HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if self.path == "/api/attention":
                values = {key: payload[key] for key in ("dnd", "min_significance", "cooldown_seconds", "budget_per_hour", "quiet_hours") if key in payload}
                if not values:
                    raise ValueError("attention settings are required")
                attention = self.server.attention.configure(**values)
                self.server._persist_presence_preferences()
                self._json({"ok": True, "attention": attention, "persistent": self.server.presence_file is not None})
                return
            if self.path == "/api/resources":
                values = {
                    key: payload[key]
                    for key in ("profile", "gaming_mode")
                    if key in payload
                }
                if not values:
                    raise ValueError("resource settings are required")
                self._json({"ok": True, "resources": self.server.resources.configure(**values)})
                return
            if self.path == "/api/ambient-memory/triage":
                self._json(self.server.ambient_memory.triage())
                return
            if self.path == "/api/ambient-memory/promote":
                if payload.get("confirm") is not True:
                    raise ValueError("promoting ambient memory requires confirm=true")
                episode_id = str(payload.get("episode_id") or "").strip()[:120]
                if not episode_id:
                    raise ValueError("episode_id is required")
                episode = self.server.ambient_memory.episode(episode_id)
                if episode is None:
                    raise ValueError("ambient episode was not found or expired")
                episode_payload = episode.get("payload")
                if not isinstance(episode_payload, dict):
                    raise ValueError("ambient episode payload is invalid")
                if episode_payload.get("importance") != "promote_candidate":
                    raise ValueError("only promote_candidate episodes may be promoted")
                if episode_payload.get("promoted"):
                    self._json({"ok": True, "status": "already_promoted", "episode": episode})
                    return
                adapter = self.server.gateway.jawl_web
                if adapter is None or not adapter.token:
                    raise JawlWebUnavailable("JAWL memory control requires a console token")
                memory_key = f"ambient.episode.{episode_id}"
                stored = adapter.remember_memory(
                    memory_key=memory_key,
                    kind="summary",
                    subject="ambient",
                    predicate="episode_summary",
                    value=str(episode_payload.get("summary") or "")[:4000],
                    source=f"ambient:{str(episode_payload.get('source') or 'mixed')[:32]}",
                    confidence=float(episode_payload.get("confidence", 0.5)),
                    provenance={
                        "ambient_episode_id": episode_id,
                        "source_event_ids": list(episode_payload.get("source_event_ids") or [])[:32],
                        "observed_from": str(episode_payload.get("observed_from") or "")[:80],
                        "observed_until": str(episode_payload.get("observed_until") or "")[:80],
                        "triage_provider": str(episode_payload.get("triage_provider") or "deterministic")[:80],
                    },
                    valid_from=str(episode_payload.get("observed_from") or "") or None,
                    retention_tier="standard",
                )
                marked = self.server.ambient_memory.mark_promoted(episode_id, memory_key)
                self._json({"ok": True, "status": "promoted", "episode": marked, "memory": stored})
                return
            if self.path == "/api/ambient-memory/clear":
                self._json(self.server.ambient_memory.clear())
                return
            if self.path == "/api/ambient-memory/config":
                mode = str(payload.get("mode") or "set").strip()
                if mode == "disable_and_erase":
                    if payload.get("confirm") is not True:
                        raise ValueError("disable_and_erase requires confirm=true")
                    if self.server.ambient_audio is not None:
                        self.server.ambient_audio.stop()
                    self.server.ambient_memory.set_enabled(False)
                    erased = self.server.ambient_memory.clear()
                    self._json({
                        "ok": True,
                        "mode": mode,
                        "state": self.server.ambient_memory.state(),
                        "erased": erased,
                    })
                    return
                if mode != "set":
                    raise ValueError("unsupported ambient memory mode")
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be boolean")
                if not enabled and self.server.ambient_audio is not None:
                    self.server.ambient_audio.stop()
                self._json({"ok": True, "state": self.server.ambient_memory.set_enabled(enabled)})
                return
            if self.path == "/api/ambient-audio/start":
                if self.server.ambient_audio is None:
                    self._json({"error": "system audio is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json({"ok": True, "state": self.server.ambient_audio.start()})
                return
            if self.path == "/api/ambient-audio/stop":
                if self.server.ambient_audio is None:
                    self._json({"error": "system audio is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json({"ok": True, "state": self.server.ambient_audio.stop()})
                return
            if self.path == "/api/ambient-audio/playback":
                active = payload.get("active")
                if not isinstance(active, bool):
                    raise ValueError("active must be boolean")
                if active:
                    ttl_seconds = payload.get("ttl_seconds", 30)
                    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
                        raise ValueError("ttl_seconds must be numeric")
                    state = self.server.playback_suppression.begin(ttl_seconds)
                else:
                    state = self.server.playback_suppression.end()
                self._json({"ok": True, "playback": state})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
        except VoiceMemUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except ASRUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except AmbientAudioDisabled as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except SystemAudioUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except TTSCancelled:
            self._json({"error": "speech request was superseded"}, status=HTTPStatus.CONFLICT)
        except TTSUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except JawlWebUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        # The first server must not leak request contents into stdout.
        return

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        decoded = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(decoded, dict):
            raise ValueError("JSON body must be an object")
        return decoded

    def _proxy_jawl_console(self) -> bool:
        """Reverse-proxy the JAWL console under this origin (single-origin UI).

        ``/console/*`` maps to the console's own files and ``/console-api/*``
        maps back to its ``/api/*`` namespace; console.js is rewritten so its
        absolute API calls stay inside the proxied namespace. The console
        token is injected server-side; the browser only needs the Companion
        session cookie.
        """
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/console":
            location = "/console/" + (("?" + parsed.query) if parsed.query else "")
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", location)
            self.end_headers()
            return True
        if not (path.startswith("/console/") or path.startswith("/console-api/")):
            return False
        presented = self.headers.get("X-Companion-Session") or ""
        if not presented:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie = cookies.get("companion_session")
            presented = cookie.value if cookie is not None else ""
        if presented != self.server.session_token:
            self._json({"error": "valid local session is required"}, status=HTTPStatus.FORBIDDEN)
            return True
        adapter = self.server.gateway.jawl_web
        if adapter is None:
            self._json({"error": "JAWL console proxy is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return True
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and not self.server.origin_allowed(origin, self.headers.get("Host")):
                self._json({"error": "request origin is not allowed"}, status=HTTPStatus.FORBIDDEN)
                return True
        if path.startswith("/console-api/"):
            upstream_path = "/api" + path[len("/console-api"):]
        else:
            upstream_path = path[len("/console"):]
        target = adapter.base_url.rstrip("/") + upstream_path
        if parsed.query:
            target += "?" + parsed.query
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else None
        headers = {"Host": urlsplit(adapter.base_url).netloc}
        if adapter.token:
            headers["X-Console-Token"] = adapter.token
        content_type = self.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type
        accept = self.headers.get("Accept")
        if accept:
            headers["Accept"] = accept
        upstream = urllib_request.Request(target, data=body, headers=headers, method=self.command)
        try:
            response = urllib_request.urlopen(upstream, timeout=30)
        except urllib_error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            upstream_type = exc.headers.get("Content-Type")
            if upstream_type:
                self.send_header("Content-Type", upstream_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return True
        except Exception:  # noqa: BLE001 - proxy failures must fail closed
            self._json({"error": "JAWL console upstream is unavailable"}, status=HTTPStatus.BAD_GATEWAY)
            return True
        with response:
            response_type = response.headers.get("Content-Type", "application/octet-stream")
            self.send_response(response.status)
            self.send_header("Content-Type", response_type)
            if "text/event-stream" in response_type:
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return True
            payload = response.read()
            if "javascript" in response_type:
                try:
                    payload = payload.decode("utf-8").replace('"/api/', '"/console-api/').encode("utf-8")
                except UnicodeDecodeError:
                    pass
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        return True

    def _serve_websocket(self) -> None:
        """P2 single-connection transport: chat and voice over one socket."""
        if urlsplit(self.path).path != "/api/ws":
            self._json({"error": "unsupported websocket path"}, status=HTTPStatus.NOT_FOUND)
            return
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        cookie = cookies.get("companion_session")
        presented = cookie.value if cookie is not None else ""
        origin = self.headers.get("Origin")
        if not self.server.origin_allowed(origin, self.headers.get("Host")):
            self._json({"error": "request origin is not allowed"}, status=HTTPStatus.FORBIDDEN)
            return
        if presented != self.server.session_token:
            self._json({"error": "valid local session is required"}, status=HTTPStatus.FORBIDDEN)
            return
        send_handshake_response(self)
        try:
            self.connection.settimeout(None)
        except OSError:
            pass
        connection = WebSocketConnection(self.rfile, self.connection)
        try:
            while not connection.closed:
                raw = connection.read_message()
                if raw is None:
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    connection.send_text(json.dumps({"type": "error", "error": "invalid json"}))
                    continue
                if not isinstance(payload, dict):
                    connection.send_text(json.dumps({"type": "error", "error": "payload must be an object"}))
                    continue
                self._handle_ws_action(connection, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except WebSocketError:
            pass
        finally:
            self.close_connection = True
            try:
                connection.send_close()
            except OSError:
                pass

    def _handle_ws_action(self, connection: WebSocketConnection, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "")
        send = lambda data: connection.send_text(json.dumps(data, ensure_ascii=False))  # noqa: E731
        if action == "ping":
            send({"type": "pong"})
            return
        if action == "chat":
            correlation_id = self._correlation_id(payload)
            try:
                for event in self.server.gateway.stream_text(
                    self.server.enrich_turn_text(str(payload.get("text") or "")),
                    session_id=self.server.session_token,
                    correlation_id=correlation_id,
                ):
                    send(event)
            except Exception as exc:  # noqa: BLE001 - report provider failures in-band
                send({"type": "error", "error": str(exc)[:500], "correlation_id": correlation_id})
            return
        if action == "voice_chunk":
            send({"type": "voice_ack", **self._feed_voice_chunk(payload)})
            return
        if action == "voice_end":
            send({"type": "voice_final", **self._finish_voice_turn(payload)})
            return
        if action == "voice_reset":
            if self.server.streaming_asr is not None:
                try:
                    self.server.streaming_asr.reset_utterance()
                except Exception:
                    pass
            send({"type": "voice_reset_ack"})
            return
        send({"type": "error", "error": "unsupported_action"})

    def _feed_voice_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Shared voice-chunk ingestion for /api/voice/audio and the WS transport."""
        if self.server.voice_mem is None:
            return {"ok": False, "error": "VoiceMem sidecar is not configured"}
        encoded = payload.get("pcm16_base64", "")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("pcm16_base64 must be a non-empty string")
        try:
            pcm16 = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("pcm16_base64 is invalid") from exc
        sample_rate = payload.get("sample_rate", 16000)
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            raise ValueError("sample_rate must be an integer")
        channels = payload.get("channels", 1)
        if isinstance(channels, bool) or not isinstance(channels, int):
            raise ValueError("channels must be an integer")
        session_id = str(payload.get("session_id") or self.server.session_token)[:200]
        if self.server.streaming_asr is not None:
            try:
                self.server.streaming_asr.feed(pcm16, sample_rate=sample_rate, channels=channels)
            except Exception:
                pass  # the streaming lane is an accelerator, never a blocker
        if self.server.asr is not None:
            buffered = self.server.asr.feed_audio(
                pcm16, sample_rate=sample_rate, channels=channels, session_id=session_id
            )
            return {"ok": True, "mode": "external_final_utterance", "events": [], "responses": [], "buffer": buffered}
        events = self.server.voice_mem.feed_audio(
            pcm16, sample_rate=sample_rate, session_id=session_id
        )
        responses = self._voice_turn_responses(events, session_id)
        return {
            "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
            "events": events,
            "responses": responses,
        }

    def _finish_voice_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Shared utterance finalization for /api/voice/end and the WS transport."""
        if self.server.voice_mem is None:
            return {"ok": False, "error": "VoiceMem sidecar is not configured"}
        session_id = str(payload.get("session_id") or self.server.session_token)[:200]
        if self.server.asr is not None:
            batch_text = ""
            transcriber = getattr(self.server, "gigaam_transcriber", None)
            if transcriber is not None:
                try:
                    wav_bytes = self.server.asr.to_wav(session_id)
                    if wav_bytes:
                        batch_text = str(transcriber.transcribe(wav_bytes) or "").strip()[:12_000]
                except Exception:  # noqa: BLE001 - batch lane is an accelerator
                    batch_text = ""
            if batch_text and is_meaningful_transcript(batch_text):
                # GigaAM (Sber) file-mode transcription of the complete
                # buffered utterance: measured faster and more accurate than
                # the Qwen fallback; drop the buffer without a second call.
                try:
                    self.server.asr.discard(session_id)
                except Exception:
                    pass
                transcription = {"status": "transcribed", "text": batch_text}
                asr_source = "gigaam"
            else:
                try:
                    transcription = self.server.asr.finish(session_id)
                except Exception as exc:  # noqa: BLE001 - the fallback lane may be offline
                    return {"ok": False, "error": f"ASR fallback failed: {type(exc).__name__}"}
                asr_source = "qwen"
            if self.server.streaming_asr is not None:
                try:
                    self.server.streaming_asr.reset_utterance()
                except Exception:
                    pass
            if transcription["status"] in {"empty", "no_speech"}:
                return {"ok": True, "mode": "external_final_utterance", "transcript": "", "events": [], "responses": []}
            text = str(transcription["text"] or "").strip()[:12_000]
            if not is_meaningful_transcript(text):
                log_event("asr_filtered", reason="noise_hallucination", text=text, source=asr_source)
                return {
                    "ok": True, "mode": "external_final_utterance",
                    "transcript": "", "events": [], "responses": [],
                    "filtered": "asr_noise_hallucination",
                }
            log_event("asr_final", text=text, session=session_id[:40], source=asr_source)
            correlation_id = self._correlation_id(payload)
            events = self._external_asr_events(text, session_id, correlation_id)
            memory_sync = (
                self.server.voice_mem_async.enqueue_partial(
                    text, ended=True, session_id=session_id,
                )
                if self.server.voice_mem_async is not None
                else {"status": "not_configured"}
            )
            responses = self._voice_turn_responses(events, session_id)
            return {
                "ok": memory_sync.get("status") in {"queued", "not_configured"},
                "mode": "external_final_utterance",
                "correlation_id": correlation_id,
                "transcript": text,
                "events": events,
                "responses": responses,
                "memory_sync": memory_sync,
            }
        events = self.server.voice_mem.end_audio(session_id=session_id)
        responses = self._voice_turn_responses(events, session_id, self._correlation_id(payload))
        return {
            "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
            "events": events,
            "responses": responses,
        }

    def _require_browser_session(self) -> None:
        presented_session = self.headers.get("X-Companion-Session")
        if not presented_session:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie = cookies.get("companion_session")
            presented_session = cookie.value if cookie is not None else ""
        if presented_session != self.server.session_token:
            raise PermissionError("valid local session is required")
        if self.headers.get("X-Companion-CSRF") != self.server.csrf_token:
            raise PermissionError("valid CSRF token is required")
        origin = self.headers.get("Origin")
        if not self.server.origin_allowed(origin, self.headers.get("Host")):
            raise PermissionError("request origin is not allowed")

    def _authenticate_network_request(self) -> bool:
        """Challenge every LAN control request before serving UI or API data."""
        if not self.server.lan_mode:
            return True
        authorization = self.headers.get("Authorization", "")
        scheme, _, encoded = authorization.partition(" ")
        username = password = ""
        if scheme.casefold() == "basic" and encoded:
            try:
                decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (ValueError, UnicodeError, base64.binascii.Error):
                username = password = ""
        valid_user = hmac.compare_digest(
            username.encode("utf-8"), self.server.lan_auth_user.encode("utf-8")
        )
        valid_token = hmac.compare_digest(
            password.encode("utf-8"), self.server.lan_access_token.encode("utf-8")
        )
        if valid_user and valid_token:
            return True
        self._unauthorized()
        return False

    def _unauthorized(self) -> None:
        body = b'{"error":"LAN authentication required"}'
        self.send_response(HTTPStatus.UNAUTHORIZED)
        _security_headers(self)
        self.send_header("WWW-Authenticate", f'Basic realm="{LAN_AUTH_REALM}", charset="UTF-8"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        set_session_cookie: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        _security_headers(self)
        if set_session_cookie:
            cookie_flags = "; Secure" if self.server.tls_enabled else ""
            self.send_header(
                "Set-Cookie",
                f"companion_session={self.server.session_token}; HttpOnly; SameSite=Strict; Path=/{cookie_flags}",
            )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        _security_headers(self)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_tts(
        self,
        text: str,
        *,
        voice: str | None,
        speed: float,
        emotion: dict[str, Any] | None = None,
    ) -> None:
        """Send sentence WAVs as newline-delimited JSON without buffering the reply."""
        self.send_response(HTTPStatus.OK)
        _security_headers(self)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

        stream = self.server.tts.stream(
            text, voice=voice, speed=speed, emotion=emotion
        )
        try:
            count = 0
            for index, audio in enumerate(stream):
                self._stream_event({
                    "type": "audio",
                    "index": index,
                    "media_type": "audio/wav",
                    "data_base64": base64.b64encode(audio).decode("ascii"),
                })
                count += 1
            self._stream_event({"type": "done", "count": count})
        except TTSCancelled:
            try:
                self._stream_event({"type": "cancelled"})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                return
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            # Closing the browser stream closes the service-owned generator in
            # its finally block, which cancels only this synthesis generation.
            return
        except Exception as exc:  # noqa: BLE001 - report provider failures in-band
            try:
                self._stream_event({"type": "error", "error": str(exc)[:500]})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                return
        finally:
            # A disconnected browser request must release the service-owned
            # generator immediately; relying on frame destruction can leave
            # the single speech slot occupied after barge-in.
            stream.close()

    @staticmethod
    def _correlation_id(payload: dict[str, Any]) -> str:
        value = str(payload.get("correlation_id") or "").strip()
        return value[:128] if value else f"turn-{uuid4().hex}"

    def _stream_chat(self, text: str, correlation_id: str | None = None) -> None:
        """Stream text deltas and one final ResponseEnvelope as NDJSON."""
        self.send_response(HTTPStatus.OK)
        _security_headers(self)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in self.server.gateway.stream_text(
                self.server.enrich_turn_text(text), session_id=self.server.session_token, correlation_id=correlation_id,
            ):
                self._stream_event(event)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return
        except Exception as exc:  # noqa: BLE001 - report provider failures in-band
            try:
                self._stream_event({"type": "error", "error": str(exc)[:500]})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                return

    def _stream_event(self, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _voice_turn_responses(
        self, events: list[dict[str, Any]], session_id: str, correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        responses = []
        for event in events:
            if event.get("type") != "VOICE_TURN":
                continue
            turn_text = event.get("payload", {}).get("text", "")
            responses.append(self.server.gateway.handle_text(
                self.server.enrich_turn_text(turn_text), session_id=session_id,
                correlation_id=event.get("correlation_id") or correlation_id,
            ))
        return responses

    @staticmethod
    def _external_asr_events(
        text: str, session_id: str, correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Create transport events from authoritative final ASR text.

        The Companion is not a second cognitive runtime here: it only adapts
        the already-transcribed utterance into the same event shape that the
        VoiceMem sidecar emits. VoiceMem receives the identical text on its
        bounded background queue for memory/affect enrichment.
        """
        request_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        common = {
            "schema_version": 1,
            "request_id": request_id,
            "session_id": session_id,
            "created_at": created_at,
            "source": "companion_external_asr",
            "priority": 0,
            "correlation_id": correlation_id or f"turn-{uuid4().hex}",
        }
        return [
            {
                **common,
                "event_id": str(uuid4()),
                "type": "USER_PARTIAL",
                "payload": {"text": text, "is_final": False},
            },
            {
                **common,
                "event_id": str(uuid4()),
                "type": "VOICE_TURN",
                "payload": {
                    "text": text,
                    "is_final": True,
                    "memory_context": "",
                    "affect": {},
                    "speaker_id": "",
                },
            },
        ]


class CompanionPresentationServer(ThreadingHTTPServer):
    """Unprivileged loopback origin for the avatar/OBS surface."""

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        companion: CompanionServer,
        tls_context: ssl.SSLContext | None = None,
        presentation_access_token: str | None = None,
    ):
        self.companion = companion
        self.frontend_dir = companion.frontend_dir
        self.avatar_assets = companion.avatar_assets
        self.tls_enabled = tls_context is not None
        self.url_scheme = "https" if self.tls_enabled else "http"
        self.remote_access = not is_loopback_host(server_address[0])
        self.presentation_access_token = (
            _validate_lan_access_token(presentation_access_token)
            if self.remote_access
            else ""
        )
        super().__init__(server_address, CompanionPresentationRequestHandler)
        if tls_context is not None:
            self.socket = tls_context.wrap_socket(self.socket, server_side=True)


class CompanionPresentationRequestHandler(BaseHTTPRequestHandler):
    server: CompanionPresentationServer

    def _require_presentation_access(self) -> bool:
        """Authenticate remote presentation reads without affecting loopback OBS."""
        if not self.server.remote_access:
            return True
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        candidate = self.headers.get("X-Companion-Presentation-Token") or (
            query.get("token", [""])[0]
        )
        expected = self.server.presentation_access_token
        if expected and hmac.compare_digest(str(candidate), expected):
            return True
        self.send_error(HTTPStatus.FORBIDDEN, "presentation access token required")
        return False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if not self._require_presentation_access():
            return
        if path == "/api/presentation/state":
            self._json(self.server.companion.presentation_state())
            return
        if path == "/api/presentation/config":
            config = self.server.avatar_assets.config() if self.server.avatar_assets else {
                "enabled": False,
                "runtime_url": None,
                "model_url": None,
                "adapter": None,
                "capabilities": {
                    "expressions": 0,
                    "motion_groups": [],
                    "physics": False,
                    "pose": False,
                    "display_info": False,
                    "lip_sync": True,
                    "fallback_expressions": [
                        "neutral", "attentive", "concerned", "confused",
                        "happy", "sad", "angry", "surprised",
                    ],
                },
            }
            self._json(config)
            return
        asset_prefix = "/avatar-assets/"
        if path.startswith(asset_prefix) and self.server.avatar_assets is not None:
            asset = self.server.avatar_assets.resolve_public(path[len(asset_prefix):])
            if asset is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                body = asset.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            _security_headers(self, presentation=True)
            self.send_header("Content-Type", self.server.avatar_assets.content_type(asset))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/", "/avatar", "/avatar.html"}:
            index_path = self.server.frontend_dir / "avatar.html"
            try:
                body = index_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "frontend is not installed")
                return
            self.send_response(HTTPStatus.OK)
            _security_headers(self, presentation=True)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - read-only presentation API
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        _security_headers(self, presentation=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _local_url(host: str, port: int, path: str) -> str:
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{host_part}:{port}{path}"


def create_presentation_server(
    companion: CompanionServer,
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    lan_mode: bool = False,
    tls_cert_file: str | os.PathLike[str] | None = None,
    tls_key_file: str | os.PathLike[str] | None = None,
    access_token: str | None = None,
) -> CompanionPresentationServer:
    """Create the isolated avatar/OBS server without exposing control state.

    A remote presentation bind gets its own read-only bearer token.  The token
    is intentionally separate from the control-plane LAN credential so an OBS
    or tablet link cannot be upgraded into a control session.
    """
    host = require_bind_host(host, lan_mode=lan_mode)
    tls_context = create_tls_context(tls_cert_file, tls_key_file)
    if not is_loopback_host(host) and tls_context is None:
        raise ValueError("non-loopback LAN presentation requires a trusted TLS certificate and private key")
    remote_token = access_token or (secrets.token_urlsafe(24) if not is_loopback_host(host) else None)
    server = CompanionPresentationServer(
        (host, port),
        companion,
        tls_context=tls_context,
        presentation_access_token=remote_token,
    )
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    url = f"{server.url_scheme}://{host_part}:{server.server_port}/avatar"
    if server.remote_access:
        url += "?token=" + quote(server.presentation_access_token, safe="")
    companion.set_presentation_url(url)
    return server


def create_server(
    host: str = "127.0.0.1",
    port: int = 2367,
    frontend_dir: Path | None = None,
    gateway: TextGateway | None = None,
    hostos_executor: HostOSExecutor | None = None,
    vision_describer: Any | None = None,
    screen_watch: bool = False,
    screen_watch_interval: float = 10.0,
    voice_mem: VoiceMemProcessClient | None = None,
    tts_service: TTSService | None = None,
    avatar_assets: AvatarAssetStore | None = None,
    jawl_event_dir: Path | None = None,
    attention: AttentionPresence | None = None,
    activity_provider: Callable[[], dict[str, Any]] | None = None,
    ambient_memory: AmbientMemoryBuffer | None = None,
    ambient_audio: AmbientAudioService | None = None,
    ambient_scheduler: AmbientTriageScheduler | None = None,
    resource_governor: ResourceGovernor | None = None,
    jawl_hostos_control: bool = False,
    audit_file: Path | None = None,
    asr_service: ExternalASRService | None = None,
    streaming_asr: Any | None = None,
    gigaam_transcriber: Any | None = None,
    helper_urls: dict[str, str] | None = None,
    proactive_feed: Any | None = None,
    sensory_ingestor: Any | None = None,
    perception_fusion: Any | None = None,
    legacy_presentation: bool = True,
    presence_file: Path | None = None,
    stream_chat: StreamChatIngestor | None = None,
    stream_chat_event_sink: Callable[[dict[str, Any]], Any] | None = None,
    lan_mode: bool = False,
    lan_access_token: str | None = None,
    lan_auth_user: str = "tablet",
    tls_context: ssl.SSLContext | None = None,
    tls_cert_file: str | os.PathLike[str] | None = None,
    tls_key_file: str | os.PathLike[str] | None = None,
) -> CompanionServer:
    host = require_bind_host(host, lan_mode=lan_mode)
    if lan_mode:
        _validate_lan_access_token(lan_access_token)
    if tls_context is not None and (tls_cert_file is not None or tls_key_file is not None):
        raise ValueError("supply either tls_context or TLS certificate/key files, not both")
    tls_context = tls_context or create_tls_context(tls_cert_file, tls_key_file)
    if not is_loopback_host(host) and tls_context is None:
        raise ValueError("non-loopback LAN control requires a trusted TLS certificate and private key")
    root = frontend_dir or Path(__file__).resolve().parents[2] / "frontend"
    active_gateway = gateway or TextGateway()
    if jawl_hostos_control:
        if active_gateway.jawl_web is None:
            raise ValueError("jawl_hostos_control requires a configured JAWL web adapter")
        jawl_base_url = getattr(active_gateway.jawl_web, "base_url", None)
        jawl_host = urlsplit(jawl_base_url).hostname if jawl_base_url else None
        if jawl_base_url and not active_gateway.jawl_web.token and jawl_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("jawl_hostos_control requires a JAWL console token")
    audit_log = AuditLog(audit_file) if audit_file else None
    active_executor = hostos_executor or HostOSExecutor(
        policy=active_gateway.policy,
        sandbox_root=Path(__file__).resolve().parents[2] / "runtime" / "sandbox",
        workspace_roots=(Path(__file__).resolve().parents[2],),
        host_roots=(Path(__file__).resolve().parents[2],),
        dry_run=True,
    )
    if audit_log:
        active_gateway.policy.audit_sink = audit_log.append
        active_executor.policy.audit_sink = audit_log.append
    plan_executor = (
        JawlNativeVisionExecutor(active_gateway.jawl_web)
        if jawl_hostos_control and active_gateway.jawl_web is not None
        else None
    )
    vision_service = VisionLookService(
        active_executor,
        describer=vision_describer,
        plan_executor=plan_executor,
    )
    event_sink = JawlEventFileSink(jawl_event_dir) if jawl_event_dir else None
    active_attention = attention or AttentionPresence(
        intent_sink=event_sink.publish if event_sink is not None else None,
        activity_provider=activity_provider,
        turn_arbiter=active_gateway.arbiter,
        summary_composer=(perception_fusion.compose if perception_fusion is not None else None),
    )

    def _perception_sink(event: dict[str, Any]) -> Any:
        # Feed the fusion store from every successful look so direct screen
        # questions always have fresh data; the attention gate below only
        # decides when the agent may be woken, not what perception remembers.
        if perception_fusion is not None and isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                perception_fusion.note("screen", str(payload.get("summary") or ""))
        return active_attention.consume(event)

    watcher = (
        ScreenDeltaWatcher(
            vision_service,
            active_gateway.arbiter,
            interval_seconds=screen_watch_interval,
            session_id="screen-sensor",
            event_sink=_perception_sink,
        )
        if screen_watch
        else None
    )
    server = CompanionServer(
        (host, port),
        root,
        active_gateway,
        active_executor,
        vision_service,
        watcher,
        voice_mem,
        tts_service,
        avatar_assets,
        active_attention,
        ambient_memory=ambient_memory,
        sensory_ingestor=sensory_ingestor,
        ambient_audio=ambient_audio,
        ambient_scheduler=ambient_scheduler,
        jawl_hostos_control=jawl_hostos_control,
        audit_log=audit_log,
        asr_service=asr_service,
        streaming_asr=streaming_asr,
        gigaam_transcriber=gigaam_transcriber,
        helper_urls=helper_urls,
        proactive_feed=proactive_feed,
        perception_fusion=perception_fusion,
        legacy_presentation=legacy_presentation,
        resource_governor=resource_governor,
        presence_file=presence_file,
        stream_chat=stream_chat,
        stream_chat_event_sink=stream_chat_event_sink or (event_sink.publish_chat if event_sink else None),
        lan_mode=lan_mode,
        lan_access_token=lan_access_token,
        lan_auth_user=lan_auth_user,
        tls_context=tls_context,
    )
    if watcher is not None:
        watcher.start()
    return server
