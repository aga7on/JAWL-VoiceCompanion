"""Run the local browser control plane."""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .gateway import TextGateway
from .ambient_audio import AmbientAudioASRBridge, AmbientAudioService
from .ambient_memory import AmbientMemoryBuffer, AmbientTriageScheduler
from .ambient_triage import OpenAICompatibleTriageProvider
from .asr import ExternalASRService, OpenAICompatibleASRClient
from .browser_adapter import BrowserAdapter
from .avatar import AvatarAssetStore
from .jawl_adapter import JawlTerminalAdapter
from .jawl_web import JawlWebChatAdapter
from .hostos_tools import HostOSExecutor
from .llm import OpenAICompatibleChatClient
from .screen_adapter import ScreenCaptureAdapter
from .tts import Qwen3TTSHttpClient, TeraTTSHttpClient, TTSService
from .vision import OpenAICompatibleVisionClient
from .voicemem_client import VoiceMemProcessClient
from .user_activity import WindowsUserActivity
from .windows_ui import WindowsUIAutomationAdapter
from .windows_pointer import WindowsPointerAdapter
from .windows_keyboard import WindowsKeyboardAdapter
from .web import create_presentation_server, create_server, is_loopback_host


def _default_frontend_dir() -> Path:
    """Find source-tree or wheel-installed frontend assets."""

    source_root = Path(__file__).resolve().parents[2] / "frontend"
    installed_root = Path(sys.prefix) / "jawl_voicecompanion" / "frontend"
    for candidate in (source_root, installed_root):
        if (candidate / "index.html").is_file() and (candidate / "avatar.html").is_file():
            return candidate
    return source_root


def _parse_redaction_rects(values: list[str]) -> tuple[tuple[int, int, int, int], ...]:
    """Parse explicit transient screen redaction rectangles."""
    rects = []
    for value in values:
        parts = [part.strip() for part in str(value).split(",")]
        if len(parts) != 4:
            raise ValueError("--screen-redact-rect must be left,top,right,bottom")
        try:
            rect = tuple(int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("--screen-redact-rect coordinates must be integers") from exc
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise ValueError("--screen-redact-rect must have positive dimensions")
        rects.append(rect)
    return tuple(rects)


def main() -> None:
    parser = argparse.ArgumentParser(description="JAWL VoiceCompanion Phase 1 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2367)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="explicitly allow private/LAN binds; remote control also requires TLS and JAWL_LAN_TOKEN",
    )
    parser.add_argument(
        "--tls-cert",
        type=Path,
        default=None,
        help="PEM certificate chain for HTTPS (required with --lan and a non-loopback host)",
    )
    parser.add_argument(
        "--tls-key",
        type=Path,
        default=None,
        help="PEM private key for HTTPS (required with --lan and a non-loopback host)",
    )
    parser.add_argument(
        "--lan-auth-token-env",
        default="JAWL_LAN_TOKEN",
        help="environment variable containing the LAN Basic-auth password; never put it in argv",
    )
    parser.add_argument(
        "--lan-auth-user",
        default="tablet",
        help="HTTP Basic-auth username for LAN control (default: tablet)",
    )
    parser.add_argument(
        "--lan-public-host",
        default=None,
        help="host/IP printed in the LAN URL when --host is 0.0.0.0 or ::",
    )
    parser.add_argument(
        "--presentation-host",
        default="127.0.0.1",
        help="loopback host for the isolated avatar/OBS presentation server",
    )
    parser.add_argument(
        "--presentation-port",
        type=int,
        default=8766,
        help="port for the isolated avatar/OBS presentation server (0 chooses a free port)",
    )
    parser.add_argument("--frontend", type=Path, default=None)
    parser.add_argument(
        "--jawl-port-file",
        type=Path,
        default=None,
        help="path to JAWL's terminal.port; omit to use the deterministic mock brain",
    )
    parser.add_argument(
        "--jawl-web-url",
        default=None,
        help="local JAWL web console URL, for example http://127.0.0.1:8770",
    )
    parser.add_argument(
        "--jawl-web-token-env",
        default="JAWL_WEB_TOKEN",
        help="environment variable containing JAWL's optional console token",
    )
    parser.add_argument(
        "--jawl-hostos-control",
        action="store_true",
        help="allow the browser to apply JAWL native HostOS levels and restart its agent",
    )
    parser.add_argument("--jawl-web-timeout", type=float, default=2.0)
    parser.add_argument("--jawl-chat-timeout", type=float, default=120.0)
    parser.add_argument(
        "--llm-url",
        default=None,
        help="optional OpenAI-compatible chat endpoint; mutually exclusive with JAWL adapters",
    )
    parser.add_argument("--llm-model", default=None, help="chat model name for --llm-url")
    parser.add_argument("--llm-api-key-env", default="LLM_API_KEY")
    parser.add_argument(
        "--llm-user-agent",
        default=None,
        help="optional HTTP User-Agent for providers with client-specific routing/rate limits",
    )
    parser.add_argument("--llm-timeout", type=float, default=120.0)
    parser.add_argument(
        "--hostos-live",
        action="store_true",
        help="enable real HostOS adapters; otherwise all tool requests are dry-run",
    )
    parser.add_argument(
        "--screen-enabled",
        action="store_true",
        help="explicitly enable focused-window snapshots for screen.observe",
    )
    parser.add_argument(
        "--screen-max-width",
        type=int,
        default=960,
        help="maximum captured screen width in pixels",
    )
    parser.add_argument(
        "--screen-max-height",
        type=int,
        default=720,
        help="maximum captured screen height in pixels",
    )
    parser.add_argument(
        "--screen-max-bytes",
        type=int,
        default=1_000_000,
        help="maximum transient JPEG size for screen.observe",
    )
    parser.add_argument(
        "--screen-ocr",
        action="store_true",
        help="enable optional transient OCR grounding; pytesseract remains optional",
    )
    parser.add_argument(
        "--screen-redact-rect",
        action="append",
        default=[],
        metavar="L,T,R,B",
        help="opaque-redact a transient screen rectangle before JPEG/VLM upload; repeatable",
    )
    parser.add_argument(
        "--screen-watch",
        action="store_true",
        help="start the explicit opt-in SCREEN_DELTA watcher",
    )
    parser.add_argument(
        "--screen-watch-interval",
        type=float,
        default=10.0,
        help="seconds between SCREEN_DELTA watcher polls",
    )
    parser.add_argument(
        "--user-activity",
        action="store_true",
        help="use low-privacy Windows idle/focus signals to suppress proactive interruptions",
    )
    parser.add_argument(
        "--user-activity-idle-seconds",
        type=float,
        default=60.0,
        help="seconds without Windows input before the user is considered idle",
    )
    parser.add_argument(
        "--jawl-event-dir",
        type=Path,
        default=None,
        help="explicit JAWL .jawl_events directory for proactive screen intents",
    )
    parser.add_argument(
        "--vision-url",
        default=None,
        help="OpenAI-compatible vision endpoint; requires --vision-model",
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="vision model name for --vision-url",
    )
    parser.add_argument(
        "--vision-api-key-env",
        default="VISION_API_KEY",
        help="environment variable containing an optional vision API key",
    )
    parser.add_argument(
        "--vision-timeout",
        type=float,
        default=30.0,
        help="vision request timeout in seconds",
    )
    parser.add_argument(
        "--voicemem-python",
        type=Path,
        default=None,
        help="Python executable for the optional VoiceMem sidecar",
    )
    parser.add_argument(
        "--voicemem-timeout",
        type=float,
        default=30.0,
        help="VoiceMem sidecar request timeout in seconds",
    )
    parser.add_argument("--voicemem-mode", default="normal")
    parser.add_argument("--voicemem-audio-rate", type=int, default=16000)
    parser.add_argument(
        "--voicemem-local-memory",
        action="store_true",
        help="use VoiceMem local E5 memory components without an LLM request",
    )
    parser.add_argument(
        "--voicemem-warmup",
        choices=("none", "text", "audio"),
        default="none",
        help="preload VoiceMem models before serving (audio may take longer)",
    )
    parser.add_argument(
        "--asr-url",
        default=None,
        help="optional OpenAI-compatible final-utterance ASR endpoint; requires --asr-model",
    )
    parser.add_argument(
        "--asr-model",
        default=None,
        help="ASR model name for --asr-url, for example Qwen3-ASR-0.6B",
    )
    parser.add_argument("--asr-api-key-env", default="ASR_API_KEY")
    parser.add_argument("--asr-timeout", type=float, default=30.0)
    parser.add_argument("--asr-max-utterance-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument(
        "--ambient-memory",
        action="store_true",
        help="enable bounded ambient evidence; capture remains stopped until enabled in the browser",
    )
    parser.add_argument(
        "--ambient-audio",
        action="store_true",
        help="configure explicit Windows system-audio loopback controls (does not start capture)",
    )
    parser.add_argument(
        "--ambient-triage-url",
        default=None,
        help="optional OpenAI-compatible delayed ambient-triage endpoint",
    )
    parser.add_argument(
        "--ambient-triage-model",
        default=None,
        help="model name for --ambient-triage-url, for example Bonsai-1.7B",
    )
    parser.add_argument("--ambient-triage-api-key-env", default="AMBIENT_TRIAGE_API_KEY")
    parser.add_argument("--ambient-triage-timeout", type=float, default=120.0)
    parser.add_argument(
        "--ambient-triage-interval",
        type=float,
        default=0.0,
        help="opt-in background triage interval in seconds; zero disables the worker",
    )
    parser.add_argument(
        "--tts-url",
        default=None,
        help="local TTS REST base URL, for example http://127.0.0.1:9889",
    )
    parser.add_argument(
        "--tts-provider",
        choices=("tera", "qwen"),
        default="tera",
        help="explicit worker contract behind --tts-url (default: tera)",
    )
    parser.add_argument("--tts-timeout", type=float, default=120.0)
    parser.add_argument("--live2d-assets", type=Path, default=None)
    parser.add_argument("--live2d-model", default="model3.json")
    parser.add_argument("--live2d-runtime", default="live2d-runtime.js")
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="metadata-only HostOS audit JSONL path (default: runtime/audit.ndjson)",
    )
    parser.add_argument("--sandbox-root", type=Path, default=None)
    parser.add_argument("--workspace-root", type=Path, action="append", default=[])
    parser.add_argument("--host-root", type=Path, action="append", default=[])
    parser.add_argument("--allowed-executable", action="append", default=[])
    args = parser.parse_args()
    if args.lan_public_host and not args.lan:
        parser.error("--lan-public-host requires --lan")
    lan_access_token = os.environ.get(args.lan_auth_token_env, "") if args.lan else None
    if args.lan and len(lan_access_token or "") < 16:
        parser.error(
            f"--lan requires {args.lan_auth_token_env} with at least 16 characters; keep it in the environment"
        )
    try:
        screen_redaction_rects = _parse_redaction_rects(args.screen_redact_rect)
    except ValueError as exc:
        parser.error(str(exc))
    responder = None
    brain_name = "phase1_mock_brain"
    jawl_web = None
    if (args.llm_url or args.llm_model) and (args.jawl_web_url or args.jawl_port_file):
        parser.error("--llm-url/--llm-model cannot be combined with a JAWL adapter")
    if args.jawl_web_url:
        try:
            jawl_web = JawlWebChatAdapter(
                args.jawl_web_url,
                token=os.environ.get(args.jawl_web_token_env, ""),
                timeout_seconds=args.jawl_web_timeout,
                chat_timeout_seconds=args.jawl_chat_timeout,
                native_gateway=True,
            )
        except ValueError as exc:
            parser.error(str(exc))
        responder = jawl_web
        brain_name = "jawl_web_chat"
    elif args.jawl_port_file:
        responder = JawlTerminalAdapter(args.jawl_port_file)
        brain_name = "jawl_terminal"
    elif args.llm_url or args.llm_model:
        if not args.llm_url or not args.llm_model:
            parser.error("--llm-url and --llm-model must be provided together")
        responder = OpenAICompatibleChatClient(
            args.llm_url,
            args.llm_model,
            api_key=os.environ.get(args.llm_api_key_env, ""),
            timeout_seconds=args.llm_timeout,
            user_agent=args.llm_user_agent,
        )
        brain_name = "openai_compatible_chat"
    if args.jawl_hostos_control and not args.jawl_web_url:
        parser.error("--jawl-hostos-control requires --jawl-web-url")
    if args.jawl_hostos_control and not os.environ.get(args.jawl_web_token_env, ""):
        host = urlsplit(args.jawl_web_url).hostname if args.jawl_web_url else None
        if host not in {"127.0.0.1", "localhost", "::1"}:
            parser.error(f"--jawl-hostos-control requires a token in {args.jawl_web_token_env} for non-loopback JAWL URLs")
    gateway = TextGateway(responder=responder, brain_name=brain_name, jawl_web=jawl_web)
    hostos_executor = None
    if args.hostos_live:
        project_root = Path(__file__).resolve().parents[2]
        hostos_executor = HostOSExecutor(
            policy=gateway.policy,
            sandbox_root=args.sandbox_root or project_root / "runtime" / "sandbox",
            workspace_roots=tuple(args.workspace_root),
            host_roots=tuple(args.host_root),
            dry_run=False,
            allowed_executables=frozenset(args.allowed_executable),
            ui_automation=WindowsUIAutomationAdapter(),
            pointer=WindowsPointerAdapter(require_fresh_token=True),
            keyboard=WindowsKeyboardAdapter(),
            screen_capture=ScreenCaptureAdapter(
                enabled=args.screen_enabled,
                max_width=args.screen_max_width,
                max_height=args.screen_max_height,
                max_bytes=args.screen_max_bytes,
                ocr_enabled=args.screen_ocr,
                redaction_rects=screen_redaction_rects,
            ),
        )
        hostos_executor.browser = BrowserAdapter(ui_automation=hostos_executor.ui_automation)
    vision_describer = None
    if args.vision_url or args.vision_model:
        if not args.vision_url or not args.vision_model:
            parser.error("--vision-url and --vision-model must be provided together")
        vision_describer = OpenAICompatibleVisionClient(
            args.vision_url,
            args.vision_model,
            api_key=os.environ.get(args.vision_api_key_env, ""),
            timeout_seconds=args.vision_timeout,
        )
    if args.screen_watch and not (args.hostos_live and args.screen_enabled and vision_describer):
        parser.error("--screen-watch requires --hostos-live, --screen-enabled, --vision-url and --vision-model")
    voicemem_args = [
        "--mode", args.voicemem_mode,
        "--audio-sample-rate", str(args.voicemem_audio_rate),
    ]
    if args.voicemem_local_memory:
        voicemem_args.append("--local-memory")
    voice_mem = (
        VoiceMemProcessClient(
            args.voicemem_python,
            args=tuple(voicemem_args),
            timeout_seconds=args.voicemem_timeout,
        )
        if args.voicemem_python
        else None
    )
    if voice_mem is not None and args.voicemem_warmup != "none":
        try:
            voice_mem.warmup(kind=args.voicemem_warmup)
        except Exception as exc:
            voice_mem.close()
            parser.error(f"VoiceMem {args.voicemem_warmup} warmup failed: {type(exc).__name__}")
    if args.asr_url or args.asr_model:
        if not args.asr_url or not args.asr_model:
            parser.error("--asr-url and --asr-model must be provided together")
        asr_service = ExternalASRService(
            OpenAICompatibleASRClient(
                args.asr_url,
                args.asr_model,
                api_key=os.environ.get(args.asr_api_key_env, ""),
                timeout_seconds=args.asr_timeout,
            ),
            max_utterance_bytes=args.asr_max_utterance_bytes,
        )
    else:
        asr_service = None
    if args.ambient_triage_url or args.ambient_triage_model:
        if not args.ambient_triage_url or not args.ambient_triage_model:
            parser.error("--ambient-triage-url and --ambient-triage-model must be provided together")
        triage_provider = OpenAICompatibleTriageProvider(
            args.ambient_triage_url,
            args.ambient_triage_model,
            api_key=os.environ.get(args.ambient_triage_api_key_env, ""),
            timeout=args.ambient_triage_timeout,
        )
    else:
        triage_provider = None
    if args.ambient_triage_interval < 0:
        parser.error("--ambient-triage-interval must be zero or positive")
    ambient_memory = AmbientMemoryBuffer(enabled=args.ambient_memory, triage_provider=triage_provider)
    ambient_scheduler = (
        AmbientTriageScheduler(ambient_memory, args.ambient_triage_interval)
        if args.ambient_triage_interval > 0 else None
    )
    if ambient_scheduler is not None:
        ambient_scheduler.start()
    ambient_audio = None
    if args.ambient_audio:
        if voice_mem is None:
            parser.error("--ambient-audio requires --voicemem-python")
        ambient_audio = AmbientAudioService(AmbientAudioASRBridge(
            voice_mem,
            ambient_memory,
            final_asr=asr_service,
        ))
    if args.tts_url:
        tts_client = Qwen3TTSHttpClient if args.tts_provider == "qwen" else TeraTTSHttpClient
        tts_service = TTSService(tts_client(args.tts_url, timeout_seconds=args.tts_timeout))
    else:
        tts_service = None
    avatar_assets = None
    if args.live2d_assets:
        try:
            avatar_assets = AvatarAssetStore(
                args.live2d_assets, model=args.live2d_model, runtime=args.live2d_runtime,
            )
        except ValueError as exc:
            parser.error(str(exc))
    server = create_server(
        args.host,
        args.port,
        args.frontend or _default_frontend_dir(),
        gateway,
        hostos_executor,
        vision_describer,
        screen_watch=args.screen_watch,
        screen_watch_interval=args.screen_watch_interval,
        voice_mem=voice_mem,
        tts_service=tts_service,
        avatar_assets=avatar_assets,
        jawl_event_dir=args.jawl_event_dir,
        ambient_memory=ambient_memory,
        ambient_audio=ambient_audio,
        ambient_scheduler=ambient_scheduler,
        asr_service=asr_service,
        activity_provider=(
            WindowsUserActivity(args.user_activity_idle_seconds).sample
            if args.user_activity else None
        ),
        jawl_hostos_control=args.jawl_hostos_control,
        audit_file=args.audit_file or Path(__file__).resolve().parents[2] / "runtime" / "audit.ndjson",
        presence_file=Path(__file__).resolve().parents[2] / "runtime" / "presence.json",
        legacy_presentation=False,
        lan_mode=args.lan,
        lan_access_token=lan_access_token,
        lan_auth_user=args.lan_auth_user,
        tls_cert_file=args.tls_cert,
        tls_key_file=args.tls_key,
    )
    presentation = None
    try:
        presentation = create_presentation_server(
            server,
            host=args.presentation_host,
            port=args.presentation_port,
            lan_mode=args.lan,
            tls_cert_file=(args.tls_cert if not is_loopback_host(args.presentation_host) else None),
            tls_key_file=(args.tls_key if not is_loopback_host(args.presentation_host) else None),
        )
        presentation_thread = threading.Thread(
            target=presentation.serve_forever,
            name="avatar-presentation",
            daemon=True,
        )
        presentation_thread.start()
        display_host = args.lan_public_host or args.host
        if display_host in {"0.0.0.0", "::"}:
            display_host = "<LAN-IP>"
        host_part = f"[{display_host}]" if ":" in display_host and not display_host.startswith("[") else display_host
        print(f"JAWL VoiceCompanion control: {server.url_scheme}://{host_part}:{server.server_port}")
        print(f"JAWL VoiceCompanion avatar/OBS: {server.presentation_url}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if presentation is not None:
            presentation.shutdown()
            presentation.server_close()
        server.server_close()


if __name__ == "__main__":
    main()
