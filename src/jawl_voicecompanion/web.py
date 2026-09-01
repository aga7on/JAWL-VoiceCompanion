"""Minimal loopback web control plane for the Phase 1 vertical slice."""

from __future__ import annotations

import json
import base64
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .approvals import ApprovalStore
from .ambient_audio import AmbientAudioDisabled, AmbientAudioService
from .ambient_memory import AmbientMemoryBuffer
from .attention import AttentionPresence
from .avatar import AvatarAssetStore
from .doctor import build_doctor_report
from .gateway import TextGateway
from .hostos_tools import HostOSExecutor
from .jawl_events import JawlEventFileSink
from .jawl_web import JawlWebUnavailable
from .models import ToolRequest
from .presence import ScreenDeltaWatcher
from .tts import TTSService, TTSUnavailable, TTSCancelled
from .vision import VisionLookService
from .voicemem_client import VoiceMemProcessClient, VoiceMemUnavailable
from .system_audio import SystemAudioUnavailable


MAX_BODY_BYTES = 64 * 1024


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
        ambient_audio: AmbientAudioService | None = None,
    ):
        self.frontend_dir = frontend_dir.resolve()
        self.gateway = gateway
        self.hostos = hostos_executor
        self.vision = vision_service
        self.screen_watcher = screen_watcher
        self.voice_mem = voice_mem
        self.tts = tts_service
        self.avatar_assets = avatar_assets
        self.attention = attention or AttentionPresence()
        self.ambient_memory = ambient_memory or AmbientMemoryBuffer()
        self.ambient_audio = ambient_audio
        self.approvals = ApprovalStore(hostos_executor)
        self.session_token = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        super().__init__(server_address, CompanionRequestHandler)

    def server_close(self) -> None:
        if self.screen_watcher is not None:
            self.screen_watcher.stop()
        if self.ambient_audio is not None:
            self.ambient_audio.stop()
        if self.voice_mem is not None:
            self.voice_mem.close()
        if self.tts is not None:
            self.tts.close()
        super().server_close()


class CompanionRequestHandler(BaseHTTPRequestHandler):
    server: CompanionServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(self.server.gateway.health())
            return
        if path == "/api/doctor":
            self._json(build_doctor_report(
                gateway=self.server.gateway,
                hostos=self.server.hostos,
                vision=self.server.vision,
                voice_mem=self.server.voice_mem,
                tts=self.server.tts,
                avatar_assets=self.server.avatar_assets,
            ))
            return
        if path == "/api/session":
            self._json({"session_token": self.server.session_token, "csrf_token": self.server.csrf_token})
            return
        if path == "/api/state":
            self._json(self.server.gateway.state())
            return
        if path == "/api/audit":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            self._json({"events": self.server.gateway.audit()})
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
        if path == "/api/ambient-memory":
            try:
                self._require_browser_session()
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            self._json({
                "state": self.server.ambient_memory.state(),
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
                self._json(self.server.ambient_audio.state())
            return
        if path == "/api/voice/status":
            if self.server.voice_mem is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            try:
                self._json({"configured": True, **self.server.voice_mem.health()})
            except VoiceMemUnavailable as exc:
                self._json({"configured": True, "status": "degraded", "reason": str(exc)})
            return
        if path == "/api/tts/status":
            if self.server.tts is None:
                self._json({"configured": False, "status": "not_configured"})
                return
            self._json(self.server.tts.health())
            return
        if path == "/api/avatar/config":
            self._json(self.server.avatar_assets.config() if self.server.avatar_assets else {
                "enabled": False, "runtime_url": None, "model_url": None, "adapter": None,
            })
            return
        if path in {"/api/jawl/status", "/api/jawl/overview", "/api/jawl/memory", "/api/jawl/persona"}:
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
                else:
                    self._json(adapter.overview())
            except JawlWebUnavailable as exc:
                self._json({"configured": True, "status": "offline", "error": str(exc)})
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
        if path in ("/", "/index.html", "/avatar", "/avatar.html"):
            filename = "avatar.html" if path in ("/avatar", "/avatar.html") else "index.html"
            index_path = self.server.frontend_dir / filename
            try:
                body = index_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "frontend is not installed")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            self._require_browser_session()
            payload = self._read_json()
            if self.path == "/api/chat":
                self._json(self.server.gateway.handle_text(payload.get("text", "")))
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
                events = self.server.voice_mem.feed_partial(text, ended=ended, session_id=session_id)
                responses = self._voice_turn_responses(events, session_id)
                self._json({
                    "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
                    "events": events,
                    "responses": responses,
                })
                return
            if self.path == "/api/voice/audio":
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
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
                session_id = str(payload.get("session_id") or self.server.session_token)[:200]
                events = self.server.voice_mem.feed_audio(
                    pcm16, sample_rate=sample_rate, session_id=session_id
                )
                responses = self._voice_turn_responses(events, session_id)
                self._json({
                    "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
                    "events": events,
                    "responses": responses,
                })
                return
            if self.path == "/api/voice/end":
                if self.server.voice_mem is None:
                    self._json({"error": "VoiceMem sidecar is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                session_id = str(payload.get("session_id") or self.server.session_token)[:200]
                events = self.server.voice_mem.end_audio(session_id=session_id)
                responses = self._voice_turn_responses(events, session_id)
                self._json({
                    "ok": not any(event.get("type") == "VOICE_DEGRADED" for event in events),
                    "events": events,
                    "responses": responses,
                })
                return
            if self.path == "/api/tts/synthesize":
                if self.server.tts is None:
                    self._json({"error": "TTS provider is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                text = payload.get("text", "")
                voice = payload.get("voice")
                speed = payload.get("speed", 1.0)
                if not isinstance(text, str) or voice is not None and not isinstance(voice, str):
                    raise ValueError("text must be string and voice must be string or null")
                if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                    raise ValueError("speed must be a number")
                audio = self.server.tts.synthesize(text, voice=voice, speed=float(speed))
                self._audio(audio)
                return
            if self.path == "/api/hostos/execute":
                raw_request = payload.get("request", payload)
                if not isinstance(raw_request, dict):
                    raise ValueError("request must be an object")
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
            parts = urlsplit(self.path)
            prefix = "/api/hostos/approvals/"
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
                state = self.server.gateway.policy.set_access_level(payload["level"], actor="browser")
                self._json({"ok": True, "policy": state})
                return
            if self.path == "/api/emergency-stop":
                state = self.server.gateway.policy.set_emergency_stop(True, actor="browser")
                self._json({"ok": True, "policy": state})
                return
            if self.path == "/api/attention":
                values = {key: payload[key] for key in ("dnd", "min_significance", "cooldown_seconds", "budget_per_hour") if key in payload}
                if not values:
                    raise ValueError("attention settings are required")
                self._json({"ok": True, "attention": self.server.attention.configure(**values)})
                return
            if self.path == "/api/ambient-memory/triage":
                self._json(self.server.ambient_memory.triage())
                return
            if self.path == "/api/ambient-memory/clear":
                self._json(self.server.ambient_memory.clear())
                return
            if self.path == "/api/ambient-memory/config":
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
            self.send_error(HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
        except VoiceMemUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except AmbientAudioDisabled as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except SystemAudioUnavailable as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except TTSCancelled:
            self._json({"error": "speech request was superseded"}, status=HTTPStatus.CONFLICT)
        except TTSUnavailable as exc:
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

    def _require_browser_session(self) -> None:
        if self.headers.get("X-Companion-Session") != self.server.session_token:
            raise PermissionError("valid local session is required")
        if self.headers.get("X-Companion-CSRF") != self.server.csrf_token:
            raise PermissionError("valid CSRF token is required")
        origin = self.headers.get("Origin")
        if origin:
            allowed = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if origin not in allowed:
                raise PermissionError("request origin is not allowed")

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _voice_turn_responses(self, events: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
        responses = []
        for event in events:
            if event.get("type") != "VOICE_TURN":
                continue
            turn_text = event.get("payload", {}).get("text", "")
            responses.append(self.server.gateway.handle_text(turn_text, session_id=session_id))
        return responses


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
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
    ambient_memory: AmbientMemoryBuffer | None = None,
    ambient_audio: AmbientAudioService | None = None,
) -> CompanionServer:
    root = frontend_dir or Path(__file__).resolve().parents[2] / "frontend"
    active_gateway = gateway or TextGateway()
    active_executor = hostos_executor or HostOSExecutor(
        policy=active_gateway.policy,
        sandbox_root=Path(__file__).resolve().parents[2] / "runtime" / "sandbox",
        workspace_roots=(Path(__file__).resolve().parents[2],),
        host_roots=(Path(__file__).resolve().parents[2],),
        dry_run=True,
    )
    vision_service = VisionLookService(active_executor, describer=vision_describer)
    event_sink = JawlEventFileSink(jawl_event_dir) if jawl_event_dir else None
    active_attention = attention or AttentionPresence(
        intent_sink=event_sink.publish if event_sink is not None else None,
    )
    watcher = (
        ScreenDeltaWatcher(
            vision_service,
            active_gateway.arbiter,
            interval_seconds=screen_watch_interval,
            session_id="screen-sensor",
            event_sink=active_attention.consume,
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
        ambient_audio=ambient_audio,
    )
    if watcher is not None:
        watcher.start()
    return server
